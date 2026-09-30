"""El PRESET DE CANAL entero, decidido en cuatro campos y generado de una tirada.

Adaptado del original (`pasos/presets_light.py`). El modo editor toma las
decisiones de un canal repartidas por varias pantallas: describir el
estilo, escribir la guía con números, dibujar el moodboard, aprobarlo
mirándolo, escribir el tono, buscar la voz entre ochocientas. Cada
parada es una decisión buena —por eso el modo editor sigue entero— pero
para montar un canal NUEVO son seis paradas antes de haber hecho un
solo vídeo.

El modo light hace las mismas cosas y no para en ninguna. Se le dan
cuatro datos:

    estilo gráfico    imágenes de referencia y/o una descripción escrita
    tono del guion    una descripción escrita
    voz               una descripción escrita
    idioma            uno, elegido a mano

y de ahí sale el preset de canal completo: guía de estilo, referencias
dibujadas, grafismo, instrucciones de guion, voz y mandos. Lo que se
enseña al final son CUATRO cosas —el estilo gráfico, el tono, la voz y
el idioma— y nada más. No hay desglose: si algo no convence se pide en
una frase («que los subtítulos sean más claros») y se rehace ESA de
las tres.

POR QUÉ ES EL TIPO 'canal' Y NO UN TIPO NUEVO
---------------------------------------------
Porque es exactamente lo que el tipo 'canal' ya guardaba: guion +
estilo + voz + grafismo. Un tipo nuevo habría dado dos clases de preset
que fijan lo mismo, dos sitios donde aplicar y dos que mantener. Lo
único que hacía falta era guardar DE DÓNDE salió
(`presets_canal.CLAVES_ORIGEN`), que es lo que permite rehacer una
parte sin volver a pedirlo todo.

Consecuencia buena: un preset hecho aquí se aplica en el modo editor
igual que cualquier otro, y uno montado a mano allí sale en esta
galería en cuanto sea de tipo canal.

POR QUÉ SE GENERA EN UN PROYECTO
--------------------------------
Todo lo que hace falta —escribir la guía, dibujar, describir la voz—
son las MISMAS funciones que corren los botones del modo editor, y
todas trabajan sobre un proyecto: ahí viven las láminas, los params y
la bitácora. Así que el preset se genera en un proyecto TALLER, oculto
de la lista, y al acabar se congela en el preset. No hay un camino
«automático» y otro «a mano»: hay un camino, llamado desde dos sitios.

El taller se queda después de guardar, y esa es la razón de que
rehacer solo el tono no vuelva a escribir la guía: las láminas siguen
ahí. Se borra con el preset.

EL MOODBOARD SE APRUEBA SOLO, Y AQUÍ ESTÁ EL PORQUÉ
---------------------------------------------------
`moodboard.py` dice —y sigue siendo verdad— que las láminas dibujadas
pueden derivar, y que por eso nacen PROPUESTAS y las aprueba una
persona mirándolas. En este modo no hay nadie mirando a mitad de
camino: pararse ahí sería volver a las seis paradas.

Lo que se hace es mover la mirada al FINAL, no quitarla: lo primero
que se ve de un preset recién hecho son LAS PROPIAS LÁMINAS del
moodboard con la cartela y el subtítulo puestos encima, o sea
exactamente lo que va a salir en los vídeos. Si deriva, se ve ahí, y
se corrige con una frase.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from . import comun

# ===========================================================================
# LAS TAREAS
#
# Misma forma que `recetas.TAREAS` y por el mismo motivo: aquí viven los
# DATOS —qué hay, de qué depende cada una, cuál cuesta dinero, cuánto
# tarda— y en las rutas vive QUÉ FUNCIÓN corre cada una, que es la misma
# que corre su botón del modo editor.
#
#   segundos   lo que se espera que tarde, para que la barra sea REALISTA.
#              La barra se reparte por TIEMPO y no por número de tareas:
#              con seis tareas de las que una dura dos minutos y otra
#              tres segundos, contar tareas da una barra que se planta en
#              el 20 % y salta al 90 %.
#   cuesta     si gasta dinero de verdad (imágenes). El tono y la voz van
#              por LLM de texto: céntimos, contados por el medidor.
#   imagenes   cuántas imágenes paga. Se declara y no se deduce porque es
#              lo único que se puede decir ANTES de pulsar, y decirlo
#              antes es la regla de esta casa.
# ===========================================================================

TAREAS = [
    {"id": "guia", "nombre": "La guía de estilo",
     "necesita": [], "segundos": 60, "cuesta": False,
     "porque": "escribe por escrito cómo tiene que verse el vídeo"},
    {"id": "referencias", "nombre": "Las referencias de estilo",
     "necesita": ["guia"], "segundos": 120, "cuesta": True, "imagenes": 6,
     "porque": "dibuja una cara, unos cuerpos, un interior y un objeto en "
               "ese estilo: es lo que después copia cada plano"},
    {"id": "grafismo", "nombre": "El grafismo",
     "necesita": ["guia"], "segundos": 3, "cuesta": False,
     "porque": "saca de la guía el set de diseño y la paleta del texto en "
               "pantalla; no llama a ningún modelo"},
    {"id": "tono", "nombre": "El tono del guion",
     "necesita": [], "segundos": 60, "cuesta": False,
     "porque": "escribe las instrucciones con las que se redactarán los "
               "guiones"},
    {"id": "voz", "nombre": "La voz",
     "necesita": [], "segundos": 80, "cuesta": False,
     "porque": "elige la voz y sus mandos a partir de cómo has dicho que "
               "suene"},
    {"id": "muestra", "nombre": "Las muestras del preset",
     "necesita": ["referencias", "grafismo"], "segundos": 45, "cuesta": False,
     "porque": "pone la cartela y el subtítulo sobre las referencias ya "
               "dibujadas: es lo que se ve en la tarjeta y lo que hay que "
               "mirar"},
]

# ===========================================================================
# CÓMO SE CUENTA ESTO EN PÚBLICO
#
# Se dice QUÉ se está consiguiendo y no CÓMO, en gerundio, sin una palabra
# de la cocina. Esta es además la primera barra que se ve al entrar en el
# modo light, o sea la primera que se graba.
#
# La regla de seguridad es la de siempre: una tarea que no esté aquí dice
# «Trabajando» y se calla.
# ===========================================================================

PUBLICO = {
    "guia": {
        "nombre": "Entendiendo el concepto visual",
        "fases": ["leyendo la imagen", "escribiendo el criterio"],
    },
    "referencias": {
        "nombre": "Dibujando tu mundo",
        "fases": ["dando cara a la gente", "levantando los lugares",
                  "rematando los detalles"],
    },
    "grafismo": {
        "nombre": "Definiendo la identidad",
        "fases": ["eligiendo colores y letras"],
    },
    "tono": {
        "nombre": "Aprendiendo tu forma de contar",
        "fases": ["leyendo cómo hablas", "escribiendo el criterio del relato"],
    },
    "voz": {
        "nombre": "Buscando la voz",
        "fases": ["escuchando candidatas", "afinando el timbre"],
    },
    "muestra": {
        "nombre": "Preparando las muestras",
        "fases": ["montando el ejemplo que vas a ver"],
    },
}

#: Lo que se dice de una tarea que no está en la tabla.
PUBLICO_GENERICO = "Trabajando"


def publico_de(tid, fraccion=None):
    """Cómo se cuenta una tarea del estilo en público."""
    ficha = PUBLICO.get(str(tid)) or {}
    titulo = ficha.get("nombre") or PUBLICO_GENERICO
    fases = ficha.get("fases") or []
    if not fases or fraccion is None:
        return titulo
    try:
        valor = min(1.0, max(0.0, float(fraccion)))
    except (TypeError, ValueError):
        return titulo
    indice = min(len(fases) - 1, int(valor * len(fases)))
    return f"{titulo} — {fases[indice]}"


TAREAS_POR_ID = {t["id"]: t for t in TAREAS}

#: Qué tareas rehace cada uno de los tres botones de feedback. Son TRES y
#: no seis a propósito: el canal ve tres cosas, así que corrige tres cosas.
#:
#: Corregir el estilo gráfico NO vuelve a escribir el tono ni a buscar la
#: voz: eso ya está hecho en el taller y no ha cambiado. Lo que se rehace
#: es lo que la corrección puede tocar —la guía escrita, lo dibujado a
#: partir de ella, el grafismo que sale de ella y las muestras.
PARTES = {
    "estilo": {
        "nombre": "el estilo gráfico",
        "tareas": ("guia", "referencias", "grafismo", "muestra"),
    },
    "tono": {"nombre": "el tono del guion", "tareas": ("tono",)},
    "voz": {"nombre": "la voz", "tareas": ("voz",)},
}


def tareas_de_estilo(encargo):
    """Qué hay que rehacer para cambiar el estilo gráfico. -> tupla

    Son siempre las mismas, y por eso `encargo` no se mira: el estilo sale
    de lo escrito y el taller ya lo tiene. Se queda como función —y con su
    argumento— porque es el sitio donde declarar una excepción si algún
    día una fuente nueva obliga a rehacer algo antes.
    """
    return PARTES["estilo"]["tareas"]


def imagenes_de_parte(parte, encargo=None):
    """Cuántas imágenes paga rehacer esa parte. -> int

    Se suma de la tabla y no se escribe en ningún otro sitio: para decir
    el precio antes de pulsar tiene que salir de donde está el precio.
    """
    ficha = PARTES.get(parte) or {}
    return sum(int((TAREAS_POR_ID.get(t) or {}).get("imagenes") or 0)
               for t in ficha.get("tareas", ()))


#: CAMBIAR EL IDIOMA NO ES REHACER EL ESTILO, y por eso no está en PARTES:
#: no sale como botón de feedback, lo dispara el desplegable de idioma.
#:
#: Lo que hay que adaptar son las dos cosas que llevan LENGUA dentro:
#:
#:   tono      las instrucciones del guion se escriben en el idioma del
#:             canal, así que en otro idioma hay que reescribirlas. Es
#:             una llamada de texto: céntimos.
#:   muestra   el subtítulo y la cartela de las muestras van DIBUJADOS en
#:             la imagen. Pero no hay nada que volver a dibujar: la
#:             muestra es una referencia del estilo con el texto encima, y
#:             la referencia limpia sigue donde estaba. Recomponer es
#:             rasterizar, que no cuesta.
#:
#: Lo que NO se toca: la guía de estilo (va en inglés porque la lee un
#: generador de imágenes, no una persona), las referencias dibujadas, el
#: grafismo y la voz —que ya se eligió para el idioma nuevo—.
TAREAS_DE_IDIOMA = ("tono", "muestra")

_NOMBRES_LLANOS = {"es": "castellano", "en": "inglés"}

#: Lo que se le cuenta a quien acaba de cambiar el idioma de un canal,
#: con el precio delante. Aquí hace más falta que en otros sitios: lo
#: que se acaba de hacer fue casi gratis y lo que se ofrece cuesta.
AVISO_LAMINAS_EN_OTRO_IDIOMA = (
    "las láminas de estilo se dibujaron en {anterior} y ahí se quedan: si "
    "alguna lleva letras dentro (el diagrama casi siempre las lleva), "
    "seguirá rotulada en {anterior} y los vídeos la copiarán. Para pasarlas "
    "a {nuevo} hay que regenerar el estilo: {imagenes} imágenes, unos "
    "{usd} $."
)


def aviso_de_idioma(anterior, nuevo, calidad="medium"):
    """El aviso con su precio, o "" si no hay nada que avisar."""
    anterior = str(anterior or "").strip().lower()
    nuevo = str(nuevo or "").strip().lower()
    if not anterior or not nuevo or anterior == nuevo:
        return ""
    imagenes = imagenes_de_parte("estilo")
    if not imagenes:
        return ""
    por_imagen = comun.COSTE_IMAGEN.get(str(calidad or "medium"),
                                        comun.COSTE_IMAGEN["medium"])
    return AVISO_LAMINAS_EN_OTRO_IDIOMA.format(
        anterior=_NOMBRES_LLANOS.get(anterior, anterior),
        nuevo=_NOMBRES_LLANOS.get(nuevo, nuevo),
        imagenes=imagenes,
        usd=f"{imagenes * por_imagen:.2f}".replace(".", ","))


# ===========================================================================
# EL RITMO DEL VÍDEO
#
# UN SOLO MANDO QUE RELLENA LA HORQUILLA DE DURACIÓN DE UNA ESCENA
# (`brief.ritmo_min/max`, en segundos por escena). Es el mismo mando que
# en el modo editor se escribe con dos números; aquí es un deslizador.
#
# El escalón es geométrico y no lineal: el ritmo se percibe en
# proporción, así que bajar de 40 a 28 se nota lo mismo que bajar de 15
# a 10.
# ===========================================================================

RITMOS = [
    {"id": "muy_lento", "nombre": "Muy lento",
     "ritmo_min": 40, "ritmo_max": 70, "media_s": 48.0,
     "velocidad": 0.9},
    {"id": "lento", "nombre": "Lento",
     "ritmo_min": 28, "ritmo_max": 48, "media_s": 34.0,
     "velocidad": 0.95},
    {"id": "medio", "nombre": "Medio",
     "ritmo_min": 18, "ritmo_max": 36, "media_s": 24.0,
     "velocidad": 1.0},
    {"id": "rapido", "nombre": "Rápido",
     "ritmo_min": 10, "ritmo_max": 24, "media_s": 15.0,
     "velocidad": 1.05},
    {"id": "muy_rapido", "nombre": "Muy rápido",
     "ritmo_min": 6, "ritmo_max": 15, "media_s": 9.5,
     "velocidad": 1.1},
]

RITMO_POR_DEFECTO = "medio"
RITMOS_POR_ID = {r["id"]: r for r in RITMOS}

#: CINCO RITMOS, TRES VELOCIDADES DE VOCES. La velocidad de la voz y la
#: duración de una escena son DOS ejes, no uno: un montaje rápido con voz
#: normal es una combinación que funciona. Por eso el ritmo mueve la voz
#: UN escalón como mucho.
#:
#: Y solo rellena si TU no has dicho nada de velocidad. Quien decide si
#: lo dijiste es el propio texto con el que se elige la voz: lo que
#: escribes manda, lo que no escribes lo rellena el ritmo. Es la regla
#: de todo este modo.


def ritmo_de(id_ritmo):
    """La ficha de un ritmo, con el defecto si no se conoce."""
    return RITMOS_POR_ID.get(str(id_ritmo or "").strip().lower()) \
        or RITMOS_POR_ID[RITMO_POR_DEFECTO]


def coste_por_minuto(id_ritmo, calidad="low"):
    """Lo que cuesta un minuto de vídeo a este ritmo. -> USD

    Es la única cifra de dinero que este modo enseña: un minuto son
    60/media_s escenas, y cada escena una imagen. No incluye lo que se
    paga UNA vez por estilo (las referencias dibujadas): eso ya se dice
    al crearlo.
    """
    ficha = ritmo_de(id_ritmo)
    por_imagen = comun.COSTE_IMAGEN.get(str(calidad or "low"),
                                        comun.COSTE_IMAGEN["low"])
    return round((60.0 / max(1.0, float(ficha["media_s"]))) * por_imagen, 3)


def params_de_ritmo(id_ritmo):
    """Qué se escribe en los params de cada paso. -> {paso: {clave: valor}}

    Se devuelve por PASO y no suelto por la misma razón que
    `presets_canal.cambios_para`: quien sabe qué clave va a qué paso es
    esta tabla, y repartir esa regla entre la pantalla y el servidor es
    como se acaba con dos versiones que se contradicen.
    """
    ficha = ritmo_de(id_ritmo)
    return {"brief": {"ritmo_min": ficha["ritmo_min"],
                      "ritmo_max": ficha["ritmo_max"]}}


def ritmo_parecido(ritmo_min=None, ritmo_max=None):
    """El ritmo cuya horquilla de escena se parece más a esa. -> ficha

    Hace falta para el modo EDITOR, que no guarda ningún ritmo: allí se
    escriben `brief.ritmo_min` y `ritmo_max` a mano. Para decir cuánto
    va a costar un vídeo hace falta la duración MEDIA de una escena, y
    esa está declarada por ritmo y no se deduce de la horquilla.
    """
    if ritmo_min is None and ritmo_max is None:
        return ritmo_de(RITMO_POR_DEFECTO)
    minimo = float(ritmo_min if ritmo_min is not None else ritmo_max)
    maximo = float(ritmo_max if ritmo_max is not None else ritmo_min)
    return min(RITMOS, key=lambda r: (abs(r["ritmo_min"] - minimo)
                                      + abs(r["ritmo_max"] - maximo)))


def contexto_de_ritmo(id_ritmo):
    """Cómo se le cuenta el ritmo a quien elige la voz. -> frase, o ''."""
    ficha = ritmo_de(id_ritmo)
    return (f"El montaje va a ir a escenas de unos {ficha['media_s']:.0f} s "
            f"de media (ritmo «{ficha['nombre'].lower()}»).")


def ficha_de_ritmo(id_ritmo, calidad="low"):
    """El ritmo tal y como lo enseña la pantalla: solo dos cifras."""
    ficha = dict(ritmo_de(id_ritmo))
    ficha["usd_por_minuto"] = coste_por_minuto(ficha["id"], calidad)
    return ficha


class ErrorEncargo(ValueError):
    """Lo que ha llegado del navegador no vale, y se dice por qué."""


# ===========================================================================
# EL ENCARGO: los cuatro campos
# ===========================================================================

#: Los idiomas que sabe escribir el estudio entero (guion y tono).
IDIOMAS = ("es", "en")

#: Cuántas imágenes de referencia se pueden adjuntar al estilo. Es un
#: tope de SUBIDA, no de generación: las aportadas son material humano
#: que la guía lee tal cual — el tope existe para que un catálogo entero
#: no acabe pegado a una sola llamada, no para recortar el kit del canal.
MAX_IMAGENES_ESTILO = 24


def max_imagenes_estilo():
    """El tope de imágenes de referencia del estilo. -> int

    Función y no constante directa para que la API y la pantalla digan
    «24» del mismo sitio que lo exige `validar_encargo`.
    """
    return MAX_IMAGENES_ESTILO


def validar_encargo(crudo):
    """Deja el encargo limpio, o levanta diciendo qué falta. -> dict

    El estilo gráfico son IMÁGENES DE REFERENCIA y/o una descripción
    escrita. Con imágenes la fuente es lo que se ve (el kit visual del
    canal) y lo escrito acompaña; sin imágenes la descripción escrita es
    la única fuente — y con menos de ocho letras se inventa todo lo que
    no se dice, que es casi todo.
    """
    datos = crudo if isinstance(crudo, dict) else {}
    limpio = {}

    nombre = " ".join(str(datos.get("nombre") or "").split())
    if not nombre:
        raise ErrorEncargo("ponle un nombre al canal: es lo que se lee en la "
                           "tarjeta y lo único que distingue un preset de "
                           "otro")
    limpio["nombre"] = nombre[:80]

    idioma = str(datos.get("idioma") or "").strip().lower()
    if idioma not in IDIOMAS:
        raise ErrorEncargo(
            f"idioma desconocido: {idioma!r}. Los que hay son: "
            + ", ".join(IDIOMAS))
    limpio["idioma"] = idioma

    # El ritmo tiene defecto y no se exige: es un deslizador, y un
    # deslizador siempre está en algún sitio. Uno desconocido cae en el
    # de en medio en vez de tumbar el encargo.
    limpio["ritmo"] = ritmo_de(datos.get("ritmo"))["id"]

    # EL ESTILO GRÁFICO: las imágenes aportadas y/o una descripción.
    # `estilo_imagenes` son NOMBRES de ficheros ya subidos al buzón de
    # aportadas (la ruta la resuelve la ruta que siembra, no el encargo:
    # un encargo con rutas absolutas dentro no se puede copiar ni
    # congelar).
    prompt = " ".join(str(datos.get("estilo_prompt") or "").split())
    imagenes = datos.get("estilo_imagenes")
    if imagenes is None:
        imagenes = []
    if not isinstance(imagenes, list):
        raise ErrorEncargo("«estilo_imagenes» tiene que ser una lista de "
                           "nombres de imágenes")
    imagenes = [str(n).strip() for n in imagenes if str(n).strip()]
    if len(imagenes) > MAX_IMAGENES_ESTILO:
        raise ErrorEncargo(
            f"has adjuntado {len(imagenes)} imágenes y el tope son "
            f"{MAX_IMAGENES_ESTILO}")
    if prompt and len(prompt) < 8:
        raise ErrorEncargo(
            "las indicaciones del estilo gráfico son opcionales cuando hay "
            "imágenes, pero con dos palabras no dicen nada: descríbelo con "
            "algo más de detalle o deja solo el material")
    if not imagenes and not prompt:
        raise ErrorEncargo(
            "falta el estilo gráfico: adjunta al menos una imagen que ya "
            "tenga el aspecto que quieres, o describe con tus palabras cómo "
            "quiero verte («cómic europeo de línea clara, fondos de "
            "acuarela»)")
    if imagenes:
        limpio["estilo_imagenes"] = imagenes
    limpio["estilo_prompt"] = prompt

    # EL TONO DEL GUION: también escrito. No hay nada que copiar, hay
    # algo que decidir, y un párrafo sobre cómo se cuenta una historia
    # sí basta para escribir las instrucciones.
    prompt = " ".join(str(datos.get("tono_prompt") or "").split())
    if not prompt:
        raise ErrorEncargo("falta el tono del guion: describe con tus "
                           "palabras cómo quieres que suene («seco y sin "
                           "adjetivos, que los datos hablen solos»)")
    if len(prompt) < 8:
        raise ErrorEncargo(
            "describe el tono del guion con algo más de detalle: con dos "
            "palabras se lo inventa entero")
    limpio["tono_prompt"] = prompt

    voz = " ".join(str(datos.get("voz_prompt") or "").split())
    if not voz:
        raise ErrorEncargo("falta la voz: describe cómo quieres que suene "
                           "(«grave, pausada, sin dramatismo»)")
    if len(voz) < 8:
        raise ErrorEncargo(
            "describe la voz con algo más de detalle: con dos palabras se "
            "lo inventa entero")
    limpio["voz_prompt"] = voz

    # LA VOZ ELEGIDA A MANO, opcional: el id de una voz del catálogo (lo
    # normal, la clonada del canal). Con ella la descripción sigue
    # valiendo —pone la velocidad y el color— pero la voz no se elige:
    # es esa.
    voz_id = " ".join(str(datos.get("voz_id") or "").split())
    if voz_id and not re.match(r"^[A-Za-z0-9_-]{8,64}$", voz_id):
        raise ErrorEncargo("«voz_id» no parece un id de voz de ElevenLabs")
    limpio["voz_id"] = voz_id

    # AQUÍ NO HAY PERSONAJES DEL CANAL NI LLAMADAS A LA ACCIÓN, y las dos
    # ausencias son decisiones:
    #
    #   * los personajes fijos se retiraron enteros. Lo que queda es el
    #     REPARTO de cada vídeo (catálogo visual), que es donde vive la
    #     gente que sale en los planos.
    #   * lo que cambia entre dos vídeos del mismo canal no se decide en
    #     el estilo: se decide vídeo por vídeo.
    return limpio


def tareas_de(encargo, solo=None):
    """Las tareas que aplican a este encargo, en orden de declaración.

    `solo` recorta a un subconjunto (los tres botones de feedback),
    arrastrando lo que dependa de ello dentro del propio subconjunto.
    """
    tareas = list(TAREAS)
    if solo is not None:
        pedidas = set(solo)
        tareas = [t for t in tareas if t["id"] in pedidas]
    return tareas


def tandas_de(encargo, solo=None):
    """Las tareas agrupadas en TANDAS: lo de una tanda puede correr a la vez.

    Es lo que hace que el tono y la voz —que no dependen de nada— corran
    mientras se escribe la guía, que es la tarea larga. Sin esto la
    creación de un preset sería la suma de los seis tiempos en vez del
    camino crítico.
    """
    tareas = tareas_de(encargo, solo)
    disponibles = {t["id"] for t in tareas}
    nivel, orden = {}, []
    pendientes = list(tareas)
    while pendientes:
        antes = len(pendientes)
        for tarea in list(pendientes):
            faltan = [d for d in tarea["necesita"]
                      if d in disponibles and d not in nivel]
            if faltan:
                continue
            previos = [nivel[d] for d in tarea["necesita"] if d in nivel]
            nivel[tarea["id"]] = (max(previos) + 1) if previos else 0
            orden.append(tarea)
            pendientes.remove(tarea)
        if len(pendientes) == antes:
            raise ErrorEncargo("ciclo en las dependencias del preset: "
                               + ", ".join(t["id"] for t in pendientes))
    tandas = []
    for tarea in orden:
        indice = nivel[tarea["id"]]
        while len(tandas) <= indice:
            tandas.append([])
        tandas[indice].append(tarea)
    return tandas


def segundos_de(tarea):
    """Lo que se espera que tarde ESTA tarea.

    Por ahora sale de la tabla escrita: los tiempos reales por tarea del
    taller no están en las estadísticas por paso (que cuentan pasos del
    grafo, no tareas de un taller). El día que se midan, el historial
    manda — la firma de esta función ya es la de un respaldo.
    """
    return float(tarea["segundos"])


def plan_de(encargo, solo=None):
    """El plan completo, con los tiempos con los que se pinta la barra.

    Devuelve {tandas: [[tarea...]], segundos: total, imagenes}. El total
    es la suma del MÁXIMO de cada tanda, no la suma de todo: lo de una
    tanda corre a la vez, y una barra que suma tiempos paralelos promete
    el doble de lo que va a tardar.
    """
    tandas = tandas_de(encargo, solo)
    fichas, total = [], 0.0
    for tanda in tandas:
        conjunto = []
        for tarea in tanda:
            ficha = dict(tarea)
            ficha["segundos"] = round(segundos_de(tarea), 1)
            ficha["publico"] = publico_de(tarea["id"])
            conjunto.append(ficha)
        duracion = max([f["segundos"] for f in conjunto] or [0.0])
        for ficha in conjunto:
            ficha["desde"] = round(total, 1)
            ficha["tanda_segundos"] = duracion
        total += duracion
        fichas.append(conjunto)
    sueltas = [t for tanda in fichas for t in tanda]
    return {"tandas": fichas, "segundos": round(total, 1),
            "imagenes": sum(int(t.get("imagenes") or 0) for t in sueltas),
            "tareas": sueltas}


# ===========================================================================
# LAS MUESTRAS: la cara del preset
#
# Las láminas de referencia del estilo, con su cartela y su subtítulo
# puestos por el MISMO código que dibuja el vídeo (`p8_render`: el mismo
# _rotulo_png y el mismo _cartela_png que monta el render). Es lo único
# que se ve de un preset recién hecho, así que tiene que ser lo que va a
# salir: una miniatura pintada aparte con otra tipografía sería una
# promesa que el render no cumple.
#
# NO SE DIBUJA NADA NUEVO PARA ESTO. Antes (en el original) eran cuatro
# planos dibujados a propósito, y las láminas iban aparte y limpias en
# una segunda fila. Eran cuatro imágenes pagadas por estilo para enseñar
# lo mismo que ya enseñaban las láminas —que además son las que el
# generador copia de verdad en cada plano, o sea la promesa más honesta
# que se puede hacer.
# ===========================================================================

#: EL TEXTO DE LAS MUESTRAS, EN EL IDIOMA DEL ESTILO.
#:
#: La muestra existe para ENSEÑAR cómo va a quedar el vídeo, y un
#: subtítulo en otro idioma ya no enseña eso — ni la longitud de línea,
#: ni dónde parte, ni cómo se ve la caja con esa cantidad de texto.
#:
#: Las cartelas NO son un dibujo aparte: salen del MISMO motor que las
#: escribe en el vídeo (`pasos/cartelas.py`), con un juego propio y
#: traducido, corto a propósito — dos plantillas por idioma bastan para
#: ver la tipografía, la paleta y el velo, que es lo que se juzga. Un
#: idioma que no esté cae en castellano.
MUESTRAS_POR_IDIOMA = {
    "es": {
        "locucion": (
            "Una tarde de octubre, alguien abrió una puerta que llevaba "
            "años cerrada. Nadie lo notó hasta seis meses después. Para "
            "entonces, lo que había dentro ya estaba a la venta, y el "
            "precio era ridículo."),
        "frases": (
            "Así se ve un plano de este canal con su subtítulo debajo",
            "El texto entra cuando se dice y se va cuando termina la frase",
            "Cada palabra aparece sincronizada con la locución",
        ),
        "cartelas": (
            {"plantilla": "cifra",
             "datos": {"cifra": "10.000.000", "label": "cuentas a la venta"}},
            {"plantilla": "cita",
             "datos": {"texto": "Una contraseña era toda la cerradura",
                       "quien": "el peritaje"}},
        ),
    },
    "en": {
        "locucion": (
            "One October afternoon, someone opened a door that had been "
            "shut for years. Nobody noticed for six months. By then, what "
            "was inside had already been put up for sale, and the price "
            "was absurd."),
        "frases": (
            "This is how a shot of this channel looks with its subtitle",
            "The text comes in when it is said and leaves at line's end",
            "Every word appears in sync with the narration",
        ),
        "cartelas": (
            {"plantilla": "cifra",
             "datos": {"cifra": "10,000,000", "label": "accounts up for sale"}},
            {"plantilla": "cita",
             "datos": {"texto": "One password was the whole lock",
                       "quien": "the audit"}},
        ),
    },
}


def muestras_de_idioma(idioma):
    """El juego de textos de ese idioma, con el castellano de respaldo."""
    return MUESTRAS_POR_IDIOMA.get(str(idioma or "").strip().lower()) \
        or MUESTRAS_POR_IDIOMA["es"]


#: En cuántas columnas se apila la cara de la tarjeta. DOS, y las filas
#: salen de cuántas muestras haya: la hoja crece hacia abajo en vez de
#: dejar fuera las que no caben, que es lo que hacía el 2x2 con seis
#: muestras.
COLUMNAS_MINIATURA = 2

#: Hasta cuántas muestras puede tener un estilo. NO es una decisión de
#: diseño —son las que tenga el moodboard, hoy seis— sino el tope al que
#: buscarlas en el disco: `muestra1.png`, `muestra2.png`...
MUESTRAS_MAX = 8


def nombres_de_muestra():
    """Cómo se pueden llamar las muestras sueltas, en orden. -> [nombres]"""
    return [f"muestra{n}.png" for n in range(1, MUESTRAS_MAX + 1)]


#: Cuántas de las muestras llevan cartela. DOS de seis: la fila tiene
#: que parecerse al vídeo terminado, y en un vídeo la narración no para
#: —subtítulo en casi todos los planos— pero una cartela sale cada
#: varios. Con las seis encarteladas no se enseña el canal, se enseña
#: una promo del rotulador.
CARTELAS_EN_MUESTRAS = 2


def _posiciones_de_cartela(cuantas, semilla):
    """Qué muestras llevan cartela: repartidas y nunca dos seguidas.

    LA SEMILLA CORRE EL JUEGO, NO LO SORTEA. Decide DÓNDE empieza la
    rueda. Sorteándolo salían dos cartelas seguidas.
    """
    paso = max(1, cuantas // max(1, CARTELAS_EN_MUESTRAS))
    salto = random.Random(f"{semilla}:muestras").randrange(max(1, paso))
    return [i for i in range(cuantas) if (i + salto) % paso == 0][
        :CARTELAS_EN_MUESTRAS]


def componer(laminas, destino, grafismo_params, semilla=""):
    """Monta las muestras con sus capas puestas. -> {miniatura, celdas}

    Salen las DOS cosas del mismo trabajo y por eso se hacen a la vez:

        celdas      las sueltas, que es como se miran al editar el
                    estilo —una tras otra, a lo ancho, y cada una legible
        miniatura   todas ellas en dos columnas, que es la cara de la
                    tarjeta de la galería

    Componer dos veces sería pagar dos veces el mismo dibujo.

    `laminas` son las láminas LIMPIAS del estilo —las mismas que copia
    cada plano del vídeo— en el orden en que se van a enseñar. El
    subtítulo se compone con `p8_render._rotulo_png` y la cartela con
    `cartelas.png_carta`, que son EXACTAMENTE lo que monta el render:
    componer aquí a mano con otra tipografía habría dado una miniatura
    que no se parece al vídeo.

    `grafismo_params` trae {diseno, paleta, subtitulo_tam, idioma}.
    """
    from PIL import Image                                   # noqa: PLC0415

    from . import cartelas as cartelas_motor
    from . import p8_render
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    idioma = str((grafismo_params or {}).get("idioma") or "es")
    textos = muestras_de_idioma(idioma)
    paleta = (grafismo_params or {}).get("paleta") or {}
    diseno = str((grafismo_params or {}).get("diseno") or "pastilla")
    tam = (grafismo_params or {}).get("subtitulo_tam") or "normal"

    limpias = [Path(ruta) for ruta in laminas if ruta and Path(ruta).is_file()]
    if not limpias:
        raise RuntimeError("no hay láminas que componer: el moodboard no "
                           "tiene referencias dibujadas")
    cartelas_en = _posiciones_de_cartela(len(limpias), semilla)

    trabajo = destino.parent / "_muestras"
    trabajo.mkdir(parents=True, exist_ok=True)
    celdas: list[Path] = []
    for indice, lamina in enumerate(limpias):
        base = Image.open(lamina).convert("RGB")
        base = base.resize((p8_render.ANCHO, p8_render.ALTO), Image.LANCZOS)
        if indice in cartelas_en:
            # UN PLANO DE TEXTO: la cartela va SOBRE la lámina con su
            # velo, escrita del todo — igual que en el render, y sin
            # subtítulo encima.
            ficha = textos["cartelas"][indice % len(textos["cartelas"])]
            salida = trabajo / f"celda{indice + 1}.png"
            cartelas_motor.png_carta(ficha, paleta=paleta, base=base) \
                .save(salida, "PNG")
            celdas.append(salida)
            continue
        frase = textos["frases"][indice % len(textos["frases"])]
        rotulo = Image.open(p8_render._rotulo_png(
            frase, trabajo / f"celda{indice + 1}.png",
            ancho_max=1400, diseno=diseno, paleta=paleta, tam=tam))
        ancho_objetivo = int(p8_render.ANCHO * 0.86)
        if rotulo.width > ancho_objetivo:
            alto = round(rotulo.height * ancho_objetivo / rotulo.width)
            rotulo = rotulo.resize((ancho_objetivo, alto), Image.LANCZOS)
        x = (base.width - rotulo.width) // 2
        y = base.height - rotulo.height - int(base.height * 0.06)
        base.paste(rotulo, (x, y), rotulo)
        salida = trabajo / f"celda{indice + 1}.png"
        base.save(salida, "PNG")
        celdas.append(salida)

    # las SUELTAS, con su nombre definitivo, para poder servirlas una a
    # una y ponerlas en fila al editar el estilo.
    #
    # `muestraN.png` es la lámina CON su cartela o su subtítulo encima.
    # NO es una referencia de estilo y no puede serlo nunca: si entrara
    # en el prompt de un plano, el generador copiaría esos rótulos —que
    # son grafismo de la casa, no de la escena— como si fueran parte del
    # dibujo. Las referencias son la lámina LIMPIA, que sigue intacta
    # donde estaba.
    sueltas = []
    for indice, ruta in enumerate(celdas, start=1):
        final = destino.parent / f"muestra{indice}.png"
        try:
            Image.open(ruta).convert("RGB").save(final, "PNG")
            sueltas.append(final)
        except Exception:                                   # noqa: BLE001
            continue

    # LA CARA DE LA TARJETA: LAS MISMAS, TODAS, EN DOS COLUMNAS.
    #
    # Cada celda sigue siendo 16:9 entero, o sea que ninguna se recorta.
    # La hoja deja de ser 16:9 y pasa a ser 32:27, que es lo que la
    # tarjeta reserva.
    celda_w = p8_render.ANCHO // COLUMNAS_MINIATURA
    celda_h = round(celda_w * p8_render.ALTO / p8_render.ANCHO)
    filas = max(1, -(-len(celdas) // COLUMNAS_MINIATURA))    # techo de la división
    hoja = Image.new("RGB", (celda_w * COLUMNAS_MINIATURA, celda_h * filas),
                     (11, 12, 9))
    for indice, ruta in enumerate(celdas):
        try:
            foto = Image.open(ruta).convert("RGB")
        except Exception:                                   # noqa: BLE001
            continue
        foto = foto.resize((celda_w, celda_h), Image.LANCZOS)
        hoja.paste(foto, ((indice % COLUMNAS_MINIATURA) * celda_w,
                          (indice // COLUMNAS_MINIATURA) * celda_h))
    hoja.save(destino, "PNG")
    return {"miniatura": str(destino), "celdas": [str(x) for x in sueltas]}
