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
from src.schemas.gemini import GeminiChunkResponse
from src.prompts import prompt_manager  # ✅ NUEVA IMPORTACIÓN

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
    task_time_limit=1800,
    task_soft_time_limit=1500,
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_video_upload(self, video_id: str, video_path: str, title: str):
    """
    Tarea principal: procesa un video subido desde extracción hasta transcripción completa.
    """
    db: Session = SessionLocal()
    
    audio_path: str | None = None
    work_dir: str | None = None
    video = None
    chunks_dir: str | None = None
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video {video_id} not found in database")
        
        video.status = VideoStatus.procesando
        db.commit()
        
        if not os.path.isfile(video_path):
            error_msg = f"Video file NOT FOUND: {video_path}"
            logger.error(f"[{title}] {error_msg}")
            video.status = VideoStatus.error
            video.error_reason = error_msg[:200]
            db.commit()
            raise FileNotFoundError(error_msg)
        
        logger.info(f"[{title}] File verified: {video_path} (size: {os.path.getsize(video_path)} bytes)")
        
        work_dir = os.path.join(settings.upload_dir, f"temp_{video_id}")
        os.makedirs(work_dir, exist_ok=True)
        chunks_dir = os.path.join(work_dir, "chunks")
        os.makedirs(chunks_dir, exist_ok=True)
        
        logger.info(f"[{title}] Extracting audio...")
        try:
            audio_path = extract_audio(video_path, work_dir)
            if not audio_path or not os.path.isfile(audio_path):
                raise RuntimeError(f"extract_audio returned invalid path: {audio_path}")
            logger.info(f"[{title}] Audio extracted: {audio_path}")
            
            video.audio_path = audio_path
            db.commit()
            
        except Exception as e:
            logger.error(f"[{title}] FFmpeg extraction failed: {e}")
            video.status = VideoStatus.error
            video.error_reason = f"Audio extraction failed: {str(e)[:150]}"
            db.commit()
            raise

        video.status = VideoStatus.cargada
        db.commit()
        
        logger.info(f"[{title}] Splitting audio into chunks...")
        chunks_meta = split_audio_with_overlap(
            audio_path=audio_path,
            output_dir=chunks_dir,
            chunk_duration=settings.chunk_duration_sec,
            overlap=settings.chunk_overlap_sec
        )
        
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
        
        logger.info(f"[{title}] Queueing transcription tasks...")
        for meta in chunks_meta:
            chunk = db.query(Chunk).filter(
                Chunk.video_id == video_id, 
                Chunk.index == meta.index
            ).first()
            if chunk:
                transcribe_chunk.delay(
                    chunk_id=str(chunk.id),
                    chunk_path=meta.file_path,
                    title=title
                )
        
        video.status = VideoStatus.transcribiendo
        db.commit()
        
        logger.info(f"[{title}] ✅ Processing queued successfully")
        return {"status": "queued", "chunks": len(chunks_meta)}
        
    except FileNotFoundError as e:
        logger.error(f"[{title}] Permanent error (no retry): {e}")
        if video:
            video.status = VideoStatus.error
            video.error_reason = str(e)[:200]
            db.commit()
        raise
        
    except Exception as e:
        logger.error(f"[{title}] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        if video:
            video.status = VideoStatus.error
            video.error_reason = f"{type(e).__name__}: {str(e)[:150]}"
            db.commit()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=10 * (self.request.retries + 1))
        raise
        
    finally:
        if db:
            db.close()
        
        try:
            paths_to_clean = []
            if video_path and os.path.exists(video_path):
                paths_to_clean.append(video_path)
            if audio_path and os.path.exists(audio_path):
                paths_to_clean.append(audio_path)
            if chunks_dir and os.path.exists(chunks_dir):
                paths_to_clean.append(chunks_dir)
            
            if paths_to_clean:
                logger.debug(f"[{title}] Cleaning up: {paths_to_clean}")
                cleanup_video_files(
                    video_path=video_path if video_path in paths_to_clean else None,
                    audio_path=audio_path if audio_path in paths_to_clean else None,
                    chunks_dir=chunks_dir if chunks_dir in paths_to_clean else None,
                    keep_audio=True
                )
        except Exception as cleanup_error:
            logger.warning(f"[{title}] Cleanup warning (non-fatal): {cleanup_error}")

# =============================================================================
# TAREA: TRANSCRIBIR CHUNK (ACTUALIZADA CON PROMPT MANAGER Y MÚLTIPLES HABLANTES)
# =============================================================================

