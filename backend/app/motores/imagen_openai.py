"""Imágenes: OpenAI gpt-image-1 (igual que el original, con coste medido).

Genera una imagen por plano a partir de la descripcion visual del guion, con
las referencias del estilo del canal adjuntas (prompt compuesto, no
image-to-image: gpt-image-1 no las acepta en la API basica).

El coste es el motivo de las reglas de la tanda (docs del original): una a
una, nunca en paralelo, y calidad elegida al crear el proyecto.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

TIEMPO_FUERA_S = 300
BASE = "https://api.openai.com/v1/images/generations"

#: (calidad -> (etiqueta, multiplicador de coste relativo)). El precio real
#: lo lleva el medidor de coste; esto es para la estimacion previa.
CALIDADES = {
    "low": {"size": "1536x1024", "etiqueta": "borrador"},
    "medium": {"size": "1536x1024", "etiqueta": "estandar"},
    "high": {"size": "1536x1024", "etiqueta": "detalle"},
}

TAMANO_VERTICAL = "1024x1536"
TAMANO_HORIZONTAL = "1536x1024"


class ErrorImagen(RuntimeError):
    """Fallo de generacion con texto para humano."""


def clave(claves: dict | None = None) -> str:
    if claves and claves.get("openai"):
        return str(claves["openai"])
    return os.environ.get("ESTUDIO_OPENAI_KEY", "")


def probar(claves: dict | None = None) -> dict:
    """Prueba barata: la API de imagenes no tiene /models publico; se usa
    el mismo limite de la cuenta via /v1/models y se aclara en el detalle."""
    clave_ = clave(claves)
    if not clave_:
        return {"ok": False, "detalle": "sin clave"}
    try:
        respuesta = requests.get("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {clave_}"},
                                 timeout=30)
        if respuesta.status_code == 200:
            return {"ok": True,
                    "detalle": "clave valida (el saldo no se puede comprobar)"}
        return {"ok": False,
                "detalle": f"{respuesta.status_code}: {respuesta.text[:200]}"}
    except requests.RequestException as fallo:
        return {"ok": False, "detalle": f"red: {fallo}"}


def generar(descripcion: str, destino: Path, calidad: str = "low",
            claves: dict | None = None, vertical: bool = False,
            estilo: str = "") -> Path:
    """Genera UNA imagen y la escribe en `destino` (png). -> ruta

    `estilo` es la referencia textual del canal (paleta, tecnica, encuadres):
    se antepone a la descripcion de cada plano para consistencia visual.
    """
    clave_ = clave(claves)
    if not clave_:
        raise ErrorImagen("falta la clave de OpenAI para imagenes "
                          "(ESTUDIO_OPENAI_KEY o secretos/claves.json)")
    ajustes = CALIDADES.get(calidad, CALIDADES["low"])
    tamano = TAMANO_VERTICAL if vertical else ajustes.get("size", "1536x1024")
    prompt = f"{estilo}\n\n{descripcion}".strip() if estilo else descripcion
    try:
        respuesta = requests.post(
            BASE,
            headers={"Authorization": f"Bearer {clave_}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": prompt,
                  "size": tamano, "quality": calidad, "n": 1},
            timeout=TIEMPO_FUERA_S)
    except requests.RequestException as fallo:
        raise ErrorImagen(f"red: {fallo}") from fallo
    if respuesta.status_code != 200:
        raise ErrorImagen(f"OpenAI {respuesta.status_code}: "
                          f"{respuesta.text[:300]}")
    datos = respuesta.json().get("data", [])
    if not datos or not datos[0].get("b64_json"):
        raise ErrorImagen("OpenAI no devolvio imagen")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64decode(datos[0]["b64_json"]))
    return destino
