"""Paso 3 — guion: escenas con narración y descripción visual.

UNA llamada de LLM por generación (más reescrituras de escena suelta bajo
demanda), y UN reintento con correcciones si la longitud se sale de la
horquilla. El guion es la columna vertebral:

    [{"id": "S001", "titulo": str, "narracion": str,
      "visual": str,          # QUE se pide a la imagen
      "texto_pantalla": str,  # rotulo corto (callouts lo pule luego)
      "duracion_estimada": s}]

LA DURACIÓN SE PIDE EN MINUTOS Y SE OBEDECE EN PALABRAS
--------------------------------------------------------
La duración no se le puede imponer a un guionista pidiendo «20 minutos»:
un guion es texto y lo que dura lo decide quien lo lee. Como en el
original del Estudio, la duración pedida (`params.duracion_min`) se
traduce aquí a un PRESUPUESTO DE PALABRAS con horquilla ±30 % (a
2,6 palabras/s, el ritmo con el que este Estudio estima todas las
duraciones), y de ahí salen las dos cifras que el modelo sí puede
obedecer: CUÁNTAS escenas y CUÁNTAS palabras por escena. El prompt lo
dice con su aritmética (N × M ≈ total) porque dos reglas de longitud
sin la multiplicación son dos intenciones sin cuenta: «entre X e Y
palabras» y «escenas cortas» se cumplen a la vez escribiendo muchas
escenas cortas... que es como salían guiones de 3 minutos cuando se
pedían veinte.

Si la generación cae fuera de la horquilla, se reintenta UNA vez y la
corrección VIAJA CON EL TEXTO QUE CORRIGE: el intento anterior va
dentro de la instrucción, escena a escena y con su cuenta de palabras,
porque cada llamada es una sesión limpia y «recorta a 3.000» de un
texto que el modelo no tiene delante es una orden imposible. Se
entrega el intento MÁS CERCANO al presupuesto, no el último: un
reintento es una apuesta y se puede perder.

Sin duración pedida (proyectos viejos que solo traen «escenas»), manda
el número de escenas y no hay horquilla: el comportamiento de siempre.

La unidad de este paso (y de voz) es la ESCENA: corregir una escena no
invalida las demás aguas abajo — la réplica marca por unidades.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun, marcas_tts, p2_brief
from ..motores import llm

SISTEMA = """Eres un guionista de vídeos narrados en español, estilo
divulgación limpia, sin relleno. Escribe el guion COMPLETE a partir del
brief y del material.

Reglas:
- "narracion": lo que se OYE. Español natural, frases cortas, sin
  formalismos. Nada de "en este vídeo vamos a..." más de una vez.
- "visual": lo que se VE. Describe UN encuadre concreto por escena,
  con sujeto, acción, ambiente y luz. Sin texto en la imagen.
- "texto_pantalla": rótulo de 2 a 5 palabras para reforzar la idea.
- "duracion_estimada": segundos que durará narrar esa escena (número).
- "abre_seccion": true SOLO en la escena que abre una sección del
  relato (un capítulo, un cambio grande de tema). Es estructura, no
  estilo: marca dónde tiene que haber aire al escuchar.
- CUÁNTAS escenas y CUÁNTO dura cada una los manda la sección
  LONGITUD del encargo; el conjunto cuenta una historia con arco.
