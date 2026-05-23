# src/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator, Field, Optional
from typing import List
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    # ================= DATABASE =================
    # Híbrido: puede venir de .env (local) o construirse desde variables de Render
    database_url: Optional[str] = None
    
    # Variables que Render inyecta automáticamente para PostgreSQL
    pg_host: Optional[str] = Field(None, alias="PGHOST")
    pg_port: Optional[str] = Field(None, alias="PGPORT")
    pg_user: Optional[str] = Field(None, alias="PGUSER")
    pg_password: Optional[str] = Field(None, alias="PGPASSWORD")
    pg_database: Optional[str] = Field(None, alias="PGDATABASE")

    # ================= REDIS =================
    # Híbrido: puede venir de .env (local) o de Render
    redis_url: Optional[str] = None
    
    # Render inyecta REDIS_URL automáticamente (alias para compatibilidad)
    render_redis_url: Optional[str] = Field(None, alias="REDIS_URL")

    # ================= GEMINI =================
    gemini_api_keys_raw: str = Field(alias="GEMINI_API_KEYS", default="")
    gemini_model: str = "gemini-2.5-flash"
    
    @property
    def gemini_api_keys(self) -> List[str]:
        """Lista de API keys válidas (sin espacios, filtrando vacías)."""
        return [k.strip() for k in self.gemini_api_keys_raw.split(",") if k.strip()]

    # ================= UPLOADS & LIMITS =================
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 1500
    max_duration_min: int = 120
    chunk_duration_sec: int = 150  # 2.5 minutos
    chunk_overlap_sec: int = 5     # solape para preservar contexto

    # ================= SERVER =================
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # =========================================================================
    # PROPIEDADES COMPUTADAS: Construyen URLs si no están explícitas
    # =========================================================================
    
    @property
    def effective_database_url(self) -> str:
        """
        Retorna la URL de conexión a PostgreSQL.
        
        Prioridad:
        1. database_url explícita (desarrollo local con Docker)
        2. Construida desde variables PG* de Render
        3. Fallback para desarrollo sin Docker
        """
        # 1. Si tenemos database_url explícita, usarla (caso Docker local)
        if self.database_url:
            return self.database_url
        
        # 2. Si estamos en Render, construir URL desde variables separadas
        if self.pg_host and self.pg_password:
            return (
                f"postgresql+psycopg2://{self.pg_user or 'postgres'}:"
                f"{self.pg_password}@"
                f"{self.pg_host}:"
                f"{self.pg_port or '5432'}/"
                f"{self.pg_database or 'vidtranscribe'}"
            )
        
        # 3. Fallback para desarrollo local sin Docker
        return "postgresql+psycopg2://postgres:postgres@localhost:5432/vidtranscribe"
    
    @property
    def effective_redis_url(self) -> str:
        """
        Retorna la URL de conexión a Redis.
        
        Prioridad:
        1. redis_url explícita (desarrollo local con Docker)
        2. REDIS_URL inyectada por Render
        3. Fallback para desarrollo local
        """
        # 1. Si tenemos redis_url explícita, usarla (caso Docker local)
        if self.redis_url:
            return self.redis_url
        
        # 2. Si Render inyectó REDIS_URL, usarla
        if self.render_redis_url:
            return self.render_redis_url
        
        # 3. Fallback para desarrollo local
        return "redis://localhost:6379/0"

    # =========================================================================
    # VALIDACIONES
    # =========================================================================
    
    @model_validator(mode="after")
    def validate_limits(self) -> "Settings":
        if self.max_file_size_mb < 10:
            raise ValueError("MAX_FILE_SIZE_MB debe ser al menos 10")
        if self.max_duration_min < 5:
            raise ValueError("MAX_DURATION_MIN debe ser al menos 5")
        if not self.gemini_api_keys:
            raise ValueError("GEMINI_API_KEYS debe tener al menos una clave válida")
        return self

# Instancia global para importar en toda la app
settings = Settings()