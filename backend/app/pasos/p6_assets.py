"""Paso 6 — assets: una imagen por escena, de UNA EN UNA.

Regla heredada del original: las tandas de imagenes NO van en paralelo —
cuestan dinero, y dos a la vez tardan el doble por imagen y pierden el
registro del gasto. La calidad se fija al crear el proyecto (entra en la
firma: cambiarla dejaria obsoleto solo lo de abajo).

La unidad de este paso es el PLANO (una escena = un plano en esta réplica).

El prompt de cada plano se ARMA con capas (regla de `pasos/direccion.py`):

    redactado  el prompt escrito entero (redactor), si existe MANDA
    + estilo   la guia del canal, la misma en todos
    + direccion que se ve en ESTE plano (la capa que distingue vecinos)
    + frase    la narracion de la escena

Y hay planos que no se pagan: si una escena lleva CARTELA decidida
(`params.unidades[escena].cartela`), no se genera imagen — el plano
entero es texto, y lo dibuja el grafismo del render.
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


def prompt_de(escena: dict, unidades: dict, estilo: str) -> str:
    """El encargo de imagen de un plano, armado por capas.

    La misma cuenta usa la pantalla para ENSEÑAR el prompt antes de
    pagar: lo que se ve es lo que se manda.
    """
    ficha = unidades.get(escena["id"]) or {}
    redactado = " ".join(str(ficha.get("prompt") or "").split())
    if redactado:
        return redactado  # el redactor escribe el encargo ENTERO
    direccion = " ".join(str(ficha.get("direccion") or "").split())
    piezas = []
    if estilo:
        piezas.append(f"Style: {estilo.strip()}")
    if direccion:
        piezas.append(direccion)
    frase = str(escena.get("visual") or escena.get("narracion", "")).strip()
    if frase:
        piezas.append(frase)
    return "\n".join(piezas) or "abstract neutral illustration"


def es_cartela(unidades: dict, escena_id: str) -> dict | None:
    ficha = unidades.get(escena_id) or {}
    cartela = ficha.get("cartela")
    return cartela if isinstance(cartela, dict) and cartela.get("plantilla") \
        else None


def ejecutar(proyecto: Proyecto, params: dict, trabajo,
             solo_escenas: list | None = None) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    if solo_escenas:
        escenas = [e for e in escenas if e["id"] in solo_escenas]
    unidades = params.get("unidades") or {}
    estilo = params.get("estilo", "")
    cartelas = [e for e in escenas if es_cartela(unidades, e["id"])]
    a_pagar = [e for e in escenas if not es_cartela(unidades, e["id"])]
    claves = comun.claves_actuales()
    if a_pagar and not imagen_openai.clave(claves):
        raise imagen_openai.ErrorImagen(
            "falta la clave de OpenAI para imagenes (Configuracion -> claves)")
    calidad = params.get("calidad", "low")
    carpeta = proyecto.carpeta_paso("assets") / "imagenes"
    planos = []
    for indice, escena in enumerate(escenas, start=1):
        trabajo.comprobar_cancelacion()
        cartela = es_cartela(unidades, escena["id"])
        if cartela:
            trabajo.avance(f"cartela {indice}/{len(escenas)}: {escena['id']} "
                           "(plano de texto: no se paga imagen)")
            planos.append({"escena": escena["id"], "cartela": cartela,
                           "imagen": None,
                           "prompt": "(cartela)"})
            continue
        trabajo.avance(f"imagen {indice}/{len(escenas)}: {escena['id']} "
                       "(una a una, cuesta dinero)")
        destino = carpeta / f"{escena['id']}.png"
        encargo = prompt_de(escena, unidades, estilo)
        imagen_openai.generar(
            encargo, destino, calidad=calidad, claves=claves, estilo="")
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="imagen",
            proveedor="openai", modelo="gpt-image-1", calidad=calidad,
            contexto=f"assets:{escena['id']}", proyecto_dir=proyecto.raiz)
        planos.append({"escena": escena["id"],
                       "imagen": f"pasos/assets/imagenes/{escena['id']}.png",
                       "prompt": encargo[:300]})
    if cartelas:
        trabajo.avance(f"{len(planos)} planos: {len(a_pagar)} imagen(es) + "
                       f"{len(cartelas)} cartela(s) de texto")
    else:
        trabajo.avance(f"{len(planos)} imagenes listas (calidad {calidad})")
    return {"planos": planos, "calidad": calidad,
            "cartelas": len(cartelas)}


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
