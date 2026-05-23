# src/tasks.py
"""
Tareas asíncronas con Celery para procesamiento de videos:
- Extracción y chunking de audio
- Transcripción con Gemini (con rotación de keys y manejo de límites)
- Generación de resúmenes
"""
import os
import logging
from datetime import datetime, timezone
from celery import Celery
from sqlalchemy.orm import Session

from src.database import SessionLocal, engine
from src.models import Video, Chunk, Transcription, Summary, VideoStatus, ChunkStatus
from src.config import settings
from src.services.audio import extract_audio, split_audio_with_overlap, cleanup_video_files
from src.services.gemini_router import GeminiKeyRouter
from src.schemas.gemini import GeminiChunkResponse  # Lo crearemos después

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Configurar Celery
celery_app = Celery(
    "vidtranscribe",
    broker=settings.effective_redis_url,
    backend=settings.effective_redis_url.replace("redis://", "rpc://")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,  # 30 minutos máximo por tarea
    task_soft_time_limit=1500,  # 25 minutos soft limit
)

@celery_app.task(bind=True, max_retries=8, default_retry_delay=30)
def process_video_upload(self, video_id: str, video_path: str, title: str):
    """
    Tarea principal: procesa un video subido desde extracción hasta transcripción completa.
    
    Flujo:
    1. Extraer audio del video
    2. Dividir audio en chunks con solape
    3. Registrar chunks en BD
    4. Encolar transcripción de cada chunk
    5. Generar resumen al finalizar
    """
    db: Session = SessionLocal()
    router = GeminiKeyRouter()
    
    try:
        # 1. Actualizar estado del video
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video {video_id} not found")
        
        video.status = VideoStatus.procesando
        db.commit()
        
        # 2. Crear directorio de trabajo
        work_dir = os.path.join(settings.upload_dir, title)
        os.makedirs(work_dir, exist_ok=True)
        
        # 3. Extraer audio
        logger.info(f"[{title}] Extracting audio...")
        audio_path = extract_audio(video_path, work_dir)
        video.status = VideoStatus.cargada
        db.commit()
        
        # 4. Dividir en chunks
        logger.info(f"[{title}] Splitting audio into chunks...")
        chunks_meta = split_audio_with_overlap(
            audio_path=audio_path,
            output_dir=os.path.join(work_dir, "chunks"),
            chunk_duration=settings.chunk_duration_sec,
            overlap=settings.chunk_overlap_sec
        )
        
        # 5. Registrar chunks en BD
        logger.info(f"[{title}] Registering {len(chunks_meta)} chunks in DB...")
        for meta in chunks_meta:
            chunk = Chunk(
                video_id=video_id,
                index=meta.index,
                start_sec=meta.start_sec,
                end_sec=meta.end_sec,
                file_path=meta.file_path,
                status=ChunkStatus.pendiente
            )
            db.add(chunk)
        db.commit()
        
        # 6. Encolar transcripción de cada chunk (en paralelo)
        logger.info(f"[{title}] Queueing transcription tasks...")
        for meta in chunks_meta:
            transcribe_chunk.delay(
                chunk_id=str([c.id for c in video.chunks if c.index == meta.index][0]),
                chunk_path=meta.file_path,
                title=title
            )
        
        # 7. Actualizar estado a "transcribiendo"
        video.status = VideoStatus.transcribiendo
        db.commit()
        
        logger.info(f"[{title}] Video processing queued successfully")
        return {"status": "queued", "chunks": len(chunks_meta)}
        
    except Exception as e:
        logger.error(f"[{title}] Error in process_video_upload: {e}", exc_info=True)
        if video:
            video.status = VideoStatus.error
            db.commit()
        raise self.retry(exc=e, countdown=60)
        
    finally:
        db.close()
        # Limpieza opcional: eliminar video original, conservar audio y chunks
        cleanup_video_files(video_path, audio_path, os.path.join(work_dir, "chunks"), keep_audio=True)


