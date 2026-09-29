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

ROLES = ("guion", "correccion", "titulos", "descripcion",
         "direccion", "redactor", "cartelas", "repaso",
         "catalogo", "conservacion", "guia_estilo", "asistente")
ROL_INVALIDO = ("rol desconocido; roles: " + ", ".join(ROLES))

# ajustes que acepta PUT /api/ajustes (lo demás tiene su ruta propia)
PERMITIDOS = ("onboarding_visto",)


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


# ------------------------------------------------------------ codex (OAuth)

@router.get("/codex", dependencies=[_SESION])
def codex_estado() -> dict:
    """La sesion de ChatGPT para textos: conectada, quien y hasta cuando."""
    from ..motores import codex_oauth
    return codex_oauth.estado(AJUSTES.carpeta_claves)


@router.post("/codex/conectar", dependencies=_MUTAR)
def codex_conectar() -> dict:
    """Arranca el flujo de dispositivo: devuelve lo que hay que mostrar."""
    from ..motores import codex_oauth
    try:
        return codex_oauth.iniciar(AJUSTES.carpeta_claves)
    except codex_oauth.ErrorCodex as fallo:
        raise HTTPException(502, str(fallo)) from fallo


@router.post("/codex/sondeo", dependencies=_MUTAR)
def codex_sondeo() -> dict:
    """Una vuelta de polling del flujo (pendiente | conectado | ...)."""
    from ..motores import codex_oauth
    try:
        return codex_oauth.sondear(AJUSTES.carpeta_claves)
    except codex_oauth.ErrorCodex as fallo:
        raise HTTPException(502, str(fallo)) from fallo


@router.delete("/codex", dependencies=_MUTAR)
def codex_desconectar() -> dict:
    """Borra la sesion local de la cuenta ChatGPT."""
    from ..motores import codex_oauth
    try:
        return codex_oauth.desconectar(AJUSTES.carpeta_claves)
    except codex_oauth.ErrorCodex as fallo:
        raise HTTPException(502, str(fallo)) from fallo


# ------------------------------------------------------- modelos por rol

@router.get("/proveedores", dependencies=[_SESION])
def proveedores() -> dict:
    """Catálogo para la pantalla de Configuración."""
    return {"proveedores": llm.PROVEEDORES,
            "roles_defecto": llm.ROLES_DEFECTO}


@router.get("/ajustes", dependencies=[_SESION])
def ajustes() -> dict:
    return _ajustes_publicos()


@router.put("/ajustes", dependencies=_MUTAR)
def poner_ajustes(cuerpo: dict) -> dict:
    """Ajustes generales del servicio, con lista blanca (lo demás tiene su
    propia ruta: modelos en /ajustes/llm, tarifas en /coste/tarifas)."""
    nuevos = cuerpo or {}
    if not isinstance(nuevos, dict):
        raise HTTPException(400, "se esperaba {ajuste: valor}")
    if "onboarding_visto" in nuevos and not isinstance(
            nuevos["onboarding_visto"], bool):
        raise HTTPException(400, "onboarding_visto debe ser true o false")
    desconocidas = sorted(set(nuevos) - set(PERMITIDOS))
    if desconocidas:
        raise HTTPException(400, "ajuste desconocido: " + ", ".join(desconocidas))
    datos = _ajustes_guardados()
    for clave in PERMITIDOS:
        if clave in nuevos:
            datos[clave] = nuevos[clave]
    _guardar_ajustes(datos)
    return _ajustes_publicos()


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
    return _ajustes_publicos()


def _ajustes_guardados() -> dict:
    datos = leer_json(Path(AJUSTES.datos) / "ajustes.json", {}) or {}
    if not isinstance(datos, dict):
        return {}
    return datos


def _ajustes_publicos() -> dict:
    """Lo que ve la UI: los guardados con los ajustes de obra normalizados.

    `onboarding_visto` no está en el fichero hasta que alguien cierra la
    guía: ausente es «aún no la ha visto», no «ya la vio».
    """
    datos = dict(_ajustes_guardados())
    datos.setdefault("onboarding_visto", False)
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


# ------------------------------------------------------------ estadísticas

@router.get("/estadisticas", dependencies=[_SESION])
def estadisticas() -> dict:
    """Tiempos reales por paso, entre todos los proyectos (de la bitácora).

    La cola es por proyecto y en serie: emparejar cada «paso_lanzado» con el
    «paso_completado» que le sigue da la duración real de cada corrida.
    """
    from datetime import datetime

    from ..nucleo.proyecto import Proyecto, leer_jsonl

    tiempos: dict[str, list[float]] = {}
    corridas = 0
    proyectos = 0
    for proyecto in Proyecto.listar(AJUSTES.carpeta_proyectos):
        eventos = leer_jsonl(proyecto.fichero_bitacora)
        if not eventos:
            continue
        proyectos += 1
        pendientes: dict[str, str] = {}
        for evento in eventos:
            nombre = evento.get("evento", "")
            paso = str(evento.get("paso", ""))
            t = str(evento.get("t", ""))
            if nombre == "paso_lanzado" and paso:
                pendientes[paso] = t          # la última lanzada manda
            elif nombre == "paso_completado" and paso in pendientes:
                try:
                    # ahora() acaba en «Z»: fromisoformat (<3.11) no la traga
                    inicio = datetime.fromisoformat(
                        pendientes.pop(paso).rstrip("Z"))
                    fin = datetime.fromisoformat(t.rstrip("Z"))
                    segundos = (fin - inicio).total_seconds()
                except ValueError:
                    continue
                if 0 < segundos < AJUSTES.tope_trabajo_s:
                    tiempos.setdefault(paso, []).append(segundos)
                    corridas += 1

    def _resumen(valores: list[float]) -> dict:
        ordenados = sorted(valores)
        n = len(ordenados)
        return {"n": n,
                "media_s": round(sum(ordenados) / n, 1),
                "mediana_s": round(ordenados[n // 2], 1),
                "max_s": round(ordenados[-1], 1)}

    return {"proyectos": proyectos, "corridas": corridas,
            "por_paso": {paso: _resumen(valores)
                         for paso, valores in sorted(tiempos.items())}}


@router.post("/estadisticas/valoracion", status_code=201, dependencies=_MUTAR)
def valorar_ajuste(cuerpo: dict) -> dict:
    """Anota si el resultado de un ajuste gustó o no (aprende de lo que sale)."""
    from ..nucleo.proyecto import ahora, anadir_jsonl

    ajuste = str((cuerpo or {}).get("ajuste", "")).strip()
    if not ajuste:
        raise HTTPException(400, "falta el ajuste a valorar")
    gusto = (cuerpo or {}).get("gusto") is True
    registro_valoracion = {"t": ahora(), "ajuste": ajuste, "gusto": gusto,
                           "nota": str((cuerpo or {}).get("nota", ""))[:500]}
    anadir_jsonl(Path(AJUSTES.datos) / "valoraciones.jsonl", registro_valoracion)
    return registro_valoracion


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
