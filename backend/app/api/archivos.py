"""Servicio de archivos de un proyecto: /a/{pid}/{ruta}.

Todo lo que la UI muestra (imágenes, audio, vídeo) pasa por aquí. La ruta
se une bajo la carpeta del proyecto y se verifica con realpath — un
`..` o una ruta absoluta no pasa (patrón ruta_contenida del original,
docs/AUDITORIA.md H8).

Soporta Range para que el navegador pueda buscar dentro del vídeo final
sin bajárselo entero.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from .. import seguridad
from ..config import AJUSTES

router = APIRouter(prefix="/a", tags=["archivos"])

TROCEO = 1024 * 512  # 512 KiB por trozo en el streaming

TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif",
         ".mp4": "video/mp4", ".webm": "video/webm",
         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
         ".json": "application/json", ".txt": "text/plain; charset=utf-8",
         ".vtt": "text/vtt", ".srt": "text/plain; charset=utf-8"}

_ENCAJE_RANGO = re.compile(r"bytes=(\d*)-(\d*)")


def proyecto_de(pid: str) -> Path:
    """Carpeta de un proyecto, validando el id contra el patrón."""
    from ..nucleo.proyecto import id_valido
    if not id_valido(pid):
        raise HTTPException(404, "proyecto desconocido")
    return AJUSTES.carpeta_proyectos / pid


def ruta_segura(pid: str, ruta: str) -> Path:
    """Ruta absoluta dentro del proyecto o 404 (nunca un listado)."""
    from ..nucleo.proyecto import ruta_contenida
    carpeta = proyecto_de(pid)
    try:
        destino = ruta_contenida(carpeta, *ruta.split("/"))
    except ValueError:
        raise HTTPException(404, "no existe") from None
    if not destino.is_file():
        raise HTTPException(404, "no existe")
    return destino


@router.get("/{pid}/{ruta:path}",
            dependencies=[Depends(seguridad.exigir_sesion)])
def servir(pid: str, ruta: str, request: Request) -> Response:
    origen = ruta_segura(pid, ruta)
    tipo = TIPOS.get(origen.suffix.lower(), "application/octet-stream")
    cabeceras = {"Cache-Control": "private, max-age=60",
                 "Content-Type": tipo}
    # el nombre del paso viaja como hint de descarga para el vídeo final
    if origen.suffix == ".mp4":
        cabeceras["Accept-Ranges"] = "bytes"

    rango = None
    if request is not None:
        crudo = request.headers.get("range", "")
        if crudo:
            encaje = _ENCAJE_RANGO.fullmatch(crudo.strip())
            if encaje:
                rango = (encaje.group(1), encaje.group(2))

    if rango is None:
        return FileResponse(origen, headers=cabeceras,
                            media_type=tipo)

    tamano = origen.stat().st_size
    inicio, fin = rango
    inicio = int(inicio) if inicio else 0
    fin = int(fin) if fin else tamano - 1
    fin = min(fin, tamano - 1)
    if inicio > fin or inicio >= tamano:
        raise HTTPException(416, "rango inválido",
                            headers={"Content-Range": f"bytes */{tamano}"})

    def trozos():
        with open(origen, "rb") as fichero:
            fichero.seek(inicio)
            restante = fin - inicio + 1
            while restante > 0:
                bloque = fichero.read(min(TROCEO, restante))
                if not bloque:
                    break
                restante -= len(bloque)
                yield bloque

    return StreamingResponse(
        trozos(), status_code=206,
        media_type=tipo,
        headers={**cabeceras,
                 "Content-Range": f"bytes {inicio}-{fin}/{tamano}",
                 "Content-Length": str(fin - inicio + 1)})
