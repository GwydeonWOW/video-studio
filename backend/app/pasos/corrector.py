"""EL CORRECTOR DE UN PLANO: la nota del revisor, convertida en encargo.

QUE ES
------
Cuando alguien rechaza una imagen con una nota («que el ordenador sea el
mismo que en la escena anterior, y mantén la composición»), el generador
necesita DOS cosas que una frase no lleva: la descripción nueva del plano
(ya con lo que la nota pide incorporado) y las REFERENCIAS de las que se
habla — el plano vecino, el personaje del catálogo — con el detalle de qué
copiar de cada una. El camino corto (la nota pegada al final del prompt)
vale para «cámbiale las gafas» y se queda corto en cuanto la nota nombra
OTRA escena, OTRO personaje o pide conservar lo que ya está bien.

QUE HACE
--------
Una llamada al LLM del rol «corrector» (el grande: es el que decide qué
se dibuja) recibe la nota, el contexto del plano y un INVENTARIO textual
de todo el material del vídeo: la imagen actual del plano, los planos
vecinos, el reparto, los sitios. La imagen rechazada VIAJA ADJUNTA a la
llamada cuando existe — el LLM de GLM ve imágenes (glm-5.3v) y «el detalle
es lo que SOLO se sabe mirando la imagen» — y devuelve:

  - `alcance`        retoque (se conserva la composición) o sustituye
  - `personajes`     quién sale en el plano nuevo (ids del reparto)
  - `escena`         la descripción nueva del plano, en inglés, ya con lo
                     que pide la nota
  - `referencias`    la lista ORDENADA de inventario que se cita, con el
                     detalle de qué copiar de cada una
  - `porque`         una línea, para la bitácora

LA DIFERENCIA CON EL ORIGINAL, Y POR QUÉ ES ADAPTACIÓN Y NO RECORTA
-------------------------------------------------------------------
El motor de imagen del original (gpt-image) ADJUNTA imágenes a cada
llamada: las referencias que devolvía su agente viajaban dentro del
encargo. El de aquí (motores/imagen_glm.py) es de PROMPT COMPUESTO: solo
lee texto. Así que las referencias vuelven TEXTUALES — cada una
presentada por la MISMA frase de su clase que oiría un plano nuevo, más
el detalle del agente — y la imagen rechazada no se adjunta al generar:
se DESCRIBE lo que se conserva, que es el trabajo del agente al
escribir el detalle con ella delante.

LO QUE NO HACE
--------------
No genera. No toca el plan: la descripción nueva y los personajes valen
para ESTA regeneración y se guardan en el resultado de la unidad, no en
el plan. Y no puede citar nada que no esté en el inventario: la
respuesta se valida contra él, clave a clave.

SI FALLA
--------
Se vuelve al camino de siempre (la nota pegada al final del prompt, que
es `prompt_de` sin corrección) y se anota el fallo. Una corrección
nunca se queda sin hacer porque el agente no contestara.
"""
from __future__ import annotations

import time

from ..motores import llm
from . import comun

#: Cuántas referencias puede citar el agente. Cada una son una línea del
#: prompt y a partir de seis o siete el generador deja de saber cuál manda.
MAX_REFERENCIAS = 6

#: Cuántos planos vecinos (a cada lado) entran en el inventario.
VECINOS = 3

SISTEMA = ("Eres el director de arte que corrige UN plano de un video de "
           "animacion narrada a partir de la nota de un revisor. La imagen "
           "que el revisor rechaza va adjunta a este mensaje, cuando "
           "existe: mira la imagen antes de decidir nada, porque la nota "
           "puede "
           "hablar de algo que solo se ve mirando. Responde "
           "exclusivamente con el objeto JSON pedido, sin texto alrededor "
           "y sin vallas de markdown.")