Responde SOLO JSON: {"escenas": [{"id": "S001", ...}, ...]}"""

#: ±30 % alrededor del presupuesto: un guion de locución no se clava al
#: segundo, y perseguir la cifra exacta produce guiones estirados o
#: mutilados (misma regla que el original).
TOLERANCIA = 0.30

#: Tokens de salida por palabra de guion (JSON en español con ids y
#: visuales incluidos): el techo de la llamada crece con el vídeo o un
#: guion largo vuelve con `finish: length` y el JSON partido.
TOKENS_POR_PALABRA = 2.5


def params_defecto() -> dict:
    # anotaciones_voz: el redactor puede meter <break> en la narracion
    # (ver marcas_tts). pausa_gancho_ms / pausa_seccion_ms: aire
    # ESTRUCTURAL que no depende de que el redactor se acuerde — lo pone
    # el motor en el texto (gancho: final de la primera escena; seccion:
    # delante de cada escena que abre seccion). 0 lo apaga.
    return {"duracion_min": 10, "anotaciones_voz": True,
            "pausa_gancho_ms": 900, "pausa_seccion_ms": 900}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 2 if (params or {}).get("duracion_min") else 1,
            "imagenes": 0, "caracteres_voz": 0, "coste": None}


def _horquilla(duracion_min, formato) -> dict | None:
    """Duración pedida -> presupuesto de palabras y reparto en escenas.

    `formato` es el del brief (segundos por escena que fija la cadencia
    del canal). None si no hay duración: modo viejo, manda «escenas».
    """
    try:
        duracion_s = int(round(float(duracion_min or 0))) * 60
    except (TypeError, ValueError):
        return None
    if duracion_s <= 0:
        return None
    presupuesto = int(round(duracion_s * comun.RITMO_PALABRAS_S))
    seg_min, seg_max = 20, 40
    if isinstance(formato, dict):
        try:
            candidato_min = int(formato.get("min") or 20)
            candidato_max = int(formato.get("max") or 40)
        except (TypeError, ValueError):
            candidato_min, candidato_max = 0, 0
        if 0 < candidato_min <= candidato_max:
            seg_min, seg_max = candidato_min, candidato_max
    palabras_escena = max(30, min(150,
                                  round((seg_min + seg_max) / 2
                                        * comun.RITMO_PALABRAS_S)))
    return {
        "duracion_s": duracion_s,
        "objetivo": presupuesto,
        "min": round(presupuesto * (1 - TOLERANCIA)),
        "max": round(presupuesto * (1 + TOLERANCIA)),
        "escenas": max(3, min(120, round(presupuesto / palabras_escena))),
        "palabras_escena": palabras_escena,
    }


def _seccion_longitud(h: dict) -> str:
    """Las reglas de longitud CON su aritmética: N × M ≈ total."""
    return (
        "LONGITUD DEL VÍDEO (manda sobre cualquier otra regla):\n"
        f"- La narración completa, ENTRE {h['min']} Y {h['max']} palabras "
        f"(objetivo ~{h['objetivo']}: son ~{round(h['duracion_s'] / 60)} min "
        f"narrados a {comun.RITMO_PALABRAS_S} palabras/s).\n"
        f"- Reparto: unas {h['escenas']} escenas de unas "
        f"{h['palabras_escena']} palabras cada una "
        f"({h['escenas']} x {h['palabras_escena']} ≈ "
        f"{h['escenas'] * h['palabras_escena']}).\n"
        "- Si el reparto no cuadra, el TOTAL manda: alarga o acorta las "
        "escenas (o añade o quita alguna) hasta caer en la horquilla.\n"
        "- ANTES DE ENTREGAR, CUENTA: suma las palabras de todas las "
        "escenas. Si te pasaste, recorta frases enteras que no aporten "
        "un hecho nuevo; si te quedaste corto, desarrolla los hechos "
        "del material con más contexto y explicación — nunca relleno.")


def _palabras_de(salida: list[dict]) -> int:
    # contar_palabras y no palabras a secas: las anotaciones de voz no se
    # locutan y la horquilla se mide sobre lo que se OYE
    return sum(marcas_tts.contar_palabras(e["narracion"]) for e in salida)


def _a_salida(respuesta, override: dict) -> list[dict]:
    """Respuesta del modelo -> lista de escenas normalizadas."""
    escenas = respuesta.get("escenas") if isinstance(respuesta, dict) else respuesta
    if not isinstance(escenas, list) or not escenas:
        raise llm.ErrorLLM("el guion no trae escenas")
    salida = []
    for indice, escena in enumerate(escenas, start=1):
        narracion = comun.normalizar_texto(escena.get("narracion", ""))
        if not narracion:
            continue
        sid = comun.limpiar_id(escena.get("id", f"S{indice}"))
        manual = " ".join(str(override.get(sid, {}).get("texto") or "").split())
        if manual:
            narracion = manual
        # sanear deja solo <break> del vocabulario: lo que el motor no
        # reconoce lo LOCUTA en voz alta. Y una escena que solo trae
        # etiquetas no es una escena (no se locuta nada)
        narracion = marcas_tts.sanear(narracion)
        if not marcas_tts.limpiar(narracion):
            continue
        salida.append({
            "id": sid,
            "titulo": comun.normalizar_texto(escena.get("titulo", ""))[:120],
            "narracion": narracion,
            "visual": comun.normalizar_texto(escena.get("visual", ""))[:600],
            "texto_pantalla": comun.normalizar_texto(
                escena.get("texto_pantalla", ""))[:60],
            "abre_seccion": bool(escena.get("abre_seccion")),
            "duracion_estimada": comun.duracion_estimada(
                marcas_tts.limpiar(narracion)),
        })
    return salida


def _pausas_estructurales(escenas: list[dict], params: dict) -> None:
    """El aire que no puede depender de que el redactor se acuerde.

    `pausa_gancho_ms` detras de la primera escena (el gancho remata y se
    queda colgando: sin aire, la entrada le pisa el final) y
    `pausa_seccion_ms` delante de cada escena que abre seccion — que se
    pone al FINAL de la anterior, porque el TTS solo sabe callar entre
    trozos de texto. La primera escena no lleva pausa de seccion aunque
    abra: ya lleva la del gancho. 0 apaga cada una.
    """
    params = params or {}

    def _soplar(escena: dict, ms: float) -> None:
        escena["narracion"] = marcas_tts.pausa_al_final(
            escena["narracion"], ms)
        escena["duracion_estimada"] = round(
            comun.duracion_estimada(marcas_tts.limpiar(escena["narracion"]))
            + marcas_tts.silencio_final(escena["narracion"]) / 1000.0, 2)

    try:
        gancho = float(params.get("pausa_gancho_ms") or 0)
        seccion = float(params.get("pausa_seccion_ms") or 0)
    except (TypeError, ValueError):
        gancho, seccion = 0.0, 0.0
    if gancho > 0 and escenas:
        _soplar(escenas[0], gancho)
    if seccion > 0:
        for indice in range(1, len(escenas)):
            if escenas[indice].get("abre_seccion"):
                _soplar(escenas[indice - 1], seccion)


def _corregir_horquilla(salida: list[dict], h: dict, llamadas, override: dict,
                        trabajo) -> list[dict]:
    """Un reintento cuando la longitud quedó fuera, y el mejor gana.

    La corrección viaja con el texto que corrige (ver la cabecera del
    módulo) y se entrega el intento más cercano al presupuesto — no el
    último. Si el reintento revienta o viene roto, se entrega el
    primero: ya es un guion usable.
    """
    total = _palabras_de(salida)
    if h["min"] <= total <= h["max"] or not salida:
        return salida
    if total < h["min"]:
        orden = (f"el guion se quedó en {total} palabras y el mínimo son "
                 f"{h['min']}: desarrolla los hechos del material con más "
                 "contexto y explicación por punto, sin relleno")
    else:
        orden = (f"el guion se fue a {total} palabras y el máximo son "
                 f"{h['max']}: recorta frases enteras que no aporten un "
                 "hecho nuevo, sin perder ningún hecho")
    listado = "\n".join(
        f"{e['id']} ({marcas_tts.contar_palabras(e['narracion'])} pal.): "
        f"{e['narracion'][:180]}" for e in salida)
    trabajo.avance(f"rehaciendo el largo: {orden[:70]}")
    original = llamadas.instruccion
    llamadas.instruccion = (
        original
        + "\n\n== CORRECCIONES AL INTENTO ANTERIOR ==\n"
        + f"- {orden}. El total manda sobre el número de escenas: añade o "
        "quita escenas si hace falta.\n"
        "El intento anterior, escena a escena (parte de él y conserva lo "
        "bueno):\n" + listado)
    try:
        respuesta = llm.llamar_json(llamadas, claves=comun.claves_actuales())
        segunda = _a_salida(respuesta, override)
    except llm.ErrorLLM:
        return salida
    finally:
        llamadas.instruccion = original
    if not segunda:
        return salida
    mejor_primera = abs(total - h["objetivo"])
    mejor_segunda = abs(_palabras_de(segunda) - h["objetivo"])
    return segunda if mejor_segunda < mejor_primera else salida


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    ingesta = p2_brief.proyecto_leer_datos(proyecto, "ingesta")
    brief = p2_brief.proyecto_leer_datos(proyecto, "brief")
    if not brief:
        raise ValueError("falta el brief: genera primero el paso anterior")
    trabajo.avance("escribiendo el guion")
    h = _horquilla((params or {}).get("duracion_min"),
                   brief.get("formato") if isinstance(brief, dict) else None)
    llamadas = llm.rol_config("guion", comun.ajustes_llm())
    llamadas.sistema = SISTEMA
    linea = p2_brief.linea_canal(params)
    # el brief ya trae el formato del canal en "formato"; la línea se la
    # recuerda al guionista para que la narración respete la cadencia
    partes = [f"BRIEF:\n{a_json(brief)}"]
    if linea:
        partes.append(linea)
    partes.append(f"MATERIAL (respaldo):\n{ingesta.get('texto', '')[:40000]}")
    if (params or {}).get("anotaciones_voz", True):
        # el vocabulario de anotaciones viaja con el encargo: sin el, el
        # redactor no sabe que existe; con el, no se inventa etiquetas
        # (que el motor LOCUTA en voz alta)
        partes.append(marcas_tts.instrucciones())
    if h:
        partes.append(_seccion_longitud(h))
        # el techo crece con el vídeo: 40 min son ~6.200 palabras y el
        # tope fijo de 12.000 tokens no da para el JSON entero
        llamadas.max_tokens = max(12000, int(h["objetivo"] * TOKENS_POR_PALABRA))
    else:
        try:
            escenas_pedidas = max(1, int(params.get("escenas") or 8))
        except (TypeError, ValueError):
            escenas_pedidas = 8
        partes.append(f"Numero de escenas apuntado: {escenas_pedidas}.")
        llamadas.max_tokens = 12000
    llamadas.instruccion = "\n\n".join(partes)
    llamadas.contexto = "guion"
    llamadas.proyecto = proyecto.id
    # LO ESCRITO A MANO MANDA: el repaso guarda por unidad la narración
    # corregida (`params.unidades[SXXX].texto`, cajón que nadie más
    # toca) y aquí se aplica DESPUÉS del modelo — es el cajón vivo del
    # cambio `escena_texto` del repaso, y sin releerlo la corrección se
    # marcaría como aplicada y el vídeo seguiría diciendo lo mismo.
    override = {str(k): v for k, v in
                ((params.get("unidades") or {}).items())
                if isinstance(v, dict) and v.get("texto")}
    respuesta = llm.llamar_json(llamadas, claves=comun.claves_actuales())
    salida = _a_salida(respuesta, override)
    if h:
        salida = _corregir_horquilla(salida, h, llamadas, override, trabajo)
    if len(salida) < 3:
        raise llm.ErrorLLM(f"el guion quedo con {len(salida)} escenas "
                           "validas: hace falta al menos 3")
    # ids unicos y correlativos
    for indice, escena in enumerate(salida, start=1):
        escena["id"] = f"S{indice:03d}"
    _pausas_estructurales(salida, params)
    total = sum(e["duracion_estimada"] for e in salida)
    salida_datos = {"escenas": salida, "duracion_estimada": round(total, 2)}
    if h:
        salida_datos["horquilla"] = {
            "objetivo": h["objetivo"], "min": h["min"], "max": h["max"],
            "palabras": _palabras_de(salida),
        }
        trabajo.avance(f"guion de {len(salida)} escenas, "
                       f"{salida_datos['horquilla']['palabras']} palabras "
                       f"(horquilla {h['min']}-{h['max']})")
    else:
        trabajo.avance(f"guion de {len(salida)} escenas, ~{round(total)} s")
    return salida_datos


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
    # mismo trato que la generacion entera: solo etiquetas del
    # vocabulario (lo demas lo LOCUTA el motor). Y se conserva la marca
    # estructural de la escena, que el prompt de correccion no le ensena
    nueva["narracion"] = marcas_tts.sanear(nueva["narracion"])
    if not nueva["narracion"]:
        raise llm.ErrorLLM("la reescritura no trajo narracion")
    nueva["id"] = escena_id
    nueva["abre_seccion"] = bool(actual.get("abre_seccion"))
    nueva["duracion_estimada"] = comun.duracion_estimada(
        marcas_tts.limpiar(nueva["narracion"]))
    return nueva


def a_json(valor) -> str:
    import json
    return json.dumps(valor, ensure_ascii=False, indent=1)
