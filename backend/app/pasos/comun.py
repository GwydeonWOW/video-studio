"""Utilidades comunes a todos los pasos del pipeline."""
from __future__ import annotations

import math
import re
from pathlib import Path

try:
    from ..config import AJUSTES
    from ..nucleo.proyecto import Proyecto
except ImportError:
    from config import AJUSTES          # type: ignore
    from nucleo.proyecto import Proyecto  # type: ignore


def claves_actuales() -> dict:
    """Claves de API combinadas (entorno + volumen)."""
    from ..nucleo.claves import leer_claves
    return leer_claves(AJUSTES.carpeta_claves)


def ajustes_llm() -> dict:
    """Preferencias de modelos por rol (datos/ajustes.json)."""
    from ..nucleo.proyecto import leer_json
    datos = leer_json(Path(AJUSTES.datos) / "ajustes.json", {}) or {}
    return datos.get("llm", {}) or {}


#: Precio orientativo de cada llamada para la estimacion PREVIA de la
#: pantalla. El coste real lo apunta el medidor al ejecutar.
COSTE_LLAMADA_LLAM = {"glm": 0.004, "openai": 0.008, "anthropic": 0.02}
COSTE_IMAGEN = {"low": 0.015, "medium": 0.015, "high": 0.015}
#: caracteres de voz por dolar (aprox.)
CARACTERES_POR_DOLAR = 6667


def limpiar_id(texto: str, prefijo: str = "S") -> str:
    """S001, S002... a partir del indice o del texto que traiga."""
    encaje = re.search(r"(\d+)", str(texto))
    numero = int(encaje.group(1)) if encaje else 0
    return f"{prefijo}{numero:03d}"


def palabras(texto: str) -> int:
    return len([p for p in re.split(r"\s+", texto.strip()) if p])


#: Lectura aproximada en segundos (2.6 palabras/s es el ritmo natural del
#: espanol narrado; el original mide lo mismo tras generar la voz).
RITMO_PALABRAS_S = 2.6


def duracion_estimada(texto: str) -> float:
    return round(palabras(texto) / RITMO_PALABRAS_S, 2)


def ffmpeg() -> str:
    return AJUSTES.ffmpeg


def ffprobe() -> str:
    return AJUSTES.ffprobe


def duracion_de(ruta: Path) -> float:
    """Duracion real de un audio/video con ffprobe."""
    import subprocess
    try:
        proceso = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
            capture_output=True, text=True, timeout=60)
        return round(float(proceso.stdout.strip()), 3)
    except (ValueError, subprocess.SubprocessError):
        return 0.0


def normalizar_texto(texto: str) -> str:
    """Colapsa espacios y recorta; el LLM a veces deja saltos raros."""
    return re.sub(r"[ \t]+", " ", str(texto or "")).strip()


def partir_en_frases(texto: str, max_caracteres: int = 90) -> list[str]:
    """Parte un texto en frases/aptitudes para rotulos (para callouts)."""
    frases = re.split(r"(?<=[.!?])\s+", normalizar_texto(texto))
    salida, actual = [], ""
    for frase in frases:
        if len(actual) + len(frase) + 1 > max_caracteres and actual:
            salida.append(actual.strip())
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual:
        salida.append(actual)
    return salida