INSTRUCCION = """Corrige el plano {sid} de «{titulo}» siguiendo la nota del revisor.

LA NOTA DEL REVISOR (manda sobre todo lo demas):
<<<
{nota}
>>>

EL PLANO, TAL Y COMO ESTA:
  narracion (lo que dice la voz en ese tramo): {narracion}
  sitio: {sitio}
  personajes del plano ahora: {personajes}
  descripcion con la que se dibujo (en ingles): {descripcion}
  tipo de plano (obligatorio, no lo cambies): {encuadre}

EL ESTILO DEL VIDEO:
{estilo}

EL REPARTO (id -> como es; cada uno esta en el inventario):
{reparto}

LOS SITIOS DEL VIDEO (id -> como es):
{sitios}

INVENTARIO DE REFERENCIAS (clave -> que es). Solo puedes citar claves de
esta lista, tal cual estan escritas. Cada una lleva su CLASE entre
corchetes, y la clase decide lo que el generador oye de ella por defecto:
  [rechazada]    «es este mismo plano tal y como se dibujo: conserva todo y
                 cambia solo lo que pide la nota»
  [continuidad]  «es un plano vecino: misma paleta, misma luz, mismo sitio
                 si lo es; no copies su encuadre ni sus poses»
  [reparto]      «es como es ese personaje: copia su cara, pelo, cuerpo y
                 ropa; nada mas que eso»
  [adjunta]      «usala SOLO para lo que la nota pida de ella»
{inventario}

QUE TIENES QUE DEVOLVER
Un objeto JSON con estas claves:
  "alcance"      "retoque" si la composicion se conserva y cambia algo
                 concreto; "sustituye" si el plano nuevo es otra cosa.
  "personajes"   la lista de ids del reparto que salen en el plano NUEVO
                 (vacia si no sale nadie del reparto). Los personajes
                 genericos («trabajadores random») no van aqui: van en la
                 descripcion.
  "escena"       la descripcion NUEVA del plano en ingles, completa y
                 autosuficiente: que se ve, quien, donde, que hace cada
                 uno. Incorpora lo que pide la nota y conserva lo que la
                 nota no toca — de la imagen adjunta, si va, conserva lo
                 que la nota no menciona y describelo en el detalle de la
                 referencia [rechazada]. No describas el estilo de dibujo
                 (eso lo pone la guia) ni escribas «reference image».
  "referencias"  la lista ORDENADA de referencias a citar, cada una
                 {{"clave": <clave del inventario>, "detalle": <frase en
                 ingles>}}. El generador ya oye la frase de su clase
                 (arriba); el detalle es lo que SOLO se sabe mirando: que
                 copiar de ella en concreto y que no. Ejemplos:
                   - imagen rechazada: «keep the empty cubicles, the
                     stacked boxes and the whiteboard of crossed-out
                     numbers exactly; change only who sits at the desk»
                   - plano vecino: «copy only the beige boxy CRT at its
                     left edge, same model and screen, and put that
                     computer on the central desk; copy nothing else»
                   - personaje: «grey polo, no tie, round glasses»
                 Como mucho {max_referencias} referencias; no cites lo que
                 no vayas a precisar en su detalle. Si el alcance es
                 sustituye, no cites la imagen rechazada: con ella
                 delante el generador la retoca en vez de sustituirla.
  "porque"       una linea: que has mirado y por que has elegido esas
                 referencias.

REGLAS
- La identidad de cada personaje del reparto sale de SU ficha: si la
  nota mete a alguien del reparto en el plano, citale y nombralo en
  "personajes". Si la nota pide personajes genericos, describelos en
  "escena" (distintos entre si) y no les cites.
- Si la nota se contradice con la narracion o con el sitio, manda la
  nota.
- Nada de texto escrito en la imagen salvo que la nota lo pida.
"""


def _texto(valor, tope=1200):
    return " ".join(str(valor or "").split())[:tope]


def _inventario_legible(inventario):
    lineas = []
    for ficha in inventario or []:
        lineas.append(f"  {ficha['clave']}\n      -> [{ficha.get('clase') or 'adjunta'}] "
                      f"{_texto(ficha.get('que'), 400)}")
    return "\n".join(lineas) if lineas else "  (sin referencias)"


def _reparto_legible(reparto):
    lineas = []
    for ident, ficha in (reparto or {}).items():
        if not isinstance(ficha, dict):
            continue
        lineas.append(f"  {ident}: {_texto(ficha.get('descripcion'), 400)}")
    return "\n".join(lineas) if lineas else "  (sin reparto)"


def _sitios_legibles(sets):
    lineas = []
    for ident, ficha in (sets or {}).items():
        if isinstance(ficha, dict):
            luz = _texto(ficha.get("luz"), 120)
            como = _texto(ficha.get("descripcion"), 300)
            lineas.append(f"  {ident}: {como}"
                          + (f" — luz: {luz}" if luz else ""))
    return "\n".join(lineas) if lineas else "  (sin sitios)"


