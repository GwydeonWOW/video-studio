"""Utilidades comunes a todos los pasos del pipeline."""
from __future__ import annotations

import hashlib
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


# HORIZONTAL (16:9) O VERTICAL (9:16), y se decide al crear el vídeo (el
# param `formato` del brief, junto a la duración). Todo lo que cuelga de
# esa decisión la lee de aquí y de ningún otro sitio: el tamaño al que
# se PIDE cada imagen, y el cuadro de salida del MP4. Vive en `comun`
# porque lo leen p2, p4, p6 y p8, y ninguno importa a los demás en ese
# sentido. El porte del original, con los tamaños de este motor:
#
#   salida        el cuadro del MP4 y de la banda quieta (subtítulos)
#   generacion    el lienzo al que se pide cada imagen a GLM: 16:9 o 9:16
#   vertical      lo que se le pasa a `imagen_glm.generar`
FORMATOS = {
    "horizontal": {"nombre": "Horizontal 16:9", "salida": [1920, 1080],
                   "generacion": "1344x768", "vertical": False},
    "vertical": {"nombre": "Vertical 9:16", "salida": [1080, 1920],
                 "generacion": "768x1344", "vertical": True},
}
FORMATO_POR_DEFECTO = "horizontal"


def normalizar_formato(valor) -> str:
    """'vertical' | 'horizontal'. Lo desconocido cae en horizontal, que es
    lo que había siempre: un proyecto anterior a esto no trae ninguno."""
    texto = str(valor or "").strip().lower()
    if texto in ("vertical", "9:16", "9x16", "portrait"):
        return "vertical"
    return FORMATO_POR_DEFECTO


def ficha_formato(valor) -> dict:
    """La ficha del formato, con sus tres tamaños. Nunca levanta."""
    ficha = dict(FORMATOS[normalizar_formato(valor)])
    ficha["id"] = normalizar_formato(valor)
    ficha["salida"] = list(ficha["salida"])
    return ficha


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


def huella_fichero(ruta, bloque: int = 1 << 20) -> str:
    """Hash del contenido de un fichero (cadena vacia si no existe).

    Lo usa el guardian de planos repetidos de p6: dos imagenes
    identicas son un fallo que en disco es un byte a byte identico.
    """
    if not ruta:
        return ""
    try:
        if not Path(ruta).is_file():
            return ""
        resumen = hashlib.sha256()
        with open(ruta, "rb") as fh:
            for trozo in iter(lambda: fh.read(bloque), b""):
                resumen.update(trozo)
        return resumen.hexdigest()[:16]
    except OSError:
        return ""


def desempatar(*partes) -> int:
    """Entero estable a partir de varias claves: desempata sin usar random."""
    return int(hashlib.sha256("|".join(str(p) for p in partes)
                              .encode("utf-8")).hexdigest()[:8], 16)
