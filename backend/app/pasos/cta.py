"""Las llamadas a la acción del vídeo: la presentación y los dos
momentos en que se le pide algo a quien mira.

Tres momentos, y los tres son iguales por dentro: una casilla y lo que
se quiere que se diga.

    cta = {
      "presentacion": {"puesto": False, "texto": ""},
      "cta_medio":    {"puesto": False, "texto": ""},
      "cta_final":    {"puesto": False, "texto": ""},
    }

Son tres casillas INDEPENDIENTES y las tres vienen APAGADAS: se marca
solo lo que se quiera —solo la presentación, solo el cierre, las tres o
ninguna—. Un vídeo no pide nada mientras nadie diga que lo pida: lo que
se cuela solo es lo que nadie ha decidido. Y los tres son iguales a
propósito —la presentación no pide nada y las otras dos sí, pero desde
la pantalla y desde el prompt son el mismo gesto: se deja de narrar y
se habla a quien está mirando—; separarlos en dos mecanismos habría
dado dos sitios donde escribir lo mismo.

LO QUE SE ESCRIBE ES UNA INDICACIÓN, NO UN TEXTO FINAL
------------------------------------------------------
En la casilla se dice QUÉ se quiere que pida —«que se suscriba», «que
visite mi web», «que se apunte a la lista»— y el redactor lo escribe
con las palabras de ESE vídeo. No es una plantilla que se pega tal
cual, y por eso el prompt lo llama patrón: una frase idéntica repetida
en cada vídeo se oye como una cuna.

Aqui no se busca nada fuera. Lo que hay es lo que se escribe: ni
catálogos de producto, ni material de la web, ni enlaces que alguien
tenga que mantener al día.

SON DEL VÍDEO, Y SOLO DEL VÍDEO
-------------------------------
Viven en los params del guion, así que cambiarlos deja obsoleto el
guion y lo que cuelga de él, que es justo lo que tiene que pasar: el
texto que se redacta depende de ellos.

Y NO viajan en el estilo del canal, a propósito. Se deciden al encargar
CADA vídeo, que es donde se sabe qué se quiere pedir esta vez: un vídeo
puede querer mandar a la web y el siguiente solo pedir un comentario.
Si el estilo se las llevara, elegir un estilo pisaría lo que se acaba
de escribir para este vídeo —lo contrario de lo que espera quien elige
un estilo—, y habría dos sitios donde mirar cuando lo que sale no es lo
que se pidió (`nucleo/estilo.aplicar_a_params` no las toca).
"""
from __future__ import annotations

import copy

#: Los tres momentos, en el orden en que salen en el vídeo.
MOMENTOS = ("presentacion", "cta_medio", "cta_final")

#: Los dos que son una llamada a la acción. La presentación no lo es
#: —no pide nada— y por eso se cuenta aparte cuando hay que decir
#: cuántas hay.
LLAMADAS = ("cta_medio", "cta_final")

#: Cómo se llama cada uno en la pantalla y en los avisos.
ETIQUETA = {
    "presentacion": "la presentación",
    "cta_medio": "la llamada a la acción de mitad",
    "cta_final": "la llamada a la acción del cierre",
}

#: Dónde cae cada uno. Es lo que el redactor necesita para colocarlo, y
#: se dice en términos del guion —escenas y secciones— porque es lo
#: único que él ve.
SITIO = {
    "presentacion": ("EN LA PRIMERA ESCENA DESPUÉS DEL GANCHO de entrada, "
                     "nunca en el propio gancho: el gancho es lo único que "
                     "sujeta a quien acaba de llegar."),
    "cta_medio": ("A MITAD DEL VÍDEO, en el corte entre dos secciones y "
                  "justo después de haber contado algo que se sostiene solo. "
                  "Se apoya en lo que se acaba de explicar; no se mete en "
                  "medio de una explicación."),
    "cta_final": ("EN LA ÚLTIMA ESCENA, como cierre. Es la única que puede "
                  "pedir dos cosas seguidas, y aun así corta."),
}

#: Lo que se dice en cada momento cuando nadie ha escrito nada. No es
#: un texto prefabricado —el redactor lo escribe con sus palabras— sino
#: QUÉ decir.
POR_OMISION = {
    "presentacion": ("quién eres y qué se va a ver en este vídeo, en una "
                     "frase y sin currículum"),
    "cta_medio": "que se suscriba o deje un comentario",
    "cta_final": "que se suscriba y vea otro vídeo del canal",
}

#: Lo que lleva un vídeo cuyo encargo no ha tocado nada: NADA. Las tres
#: apagadas, y es deliberado — un vídeo no se presenta ni pide nada
#: mientras nadie lo marque.
POR_DEFECTO = {
    "presentacion": {"puesto": False, "texto": ""},
    "cta_medio": {"puesto": False, "texto": ""},
    "cta_final": {"puesto": False, "texto": ""},
}

#: Un párrafo largo describiendo una llamada a la acción no es una
#: llamada a la acción: es un guion escrito en la casilla de al lado.
#: El tope corta ahí.
MAX_TEXTO = 600


# ------------------------------------------------------------------ params