def preparar(nota, escena, catalogo, estilo_legible, inventario,
             titulo="", imagen_actual="", proyecto_id="", avisar=None):
    """Convierte la nota en (alcance, personajes, escena, referencias). -> dict

    `inventario` es [{"clave", "que", "clase"}]: claves cortas que el
    agente cita y `p6_assets` traduce a líneas del prompt (aquí el
    generador no adjunta imágenes; ver la cabecera del módulo).
    `imagen_actual` es la ruta de la imagen rechazada: viaja ADJUNTA a
    la llamada para que el agente la mire (visión).

    Devuelve {"error": ...} si el agente no contesta o contesta algo
    inservible: quien llama vuelve entonces al camino de siempre.
    """
    avisar = avisar or (lambda *_a, **_k: None)
    nota = _texto(nota, 2000)
    if not nota or not inventario:
        return {"error": "no hay nota o no hay inventario"}
    validas = {str(f.get("clave")): f for f in inventario}
    reparto = (catalogo or {}).get("reparto") or {}
    instruccion = INSTRUCCION.format(
        sid=escena.get("id"), titulo=_texto(titulo, 120) or "sin titulo",
        nota=nota,
        narracion=_texto(escena.get("narracion"), 600) or "(sin narracion)",
        sitio=escena.get("set") or "(sin sitio)",
        personajes=", ".join(str(x) for x in (escena.get("personajes") or []))
        or "(nadie del reparto)",
        descripcion=_texto(escena.get("prompt"), 1500) or "(sin descripcion)",
        encuadre=_texto(escena.get("encuadre"), 300) or "(libre)",
        estilo=estilo_legible or "  (sin guia escrita)",
        reparto=_reparto_legible(reparto),
        sitios=_sitios_legibles((catalogo or {}).get("sets")),
        inventario=_inventario_legible(inventario),
        max_referencias=MAX_REFERENCIAS)
    arranque = time.time()
    avisar(f"{escena.get('id')}: el corrector esta leyendo la nota"
           + (" y la imagen" if imagen_actual else ""))
    llamada = llm.rol_config("corrector", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = instruccion
    llamada.contexto = f"corrector:{escena.get('id')}"
    llamada.proyecto = str(proyecto_id or "")
    if imagen_actual:
        # el agente MIRA la imagen rechazada (la nota habla de ella);
        # el rol se resuelve solo al modelo que ve
        llamada.imagenes = [str(imagen_actual)]
    try:
        datos = llm.llamar_json(llamada, claves=comun.claves_actuales())
    except Exception as fallo:                                   # noqa: BLE001
        return {"error": f"{type(fallo).__name__}: {fallo}"[:300],
                "segundos": round(time.time() - arranque, 1)}
    if not isinstance(datos, dict):
        return {"error": "la respuesta no es un objeto",
                "segundos": round(time.time() - arranque, 1)}

    alcance = str(datos.get("alcance") or "").strip().lower()
    if alcance not in ("retoque", "sustituye"):
        alcance = "retoque"
    personajes = []
    for ident in (datos.get("personajes") or []):
        ident = str(ident or "").strip()
        if ident in reparto and ident not in personajes:
            personajes.append(ident)
    descripcion = _texto(datos.get("escena"), 2500)
    referencias, vistas = [], set()
    for cruda in (datos.get("referencias") or []):
        if not isinstance(cruda, dict):
            continue
        clave = str(cruda.get("clave") or "").strip()
        ficha = validas.get(clave)
        detalle = _texto(cruda.get("detalle") or cruda.get("etiqueta"), 600)
        if not ficha or clave in vistas or not detalle:
            continue
        vistas.add(clave)
        # la referencia sale con la clase y los atributos del inventario
        # (nombre, mismo_set...) y con el detalle del agente encima
        referencia = {k: v for k, v in ficha.items() if k not in ("que",)}
        referencia["detalle"] = detalle
        referencias.append(referencia)
        if len(referencias) >= MAX_REFERENCIAS:
            break
    if not descripcion:
        return {"error": "el corrector no ha devuelto la descripcion del "
                         "plano",
                "segundos": round(time.time() - arranque, 1)}
    return {"alcance": alcance, "personajes": personajes, "escena": descripcion,
            "referencias": referencias,
            "porque": _texto(datos.get("porque"), 400),
            "segundos": round(time.time() - arranque, 1)}
