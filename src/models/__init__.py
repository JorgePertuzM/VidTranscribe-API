# src/models/__init__.py
import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Enum, DateTime, Text, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base

class VideoStatus(str, enum.Enum):
    cargando = "cargando"
    cargada = "cargada"
    procesando = "procesando"
    transcribiendo = "transcribiendo"
    transcrita = "transcrita"
    error = "error"

class ChunkStatus(str, enum.Enum):
    pendiente = "pendiente"
    transcribiendo = "transcribiendo"
    transcrita = "transcrita"
    error = "error"

class Video(Base):
    """Representa un video subido por el usuario."""
    __tablename__ = "videos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[VideoStatus] = mapped_column(Enum(VideoStatus), default=VideoStatus.cargando)
    search_vector: Mapped[TSVECTOR | None] = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    chunks = relationship("Chunk", back_populates="video", cascade="all, delete-orphan", lazy="selectin")
    summary = relationship("Summary", back_populates="video", uselist=False, cascade="all, delete-orphan", lazy="joined")

    __table_args__ = (
        Index("idx_video_search", "search_vector", postgresql_using="gin"),
    )

class Chunk(Base):
    """Fragmento de audio de 2.5 min + solape de 5s."""
    __tablename__ = "chunks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ChunkStatus] = mapped_column(Enum(ChunkStatus), default=ChunkStatus.pendiente)
    error_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    video = relationship("Video", back_populates="chunks")
    transcription = relationship("Transcription", back_populates="chunk", uselist=False, cascade="all, delete-orphan", lazy="joined")

class Transcription(Base):
    """Resultado de Gemini para un chunk específico."""
    __tablename__ = "transcriptions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str] = mapped_column(String(100), default="Desconocido")
    sentiment: Mapped[str] = mapped_column(String(50), nullable=False)
    tone: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    chunk = relationship("Chunk", back_populates="transcription")

class Summary(Base):
    """Resumen estructurado generado automáticamente al finalizar."""
    __tablename__ = "summaries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    video = relationship("Video", back_populates="summary")