@celery_app.task(bind=True, max_retries=12, default_retry_delay=15)
def transcribe_chunk(self, chunk_id: str, chunk_path: str, title: str):
    """
    Transcribe un chunk de audio usando Gemini con rotación de keys y manejo de límites.
    """
    db: Session = SessionLocal()
    router = GeminiKeyRouter()
    
    try:
        chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
        
        chunk.status = ChunkStatus.transcribiendo
        db.commit()
        
        # 1. Obtener una API key disponible
        key_idx, api_key = router.get_available_key()
        if api_key is None:
            # Todas las keys agotadas: reencolar con backoff hasta reset de cuota
            logger.warning(f"[{title}] All API keys exhausted. Retrying in 2 min...")
            raise self.retry(countdown=120, exc=Exception("ALL_KEYS_EXHAUSTED"))
        
        # 2. Preparar llamada a Gemini
        client = router.get_gemini_client(api_key)
        
        # Leer audio chunk
        with open(chunk_path, "rb") as f:
            audio_bytes = f.read()
        
        # Prompt estructurado para JSON mode
        prompt = """
Transcribe literalmente el siguiente fragmento de audio de máximo 2.5 minutos.
Responde ÚNICAMENTE en JSON válido siguiendo este esquema exacto:

{
  "transcription": "texto literal transcrito. Usa [cruce voces], [inentendible] o [Ruido de fondo] si aplica.",
  "speaker": "infiere quién habla: 'Narrador principal', 'Estudiante', 'Desconocido', etc.",
  "sentiment": "positivo | negativo | neutro",
  "tone": "autoridad | inseguridad | conversacional | didáctico | otro",
  "confidence": 0.0 a 1.0 (qué tan seguro estás de la transcripción)
}

No añadas explicaciones, markdown, ni texto fuera del JSON.
""".strip()
        
        # 3. Llamar a Gemini con JSON mode
        response = client.models.generate_content(
            model=router.model_name,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/mpeg"),
                types.Part.from_text(text=prompt)
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiChunkResponse.model_json_schema()
            )
        )
        
        # 4. Parsear respuesta
        result = router.parse_gemini_response(response.text)
        
        # 5. Validar y guardar transcripción
        transcription = Transcription(
            chunk_id=chunk_id,
            text=result["transcription"],
            speaker=result.get("speaker", "Desconocido"),
            sentiment=result["sentiment"],
            tone=result["tone"],
            confidence=result.get("confidence")
        )
        db.add(transcription)
        
        # 6. Actualizar estado del chunk
        chunk.status = ChunkStatus.transcrita
        db.commit()
        
        # 7. Registrar uso de la key (SOLO si fue exitoso)
        router.record_usage(key_idx)
        logger.info(f"[{title}] Chunk {chunk.index} transcribed with key #{key_idx}")
        
        # 8. Verificar si todos los chunks del video están listos → generar resumen
        _check_and_generate_summary.delay(video_id=str(chunk.video_id), title=title)
        
        return {"status": "success", "chunk_index": chunk.index}
        
    except Exception as e:
        error_str = str(e).upper()
        
        # Manejo específico de errores de cuota de Gemini
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "RATE_LIMIT" in error_str:
            logger.warning(f"[{title}] Key #{key_idx if 'key_idx' in locals() else '?'} hit 429. Retrying with backoff...")
            # Forzar bloqueo de esta key incrementando su contador
            if 'key_idx' in locals() and key_idx is not None:
                router.record_usage(key_idx)
            return self.retry(countdown=2 ** min(self.request.retries, 6) * 10)  # Backoff exponencial: 20s, 40s, 80s...
        
        # Otros errores: reintento genérico
        logger.error(f"[{title}] Error transcribing chunk {chunk_id}: {e}", exc_info=True)
        if chunk:
            chunk.status = ChunkStatus.error
            chunk.error_reason = str(e)[:200]
            db.commit()
        return self.retry(countdown=30, exc=e)
        
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def _check_and_generate_summary(self, video_id: str, title: str):
    """
    Verifica si todos los chunks de un video están transcritos y, si es así,
    genera y guarda el resumen estructurado.
    """
    db: Session = SessionLocal()
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return
        
        # Verificar si todos los chunks están transcritos
        total_chunks = len(video.chunks)
        transcribed_chunks = sum(1 for c in video.chunks if c.status == ChunkStatus.transcrita)
        
        if transcribed_chunks < total_chunks:
            # Aún no están todos: reencolar para verificar después
            return self.retry(countdown=30)
        
        # Verificar si ya existe resumen (idempotencia)
        if video.summary:
            video.status = VideoStatus.transcrita
            db.commit()
            return
        
        # 1. Recopilar todas las transcripciones ordenadas
        transcriptions = [
            f"[{c.start_sec:.1f}s] {c.transcription.text}"
            for c in sorted(video.chunks, key=lambda x: x.index)
            if c.transcription
        ]
        full_text = "\n".join(transcriptions)
        
        # 2. Generar resumen con Gemini (usar una key disponible)
        router = GeminiKeyRouter()
        key_idx, api_key = router.get_available_key()
        if not api_key:
            return self.retry(countdown=120)
        
        client = router.get_gemini_client(api_key)
        summary_prompt = f"""
Eres un asistente académico experto. Genera un resumen estructurado y bien formateado de la siguiente transcripción de clase universitaria.

Formato requerido (Markdown):
# Resumen: {title}

## 📋 Puntos Clave
- [Punto 1]
- [Punto 2]
- ...

## 🎯 Conclusiones Principales
[2-3 conclusiones fundamentales]

## ❓ Preguntas para Reflexión
- [Pregunta 1]
- [Pregunta 2]

## 🔍 Términos Importantes
- **Término**: definición breve

Transcripción completa:
{full_text[:100000]}  # Límite de seguridad de tokens
""".strip()
        
        # ✅ DESPUÉS (usa text/plain, que SÍ es válido):
        response = client.models.generate_content(
            model=router.model_name,
            contents=[summary_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="text/plain"
            )
        )
        
        # 3. Guardar resumen en BD
        summary = Summary(
            video_id=video_id,
            content=response.text.strip()
        )
        db.add(summary)
        
        # 4. Actualizar estado final del video
        video.status = VideoStatus.transcrita
        db.commit()
        
        # 5. Registrar uso de key
        router.record_usage(key_idx)
        logger.info(f"[{title}] Summary generated successfully")
        
        return {"status": "summary_generated"}
        
    except Exception as e:
        logger.error(f"[{title}] Error generating summary: {e}", exc_info=True)
        return self.retry(exc=e)
        
    finally:
        db.close()