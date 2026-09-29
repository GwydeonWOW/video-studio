"""Estilo del canal: definición única que hereda cada vídeo nuevo.

Además de los valores de siempre, aquí vive el KIT VISUAL: las imágenes
de referencia que sube quien ya sabe cómo debe verse el canal. No es un
buzón (como el del modo light): este kit es canónico, persiste en
`datos/_kit_canal/` y cada proyecto nuevo lo hereda SEMBRADO en
`estilo/aportadas/` — la guía de estilo se escribe mirándolo.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import seguridad
from ..config import AJUSTES
from ..nucleo import estilo as nucleo_estilo
from ..nucleo.proyecto import ruta_contenida
from .rutas_presets import _servir_aportada, guardar_imagenes

router = APIRouter(prefix="/api/estilo", tags=["estilo"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]


@router.get("", dependencies=[_SESION])
def leer_estilo() -> dict:
    return nucleo_estilo.leer(AJUSTES.datos)


@router.put("", dependencies=_MUTAR)
def guardar_estilo(cuerpo: dict) -> dict:
    return nucleo_estilo.guardar(AJUSTES.datos, cuerpo or {})


# ------------------------------------------------------- kit visual del canal
#
# Subir/quitar imágenes reference del look del canal. Los nombres viven
# en estilo.json ("kit", en orden) y los bytes en datos/_kit_canal/.

@router.get("/imagenes", dependencies=[_SESION])
def listar_kit() -> dict:
    """El kit guardado: nombres en orden, para las miniaturas."""
    estilo = nucleo_estilo.leer(AJUSTES.datos)
    carpeta = nucleo_estilo.carpeta_kit(AJUSTES.datos)
    imagenes = []
    for nombre in estilo["kit"]:
        ruta = carpeta / nombre
        if ruta.is_file():
            imagenes.append({"nombre": nombre, "bytes": ruta.stat().st_size})
    return {"imagenes": imagenes, "tope": nucleo_estilo.MAX_KIT}


@router.post("/imagenes", dependencies=_MUTAR)
def subir_kit(cuerpo: dict) -> dict:
    """Añade imágenes al kit (base64 en JSON, como las capturas).

    Persisten en el acto: esto no es un buzón, es el kit del canal. Lo
    que no pasa el filtro vuelve en `avisos` y el resto se queda.
    """
    entradas = (cuerpo or {}).get("imagenes")
    if not isinstance(entradas, list):
        entradas = []
    estilo = nucleo_estilo.leer(AJUSTES.datos)
    hueco = max(nucleo_estilo.MAX_KIT - len(estilo["kit"]), 0)
    avisos = []
    if len(entradas) > hueco:
        avisos.append(f"el tope es {nucleo_estilo.MAX_KIT}: se suben "
                      f"{hueco} y se dejan {len(entradas) - hueco}")
    aceptadas, avisos_subida = guardar_imagenes(
        entradas[:hueco] if hueco else [],
        nucleo_estilo.carpeta_kit(AJUSTES.datos))
    if aceptadas:
        nucleo_estilo.guardar_nombres_kit(
            AJUSTES.datos, estilo["kit"] + [a["nombre"] for a in aceptadas])
    return {"imagenes": aceptadas, "avisos": avisos + avisos_subida,
            "kit": nucleo_estilo.leer(AJUSTES.datos)["kit"],
            "tope": nucleo_estilo.MAX_KIT}


@router.get("/imagenes/{nombre}", dependencies=[_SESION])
def leer_imagen_kit(nombre: str):
    """Una imagen del kit, con el candado de siempre."""
    return _servir_aportada(nucleo_estilo.carpeta_kit(AJUSTES.datos), nombre)


@router.delete("/imagenes/{nombre}", dependencies=_MUTAR)
def borrar_imagen_kit(nombre: str) -> dict:
    """Quita una imagen del kit (fichero y lista)."""
    carpeta = nucleo_estilo.carpeta_kit(AJUSTES.datos)
    try:
        ruta = ruta_contenida(carpeta, nombre)
    except ValueError:
        raise HTTPException(404, "fichero desconocido")
    estilo = nucleo_estilo.leer(AJUSTES.datos)
    if ruta.parent == carpeta and ruta.is_file() and ruta.name in estilo["kit"]:
        ruta.unlink()
        nucleo_estilo.guardar_nombres_kit(
            AJUSTES.datos, [n for n in estilo["kit"] if n != ruta.name])
        return {"borrada": ruta.name,
                "kit": nucleo_estilo.leer(AJUSTES.datos)["kit"]}
    raise HTTPException(404, "fichero desconocido")
