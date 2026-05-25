# src/routers/transcriptions.py
"""
Router para gestión de transcripciones: listado, búsqueda full-text, 
transcripción completa con sincronización y resúmenes.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_, text, case
from pydantic import BaseModel, Field
import re
from fastapi.responses import Response
from src.services.export_service import generate_pdf, generate_word

from src.database import get_db
from src.models import Video, Chunk, Transcription, Summary, VideoStatus, ChunkStatus
from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# MODELOS DE RESPUESTA (Pydantic)
# =============================================================================

class ChunkResponse(BaseModel):
    """Respuesta para un fragmento transcrito con metadata de sincronización."""
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    original_start: str  # HH:MM:SS.mmm
    original_end: str
    file_path: str
    text: str
    speaker: str
    sentiment: str
    tone: str
    confidence: Optional[float] = None
    
    class Config:
        from_attributes = True


class TranscriptionListResponse(BaseModel):
    """Respuesta paginada para listado de transcripciones."""
    video_id: str
    title: str
    status: str
    duration_sec: float
    chunk_count: int
    transcribed_count: int
    created_at: str
    
    class Config:
        from_attributes = True


class FullTranscriptionResponse(BaseModel):
    """Respuesta completa para transcripción con sincronización."""
    video_id: str
    title: str
    duration_sec: float
    status: str
    audio_url: Optional[str] = None
    chunks: List[ChunkResponse]
    
    class Config:
        from_attributes = True


class SummaryResponse(BaseModel):
    """Respuesta para resumen estructurado."""
    video_id: str
    title: str
    content: str  # Markdown estructurado
    created_at: str
    
    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    """Respuesta para búsqueda full-text con relevancia."""
    video_id: str
    title: str
    chunk_index: int
    start_sec: float
    original_timestamp: str  # HH:MM:SS.mmm
    text: str
    speaker: str
    sentiment: str
    tone: str
    confidence: Optional[float] = None
    rank: float  # Relevancia de la búsqueda (ts_rank)
    
    class Config:
        from_attributes = True


class ListTranscriptionsQuery(BaseModel):
    """Parámetros de consulta para listado con filtros."""
    status: Optional[VideoStatus] = None
    q: Optional[str] = Field(None, min_length=1, max_length=100, description="Búsqueda por título")
    page: int = Field(1, ge=1, description="Página (1-based)")
    size: int = Field(5, ge=1, le=15, description="Registros por página (1-15)")
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

class SearchRequest(BaseModel):
    """Request body para búsqueda full-text."""
    q: str = Field(..., min_length=1, max_length=100, description="Término o frase a buscar")
    limit: int = Field(default=20, ge=1, le=100, description="Máximo resultados a devolver (1-100)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "q": "célula mitocondria",
                "limit": 10
            }
        }
        
# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/", response_model=List[TranscriptionListResponse], tags=["Transcriptions"])
def list_transcriptions(
    query: ListTranscriptionsQuery = Depends(),
    db: Session = Depends(get_db)
):
    """
    Lista transcripciones con filtros y paginación.
    
    Filtros disponibles:
    - status: cargando|cargada|procesando|transcribiendo|transcrita|error
    - q: búsqueda por título (case-insensitive)
    
    Paginación:
    - page: número de página (default: 1)
    - size: registros por página (1-15, default: 5)
    """
    # Construir query base
    stmt = db.query(
        Video.id,
        Video.title,
        Video.status,
        Video.duration_sec,
        Video.created_at,
        func.count(Chunk.id).label('chunk_count'),
        func.sum(
            case((Chunk.status == ChunkStatus.transcrita, 1), else_=0)
        ).label('transcribed_count')
    ).outerjoin(Chunk, Video.id == Chunk.video_id).group_by(Video.id)
    
    # Aplicar filtros
    if query.status:
        stmt = stmt.filter(Video.status == query.status)
    
    if query.q:
        stmt = stmt.filter(Video.title.ilike(f"%{query.q}%"))
    
    # Aplicar paginación
    stmt = stmt.order_by(Video.created_at.desc()).offset(query.offset).limit(query.size)
    
    # Ejecutar y formatear respuesta
    results = stmt.all()
    
    return [
        TranscriptionListResponse(
            video_id=str(r.id),
            title=r.title,
            status=r.status.value,
            duration_sec=r.duration_sec,
            chunk_count=r.chunk_count or 0,
            transcribed_count=r.transcribed_count or 0,
            created_at=r.created_at.isoformat()
        )
        for r in results
    ]


@router.get("/{video_id}/full", response_model=FullTranscriptionResponse, tags=["Transcriptions"])
def get_full_transcription(
    video_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Obtiene la transcripción completa de un video con metadata para sincronización.
    
    Ideal para frontend: cada chunk incluye timestamps exactos para "ir al momento".
    
    Metadata de sincronización:
    - start_sec / end_sec: segundos desde el inicio del audio (float)
    - original_start / original_end: formato legible HH:MM:SS.mmm
    - file_path: ruta al archivo de audio del chunk (para streaming opcional)
    
    Uso en frontend:
    ```js
    // Al hacer clic en un chunk:
    audioElement.currentTime = chunk.start_sec;  // Salta al momento exacto
    ```
    """
    # Buscar video con chunks y transcripciones
    video = db.query(Video).options(
        joinedload(Video.chunks).joinedload(Chunk.transcription)
    ).filter(Video.id == video_id).first()
    
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    # Construir audio_url solo si el video está transcrito y tiene audio procesado
    audio_url = None
    if video.status == VideoStatus.transcrita:
        # Construir URL absoluta usando la base del request
        base_url = str(request.base_url).rstrip('/')
        audio_url = f"{base_url}/api/v1/videos/{video_id}/stream"
        
    # Ordenar chunks por índice y filtrar los que tienen transcripción
    chunks_with_transcription = [
        ChunkResponse(
            index=c.index,
            start_sec=c.start_sec,
            end_sec=c.end_sec,
            duration_sec=c.end_sec - c.start_sec,
            original_start=_format_timestamp(c.start_sec),
            original_end=_format_timestamp(c.end_sec),
            file_path=c.file_path,
            text=c.transcription.text if c.transcription else "",
            speaker=c.transcription.speaker if c.transcription else "Desconocido",
            sentiment=c.transcription.sentiment if c.transcription else "neutro",
            tone=c.transcription.tone if c.transcription else "otro",
            confidence=c.transcription.confidence if c.transcription else None
        )
        for c in sorted(video.chunks, key=lambda x: x.index)
        if c.transcription  # Solo chunks ya transcritos
    ]
    
    return FullTranscriptionResponse(
        video_id=str(video.id),
        title=video.title,
        duration_sec=video.duration_sec,
        status=video.status.value,
        audio_url=audio_url,  # ← Incluir el nuevo campo
        chunks=chunks_with_transcription
    )


