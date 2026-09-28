"""Estilo del canal: definición única que hereda cada vídeo nuevo."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import seguridad
from ..config import AJUSTES
from ..nucleo import estilo as nucleo_estilo

router = APIRouter(prefix="/api/estilo", tags=["estilo"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]


@router.get("", dependencies=[_SESION])
def leer_estilo() -> dict:
    return nucleo_estilo.leer(AJUSTES.datos)


@router.put("", dependencies=_MUTAR)
def guardar_estilo(cuerpo: dict) -> dict:
    return nucleo_estilo.guardar(AJUSTES.datos, cuerpo or {})
