"""Paso 7 — callouts: rótulos y acentos sobre el vídeo.

UNA llamada de LLM (rol "titulos") que, por escena, pule el texto en
pantalla y decide si lleva acento destacado. Cada rótulo hereda su ventana
temporal de las MARCAS DE PALABRA de la voz: aparece cuando la narración
llega a su idea y se va antes de estorbar.

La unidad sigue siendo la escena.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

SISTEMA = """Eres editor de rótulos de vídeo en español. Por cada escena
recibes su narración, su rótulo propuesto y las marcas de tiempo por
palabra. Devuelves por escena UN rótulo de 2 a 5 palabras y el instante
(en segundos, dentro de la duración de esa escena) en que debe aparecer.

Reglas: sin puntos finales, sin gritar en mayúsculas, el rótulo nombra la
idea clave. Si la escena no aporta idea mostrable, rótulo vacío "".
Responde SOLO JSON: {"rotulos": [{"id": "S001", "texto": str,
"aparece": float}, ...]}"""


def params_defecto() -> dict:
    return {"duracion_max": 4.0}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 1, "imagenes": 0, "caracteres_voz": 0,
            "coste": None}


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    if not voz.get("escenas") or not guion.get("escenas"):
        raise ValueError("falta guion o voz: genera primero los pasos previos")
    trabajo.avance("escribiendo rotulos")
    vinetas = []
    palabras_de = {p["id"]: p.get("palabras", []) for p in voz["escenas"]}
    duracion_de = {p["id"]: p["duracion"] for p in voz["escenas"]}
    for escena in guion["escenas"]:
        palabras = palabras_de.get(escena["id"], [])
        # resumen de marcas: primer/ultimo tercio, sin volcar todo
        marcas = ([(w["palabra"], w["inicio"], w["fin"]) for w in palabras]
                  [:60])
        vinetas.append({
            "id": escena["id"],
            "titulo": escena.get("titulo", ""),
            "narracion": escena["narracion"],
            "propuesta": escena.get("texto_pantalla", ""),
            "duracion": duracion_de.get(escena["id"], 0),
            "palabras": marcas,
        })
    llamada = llm.rol_config("titulos", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = _a_json(vinetas)
    llamada.contexto = "callouts"
    llamada.proyecto = proyecto.id
    respuesta = llm.llamar_json(llamada, claves=comun.claves_actuales())
    propuestas = (respuesta.get("rotulos", [])
                  if isinstance(respuesta, dict) else respuesta)
    rotulos = []
    duracion_max = float(params.get("duracion_max", 4.0))
    for item in propuestas:
        escena_id = comun.limpiar_id(item.get("id", ""))
        texto = comun.normalizar_texto(item.get("texto", ""))[:60]
        if not texto:
            continue
        try:
            aparece = max(0.0, float(item.get("aparece", 0.0)))
        except (TypeError, ValueError):
            aparece = 0.0
        total_escena = duracion_de.get(escena_id, aparece + duracion_max)
        # el rotulo no puede empezar tan tarde que no se ve
        aparece = min(aparece, max(0.0, total_escena - 1.0))
        rotulos.append({"id": escena_id, "texto": texto,
                        "aparece": round(aparece, 2),
                        "dura": duracion_max})
    trabajo.avance(f"{len(rotulos)} rotulos colocados")
    return {"rotulos": rotulos}


def _a_json(valor) -> str:
    import json
    return json.dumps(valor, ensure_ascii=False)
