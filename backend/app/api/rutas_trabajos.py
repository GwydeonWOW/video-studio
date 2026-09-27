"""Trabajos en segundo plano: consulta, cancelación y eventos SSE.

El flujo de eventos imita al original: sondeo del gestor cada segundo y
emisión SSE solo cuando algo cambia, con latido anti-proxy. El navegador
usa EventSource; si el proxy de Coolify trocea el flujo, la UI cae a
sondeo del propio GET /{tid}.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import seguridad
from ..config import AJUSTES
from ..nucleo.trabajos import GestorTrabajos

router = APIRouter(prefix="/api/trabajos", tags=["trabajos"])

#: Un solo gestor para todo el servicio; la cola es POR PROYECTO.
GESTOR = GestorTrabajos(tope_s=AJUSTES.tope_trabajo_s)

INTERVALO_SSE = 1.0
CABECERAS_SSE = {"Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no"}


@router.get("", dependencies=[Depends(seguridad.exigir_sesion)])
def listar(proyecto: str | None = None) -> list[dict]:
    return GESTOR.listar(proyecto)


@router.get("/{tid}", dependencies=[Depends(seguridad.exigir_sesion)])
def detalle(tid: str) -> dict:
    try:
        return _ficha_completa(tid)
    except KeyError:
        raise HTTPException(404, "trabajo desconocido") from None


@router.post("/{tid}/cancelar",
             dependencies=[Depends(seguridad.exigir_sesion),
                           Depends(seguridad.exigir_origen)])
def cancelar(tid: str) -> dict:
    try:
        return GESTOR.cancelar(tid)
    except KeyError:
        raise HTTPException(404, "trabajo desconocido") from None


@router.get("/{tid}/eventos", dependencies=[Depends(seguridad.exigir_sesion)])
async def eventos(tid: str, desde: int = 0) -> StreamingResponse:
    """SSE: estado + líneas de avance hasta que el trabajo termina."""
    try:
        GESTOR.estado(tid)
    except KeyError:
        raise HTTPException(404, "trabajo desconocido") from None

    async def flujo():
        indice = max(0, int(desde))
        ultimo: tuple = ()
        # el trabajo puede tardar horas: el bucle vive mientras exista
        while True:
            try:
                ficha = GESTOR.estado(tid)
            except KeyError:
                break
            indice_nuevo, nuevos = GESTOR.eventos_desde(tid, indice)
            actual = (ficha["estado"], indice_nuevo)
            if nuevos:
                yield _sse("avance", {"desde": indice, "eventos": nuevos})
                indice = indice_nuevo
            if actual != ultimo:
                yield _sse("estado", ficha)
                ultimo = actual
            if ficha["estado"] in ("hecho", "fallo", "cancelado"):
                yield _sse("fin", _ficha_completa(tid))
                return
            yield ": latido\n\n"
            await asyncio.sleep(INTERVALO_SSE)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers=CABECERAS_SSE)


def _ficha_completa(tid: str) -> dict:
    """Ficha del trabajo + todas sus líneas de evento."""
    ficha = GESTOR.estado(tid)
    _, eventos = GESTOR.eventos_desde(tid, 0)
    ficha["lineas"] = eventos[-100:]
    if ficha["estado"] == "hecho":
        trabajo = GESTOR._trabajos.get(tid)
        ficha["resultado"] = trabajo.resultado if trabajo else None
    return ficha


def _sse(evento: str, datos) -> str:
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False)}\n\n"
