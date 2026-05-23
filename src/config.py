# src/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator, Field
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
    database_url: str

    # ================= REDIS =================
    redis_url: str

    # ================= GEMINI =================
    # Definido como str en el .env, pero convertido a List[str] internamente
    gemini_api_keys_raw: str = Field(alias="GEMINI_API_KEYS", default="")
    gemini_model: str = "gemini-2.5-flash"
    
    # Propiedad computada para uso interno (lista de claves)
    @property
    def gemini_api_keys(self) -> List[str]:
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