#: Lo que este módulo aporta a los params del guion: un solo sitio
#: donde están escritos los defectos.
PARAMS_POR_DEFECTO = {"cta": copy.deepcopy(POR_DEFECTO)}


def normalizar(crudo, estricto=True) -> dict:
    """Los tres momentos, completos y con los tipos correctos.

    SIN NADA GUARDADO, LOS TRES APAGADOS. La pantalla lee lo GUARDADO,
    así que no se deduce nada aquí: una pantalla que dice una cosa y un
    vídeo que hace otra es peor que una casilla que se marca en un clic.
    """
    ficha = copy.deepcopy(POR_DEFECTO)
    if crudo in (None, ""):
        return ficha
    if not isinstance(crudo, dict):
        if estricto:
            raise ValueError("cta tiene que ser un objeto con presentacion, "
                             "cta_medio y cta_final")
        return ficha
    for momento in MOMENTOS:
        ranura = crudo.get(momento)
        if ranura in (None, ""):
            continue
        if not isinstance(ranura, dict):
            if estricto:
                raise ValueError(f"cta.{momento} tiene que ser un objeto con "
                                 f"puesto y texto")
            continue
        destino = ficha[momento]
        if "puesto" in ranura:
            destino["puesto"] = bool(ranura["puesto"])
        texto = " ".join(str(ranura.get("texto") or "").split())
        if estricto and len(texto) > MAX_TEXTO:
            raise ValueError(f"lo que se pide en {ETIQUETA[momento]} son "
                             f"{len(texto)} caracteres y el tope son "
                             f"{MAX_TEXTO}: es una frase, no un guion")
        destino["texto"] = texto[:MAX_TEXTO]
    return ficha


def _normalizar(params: dict, estricto=True) -> dict:
    """Lo que este módulo aporta a los params ya normalizados del guion."""
    return {"cta": normalizar((params or {}).get("cta"), estricto=estricto)}


def activos(ficha) -> list[tuple[str, dict]]:
    """Los momentos que este vídeo lleva de verdad. -> [(momento, ranura)]"""
    ficha = ficha if isinstance(ficha, dict) else {}
    return [(m, ficha[m]) for m in MOMENTOS
            if isinstance(ficha.get(m), dict) and ficha[m].get("puesto")]


def describir(ficha) -> str:
    """Una línea para la bitácora: qué momentos lleva el vídeo."""
    puestos = [ETIQUETA[m] for m, _ in activos(ficha)]
    if not puestos:
        return "sin presentación ni llamadas a la acción"
    return ", ".join(puestos)


# ------------------------------------------------------ el bloque del prompt

def bloque_para_guion(ficha) -> str:
    """El trozo del prompt que explica los tres momentos. -> str o ""

    Se escribe ANTES de redactar y no se cose después: una llamada a la
    acción cosida sobre un guion terminado se nota porque la escena
    anterior no la prepara. Aquí el redactor sabe desde el principio
    cuántas hay y dónde caen, y puede rematar la escena de antes para
    que la petición caiga en su sitio.
    """
    puestos = activos(ficha)
    if not puestos:
        return ""
    lineas = [
        "== LA PRESENTACIÓN Y LAS LLAMADAS A LA ACCIÓN ==",
        "Estas escenas son escenas del guion como las demás —misma voz, "
        "primera persona, mismo tono y las mismas palabras por escena—; lo "
        "único que las distingue es que en ellas se deja de narrar y se "
        "habla a quien está mirando. Se te dicen ahora, y no después, para "
        "que la escena anterior las prepare: una petición que cae de golpe "
        "se nota.",
        "",
    ]
    for momento, ranura in puestos:
        lineas.append(f"  · {ETIQUETA[momento].upper()} — {SITIO[momento]}")
        pedido = str(ranura.get("texto") or "").strip()
        if momento == "presentacion":
            if pedido:
                lineas.append(f"    Así se presenta este canal (es el PATRÓN, "
                              f"no el texto: adáptalo a lo que se enseña en "
                              f"ESTE vídeo, sin copiarlo palabra por palabra): "
                              f"«{pedido}»")
            else:
                lineas.append(f"    Qué dice: {POR_OMISION[momento]}. Del "
                              f"tipo «en este vídeo te voy a contar...».")
        else:
            lineas.append(f"    Qué pide: {pedido or POR_OMISION[momento]}")
    lineas.extend([
        "",
        "CÓMO SE ESCRIBEN: una o dos frases, en primera persona, con las "
        "palabras del vídeo y no con las de un anuncio. Se pide UNA cosa "
        "por escena (la del cierre puede pedir dos). Nada de «no "
        "olvides», «dale a la campanita» ni superlativos. Si el vídeo "
        "acaba de contar algo que da pie a la petición, se usa: esa es "
        "la única forma de que no suene pegada.",
    ])
    if len([m for m, _ in puestos if m in LLAMADAS]) > 1:
        lineas.append(
            "NO SE REPITEN ENTRE SÍ. Las dos llamadas de este vídeo no piden "
            "lo mismo con las mismas palabras; si las dos acaban siendo "
            "«suscríbete», cambia una por otra cosa (comentar, ver otro "
            "vídeo).")
    return "\n".join(lineas)
