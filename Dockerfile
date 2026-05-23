# Dockerfile
FROM python:3.14-slim

# =============================================================================
# METADATA (buenas prácticas)
# =============================================================================
LABEL maintainer="tu-email@dominio.com"
LABEL description="VidTranscribe API: Transcripción de videos con Gemini IA"
LABEL version="0.1.0"

# =============================================================================
# INSTALAR DEPENDENCIAS DEL SISTEMA (FFmpeg + herramientas)
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# CONFIGURAR ENTORNO DE TRABAJO
# =============================================================================
WORKDIR /app

# Copiar archivos de dependencias primero (para aprovechar caché de Docker)
COPY pyproject.toml requirements.txt ./

# Instalar dependencias de Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# Copiar el código fuente
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .env.example ./

# Crear directorio de uploads (con permisos correctos)
RUN mkdir -p /app/uploads && chmod 755 /app/uploads

# =============================================================================
# PUERTO Y USUARIO (seguridad básica)
# =============================================================================
EXPOSE 8000

# Crear usuario no-root para ejecutar la app (opcional pero recomendado)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# =============================================================================
# COMANDO DE INICIO
# =============================================================================
# Se puede sobrescribir con docker-compose o en producción
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]