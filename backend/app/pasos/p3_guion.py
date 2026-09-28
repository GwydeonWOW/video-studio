"""Paso 3 — guion: escenas con narración y descripción visual.

UNA llamada de LLM por generación (más reescrituras de escena suelta bajo
demanda). El guion es la columna vertebral:

    [{"id": "S001", "titulo": str, "narracion": str,
      "visual": str,          # QUE se pide a la imagen
      "texto_pantalla": str,  # rotulo corto (callouts lo pule luego)
      "duracion_estimada": s}]

La unidad de este paso (y de voz) es la ESCENA: corregir una escena no
invalida las demás aguas abajo — la réplica marca por unidades.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

SISTEMA = """Eres un guionista de vídeos narrados en español, estilo
divulgación limpia, sin relleno. Escribe el guion COMPLETE a partir del
brief y del material.

Reglas:
- Entre 6 y 14 escenas; el conjunto cuenta una historia con arco.
- "narracion": lo que se OYE. Español natural, frases cortas, sin
  formalismos. Nada de "en este vídeo vamos a..." más de una vez.
- "visual": lo que se VE. Describe UN encuadre concreto por escena,
  con sujeto, acción, ambiente y luz. Sin texto en la imagen.
- "texto_pantalla": rótulo de 2 a 5 palabras para reforzar la idea.
- "duracion_estimada": segundos que durará narrar esa escena (número).
Responde SOLO JSON: {"escenas": [{"id": "S001", ...}, ...]}"""


def params_defecto() -> dict:
    return {"escenas": 8}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 1, "imagenes": 0, "caracteres_voz": 0,
            "coste": None}


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    ingesta = p2_brief.proyecto_leer_datos(proyecto, "ingesta")
    brief = p2_brief.proyecto_leer_datos(proyecto, "brief")
    if not brief:
        raise ValueError("falta el brief: genera primero el paso anterior")
    trabajo.avance("escribiendo el guion")
    llamadas = llm.rol_config("guion", comun.ajustes_llm())
    llamadas.sistema = SISTEMA
    linea = p2_brief.linea_canal(params)
    # el brief ya trae el formato del canal en "formato"; la línea se la
    # recuerda al guionista para que la narración respete la cadencia
    partes = [f"BRIEF:\n{a_json(brief)}"]
    if linea:
        partes.append(linea)
    partes.append(f"MATERIAL (respaldo):\n{ingesta.get('texto', '')[:40000]}")
    partes.append(f"Numero de escenas apuntado: "
                  f"{int(params.get('escenas', 8))}.")
    llamadas.instruccion = "\n\n".join(partes)
    llamadas.contexto = "guion"
    llamadas.proyecto = proyecto.id
    llamadas.max_tokens = 12000
    respuesta = llm.llamar_json(llamadas, claves=comun.claves_actuales())
    escenas = respuesta.get("escenas") if isinstance(respuesta, dict) else respuesta
    if not isinstance(escenas, list) or not escenas:
        raise llm.ErrorLLM("el guion no trae escenas")
    # LO ESCRITO A MANO MANDA: el repaso guarda por unidad la narración
    # corregida (`params.unidades[SXXX].texto`, cajón que nadie más
    # toca) y aquí se aplica DESPUÉS del modelo — es el cajón vivo del
    # cambio `escena_texto` del repaso, y sin releerlo la corrección se
    # marcaría como aplicada y el vídeo seguiría diciendo lo mismo.
    override = {str(k): v for k, v in
                ((params.get("unidades") or {}).items())
                if isinstance(v, dict) and v.get("texto")}
    salida = []
    for indice, escena in enumerate(escenas, start=1):
        narracion = comun.normalizar_texto(escena.get("narracion", ""))
        if not narracion:
            continue
        sid = comun.limpiar_id(escena.get("id", f"S{indice}"))
        manual = " ".join(str(override.get(sid, {}).get("texto") or "").split())
        if manual:
            narracion = manual
        salida.append({
            "id": sid,
            "titulo": comun.normalizar_texto(escena.get("titulo", ""))[:120],
            "narracion": narracion,
            "visual": comun.normalizar_texto(escena.get("visual", ""))[:600],
            "texto_pantalla": comun.normalizar_texto(
                escena.get("texto_pantalla", ""))[:60],
            "duracion_estimada": comun.duracion_estimada(narracion),
        })
    if len(salida) < 3:
        raise llm.ErrorLLM(f"el guion quedo con {len(salida)} escenas "
                           "validas: hace falta al menos 3")
    # ids unicos y correlativos
    for indice, escena in enumerate(salida, start=1):
        escena["id"] = f"S{indice:03d}"
    total = sum(e["duracion_estimada"] for e in salida)
    trabajo.avance(f"guion de {len(salida)} escenas, ~{round(total)} s")
    return {"escenas": salida, "duracion_estimada": round(total, 2)}


def reescribir_escena(proyecto: Proyecto, escena_id: str, orden: str,
                      trabajo=None) -> dict:
    """Correccion de UNA escena bajo demanda (boton de la pantalla).

    Devuelve la escena nueva; quien llama decide si la aplica (y marca por
    unidades aguas abajo).
    """
    datos = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = datos.get("escenas", [])
    actual = next((e for e in escenas if e["id"] == escena_id), None)
    if actual is None:
        raise ValueError(f"escena inexistente: {escena_id}")
    llamada = llm.rol_config("correccion", comun.ajustes_llm())
    llamada.sistema = (
        "Reescribes UNA escena de un guion siguiendo la correccion pedida. "
        "Mantienes el id y el estilo del resto. Responde SOLO JSON con la "
        "escena: {\"id\": str, \"titulo\": str, \"narracion\": str, "
        "\"visual\": str, \"texto_pantalla\": str}")
    llamada.instruccion = (f"ESCENA ACTUAL:\n{a_json(actual)}\n\n"
                           f"CORRECCION PEDIDA:\n{orden}")
    llamada.contexto = f"guion:{escena_id}"
    llamada.proyecto = proyecto.id
    nueva = llm.llamar_json(llamada, claves=comun.claves_actuales())
    if not isinstance(nueva, dict) or not nueva.get("narracion"):
        raise llm.ErrorLLM("la reescritura no trajo narracion")
    nueva["id"] = escena_id
    nueva["duracion_estimada"] = comun.duracion_estimada(nueva["narracion"])
    return nueva


def a_json(valor) -> str:
    import json
    return json.dumps(valor, ensure_ascii=False, indent=1)
