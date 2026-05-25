# src/prompts/__init__.py
"""
Gestor de prompts para Gemini.
Carga prompts desde archivos .txt para facilitar su mantenimiento.
"""
import os
from pathlib import Path


class PromptManager:
    """Gestor centralizado de prompts."""
    
    def __init__(self):
        self.prompts_dir = Path(__file__).parent
        self._cache = {}
    
    def _load_prompt(self, filename: str) -> str:
        """Carga un prompt desde archivo con caché."""
        if filename not in self._cache:
            filepath = self.prompts_dir / filename
            if not filepath.exists():
                raise FileNotFoundError(f"Prompt file not found: {filepath}")
            
            with open(filepath, 'r', encoding='utf-8') as f:
                self._cache[filename] = f.read().strip()
        
        return self._cache[filename]
    
    def get_transcribe_prompt(self) -> str:
        """Retorna el prompt para transcripción de chunks."""
        return self._load_prompt("transcribe_chunk.txt")
    
    def get_summary_prompt(self) -> str:
        """Retorna el prompt para generación de resúmenes."""
        return self._load_prompt("generate_summary.txt")
    
    def reload(self):
        """Recarga todos los prompts (útil para desarrollo)."""
        self._cache.clear()


# Instancia global para usar en toda la aplicación
prompt_manager = PromptManager()