"""Configuración del servicio: claves, modelos por rol, tarifas, salud.

La UI JAMAS recibe una clave: solo etiqueta, ultimos 4 y estado (H4).
Los roles (guion/correccion/titulos/descripcion) eligen proveedor y
modelo sin tocar codigo — el enrutador multi-modelo de la réplica.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .. import seguridad
from ..config import AJUSTES
from ..motores import llm, voz_elevenlabs
from ..nucleo import coste as nucleo_coste
from ..nucleo.claves import (CATALOGO, enmascaradas, guardar_claves,
                             probar_claves)
from ..nucleo.proyecto import leer_json, escribir_json

router = APIRouter(prefix="/api", tags=["config"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]

ROL_INVALIDO = "rol desconocido; roles: guion, correccion, titulos, descripcion"
ROLES = ("guion", "correccion", "titulos", "descripcion")


# ------------------------------------------------------------------- salud

@router.get("/salud")
def salud() -> dict:
    """Latido público (lo monitors Coolify)."""
    return {"ok": True, "servicio": "estudio-video"}


# ------------------------------------------------------------------ claves

@router.get("/claves", dependencies=[_SESION])
def estado_claves() -> list[dict]:
    return enmascaradas(AJUSTES.carpeta_claves)


@router.put("/claves", dependencies=_MUTAR)
def poner_claves(cuerpo: dict) -> list[dict]:
    """Guarda SOLO las claves que llegan con valor; vacío no borra nada."""
    validas = {clave for clave, *_ in CATALOGO}
    nuevas = {k: str(v).strip() for k, v in (cuerpo or {}).items()
              if k in validas and str(v or "").strip()}
    if nuevas:
        guardar_claves(AJUSTES.carpeta_claves, nuevas)
    return enmascaradas(AJUSTES.carpeta_claves)


@router.post("/claves/probar", dependencies=[_SESION])
def probar() -> dict:
    """Prueba cada clave contra su servicio, sin coste (30 s por servicio)."""
    return probar_claves(AJUSTES.carpeta_claves)


# ------------------------------------------------------- modelos por rol

@router.get("/proveedores", dependencies=[_SESION])
def proveedores() -> dict:
    """Catálogo para la pantalla de Configuración."""
    return {"proveedores": llm.PROVEEDORES,
            "roles_defecto": llm.ROLES_DEFECTO}


@router.get("/ajustes", dependencies=[_SESION])
def ajustes() -> dict:
    return _ajustes_guardados()


@router.put("/ajustes/llm", dependencies=_MUTAR)
def poner_ajustes_llm(cuerpo: dict) -> dict:
    """Asigna proveedor/modelo a cada rol; se valida contra el catálogo."""
    datos = _ajustes_guardados()
    roles = (cuerpo or {}).get("llm", cuerpo or {})
    if not isinstance(roles, dict):
        raise HTTPException(400, "se esperaba {rol: {proveedor, modelo}}")
    limpios: dict[str, dict] = {}
    for rol, conf in roles.items():
        if rol not in ROLES:
            raise HTTPException(400, ROL_INVALIDO)
        if not isinstance(conf, dict):
            continue
        proveedor = str(conf.get("proveedor", ""))
        modelo = str(conf.get("modelo", ""))
        catalogo = llm.PROVEEDORES.get(proveedor)
        if not catalogo:
            raise HTTPException(400, f"proveedor desconocido: {proveedor!r}")
        if modelo and modelo not in catalogo["modelos"]:
            raise HTTPException(400, f"modelo {modelo!r} no está en {proveedor}")
        limpios[rol] = {"proveedor": proveedor, "modelo": modelo}
    datos["llm"] = limpios
    _guardar_ajustes(datos)
    return datos


def _ajustes_guardados() -> dict:
    datos = leer_json(Path(AJUSTES.datos) / "ajustes.json", {}) or {}
    if not isinstance(datos, dict):
        return {}
    return datos


def _guardar_ajustes(datos: dict) -> None:
    escribir_json(Path(AJUSTES.datos) / "ajustes.json", datos)


# ----------------------------------------------------------------- tarifas

@router.get("/coste/tarifas", dependencies=[_SESION])
def ver_tarifas() -> dict:
    return nucleo_coste.tarifas(AJUSTES.datos)


@router.put("/coste/tarifas", dependencies=_MUTAR)
def poner_tarifas(cuerpo: dict) -> dict:
    """Sobreescribe tarifas concretas en datos/tarifas.json (manda sobre
    los defectos)."""
    if not isinstance(cuerpo, dict) or not cuerpo:
        raise HTTPException(400, "se esperaba {clave: precio}")
    fichero = Path(AJUSTES.datos) / "tarifas.json"
    actuales = leer_json(fichero, {}) or {}
    actuales.update(cuerpo)
    escribir_json(fichero, actuales)
    return nucleo_coste.tarifas(AJUSTES.datos)


@router.get("/coste/global", dependencies=[_SESION])
def coste_global() -> dict:
    return nucleo_coste.global_(AJUSTES.datos)


# ------------------------------------------------------------------- voces

@router.get("/voces", dependencies=[_SESION])
def voces() -> list[dict]:
    """Catálogo de voces de ElevenLabs para el paso de voz."""
    from ..pasos import comun
    return voz_elevenlabs.voces(comun.claves_actuales())


@router.post("/voces/probar", dependencies=[_SESION])
def probar_voz() -> dict:
    from ..pasos import comun
    return voz_elevenlabs.probar(comun.claves_actuales())
