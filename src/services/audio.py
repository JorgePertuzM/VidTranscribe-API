# src/services/audio.py
"""
Servicio de procesamiento de audio: extracción MP3 y particionado inteligente.
"""
import os
import ffmpeg
from pathlib import Path
from typing import List
from dataclasses import dataclass
from src.config import settings

@dataclass
class ChunkMetadata:
    """Metadatos exactos de un fragmento de audio."""
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    original_start: str  # HH:MM:SS.mmm
    original_end: str    # HH:MM:SS.mmm
    file_path: str

def _format_timestamp(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS.mmm legible."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"

def extract_audio(video_path: str, output_dir: str) -> str:
    """
    Extrae audio de un video y lo convierte a MP3 (128kbps, mono para optimizar tokens).
    
    Args:
        video_path: Ruta absoluta al video subido
        output_dir: Directorio donde guardar el audio
        
    Returns:
        Ruta absoluta al archivo MP3 generado
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = os.path.join(output_dir, "audio_full.mp3")
    
    # Si ya existe, no reprocesar (idempotencia)
    if os.path.exists(output_path):
        return output_path
    
    try:
        (
            ffmpeg
            .input(video_path)
            .output(
                output_path,
                acodec='libmp3lame',
                audio_bitrate='128k',
                ac=1,  # Mono: reduce tokens sin perder calidad para transcripción
                loglevel='error'
            )
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
        return output_path
    except ffmpeg.Error as e:
        stderr = e.stderr.decode() if e.stderr else "Unknown error"
        raise RuntimeError(f"FFmpeg failed to extract audio: {stderr}")

def split_audio_with_overlap(
    audio_path: str,
    output_dir: str,
    chunk_duration: int = 150,  # 2.5 minutos en segundos
    overlap: int = 5            # 5 segundos de solape
) -> List[ChunkMetadata]:
    """
    Divide un audio en fragmentos con solape para preservar contexto entre cortes.
    
    Args:
        audio_path: Ruta al archivo MP3 completo
        output_dir: Directorio para guardar los chunks
        chunk_duration: Duración de cada chunk en segundos (default: 150)
        overlap: Solape entre chunks en segundos (default: 5)
        
    Returns:
        Lista de ChunkMetadata con rutas y timestamps exactos
    """
    # Obtener duración total del audio con ffprobe
    try:
        probe = ffmpeg.probe(audio_path, cmd='ffprobe')
        duration = float(probe['streams'][0]['duration'])
    except Exception as e:
        raise RuntimeError(f"Failed to probe audio duration: {e}")
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    chunks: List[ChunkMetadata] = []
    
    step = chunk_duration - overlap  # Paso real entre inicios de chunks
    index = 0
    
    for start in range(0, int(duration), int(step)):
        end = min(start + chunk_duration, duration)
        
        # Evitar chunks muy cortos al final (< 30 seg)
        if end - start < 30 and index > 0:
            # Fusionar con el chunk anterior si es muy corto
            continue
            
        chunk_filename = f"chunk_{index:03d}_{int(start)}_{int(end)}.mp3"
        chunk_path = os.path.join(output_dir, chunk_filename)
        
        try:
            (
                ffmpeg
                .input(audio_path, ss=start, t=end - start)
                .output(chunk_path, acodec='copy', loglevel='error')
                .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
            )
            
            metadata = ChunkMetadata(
                index=index,
                start_sec=start,
                end_sec=end,
                duration_sec=end - start,
                original_start=_format_timestamp(start),
                original_end=_format_timestamp(end),
                file_path=chunk_path
            )
            chunks.append(metadata)
            index += 1
            
        except ffmpeg.Error as e:
            stderr = e.stderr.decode() if e.stderr else "Unknown error"
            raise RuntimeError(f"FFmpeg failed to split chunk {index}: {stderr}")
    
    return chunks

def cleanup_video_files(video_path: str, audio_path: str, chunks_dir: str, keep_audio: bool = False):
    """
    Limpia archivos temporales después del procesamiento.
    
    Args:
        video_path: Ruta al video original (siempre se elimina)
        audio_path: Ruta al audio completo
        chunks_dir: Directorio con los chunks
        keep_audio: Si True, conserva el audio completo para debugging
    """
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
        if not keep_audio and os.path.exists(audio_path):
            os.remove(audio_path)
        # Los chunks se mantienen: son necesarios para la sincronización frontend
    except OSError as e:
        # No bloquear el flujo si falla la limpieza
        print(f"⚠️ Warning: Could not cleanup files: {e}")