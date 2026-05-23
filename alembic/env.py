# alembic/env.py
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
import os

# =============================================================================
# CONFIGURAR PATH PARA IMPORTS (CRÍTICO)
# =============================================================================
# Agregar la raíz del proyecto al PATH para que Python encuentre 'src'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# =============================================================================
# IMPORTAR BASE Y MODELOS (CRÍTICO: los modelos deben importarse para registrarse)
# =============================================================================
from src.database import Base
from src.config import settings

# ✅ IMPORTAR TODOS LOS MODELOS para que se registren en Base.metadata
# Esto es OBLIGATORIO para que Alembic "vea" las tablas
from src.models import Video, Chunk, Transcription, Summary  # ← ESTA LÍNEA ES CLAVE

# =============================================================================
# CONFIGURACIÓN DE ALEMBIC
# =============================================================================
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ CRÍTICO: target_metadata debe ser Base.metadata (ahora poblado por los imports de modelos)
target_metadata = Base.metadata

# Sobrescribir URL desde settings (ignora alembic.ini)
config.set_main_option("sqlalchemy.url", settings.effective_database_url)


def run_migrations_offline() -> None:
    """Ejecutar migraciones en modo offline (sin conexión a BD)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecutar migraciones en modo online (con conexión a BD)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()