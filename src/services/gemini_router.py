# src/services/gemini_router.py
"""
Router inteligente para API Keys de Gemini con rotación automática y tracking de límites.
Gestiona RPM (requests per minute) y RPD (requests per day) por key, respetando la zona horaria PT de Google.
"""
import os
import redis
import pytz
from datetime import datetime, timezone
from typing import Optional, Tuple
from google import genai
from google.genai import types
from src.config import settings

# Cliente Redis compartido (singleton)
_redis_client: Optional[redis.Redis] = None

def get_redis_client() -> redis.Redis:
    """Obtiene o crea el cliente Redis singleton."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    return _redis_client

class GeminiKeyRouter:
    """
    Gestiona un pool de API keys de Gemini con:
    - Rotación automática cuando se agota la cuota
    - Tracking atómico de RPM/RPD en Redis
    - Respeto a la zona horaria Pacific Time (reset diario de Google)
    """
    
    def __init__(self):
        self.api_keys = settings.gemini_api_keys
        if not self.api_keys:
            raise ValueError("GEMINI_API_KEYS no configurado en .env")
        
        # Límites del plan Free de Gemini (ajustables si cambia la API)
        self.rpm_limit = 5   # requests por minuto por key
        self.rpd_limit = 20  # requests por día por key
        
        # Zona horaria de Pacific Time para coincidencia con reset de Google
        self.pt_tz = pytz.timezone("America/Los_Angeles")
        self.model_name = settings.gemini_model

    def _get_time_keys(self) -> dict[str, str]:
        """Genera claves temporales para Redis basadas en Pacific Time."""
        now = datetime.now(self.pt_tz)
        return {
            "minute": now.strftime("%Y%m%d%H%M"),  # Ej: 202605230015
            "day": now.strftime("%Y%m%d"),          # Ej: 20260523
        }

    def get_available_key(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Busca la primera API key con cuota disponible (RPM y RPD).
        
        Returns:
            Tuple (índice_de_la_key, api_key) o (None, None) si todas están agotadas.
        """
        t = self._get_time_keys()
        redis_cli = get_redis_client()
        
        for i, key in enumerate(self.api_keys):
            rpm_key = f"gem:rpm:{i}:{t['minute']}"
            rpd_key = f"gem:rpd:{i}:{t['day']}"
            
            # Obtener contadores actuales (0 si no existen)
            rpm_used = int(redis_cli.get(rpm_key) or 0)
            rpd_used = int(redis_cli.get(rpd_key) or 0)
            
            # Verificar si esta key tiene cuota disponible
            if rpm_used < self.rpm_limit and rpd_used < self.rpd_limit:
                return i, key
        
        # Todas las keys agotadas
        return None, None

    def record_usage(self, key_idx: int) -> None:
        """
        Registra el uso de una key incrementando contadores en Redis de forma atómica.
        Los contadores expiran automáticamente para evitar acumulación.
        """
        t = self._get_time_keys()
        redis_cli = get_redis_client()
        pipe = redis_cli.pipeline()
        
        rpm_key = f"gem:rpm:{key_idx}:{t['minute']}"
        rpd_key = f"gem:rpd:{key_idx}:{t['day']}"
        
        # Incrementar y establecer expiración en una transacción atómica
        pipe.incr(rpm_key)
        pipe.expire(rpm_key, 70)  # 1 minuto + buffer de 10s
        pipe.incr(rpd_key)
        pipe.expire(rpd_key, 86400)  # 24 horas exactas
        
        pipe.execute()

    def get_gemini_client(self, api_key: str) -> genai.Client:
        """Crea y retorna un cliente Gemini configurado."""
        return genai.Client(api_key=api_key)

    def parse_gemini_response(self, response_text: str) -> dict:
        """
        Parsea la respuesta JSON de Gemini con validación básica.
        Gemini en JSON mode debería devolver JSON válido, pero añadimos fallback.
        """
        import json
        try:
            # Gemini puede devolver código markdown ```json ... ```
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = clean.split("```json", 1)[-1].split("```", 1)[0].strip()
            return json.loads(clean)
        except Exception as e:
            raise ValueError(f"Failed to parse Gemini JSON response: {e}. Raw: {response_text[:200]}")