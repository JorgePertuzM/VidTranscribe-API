# src/routers/videos.py
"""
Router para gestión de videos: upload, validación, polling de estado.
"""
import os
import uuid
import shutil
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from src.database import get_db
from src.models import Video, Chunk, VideoStatus, ChunkStatus
from src.config import settings
from src.tasks import process_video_upload

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# MODELOS DE RESPUESTA (Pydantic)
# =============================================================================

class VideoUploadResponse(BaseModel):
    """Respuesta exitosa de upload (202 Accepted)."""
    video_id: uuid.UUID
    title: str
    status: str
    message: str


class VideoStatusResponse(BaseModel):
    """Respuesta de polling de estado."""
    video_id: uuid.UUID
    title: str
    status: str
    progress: str | None = None
    error_reason: str | None = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/upload", response_model=VideoUploadResponse, status_code=202)
async def upload_video(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=3, max_length=100),
    db: Session = Depends(get_db)
):
    """
    Sube un video para procesamiento asíncrono.
    
    Valida:
    - Formato de archivo (mp4, mkv, avi, mov, webm)
    - Tamaño máximo (configurable en .env)
    - Duración máxima (configurable en .env) ← ✅ AHORA usa ruta guardada
    - Título único
    
    Retorna 202 Accepted con video_id para polling de estado.
    """
    # -------------------------------------------------------------------------
    # 1. Validar extensión del archivo
    # -------------------------------------------------------------------------
    allowed_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado. Permitidos: {', '.join(allowed_extensions)}"
        )
    
    # -------------------------------------------------------------------------
    # 2. Validar tamaño (leer sin cargar todo en memoria)
    # -------------------------------------------------------------------------
    file.file.seek(0, os.SEEK_END)
    file_size_bytes = file.file.tell()
    file_size_mb = file_size_bytes / (1024 * 1024)
    file.file.seek(0)  # Resetear pointer
    
    if file_size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo muy grande: {file_size_mb:.1f}MB > límite de {settings.max_file_size_mb}MB"
        )
    
    # -------------------------------------------------------------------------
    # 3. ✅ CORRECCIÓN CRÍTICA: Guardar archivo PRIMERO, luego validar duración
    # -------------------------------------------------------------------------
    video_id = uuid.uuid4()
    temp_dir = Path(settings.upload_dir) / f"temp_{video_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    video_path = temp_dir / file.filename
    
    # Guardar archivo en disco (chunked para no saturar memoria)
    try:
        with open(video_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
    except Exception as e:
        # Limpieza si falla la escritura
        if video_path.exists():
            video_path.unlink()
        raise HTTPException(status_code=500, detail=f"Error guardando archivo: {str(e)}")
    
    # -------------------------------------------------------------------------
    # 4. Validar duración con ffprobe (AHORA usa la ruta del archivo guardado)
    # -------------------------------------------------------------------------
    duration_sec = 0.0
    try:
        import ffmpeg
        # ✅ CORRECCIÓN: Pasar str(video_path) en lugar de file.file
        probe = ffmpeg.probe(
            str(video_path),
            cmd='ffprobe',
            select_streams='v',
            show_entries='format=duration'
        )
        duration_sec = float(probe['format']['duration'])
        duration_min = duration_sec / 60
        
        if duration_min > settings.max_duration_min:
            # Limpieza si no cumple límites
            video_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Video muy largo: {duration_min:.1f}min > límite de {settings.max_duration_min}min"
            )
    except ffmpeg.Error as e:
        # Si ffprobe falla, continuar sin validación de duración (menos estricto)
        logger.warning(f"Could not probe video duration for {video_path}: {e}")
        # No eliminamos el archivo: dejamos que el procesamiento intente extraer audio
    except Exception as e:
        # Otros errores de ffprobe: log y continuar
        logger.warning(f"Unexpected error probing video: {e}")
    
    # -------------------------------------------------------------------------
    # 5. Verificar unicidad del título
    # -------------------------------------------------------------------------
    existing = db.query(Video).filter(Video.title == title).first()
    if existing:
        # Limpieza si el título ya existe
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una transcripción con el título '{title}'. Usa un título único."
        )
    
    # -------------------------------------------------------------------------
    # 6. Registrar en BD
    # -------------------------------------------------------------------------
    video = Video(
        id=video_id,
        title=title,
        duration_sec=duration_sec,
        status=VideoStatus.cargando
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    
    # -------------------------------------------------------------------------
    # 7. Encolar tarea de procesamiento (background)
    # -------------------------------------------------------------------------
    try:
        process_video_upload.delay(
            video_id=str(video_id),
            video_path=str(video_path),
            title=title
        )
        logger.info(f"Video {video_id} queued for processing")
    except Exception as e:
        logger.error(f"Failed to queue task for video {video_id}: {e}")
        # Revertir: eliminar archivo y registro en BD
        video_path.unlink(missing_ok=True)
        db.delete(video)
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue processing task")
    
    # -------------------------------------------------------------------------
    # 8. Respuesta exitosa
    # -------------------------------------------------------------------------
    return VideoUploadResponse(
        video_id=video_id,
        title=title,
        status=video.status.value,
        message="Video recibido. Procesamiento en curso. Usa GET /status/{video_id} para verificar progreso."
    )


@router.get("/status/{video_id}", response_model=VideoStatusResponse)
def get_video_status(video_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Obtiene el estado actual de procesamiento de un video.
    Ideal para polling desde el frontend cada 3-5 segundos.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    # Calcular progreso si está en proceso
    progress = None
    if video.status in [VideoStatus.procesando, VideoStatus.transcribiendo]:
        total = len(video.chunks)
        done = sum(1 for c in video.chunks if c.status == ChunkStatus.transcrita)
        progress = f"{done}/{total} chunks" if total > 0 else "Iniciando..."
    
    # Obtener razón de error si aplica
    error_reason = None
    if video.status == VideoStatus.error:
        # Buscar el primer chunk con error para dar contexto
        failed_chunk = next((c for c in video.chunks if c.error_reason), None)
        error_reason = failed_chunk.error_reason if failed_chunk else "Error desconocido en procesamiento"
    
    return VideoStatusResponse(
        video_id=video.id,
        title=video.title,
        status=video.status.value,
        progress=progress,
        error_reason=error_reason
    )


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Elimina un video y todos sus datos asociados (chunks, transcripciones, resumen).
    Cascada manejada por SQLAlchemy relationships.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    # Eliminar archivos del sistema de archivos
    # 1. Carpeta temporal del upload (si existe)
    temp_dir = Path(settings.upload_dir) / f"temp_{video_id}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    # 2. Carpeta de trabajo por título (si existe)
    work_dir = Path(settings.upload_dir) / video.title
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    
    # Eliminar registro de BD (cascada elimina chunks, transcriptions, summary)
    db.delete(video)
    db.commit()
    
    return None  # 204 No Content