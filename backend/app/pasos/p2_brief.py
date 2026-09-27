"""Paso 2 — brief: de que va el vídeo y como se cuenta.

UNA llamada de LLM (rol "guion" o el proveedor configurado) que devuelve
estructura: tema, angulo, publico, puntos clave y tono. Es lo que encadena
guion y todo lo de abajo: corregir el brief rehace el guion.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun
from ..motores import llm

SISTEMA = """Eres un guionista de vídeos de divulgación en español.
Del material que te entregan extraes el encargo:
- tema: de qué va, en una frase
- angulo: el punto de vista o la promesa que engancha
- publico: a quién se lo cuentas
- puntos: 4 a 8 puntos clave en orden narrativo (cada uno, una frase)
- tono: cercano, divulgativo, sobrio... la palabra justa
- formato: min 20 y max 40, segundos de duración objetivo por escena
Responde SOLO JSON: {"tema": str, "angulo": str, "publico": str,
"puntos": [str], "tono": str, "formato": {"min": int, "max": int}}"""


def params_defecto() -> dict:
    return {}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 1, "imagenes": 0, "caracteres_voz": 0,
            "coste": None}   # None -> la API lo rellena con el proveedor activo


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    ingesta = proyecto_leer_datos(proyecto, "ingesta")
    texto = ingesta.get("texto", "")
    if not texto:
        raise ValueError("falta la ingesta: genera primero el paso anterior")
    trabajo.avance("leyendo el material y escribiendo el brief")
    llamada = llm.rol_config("guion", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = f"MATERIAL:\n\n{texto[:60000]}"
    llamada.contexto = "brief"
    llamada.proyecto = proyecto.id
    respuesta = llm.llamar_json(llamada, claves=comun.claves_actuales())
    if not isinstance(respuesta, dict) or not respuesta.get("puntos"):
        raise llm.ErrorLLM("el brief no trae puntos: respuesta invalida")
    respuesta.setdefault("formato", {"min": 20, "max": 40})
    trabajo.avance(f"brief listo: {len(respuesta['puntos'])} puntos, "
                   f"tono {respuesta.get('tono', '?')}")
    return respuesta


def proyecto_leer_datos(proyecto: Proyecto, paso: str):
    """Lee el datos.json de un paso anterior."""
    from ..nucleo.proyecto import leer_json
    return leer_json(proyecto.carpeta_paso(paso) / "datos.json", {}) or {}
