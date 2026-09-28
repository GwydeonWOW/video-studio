"""Las transiciones entre planos: el catálogo, quién reparte y cómo se pintan.

ADAPTACIÓN DEL ORIGINAL (pasos/transiciones.py del estudio de referencia)
------------------------------------------------------------------------
El original cocina cada transición con shaders GLSL (hyperframes) sobre un
render que ya escribe PNG por fotograma. Este motor renderiza con ffmpeg
directo, así que cada transición del catálogo trae su efecto `xfade` de
ffmpeg — que es LO QUE DE VERDAD SE VE en el vídeo — y la pantalla recibe
ese mismo nombre para previsualizarlo con la misma familia de efecto. No
hay GLSL aquí porque aquí no habría nada que lo ejecutase: la muestra
correría un shader que el render no corre, y esa es exactamente la pantalla
que miente que este estudio evita.

EL RITMO Y EL CATÁLOGO SON DOS DECISIONES DISTINTAS
---------------------------------------------------
La RANURA (suave / acento) pertenece al corte; este módulo decide QUÉ
transición concreta ocupa ese hueco, y eso se resuelve al RENDERIZAR. La
separación importa por dinero: cambiar la paleta de transiciones deja
obsoleto el render y nada más — ni las imágenes ni las capas.

En el original la ranura la dejaba escrita el motor del guion; aquí se
deriva de forma determinista del propio montaje: un ACENTO cada pocos
planos (el golpe que puntuación es), y suave en el resto. El primer plano
nunca lleva transición: no hay nada de lo que venir.
"""
from __future__ import annotations

from . import sonido

# ===========================================================================
# EL CATÁLOGO
#
#   familia   dos transiciones de la misma familia no van seguidas: lo que
#             cansa no es repetir una, es repetir la CLASE.
#   fuerza    1 discreta · 2 se nota · 3 golpe. De aquí salen las dos bolsas:
#             'suave' coge de fuerza <= 2 y 'acento' de fuerza >= 2.
#   factor    multiplica la duración base. Un latigazo tiene que ser corto o
#             se lee como un barrido; una fuga de luz necesita respirar.
#   xfade     el efecto de ffmpeg que este motor usa de verdad en el corte.
#   defecto   si entra sin que nadie toque nada: la selección de fábrica es
#             sobria a propósito (documental narrado, no videoclip).
# ===========================================================================

CATALOGO = {
    "fundido": {
        "nombre": "Fundido",
        "descripcion": "Un plano se disuelve en el otro. Lo de siempre, y lo que mejor cierra una frase.",
        "familia": "mezcla", "fuerza": 1, "factor": 1.0, "xfade": "fade",
        "defecto": True, "origen": "estudio",
    },
    "flash-through-white": {
        "nombre": "Destello blanco",
        "descripcion": "Pasa por blanco a medio camino. El acento clásico: se nota y no distrae.",
        "familia": "destello", "fuerza": 2, "factor": 0.9, "xfade": "fadewhite",
        "defecto": True, "origen": "estudio",
    },
    "light-leak": {
        "nombre": "Fuga de luz",
        "descripcion": "Un velo de luz entra por una esquina y se lo come todo.",
        "familia": "destello", "fuerza": 2, "factor": 1.5, "xfade": "fadegrays",
        "defecto": True, "origen": "estudio",
    },
    "sdf-iris": {
        "nombre": "Iris",
        "descripcion": "El plano nuevo se abre en círculo desde el centro.",
        "familia": "iris", "fuerza": 2, "factor": 1.1, "xfade": "circleopen",
        "defecto": True, "origen": "estudio",
    },
    "cinematic-zoom": {
        "nombre": "Zoom cinematográfico",
        "descripcion": "Los dos planos se acercan hacia el centro. Muy de cine.",
        "familia": "optica", "fuerza": 2, "factor": 1.4, "xfade": "zoomin",
        "defecto": True, "origen": "estudio",
    },
    "whip-pan": {
        "nombre": "Latigazo",
        "descripcion": "Barrido horizontal con arrastre, como girar la cámara de golpe. Corto por definición.",
        "familia": "barrido", "fuerza": 3, "factor": 0.7, "xfade": "slideleft",
        "defecto": True, "origen": "estudio",
    },
    "chromatic-split": {
        "nombre": "Separación de color",
        "descripcion": "Los canales se abren del centro y vuelven. Discreta y con nervio.",
        "familia": "optica", "fuerza": 2, "factor": 1.0, "xfade": "squeezeh",
        "defecto": False, "origen": "estudio",
    },
    "cross-warp-morph": {
        "nombre": "Deformación cruzada",
        "descripcion": "Los dos planos se deforman uno hacia el otro y se funden por manchas.",
        "familia": "disolvencia", "fuerza": 2, "factor": 1.2, "xfade": "dissolve",
        "defecto": False, "origen": "estudio",
    },
    "domain-warp": {
        "nombre": "Disolución con remolinos",
        "descripcion": "Se disuelve por un frente retorcido, con el borde encendido.",
        "familia": "disolvencia", "fuerza": 3, "factor": 1.3, "xfade": "radial",
        "defecto": False, "origen": "estudio",
    },
    "ridged-burn": {
        "nombre": "Quemado",
        "descripcion": "El plano arde por un frente irregular. Como película quemándose.",
        "familia": "disolvencia", "fuerza": 3, "factor": 1.3, "xfade": "hlslice",
        "defecto": False, "origen": "estudio",
    },
    "ripple-waves": {
        "nombre": "Ondas",
        "descripcion": "Ondas concéntricas desde el centro deforman los dos planos mientras se cambian.",
        "familia": "onda", "fuerza": 2, "factor": 1.2, "xfade": "distance",
        "defecto": False, "origen": "estudio",
    },
    "thermal-distortion": {
        "nombre": "Calor",
        "descripcion": "Temblor de aire caliente subiendo desde abajo. Buena para desiertos y tensión.",
        "familia": "onda", "fuerza": 2, "factor": 1.3, "xfade": "hblur",
        "defecto": False, "origen": "estudio",
    },
    "gravitational-lens": {
        "nombre": "Colapso",
        "descripcion": "El plano que sale se traga hacia el centro, como un agujero negro.",
        "familia": "colapso", "fuerza": 3, "factor": 1.3, "xfade": "circleclose",
        "defecto": False, "origen": "estudio",
    },
    "swirl-vortex": {
        "nombre": "Remolino",
        "descripcion": "Los dos planos giran en espiral en sentidos contrarios. Fuerte: para un salto grande.",
        "familia": "colapso", "fuerza": 3, "factor": 1.2, "xfade": "hrslice",
        "defecto": False, "origen": "estudio",
    },
    "glitch": {
        "nombre": "Glitch",
        "descripcion": "Bloques desplazados y color roto. Para señal, cámaras y ordenadores.",
        "familia": "digital", "fuerza": 3, "factor": 0.8, "xfade": "pixelize",
        "defecto": False, "origen": "estudio",
    },
}

