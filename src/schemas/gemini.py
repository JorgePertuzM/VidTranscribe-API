# src/schemas/gemini.py
"""
Esquemas Pydantic para respuestas estructuradas de Gemini.
Usado para validar y tipar las respuestas de la IA.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Literal, List, Optional


class TranscriptionSegment(BaseModel):
    """
    Un segmento de transcripción con un solo hablante.
    Representa una intervención individual dentro del fragmento de audio.
    """
    start_time: float = Field(
        ..., 
        ge=0.0, 
        description="Tiempo de inicio en segundos desde el inicio del chunk (0.0 = inicio del fragmento)"
    )
    end_time: float = Field(
        ..., 
        ge=0.0, 
        description="Tiempo de fin en segundos desde el inicio del chunk"
    )
    speaker: str = Field(
        ..., 
        min_length=1,
        description="Identificador del hablante: nombre (ej: 'Don Ramón'), rol (ej: 'Entrevistador'), o descripción (ej: 'Voz grave', 'Mujer joven')"
    )
    text: str = Field(
        ..., 
        min_length=1,
        description="Texto literal transcrito. Usa [cruce voces], [inentendible] o [Ruido de fondo] si aplica."
    )
    sentiment: Literal["positivo", "negativo", "neutro"] = Field(
        ...,
        description="Sentimiento predominante en esta intervención"
    )
    tone: str = Field(
        ...,
        description="Tono del hablante: 'autoridad', 'inseguridad', 'conversacional', 'didáctico', 'enojado', 'alegre', 'triste', 'sarcástico', 'formal', 'informal', 'otro'"
    )
    confidence: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Nivel de confianza de la IA en esta transcripción (0.0 a 1.0)"
    )
    
    @field_validator("speaker")
    @classmethod
    def validate_speaker(cls, v: str) -> str:
        """Valida que el hablante tenga un nombre significativo."""
        if not v or len(v.strip()) == 0:
            return "Desconocido"
        return v.strip()
    
    @field_validator("text")
    @classmethod
    def validate_text_markers(cls, v: str) -> str:
        """Valida que los marcadores especiales estén bien formateados."""
        # No forzar presencia, solo limpiar espacios
        return v.strip()
    
    @field_validator("start_time", "end_time")
    @classmethod
    def validate_times(cls, v: float, info) -> float:
        """Valida que los tiempos sean coherentes."""
        if v < 0:
            return 0.0
        return v


class GeminiChunkResponse(BaseModel):
    """
    Respuesta esperada de Gemini para transcripción de un chunk.
    Soporta múltiples hablantes y segmentos dentro del mismo fragmento.
    Usado con response_mime_type="application/json" y response_schema.
    
    Ejemplo de respuesta esperada:
    {
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 4.2,
                "speaker": "Don Ramón",
                "text": "¡Oh, y ahora quién fue!",
                "sentiment": "negativo",
                "tone": "enojado",
                "confidence": 0.95
            },
            {
                "start_time": 4.2,
                "end_time": 7.8,
                "speaker": "El Chavo",
                "text": "Fue sin querer queriendo, señor...",
                "sentiment": "neutro",
                "tone": "inseguro",
                "confidence": 0.92
            }
        ]
    }
    """
    segments: List[TranscriptionSegment] = Field(
        ..., 
        min_length=1,
        description="Lista de segmentos de habla en orden cronológico. Cada segmento representa una intervención de un hablante."
    )
    
    @field_validator("segments")
    @classmethod
    def validate_segments_order(cls, segments: List[TranscriptionSegment]) -> List[TranscriptionSegment]:
        """
        Valida que los segmentos estén en orden cronológico ascendente.
        También asegura que los tiempos sean coherentes.
        """
        if not segments:
            raise ValueError("Debe haber al menos un segmento de transcripción")
        
        last_end_time = -1.0
        
        for i, seg in enumerate(segments):
            # Validar que start_time sea >= 0
            if seg.start_time < 0:
                segments[i].start_time = 0.0
            
            # Validar que end_time sea >= start_time
            if seg.end_time < seg.start_time:
                segments[i].end_time = seg.start_time + 1.0
            
            # Validar orden cronológico (permite solapamiento mínimo)
            if seg.start_time < last_end_time - 0.5:  # Permite 0.5s de solape
                # Ajustar start_time si hay demasiado solapamiento
                segments[i].start_time = last_end_time
            
            last_end_time = seg.end_time
        
        return segments
    
    def to_formatted_text(self, include_timestamps: bool = True) -> str:
        """
        Convierte los segmentos a texto formateado para almacenar en la BD.
        
        Args:
            include_timestamps: Si incluir timestamps en el texto
        
        Returns:
            Texto formateado con marcadores de hablante y opcionalmente timestamps
        """
        lines = []
        for seg in self.segments:
            if include_timestamps:
                lines.append(f"[{seg.speaker}] ({seg.start_time:.1f}s - {seg.end_time:.1f}s): {seg.text}")
            else:
                lines.append(f"[{seg.speaker}]: {seg.text}")
        return "\n".join(lines)
    
    def get_primary_speaker(self) -> str:
        """
        Obtiene el hablante principal (el que más tiempo habla).
        """
        if not self.segments:
            return "Desconocido"
        
        speaker_duration = {}
        for seg in self.segments:
            duration = seg.end_time - seg.start_time
            speaker_duration[seg.speaker] = speaker_duration.get(seg.speaker, 0) + duration
        
        return max(speaker_duration, key=speaker_duration.get)
    
    def get_dominant_sentiment(self) -> str:
        """
        Obtiene el sentimiento predominante en el fragmento.
        """
        if not self.segments:
            return "neutro"
        
        sentiment_count = {"positivo": 0, "negativo": 0, "neutro": 0}
        for seg in self.segments:
            sentiment_count[seg.sentiment] += 1
        
        return max(sentiment_count, key=sentiment_count.get)
    
    def get_average_confidence(self) -> float:
        """
        Obtiene la confianza promedio de todos los segmentos.
        """
        if not self.segments:
            return 0.0
        return sum(seg.confidence for seg in self.segments) / len(self.segments)