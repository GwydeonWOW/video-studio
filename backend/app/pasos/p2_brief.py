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


#: Código de idioma -> nombre EN INGLÉS para el prompt de imagen. Al
#: generador se le habla en inglés —la guía, las reglas de la casa y la
#: descripción del plano van en inglés— así que decirle «español» ahí
#: dentro es pedirle que adivine. UNA sola tabla (regla del original):
#: dos tablas de idiomas se desincronizan el día que se añada uno.
#: Vacío cuando no lo conoce, y es deliberado: mejor no decir nada que
#: colarle un código de dos letras, que lo dibujaría tan tranquilo.
NOMBRE_IDIOMA_EN = {"es": "Spanish", "en": "English"}


def nombre_idioma_en(idioma: str) -> str:
    codigo = str(idioma or "").strip().lower()
    return NOMBRE_IDIOMA_EN.get(codigo, "")


def params_defecto() -> dict:
    return {}


def linea_canal(params: dict) -> str:
    """La línea editorial del canal, tal como se la cuenta al modelo.

    Viene de los params sembrados con el estilo del canal (o vacía si el
    proyecto no la tiene: los proyectos viejos siguen igual)."""
    partes = []
    tono = str(params.get("tono", "") or "").strip()
    if tono:
        partes.append(f"- Tono: {tono}.")
    idioma = str(params.get("idioma", "") or "").strip().lower()
    if idioma == "en":
        partes.append('- Idioma de la narración: inglés ("angulo", "publico" '
                      'y "tono" del JSON también en inglés).')
    try:
        ritmo_min = int(params.get("ritmo_min") or 0)
        ritmo_max = int(params.get("ritmo_max") or 0)
    except (TypeError, ValueError):
        ritmo_min = ritmo_max = 0
    if ritmo_min > 0 and ritmo_max >= ritmo_min:
        partes.append(f"- Cadencia del canal: entre {ritmo_min} y {ritmo_max} "
                      "segundos por escena (respétalo en \"formato\").")
    if not partes:
        return ""
    return "LINEA DEL CANAL (todos los vídeos del canal la siguen):\n" + \
        "\n".join(partes)


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
    linea = linea_canal(params)
    llamada.instruccion = (f"{linea}\n\nMATERIAL:\n\n{texto[:60000]}"
                           if linea else f"MATERIAL:\n\n{texto[:60000]}")
    llamada.contexto = "brief"
    llamada.proyecto = proyecto.id
    respuesta = llm.llamar_json(llamada, claves=comun.claves_actuales())
    if not isinstance(respuesta, dict) or not respuesta.get("puntos"):
        raise llm.ErrorLLM("el brief no trae puntos: respuesta invalida")
    try:
        ritmo_min = int(params.get("ritmo_min") or 20)
        ritmo_max = int(params.get("ritmo_max") or 40)
    except (TypeError, ValueError):
        ritmo_min, ritmo_max = 20, 40
    respuesta.setdefault("formato", {"min": ritmo_min, "max": ritmo_max})
    # OJO al nombre: "formato" en los DATOS es la cadencia {min, max} que
    # dicta el propio modelo. El porte del vídeo (horizontal | vertical) es
    # un mando de quien crea el proyecto y viaja como param "formato" del
    # brief; aquí se copia a "formato_salida" para que p4/p6/p8 puedan
    # leerlo sin preguntarle a la cadencia. Un proyecto sin el mando es
    # horizontal: normalizar_formato cae ahí con cualquier otra cosa.
    respuesta["formato_salida"] = comun.normalizar_formato(params.get("formato"))
    trabajo.avance(f"brief listo: {len(respuesta['puntos'])} puntos, "
                   f"tono {respuesta.get('tono', '?')}")
    return respuesta


def proyecto_leer_datos(proyecto: Proyecto, paso: str):
    """Lee el datos.json de un paso anterior."""
    from ..nucleo.proyecto import leer_json
    return leer_json(proyecto.carpeta_paso(paso) / "datos.json", {}) or {}
