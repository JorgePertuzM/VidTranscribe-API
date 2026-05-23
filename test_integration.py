#!/usr/bin/env python3
"""
Script de prueba de integración para VidTranscribe API (versión Python).
Equivalente a test_integration.ps1 para entornos no-Windows.

Uso:
    python test_integration.py
    python test_integration.py --title "Mi Clase" --duration 45 --api-url http://mi-vps:8000
"""

import argparse
import asyncio
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

def check_prerequisites(api_url: str):
    """Verifica que FFmpeg y la API estén disponibles."""
    console.print("[bold cyan]► PREREQUISITOS[/] Verificando dependencias...")
    
    # FFmpeg
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
        version = result.stdout.splitlines()[0].split()[2]
        console.print(f"  [green]✅[/] FFmpeg: {version}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("  [red]❌[/] FFmpeg no encontrado. Instálalo con: sudo apt install ffmpeg")
        sys.exit(1)
    
    # API
    try:
        with httpx.Client(timeout=5) as client:
            health = client.get(f"{api_url}/health").json()
            if health.get("status") != "ok":
                raise ValueError(f"API no saludable: {health}")
        console.print(f"  [green]✅[/] API: {api_url} (status: ok)")
    except Exception as e:
        console.print(f"  [red]❌[/] No se pudo conectar a la API: {e}")
        sys.exit(1)

def create_test_video(output_path: str, duration_sec: int, title: str) -> str:
    """Genera un video de prueba con FFmpeg."""
    console.print(f"[bold cyan]► GENERAR VIDEO[/] Creando video de prueba ({duration_sec}s)...")
    
    cmd = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"color=c=black:s=640x360:r=24:d={duration_sec}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_sec}",
        "-vf", f"drawtext=fontfile=Arial:text='{title}':x=(w-text_w)/2:y=(h-text_h)/2:fontsize=24:fontcolor=white",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-y",
        output_path
    ]
    
    start = time.time()
    subprocess.run(cmd, capture_output=True, check=True)
    elapsed = time.time() - start
    
    file_size = Path(output_path).stat().st_size / 1024
    console.print(f"  [green]✅[/] Video creado: {Path(output_path).name} ({file_size:.1f} KB, {elapsed:.1f}s)")
    return output_path

async def upload_video(file_path: str, title: str, api_url: str) -> dict:
    """Sube el video a la API."""
    console.print("[bold cyan]► UPLOAD[/] Subiendo video a la API...")
    
    async with httpx.AsyncClient(timeout=30) as client:
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "video/mp4")}
            data = {"title": title}
            response = await client.post(f"{api_url}/api/v1/videos/upload", files=files, data=data)
            response.raise_for_status()
    
    result = response.json()
    console.print(f"  [green]✅[/] Upload exitoso: {result['video_id']} (status: {result['status']})")
    return result

async def wait_processing(video_id: str, api_url: str, max_attempts: int = 60, interval: int = 3) -> bool:
    """Espera a que el procesamiento termine con polling."""
    console.print(f"[bold cyan]► POLLING[/] Esperando procesamiento (máx {max_attempts * interval // 60} min)...")
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Procesando...", total=None)
        
        for attempt in range(max_attempts):
            async with httpx.AsyncClient(timeout=10) as client:
                status = await client.get(f"{api_url}/api/v1/videos/status/{video_id}")
                status.raise_for_status()
                data = status.json()
            
            progress.update(task, description=f"{data['status']} {data.get('progress', '')}")
            
            if data["status"] == "transcrita":
                progress.update(task, description="✅ Completado", completed=True)
                return True
            elif data["status"] == "error":
                progress.update(task, description=f"❌ Error: {data.get('error_reason')}", completed=True)
                return False
            
            await asyncio.sleep(interval)
    
    console.print("  [yellow]⏱️[/] Tiempo máximo alcanzado")
    return False

async def show_results(video_id: str, api_url: str):
    """Muestra transcripción y resumen."""
    console.print("[bold cyan]► RESULTADOS[/] Obteniendo transcripción y resumen...")
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Transcripción
        console.print("\n[bold]📝 Transcripción completa:[/]")
        try:
            full = await client.get(f"{api_url}/api/v1/videos/{video_id}/full")
            full.raise_for_status()
            data = full.json()
            for chunk in data.get("chunks", []):
                console.print(f"\n  [gray]┌─ Chunk {chunk['index']} [{chunk['original_start']} → {chunk['original_end']}][/gray]")
                console.print(f"  [dim]│ Speaker: {chunk['speaker']} | Sentiment: {chunk['sentiment']} | Tone: {chunk['tone']}[/dim]")
                console.print(f"  [dim]│ Confidence: {chunk.get('confidence', 'N/A')}[/dim]")
                console.print(f"  [cyan]│ Text:[/cyan]")
                for line in chunk["text"].split("\n"):
                    console.print(f"  [white]│   {line}[/white]")
                console.print("  [gray]└─[/gray]")
        except Exception as e:
            console.print(f"  [red]❌ Error obteniendo transcripción: {e}[/red]")
        
        # Resumen
        console.print("\n[bold]📋 Resumen generado:[/]")
        try:
            summary = await client.get(f"{api_url}/api/v1/videos/{video_id}/summary")
            summary.raise_for_status()
            content = summary.json().get("content", "")
            if content:
                console.print(content)
            else:
                console.print("  [yellow](Resumen no disponible aún)[/yellow]")
        except Exception as e:
            console.print(f"  [red]❌ Error obteniendo resumen: {e}[/red]")

async def main():
    parser = argparse.ArgumentParser(description="Prueba de integración para VidTranscribe API")
    parser.add_argument("--title", default=f"Test-{datetime.now().strftime('%Y%m%d-%H%M%S')}", help="Título del video de prueba")
    parser.add_argument("--duration", type=int, default=30, help="Duración en segundos (10-120)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="URL base de la API")
    parser.add_argument("--no-cleanup", action="store_true", help="No eliminar archivo de prueba al finalizar")
    parser.add_argument("--verbose", action="store_true", help="Mostrar logs detallados")
    args = parser.parse_args()
    
    console.print(f"\n[bold magenta]🎬 VidTranscribe - Prueba de Integración[/]")
    console.print(f"   [dim]Título: {args.title} | Duración: {args.duration}s | API: {args.api_url}[/dim]\n")
    
    try:
        check_prerequisites(args.api_url)
        
        video_path = f"test_video_{args.title.replace(' ', '_')}.mp4"
        create_test_video(video_path, args.duration, args.title)
        
        upload_resp = await upload_video(video_path, args.title, args.api_url)
        video_id = upload_resp["video_id"]
        
        completed = await wait_processing(video_id, args.api_url)
        await show_results(video_id, args.api_url)
        
        if not args.no_cleanup and Path(video_path).exists():
            console.print("\n[bold cyan]► LIMPIEZA[/] Eliminando archivo de prueba...")
            Path(video_path).unlink()
            console.print("  [green]✅[/] Archivo eliminado")
        
        console.print(f"\n[green]✅ Prueba finalizada.[/green]")
        return 0 if completed else 1
        
    except Exception as e:
        console.print(f"\n[red]❌ Error crítico: {e}[/red]")
        if args.verbose:
            import traceback
            console.print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)