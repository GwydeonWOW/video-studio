"""El chat del asistente: charlas, mensajes, cancelación y la foto de estado.

La burbuja de abajo a la derecha de la pantalla (ver pasos/asistente.py,
que es el motor). Aquí vive lo que habla HTTP:

    GET  /api/asistente                       puedo contestar, y con qué
    POST /api/asistente/probar                prueba la clave del rol
    GET  /api/asistente/foto                  la foto del estado, en texto
    POST /api/asistente/charlas               abre una charla
    GET  /api/asistente/charlas/{cid}         sus turnos (la pantalla sondea)
    DELETE /api/asistente/charlas/{cid}       la cierra
    POST /api/asistente/charlas/{cid}/mensajes    pregunta (202: sigue con GET)
    POST /api/asistente/charlas/{cid}/cancelar   para la respuesta en marcha

Una pregunta es un 202 porque la respuesta puede tardar un minuto: el turno
corre en el servidor y la pantalla lo sigue con GET de la charla cada poco.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from .. import seguridad
from ..config import AJUSTES
from ..motores import llm
from ..nucleo.claves import CATALOGO, leer_claves
from ..nucleo.coste import de_proyecto
from ..nucleo.estado import Estado, GRAFO
from ..nucleo.proyecto import Proyecto, leer_jsonl
from ..pasos import asistente
from .rutas_trabajos import GESTOR

router = APIRouter(prefix="/api/asistente", tags=["asistente"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]


def _asistente():
    return asistente


def _charla_o_404(cid: str):
    charla = asistente.obtener(cid)
    if charla is None:
        raise HTTPException(
            404, f"no hay ninguna charla '{cid}': se habrá cerrado o el "
                 f"servicio se ha reiniciado. Abre una nueva.")
    return charla


# ------------------------------------------------------------------ el estado

@router.get("", dependencies=[_SESION])
def estado() -> dict:
    """Si el asistente puede contestar ahora, y con qué modelo."""
    return asistente.estado()


@router.post("/probar", dependencies=[_SESION])
def probar() -> dict:
    """Prueba la clave del rol del asistente contra su servicio."""
    from ..pasos.comun import ajustes_llm, claves_actuales
    llamada = llm.rol_config(asistente.ROL, ajustes_llm())
    resultado = llm.probar(llamada.proveedor, claves_actuales())
    return {**resultado, "proveedor": llamada.proveedor,
            "modelo": llamada.modelo, "estado": asistente.estado()}


@router.get("/foto", dependencies=[_SESION])
def foto(proyecto: str = Query(default=""),
         pantalla: dict | None = Body(default=None)) -> dict:
    """Lo que el asistente ve del estudio ahora mismo, en texto y sin claves."""
    return {"foto": foto_del_estudio(proyecto, pantalla)}


# ------------------------------------------------------------------- charlas

@router.post("/charlas", status_code=201, dependencies=_MUTAR)
def abrir() -> dict:
    """Abre una charla vacía con el asistente."""
    return asistente.nueva().ver()


@router.get("/charlas/{cid}", dependencies=[_SESION])
def leer(cid: str) -> dict:
    """Los turnos de una charla; el último dice si sigue pensando."""
    return _charla_o_404(cid).ver()


@router.post("/charlas/{cid}/mensajes", status_code=202, dependencies=_MUTAR)
def preguntar(cid: str, cuerpo: dict | None = Body(default=None)) -> dict:
    """Manda una pregunta; la respuesta se sigue con GET de la charla."""
    charla = _charla_o_404(cid)
    datos = cuerpo or {}
    texto = str(datos.get("texto") or "").strip()
    if not texto:
        raise HTTPException(400, "escribe algo que preguntar")
    # SIN CLAVE NO SE PREGUNTA, y se dice antes de lanzar nada.
    ficha_estado = asistente.estado()
    if not ficha_estado["listo"]:
        raise HTTPException(409, "el asistente no puede contestar todavía: "
                                 + ficha_estado["motivo"])
    pid = str(datos.get("proyecto") or "").strip()
    foto = foto_del_estudio(pid, datos.get("pantalla"))
    try:
        return charla.preguntar(texto, foto, pid=pid)
    except asistente.Ocupada as fallo:
        raise HTTPException(409, str(fallo)) from fallo
    except asistente.ErrorAsistente as fallo:
        raise HTTPException(400, str(fallo)) from fallo


@router.post("/charlas/{cid}/cancelar", dependencies=_MUTAR)
def cancelar(cid: str) -> dict:
    """Para la respuesta que esté en marcha en esa charla."""
    charla = _charla_o_404(cid)
    return {"cancelado": charla.cancelar(), "charla": charla.ver()}


@router.delete("/charlas/{cid}", dependencies=_MUTAR)
def cerrar(cid: str) -> dict:
    """Cierra una charla; lo que estuviera contestando se cancela."""
    return {"cerrada": asistente.olvidar(cid)}


# -------------------------------------------------------------- la foto

def foto_del_estudio(pid: str, pantalla: dict | None = None) -> str:
    """El estado del estudio ahora mismo, en texto, para el asistente.

    Cada trozo va protegido por su cuenta: que no se pueda leer el coste
    no puede dejar sin contestar una pregunta sobre las claves. Y aquí no
    viaja NINGUNA clave: solo si está puesta o no.
    """
    lineas = [f"fecha y hora: {time.strftime('%Y-%m-%d %H:%M:%S')}",
              f"carpeta de datos: {AJUSTES.datos}",
              f"modo simulado: {'sí' if asistente.simulado() else 'no'}"]

    # -- claves (sin ninguna dentro)
    try:
        claves = leer_claves(AJUSTES.carpeta_claves)
        trozos = []
        for clave, etiqueta, _variable, uso in CATALOGO:
            trozos.append(f"{etiqueta} ({uso}): "
                          + ("puesta" if claves.get(clave) else "SIN PONER"))
        lineas.append("claves: " + "; ".join(trozos))
    except Exception as fallo:                          # noqa: BLE001
        lineas.append(f"claves: no se han podido leer ({fallo})")

    try:
        lineas.append(f"ajustes: calidad de imagen para los vídeos nuevos = "
                      f"{AJUSTES.calidad_imagen}")
    except Exception as fallo:                          # noqa: BLE001
        lineas.append(f"ajustes: no se han podido leer ({fallo})")

    # -- los proyectos que hay (los talleres del modo light no cuentan)
    try:
        proyectos = [p for p in Proyecto.listar(AJUSTES.carpeta_proyectos)
                     if not p.leer().get("taller")]
        lineas.append(f"proyectos (vídeos): {len(proyectos)}")
        for proyecto in proyectos[:15]:
            datos = proyecto.leer()
            lineas.append(f"  - {proyecto.id} «{datos.get('nombre', proyecto.id)}», "
                          f"actualizado {datos.get('actualizado') or '?'}")
    except Exception as fallo:                          # noqa: BLE001
        lineas.append(f"proyectos: no se han podido listar ({fallo})")

    # -- el proyecto que la pantalla tiene abierto
    pid = str(pid or "").strip()
    if pid:
        try:
            proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
            datos = proyecto.leer()
            estado = Estado(proyecto)
            lineas.append(f"\nPROYECTO ABIERTO EN PANTALLA: {proyecto.id} "
                          f"«{datos.get('nombre', proyecto.id)}»")
            for paso in GRAFO:
                ficha = estado.paso(paso)
                lineas.append(
                    f"  paso {paso}: estado {estado.estado_de(paso)}"
                    + (f", versión activa v{ficha.get('version', 0)}"
                       if ficha.get("version") else ", sin versión")
                    + (f", {len(estado.unidades_obsoletas(paso))} unidades "
                       f"obsoletas"
                       if estado.unidades_obsoletas(paso) else ""))
            trabajos = GESTOR.listar(pid)[-10:]
            if trabajos:
                lineas.append("  últimos trabajos (el más viejo primero):")
                for trabajo in trabajos:
                    lineas.append(
                        f"    - {trabajo['id']} [{trabajo['paso']}] "
                        f"{trabajo['estado']}"
                        + (f", ERROR: {str(trabajo.get('error'))[:700]}"
                           if trabajo.get("error") else ""))
            eventos = leer_jsonl(proyecto.fichero_bitacora)[-40:]
            if eventos:
                lineas.append("  últimos eventos de la bitácora del proyecto:")
                for evento in eventos:
                    lineas.append(f"    {evento}")
            try:
                coste = de_proyecto(proyecto.raiz)
                lineas.append(f"  coste del vídeo: "
                              f"{coste.get('coste', 0.0):.4f} USD")
            except Exception as fallo:                  # noqa: BLE001
                lineas.append(f"  coste del vídeo: no se ha podido leer ({fallo})")
        except FileNotFoundError:
            lineas.append(f"\nproyecto abierto en pantalla: {pid} -> no existe")
        except Exception as fallo:                      # noqa: BLE001
            lineas.append(f"\nproyecto abierto en pantalla: {pid} -> no se ha "
                          f"podido leer ({fallo})")

    # -- trabajos vivos en cualquier proyecto
    try:
        vivos = [t for t in GESTOR.listar()
                 if t["estado"] in ("en_cola", "ejecutando")]
        for trabajo in vivos:
            lineas.append(f"trabajo en marcha ({trabajo['proyecto']}): "
                          f"{trabajo['id']} [{trabajo['paso']}] "
                          f"{trabajo['estado']}")
    except Exception as fallo:                          # noqa: BLE001
        lineas.append(f"trabajos: no se han podido leer ({fallo})")

    # -- lo que la pantalla tiene delante
    if isinstance(pantalla, dict):
        lineas.append("\nLO QUE LA PERSONA TIENE EN PANTALLA:")
        if pantalla.get("pestana"):
            lineas.append(f"  pestaña: {pantalla['pestana']}")
        if pantalla.get("url"):
            lineas.append(f"  url: {str(pantalla['url'])[:300]}")
        errores = pantalla.get("errores")
        if isinstance(errores, dict) and errores:
            lineas.append("  errores a la vista (por paso):")
            for paso, texto in list(errores.items())[:8]:
                lineas.append(f"    - {paso}: {str(texto)[:800]}")
    return "\n".join(lineas)
