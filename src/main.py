# src/main.py
"""
Entry point minimalista de VidTranscribe API.
Configuración esencial: FastAPI, CORS, Lifespan y Routers.
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import engine, check_db_connection
from src.routers import system, videos, transcriptions  # ✅ Router de videos

# Logging básico y funcional
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/Shutdown esencial."""
    # Startup
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    logger.info("✅ Servidor iniciado. Uploads: %s", settings.upload_dir)
    if not check_db_connection():
        logger.error("❌ PostgreSQL: conexión fallida")
    yield
    # Shutdown
    engine.dispose()
    logger.info("🛑 Servidor detenido")


app = FastAPI(
    title="VidTranscribe API",
    version="0.1.0",
    description="MVP: Transcripción de videos con Gemini IA y chunking.",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json"
)

# CORS (abierto para desarrollo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check simple
@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "database": "connected" if check_db_connection() else "disconnected"
    }

# Montaje de routers
app.include_router(videos.router, prefix="/api/v1/videos", tags=["Videos"])
app.include_router(transcriptions.router, prefix="/api/v1/transcriptions", tags=["Transcriptions"])
app.include_router(system.router, tags=["System"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=settings.debug)