@router.get("/{video_id}/summary", response_model=SummaryResponse, tags=["Transcriptions"])
def get_summary(
    video_id: str,
    db: Session = Depends(get_db)
):
    """
    Obtiene el resumen estructurado generado automáticamente.
    
    El resumen se genera cuando todos los chunks están transcritos.
    Formato: Markdown con secciones para puntos clave, conclusiones, etc.
    """
    video = db.query(Video).options(
        joinedload(Video.summary)
    ).filter(Video.id == video_id).first()
    
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    if not video.summary:
        # Si aún no hay resumen, verificar si ya terminó el procesamiento
        if video.status == VideoStatus.transcrita:
            # Forzar regeneración del resumen (opcional)
            from src.tasks import _check_and_generate_summary
            _check_and_generate_summary.delay(video_id=str(video.id), title=video.title)
            raise HTTPException(
                status_code=202,
                detail="Resumen en generación. Intenta en unos segundos."
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Resumen no disponible. Estado actual: {video.status.value}"
            )
    
    return SummaryResponse(
        video_id=str(video.id),
        title=video.title,
        content=video.summary.content,
        created_at=video.summary.created_at.isoformat()
    )


@router.post("/{video_id}/search", response_model=List[SearchResponse], tags=["Transcriptions"])
def search_in_transcription(
    video_id: str,
    search_request: SearchRequest = Body(..., description="Parámetros de búsqueda en JSON"),
    db: Session = Depends(get_db)
):
    """
    Búsqueda full-text dentro de la transcripción de un video específico.
    
    🔹 Request Body (JSON):
    ```json
    {
        "q": "término a buscar",
        "limit": 20
    }
    ```
    
    🔹 Parámetros:
    - q: Término o frase a buscar (case-insensitive, soporta múltiples palabras)
    - limit: Máximo resultados (1-100, default: 20)
    
    🔹 Respuesta incluye:
    - rank: Relevancia de la coincidencia (mayor = más relevante)
    - original_timestamp: Momento exacto en el video (HH:MM:SS.mmm)
    - start_sec: Segundos desde el inicio (para sincronización con audio)
    
    🔹 Ejemplo de uso frontend:
    ```js
    // Al hacer clic en un resultado de búsqueda:
    audioElement.currentTime = result.start_sec;  // Salta al momento exacto
    highlightText(result.text, searchRequest.q);   // Resalta el término
    ```
    
    🔹 Ejemplo de request:
    ```bash
    curl -X POST http://localhost:8000/api/v1/transcriptions/{id}/search \
      -H "Content-Type: application/json" \
      -d '{"q": "célula", "limit": 10}'
    ```
    """
    # -------------------------------------------------------------------------
    # 1. Buscar el video primero
    # -------------------------------------------------------------------------
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    
    # -------------------------------------------------------------------------
    # 2. ✅ CORRECCIÓN CRÍTICA: Búsqueda full-text con PostgreSQL tsvector
    # -------------------------------------------------------------------------
    # Usamos plainto_tsquery que maneja automáticamente la tokenización
    # y es compatible con la configuración 'spanish' de PostgreSQL
    search_query = func.plainto_tsquery('spanish', search_request.q)
    
    # -------------------------------------------------------------------------
    # 3. Query con ts_rank para ordenar por relevancia
    # -------------------------------------------------------------------------
    stmt = db.query(
        Chunk.index,
        Chunk.start_sec,
        Chunk.end_sec,
        Transcription.text,
        Transcription.speaker,
        Transcription.sentiment,
        Transcription.tone,
        Transcription.confidence,
        func.ts_rank(Video.search_vector, search_query).label('rank')
    ).join(Transcription, Chunk.id == Transcription.chunk_id).join(
        Video, Chunk.video_id == Video.id
    ).filter(
        and_(
            Video.id == video_id,
            Video.search_vector.op('@@')(search_query)  # Operador de coincidencia full-text
        )
    ).order_by(
        func.ts_rank(Video.search_vector, search_query).desc(),  # Más relevante primero
        Chunk.start_sec.asc()  # Luego por orden cronológico
    ).limit(search_request.limit)
    
    results = stmt.all()
    
    # -------------------------------------------------------------------------
    # 4. Formatear y retornar respuesta
    # -------------------------------------------------------------------------
    return [
        SearchResponse(
            video_id=video_id,
            title=video.title,
            chunk_index=r.index,
            start_sec=r.start_sec,
            original_timestamp=_format_timestamp(r.start_sec),
            text=r.text,
            speaker=r.speaker,
            sentiment=r.sentiment,
            tone=r.tone,
            confidence=r.confidence,
            rank=float(r.rank)
        )
        for r in results
    ]


