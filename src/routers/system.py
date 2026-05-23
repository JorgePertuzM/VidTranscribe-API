# src/routers/system.py
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
import shutil
from src.config import settings
from src.database import check_db_connection

router = APIRouter()

@router.get("/health", tags=["System"])
def health_check():
    """Verifica servicios críticos."""
    db_ok = check_db_connection()
    
    # Verificar Redis
    redis_ok = False
    try:
        import redis
        r = redis.from_url(settings.effective_redis_url, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
    except: pass
    
    # Verificar FFmpeg
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    
    status_code = status.HTTP_200_OK if (db_ok and ffmpeg_ok) else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        content={
            "status": "ok" if status_code == 200 else "degraded",
            "services": {
                "postgresql": "connected" if db_ok else "disconnected",
                "redis": "connected" if redis_ok else "disconnected",
                "ffmpeg": "available" if ffmpeg_ok else "missing"
            }
        },
        status_code=status_code
    )

@router.get("/", tags=["System"])
def root():
    """Información básica de la API."""
    return {
        "name": "VidTranscribe API",
        "version": "0.1.0",
        "docs": "/docs"
    }