@celery_app.task(bind=True, max_retries=12, default_retry_delay=15)
def transcribe_chunk(self, chunk_id: str, chunk_path: str, title: str):
    """
    Transcribe un chunk de audio usando Gemini con rotación de keys.
    Soporta identificación de múltiples hablantes dentro del mismo fragmento.
    """
    db: Session = SessionLocal()
    router = GeminiKeyRouter()
    chunk = None
    key_idx = None
    
    try:
        chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
        
        chunk.status = ChunkStatus.transcribiendo
        db.commit()
        
        # 1. Obtener una API key disponible
        key_idx, api_key = router.get_available_key()
        if api_key is None:
            logger.warning(f"[{title}] All API keys exhausted. Retrying in 2 min...")
            raise self.retry(countdown=120, exc=Exception("ALL_KEYS_EXHAUSTED"))
        
        # 2. Preparar llamada a Gemini
        client = router.get_gemini_client(api_key)
        
        # Leer audio chunk
        with open(chunk_path, "rb") as f:
            audio_bytes = f.read()
        
        # ✅ Usar prompt desde archivo externo
        prompt = prompt_manager.get_transcribe_prompt()
        
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
        
        # 4. Parsear respuesta (diccionario con "segments")
        result = router.parse_gemini_response(response.text)
        
        # 5. Validar con el modelo Pydantic
        gemini_response = GeminiChunkResponse(**result)
        
        # 6. Convertir a formato de texto para guardar en BD
        #    Formato: [Speaker] (start - end): texto
        formatted_text = gemini_response.to_formatted_text(include_timestamps=True)
        
        # 7. Obtener metadata agregada para compatibilidad con modelo actual
        primary_speaker = gemini_response.get_primary_speaker()
        dominant_sentiment = gemini_response.get_dominant_sentiment()
        avg_confidence = gemini_response.get_average_confidence()
        
        # 8. Guardar transcripción
        transcription = Transcription(
            chunk_id=chunk_id,
            text=formatted_text,
            speaker=primary_speaker,
            sentiment=dominant_sentiment,
            tone="múltiple",  # Porque puede haber varios tonos
            confidence=avg_confidence
        )
        db.add(transcription)
        
        # 9. Actualizar estado del chunk
        chunk.status = ChunkStatus.transcrita
        db.commit()
        
        # 10. Registrar uso de la key (SOLO si fue exitoso)
        router.record_usage(key_idx)
        
        segments_count = len(gemini_response.segments)
        logger.info(f"[{title}] Chunk {chunk.index} transcribed: {segments_count} segment(s), primary speaker: '{primary_speaker}', confidence: {avg_confidence:.2f}")
        
        # 11. Verificar si todos los chunks del video están listos → generar resumen
        _check_and_generate_summary.delay(video_id=str(chunk.video_id), title=title)
        
        return {
            "status": "success", 
            "chunk_index": chunk.index,
            "segments": segments_count,
            "primary_speaker": primary_speaker,
            "confidence": avg_confidence
        }
        
    except Exception as e:
        error_str = str(e).upper()
        
        # Manejo específico de errores de cuota de Gemini
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "RATE_LIMIT" in error_str:
            logger.warning(f"[{title}] Key #{key_idx if key_idx is not None else '?'} hit 429. Retrying with backoff...")
            if key_idx is not None:
                router.record_usage(key_idx)
            return self.retry(countdown=2 ** min(self.request.retries, 6) * 10)
        
        # Otros errores: reintento genérico
        logger.error(f"[{title}] Error transcribing chunk {chunk_id}: {e}", exc_info=True)
        if chunk:
            chunk.status = ChunkStatus.error
            chunk.error_reason = str(e)[:500]
            db.commit()
        return self.retry(countdown=30, exc=e)
        
    finally:
        db.close()

# =============================================================================
# TAREA: VERIFICAR Y GENERAR RESUMEN (ACTUALIZADA CON PROMPT MANAGER)
# =============================================================================

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
        
        # 2. Generar resumen con Gemini
        router = GeminiKeyRouter()
        key_idx, api_key = router.get_available_key()
        if not api_key:
            return self.retry(countdown=120)
        
        client = router.get_gemini_client(api_key)
        
        # ✅ Usar prompt desde archivo externo con formato
        prompt_template = prompt_manager.get_summary_prompt()
        summary_prompt = prompt_template.format(
            title=title,
            full_text=full_text[:100000]
        )
        
        # 3. Llamar a Gemini
        response = client.models.generate_content(
            model=router.model_name,
            contents=[summary_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="text/plain"
            )
        )
        
        # 4. Guardar resumen en BD
        summary = Summary(
            video_id=video_id,
            content=response.text.strip()
        )
        db.add(summary)
        
        # 5. Actualizar estado final del video
        video.status = VideoStatus.transcrita
        db.commit()
        
        # 6. Registrar uso de key
        router.record_usage(key_idx)
        logger.info(f"[{title}] Summary generated successfully")
        
        return {"status": "summary_generated"}
        
    except Exception as e:
        logger.error(f"[{title}] Error generating summary: {e}", exc_info=True)
        return self.retry(exc=e)
        
    finally:
        db.close()