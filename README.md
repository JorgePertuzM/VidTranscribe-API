# 🎬 VidTranscribe API (MVP)
Backend para transcripción inteligente de videos universitarios con IA (Gemini), procesamiento asíncrono y búsqueda semántica.

## 📦 Stack
- **FastAPI** + Uvicorn
- **PostgreSQL** + SQLAlchemy 2.0
- **Celery** + Redis (cola de tareas)
- **Google Gemini 2.5 Flash** (rotación de keys + JSON schema)
- **ffmpeg** + pydub (audio chunking con solape)

## 🚀 Instalación Rápida


### 1. Crear y activar entorno virtual


```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 2. Instalar dependencias

```bash
pip install -e ".[dev]"
```

### 3. Configurar variables

```bash
cp .env.example .env
```
- *Edita* .env con tus credenciales DB, Redis y GEMINI_API_KEYS

### 4. Base de datos
- *Asegúrate* de tener PostgreSQL corriendo y creado: CREATE DATABASE vidtranscribe;
```bash
alembic upgrade head
```

### 5. Iniciar servicios

```bash
celery -A src.tasks worker --loglevel=info -c 4 &
uvicorn src.main:app --reload
```

## 📁 Estructura

```bash
vidtranscribe/
├── src/
│   ├── main.py          # Entrypoint FastAPI
│   ├── config.py        # Settings validados
│   ├── database.py      # Engine + Session
│   ├── models/          # SQLAlchemy ORM
│   ├── schemas/         # Pydantic DTOs
│   ├── routers/         # Endpoints REST
│   ├── services/        # Lógica de negocio
│   └── tasks.py         # Celery workers
├── alembic/             # Migraciones DB
├── uploads/             # Videos/Audios procesados
└── pyproject.toml       # Dependencias
```

## 🔑 Límites Gemini Free
RPM: 5 | RPD: 20 por key
Rotación automática de hasta 4 keys vía Redis
Reintento con backoff en 429 ResourceExhausted.