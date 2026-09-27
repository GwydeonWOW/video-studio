"""Rutas de autenticación: instalación, login, logout.

Flujo (docs/AUDITORIA.md H1): la sesión vive en el propio servicio, sin
proxy externo. Primer arranque sin ESTUDIO_HASH ni credenciales.json →
la UI muestra la pantalla de instalación y crea la contraseña aquí.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import seguridad
from ..seguridad import (NOMBRE_COOKIE, anotar_intento, crear_sesion,
                         exigir_origen, exigir_sesion, hash_contrasena,
                         intentos_de, ip_de, necesita_instalacion,
                         verificar_contrasena)

router = APIRouter(prefix="/api/auth", tags=["auth"])

MENSAJE_GENERICO = "usuario o contraseña incorrectos"


@router.get("/estado")
def estado(request: Request) -> dict:
    """Situación del login (público: lo consulta la pantalla de entrada)."""
    autenticado = (
        seguridad.AJUSTES.sin_login
        or not necesita_instalacion()
        and seguridad.sesion_valida(seguridad.token_de(request))
    )
    return {"instalacion": necesita_instalacion(),
            "sin_login": seguridad.AJUSTES.sin_login,
            "usuario": seguridad.AJUSTES.usuario,
            "autenticado": bool(autenticado)}


@router.post("/instalar", dependencies=[Depends(exigir_origen)])
def instalar(cuerpo: dict, request: Request, response: Response) -> dict:
    """Primer arranque: fija la contraseña y entra."""
    if not necesita_instalacion():
        raise HTTPException(409, "ya hay contraseña instalada")
    _limitar(request)
    contrasena = str(cuerpo.get("contrasena", ""))
    if len(contrasena) < seguridad.MIN_CONTRASENA:
        raise HTTPException(400, f"la contraseña debe tener al menos "
                                 f"{seguridad.MIN_CONTRASENA} caracteres")
    seguridad.guardar_credenciales(hash_contrasena(contrasena))
    response.set_cookie(NOMBRE_COOKIE, crear_sesion(),
                        httponly=True, samesite="lax", max_age=seguridad.VIDA_SESION_S)
    return {"ok": True, "usuario": seguridad.AJUSTES.usuario}


@router.post("/login", dependencies=[Depends(exigir_origen)])
def login(cuerpo: dict, request: Request, response: Response) -> dict:
    """Entrada con la contraseña única del estudio."""
    _limitar(request)
    guardado = seguridad.hash_actual()
    if not guardado:
        raise HTTPException(409, "el estudio no está instalado")
    contrasena = str(cuerpo.get("contrasena", ""))
    if not verificar_contrasena(contrasena, guardado):
        raise HTTPException(401, MENSAJE_GENERICO)
    response.set_cookie(NOMBRE_COOKIE, crear_sesion(),
                        httponly=True, samesite="lax", max_age=seguridad.VIDA_SESION_S)
    return {"ok": True, "usuario": seguridad.AJUSTES.usuario}


@router.post("/logout", dependencies=[Depends(exigir_origen)])
def logout(request: Request, response: Response) -> dict:
    seguridad.cerrar_sesion(seguridad.token_de(request))
    response.delete_cookie(NOMBRE_COOKIE)
    return {"ok": True}


def _limitar(request: Request) -> None:
    """Freno de fuerza bruta: 8 intentos / 15 min por IP."""
    if len(intentos_de(ip_de(request))) >= seguridad.INTENTOS_MAX:
        raise HTTPException(429, "demasiados intentos: espera un rato")
    anotar_intento(ip_de(request))
