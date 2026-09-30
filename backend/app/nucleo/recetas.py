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
viven y cuál cuesta dinero). El código que las corre vive en la API
(`rutas_proyectos`), y reutiliza el MISMO camino que el botón de cada
paso — una tarea declarada sin paso real en el grafo no puede existir,
porque la tabla se deriva del grafo.
"""

# El orden NO es estético: es el del grafo (ingesta → ... → render).
# Cada tarea declara su pestaña; `necesita` son los ids de SU MISMA
# pestaña que tienen que ir antes.
TAREAS = [
    {"id": "ingesta", "nombre": "El material de origen", "pestana": "origen",
     "paso": "ingesta", "necesita": [], "cuesta": False,
     "porque": "baja el vídeo o pega el texto del que parte todo"},
    {"id": "brief", "nombre": "El presupuesto de palabras", "pestana": "guion",
     "paso": "brief", "necesita": [], "cuesta": True,
     "porque": "decide cuántas palabras caben en la duración pedida"},
    {"id": "guion", "nombre": "El guion", "pestana": "guion",
     "paso": "guion", "necesita": ["brief"], "cuesta": True,
     "porque": "redacta el guion con las instrucciones del brief"},
    {"id": "voz", "nombre": "La locución", "pestana": "voz",
     "paso": "voz", "necesita": [], "cuesta": True,
     "porque": "graba la narración escena a escena (guion aprobado)"},
    {"id": "revision_audio", "nombre": "La revisión de audio",
     "pestana": "voz", "paso": "revision_audio", "necesita": ["voz"],
     "cuesta": False,
     "porque": "escucha la toma y señala lo que no cuadra"},
    {"id": "assets", "nombre": "Las imágenes", "pestana": "montaje",
     "paso": "assets", "necesita": [], "cuesta": True,
     "porque": "una imagen por escena, de una en una (cuesta dinero)"},
    {"id": "callouts", "nombre": "Los rótulos", "pestana": "montaje",
     "paso": "callouts", "necesita": ["assets"], "cuesta": True,
     "porque": "decide el rótulo de cada escena con las marcas de la voz"},
    {"id": "render", "nombre": "El montaje", "pestana": "montaje",
     "paso": "render", "necesita": ["assets"], "cuesta": False,
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
