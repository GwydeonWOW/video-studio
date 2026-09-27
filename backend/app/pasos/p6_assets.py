"""Paso 6 — assets: una imagen por escena, de UNA EN UNA.

Regla heredada del original: las tandas de imagenes NO van en paralelo —
cuestan dinero, y dos a la vez tardan el doble por imagen y pierden el
registro del gasto. La calidad se fija al crear el proyecto (entra en la
firma: cambiarla dejaria obsoleto solo lo de abajo).

La unidad de este paso es el PLANO (una escena = un plano en esta réplica).
"""
from __future__ import annotations

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import imagen_openai


def params_defecto() -> dict:
    return {"calidad": AJUSTES.calidad_imagen, "estilo": ""}


def estimar(params: dict) -> dict:
    guion = p2_brief.proyecto_leer_datos  # noqa: F841 (firma homogenea)
    return {"llamadas_llm": 0, "imagenes": "?", "caracteres_voz": 0,
            "coste": None}


def ejecutar(proyecto: Proyecto, params: dict, trabajo,
             solo_escenas: list | None = None) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    if solo_escenas:
        escenas = [e for e in escenas if e["id"] in solo_escenas]
    claves = comun.claves_actuales()
    if not imagen_openai.clave(claves):
        raise imagen_openai.ErrorImagen(
            "falta la clave de OpenAI para imagenes (Configuracion -> claves)")
    calidad = params.get("calidad", "low")
    estilo = params.get("estilo", "")
    carpeta = proyecto.carpeta_paso("assets") / "imagenes"
    planos = []
    for indice, escena in enumerate(escenas, start=1):
        trabajo.comprobar_cancelacion()
        trabajo.avance(f"imagen {indice}/{len(escenas)}: {escena['id']} "
                       "(una a una, cuesta dinero)")
        destino = carpeta / f"{escena['id']}.png"
        imagen_openai.generar(
            escena.get("visual", escena.get("titulo", "sin descripcion")),
            destino, calidad=calidad, claves=claves, estilo=estilo)
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="imagen",
            proveedor="openai", modelo="gpt-image-1", calidad=calidad,
            contexto=f"assets:{escena['id']}", proyecto_dir=proyecto.raiz)
        planos.append({"escena": escena["id"],
                       "imagen": f"pasos/assets/imagenes/{escena['id']}.png",
                       "prompt": escena.get("visual", "")[:300]})
    trabajo.avance(f"{len(planos)} imagenes listas (calidad {calidad})")
    return {"planos": planos, "calidad": calidad}


def regenerar_plano(proyecto: Proyecto, escena_id: str, params: dict) -> dict:
    """Regenera UN plano bajo demanda (boton de la imagen)."""
    resultado = ejecutar(proyecto, params, _TrabajoMudo(), solo_escenas=[escena_id])
    return resultado["planos"][0]


class _TrabajoMudo:
    """Avance que no va a ninguna parte (llamadas sueltas fuera de cola)."""

    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass
