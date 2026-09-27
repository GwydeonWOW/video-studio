"""Voz: ElevenLabs (sustituye a Cartesia en el original).

Usos:
- `voces()`: catalogo de voces de la cuenta (para elegir en el estilo).
- `hablar()`: TTS de una narracion -> mp3 en disco + duracion.
- `hablar_con_marcas()`: TTS con alineacion por caracter -> marcas de tiempo
  por palabra. Es lo que permite repasar el guion contra el audio y medir la
  duracion real de cada seccion sin estimaciones.

Endpoint: https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps
Modelo por defecto: eleven_multilingual_v2 (espanol natural). Para borradores
internos se puede usar eleven_flash (mas barato y rapido).
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

TIEMPO_FUERA_S = 300
BASE = "https://api.elevenlabs.io/v1"

MODELOS = {
    "multilingual": "eleven_multilingual_v2",
    "flash": "eleven_flash_v2_5",
    "v3": "eleven_v3",
}

#: Limite de la API por peticion; las narraciones largas se parten por
#: frases y se concatenan las marcas.
TOPE_CARACTERES = 4500


class ErrorVoz(RuntimeError):
    """Fallo de ElevenLabs con texto para humano."""


def clave(claves: dict | None = None) -> str:
    if claves and claves.get("elevenlabs"):
        return str(claves["elevenlabs"])
    return os.environ.get("ESTUDIO_ELEVENLABS_KEY", "")


def _cabeceras(clave_: str) -> dict:
    return {"xi-api-key": clave_, "Content-Type": "application/json"}


def voces(claves: dict | None = None) -> list[dict]:
    """Voces disponibles: [{voice_id, nombre, idiomas, etiquetas}]."""
    clave_ = clave(claves)
    if not clave_:
        return []
    try:
        respuesta = requests.get(f"{BASE}/voices",
                                 headers=_cabeceras(clave_), timeout=30)
        if respuesta.status_code != 200:
            raise ErrorVoz(f"{respuesta.status_code}: {respuesta.text[:200]}")
        lista = []
        for voz in respuesta.json().get("voices", []):
            lista.append({
                "voice_id": voz.get("voice_id", ""),
                "nombre": voz.get("name", ""),
                "etiquetas": voz.get("labels", {}) or {},
                "idiomas": [p.get("language_id", "")
                            for p in voz.get("fine_tuning", {})
                            .get("language", []) or []],
            })
        return lista
    except requests.RequestException as fallo:
        raise ErrorVoz(f"red: {fallo}") from fallo


def probar(claves: dict | None = None) -> dict:
    """Prueba de clave sin coste: leer el catalogo de voces."""
    clave_ = clave(claves)
    if not clave_:
        return {"ok": False, "detalle": "sin clave"}
    try:
        respuesta = requests.get(f"{BASE}/user", headers=_cabeceras(clave_),
                                 timeout=30)
        if respuesta.status_code == 200:
            cuota = respuesta.json().get("subscription", {})
            return {"ok": True,
                    "detalle": f"cuota {cuota.get('character_count', '?')}/"
                               f"{cuota.get('character_limit', '?')}"}
        return {"ok": False,
                "detalle": f"{respuesta.status_code}: {respuesta.text[:200]}"}
    except requests.RequestException as fallo:
        return {"ok": False, "detalle": f"red: {fallo}"}


def _modelo_de(nombre: str) -> str:
    return MODELOS.get(nombre, nombre if nombre.startswith("eleven")
                       else MODELOS["multilingual"])


def hablar(narracion: str, voz: str, destino: Path, claves: dict | None = None,
           modelo: str = "multilingual", estabilidad: float = 0.5,
           similitud: float = 0.75, velocidad: float = 1.0) -> Path:
    """Genera el audio de una narracion entera y lo escribe en `destino`.

    Devuelve la ruta. La duracion se lee despues con ffprobe (voz.__len__).
    """
    mp3, _marcas = _generar(narracion, voz, claves, modelo, estabilidad,
                            similitud, velocidad, con_marcas=False)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(mp3)
    return destino


def hablar_con_marcas(narracion: str, voz: str, destino: Path,
                      claves: dict | None = None,
                      modelo: str = "multilingual", estabilidad: float = 0.5,
                      similitud: float = 0.75,
                      velocidad: float = 1.0) -> dict:
    """Genera audio + marcas de tiempo por palabra.

    Devuelve {"ruta": Path, "duracion": float, "palabras": [
        {"palabra": str, "inicio": s, "fin": s}, ...]}
    """
    mp3, marcas = _generar(narracion, voz, claves, modelo, estabilidad,
                           similitud, velocidad, con_marcas=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(mp3)
    duracion = marcas.get("audio_duration") or 0.0
    palabras = _palabras_de(marcas, narracion)
    return {"ruta": destino, "duracion": round(duracion, 3), "palabras": palabras}


def _palabras_de(marcas: dict, narracion: str) -> list[dict]:
    """Convierte la alineacion por caracter en marcas por palabra."""
    inicios = marcas.get("character_start_times_seconds") or []
    finales = marcas.get("character_end_times_seconds") or []
    texto = marcas.get("normalized_text") or narracion
    if len(inicios) < len(texto) or len(finales) < len(texto):
        return []
    palabras, actual, arranque = [], "", None
    for indice, caracter in enumerate(texto):
        if caracter.isspace():
            if actual and arranque is not None:
                palabras.append({"palabra": actual, "inicio": arranque,
                                 "fin": finales[indice - 1]})
            actual, arranque = "", None
        else:
            if arranque is None:
                arranque = inicios[indice]
            actual += caracter
    if actual and arranque is not None:
        palabras.append({"palabra": actual, "inicio": arranque,
                         "fin": finales[len(texto) - 1]})
    return [{"palabra": p["palabra"], "inicio": round(p["inicio"], 3),
             "fin": round(p["fin"], 3)} for p in palabras]


def _partir(narracion: str) -> list[str]:
    """Parte narraciones largas en trozos por debajo del tope, por frases."""
    texto = narracion.strip()
    if len(texto) <= TOPE_CARACTERES:
        return [texto]
    trozos, actual = [], ""
    import re
    frases = re.split(r"(?<=[.!?;:])\s+", texto)
    for frase in frases:
        if len(actual) + len(frase) + 1 > TOPE_CARACTERES and actual:
            trozos.append(actual.strip())
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


def _generar(narracion: str, voz: str, claves: dict | None, modelo: str,
             estabilidad: float, similitud: float, velocidad: float,
             con_marcas: bool) -> tuple[bytes, dict]:
    clave_ = clave(claves)
    if not clave_:
        raise ErrorVoz("falta la clave de ElevenLabs "
                       "(ESTUDIO_ELEVENLABS_KEY o secretos/claves.json)")
    trozos = _partir(narracion)
    audio_total, palabras_total, duracion_total = b"", [], 0.0
    for trozo in trozos:
        url = (f"{BASE}/text-to-speech/{voz}/with-timestamps" if con_marcas
               else f"{BASE}/text-to-speech/{voz}")
        cuerpo = {
            "text": trozo,
            "model_id": _modelo_de(modelo),
            "voice_settings": {
                "stability": estabilidad,
                "similarity_boost": similitud,
                "speed": velocidad,
            },
        }
        try:
            respuesta = requests.post(
                url, headers=_cabeceras(clave_), params={
                    "output_format": "mp3_44100_128"},
                json=cuerpo, timeout=TIEMPO_FUERA_S)
        except requests.RequestException as fallo:
            raise ErrorVoz(f"red: {fallo}") from fallo
        if respuesta.status_code != 200:
            raise ErrorVoz(f"ElevenLabs {respuesta.status_code}: "
                           f"{respuesta.text[:200]}")
        if con_marcas:
            cuerpo_json = respuesta.json()
            audio = base64.b64decode(cuerpo_json.get("audio_base64", ""))
            marcas = cuerpo_json.get("normalized_alignment") or \
                cuerpo_json.get("alignment") or {}
            desplazamiento = duracion_total
            for palabra in _palabras_de(marcas, trozo):
                palabras_total.append({
                    "palabra": palabra["palabra"],
                    "inicio": round(palabra["inicio"] + desplazamiento, 3),
                    "fin": round(palabra["fin"] + desplazamiento, 3)})
            duracion_total += float(marcas.get("audio_duration")
                                    or _durar(audio))
        else:
            audio = respuesta.content
        audio_total += audio
    if con_marcas:
        return audio_total, {"audio_duration": duracion_total,
                             "palabras": palabras_total}
    return audio_total, {}


def _durar(mp3: bytes) -> float:
    """Duracion aproximada de un mp3 en bytes sin ffprobe (por si acaso)."""
    # 128 kbps -> 16 KB/s; suficiente como ultimo recurso de respaldo
    return len(mp3) / 16000.0


def personajes_de(claves: dict | None = None) -> int:
    """Caracteres consumidos/limite de la suscripcion (para la UI)."""
    clave_ = clave(claves)
    if not clave_:
        return 0
    try:
        respuesta = requests.get(f"{BASE}/user", headers=_cabeceras(clave_),
                                 timeout=30)
        sub = respuesta.json().get("subscription", {})
        return int(sub.get("character_count", 0))
    except (requests.RequestException, ValueError):
        return 0
