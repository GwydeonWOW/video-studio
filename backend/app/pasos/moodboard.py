"""Referencias de estilo hechas a propósito, en vez de las que hubiera.

Réplica del original (`pasos/moodboard.py`) por el camino del «estilo
descrito»: esta réplica no tiene fotogramas de un vídeo de referencia,
así que las láminas se dibujan A PROPÓSITO a partir de la guía escrita
(cada eje es algo que el vídeo va a necesitar resolver: una cara, unos
cuerpos, un interior...). Y al revés NO: la guía no se reescribe nunca
mirando las láminas — sería describir una copia, y la deriva se
congelaría para todo el canal.

EL RIESGO, Y POR QUÉ HAY UNA PERSONA EN MEDIO (regla del original): el
moodboard lo dibuja el mismo modelo que después lo imita. Si deriva, la
deriva se congela y la heredan todas las imágenes. Por eso:
  - nace PROPUESTO y sólo cuenta como aprobado cuando alguien lo ha
    mirado;
  - se corrige POR EJE con una petición escrita («los brazos eran más
    delgados»), porque en la práctica derivan unos ejes y otros no;
  - y un moodboard nunca se genera a partir de otro moodboard.

Diferencia honesta: el motor de imagen de esta réplica no adjunta
referencias en cada plano (prompt compuesto, documentado en
motores/imagen_glm.py), así que el moodboard aquí es la hoja de
comprobación visual del estilo — lo que se mira para decidir si la
guía está bien — y no un adjunto que viaja en cada llamada.

DONDE VIVE
    datos/moodboards/<clave>/              aprobado, global, reutilizable
    datos/moodboards/_propuestas/<clave>/  propuesto, pendiente de mirar

La clave identifica AL ESTILO: sale del CONTENIDO de la guía escrita,
así que dos proyectos con la misma guía comparten moodboard y el
segundo no paga nada.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from . import comun, guia_estilo, p2_brief
from ..motores import reglas

PASO = "moodboard"
PROPUESTAS = "_propuestas"

#: Los ejes que un vídeo necesita ver resueltos. El sujeto es GENÉRICO
#: a propósito: lo que tiene que viajar es el estilo, nunca el
#: contenido de un vídeo concreto.
EJES = {
    "cara": {
        "titulo": "Una cara de cerca",
        "prompt": ("A single character seen in close-up, head and shoulders, "
                   "front view, neutral serious expression, plain flat "
                   "background. Nothing else in the frame."),
    },
    "cuerpos": {
        "titulo": "Varias personas de cuerpo entero",
        "prompt": ("Three ordinary people standing side by side, full body, "
                   "front view, plain flat background, relaxed neutral poses."),
    },
    "interior": {
        "titulo": "Un interior general",
        "prompt": ("A wide shot of an ordinary interior room with furniture, "
                   "seen from a corner, with no people in it."),
    },
    "exterior": {
        "titulo": "Un exterior general",
        "prompt": ("A wide exterior shot of an ordinary street with buildings "
                   "and sky, with no people in it."),
    },
    "objeto": {
        "titulo": "Un objeto de cerca",
        "prompt": ("A close-up of a single everyday object resting on a flat "
                   "surface, filling most of the frame, plain background."),
    },
    # CON SUS ETIQUETAS: la lámina que enseña cómo se rotula este canal
    # era justo la que tenía el rótulo prohibido (comentario del
    # original, que se quedó grabado).
    "diagrama": {
        "titulo": "Un diagrama sencillo",
        "prompt": ("A simple schematic diagram of three boxes connected by "
                   "arrows on a plain background, drawn in the same style. Each "
                   "box holds a simple icon and one short word under it."),
    },
}

ORIGENES = ("banco", "propuesta")


def raiz_banco() -> Path:
    return Path(AJUSTES.datos) / "moodboards"


def raiz_propuestas() -> Path:
    return raiz_banco() / PROPUESTAS


def clave_de(guia: dict | str) -> str:
    """Identidad del ESTILO: su guía escrita (texto o ficha)."""
    texto = guia.get("guia") if isinstance(guia, dict) else guia
    texto = " ".join(str(texto or "").split())
    if not texto:
        return ""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def carpeta_de(clave: str, incluir_propuestas: bool = True) -> Path | None:
    """Dónde vive el moodboard de esta clave, aprobado o propuesto."""
    clave = str(clave or "")
    if not clave:
        return None
    aprobado = raiz_banco() / clave
    if aprobado.is_dir():
        return aprobado
    propuesta = raiz_propuestas() / clave
    if incluir_propuestas and propuesta.is_dir():
        return propuesta
    return None


def ficha_de(clave: str) -> dict:
    """Qué hay hecho de este estilo: sus ejes y su estado.

    Mira las DOS carpetas y las mezcla eje por eje: de cada eje manda
    la lámina de la propuesta si existe, porque es la última dibujada y
    la que está esperando a que alguien la mire. `pendientes` son
    justo esos.
    """
    clave = str(clave or "")
    banco = raiz_banco() / clave
    propuesta = raiz_propuestas() / clave

    ficha = _leer(banco / "ficha.json")
    nueva = _leer(propuesta / "ficha.json")
    coste = (float(ficha.get("coste_usd") or 0.0)
             + float(nueva.get("coste_usd") or 0.0))
    peticiones = dict(ficha.get("peticiones") or {})
    peticiones.update(nueva.get("peticiones") or {})
    ficha.update({k: v for k, v in nueva.items()
                  if k not in ("coste_usd", "peticiones", "estado")})
    ficha["clave"] = clave
    ficha["coste_usd"] = round(coste, 4)
    ficha["peticiones"] = peticiones

    ejes, pendientes = {}, []
    for eje in sorted(EJES):
        en_propuesta = propuesta / f"{eje}.png"
        en_banco = banco / f"{eje}.png"
        if en_propuesta.is_file():
            ejes[eje] = en_propuesta
            pendientes.append(eje)
        elif en_banco.is_file():
            ejes[eje] = en_banco
    ficha["ejes"] = sorted(ejes)
    ficha["pendientes"] = pendientes
    # el estado del conjunto es el del eje más atrasado: con una sola
    # lámina sin mirar, decir «aprobado» mentiría
    ficha["estado"] = ("falta" if not ejes
                       else ("propuesto" if pendientes else "aprobado"))
    return ficha


def version_de(ruta: Path) -> int:
    """Sello de la lámina, para que el navegador no enseñe la cacheada."""
    try:
        return int(ruta.stat().st_mtime)
    except OSError:
        return 0


def prompt_de_eje(eje: str, ficha_guia: dict, peticion: str = "",
                  idioma: str = "") -> str:
    """Lo que se le pide al generador para una lámina de estilo.

    Lleva la guía escrita ENTERA — es toda la verdad del estilo en este
    camino — y la corrección de quien mira, que manda sobre la
    descripción genérica: es lo que hace que «los brazos eran más
    delgados» sirva de algo.

    Y el bloque de reglas de la casa, IGUAL QUE UN PLANO: en la primera
    prueba del original este prompt se montó a mano sin ellas y los tres
    cuerpos salieron SONRIENDO, con la regla que lo prohíbe escrita y
    sin llegar. Eso no puede depender de que alguien se acuerde.
    """
    lineas = ["Produce one single full-frame image for a style reference "
              "sheet.",
              "The written style guide below is the only description of how "
              "this production is drawn: follow every one of its numbers "
              "exactly."]
    if ficha_guia.get("guia"):
        lineas.append(str(ficha_guia["guia"]))
    if ficha_guia.get("evitar"):
        lineas.append(f"Never: {ficha_guia['evitar']}")
    lineas.append((EJES.get(eje) or {}).get("prompt") or "")
    peticion = " ".join(str(peticion or "").split())
    if peticion:
        lineas.append(f"Correction, this takes priority: {peticion}")
    bloque = reglas.bloque_prompt("prompt_imagen")
    if bloque:
        lineas.append(bloque)
    # El idioma HACE FALTA AQUÍ más que en un plano: la lámina del eje
    # «diagrama» viaja después como imagen de referencia dentro de cada
    # plano con componente, así que si sale rotulada en el idioma
    # equivocado ENSEÑA a rotular mal con un ejemplo dibujado. La
    # política vive en la regla; aquí solo el dato.
    nombre = p2_brief.nombre_idioma_en(idioma)
    if nombre:
        lineas.append(f"The language of this production is {nombre}.")
    lineas.append("No watermarks.")
    return " ".join(x for x in lineas if x)


def generar(clave: str, ficha_guia: dict, ejes=None, peticiones=None,
            calidad: str = "medium", avisar=None, proyecto_id: str = "",
            idioma: str = "") -> dict:
    """Dibuja las láminas que faltan y las deja PROPUESTAS.

    'ejes' None son todas; con una lista se rehacen sólo esas, que es lo
    que hace útil el feedback: en la práctica derivan unas y otras
    salen clavadas, y rehacer entero tiraría las buenas.

    Calidad media por defecto (regla del original): esto se genera UNA
    vez por estilo, así que ahorrar aquí es ahorrar en el sitio
    equivocado.
    """
    from ..motores import imagen_glm

    avisar = avisar or (lambda *_: None)
    clave = str(clave or "")
    if not clave:
        raise ValueError("no hay guía escrita: sin ella las láminas saldrían "
                         "con el estilo por defecto del generador")
    pedidos = [e for e in (ejes or EJES) if e in EJES]
    if not pedidos:
        raise ValueError("no hay ningún eje que dibujar")
    peticiones = peticiones or {}
    claves = comun.claves_actuales()
    if not imagen_glm.clave(claves):
        raise imagen_glm.ErrorImagen(
            "falta la clave de GLM para imágenes (Configuración -> claves)")

    carpeta = raiz_propuestas() / clave
    carpeta.mkdir(parents=True, exist_ok=True)
    ficha = _leer(carpeta / "ficha.json")
    ficha.setdefault("peticiones", {})

    hechos, gasto = [], 0.0
    avisar(f"dibujando {len(pedidos)} referencia(s) de estilo "
           f"(calidad {calidad})")
    for numero, eje in enumerate(pedidos, start=1):
        destino = carpeta / f"{eje}.png"
        prompt = prompt_de_eje(eje, ficha_guia, peticiones.get(eje),
                               idioma=idioma)
        imagen_glm.generar(prompt, destino, calidad=calidad, claves=claves)
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto_id or "__estilo",
            operacion="imagen", proveedor="glm", modelo="glm-image",
            calidad=calidad, contexto=f"moodboard:{eje}", proyecto_dir=None)
        hechos.append(eje)
        if peticiones.get(eje):
            ficha["peticiones"][eje] = peticiones[eje]
        avisar(f"{numero} de {len(pedidos)} referencias dibujadas")

    # el coste que se anota arriba es el del medidor global; la ficha
    # guarda el orientativo para que la pantalla lo enseñe
    ficha["coste_usd"] = round(float(ficha.get("coste_usd") or 0.0)
                               + len(hechos)
                               * comun.COSTE_IMAGEN.get(calidad, 0.015), 4)
    ficha["estado"] = "propuesto"
    _escribir(carpeta / "ficha.json", ficha)
    avisar(f"{len(hechos)} referencia(s) dibujadas como propuesta")
    return {"clave": clave, "ejes": hechos, "estado": "propuesto"}


def aprobar(clave: str) -> dict:
    """Mete la propuesta en el banco global. Es la decisión de una persona.

    Se copia EJE A EJE encima de lo que ya hubiera (regla del original,
    que aprendió a costa de perder cinco láminas buenas): rehacer un
    solo eje de un moodboard ya aprobado NO se lleva por delante los
    demás. Sólo entonces se tira la propuesta.
    """
    clave = str(clave or "")
    origen = raiz_propuestas() / clave
    if not clave or not origen.is_dir():
        raise ValueError("no hay ningún moodboard propuesto que aprobar")
    destino = raiz_banco() / clave
    destino.mkdir(parents=True, exist_ok=True)

    aprobadas = []
    for eje in sorted(EJES):
        lamina = origen / f"{eje}.png"
        if lamina.is_file():
            shutil.copyfile(lamina, destino / f"{eje}.png")
            aprobadas.append(eje)

    ficha = _leer(destino / "ficha.json")
    nueva = _leer(origen / "ficha.json")
    coste = (float(ficha.get("coste_usd") or 0.0)
             + float(nueva.get("coste_usd") or 0.0))
    peticiones = dict(ficha.get("peticiones") or {})
    peticiones.update(nueva.get("peticiones") or {})
    ficha.update({k: v for k, v in nueva.items()
                  if k not in ("coste_usd", "peticiones", "estado")})
    ficha.update({"clave": clave, "estado": "aprobado",
                  "coste_usd": round(coste, 4), "peticiones": peticiones})
    _escribir(destino / "ficha.json", ficha)
    shutil.rmtree(origen, ignore_errors=True)
    return {"clave": clave, "estado": "aprobado", "ejes": aprobadas}


def ruta_lamina(clave: str, eje: str, origen: str = "") -> Path | None:
    """La ruta de una lámina (propuesta si la hay, que es lo último)."""
    if eje not in EJES:
        return None
    ficha = ficha_de(clave)
    if origen == "banco":
        ruta = raiz_banco() / str(clave) / f"{eje}.png"
        return ruta if ruta.is_file() else None
    if origen == "propuesta":
        ruta = raiz_propuestas() / str(clave) / f"{eje}.png"
        return ruta if ruta.is_file() else None
    carpeta = carpeta_de(clave)
    if not carpeta:
        return None
    ruta = carpeta / f"{eje}.png"
    return ruta if ruta.is_file() else None


def _leer(ruta: Path) -> dict:
    from ..nucleo.proyecto import leer_json
    datos = leer_json(ruta, {})
    return datos if isinstance(datos, dict) else {}


def _escribir(ruta: Path, datos: dict) -> None:
    from ..nucleo.proyecto import escribir_json
    escribir_json(ruta, datos)
