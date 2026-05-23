# src/database.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from src.config import settings

# ✅ CORRECCIÓN: Base debe ser una CLASE que hereda de DeclarativeBase
class Base(DeclarativeBase):
    """Clase base para todos los modelos ORM de SQLAlchemy 2.0"""
    pass

# Engine síncrono (compatible con Celery, Alembic y scripts CLI)
engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Reconexión automática si la BD cae
    echo=settings.debug   # Log de SQL en modo debug
)

# Fábrica de sesiones para la aplicación
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependencia para inyección en FastAPI (se usará en routers)
def get_db():
    """
    Yield session DB con rollback automático en errores.
    Uso: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Función utilitaria para verificar conexión (útil en health checks)
def check_db_connection() -> bool:
    """Verifica que la BD esté accesible ejecutando una consulta simple."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False