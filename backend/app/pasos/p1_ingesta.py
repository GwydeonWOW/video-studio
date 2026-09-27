"""Paso 1 — ingesta: el material bruto que escribe el usuario.

Sin LLM y sin coste: guarda el texto y calcula el perfil (palabras,
parrafos, estimacion de duracion). Su firma encadena la de todo el grafo:
cambiar una coma del material deja obsoleto brief y todo lo de abajo.
"""
from __future__ import annotations

import math

from ..nucleo.proyecto import Proyecto
from . import comun


def params_defecto() -> dict:
    return {"texto": "", "titulo": ""}


def estimar(params: dict) -> dict:
    texto = comun.normalizar_texto(params.get("texto", ""))
    if not texto:
        return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
                "coste": 0.0}
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    texto = comun.normalizar_texto(params.get("texto", ""))
    if len(texto) < 40:
        raise ValueError("el material necesita al menos 40 caracteres: "
                         "pegar notas, un articulo, una cronologia o un guion")
    trabajo.avance("perfilando el material")
    parrafos = [p for p in texto.split("\n") if p.strip()]
    datos = {
        "titulo": (params.get("titulo") or "").strip() or parrafos[0][:60],
        "caracteres": len(texto),
        "palabras": comun.palabras(texto),
        "parrafos": len(parrafos),
        "duracion_estimada": comun.duracion_estimada(texto),
        "texto": texto,
    }
    trabajo.avance(f"material de {datos['palabras']} palabras "
                   f"(~{math.ceil(datos['duracion_estimada'])} s de narracion)")
    return datos
