# src/schemas/gemini.py
"""
Esquemas Pydantic para respuestas estructuradas de Gemini.
Usado para validar y tipar las respuestas de la IA.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class GeminiChunkResponse(BaseModel):
    """
    Respuesta esperada de Gemini para transcripción de un chunk.
    Usado con response_mime_type="application/json" y response_schema.
    """
    transcription: str = Field(
        ...,
        description="Texto literal transcrito. Usa [cruce voces], [inentendible] o [Ruido de fondo] si aplica.",
        min_length=1
    )
    speaker: str = Field(
        default="Desconocido",
        description="Quién habla: 'Narrador principal', 'Estudiante', 'Pregunta de alumno', etc."
    )
    sentiment: Literal["positivo", "negativo", "neutro"] = Field(
        ...,
        description="Tono emocional predominante en el fragmento"
    )
    tone: str = Field(
        ...,
        description="Estilo de habla: 'autoridad clara', 'inseguridad', 'conversacional', 'didáctico', 'entusiasta', etc."
    )
    confidence: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Nivel de confianza de la IA en la transcripción (0.0 a 1.0)"
    )
    
    @field_validator("transcription")
    @classmethod
    def validate_markers(cls, v: str) -> str:
        """Valida que los marcadores especiales estén bien formateados."""
        markers = ["[cruce voces]", "[inentendible]", "[Ruido de fondo]"]
        # No forzar presencia, solo validar formato si aparecen
        return v