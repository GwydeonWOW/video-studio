"""Imágenes: GLM-Image de z.ai — la MISMA clave que los textos.

Sustituye a gpt-image-1: el plano se dibuja con el modelo glm-image de
la API de z.ai (api.z.ai/api/paas/v4), así que no hace falta ninguna
clave de OpenAI para nada. Diferencia práctica con OpenAI: la respuesta
trae una URL (no el b64), así que la imagen se descarga en el acto.

Reglas de la tanda sin cambio (docs del original): una TANDA cada vez
—nunca dos trabajos de assets a la vez—, calidad elegida al crear el
proyecto y, DENTRO de la tanda, cadenas por sitio con tope (ver
pasos/p6_assets.py): los planos de sitios distintos son independientes
y se dibujan en paralelo; los de un mismo sitio, en orden de vídeo.
El precio es plano (~$0.015 por imagen); el medidor de coste lleva la
cifra real.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

TIEMPO_FUERA_S = 300
BASE = "https://api.z.ai/api/paas/v4/images/generations"
LISTA = "https://api.z.ai/api/paas/v4/models"

#: calidad -> tamano. La API exige 512-2048 px y multiplos de 32; la
#: relacion de aspecto se mantiene en 16:9 (horizontal) o 9:16 (vertical).
CALIDADES = {
    "low": {"size": "1344x768", "etiqueta": "borrador"},
    "medium": {"size": "1536x864", "etiqueta": "estandar"},
    "high": {"size": "1728x960", "etiqueta": "detalle"},
}

TAMANO_VERTICAL = "768x1344"


class ErrorImagen(RuntimeError):
    """Fallo de generacion con texto para humano."""


def clave(claves: dict | None = None) -> str:
    if claves and claves.get("glm"):
        return str(claves["glm"])
    return os.environ.get("ESTUDIO_GL_KEY", "")


def probar(claves: dict | None = None) -> dict:
    """Prueba barata: lista de modelos con la misma clave (no gasta)."""
    clave_ = clave(claves)
    if not clave_:
        return {"ok": False, "detalle": "sin clave"}
    try:
        respuesta = requests.get(LISTA,
                                 headers={"Authorization": f"Bearer {clave_}"},
                                 timeout=30)
        if respuesta.status_code == 200:
            return {"ok": True,
                    "detalle": "clave valida (la misma de los textos)"}
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
        raise ErrorImagen("falta la clave de GLM para imagenes "
                          "(ESTUDIO_GL_KEY o secretos/claves.json)")
    ajustes = CALIDADES.get(calidad, CALIDADES["low"])
    tamano = TAMANO_VERTICAL if vertical else ajustes.get("size", "1344x768")
    prompt = f"{estilo}\n\n{descripcion}".strip() if estilo else descripcion
    try:
        respuesta = requests.post(
            BASE,
            headers={"Authorization": f"Bearer {clave_}",
                     "Content-Type": "application/json"},
            json={"model": "glm-image", "prompt": prompt,
                  "size": tamano},
            timeout=TIEMPO_FUERA_S)
    except requests.RequestException as fallo:
        raise ErrorImagen(f"red: {fallo}") from fallo
    if respuesta.status_code != 200:
        raise ErrorImagen(f"GLM {respuesta.status_code}: "
                          f"{respuesta.text[:300]}")
    try:
        datos = respuesta.json().get("data", [])
    except ValueError as fallo:
        raise ErrorImagen(f"GLM devolvio algo que no es JSON: "
                          f"{respuesta.text[:200]}") from fallo
    if not datos:
        raise ErrorImagen("GLM no devolvio imagen")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if datos[0].get("b64_json"):  # por si algún día la trae embebida
        destino.write_bytes(base64.b64decode(datos[0]["b64_json"]))
        return destino
    url = str(datos[0].get("url") or "")
    if not url:
        raise ErrorImagen("GLM no devolvio ni url ni imagen")
    try:
        imagen = requests.get(url, timeout=TIEMPO_FUERA_S)
    except requests.RequestException as fallo:
        raise ErrorImagen(f"red al bajar la imagen: {fallo}") from fallo
    if imagen.status_code != 200:
        raise ErrorImagen(f"al bajar la imagen GLM {imagen.status_code}")
    destino.write_bytes(imagen.content)
    return destino