@router.get("/{video_id}/download/summary", tags=["Transcriptions"])
def download_summary(
    video_id: str,
    format: str = Query("markdown", regex="^(markdown|txt|json|pdf|word)$"),
    db: Session = Depends(get_db)
):
    """
    Descarga el resumen en diferentes formatos.
    
    Formatos soportados:
    - markdown: (default) Resumen estructurado con #, ##, -, etc.
    - txt: Texto plano sin formato
    - json: Resumen como objeto JSON estructurado
    - pdf: Documento PDF con estilo académico
    - word: Documento Microsoft Word (.docx)
    
    Uso:
    GET /api/v1/transcriptions/{video_id}/download/summary?format=pdf
    """
    
    video = db.query(Video).options(
        joinedload(Video.summary)
    ).filter(Video.id == video_id).first()
    
    if not video or not video.summary:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")
    
    content = video.summary.content
    safe_title = re.sub(r'[^\w\s-]', '', video.title).strip().replace(' ', '_')
    
    # PDF
    if format == "pdf":
        pdf_bytes = generate_pdf(content, video.title)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="Resumen_{safe_title}.pdf"',
                "Content-Length": str(len(pdf_bytes))
            }
        )
    
    # Word
    elif format == "word":
        word_bytes = generate_word(content, video.title)
        return Response(
            content=word_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="Resumen_{safe_title}.docx"',
                "Content-Length": str(len(word_bytes))
            }
        )
    
    # TXT
    elif format == "txt":
        plain = re.sub(r'^#{1,6}\s*', '', content, flags=re.MULTILINE)
        plain = re.sub(r'^-\s*', '• ', plain, flags=re.MULTILINE)
        plain = re.sub(r'\*\*(.*?)\*\*', r'\1', plain)
        return {"content": plain, "format": "txt"}
    
    # JSON
    elif format == "json":
        sections = {}
        current_section = "intro"
        for line in content.split('\n'):
            if line.startswith('## '):
                current_section = line[3:].strip().lower().replace(' ', '_')
                sections[current_section] = []
            elif line.startswith('- ') and current_section in sections:
                sections[current_section].append(line[2:].strip())
            elif line.strip() and current_section in sections:
                sections[current_section].append(line.strip())
        return {"content": sections, "format": "json"}
    
    # Markdown (default)
    else:
        return {"content": content, "format": "markdown"}


# =============================================================================
# UTILIDADES
# =============================================================================

def _format_timestamp(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS.mmm legible."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"