#: Las que entran si nadie elige nada. Lista vacía en los params = «entran
#: las de fábrica», igual que los arquetipos de rótulo.
POR_DEFECTO = tuple(k for k, v in CATALOGO.items() if v["defecto"])

#: Las ranuras que hay: corte (nada), suave (cierra frase), acento (golpe).
RANURAS = ("corte", "suave", "acento")

#: Un acento cada cuántos planos. «Cada pocos»: más a menudo es un
#: salvapantallas, menos es que no exista.
ACENTO_CADA = 5

#: Cuántas transiciones atrás se mira para no repetir familia.
VENTANA_FAMILIA = 3

#: Ninguna transición puede comerse el plano que entra: el tope es una
#: fracción de LO QUE DURA el plano.
FRACCION_MAXIMA = 0.35


def elegidas_de(params) -> list[str]:
    """Las transiciones que entran en este vídeo, validadas contra el catálogo.

    Vacío = las de fábrica: una lista vacía significa «no lo he tocado»,
    no «ninguna».
    """
    pedidas = [str(t) for t in ((params or {}).get("transiciones") or [])]
    validas = [t for t in pedidas if t in CATALOGO]
    return validas or list(POR_DEFECTO)


def _bolsas(elegidas) -> tuple[list[str], list[str]]:
    """Las dos bolsas de donde sale cada ranura, en el orden del catálogo.

    'fundido' es el respaldo de las suaves y está siempre disponible aunque
    nadie lo marque: una ranura suave sin nada que poner tendría que
    degradar a corte, y entonces el ritmo del corte se perdería por una
    casilla desmarcada en otra pantalla.
    """
    suaves = [t for t in CATALOGO if t in elegidas and 1 <= CATALOGO[t]["fuerza"] <= 2]
    acentos = [t for t in CATALOGO if t in elegidas and CATALOGO[t]["fuerza"] >= 2]
    return suaves or ["fundido"], acentos or suaves or ["fundido"]


def _sin_repetir_familia(bolsa, arranque, familias_recientes) -> str:
    """La primera de la bolsa que no repita familia, empezando por 'arranque'."""
    orden = [bolsa[(arranque + i) % len(bolsa)] for i in range(len(bolsa))]
    libres = [t for t in orden if CATALOGO[t]["familia"] not in familias_recientes]
    return (libres or orden)[0]


