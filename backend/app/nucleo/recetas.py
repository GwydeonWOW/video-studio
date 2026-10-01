"""Las RECETAS: lo que hay que hacer de una tirada, en orden.

El problema que resuelven es el del original: generar un vídeo a mano
son muchos botones en el orden correcto, y el orden importa (la voz no
se graba sin guion aprobado, las imágenes no se pagan sin guion, el
rótulo se decide con la voz delante). Eso no es una decisión creativa:
es una tubería, y una tubería la recorre el programa.

Una receta es la lista de tareas de UNA pestaña. Con ella:

    Generar lo pendiente    corre lo que falta, saltándose lo que ya
                            está hecho y al día
    Generar todo            lo corre todo, aunque esté al día

Lo que NO cambia: cada paso sigue teniendo su botón, su ficha y su
revisión. La receta no esconde nada: adelanta trabajo.

Aquí viven los DATOS (qué tareas hay, cómo se llaman, en qué pestaña
viven, cuál cuesta dinero y cuál es opcional) y el ALMACÉN de las
recetas que guarda quien usa el estudio — que son del CANAL y no de un
vídeo, así que no tocan ninguna firma. El código que las corre vive en
la API (`rutas_proyectos`), y reutiliza el MISMO camino que el botón
de cada paso — una tarea declarada sin paso real en el grafo no puede
existir, porque la tabla se deriva del grafo.

Del original no viajan los `ajustes` (modelo y esfuerzo por fase del
CLI de Claude): aquí no hay CLI, y lo que se ajusta por invocación son
los `params`, que ya viajan por su propia ruta.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.RLock()


class ErrorReceta(ValueError):
    """Lo que manda la pantalla no vale, y se dice por qué."""


# El orden NO es estético: es el del grafo (ingesta → ... → render).
# Cada tarea declara su pestaña; `necesita` son los ids de SU MISMA
# pestaña que tienen que ir antes.
#
#   opcional    si se puede correr sin ella (y entonces la receta la
#               ofrece con un interruptor). Lo no opcional siempre va:
#               una receta que se salte «las imágenes» no es una
#               receta de vídeo.
#
# Lo opcional aquí es la COLA que no rompe nada al faltar: la revisión
# del audio (una inspección, nadie la lee para montar), los rótulos y
# el montaje. La columna vertebral —material, guion, voz, imágenes—
# no se puede apagar desde una receta.
TAREAS = [
    {"id": "ingesta", "nombre": "El material de origen", "pestana": "origen",
     "paso": "ingesta", "necesita": [], "cuesta": False, "opcional": False,
     "porque": "baja el vídeo o pega el texto del que parte todo"},
    {"id": "brief", "nombre": "El presupuesto de palabras", "pestana": "guion",
     "paso": "brief", "necesita": [], "cuesta": True, "opcional": False,
     "porque": "decide cuántas palabras caben en la duración pedida"},
    {"id": "guion", "nombre": "El guion", "pestana": "guion",
     "paso": "guion", "necesita": ["brief"], "cuesta": True,
     "opcional": False,
     "porque": "redacta el guion con las instrucciones del brief"},
    {"id": "voz", "nombre": "La locución", "pestana": "voz",
     "paso": "voz", "necesita": [], "cuesta": True, "opcional": False,
     "porque": "graba la narración escena a escena (guion aprobado)"},
    {"id": "revision_audio", "nombre": "La revisión de audio",
     "pestana": "voz", "paso": "revision_audio", "necesita": ["voz"],
     "cuesta": False, "opcional": True,
     "porque": "escucha la toma y señala lo que no cuadra"},
    {"id": "assets", "nombre": "Las imágenes", "pestana": "montaje",
     "paso": "assets", "necesita": [], "cuesta": True, "opcional": False,
     "porque": "una imagen por escena, de una en una (cuesta dinero)"},
    {"id": "callouts", "nombre": "Los rótulos", "pestana": "montaje",
     "paso": "callouts", "necesita": ["assets"], "cuesta": True,
     "opcional": True,
     "porque": "decide el rótulo de cada escena con las marcas de la voz"},
    {"id": "render", "nombre": "El montaje", "pestana": "montaje",
     "paso": "render", "necesita": ["assets"], "cuesta": False,
     "opcional": True,
     "porque": "compone el MP4 con ffmpeg (no llama a ningún servicio)"},
]

#: nombre de pantalla de cada pestaña, en el orden en que se recorren
PESTANAS = {"origen": "Origen", "guion": "Guion", "voz": "Voz",
            "montaje": "Montaje"}

#: Las TANDAS del botón «generar»: qué pestañas recorre cada gesto y
#: qué tareas se quedan FUERA («sin»: mirar sin montar). Es el porte de
#: las TANDAS_LIGHT del original adaptado a estas pestañas: el botón de
#: «vídeo» de allá era la pestaña de vídeo SIN los rótulos, y aquí el
#: equivalente es montaje SIN rótulos ni render — las imágenes, que es
#: lo que se paga, con el montaje entero a un botón de distancia.
TANDAS = {
    "guion": {"nombre": "El guion", "pestanas": ["guion"], "sin": []},
    "voz": {"nombre": "La locución", "pestanas": ["voz"], "sin": []},
    "video": {"nombre": "Las imágenes", "pestanas": ["montaje"],
              "sin": ["callouts", "render"]},
    "render": {"nombre": "El vídeo montado", "pestanas": ["montaje"],
               "sin": []},
}

TAREAS_POR_ID = {t["id"]: t for t in TAREAS}

#: la receta COMPLETA (la que corre la tanda multi-vídeo)
COMPLETA = [t["id"] for t in TAREAS]


def tareas_de(pestana: str) -> list[str]:
    """Ids de tarea de una pestaña, en orden de receta."""
    return [t["id"] for t in TAREAS if t["pestana"] == pestana]


def validar_modo(modo) -> str:
    """`pendiente` (sólo lo que falta) o `todo`. Levanta si no vale."""
    modo = str(modo or "pendiente")
    if modo not in ("pendiente", "todo"):
        raise ValueError("el modo es 'pendiente' o 'todo'")
    return modo


# ===========================================================================
# EL ORDEN — topológico sobre `necesita`
# ===========================================================================

def _tareas_fichas_de(pestana: str) -> list[dict]:
    return [t for t in TAREAS if t["pestana"] == str(pestana)]


def orden_de(pestana, incluidas=None) -> list[dict]:
    """Las tareas de una pestaña ordenadas por dependencias (topológico).

    `incluidas` recorta la lista; una dependencia que no está incluida
    simplemente no espera a nadie, que es lo correcto: si has decidido
    no generar los rótulos, el montaje no tiene que esperarlos.
    """
    tareas = _tareas_fichas_de(pestana)
    if incluidas is not None:
        incluidas = set(incluidas)
        tareas = [t for t in tareas if t["id"] in incluidas]
    disponibles = {t["id"] for t in tareas}
    pendientes, hechas, salida = list(tareas), set(), []
    while pendientes:
        antes = len(pendientes)
        for tarea in list(pendientes):
            faltan = [d for d in tarea["necesita"]
                      if d in disponibles and d not in hechas]
            if faltan:
                continue
            salida.append(tarea)
            hechas.add(tarea["id"])
            pendientes.remove(tarea)
        if len(pendientes) == antes:
            # Un ciclo en la tabla es un error de programación, no de
            # datos: se dice en voz alta en vez de colgar la generación
            # para siempre.
            raise ErrorReceta("ciclo en las dependencias de la receta: "
                              + ", ".join(t["id"] for t in pendientes))
    return salida


def tandas_de(pestana, incluidas=None) -> list[list[dict]]:
    """Las tareas agrupadas en TANDAS: lo de una tanda puede correr a la vez.

    Es lo que permitiría que lo que no depende entre sí corra en
    paralelo y que lo que depende espere a todas las suyas.
    """
    orden = orden_de(pestana, incluidas)
    disponibles = {t["id"] for t in orden}
    nivel = {}
    for tarea in orden:
        previos = [nivel[d] for d in tarea["necesita"]
                   if d in disponibles and d in nivel]
        nivel[tarea["id"]] = (max(previos) + 1) if previos else 0
    tandas: list[list[dict]] = []
    for tarea in orden:
        indice = nivel[tarea["id"]]
        while len(tandas) <= indice:
            tandas.append([])
        tandas[indice].append(tarea)
    return tandas


# ===========================================================================
# EL ALMACÉN — las recetas guardadas, del canal y no de un vídeo
# ===========================================================================

def _fichero() -> Path:
    """datos/recetas.json, o lo que diga ESTUDIO_RECETAS (las pruebas)."""
    por_entorno = os.environ.get("ESTUDIO_RECETAS")
    if por_entorno:
        return Path(por_entorno)
    from ..config import AJUSTES          # diferido: nucleo no arranca config
    return Path(AJUSTES.datos) / "recetas.json"


def _vacio() -> dict:
    return {"recetas": [], "por_defecto": {}}


def leer() -> dict:
    with _LOCK:
        try:
            with open(_fichero(), "r", encoding="utf-8-sig") as fh:
                datos = json.load(fh)
        except (OSError, ValueError):
            return _vacio()
        if not isinstance(datos, dict):
            return _vacio()
        base = _vacio()
        base["recetas"] = [r for r in (datos.get("recetas") or [])
                           if isinstance(r, dict) and r.get("id")]
        defecto = datos.get("por_defecto")
        base["por_defecto"] = {k: str(v) for k, v in (defecto or {}).items()
                               if isinstance(defecto, dict)}
        return base


def _escribir(datos: dict) -> None:
    fichero = _fichero()
    os.makedirs(os.path.dirname(fichero) or ".", exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=os.path.dirname(fichero) or ".",
                prefix=".recetas-", suffix=".tmp", delete=False) as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
            temporal = fh.name
        os.replace(temporal, fichero)
        temporal = None
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def listar(pestana=None) -> list[dict]:
    recetas_guardadas = leer()["recetas"]
    if pestana:
        recetas_guardadas = [r for r in recetas_guardadas
                             if r.get("pestana") == str(pestana)]
    return recetas_guardadas


def obtener(rid) -> dict | None:
    for receta in leer()["recetas"]:
        if receta["id"] == str(rid):
            return receta
    return None


def _nuevo_id(ocupados) -> str:
    indice = 1
    while f"rc{indice}" in ocupados:
        indice += 1
    return f"rc{indice}"


def guardar(peticion) -> dict:
    """Crea o sobreescribe una receta. Devuelve la ficha guardada.

    Lo que no viene en `tareas` se escribe con su valor por defecto: una
    receta guardada tiene que decir lo que hace ENTERA, no una parte y
    el resto adivinado al leerla.
    """
    if not isinstance(peticion, dict):
        raise ErrorReceta("se esperaba un objeto con la receta")
    pestana = str(peticion.get("pestana") or "").strip()
    if pestana not in PESTANAS:
        raise ErrorReceta(f"pestana desconocida: {pestana!r}. Son "
                          + ", ".join(PESTANAS))
    nombre = str(peticion.get("nombre") or "").strip()
    if not nombre:
        raise ErrorReceta("una receta sin nombre no se puede elegir después")

    validas = set(tareas_de(pestana))
    tareas: dict[str, bool] = {}
    for tid, puesta in (peticion.get("tareas") or {}).items():
        if tid not in validas:
            raise ErrorReceta(f"la tarea '{tid}' no es de la pestana {pestana}")
        tareas[tid] = bool(puesta)
    # Lo no opcional va siempre, se diga lo que se diga: una receta que
    # se salte «las imágenes» no es una receta de vídeo.
    for ficha in _tareas_fichas_de(pestana):
        if not ficha["opcional"]:
            tareas[ficha["id"]] = True
        else:
            tareas.setdefault(ficha["id"], True)

    with _LOCK:
        datos = leer()
        ocupados = {r["id"] for r in datos["recetas"]}
        rid = str(peticion.get("id") or "").strip()
        ficha = {"id": rid or _nuevo_id(ocupados), "pestana": pestana,
                 "nombre": nombre,
                 "nota": str(peticion.get("nota") or "").strip(),
                 "tareas": tareas}
        if rid and rid in ocupados:
            datos["recetas"] = [ficha if r["id"] == rid else r
                                for r in datos["recetas"]]
        else:
            datos["recetas"].append(ficha)
        if peticion.get("por_defecto"):
            datos["por_defecto"][pestana] = ficha["id"]
        _escribir(datos)
        return ficha


def borrar(rid) -> bool:
    with _LOCK:
        datos = leer()
        quedan = [r for r in datos["recetas"] if r["id"] != str(rid)]
        if len(quedan) == len(datos["recetas"]):
            raise ErrorReceta(f"no hay ninguna receta '{rid}'")
        datos["recetas"] = quedan
        datos["por_defecto"] = {k: v for k, v in datos["por_defecto"].items()
                                if v != str(rid)}
        _escribir(datos)
        return True


def receta_puesta(pestana) -> dict | None:
    """La receta por defecto de una pestaña, o None."""
    datos = leer()
    rid = datos["por_defecto"].get(str(pestana))
    if not rid:
        return None
    for receta in datos["recetas"]:
        if receta["id"] == rid:
            return receta
    return None


def puestas_de(pestana, receta) -> list[str]:
    """Qué tareas de esta pestaña corren con esta receta. -> [ids]

    EXISTE PARA QUE LA PANTALLA Y LA TANDA DIGAN LO MISMO: la pantalla
    leyendo `receta["tareas"].get(tid, True)` y quien lanzaba recorriendo
    sólo las nombradas no coincidían con una tarea que la receta no
    traía (una guardada antes de que existiera, o de otra versión).
    No fallaba nada; salía un vídeo con menos.

    Lo que no está en la receta vale lo que diga su `de_fabrica`: una
    tarea nueva no puede encenderse sola en un vídeo ya generado.
    """
    tareas = (receta or {}).get("tareas") or {}
    salida = []
    for ficha in _tareas_fichas_de(pestana):
        tid = ficha["id"]
        if tid in tareas:
            if tareas[tid]:
                salida.append(tid)
        elif ficha.get("de_fabrica", True):
            salida.append(tid)
    return salida


def de_fabrica(pestana) -> dict:
    """La receta que se usa sin ninguna guardada.

    Todo puesto: aquí ninguna tarea se declara `de_fabrica: False`, así
    que sin receta guardada la pestaña se hace entera — exactamente lo
    que hacía el botón antes de que existieran las recetas.
    """
    return {"id": "", "pestana": str(pestana), "nombre": "Todo",
            "nota": "sin receta guardada: se hace todo lo que la "
                    "pestana sabe hacer",
            "tareas": {t["id"]: bool(t.get("de_fabrica", True))
                       for t in _tareas_fichas_de(pestana)}}


def resolver(pestana, rid=None, tareas=None) -> dict:
    """La receta con la que se va a ejecutar, mezclando lo pedido y lo guardado.

    Prioridad: lo que manda quien lanza > la receta pedida > la puesta
    por defecto > todo. Lo no opcional se fuerza siempre.
    """
    pestana = str(pestana)
    if pestana not in PESTANAS:
        raise ErrorReceta(f"pestana desconocida: {pestana!r}. Son "
                          + ", ".join(PESTANAS))
    base = (obtener(rid) if rid else None) or receta_puesta(pestana) \
        or de_fabrica(pestana)
    if base.get("pestana") and base["pestana"] != pestana:
        raise ErrorReceta(f"la receta '{base['id']}' es de la pestana "
                          f"'{base['pestana']}', no de '{pestana}'")
    puestas = dict(base.get("tareas") or {})
    validas = set(tareas_de(pestana))
    for tid, valor in (tareas or {}).items():
        if tid in validas:
            puestas[tid] = bool(valor)
    for ficha in _tareas_fichas_de(pestana):
        # una receta GUARDADA antes de que existiera esta tarea no la
        # nombra: ahí manda su defecto de fábrica, no un «True» genérico
        puestas.setdefault(ficha["id"], bool(ficha.get("de_fabrica", True)))
        if not ficha["opcional"]:
            puestas[ficha["id"]] = True
    return dict(base, tareas=puestas)


def catalogo() -> dict:
    """Lo que la pantalla necesita para pintar las recetas. Sin secretos."""
    return {
        "pestañas": PESTANAS,
        "tareas": [dict(t, de_fabrica=bool(t.get("de_fabrica", True)))
                   for t in TAREAS],
        "tandas": TANDAS,
        "recetas": listar(),
        "por_defecto": leer()["por_defecto"],
    }