def resolver(escenas, params=None, semilla=0) -> dict:
    """Qué transición concreta lleva cada plano. Determinista.

    Devuelve {id_de_plano: {"tipo","xfade","duracion","ranura"}}. El primer
    plano nunca lleva transición: no hay nada de lo que venir.

    La RANURA: si la escena trae `transicion` escrita se respeta; si no,
    se deriva del montaje — un acento cada ACENTO_CADA planos y suave en
    el resto. Determinista igual que el reparto de cartas: rehacer el
    render de un plano suelto no puede cambiarle la transición a otro.
    """
    p = params or {}
    elegidas = elegidas_de(p)
    suaves, acentos = _bolsas(elegidas)
    base = float(p.get("duracion_transicion") or 0.4)

    salida, familias = {}, []
    for indice, escena in enumerate(escenas or []):
        sid = escena.get("id")
        if not sid:
            continue
        cruda = str(escena.get("transicion") or "")
        if cruda in RANURAS:
            ranura = cruda
        elif indice > 0 and indice % ACENTO_CADA == 0:
            ranura = "acento"
        else:
            ranura = "suave"
        if indice == 0:
            ranura = "corte"
        if ranura == "corte":
            salida[sid] = {"tipo": "corte", "xfade": None, "duracion": 0.0,
                           "ranura": "corte"}
            continue
        bolsa = acentos if ranura == "acento" else suaves
        arranque = sonido.desempatar(semilla, sid, "transicion") % len(bolsa)
        nombre = _sin_repetir_familia(bolsa, arranque,
                                      set(familias[-VENTANA_FAMILIA:]))
        familias.append(CATALOGO[nombre]["familia"])
        duracion = base * float(CATALOGO[nombre]["factor"])
        plano = float(escena.get("duracion") or
                      (float(escena.get("t_out") or 0) - float(escena.get("t_in") or 0)))
        if plano > 0:
            duracion = min(duracion, plano * FRACCION_MAXIMA)
        salida[sid] = {"tipo": nombre, "xfade": CATALOGO[nombre]["xfade"],
                       "duracion": round(max(0.0, duracion), 3), "ranura": ranura}
    return salida


def cuece_el_anterior(ficha) -> bool:
    """Si esta transición necesita el último fotograma del plano de antes.

    De aquí sale la cascada del re-render: rehacer un plano obliga a
    rehacer el siguiente SÓLO si el siguiente mira hacia atrás. El corte
    no mira.
    """
    return bool(ficha) and ficha.get("tipo") != "corte"


#: El acento cuando no hay paleta (o el color no se puede leer). UNA
#: constante y no dos números en dos sitios.
ACENTO_POR_DEFECTO = "#d8a657"


def _componentes(hexa):
    """'#d8a657' -> [0.847, 0.651, 0.341]. None si no es un color legible."""
    crudo = str(hexa or "").strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    if len(crudo) != 6:
        return None
    try:
        return [int(crudo[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None


def acentos(paleta) -> dict:
    """Los tres colores de acento, derivados del acento de la paleta.

    El oscuro y el claro se derivan en vez de pedir tres colores: la guía
    de estilo ya da una paleta y añadirle dos papeles nuevos sólo para
    esto sería pedirle al modelo que decida algo que es una cuenta.
    """
    crudo = str((paleta or {}).get("acento") or (paleta or {}).get("linea") or "")
    rgb = _componentes(crudo) or _componentes(ACENTO_POR_DEFECTO)
    return {"acento": [round(v, 4) for v in rgb],
            "oscuro": [round(v * 0.45, 4) for v in rgb],
            "claro": [round(min(1.0, v * 1.35 + 0.12), 4) for v in rgb]}


def describir(params=None) -> str:
    """Frase corta con la paleta de transiciones puesta, para la pantalla."""
    elegidas = elegidas_de(params)
    nombres = [CATALOGO[t]["nombre"] for t in CATALOGO if t in elegidas]
    return ", ".join(nombres) if nombres else "solo cortes secos"


def catalogo_para_pantalla(elegidas=None) -> dict:
    """El catálogo para la pantalla, con el efecto que correrá el render.

    La muestra de la interfaz enseña el MISMO efecto que aplicará ffmpeg
    en el corte: una maqueta hecha aparte se desincroniza y entonces se
    elige otra cosa.
    """
    puestas = set(elegidas if elegidas is not None else POR_DEFECTO)
    fichas = []
    for tid, ficha in CATALOGO.items():
        fichas.append({"id": tid, "puesta": tid in puestas,
                       **{k: ficha[k] for k in
                          ("nombre", "descripcion", "familia", "fuerza",
                           "factor", "xfade", "defecto", "origen")}})
    return {"transiciones": fichas, "por_defecto": list(POR_DEFECTO),
            "acento_cada": ACENTO_CADA}
