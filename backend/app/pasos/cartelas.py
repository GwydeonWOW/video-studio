"""La cartela: un plano de TEXTO que se escribe palabra a palabra.

Puerto del `cartelas.py` del original. QUE PROBLEMA RESUELVE: un rótulo
va ENCIMA de una imagen y tiene que buscarle un hueco; una cartela ES
el plano — la imagen se oscurece con un velo y el texto se escribe
sobre ella al ritmo de la voz. Sale bien siempre porque no hay nada
debajo con lo que pelearse.

EL DINERO MANDA (misma regla que siempre): una cartela se decide ANTES
de generar, leyendo el guion — decidirla después sería pagar una imagen
para tirarla. Por eso vive con assets y no con los rótulos, aunque sea
grafismo. Las cartelas de hoy van SIEMPRE sobre la imagen del plano
(`TODAS_SOBRE_IMAGEN`): el plano paga su imagen como cualquier otro y el
montaje no se para.

DOS DIBUJANTES, UNA SOLA COMPOSICIÓN. El original renderizaba SVG con
Edge; aquí el render corre en el servidor, SIN navegador. Así que
`_cuerpo` no devuelve SVG sino una LISTA DE PRIMITIVAS —posiciones,
tamaños, colores y tiempos, ya medidos con la fuente de verdad— y hay
dos pintores que consumen lo mismo: `svg_carta` (SMIL, para la pantalla
y las muestras del catálogo) y `fotograma`/`secuencia` (PIL, un
fotograma por instante, para el ffmpeg del render). Una maqueta aparte
se desincroniza en cuanto alguien toca una plantilla; con una sola
composición no puede.

LA CARTELA OCUPA EL TRAMO EN EL QUE SE DICEN SUS PALABRAS — ese es el
enunciado, y de él salen las dos cuentas:

    encaje_de()    en qué tramo del vídeo se dicen sus palabras,
                   buscando en una VENTANA de planos
    escritura_de() ese encaje metido en el plano que la lleva: cuándo
                   entra cada palabra, y si le falta tiempo por
                   delante ('falta') o empieza antes ('antes')

`tramo_de` lo aplica al planificar: el tramo se FUNDE en un solo plano
más largo, así que no hay ningún corte dentro de la cartela y no se
paga ninguna imagen de más.

Y LO QUE HACE QUE ESTO FUNCIONE ES QUE LA CARTELA DESTILA: no repite
la narración — abrevia la cifra y se queda con el núcleo de la frase.
Sincronizar un texto destilado es trabajo del motor, y lo que sabe
emparejar (la cifra en otra notación, una palabra escrita que son
varias dichas, la comparación simétrica) vive aquí mismo, compartido
con los subtítulos (`subtitulos.cifras_en`).
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from ..nucleo import tipografia
from . import comun, p2_brief, subtitulos
from ..motores import llm
from ..nucleo.proyecto import Proyecto

#: El lienzo es el mismo que el de los planos generados: la cartela pasa
#: por toda la tubería sin que ningún paso sepa de qué clase es.
TAMANO = (1536, 1024)

#: Lo que de verdad queda en cuadro: el vídeo recorta 16:9 sobre un
#: lienzo 3:2, así que arriba y abajo se pierden 80 px. Escribir fuera
#: de esta banda es escribir donde nadie va a leer.
BANDA = (0, 80, 1536, 944)

#: Y dónde puede haber texto, con margen para respirar (1316 x 706).
SEGURO = (110, 160, 1426, 866)

#: Cuánto tarda en escribirse cada palabra: se ajusta a la duración del
#: plano entre estos dos límites. Por debajo de 0,09 no se lee que se
#: está escribiendo; por encima de 0,32 se hace lento.
S_POR_PALABRA = (0.09, 0.32)

#: La fracción del plano en la que tiene que estar escrito TODO. El
#: resto es cola: el texto completo tiene que quedarse en pantalla lo
#: suficiente para leerlo entero.
FRACCION_ESCRITURA = 0.62

#: Retardo de entrada: el corte tiene que verse antes de que empiece a
#: pasar nada, o la primera palabra se come el cambio de plano.
ENTRADA = 0.22

#: Cuánto de la región segura usa como mucho un TITULAR: uno que llega
#: justo a los dos bordes se lee apretado aunque quepa.
AIRE_TITULAR = 0.88

#: Cuánto se aparta cada columna de `contraste` del borde y de la raya
#: del medio. Con la mitad justa, la cifra de la izquierda tocaba los dos.
MARGEN_COLUMNA = 150

#: Renglones como mucho de una frase grande. En tres deja de leerse de
#: un vistazo, que es justo lo que hace una cartela.
LINEAS_TITULAR = 2

#: Cuánto se oscurece la imagen debajo de una cartela. Por debajo de
#: 0,6 el texto compite con el dibujo y no se lee de un vistazo.
VELO = 0.72

#: Cuánto tarda en oscurecerse: se ve el plano limpio un momento, se
#: apaga, y entonces empieza a escribirse el texto. Ese orden es lo que
#: lo hace parecer una transición y no un rótulo pegado encima.
VELO_ENTRADA = (0.18, 0.45)

#: Cuánto se ve la imagen LIMPIA antes de que entre el velo, como
#: fracción de lo que tarda la primera palabra: el velo ATERRIZA justo
#: cuando esa palabra entra, ni antes ni después.
FRACCION_LIMPIA = 0.3
VELO_MINIMO_S = 0.12

#: Cuántos planos como poco entre dos cartelas. Sin esto, un guion con
#: cuatro cifras seguidas encadena cuatro pantallas de texto.
SEPARACION_MINIMA = 4

#: Y cuántas como mucho, en fracción de planos: un vídeo no puede ser
#: mitad texto.
FRACCION_MAXIMA = 0.22

#: Cuánto tiene que quedarse en pantalla DESPUÉS de escribirse, por
#: palabra, para poder leerla entera.
COLA_POR_PALABRA = 0.28
COLA_MINIMA = 1.1

#: Lo que una cartela puede estar en pantalla, como mucho: el doble de
#: lo que dura el plano más largo de este vídeo. No se regenera nada
#: para cumplirlo — se avisa con el número delante.
FACTOR_TECHO = 2.0
MAX_S_POR_DEFECTO = 6.0

#: Cuántos planos ocupa una cartela como mucho, y a cuántos tiende.
PLANOS_MAXIMOS = 4
PLANOS_QUE_TIENDE = 2

PLANTILLA_POR_DEFECTO = "tesis"

#: Los campos de una cartela que NO se escriben: el icono es un glifo.
#: Contarlo daba una palabra de más en todas las cuentas de presupuesto.
CAMPOS_SIN_TEXTO = frozenset({"icono"})

#: Por debajo de esto no se abrevia nunca, y por encima SOLO si la
#: cifra entera no cabe (ver `_cifra_encajada`).
DESDE_ABREVIAR = 10000

#: Cuánto puede encoger una cifra antes de que compense abreviarla.
ENCOGIDO_ACEPTABLE = 0.7

#: Cuánto se ve el glifo gigante del fondo: por debajo no se distingue
#: del grano; por encima compite con el texto.
OPACIDAD_FANTASMA = 0.13

FONDOS = ("negro", "imagen")
FONDO_POR_DEFECTO = "negro"

#: TODAS LAS CARTELAS VAN SOBRE LA IMAGEN DEL PLANO (decisión del canal
#: en el original, 21-08): el sitio se sigue viendo detrás mientras el
#: texto remata, y el montaje no se para. LO QUE CUESTA: el plano de una
#: cartela paga su imagen como cualquier otro. El fondo negro NO se
#: borra —se dibuja igual y `sin_imagen` lo sigue distinguiendo— porque
#: volver a encenderlo tiene que ser quitar esta línea y no reescribir
#: un dibujado.
TODAS_SOBRE_IMAGEN = True


# ===========================================================================
# LAS PLANTILLAS
#
# Cada una declara sus HUECOS y nada más. El tope de caracteres no es
# una manía: es lo que separa «el agente escribió de más» de «la
# cartela salió rota». Se recorta al validar, antes de dibujar, y se
# avisa.
#
#   campos    nombre -> (obligatorio, tope de caracteres)
#   lista     si un campo es lista, cuántos elementos admite
#   cuando    lo que lee el agente para decidir si es la suya
# ===========================================================================

PLANTILLAS = {
    "cifra": {
        "nombre": "La cifra",
        "descripcion": "El número a pantalla completa, con lo que es debajo.",
        "cuando": "la narración dice una cifra que impacta y que quieres "
                  "que se lea, no que se oiga y pase",
        "campos": {"cifra": (True, 14), "label": (True, 44),
                   "nota": (False, 70), "icono": (False, 20)},
        "ejemplo": {"cifra": "10.000.000", "label": "cuentas de clientes "
                    "a la venta", "nota": "Manzanillo, octubre de 2007",
                    "icono": "base_datos"},
    },
    "cita": {
        "nombre": "La cita",
        "descripcion": "Lo que alguien dijo, entrecomillado y escribiéndose, "
                       "con quién lo dijo debajo.",
        "cuando": "la narración trae una frase entrecomillada o atribuida "
                  "a alguien",
        "campos": {"texto": (True, 170), "quien": (False, 46)},
        "ejemplo": {"texto": "Nadie sabía nada de aquel cargamento",
                    "quien": "el informe de la aduana"},
    },
    "tesis": {
        "nombre": "La frase que cae",
        "descripcion": "Una sola frase a tamaño grande, palabra a palabra. "
                       "El golpe de un tramo.",
        "cuando": "el tramo cierra una idea y quieres que se quede; es la "
                  "cartela más fuerte y la que menos hay que gastar",
        "campos": {"texto": (True, 95), "icono": (False, 20)},
        "ejemplo": {"texto": "Una contraseña sola era toda la cerradura",
                    "icono": "candado_abierto"},
    },
    "enumeracion": {
        "nombre": "La lista",
        "descripcion": "De dos a cuatro líneas que entran una detrás de "
                       "otra, numeradas.",
        "cuando": "la narración enumera cosas: tres países, cuatro pasos, "
                  "dos motivos",
        "campos": {"titulo": (False, 46), "lineas": (True, 54)},
        "lista": ("lineas", 2, 4),
        "ejemplo": {"titulo": "El botín",
                    "lineas": ["6M de cuentas con saldo",
                               "28M de números de tarjeta",
                               "La nómina de toda la plantilla"]},
    },
    "contraste": {
        "nombre": "Lo uno contra lo otro",
        "descripcion": "Dos bloques enfrentados con su cifra y su etiqueta, "
                       "y una raya en medio.",
        "cuando": "la narración compara dos magnitudes o dos estados: "
                  "antes y después, uno y otro",
        "campos": {"izq_valor": (True, 12), "izq_label": (True, 34),
                   "der_valor": (True, 12), "der_label": (True, 34)},
        "ejemplo": {"izq_valor": "Días", "izq_label": "reponer las tarjetas",
                    "der_valor": "Años",
                    "der_label": "los datos siguen circulando"},
    },
    "pregunta": {
        "nombre": "La pregunta",
        "descripcion": "Una pregunta grande, centrada, con su signo "
                       "dibujándose detrás.",
        "cuando": "el tramo abre una incógnita que el vídeo va a responder "
                  "después",
        "campos": {"texto": (True, 88), "icono": (False, 20)},
        "ejemplo": {"texto": "¿Cómo se pierde un barco de 300 metros?"},
    },
    "definicion": {
        "nombre": "La palabra",
        "descripcion": "Un término grande y debajo qué significa, como una "
                       "entrada de diccionario.",
        "cuando": "la narración usa una palabra técnica o un nombre propio "
                  "que hay que explicar una vez",
        "campos": {"termino": (True, 26), "texto": (True, 130),
                   "icono": (False, 20)},
        "ejemplo": {"termino": "Infostealer",
                    "texto": "Programa que roba en silencio las contraseñas "
                             "guardadas en el navegador",
                    "icono": "ojo"},
    },
    "capitulo": {
        "nombre": "La portada de capítulo",
        "descripcion": "El número de capítulo gigante al fondo y su título "
                       "delante.",
        "cuando": "empieza un bloque nuevo del guion; en el PRIMER plano "
                  "del capítulo y en ninguno más",
        "campos": {"numero": (True, 4), "texto": (True, 52),
                   "antetitulo": (False, 30)},
        "ejemplo": {"numero": "02", "texto": "El puerto",
                    "antetitulo": "Capítulo"},
    },
    "cronologia": {
        "nombre": "Las fechas",
        "descripcion": "De dos a cuatro hitos con su año, entrando en orden "
                       "sobre una línea que se dibuja.",
        "cuando": "la narración recorre fechas: pasó esto, después esto otro",
        "campos": {"titulo": (False, 46), "hitos": (True, 52)},
        "lista": ("hitos", 2, 4),
        "ejemplo": {"titulo": "Once meses",
                    "hitos": ["2006 · zarpa de Cartagena",
                              "2007 · lo abordan en Manzanillo",
                              "2008 · el caso se cierra"]},
    },
    "remate": {
        "nombre": "El remate",
        "descripcion": "Una frase corta abajo a la izquierda con una regla "
                       "gruesa encima. Cierra, no abre.",
        "cuando": "el tramo remata algo que ya se ha contado; es el punto "
                  "y aparte",
        "campos": {"texto": (True, 66), "icono": (False, 20)},
        "ejemplo": {"texto": "Nadie ha ido a la cárcel",
                    "icono": "escudo_roto"},
    },
}

#: Plantillas que NO puede elegir el agente. Hoy ninguna; el mecanismo
#: se queda porque el día que haya una que ponga el motor, el sitio
#: donde declararlo ya existe.
PLANTILLAS_RESERVADAS = ()


def plantillas_elegibles():
    """Las que se le ofrecen al agente y a la pantalla, en orden."""
    return [n for n in PLANTILLAS if n not in PLANTILLAS_RESERVADAS]


def plantilla_de(nombre):
    """La ficha de esa plantilla, con la de respaldo si no existe."""
    return PLANTILLAS.get(str(nombre)) or PLANTILLAS[PLANTILLA_POR_DEFECTO]


# --------------------------------------------------------------- el fondo

def es_cartela(escena):
    """Si este plano es una cartela (dict con plantilla) y no una imagen."""
    cartela = (escena or {}).get("cartela")
    return bool(isinstance(cartela, dict) and cartela.get("plantilla"))


def fondo_de(ficha):
    """'negro' o 'imagen'. Hoy SIEMPRE imagen (ver TODAS_SOBRE_IMAGEN)."""
    ficha = ficha if isinstance(ficha, dict) else {}
    if TODAS_SOBRE_IMAGEN:
        return "imagen"
    fondo = str(ficha.get("fondo") or FONDO_POR_DEFECTO)
    return fondo if fondo in FONDOS else FONDO_POR_DEFECTO


def sobre_imagen(escena):
    """Si esta cartela va ENCIMA de la imagen del plano."""
    return (es_cartela(escena)
            and fondo_de((escena or {}).get("cartela")) == "imagen")


def sin_imagen(escena):
    """Si este plano NO genera imagen: cartela de fondo negro."""
    return es_cartela(escena) and not sobre_imagen(escena)


# ------------------------------------------------------------------- color

def _rgb(hexa):
    crudo = str(hexa or "").strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    if len(crudo) != 6:
        return None
    try:
        return tuple(int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v))))
                                   for v in rgb)


def _mezclar(uno, otro, cuanto):
    """`uno` mezclado con `otro` en la proporción `cuanto` (0=uno, 1=otro)."""
    a, b = _rgb(uno) or (20, 20, 20), _rgb(otro) or (0, 0, 0)
    return _hex([a[i] + (b[i] - a[i]) * cuanto for i in range(3)])


def colores_de(paleta, plantilla=None):
    """Los colores de la cartela, derivados de la paleta del grafismo.

    No se pide una paleta propia a propósito: la cartela pertenece al
    MISMO vídeo que los rótulos, y añadir cinco selectores más sería
    pedir que se decida dos veces lo mismo. El fondo no es negro plano:
    es la sombra del vídeo empujada al negro — una historia cálida
    tiene un negro cálido y una fría uno frío.
    """
    p = dict(paleta or {})
    sombra = p.get("sombra") or p.get("fondo") or "#12130f"
    texto = p.get("texto") or "#ece7dc"
    return {
        "fondo": _mezclar(sombra, "#000000", 0.72),
        "fondo_alto": _mezclar(sombra, "#000000", 0.52),
        "texto": texto,
        "tenue": p.get("tenue") or _mezclar(texto, sombra, 0.25),
        "linea": p.get("linea") or p.get("acento") or "#d8a657",
        "acento": p.get("acento") or p.get("linea") or "#d8785a",
    }


# --------------------------------------------------------- la letra

#: La letra de la cartela cuando nadie dice otra cosa. `familia` son
#: las claves de `nucleo.tipografia` (verdana/arial/mono): el que mide
#: y el que dibuja tienen que ser el MISMO fichero.
LETRA = {"fuente": "Verdana, sans-serif", "familia": "verdana",
         "versales": True}


def _fuente_de(diseno):
    """La familia para el SVG (cadena CSS, como la pide el navegador)."""
    return (diseno or LETRA).get("fuente") or LETRA["fuente"]


def _fam_de(diseno):
    """La familia para medir/pintar: clave de `nucleo.tipografia`."""
    fam = str((diseno or LETRA).get("familia") or "").lower()
    if fam.startswith("mono"):
        return "mono"
    if fam.startswith("arial"):
        return "arial"
    return "verdana"


def _mayus(texto, diseno):
    """Versales salvo que se diga que no. Nunca en citas: ver `_cuerpo`."""
    return str(texto).upper() if (diseno or LETRA).get("versales",
                                                       True) else str(texto)


#: Los separadores de millar que puede traer el texto, en cualquier idioma.
_MILLARES = str.maketrans("", "", ".,  \u00a0\u202f\u2009")


def acortar_numero(texto):
    """'30.000.000' -> '30M'. Tal cual si no es una cifra sola.

    Solo toca cadenas que son UN número y nada más: «$2M», «4%» y
    «10 TONELADAS» se quedan como están, porque ahí el texto ya dice
    algo que una abreviatura se llevaría por delante.
    """
    crudo = str(texto or "").strip()
    digitos = crudo.translate(_MILLARES)
    if not digitos.isdigit() or len(digitos) < 2:
        return crudo
    valor = int(digitos)
    if valor < DESDE_ABREVIAR:
        return crudo
    for corte, letra in ((1_000_000_000, "B"), (1_000_000, "M"),
                         (1_000, "K")):
        if valor >= corte:
            escala = valor / float(corte)
            return (f"{escala:.1f}".rstrip("0").rstrip(".") + letra
                    if escala < 100 else f"{int(round(escala))}{letra}")
    return crudo


def _cifra_encajada(texto, fam, tam, ancho_max, alto_max, minimo):
    """La cifra dibujable: entera si cabe, abreviada solo si no.

    Se prueba primero tal cual la escribieron. Solo cuando encogerla
    tanto la dejaría ilegible se recurre a la abreviatura, y solo si de
    verdad acorta: abreviar por sistema sería reescribirle el texto a
    alguien que ha puesto justo el que quería.
    """
    lineas, usado = tipografia.encajar(texto, fam, tam, True, 0, ancho_max,
                                       alto_max, minimo=minimo,
                                       lineas_max=1)
    if usado >= tam * ENCOGIDO_ACEPTABLE:
        return lineas, usado
    corto = acortar_numero(texto)
    if corto == texto or len(corto) >= len(texto):
        return lineas, usado
    cortas, usado_corto = tipografia.encajar(corto, fam, tam, True, 0,
                                             ancho_max, alto_max,
                                             minimo=minimo, lineas_max=1)
    return (cortas, usado_corto) if usado_corto > usado else (lineas, usado)


# ===========================================================================
# ICONOS
#
# Trazos simples de 24x24, escritos aquí y no traidos de ninguna
# librería: son formas geométricas y una dependencia por diecinueve
# paths sería pagar mucho por poco. Van con `stroke` y sin relleno,
# así que heredan el color de la cartela.
#
# El catálogo es CERRADO, como las plantillas: uno inventado se ignora
# y la cartela sale sin él, que es peor que con él pero mucho mejor
# que rota.
# ===========================================================================

ICONOS = {
    "candado": "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z",
    "candado_abierto": "M7 11V8a5 5 0 0 1 9.6-2M5 11h14v10H5z",
    "llave": "M14 10a4 4 0 1 1 4 4h-1l-2 2-2-2-2 2-2-2v-2l5-5zM18 8h.01",
    "escudo": "M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z",
    "escudo_roto": "M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z"
                  "M12 2v20M9 8l6 4-6 4",
    "ojo": "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"
           "M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z",
    "alerta": "M12 3l10 17H2zM12 9v5M12 17h.01",
    "reloj": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM12 7v5l3 2",
    "tarjeta": "M2 6h20v12H2zM2 10h20M6 15h4",
    "base_datos": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"
                  "M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"
                  "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    "servidor": "M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01",
    "globo": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM3 12h18"
             "M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18",
    "persona": "M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"
               "M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7",
    "personas": "M9 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z"
                "M2 20c0-3.9 3.1-6 7-6s7 2.1 7 6"
                "M17 5.2a3.5 3.5 0 0 1 0 6.6M18 14.3c2.4.7 4 2.6 4 5.7",
    "documento": "M6 2h8l4 4v16H6zM14 2v4h4",
    "lupa": "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM16.5 16.5L21 21",
    "rayo": "M13 2L4 14h7l-1 8 9-12h-7z",
    "subida": "M3 17l6-6 4 4 8-8M15 7h6v6",
    "bajada": "M3 7l6 6 4-4 8 8M15 17h6v-6",
}


# ===========================================================================
# EMPAREJAR EL TEXTO DE LA CARTELA CON LA VOZ
#
# La cartela DESTILA la narración: escribe «30M» donde la voz dice
# «treinta millones». Lo que sabe emparejar vive aquí y se apoya en las
# tablas de números de `subtitulos` — con dos copias, la que se quede
# vieja fallaría en silencio.
# ===========================================================================

#: Una palabra escrita casa con una dicha si la más corta de las dos
#: mide al menos esto y va dentro de la otra. Sin mínimo, «de» casaría
#: con medio guion.
MINIMO_SUBCADENA = 4

_SIN_TILDES = str.maketrans("áéíóúüñàèìòùäëïöüç",
                            "aeiouunaeiouaeiouc")


def _normalizar(texto):
    """Minúsculas, sin tildes y sin signos: la forma de RECONOCER una
    palabra. Una por palabra cruda —la posición n de la lista tiene que
    ser la marca de tiempo n."""
    plano = str(texto or "").lower().translate(_SIN_TILDES)
    return re.sub(r"[^a-z0-9]+", " ", plano).strip()


def _palabras_llanas(texto):
    """Las palabras de un texto, normalizadas UNA POR PALABRA CRUDA."""
    return [_normalizar(p) for p in str(texto or "").split()]


def _valor_numerico(token):
    """El número que representa un token ESCRITO, o None. '30M' ->
    30000000.0, '4%' -> 4.0, '1.500' -> 1500.0. Se le pasa el token
    CRUDO: normalizar se come justo los signos que dicen que esto es
    una cifra (el %, el punto de los miles)."""
    crudo = str(token or "").strip()
    if not crudo:
        return None
    limpio = re.sub(r"^[\s$€£¥#~<>+-]+", "", crudo.translate(_SIN_TILDES))
    limpio = re.sub(r"[\s$€£¥#~<>+]+$", "", limpio)
    encaje = re.match(r"^(\d[\d.,]*)\s*([a-zA-Z]{0,2})%?$", limpio)
    if not encaje:
        return None
    cifra, sufijo = encaje.group(1), encaje.group(2).lower()
    # El punto y la coma son a la vez separador de miles y coma decimal,
    # y cuál es cuál lo desempata el grupo de tres cifras: «1.500» son
    # mil quinientos y «2,5» son dos y medio, se escriban como se escriban.
    trozos = re.split(r"[.,]", cifra.rstrip(".,"))
    if len(trozos) == 1:
        valor = float(trozos[0])
    elif all(len(t) == 3 for t in trozos[1:]):
        valor = float("".join(trozos))
    else:
        valor = float(trozos[0] + "." + "".join(trozos[1:]))
    escala = {"": 1, "k": 10 ** 3, "m": 10 ** 6, "mm": 10 ** 6,
              "b": 10 ** 9, "bn": 10 ** 9, "t": 10 ** 12}.get(sufijo)
    if escala is None:
        return None
    return valor * escala


def _numeros_en(dichas, idioma=None):
    """Los números que se PRONUNCIAN, como tramos con su VALOR.

    [(índice, cuántas_marcas, valor)] sin solaparse y en orden — el
    tramo es lo que convierte «treinta millones» en UNA cosa: ancla en
    «treinta» y consume también «millones», para que la palabra
    siguiente de la cartela no ancle en mitad de la cifra. La cuenta
    de números dichos vive en `subtitulos.cifras_en`, que es donde
    están las tablas.
    """
    salida = []
    for a, cuantas, cifrado in subtitulos.cifras_en(dichas, idioma):
        try:
            valor = int(str(cifrado).replace(".", "").replace(",", ""))
        except ValueError:
            continue
        if salida and salida[-1][0] + salida[-1][1] > a:
            continue
        salida.append((a, cuantas, valor))
    return salida


def casan(escrita, dicha):
    """Si esta palabra escrita y esta dicha son la misma. SIMÉTRICO.

    Casa el plural con el singular en los dos sentidos, que es lo que
    una cartela hace todo el rato: escribe «cuentas» donde se dice
    «cuenta» y al revés. El mínimo lo mide la MÁS CORTA.
    """
    escrita, dicha = str(escrita or ""), str(dicha or "")
    if not escrita or not dicha:
        return False
    if escrita == dicha:
        return True
    corta, larga = ((escrita, dicha) if len(escrita) <= len(dicha)
                    else (dicha, escrita))
    return len(corta) >= MINIMO_SUBCADENA and corta in larga


def piezas_de(termino):
    """Las palabras de un término escrito, cada una con su valor.

    [(palabra_llana, valor_o_None)]. El valor sale del token CRUDO:
    sobre el normalizado ya no queda ni % ni punto de miles con que
    reconocer una cifra. Y una cifra es UNA pieza aunque se parta al
    normalizar: «4.000» es una palabra escrita y vale cuatro mil.
    """
    piezas = []
    for crudo in str(termino or "").split():
        llanas = _normalizar(crudo).split()
        valor = _valor_numerico(crudo)
        if valor is not None:
            piezas.append((" ".join(llanas), valor))
        elif len(llanas) == 1:
            piezas.append((llanas[0], None))
        else:
            piezas.extend((llana, _valor_numerico(llana))
                          for llana in llanas)
    return piezas


def _tramo_numerico(numeros, desde):
    """El tramo de número hablado que EMPIEZA justo en `desde`, si lo hay."""
    for inicio, cuantas, valor in numeros:
        if inicio == desde:
            return cuantas, valor
        if inicio > desde:
            break
    return None


def casar_desde(piezas, dichas, desde, numeros=()):
    """Cuántas palabras DICHAS ocupa el término si empieza en `desde`.

    0 si no empieza ahí. Devuelve palabras dichas y no piezas escritas
    porque las dos cuentas dejaron de ser la misma en cuanto «30M»
    pasó a ocupar dos.
    """
    j = desde
    for llana, valor in piezas:
        if j >= len(dichas):
            return 0
        tramo = _tramo_numerico(numeros, j)
        if valor is not None and tramo and abs(tramo[1] - valor) < 1e-6:
            j += tramo[0]                  # la cifra ENTERA, no su 1ª palabra
            continue
        if not casan(llana, dichas[j]):
            return 0
        j += 1
    return j - desde


# ===========================================================================
# EL RELOJ: cuándo entra cada palabra
# ===========================================================================

def _paso_de(duracion, palabras):
    """Cuánto tarda cada palabra, para que quepan todas con cola."""
    if palabras <= 0:
        return S_POR_PALABRA[0]
    hueco = max(0.4, float(duracion) * FRACCION_ESCRITURA - ENTRADA)
    return max(S_POR_PALABRA[0], min(S_POR_PALABRA[1], hueco / palabras))


class _Reloj:
    """Cuándo entra cada palabra, en el orden en que se escriben.

    SINTETICO (`tiempos` vacío) es el de siempre: arranca en ENTRADA y
    avanza un paso fijo por palabra, calculado para que quepan todas
    con cola.

    DICHO (`tiempos` con una entrada por palabra) es el de verdad:
    cada palabra entra CUANDO SE DICE, con las marcas de la voz. Es lo
    que hace que una cartela acompañe a la narración en vez de ir por
    libre.
    """

    def __init__(self, t0, paso, tiempos=None):
        self.t0 = float(t0)
        self.paso = float(paso)
        self.tiempos = list(tiempos or [])
        self.i = 0

    @property
    def dicho(self):
        return bool(self.tiempos)

    def _momento(self, indice):
        """Cuándo entra la palabra número `indice` (0..), consumida o no."""
        if indice < len(self.tiempos):
            return float(self.tiempos[indice])
        if not self.tiempos:
            return self.t0 + indice * self.paso
        # más palabras dibujadas que alineadas (una cifra que se parte):
        # se sigue con el ritmo sintético desde la última
        return (float(self.tiempos[-1])
                + (indice - len(self.tiempos) + 1) * self.paso)

    def mirar(self):
        """Cuándo entra la SIGUIENTE palabra, sin consumirla.

        Lo pide quien dibuja algo que acompaña a un renglón y no es
        texto — el número de una lista, el punto de una cronología —:
        ese adorno tiene que aparecer CON su renglón, y su renglón
        todavía no se ha escrito.
        """
        return self._momento(self.i)

    def siguiente(self):
        valor = self._momento(self.i)
        self.i += 1
        return valor

    def fin(self):
        """Cuándo terminó de escribirse LO QUE VA CONSUMIDO. No el total.

        Las plantillas encadenan aquí lo que va detrás (la regla de
        acento, el pie de la cifra, el cursor); devolver el final de la
        cartela ENTERA hacía que todos esos adornos aparecieran de
        golpe en el último fotograma.
        """
        if self.i <= 0:
            return self.t0
        return self._momento(self.i - 1) + self.paso


def _cuando_entra(paso, t):
    """Cuándo entra la SIGUIENTE palabra que se va a escribir."""
    return paso.mirar() if isinstance(paso, _Reloj) else t


def _desempatar(*partes):
    """Entero estable a partir de varias claves: desempata sin random."""
    resumen = hashlib.sha256("|".join(str(p) for p in partes)
                             .encode("utf-8")).hexdigest()
    return int(resumen[:8], 16)


# ===========================================================================
# LAS PRIMITIVAS
#
# `_cuerpo` no dibuja: EMITE. Cada pieza es un dict con el qué (texto,
# regla, icono...) y el cuándo (t de entrada, momentos de cada
# palabra), ya medido con la fuente de verdad. Los dos pintores (SVG
# para la pantalla, PIL para el ffmpeg) consumen exactamente esto, y
# por eso no pueden discrepar.
# ===========================================================================

def _p_texto(x, y, texto, tam, color, negrita=True, espaciado=0,
             anclaje="start", opacidad=1.0, t=None, entra_dur=0.22):
    return {"tipo": "texto", "x": x, "y": y, "texto": str(texto),
            "tam": tam, "color": color, "negrita": negrita,
            "espaciado": espaciado, "anclaje": anclaje,
            "opacidad": opacidad, "t": t, "entra_dur": entra_dur}


def _p_escrito(x, y, lineas, tam, color, reloj, t0, negrita=True,
               espaciado=0, anclaje="start", animado=True,
               interlineado=1.25, registro=None):
    """El bloque que se ESCRIBE: cada palabra en su momento.

    Devuelve (primitiva, cuándo_acaba). La primitiva lleva `momentos`
    —[(segundo, palabra)]— de donde salen también las teclas de la
    máquina de escribir (`sonido`): un teclado que suena cuando no se
    escribe es peor que no ponerlo, y con dos cuentas se desincronizan
    en cuanto alguien toca el ritmo.
    """
    momentos = []
    t = t0
    for linea in lineas:
        for palabra in linea.split():
            momento = reloj.siguiente()
            momentos.append((round(momento, 3), palabra))
            t = momento + (0.0 if reloj.dicho else reloj.paso)
    if registro is not None:
        registro.extend(momentos)
    return ({"tipo": "escrito", "x": x, "y": y, "lineas": list(lineas),
             "tam": tam, "color": color, "negrita": negrita,
             "espaciado": espaciado, "anclaje": anclaje,
             "interlineado": interlineado, "animado": animado,
             "momentos": momentos},
            reloj.fin() if reloj.dicho else t)


def _p_regla(x, y, ancho, alto, color, t0, dur=0.5, opacidad=1.0):
    """Una regla de acento que se PINTA. Crece por su lado largo.

    Cuál es el lado largo importa: una raya vertical que creciera de
    ancho se ve aparecer de golpe, y la que separa los dos bloques de
    `contraste` tiene que BAJAR, que es lo que dice que hay dos lados.
    """
    return {"tipo": "regla", "x": x, "y": y, "ancho": ancho, "alto": alto,
            "color": color, "t": t0, "dur": dur, "opacidad": opacidad}


def _p_cursor(x, y, alto, color, t0, t1):
    """El bloque que parpadea al final de lo escrito. Se va cuando el
    texto termina: un cursor que sigue parpadeando en una pantalla ya
    escrita dice que va a seguir escribiendo, y no va a seguir."""
    return {"tipo": "cursor", "x": x, "y": y, "alto": alto,
            "color": color, "t0": t0, "t1": t1}


def _p_icono(nombre, x, y, tam, color, t0, opacidad=0.9):
    return {"tipo": "icono", "nombre": nombre, "x": x, "y": y,
            "tam": tam, "color": color, "t": t0, "opacidad": opacidad,
            "entra_dur": 0.3}


def _p_fantasma(texto, tam, color, semilla=0, x=None, centro=None):
    """Un glifo gigante al fondo, tenue y con deriva lenta.

    Es lo que impide que la cartela sea una diapositiva: cuando el
    texto ya está escrito, esto sigue moviéndose. La deriva es de
    10 px en 14 s — no se ve moverse, se ve VIVO, que no es lo mismo.
    """
    if not str(texto).strip():
        return None
    bx, by, bx2, by2 = BANDA
    return {"tipo": "fantasma", "texto": str(texto),
            "x": (bx + bx2) // 2 if x is None else x,
            "centro": (by + by2) // 2 if centro is None else centro,
            "tam": tam, "color": color,
            "fase": _desempatar(semilla, "fantasma") % 5}


def _p_circulo(cx, cy, r, color, t0):
    return {"tipo": "circulo", "cx": cx, "cy": cy, "r": r,
            "color": color, "t": t0, "entra_dur": 0.22}


# ===========================================================================
# LA COMPOSICIÓN
#
# Cada rama mide con la fuente de verdad y BAJA el tamaño hasta que
# entra (`tipografia.encajar`, que comprueba ancho Y alto). Por eso el
# tamaño que pide la plantilla es el MÁXIMO, no el que se usa: una
# cartela no puede salir rota — como mucho sale con la letra más
# pequeña de lo que pedía su plantilla.
#
# Dos reglas que salieron de mirar las primeras cartelas renderizadas:
#
#   AIRE      ningún bloque usa la región segura entera: un titular que
#             llega justo a los dos bordes se lee apretado aunque quepa.
#   RENGLONES un pie en cuatro líneas cabe de alto y se lee fatal: los
#             pies van por `encajar_pocas_lineas`, que prueba a meterlo
#             en UNA y solo admite la segunda si de verdad no cabe.
#
# Todo se compone alrededor del centro de la BANDA visible y no del
# lienzo: componer sobre el lienzo 3:2 deja los bloques altos, porque
# los 80 px de arriba y los de abajo no salen en el vídeo.
# ===========================================================================

def _cuerpo(plantilla, datos, colores, diseno, duracion, animado=True,
            semilla=0, registro=None, tiempos=None):
    """Las piezas de la plantilla, ya encajadas en la región segura."""
    x0, y0, x1, y1 = SEGURO
    ancho, alto = x1 - x0, y1 - y0
    cx = (x0 + x1) // 2
    cy = (BANDA[1] + BANDA[3]) // 2
    # LA FAMILIA CON LA QUE SE MIDE TIENE QUE SER LA QUE SE DIBUJA.
    fam = _fam_de(diseno)
    t = ENTRADA
    paso = _Reloj(ENTRADA, _paso_de(duracion, _cuentapalabras(datos)),
                  tiempos)
    icono = datos.get("icono")
    piezas = []

    if plantilla == "cifra":
        # Sin glifo de fondo: la cifra YA es el elemento gigante de esta
        # cartela, y ponerle otro detrás es competir consigo misma.
        cifra = _mayus(datos.get("cifra", ""), diseno)
        lineas, tam = _cifra_encajada(cifra, fam, 176, ancho * AIRE_TITULAR,
                                      alto * 0.5, minimo=64)
        salto = int(tam * 1.15)
        etiqueta, tam_e = tipografia.encajar_pocas_lineas(
            datos.get("label", ""), fam, 46, False, 2, ancho * 0.78, 150)
        bloque = (salto * len(lineas) + 42 + 8 + 46
                  + int(tam_e * 1.25) * len(etiqueta))
        arriba = cy - bloque // 2 + tam
        if icono:
            piezas.append(_p_icono(icono, cx, arriba - tam - 78, 74,
                                   colores["linea"], ENTRADA, 0.75))
        escrito, t = _p_escrito(cx, arriba, lineas, tam, colores["texto"],
                                paso, t, anclaje="middle", animado=animado,
                                interlineado=1.15, registro=registro)
        piezas.append(escrito)
        base = arriba + salto * (len(lineas) - 1)
        piezas.append(_p_regla(cx - 90, base + 42, 180, 8,
                               colores["linea"], t + 0.1))
        escrito, t = _p_escrito(cx, base + 118, etiqueta, tam_e,
                                colores["tenue"], paso, t + 0.25,
                                negrita=False, espaciado=2,
                                anclaje="middle", animado=animado,
                                registro=registro)
        piezas.append(escrito)
        if datos.get("nota"):
            # pegada al bloque, no clavada al pie: anclada abajo dejaba
            # un agujero de 200 px entre la etiqueta y ella
            nota, tam_n = tipografia.encajar_pocas_lineas(
                _mayus(datos["nota"], diseno), fam, 26, False, 4,
                ancho * 0.8, 80)
            pie = base + 118 + int(tam_e * 1.25) * (len(etiqueta) - 1) + 74
            for indice, linea in enumerate(nota):
                piezas.append(_p_texto(
                    cx, min(pie + indice * int(tam_n * 1.3), y1), linea,
                    tam_n, colores["tenue"], negrita=False, espaciado=4,
                    anclaje="middle", opacidad=0.6, t=t + 0.3))

    elif plantilla == "cita":
        # Una cita se deja en su caja original: en versales deja de
        # leerse como una cita y pasa a leerse como un titular.
        lineas, tam = tipografia.encajar(datos.get("texto", ""), fam, 62,
                                         False, 0, ancho - 190, alto * 0.6,
                                         minimo=32, interlineado=1.3)
        salto = int(tam * 1.3)
        pie = 60 + 56 if datos.get("quien") else 0
        arriba = cy - (salto * len(lineas) + pie) // 2 + tam
        # La comilla se planta por su LÍNEA BASE y cuelga de lo alto de
        # su cuadratín: a 240 px se salía por arriba de la banda.
        piezas.append(_p_texto(x0, arriba + tam * 0.55, "“", 170,
                               colores["linea"], opacidad=0.2))
        escrito, t = _p_escrito(x0 + 122, arriba, lineas, tam,
                                colores["texto"], paso, t, negrita=False,
                                animado=animado, interlineado=1.3,
                                registro=registro)
        piezas.append(escrito)
        base = arriba + salto * (len(lineas) - 1)
        piezas.append(_p_cursor(x0 + 122, base + 10, tam, colores["linea"],
                                t, t))
        if datos.get("quien"):
            piezas.append(_p_regla(x0 + 122, base + 60, 64, 4,
                                   colores["linea"], t + 0.15))
            piezas.append(_p_texto(x0 + 122, base + 116,
                                   _mayus(datos["quien"], diseno), 30,
                                   colores["tenue"], negrita=False,
                                   espaciado=3, t=t + 0.4))

    elif plantilla in ("tesis", "pregunta"):
        if plantilla == "pregunta" and not icono:
            piezas.append(_p_fantasma("?", 720, colores["linea"], semilla,
                                      centro=cy))
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 104, True, -1,
            ancho * AIRE_TITULAR, alto * 0.62, minimo=48,
            interlineado=1.22, lineas_max=LINEAS_TITULAR)
        salto = int(tam * 1.22)
        alto_icono = 96 if icono else 0
        arriba = cy - (salto * len(lineas) + 50 + alto_icono) // 2 + tam
        if icono:
            piezas.append(_p_icono(icono, cx, arriba - tam - 60, 78,
                                   colores["linea"], ENTRADA, 0.8))
        escrito, t = _p_escrito(cx, arriba, lineas, tam, colores["texto"],
                                paso, t, espaciado=-1, anclaje="middle",
                                animado=animado, interlineado=1.22,
                                registro=registro)
        piezas.append(escrito)
        piezas.append(_p_regla(cx - 60, arriba + salto * (len(lineas) - 1)
                               + 44, 120, 6, colores["linea"], t + 0.1))

    elif plantilla == "enumeracion":
        entradas = [str(v) for v in (datos.get("lineas") or [])
                    if str(v).strip()]
        arriba = y0 + 20
        if datos.get("titulo"):
            piezas.append(_p_texto(x0, arriba + 20,
                                   _mayus(datos["titulo"], diseno), 34,
                                   colores["tenue"], negrita=False,
                                   espaciado=5))
            piezas.append(_p_regla(x0, arriba + 46, 92, 5,
                                   colores["linea"], ENTRADA))
            arriba += 110
        hueco = (y1 - arriba) // max(1, len(entradas))
        tam = min(76, max(38, int(hueco * 0.44)))
        for indice, texto in enumerate(entradas):
            y = arriba + hueco * indice + tam
            partido, tam_l = tipografia.encajar_pocas_lineas(
                _mayus(texto, diseno), fam, tam, True, 0, ancho - 190,
                hueco - 14, lineas=(1, 2), minimo=None)
            # EL NÚMERO ENTRA CON SU RENGLÓN, no cuando acabó el
            # anterior: con la voz alineada entre dos líneas puede
            # haber un silencio de segundos.
            piezas.append(_p_texto(x0, y - 4, "%02d" % (indice + 1), 30,
                                   colores["linea"], espaciado=2,
                                   t=_cuando_entra(paso, t)))
            escrito, t = _p_escrito(x0 + 92, y, partido, tam_l,
                                    colores["texto"], paso, t + 0.12,
                                    animado=animado, registro=registro)
            piezas.append(escrito)

    elif plantilla == "contraste":
        piezas.append(_p_regla(cx - 1, cy - 190, 2, 380, colores["tenue"],
                               ENTRADA, dur=0.8, opacidad=0.45))
        # el ancho de cada lado deja aire A LOS DOS: al borde del cuadro
        # y a la raya del medio. Con la mitad justa, «30.000.000»
        # tocaba los dos.
        ancho_lado = ancho // 2 - MARGEN_COLUMNA
        for lado, signo in (("izq", -1), ("der", 1)):
            centro = cx + signo * (ancho // 4 + 24)
            lineas, tam = _cifra_encajada(
                _mayus(datos.get(f"{lado}_valor", ""), diseno), fam, 110,
                ancho_lado, 230, minimo=44)
            escrito, t = _p_escrito(centro, cy - 40, lineas, tam,
                                    colores["texto"], paso, t + 0.1,
                                    anclaje="middle", animado=animado,
                                    registro=registro)
            piezas.append(escrito)
            etiqueta, tam_e = tipografia.encajar_pocas_lineas(
                datos.get(f"{lado}_label", ""), fam, 38, False, 1,
                ancho_lado, 200)
            escrito, t = _p_escrito(centro, cy + 66, etiqueta, tam_e,
                                    colores["tenue"], paso, t + 0.1,
                                    negrita=False, espaciado=1,
                                    anclaje="middle", animado=animado,
                                    registro=registro)
            piezas.append(escrito)

    elif plantilla == "definicion":
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("termino", ""), diseno), fam, 108, True, -1,
            ancho * AIRE_TITULAR, 260, minimo=52, interlineado=1.2,
            lineas_max=2)
        cuerpo, tam_c = tipografia.encajar(datos.get("texto", ""), fam, 44,
                                           False, 0, ancho - 90, 260,
                                           minimo=26, interlineado=1.35,
                                           lineas_max=3)
        salto, salto_c = int(tam * 1.2), int(tam_c * 1.35)
        bloque = salto * len(lineas) + 42 + 7 + 130 + salto_c * len(cuerpo)
        arriba = cy - bloque // 2 + tam
        if icono:
            piezas.append(_p_icono(icono, x0 + 34, arriba - tam * 0.34, 66,
                                   colores["linea"], ENTRADA, 0.8))
            x0 += 108                   # el término se aparta del icono
        escrito, t = _p_escrito(x0, arriba, lineas, tam, colores["texto"],
                                paso, t, espaciado=-1, animado=animado,
                                interlineado=1.2, registro=registro)
        piezas.append(escrito)
        base = arriba + salto * (len(lineas) - 1)
        piezas.append(_p_regla(x0, base + 42, 220, 7, colores["linea"],
                               t + 0.1))
        escrito, t = _p_escrito(x0, base + 130, cuerpo, tam_c,
                                colores["tenue"], paso, t + 0.2,
                                negrita=False, animado=animado,
                                interlineado=1.35, registro=registro)
        piezas.append(escrito)

    elif plantilla == "capitulo":
        piezas.append(_p_fantasma(str(datos.get("numero", "")), 620,
                                  colores["linea"], semilla, centro=cy))
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 120, True, -1,
            ancho * AIRE_TITULAR, 300, minimo=56, interlineado=1.2,
            lineas_max=2)
        salto = int(tam * 1.2)
        arriba = cy - (salto * len(lineas)) // 2 + tam
        if datos.get("antetitulo"):
            piezas.append(_p_texto(cx, arriba - tam - 56,
                                   _mayus(datos["antetitulo"], diseno), 34,
                                   colores["tenue"], negrita=False,
                                   espaciado=10, anclaje="middle"))
        escrito, t = _p_escrito(cx, arriba, lineas, tam, colores["texto"],
                                paso, t + 0.2, espaciado=-1,
                                anclaje="middle", animado=animado,
                                interlineado=1.2, registro=registro)
        piezas.append(escrito)
        piezas.append(_p_regla(cx - 110, arriba + salto * (len(lineas) - 1)
                               + 50, 220, 8, colores["linea"], t + 0.1))

    elif plantilla == "cronologia":
        hitos = [str(v) for v in (datos.get("hitos") or [])
                 if str(v).strip()]
        arriba = y0 + 20
        if datos.get("titulo"):
            piezas.append(_p_texto(x0, arriba + 20,
                                   _mayus(datos["titulo"], diseno), 34,
                                   colores["tenue"], negrita=False,
                                   espaciado=5))
            arriba += 90
        hueco = (y1 - arriba) // max(1, len(hitos))
        tam = min(60, max(30, int(hueco * 0.40)))
        # el rail va antes que los puntos para que quede DEBAJO de ellos
        piezas.append(_p_regla(x0 + 12, arriba + 8, 3,
                               hueco * len(hitos) - 30, colores["tenue"],
                               ENTRADA, dur=max(0.8, duracion * 0.45),
                               opacidad=0.4))
        for indice, hito in enumerate(hitos):
            y = arriba + hueco * indice + tam
            partido, tam_h = tipografia.encajar_pocas_lineas(
                _mayus(hito, diseno), fam, tam, True, 0, ancho - 140,
                hueco - 16, lineas=(1, 2), minimo=None)
            piezas.append(_p_circulo(x0 + 13, y - tam_h * 0.34, 10,
                                     colores["linea"],
                                     _cuando_entra(paso, t)))
            escrito, t = _p_escrito(x0 + 62, y, partido, tam_h,
                                    colores["texto"], paso, t + 0.1,
                                    animado=animado, registro=registro)
            piezas.append(escrito)

    else:  # remate
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 88, True, 0,
            ancho * AIRE_TITULAR, alto * 0.42, minimo=40,
            interlineado=1.22, lineas_max=LINEAS_TITULAR)
        salto = int(tam * 1.22)
        base = y1 - salto * (len(lineas) - 1) - 30
        piezas.append(_p_regla(x0, base - tam - 62, 340, 10,
                               colores["linea"], ENTRADA))
        if icono:
            piezas.append(_p_icono(icono, x0 + 34, base - tam - 140, 68,
                                   colores["linea"], ENTRADA, 0.8))
        escrito, t = _p_escrito(x0, base, lineas, tam, colores["texto"],
                                paso, t + 0.25, animado=animado,
                                interlineado=1.22, registro=registro)
        piezas.append(escrito)

    return [p for p in piezas if p]


# ===========================================================================
# EL PINTOR DE SVG (la pantalla, las muestras del catálogo, la vista)
# ===========================================================================

def _svg_texto(p, diseno):
    peso = "700" if p["negrita"] else "400"
    cuerpo = (f'<text x="{p["x"]:.0f}" y="{p["y"]:.0f}" '
              f'font-family="{_fuente_de(diseno)}" font-size="{p["tam"]}" '
              f'font-weight="{peso}" letter-spacing="{p["espaciado"]}" '
              f'fill="{p["color"]}" text-anchor="{p["anclaje"]}" '
              f'opacity="{p["opacidad"]:g}">'
              f'{tipografia.escapar(p["texto"])}</text>')
    return _svg_entra(cuerpo, p["t"], p["entra_dur"])


def _svg_escrito(p, diseno):
    x, y, tam = p["x"], p["y"], p["tam"]
    salto = int(tam * p["interlineado"])
    peso = "700" if p["negrita"] else "400"
    piezas, indice = [], 0
    for i, linea in enumerate(p["lineas"]):
        cabeza = (f'<text x="{x:.0f}" y="{y + salto * i:.0f}" '
                  f'font-family="{_fuente_de(diseno)}" font-size="{tam}" '
                  f'font-weight="{peso}" letter-spacing="{p["espaciado"]}" '
                  f'fill="{p["color"]}" text-anchor="{p["anclaje"]}">')
        if not p["animado"]:
            piezas.append(cabeza + tipografia.escapar(linea) + "</text>")
            indice += len(linea.split())
            continue
        trozos = []
        for palabra in linea.split():
            momento = p["momentos"][indice][0] if indice < len(
                p["momentos"]) else 0.0
            indice += 1
            trozos.append(
                f'<tspan opacity="0">{tipografia.escapar(palabra)} '
                f'<animate attributeName="opacity" from="0" to="1" '
                f'begin="{momento:.2f}s" dur="0.14s" fill="freeze"/>'
                f'</tspan>')
        piezas.append(cabeza + "".join(trozos) + "</text>")
    return "".join(piezas)


def _svg_de(piezas, diseno=None):
    """Las primitivas, como SVG con su SMIL — lo que ve la pantalla."""
    salida = []
    for p in piezas:
        tipo = p["tipo"]
        if tipo == "texto":
            salida.append(_svg_texto(p, diseno))
        elif tipo == "escrito":
            salida.append(_svg_escrito(p, diseno))
        elif tipo == "regla":
            vertical = p["alto"] > p["ancho"]
            crece = "height" if vertical else "width"
            fijo = (f'width="{p["ancho"]:.0f}" height="0"' if vertical
                    else f'width="0" height="{p["alto"]:.0f}"')
            salida.append(
                f'<rect x="{p["x"]:.0f}" y="{p["y"]:.0f}" {fijo} '
                f'fill="{p["color"]}" opacity="{p["opacidad"]:g}">'
                f'<animate attributeName="{crece}" from="0" '
                f'to="{(p["alto"] if vertical else p["ancho"]):.0f}" '
                f'begin="{p["t"]:.2f}s" dur="{p["dur"]:g}s" fill="freeze" '
                f'calcMode="spline" keySplines="0.2 0.8 0.2 1" '
                f'keyTimes="0;1"/></rect>')
        elif tipo == "cursor":
            salida.append(
                f'<rect x="{p["x"]:.0f}" y="{p["y"] - p["alto"]:.0f}" '
                f'width="{max(8, p["alto"] * 0.5):.0f}" '
                f'height="{p["alto"]:.0f}" fill="{p["color"]}" opacity="0">'
                f'<animate attributeName="opacity" values="0;1;1;0" '
                f'begin="{p["t0"]:.2f}s" dur="0.7s" '
                f'repeatCount="indefinite"/>'
                f'<set attributeName="opacity" to="0" '
                f'begin="{p["t1"]:.2f}s"/></rect>')
        elif tipo == "icono":
            salida.append(_svg_icono(p, diseno))
        elif tipo == "fantasma":
            salida.append(_svg_fantasma(p, diseno))
        elif tipo == "circulo":
            cuerpo = (f'<circle cx="{p["cx"]}" cy="{p["cy"]:.0f}" '
                      f'r="{p["r"]}" fill="{p["color"]}"/>')
            salida.append(_svg_entra(cuerpo, p["t"], p["entra_dur"]))
    return "".join(salida)


def _svg_icono(p, diseno):
    trazo = ICONOS.get(str(p["nombre"] or ""))
    if not trazo:
        return ""
    tam = p["tam"]
    escala = tam / 24.0
    grosor = max(1.2, 2.0 / escala)
    dibujo = (f'<g transform="translate({p["x"] - tam / 2:.1f},'
              f'{p["y"] - tam / 2:.1f}) scale({escala:.4f})" fill="none" '
              f'stroke="{p["color"]}" stroke-width="{grosor:.2f}" '
              f'stroke-linecap="round" stroke-linejoin="round" '
              f'opacity="{p["opacidad"]:g}">'
              f'<path d="{trazo}"/></g>')
    return _svg_entra(dibujo, p["t"], p["entra_dur"])


def _svg_fantasma(p, diseno):
    dur = 14 + p["fase"]
    deriva = (f'<animateTransform attributeName="transform" '
              f'type="translate" values="0 0; 10 -6; -6 8; 0 0" '
              f'dur="{dur}s" repeatCount="indefinite"/>')
    # un <text> se planta por su LÍNEA BASE: colocar un glifo de 700 px
    # «en el centro» a ojo lo deja medio fuera de cuadro.
    return (f'<g opacity="{OPACIDAD_FANTASMA:g}">{deriva}'
            f'<text x="{p["x"]:.0f}" y="{p["centro"] + p["tam"] * 0.35:.0f}"'
            f' font-family="{_fuente_de(diseno)}" '
            f'font-size="{p["tam"]}" font-weight="700" '
            f'fill="{p["color"]}" text-anchor="middle">'
            f'{tipografia.escapar(p["texto"])}</text></g>')


def _svg_entra(interior, t, dur):
    """Envuelve algo que no es texto para que aparezca en su momento.

    Las palabras se escriben solas (cada tspan trae su animación); un
    punto de la cronología o el número de una lista no, y sin esto
    estarían ahí desde el fotograma uno — el «texto fantasma» que el
    motor anterior prohibió.
    """
    if t is None:
        return interior
    return (f'<g opacity="0"><animate attributeName="opacity" from="0" '
            f'to="1" begin="{t:.2f}s" dur="{dur:g}s" '
            f'fill="freeze"/>{interior}</g>')


def _svg(interior, escala=1):
    """El SVG entero. `escala` cambia el tamaño declarado, no las
    coordenadas: un SVG se rasteriza a SU tamaño intrínseco."""
    w, h = TAMANO
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {w} {h}" width="{int(w * escala)}" '
            f'height="{int(h * escala)}">{interior}</svg>')


def _fondo_svg(colores, semilla=0):
    """Casi negro, con grano, rejilla y viñeta. Ni un píxel de texto."""
    grano = int(_desempatar(semilla, "grano") % 100)
    w, h = TAMANO
    return (
        f'<defs>'
        f'<filter id="ct-grano" x="0" y="0" width="100%" height="100%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="0.82" '
        f'numOctaves="2" seed="{grano}" result="ruido"/>'
        f'<feColorMatrix in="ruido" type="saturate" values="0"/>'
        f'<feComponentTransfer><feFuncA type="linear" slope="0.14"/>'
        f'</feComponentTransfer></filter>'
        f'<pattern id="ct-rejilla" width="64" height="64" '
        f'patternUnits="userSpaceOnUse">'
        f'<path d="M64 0H0V64" fill="none" stroke="{colores["tenue"]}" '
        f'stroke-width="1" opacity="0.05"/></pattern>'
        f'<radialGradient id="ct-alto" cx="50%" cy="42%" r="62%">'
        f'<stop offset="0%" stop-color="{colores["fondo_alto"]}" '
        f'stop-opacity="1"/>'
        f'<stop offset="100%" stop-color="{colores["fondo"]}" '
        f'stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="ct-vineta" cx="50%" cy="46%" r="74%">'
        f'<stop offset="55%" stop-color="#000000" stop-opacity="0"/>'
        f'<stop offset="100%" stop-color="#000000" stop-opacity="0.7"/>'
        f'</radialGradient></defs>'
        f'<rect width="{w}" height="{h}" fill="{colores["fondo"]}"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-alto)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-rejilla)"/>'
        f'<rect width="{w}" height="{h}" filter="url(#ct-grano)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-vineta)"/>')


def _velo_svg(colores, animado=True, primera=None):
    """La capa oscura sobre la imagen para poder leer el texto.

    ENTRA, no está puesta desde el fotograma uno: se ve el plano limpio
    un momento, se oscurece, y entonces empieza a escribirse el texto.
    `primera` es el segundo de la primera palabra, y el velo aterriza
    justo ahí: antes, se oscurece y no pasa nada; después, las primeras
    palabras se escriben sobre la imagen limpia y no se leen.
    """
    w, h = TAMANO
    if primera is None:
        inicio, dur = VELO_ENTRADA
    else:
        cierra = max(VELO_MINIMO_S, float(primera))
        inicio = max(0.05, min(cierra * FRACCION_LIMPIA,
                               cierra - VELO_MINIMO_S))
        dur = max(VELO_MINIMO_S, cierra - inicio)
    entra = ("" if not animado else
             f'<animate attributeName="opacity" from="0" to="{VELO}" '
             f'begin="{inicio:.2f}s" dur="{dur:.2f}s" fill="freeze" '
             f'calcMode="spline" keySplines="0.3 0 0.2 1" keyTimes="0;1"/>')
    return (f'<defs><radialGradient id="ct-velo" cx="50%" cy="46%" r="72%">'
            f'<stop offset="35%" stop-color="{colores["fondo"]}" '
            f'stop-opacity="1"/>'
            f'<stop offset="100%" stop-color="#000000" stop-opacity="1"/>'
            f'</radialGradient></defs>'
            f'<rect width="{w}" height="{h}" fill="url(#ct-velo)" '
            f'opacity="{0 if animado else VELO}">{entra}</rect>')


def svg_carta(ficha, paleta=None, diseno=None, duracion=4.0, semilla=0,
              debajo="", tiempos=None, animada=False):
    """La cartela entera como SVG: para la vista previa y el catálogo.

    `debajo` es un trozo de SVG que va bajo todo — la imagen del plano
    cuando la cartela va encima de ella. `animada` la devuelve
    ESCRIBIÉNDOSE con los mismos tiempos con los que la va a escribir
    el render: quieta no se puede ver lo único que hay que repasar de
    una cartela — si sus palabras entran cuando la voz las dice —, y
    una animación inventada aparte volvería a ser una maqueta que se
    desincroniza.
    """
    plantilla, datos = _desmontar(ficha)
    colores = colores_de(paleta, plantilla)
    if fondo_de(ficha) == "imagen":
        base = ((debajo or _fondo_svg(colores, semilla))
                + _velo_svg(colores, animado=animada,
                            primera=(float(tiempos[0])
                                     if tiempos else ENTRADA)))
    else:
        base = _fondo_svg(colores, semilla)
    piezas = _cuerpo(plantilla, datos, colores, diseno, duracion,
                     animado=animada, semilla=semilla, tiempos=tiempos)
    return _svg(base + _svg_de(piezas, diseno))


def _desmontar(ficha):
    """(plantilla, datos) de una ficha de cartela, con respaldo roto."""
    ficha = ficha if isinstance(ficha, dict) else {}
    plantilla = str(ficha.get("plantilla") or PLANTILLA_POR_DEFECTO)
    if plantilla not in PLANTILLAS:
        plantilla = PLANTILLA_POR_DEFECTO
    datos = ficha.get("datos") if isinstance(ficha.get("datos"), dict) else {}
    if not datos:
        datos = dict(PLANTILLAS[plantilla]["ejemplo"])
    return plantilla, datos


def muestra_de(plantilla, paleta=None, diseno=None, tamano=(480, 270)):
    """SVG pequeño de cómo se ve esa plantilla, con su texto de ejemplo.

    Se dibuja con el MISMO código que la cartela de verdad y después se
    escala: una maqueta hecha aparte se desincroniza en cuanto alguien
    toca una plantilla.
    """
    ficha = {"plantilla": plantilla,
             "datos": dict(plantilla_de(plantilla)["ejemplo"])}
    entero = svg_carta(ficha, paleta, diseno, duracion=4.0)
    interior = entero[entero.index(">") + 1:-len("</svg>")]
    ancho, alto = tamano
    # se enseña la BANDA que queda en cuadro, no el lienzo entero: lo de
    # arriba y lo de abajo no sale en el vídeo y en una muestra pequeña
    # engañaría.
    bx, by, bx2, by2 = BANDA
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" '
            f'height="{alto}" viewBox="{bx} {by} {bx2 - bx} {by2 - by}">'
            f'{interior}</svg>')


def catalogo_plantillas(paleta=None, diseno=None):
    """Las plantillas con su muestra dibujada, para elegirlas mirándolas."""
    fichas = []
    for pid in plantillas_elegibles():
        ficha = PLANTILLAS[pid]
        fichas.append({
            "id": pid, "nombre": ficha["nombre"],
            "descripcion": ficha["descripcion"], "cuando": ficha["cuando"],
            "campos": {k: {"obligatorio": v[0], "tope": v[1]}
                       for k, v in ficha["campos"].items()},
            "lista": ficha.get("lista"),
            "svg": muestra_de(pid, paleta, diseno),
        })
    return fichas


# ===========================================================================
# EL ANCLAJE: cuándo se dice cada palabra de la cartela
# ===========================================================================

def tramos_de(*escenas):
    """(narracion, marcas) de cada plano, en orden de vídeo, saltando vacíos.

    Es lo que se le pasa a `encajar` para buscar en una VENTANA: las
    marcas de los vecinos ya están en el reloj del vídeo, así que
    buscar en tres planos en vez de en uno no inventa ningún dato.
    """
    tramos = []
    for escena in escenas:
        escena = escena if isinstance(escena, dict) else {}
        narracion, marcas = escena.get("narracion"), escena.get("marcas")
        if narracion and marcas:
            tramos.append((narracion, marcas))
    return tramos


def vecinos_de(escenas, sid):
    """El plano de antes y el de después de ese, para alinear en VENTANA."""
    lista = list(escenas or [])
    for indice, escena in enumerate(lista):
        if isinstance(escena, dict) and escena.get("id") == sid:
            return (lista[indice - 1] if indice > 0 else None,
                    lista[indice + 1] if indice + 1 < len(lista) else None)
    return None, None


def fuera_de_orden(palabras_cartela, narracion, idioma=None):
    """Palabras que se dicen, pero no donde la cartela las pone. -> list

    -> [(palabra, la_anterior_anclada), ...]; vacía si el orden está bien.

    EL FALLO QUE DETECTA: la narración decía «...y se abrió la puerta»
    y la cartela «SE ABRIÓ LA PUERTA»... al revés. Las palabras son las
    que se oyen, pero puestas en otro orden, y una cartela se escribe
    de izquierda a derecha al ritmo de la voz: NINGUNA sincronía puede
    quedar bien con el texto en otro orden.

    ESTO NO SE ARREGLA ANCLANDO MEJOR: el anclaje elige la ocurrencia
    buena, pero no puede reordenar la frase. Reordenarla en código
    sería arreglar la salida en vez del motor, y además destrozaría el
    texto.

    CÓMO SE MIDE: se pregunta POR EL ANCLAJE DE VERDAD, el mismo que va
    a decidir cuándo entra cada palabra, y CONTRA SU PROPIO PLANO y no
    contra la ventana de tres — con la ventana, una palabra corriente
    del plano de al lado deja en falso desorden a media cartela bien
    escrita.

        una palabra que no se dice        se salta — eso es DESTILAR
        una palabra que se dice y ancla   perfecto
        una palabra que se dice y NO ancla  <- esto es lo que se avisa

    Es un AVISO y nunca un descarte: quedan falsos positivos posibles,
    y quitarle la cartela a un plano por eso sería peor que el fallo.
    """
    palabras = [str(p) for p in (palabras_cartela or [])]
    dichas = _palabras_llanas(narracion)
    if not palabras or not dichas:
        return []

    numeros = _numeros_en(dichas, idioma)
    anclas = _anclas_mas_juntas(palabras, dichas,
                                [[0.0, 0.0]] * len(dichas), numeros)
    fuera, ultima = [], ""
    for indice, cruda in enumerate(palabras):
        if indice in anclas:
            ultima = cruda
            continue
        aguja = piezas_de(cruda)[:1]
        if not aguja or not aguja[0][0]:
            continue
        if any(casar_desde(aguja, dichas, j, numeros)
               for j in range(len(dichas))):
            fuera.append((cruda, ultima))
    return fuera


def _opciones_de(palabras, dichas, numeros):
    """Dónde podría anclar cada palabra escrita. -> [(indice, [(j, cuantas)])]

    Se calculan TODAS y no la primera: elegir la primera que casa es lo
    que ponía «UNA» sobre el «una» de «una contraseña» en vez de sobre
    el de «una puerta».
    """
    opciones = []
    for indice, cruda in enumerate(palabras):
        # La primera pieza y no todas: una palabra escrita con guion
        # sigue anclando por su primera mitad. Una cifra es UNA pieza
        # con su valor, así que entra entera.
        aguja = piezas_de(cruda)[:1]
        if not aguja or not aguja[0][0]:
            continue
        donde = []
        for j in range(len(dichas)):
            cuantas = casar_desde(aguja, dichas, j, numeros)
            if cuantas:
                donde.append((j, cuantas))
        if donde:
            opciones.append((indice, donde))
    return opciones


def _anclas_mas_juntas(palabras, dichas, marcas, numeros):
    """A qué segundo se ancla cada palabra. -> {indice: segundo}

    EL FALLO QUE ARREGLA: la narración decía «alguien tecleó un usuario
    y una contraseña» y la cartela «UNA CONTRASEÑA». El «UNA» se anclaba
    en el PRIMER «una» —el de «un usuario»— porque se cogía la primera
    marca que casaba, así que en pantalla aparecía «UNA», pasaba un
    segundo y medio de audio que no tenía nada que ver, y después
    aparecía «CONTRASEÑA». Las dos palabras se dicen juntas y salían
    separadas.

    ASÍ QUE SE ELIGE LA CADENA MÁS JUNTA, no la primera. De todas las
    formas de repartir las palabras en orden, gana la que:

        1. ancla MÁS palabras — una anclada vale más que una
           interpolada, porque la interpolada no cae donde se dice;
        2. las deja más JUNTAS (menos distancia primera-última);
        3. y a igualdad, la que empieza antes.

    Sigue siendo MONÓTONA —las palabras se anclan en orden— porque una
    cartela se escribe de izquierda a derecha y dos palabras que entren
    al revés se leen como un parpadeo. Y sigue consumiendo el TRAMO
    entero: si «30M» ancló en «treinta millones», la palabra siguiente
    no puede anclar en «millones».
    """
    opciones = _opciones_de(palabras, dichas, numeros)
    if not opciones:
        return {}

    def cadena_desde(arranque, primera_j, primera_cuantas):
        """Lo más que se puede anclar empezando por ahí. -> [(indice, j)]"""
        elegidas = [(opciones[arranque][0], primera_j)]
        j = primera_j + primera_cuantas
        for indice, donde in opciones[arranque + 1:]:
            for k, cuantas in donde:
                if k >= j:
                    elegidas.append((indice, k))
                    j = k + cuantas
                    break
        return elegidas

    mejor, coste_mejor = None, None
    # SE PRUEBA CON CADA PALABRA COMO PRIMERA ANCLADA, no solo con la
    # primera de la cartela: si la primera no se dice en este tramo,
    # empezar por la segunda ancla más palabras. Son pocas palabras y
    # pocas marcas, así que probarlas todas cuesta nada.
    for arranque in range(len(opciones)):
        for primera_j, primera_cuantas in opciones[arranque][1]:
            elegidas = cadena_desde(arranque, primera_j, primera_cuantas)
            dispersion = elegidas[-1][1] - elegidas[0][1]
            coste = (-len(elegidas), dispersion, primera_j)
            if coste_mejor is None or coste < coste_mejor:
                mejor, coste_mejor = elegidas, coste
    return {indice: float(marcas[j][0]) for indice, j in (mejor or [])}


def encajar(palabras_cartela, tramos, duracion=4.0, idioma=None):
    """Cuándo se dice cada palabra de la cartela, EN EL RELOJ DEL VÍDEO.

    Devuelve una lista de segundos absolutos (una por palabra escrita)
    o [] si no hay ni una sola ancla. NO recorta contra ningún plano a
    propósito: de esta lista sale justamente la decisión de QUÉ PLANOS
    ocupa la cartela, y recortarla antes sería decidir la respuesta con
    la pregunta.

    La cartela DESTILA la narración y eso es el estilo, no un obstáculo:
    se ancla lo que sí coincide —en orden, sin volver atrás— y lo que
    no se reparte entre sus vecinas ancladas.

    `tramos` es [(narracion, marcas), ...] en orden de vídeo; `marcas`
    es [[inicio, fin], ...] por palabra, en el reloj del vídeo.
    """
    palabras = [str(p) for p in (palabras_cartela or [])]
    if not palabras:
        return []
    dichas, marcas = [], []
    for narracion, crudas in (tramos or []):
        llanas = _palabras_llanas(narracion)
        tiempos = [m for m in (crudas or [])
                   if isinstance(m, (list, tuple)) and m]
        # La correspondencia palabra n <-> marca n es posicional y la
        # garantiza p6: si un tramo no cuadra se salta ESE tramo, no se
        # tira la ventana entera — los vecinos siguen sirviendo.
        if not llanas or len(llanas) != len(tiempos):
            continue
        dichas.extend(llanas)
        marcas.extend(tiempos)
    if not dichas:
        return []

    numeros = _numeros_en(dichas, idioma)
    anclas = _anclas_mas_juntas(palabras, dichas, marcas, numeros)
    if not anclas:
        return []

    # Lo no anclado se reparte entre las anclas que lo rodean. Fuera de
    # la primera y de la última se extrapola con el paso sintético.
    paso = _paso_de(duracion, len(palabras))
    llaves = sorted(anclas)
    tiempos, ultimo = [], None
    for indice in range(len(palabras)):
        if indice in anclas:
            valor = anclas[indice]
        else:
            antes = [k for k in llaves if k < indice]
            despues = [k for k in llaves if k > indice]
            if antes and despues:
                a, b = antes[-1], despues[0]
                fraccion = (indice - a) / float(b - a)
                valor = anclas[a] + (anclas[b] - anclas[a]) * fraccion
            elif antes:
                a = antes[-1]
                valor = anclas[a] + (indice - a) * paso
            else:
                b = despues[0]
                valor = anclas[b] - (b - indice) * paso
        # Monótono: dos palabras que entren al revés se leen como un
        # parpadeo.
        valor = valor if ultimo is None else max(valor, ultimo)
        ultimo = valor
        tiempos.append(round(valor, 3))
    return tiempos


def alinear(palabras_cartela, narracion, marcas, t_in=0.0, duracion=4.0,
            entrada=None, idioma=None, tramos=None):
    """Cuándo se dice cada palabra, DESDE EL PRINCIPIO DE SU PLANO.

    Es `encajar` metido en un plano: se resta el `t_in` y se recorta
    para que ninguna palabra entre antes de la animación de entrada ni
    después del corte — una palabra que entrara después del corte no se
    vería nunca. `tramos` alinea contra una VENTANA en vez de contra un
    solo plano; sin él se mira solo `narracion`. [] si no hay con qué
    alinear, y entonces manda el ritmo sintético de siempre y no se
    finge una sincronía que no existe.
    """
    if tramos is None:
        tramos = tramos_de({"narracion": narracion, "marcas": marcas})
    crudos = encajar(palabras_cartela, tramos, duracion=duracion,
                     idioma=idioma)
    if not crudos:
        return []
    return _en_el_plano(crudos, t_in, duracion, entrada)


def _en_el_plano(tiempos_video, t_in, duracion, entrada=None):
    """El encaje del vídeo, metido en un plano: se resta y se recorta."""
    entrada = ENTRADA if entrada is None else float(entrada)
    t_in, duracion = float(t_in), float(duracion)
    techo = max(entrada, duracion - 0.25)
    limpio, ultimo = [], -1.0
    for valor in tiempos_video:
        valor = max(entrada, min(float(valor) - t_in, techo), ultimo)
        limpio.append(round(valor, 3))
        ultimo = valor
    return limpio


def palabras_dibujadas(ficha, duracion=4.0, diseno=None):
    """Las palabras que se escriben, EN EL ORDEN en que las escribe el
    dibujado. Sale de dibujar, no de recorrer la ficha: cada plantilla
    escribe SUS campos en SU orden, así que una lista sacada del
    diccionario emparejaría la palabra 3 de la cartela con la marca de
    tiempo de otra."""
    return [palabra for _, palabra in
            tiempos_de_escritura(ficha, duracion, diseno)]


# ===========================================================================
# LOS TIEMPOS PÚBLICOS: una sola cuenta para el plan, el dibujado y el
# sonido. Antes cada uno hacía la suya.
# ===========================================================================

def cola_de_lectura(ficha, palabras=None):
    """Cuánto tiene que quedarse en pantalla YA ESCRITA para leerse."""
    if palabras is None:
        _, datos = _desmontar(ficha)
        palabras = _cuentapalabras(datos)
    return round(max(COLA_MINIMA, palabras * COLA_POR_PALABRA), 2)


def tiempo_necesario(ficha, duracion=None):
    """Cuántos segundos necesita esta cartela para escribirse Y leerse."""
    _, datos = _desmontar(ficha)
    palabras = _cuentapalabras(datos)
    escribir = palabras * _paso_de(duracion or 4.0, palabras)
    return round(ENTRADA + escribir + cola_de_lectura(ficha, palabras), 2)


def encaje_de(ficha, escena, antes=None, despues=None, diseno=None,
              idioma=None, ventana=None):
    """EN QUÉ TRAMO DEL VÍDEO se dicen las palabras de esta cartela.

        {"palabras": [...],   las que se escriben, en orden de dibujado
         "tiempos": [...],    el segundo del VÍDEO de cada una
         "ini": s, "fin": s,  el tramo que ocupan
         "cola": s}           lo que además necesita quedarse puesta

    None si no hay ni una ancla, que es cuando manda el ritmo sintético.

    Busca en una VENTANA — el plano anterior, el suyo y el siguiente —
    y no solo en el suyo, porque una cartela puede destilar una frase
    que empieza a decirse antes de su propio plano: mirando solo el
    suyo la respuesta era [] y el sistema ni se enteraba.
    """
    duracion = duracion_de(escena)
    palabras = palabras_dibujadas(ficha, duracion, diseno)
    planos = list(ventana) if ventana else [antes, escena, despues]
    tiempos = encajar(palabras, tramos_de(*planos),
                      duracion=duracion, idioma=idioma)
    if not tiempos:
        return None
    return {"palabras": palabras, "tiempos": tiempos,
            "ini": round(tiempos[0], 3), "fin": round(tiempos[-1], 3),
            "cola": cola_de_lectura(ficha, len(palabras) or 1)}


def escritura_de(ficha, escena, encaje=None, t_in=None, t_out=None,
                 diseno=None):
    """El plan de escritura, ya en el reloj del plano que la lleva.

        {"tiempos": [...],      cuándo entra cada palabra ([] = ritmo de siempre)
         "palabras": N,         cuántas se escriben de verdad
         "fin": s,              cuándo termina de escribirse
         "cola": s,             lo que necesita quedarse puesta
         "falta": s,            lo que le falta POR DELANTE (0 si le sobra)
         "antes": s,            lo que sus palabras empiezan ANTES de su tramo
         "encaje": [ini, fin],  el tramo del VÍDEO en el que se dicen
         "desde_antes": bool,   tiene que arrancar en el plano anterior
         "dos_planos": bool}    tiene que seguir en el siguiente

    `t_in`/`t_out` son el tramo de vídeo que la cartela ocupa DE
    VERDAD. Por defecto los de su plano; cuando ya se ha decidido que
    se estira, los del tramo entero — y entonces `falta` y `antes`
    salen cero, que es lo que quiere decir «ya cabe».
    """
    t_in = float(escena.get("t_in") or 0.0) if t_in is None else float(t_in)
    if t_out is None:
        t_out = t_in + duracion_de(escena)
    t_out = float(t_out)
    duracion = max(0.1, t_out - t_in)
    registro = tiempos_de_escritura(ficha, duracion_de(escena), diseno)
    cuantas = len([p for _, p in registro])

    if encaje:
        tiempos = _en_el_plano(encaje["tiempos"], t_in, duracion)
        cola = float(encaje["cola"])
        ini, fin = float(encaje["ini"]), float(encaje["fin"])
        antes = max(0.0, t_in - ini)
        falta = max(0.0, cola - (t_out - fin))
        fin_relativo = fin - t_in
    else:
        # Sin nada con qué alinear se vuelve al ritmo de siempre, y
        # entonces la única cuenta honesta es la de las palabras.
        tiempos = []
        cola = cola_de_lectura(ficha, cuantas or 1)
        fin_relativo = float(registro[-1][0]) if registro else ENTRADA
        ini, fin = t_in, t_in + fin_relativo
        antes = 0.0
        falta = max(0.0, cola - (duracion - fin_relativo))
    return {"tiempos": tiempos, "palabras": cuantas,
            "fin": round(fin_relativo, 3), "cola": cola,
            "falta": round(falta, 2), "antes": round(antes, 2),
            "encaje": [round(ini, 3), round(fin, 3)],
            "desde_antes": antes > 0.01, "dos_planos": falta > 0.01}


def techo_de(params=None):
    """Cuánto puede estar puesta una cartela en este vídeo, en segundos.

    Proporcional y no un número fijo, porque «largo» no significa lo
    mismo en dos vídeos distintos: el techo cuelga del `planos_max_s`
    que el usuario ya configura para decir el ritmo que quiere. Y NO SE
    REGENERA NADA PARA CUMPLIRLO: se avisa con el número delante y se
    arregla donde se escribe.
    """
    params = params or {}
    try:
        max_s = float(params.get("planos_max_s") or params.get("max_s")
                      or MAX_S_POR_DEFECTO)
    except (TypeError, ValueError):
        max_s = MAX_S_POR_DEFECTO
    return round(max(2.0, max_s) * FACTOR_TECHO, 2)


#: El techo del vídeo por defecto, para quien no tiene params a mano.
SEGUNDOS_MAXIMOS = techo_de(None)


def palabras_que_caben(duracion):
    """Cuántas palabras se pueden escribir Y leer en ese hueco. Al menos 1.

    Es `tiempo_necesario` al revés, y existe para poder DECÍRSELO al
    agente que escribe las cartelas: el presupuesto de palabras ya
    estaba en su prompt, pero escrito como regla general, y una regla
    general contra un plano concreto de 2,5 s no dice nada. Con el
    número de SU plano delante, la petición deja de ser un consejo.
    """
    duracion = float(duracion or 0)
    cabe = 1
    for palabras in range(1, 41):
        necesita = (ENTRADA + palabras * _paso_de(duracion, palabras)
                    + max(COLA_MINIMA, palabras * COLA_POR_PALABRA))
        if necesita > duracion:
            break
        cabe = palabras
    return cabe


def palabras_maximas(params=None):
    """El presupuesto de una cartela ENTERA, sumando todos sus campos.

    Sale de la MISMA cuenta que decide después si cabe, para que no
    puedan discrepar: lo que el agente lee es exactamente lo que el
    motor va a medir.
    """
    return palabras_que_caben(techo_de(params))


#: El presupuesto del vídeo por defecto, para quien no tiene params.
PALABRAS_MAXIMAS = palabras_maximas(None)


def cuantas_palabras(ficha):
    """Cuántas palabras tiene esta cartela en total, sumando sus campos."""
    _, datos = _desmontar(ficha)
    return _cuentapalabras(datos)


def _cuentapalabras(datos):
    """Cuántas palabras se van a ESCRIBIR en total. Manda el ritmo.

    No cuenta el icono: es un glifo, no una palabra, y contarlo pedía
    más tiempo del que necesita y media la cartela contra un techo más
    estrecho del que le toca.
    """
    total = 0
    for campo, valor in (datos or {}).items():
        if campo in CAMPOS_SIN_TEXTO:
            continue
        if isinstance(valor, list):
            total += sum(len(str(v).split()) for v in valor)
        else:
            total += len(str(valor).split())
    return max(1, total)


def plan_de_escritura(ficha, escena, diseno=None, antes=None, despues=None,
                      idioma=None):
    """Todo lo que hay que saber para escribir esta cartela en SU plano.

    Se calcula UNA vez y lo usan los tres sitios que tienen que estar
    de acuerdo: el plan (para decidir qué planos ocupa), el dibujado
    (para escribir a tiempo) y el sonido (para teclear donde se
    escribe).
    """
    encaje = encaje_de(ficha, escena, antes, despues, diseno, idioma)
    return escritura_de(ficha, escena, encaje, diseno=diseno)


def duracion_de(escena):
    """Lo que dura un plano, con los tres sitios donde puede estar."""
    escena = escena if isinstance(escena, dict) else {}
    return (float(escena.get("duracion") or 0)
            or float((escena.get("t_out") or 0) - (escena.get("t_in") or 0))
            or 4.0)


def tiempos_de_escritura(ficha, duracion=4.0, diseno=None, tiempos=None):
    """Cuándo entra cada palabra: [(segundo, palabra)]. Para el sonido.

    Sale de DIBUJAR la cartela y recoger lo que apunta el propio
    dibujado, no de una cuenta paralela: las teclas de la máquina de
    escribir tienen que caer exactamente donde caen las palabras, y con
    dos cuentas se separan en cuanto alguien toca el ritmo. Por eso
    `tiempos` tiene que llegar aquí igual que llega al dibujado: si la
    cartela va sincronizada con la voz y el teclado no, se oye escribir
    cuando no se escribe.
    """
    plantilla, datos = _desmontar(ficha)
    registro = []
    _cuerpo(plantilla, datos, colores_de(None, plantilla), diseno,
            duracion, animado=True, registro=registro, tiempos=tiempos)
    return registro


def tiempos_dichos(ficha, escena, duracion=None, diseno=None, antes=None,
                   despues=None, idioma=None):
    """Los segundos de cada palabra, alineados con la narración.

    Es el atajo que usan el render (para dibujar) y el sonido (para
    teclear): recibe el plano — que ya trae `narracion` y `marcas` — y
    devuelve lo que espera `svg_carta`/`fotograma`. [] si no hay con
    qué alinear, y entonces manda el ritmo sintético de siempre.

    Es el CAMINO DE RESPALDO: cuando el plano trae `escritura.tiempos`
    mandan esos, porque los calculó la planificación sabiendo además
    qué planos ocupa la cartela. Aquí se recalcula para un plano viejo
    o para una vista previa.
    """
    escena = escena if isinstance(escena, dict) else {}
    duracion = duracion or duracion_de(escena)
    palabras = palabras_dibujadas(ficha, duracion, diseno)
    return alinear(palabras, escena.get("narracion"), escena.get("marcas"),
                   t_in=float(escena.get("t_in") or 0.0), duracion=duracion,
                   idioma=idioma, tramos=tramos_de(antes, escena, despues))


def bloque_de(escena):
    """De qué bloque del guion sale este plano. '' si no se sabe.

    Aquí el bloque es la ESCENA del guion: es la unidad que escribió el
    redactor de una vez, y la frontera donde una cartela se para — una
    cartela que cruza esa línea se queda puesta mientras la narración
    ya cuenta otra cosa.
    """
    return str((escena or {}).get("escena") or "")


def tramo_de(ficha, escenas, indice, libre=None, diseno=None, idioma=None,
             planos=None):
    """DE QUÉ PLANO A QUÉ PLANO ocupa esta cartela. (desde, hasta, escritura).

    Una cartela ocupa el tramo de vídeo en el que se dicen sus
    palabras: se estira MIENTRAS le falte y haya un plano libre al
    lado, en vez de pararse en un número inventado.

    LA FRENAN DOS COSAS, y para en la primera que llegue:

    EL BLOQUE (la escena del guion), que es la frontera del relato.

    Y EL TOPE DE PLANOS (`PLANOS_MAXIMOS`), que es la frontera del
    montaje — en planos y no en segundos, porque lo que se decide aquí
    es de montaje: cuántos cortes se sacrifican para que el texto quepa.

    HACIA ATRÁS Y HACIA DELANTE: el tramo entero se FUNDE en un solo
    plano más largo (lo hace p6), así que no hay ningún corte dentro del
    tramo ni fondo que cambie.

    LA CARTELA SE MUDA AL PLANO DONDE SE DICE (simétrico de
    `desde_antes`): si sus palabras no EMPIEZAN hasta el plano
    siguiente, el hogar es ESE. Antes se extendía sobre los dos pero se
    escribía comprimida contra el final del primero. Y no oscila: al
    mudarse, el nuevo t_in queda por debajo del inicio del encaje, o
    sea que `antes` sale cero y la rama de arriba no dispara.

    `libre(escena)` dice si ese plano se puede absorber; sin él, ninguno.
    """
    escenas = list(escenas or [])
    libre = libre or (lambda _e: False)
    planos = int(planos or PLANOS_MAXIMOS)
    bloque = bloque_de(escenas[indice])
    desde = hasta = indice
    escritura = None

    def cabe(otro, nuevo_desde, nuevo_hasta):
        """Si la cartela puede llegar hasta ahí: misma idea Y tope."""
        if not libre(otro) or (nuevo_hasta - nuevo_desde + 1) > planos:
            return False
        # el bloque del guion manda por encima del tope: es la frontera
        # del relato, no la del montaje
        return not bloque or not bloque_de(otro) or bloque_de(otro) == bloque

    for _ in range(len(escenas) + 1):        # cota dura: nunca un while True
        ventana = escenas[max(0, desde - 1):min(len(escenas), hasta + 2)]
        encaje = encaje_de(ficha, escenas[indice], diseno=diseno,
                           idioma=idioma, ventana=ventana)
        escritura = escritura_de(ficha, escenas[indice], encaje,
                                 t_in=escenas[desde].get("t_in"),
                                 t_out=escenas[hasta].get("t_out"),
                                 diseno=diseno)
        if (escritura["desde_antes"] and desde > 0
                and cabe(escenas[desde - 1], desde - 1, hasta)):
            desde -= 1
            continue
        if (desde < hasta
                and escritura["encaje"][0]
                >= float(escenas[desde].get("t_out") or 0)):
            desde += 1
            continue
        if (escritura["dos_planos"] and hasta + 1 < len(escenas)
                and cabe(escenas[hasta + 1], desde, hasta + 1)):
            hasta += 1
            continue
        break
    return desde, hasta, escritura


def ocupacion_de(escenas, plan_bruto, diseno=None, idioma=None, planos=None):
    """Qué planos ocuparía cada cartela candidata: {sid: (desde, hasta)}.

    Se calcula ANTES de repartir, porque una cartela que ocupa dos
    planos consume DOS del reparto: contarlo después dejaría el suelo
    de separación midiendo una cosa y el vídeo enseñando otra. Es una
    cuenta OPTIMISTA — aquí todavía no se sabe cuáles van a entrar.
    """
    plan = {k: v for k, v in (plan_bruto or {}).items() if v}
    escenas = list(escenas or [])
    por_id = {e.get("id"): i for i, e in enumerate(escenas)}

    def libre(otro):
        otro = otro or {}
        return not (plan.get(otro.get("id")) or otro.get("cartela")
                    or otro.get("sigue_a"))

    ocupacion = {}
    for sid, ficha in plan.items():
        indice = por_id.get(sid)
        if indice is None:
            continue
        try:
            desde, hasta, _ = tramo_de(ficha, escenas, indice, libre,
                                       diseno, idioma, planos)
        except Exception:                                        # noqa: BLE001
            continue
        if (desde, hasta) != (indice, indice):
            ocupacion[sid] = (desde, hasta)
    return ocupacion


# ===========================================================================
# EL PINTOR DE FOTOGRAMAS (PIL, para el ffmpeg del render)
#
# El original rasterizaba el SVG con Edge; aquí no hay navegador, así
# que se pinta a mano. Come las MISMAS primitivas que el SVG —una sola
# composición, dos pintores— y con la MISMA fuente de verdad de
# `nucleo.tipografia`, porque medir con una fuente y dibujar con otra
# da la cuenta bien y el número mal.
#
# Las coordenadas de la plantilla son del lienzo 3:2 (1536x1024) pero
# el vídeo recorta la BANDA (1536x864) y la tira a 1920x1080: la
# transformación es un x1,25 uniforme, así que se pinta directamente a
# resolución final — letra incluida — en vez de escalar después.
# ===========================================================================

_TOKEN_PATH = re.compile(r"([MmLlHhVvCcSsAaQqTtZz])"
                         r"|(-?(?:\d+\.?\d*|\.\d+))")
_cache_trazos: dict[str, list] = {}


def _recorrer_path(d):
    """Un `d` de SVG, como lista de polilíneas en su caja de 24x24.

    Parser mínimo para los diecinueve iconos de arriba: líneas (M/L/
    H/V), curvas (C/S/Q/T) y arcos (A) aplanados a segmentos. Vive aquí
    y no en una librería porque son diecinueve paths y una dependencia
    sería pagar mucho por poco.
    """
    comandos = []
    for m in _TOKEN_PATH.finditer(str(d or "")):
        if m.group(1):
            comandos.append((m.group(1), []))
        elif comandos:
            comandos[-1][1].append(float(m.group(2)))
    poligonos, puntos = [], []

    def tramo(*nuevos):
        for p in nuevos:
            if not puntos or puntos[-1] != p:
                puntos.append(p)

    def bezier(x0, y0, x1, y1, x2, y2, x3, y3, pasos=12):
        for i in range(1, pasos + 1):
            u = i / float(pasos)
            v = 1.0 - u
            tramo((v ** 3 * x0 + 3 * v * v * u * x1 + 3 * v * u * u * x2
                   + u ** 3 * x3,
                   v ** 3 * y0 + 3 * v * v * u * y1 + 3 * v * u * u * y2
                   + u ** 3 * y3))

    def arco(x0, y0, rx, ry, rot, grande, barrido, x1, y1, pasos=16):
        # el método del propio estándar (F.6.5): de extremo a centro
        rx, ry = max(abs(rx), 1e-6), max(abs(ry), 1e-6)
        rad = math.radians(rot % 360)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        dx, dy = (x0 - x1) / 2.0, (y0 - y1) / 2.0
        x1p = cos_r * dx + sin_r * dy
        y1p = -sin_r * dx + cos_r * dy
        lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
        if lam > 1:
            s = math.sqrt(lam)
            rx, ry = rx * s, ry * s
        num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
        den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
        co = math.sqrt(max(0.0, num / den)) if den else 0.0
        if grande == barrido:
            co = -co
        cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
        cx = cos_r * cxp - sin_r * cyp + (x0 + x1) / 2.0
        cy = sin_r * cxp + cos_r * cyp + (y0 + y1) / 2.0

        def angulo(ux, uy, vx, vy):
            n = math.hypot(ux, uy) * math.hypot(vx, vy) or 1e-9
            a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / n)))
            return -a if ux * vy - uy * vx < 0 else a

        th1 = angulo(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        dth = angulo((x1p - cxp) / rx, (y1p - cyp) / ry,
                     (-x1p - cxp) / rx, (-y1p - cyp) / ry)
        if not barrido and dth > 0:
            dth -= 2 * math.pi
        elif barrido and dth < 0:
            dth += 2 * math.pi
        for i in range(1, pasos + 1):
            t = th1 + dth * i / pasos
            tramo((cx + rx * math.cos(t) * cos_r - ry * math.sin(t) * sin_r,
                   cy + rx * math.cos(t) * sin_r + ry * math.sin(t) * cos_r))

    x = y = 0.0
    inicio = (0.0, 0.0)
    prev = None                      # el segundo control de la C/S anterior
    for letra, nums in comandos:
        tipo = letra.upper()
        relativo = letra.islower()
        i = 0
        if tipo == "M":
            while i + 1 < len(nums) + 1 and i + 2 <= len(nums):
                nx, ny = nums[i], nums[i + 1]
                x, y = (x + nx, y + ny) if relativo else (nx, ny)
                if i == 0:
                    if puntos:
                        poligonos.append(puntos)
                    puntos = [(x, y)]
                    inicio = (x, y)
                else:
                    tramo((x, y))
                i += 2
            prev = None
        elif tipo == "L":
            while i + 2 <= len(nums):
                nx, ny = nums[i], nums[i + 1]
                x, y = (x + nx, y + ny) if relativo else (nx, ny)
                tramo((x, y))
                i += 2
            prev = None
        elif tipo == "H":
            for nx in nums:
                x = x + nx if relativo else nx
                tramo((x, y))
            prev = None
        elif tipo == "V":
            for ny in nums:
                y = y + ny if relativo else ny
                tramo((x, y))
            prev = None
        elif tipo == "C":
            while i + 6 <= len(nums):
                n = [v + (x if relativo else 0) if k % 2 == 0
                     else v + (y if relativo else 0)
                     for k, v in enumerate(nums[i:i + 6])]
                bezier(x, y, *n)
                prev = (n[2], n[3])
                x, y = n[4], n[5]
                i += 6
        elif tipo == "S":
            while i + 4 <= len(nums):
                n = [v + (x if relativo else 0) if k % 2 == 0
                     else v + (y if relativo else 0)
                     for k, v in enumerate(nums[i:i + 4])]
                c1 = (2 * x - prev[0], 2 * y - prev[1]) if prev else (x, y)
                bezier(x, y, *c1, n[0], n[1], n[2], n[3])
                prev = (n[0], n[1])
                x, y = n[2], n[3]
                i += 4
        elif tipo == "Q":
            while i + 4 <= len(nums):
                n = [v + (x if relativo else 0) if k % 2 == 0
                     else v + (y if relativo else 0)
                     for k, v in enumerate(nums[i:i + 4])]
                for j in range(1, 13):
                    u = j / 12.0
                    v = 1.0 - u
                    tramo((v * v * x + 2 * v * u * n[0] + u * u * n[2],
                           v * v * y + 2 * v * u * n[1] + u * u * n[3]))
                prev = (n[0], n[1])
                x, y = n[2], n[3]
                i += 4
        elif tipo == "T":
            while i + 2 <= len(nums):
                n = [v + (x if relativo else 0) if k % 2 == 0
                     else v + (y if relativo else 0)
                     for k, v in enumerate(nums[i:i + 2])]
                c = (2 * x - prev[0], 2 * y - prev[1]) if prev else (x, y)
                for j in range(1, 13):
                    u = j / 12.0
                    v = 1.0 - u
                    tramo((v * v * x + 2 * v * u * c[0] + u * u * n[0],
                           v * v * y + 2 * v * u * c[1] + u * u * n[1]))
                prev = c
                x, y = n[0], n[1]
                i += 2
        elif tipo == "A":
            while i + 7 <= len(nums):
                rx, ry, rot, grande, barrido = nums[i:i + 5]
                dx, dy = nums[i + 5], nums[i + 6]
                x1, y1 = (x + dx, y + dy) if relativo else (dx, dy)
                arco(x, y, rx, ry, rot, int(grande), int(barrido), x1, y1)
                x, y = x1, y1
                i += 7
            prev = None
        elif tipo == "Z":
            tramo(inicio)
            x, y = inicio
            prev = None
    if puntos:
        poligonos.append(puntos)
    return poligonos


def _trazos_de(nombre):
    """Los polígonos de un icono, cacheados (se pintan muchos frames)."""
    if nombre not in _cache_trazos:
        _cache_trazos[nombre] = _recorrer_path(ICONOS.get(nombre, ""))
    return _cache_trazos[nombre]


#: caches de lo que se precalcula una vez y se pinta en cada fotograma
_cache_fondos: dict[tuple, object] = {}
_cache_velos: dict[tuple, object] = {}
_cache_iconos: dict[tuple, object] = {}


def _suave(p):
    """El keySpline de las reglas (0.2 0.8 0.2 1), aproximado."""
    return p * p * (3.0 - 2.0 * p)


def _fondo_pil(colores, semilla, tamano):
    """Casi negro con grano, rejilla y viñeta — como `_fondo_svg`.

    Se precalcula UNA vez por cartela y se pega en cada fotograma: el
    grano es estático a propósito, igual que en el original (allá un
    feTurbulence por fotograma multiplicaba el render por nada).
    """
    from PIL import Image, ImageDraw

    clave = (colores["fondo"], colores["fondo_alto"], colores["tenue"],
             int(_desempatar(semilla, "grano") % 100), tamano)
    if clave in _cache_fondos:
        return _cache_fondos[clave]
    try:
        import numpy as np
    except ImportError:                                # pragma: no cover
        np = None
    w, h = tamano
    img = Image.new("RGB", tamano, colores["fondo"])
    if np is not None:
        yy, xx = np.mgrid[0:h, 0:w]
        ref = math.hypot(w, h) / math.sqrt(2.0)
        # el halo alto del centro (radial fondo_alto -> transparente)
        d = np.sqrt((xx - w * 0.5) ** 2 + (yy - h * 0.42) ** 2) / (0.62 * ref)
        alfa = np.clip(1.0 - d, 0.0, 1.0)
        base = np.asarray(img, dtype=np.float32)
        alto = np.asarray(Image.new("RGB", tamano, colores["fondo_alto"]),
                          dtype=np.float32)
        img = Image.fromarray((base * (1 - alfa[..., None])
                               + alto * alfa[..., None]).astype(np.uint8))
        # la viñeta de los bordes
        d = np.sqrt((xx - w * 0.5) ** 2 + (yy - h * 0.46) ** 2) / (0.74 * ref)
        alfa = 0.7 * np.clip((d - 0.55) / 0.45, 0.0, 1.0)
        base = np.asarray(img, dtype=np.float32)
        img = Image.fromarray((base * (1 - alfa[..., None])
                               ).astype(np.uint8))
        # el grano: ruido gris estático al 14 %
        rng = np.random.default_rng(clave[3])
        grano = rng.integers(0, 256, (h, w), dtype=np.uint8)
        base = np.asarray(img, dtype=np.float32)
        img = Image.fromarray((base * 0.86
                               + grano[..., None] * 0.14).astype(np.uint8))
    dibujo = ImageDraw.Draw(img, "RGBA")
    tenue = tuple(_rgb(colores["tenue"]) or (200, 195, 180)) + (13,)
    paso = max(32, int(64 * (w / float(TAMANO[0]))))
    for gx in range(0, w, paso):
        dibujo.line([(gx, 0), (gx, h)], fill=tenue, width=1)
    for gy in range(0, h, paso):
        dibujo.line([(0, gy), (w, gy)], fill=tenue, width=1)
    if len(_cache_fondos) > 8:
        _cache_fondos.clear()
    _cache_fondos[clave] = img
    return img


def _velo_pil(colores, tamano):
    """El velo radial precalculado (fondo 35 % -> negro 100 %)."""
    from PIL import Image

    clave = (colores["fondo"], tamano)
    if clave in _cache_velos:
        return _cache_velos[clave]
    try:
        import numpy as np
    except ImportError:                                # pragma: no cover
        np = None
    w, h = tamano
    if np is None:
        img = Image.new("RGB", tamano, colores["fondo"])
    else:
        yy, xx = np.mgrid[0:h, 0:w]
        ref = math.hypot(w, h) / math.sqrt(2.0)
        d = np.sqrt((xx - w * 0.5) ** 2 + (yy - h * 0.46) ** 2) / (0.72 * ref)
        cuanto = np.clip((d - 0.35) / 0.65, 0.0, 1.0)[..., None]
        a = np.asarray(Image.new("RGB", tamano, colores["fondo"]),
                       dtype=np.float32)
        img = Image.fromarray((a * (1 - cuanto)).astype(np.uint8))
    if len(_cache_velos) > 8:
        _cache_velos.clear()
    _cache_velos[clave] = img
    return img


def _icono_pil(nombre, tam_px):
    """Un icono RGBA al tamaño de pantalla, cacheado (trazo, sin relleno)."""
    from PIL import Image, ImageDraw

    clave = (nombre, tam_px)
    if clave in _cache_iconos:
        return _cache_iconos[clave]
    img = Image.new("RGBA", (tam_px + 8, tam_px + 8), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(img)
    escala = tam_px / 24.0
    grosor = max(1, round(max(1.2, 2.0 / (tam_px / 24.0)) * escala))
    # se dibuja BLANCO y se tiñe al componer: el color cambia con cada
    # plantilla, pero el trazo es siempre el mismo
    for puntos in _trazos_de(nombre):
        pts = [(4 + px * escala, 4 + py * escala) for px, py in puntos]
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        dibujo.line(pts, fill=(255, 255, 255, 255), width=grosor,
                    joint="curve")
        for extremo in (pts[0], pts[-1]):       # linecap round
            r = grosor / 2.0
            dibujo.ellipse([extremo[0] - r, extremo[1] - r,
                            extremo[0] + r, extremo[1] + r],
                           fill=(255, 255, 255, 255))
    if len(_cache_iconos) > 32:
        _cache_iconos.clear()
    _cache_iconos[clave] = img
    return img


def _tinte(sprite, rgb, alfa):
    """El sprite blanco, del color pedido y con la opacidad pedida."""
    from PIL import Image

    r, g, b, a = sprite.split()
    if alfa < 0.999:
        a = a.point(lambda v: int(v * alfa))
    plano = Image.merge("RGBA", (r.point(lambda v: rgb[0]),
                                 g.point(lambda v: rgb[1]),
                                 b.point(lambda v: rgb[2]), a))
    return plano


def _color_de(hexa):
    return _rgb(hexa) or (236, 231, 220)


def _texto_pil(dibujo, X, Y, texto, fuente, rgb, espaciado_px, anclaje):
    """Un texto en pantalla. Con espaciado, letra a letra (PIL no lo trae)."""
    if espaciado_px:
        anchos = [fuente.getlength(c) for c in texto]
        total = sum(anchos) + espaciado_px * max(0, len(texto) - 1)
        x = X - total / 2.0 if anclaje == "middle" else X
        for ch, ancho in zip(texto, anchos):
            dibujo.text((x, Y), ch, font=fuente, fill=rgb, anchor="ls")
            x += ancho + espaciado_px
        return
    dibujo.text((X, Y), texto, font=fuente, fill=rgb,
                anchor="ms" if anclaje == "middle" else "ls")


def fotograma(ficha, t=0.0, paleta=None, diseno=None, duracion=4.0, semilla=0,
              tiempos=None, base=None, tamano=None, animado=True,
              zoom=None):
    """La cartela pintada en el instante `t`. -> PIL.Image RGB.

    `base` es la imagen del plano (PIL.Image o ruta) cuando la cartela
    va sobre imagen; `tiempos` los segundos de cada palabra cuando va
    sincronizada con la voz. Con `animado=False` sale TODO escrito —
    es la muestra quieta de la rejilla.

    `zoom` es el Ken Burns del plano, (de, a): en el original la
    cartela viajaba DENTRO del grupo del zoom, así que imagen, velo y
    texto se movían JUNTOS — reproducirlo aquí es escalar el fotograma
    compuesto alrededor del centro, no solo la foto de abajo.
    """
    from PIL import Image, ImageDraw, ImageOps

    W, H = tamano or (1920, 1080)
    sx, sy = W / float(TAMANO[0]), H / float(BANDA[3] - BANDA[1])

    def T(x, y):
        return (x * sx, (y - BANDA[1]) * sy)

    plantilla, datos = _desmontar(ficha)
    colores = colores_de(paleta, plantilla)
    fam = _fam_de(diseno)

    # ---- el fondo: la imagen del plano con su velo, o el fondo propio
    if fondo_de(ficha) == "imagen" and base is not None:
        if isinstance(base, (str, Path)):
            base = Image.open(base)
        lienzo = ImageOps.fit(base.convert("RGB"), (W, H),
                              Image.LANCZOS)
        velo = _velo_pil(colores, (W, H))
        primera = float(tiempos[0]) if tiempos else ENTRADA
        cierra = max(VELO_MINIMO_S, primera)
        inicio = max(0.05, min(cierra * FRACCION_LIMPIA,
                               cierra - VELO_MINIMO_S))
        dur = max(VELO_MINIMO_S, cierra - inicio)
        if animado:
            p = min(1.0, max(0.0, (t - inicio) / dur)) if dur > 0 else 1.0
            cuanto = VELO * _suave(p)
        else:
            cuanto = VELO
        lienzo = Image.blend(lienzo, velo, cuanto)
    else:
        lienzo = _fondo_pil(colores, semilla, (W, H)).copy()

    piezas = _cuerpo(plantilla, datos, colores, diseno, duracion,
                     animado=animado, semilla=semilla, tiempos=tiempos)
    lienzo = lienzo.convert("RGBA")

    # ---- el fantasma, precalculado y desplazado (deriva lenta)
    for p in piezas:
        if p["tipo"] != "fantasma":
            continue
        clave = ("fantasma", p["texto"], p["tam"], p["color"], W, H)
        if clave not in _cache_iconos:
            capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(capa)
            fuente = tipografia.fuente(fam, int(p["tam"] * sy), True)
            X, Y = T(p["x"], p["centro"] + p["tam"] * 0.35)
            d.text((X, Y), p["texto"], font=fuente,
                   fill=_color_de(p["color"]) + (int(255 * OPACIDAD_FANTASMA),),
                   anchor="ms")
            _cache_iconos[clave] = capa
        ciclo = 14.0 + p["fase"]
        # values="0 0; 10 -6; -6 8; 0 0", lineal y en bucle
        secuencia = [(0.0, 0.0), (10.0, -6.0), (-6.0, 8.0), (0.0, 0.0)]
        if animado:
            fraccion = (t % ciclo) / ciclo * (len(secuencia) - 1)
            k = min(int(fraccion), len(secuencia) - 2)
            u = fraccion - k
            dx = (secuencia[k][0] * (1 - u) + secuencia[k + 1][0] * u) * sx
            dy = (secuencia[k][1] * (1 - u) + secuencia[k + 1][1] * u) * sy
        else:
            dx = dy = 0.0
        desplazado = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        desplazado.paste(_cache_iconos[clave], (int(round(dx)), int(round(dy))))
        lienzo = Image.alpha_composite(lienzo, desplazado)

    tinta = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def sellar(dibujar, alfa):
        """Dibuja sobre la tinta; si es semitransparente, capa aparte."""
        if alfa >= 0.999:
            dibujar(ImageDraw.Draw(tinta))
            return
        capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dibujar(ImageDraw.Draw(capa))
        r, g, b, a = capa.split()
        a = a.point(lambda v: int(v * alfa))
        lienzo.alpha_composite(Image.merge("RGBA", (r, g, b, a)))

    for p in piezas:
        tipo = p["tipo"]
        if tipo == "texto":
            fuente = tipografia.fuente(fam, max(6, int(round(p["tam"] * sy))),
                                       p["negrita"])
            X, Y = T(p["x"], p["y"])
            rgb = _color_de(p["color"])
            alfa = p["opacidad"]
            if animado and p["t"] is not None:
                dur = p["entra_dur"] or 0.22
                alfa *= min(1.0, max(0.0, (t - p["t"]) / dur))
            if alfa <= 0.01:
                continue

            def dibuja(d, X=X, Y=Y, p=p, fuente=fuente, rgb=rgb):
                _texto_pil(d, X, Y, p["texto"], fuente, rgb,
                           p["espaciado"] * sx, p["anclaje"])
            sellar(dibuja, alfa)
        elif tipo == "escrito":
            fuente = tipografia.fuente(fam, max(6, int(round(p["tam"] * sy))),
                                       p["negrita"])
            rgb = _color_de(p["color"])
            salto = p["tam"] * p["interlineado"] * sy
            esp = p["espaciado"] * sx
            hueco = fuente.getlength(" ") + esp
            indice = 0
            for i, linea in enumerate(p["lineas"]):
                palabras = linea.split()
                anchos = [fuente.getlength(w) + esp * len(w)
                          for w in palabras]
                total = sum(anchos) + hueco * max(0, len(palabras) - 1)
                X, Y = T(p["x"], p["y"] + p["tam"] * p["interlineado"] * i)
                x = X - total / 2.0 if p["anclaje"] == "middle" else X
                for w, ancho in zip(palabras, anchos):
                    momento = (p["momentos"][indice][0]
                               if indice < len(p["momentos"]) else 0.0)
                    indice += 1
                    alfa = 1.0
                    if animado:
                        alfa = min(1.0, max(0.0, (t - momento) / 0.14))
                    if alfa > 0.01:
                        sellar(lambda d, x=x, Y=Y, w=w, fuente=fuente,
                               rgb=rgb: d.text((x, Y), w, font=fuente,
                                               fill=rgb, anchor="ls"), alfa)
                    x += ancho + hueco
        elif tipo == "regla":
            vertical = p["alto"] > p["ancho"]
            if animado:
                fraccion = min(1.0, max(0.0, (t - p["t"]) / p["dur"]))
            else:
                fraccion = 1.0
            cuanto = _suave(fraccion)
            rgb = _color_de(p["color"])

            def dibuja(d, p=p, cuanto=cuanto, vertical=vertical, rgb=rgb):
                X, Y = T(p["x"], p["y"])
                if vertical:
                    alto = p["alto"] * sy * cuanto
                    d.rectangle([X, Y, X + p["ancho"] * sx, Y + alto],
                                fill=rgb)
                else:
                    ancho = p["ancho"] * sx * cuanto
                    d.rectangle([X, Y, X + ancho, Y + p["alto"] * sy],
                                fill=rgb)
            sellar(dibuja, p["opacidad"])
        elif tipo == "cursor":
            if not animado or t > p["t1"] or t < p["t0"]:
                continue
            ciclo = (t - p["t0"]) % 0.7
            alfa = min(ciclo / 0.233, (0.7 - ciclo) / 0.233)
            alfa = max(0.0, min(1.0, alfa))
            if alfa <= 0.01:
                continue
            X, Y = T(p["x"], p["y"])

            def dibuja(d, X=X, Y=Y, p=p, rgb=_color_de(p["color"]),
                       sy=sy, sx=sx):
                ancho = max(8, p["alto"] * 0.5)
                d.rectangle([X, Y - p["alto"] * sy, X + ancho * sx, Y],
                            fill=rgb)
            sellar(dibuja, alfa)
        elif tipo == "icono":
            tam_px = int(round(p["tam"] * sy))
            sprite = _icono_pil(p["nombre"], tam_px)
            alfa = p["opacidad"]
            if animado and p["t"] is not None:
                dur = p["entra_dur"] or 0.3
                alfa *= min(1.0, max(0.0, (t - p["t"]) / dur))
            if alfa <= 0.01:
                continue
            X, Y = T(p["x"], p["y"])
            lienzo.alpha_composite(_tinte(sprite, _color_de(p["color"]),
                                          alfa),
                                   (int(round(X - tam_px / 2)) - 4,
                                    int(round(Y - tam_px / 2)) - 4))
        elif tipo == "circulo":
            alfa = 1.0
            if animado and p["t"] is not None:
                alfa = min(1.0, max(0.0, (t - p["t"]) / 0.22))
            if alfa <= 0.01:
                continue
            X, Y = T(p["cx"], p["cy"])
            r = p["r"] * sy
            rgb = _color_de(p["color"])

            def dibuja(d, X=X, Y=Y, r=r, rgb=rgb):
                d.ellipse([X - r, Y - r, X + r, Y + r], fill=rgb)
            sellar(dibuja, alfa)

    final = Image.alpha_composite(lienzo, tinta)
    if zoom:
        de, hasta = float(zoom[0]), float(zoom[1])
        escala = de + (hasta - de) * min(1.0, max(0.0, t / max(0.1, duracion)))
        if abs(escala - 1.0) > 1e-3 and escala > 0.05:
            recorte = (max(8, int(round(W / escala))),
                       max(8, int(round(H / escala))))
            x, y = (W - recorte[0]) // 2, (H - recorte[1]) // 2
            final = final.crop((x, y, x + recorte[0], y + recorte[1])) \
                .resize((W, H), Image.LANCZOS)
    return final.convert("RGB")


def secuencia(carpeta, ficha, duracion, fps=30, paleta=None, diseno=None,
              semilla=0, tiempos=None, base=None, tamano=None,
              zoom=None) -> int:
    """La cartela entera, fotograma a fotograma, en `carpeta`.

    Escribe `f00000.png`, `f00001.png`… (uno por tick de `fps`) y
    devuelve cuántos: es lo que el render alimenta a ffmpeg con
    `-framerate {fps} -i f%05d.png`. El último fotograma se mantiene
    hasta el final del plano, que es lo que dura la cola de lectura.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    cuantos = max(2, int(round(float(duracion) * fps)) + 1)
    for i in range(cuantos):
        img = fotograma(ficha, i / float(fps), paleta=paleta, diseno=diseno,
                        duracion=duracion, semilla=semilla, tiempos=tiempos,
                        base=base, tamano=tamano, zoom=zoom)
        img.save(carpeta / f"f{i:05d}.png")
    return cuantos


def png_carta(ficha, paleta=None, diseno=None, duracion=4.0, semilla=0,
              base=None, tamano=None):
    """La cartela quieta y TODO escrita, como PNG (la rejilla, el repaso)."""
    return fotograma(ficha, 0.0, paleta=paleta, diseno=diseno,
                     duracion=duracion, semilla=semilla, base=base,
                     tamano=tamano, animado=False)


# --------------------------------------------------------------- validación

def _ajustar_al_presupuesto(ficha, datos, params, avisos):
    """Suelta los campos OPCIONALES hasta que la cartela quepa. Avisa.

    Es lo único que fuerza de verdad, y está acotado a propósito:

    SUELTA lo que la plantilla declara opcional, del último al primero
    — que es el orden en que pierde importancia: la nota al pie antes
    que la etiqueta, el antetítulo antes que el titular—. Soltar un
    campo entero es una pérdida limpia; el lector no se entera de que
    faltaba.

    NO TOCA lo obligatorio ni las listas. Recortar una frase por la
    mitad deja una cartela rota, que es peor que una larga, y quitar
    una línea de una enumeración cambia lo que el vídeo cuenta. Si
    después de soltar lo opcional sigue sin caber, eso solo se arregla
    reescribiéndola: se dice con el número delante y ahí acaba el
    trabajo del motor.

    Y NO SE VUELVE A LLAMAR AL AGENTE. Reintentar en bucle hasta que
    quepa ralentiza la producción por algo que pasa pocas veces; lo que
    tiene que salir bien por norma general es el ritmo, no cada plano.
    """
    datos = dict(datos or {})
    techo, caben = techo_de(params), palabras_maximas(params)
    if _cuentapalabras(datos) <= caben:
        return datos, avisos
    # del último al primero: los campos van en el orden en que se
    # dibujan, y lo que se dibuja al final es lo que menos pesa
    opcionales = [c for c, (obligatorio, _) in ficha["campos"].items()
                  if not obligatorio and c not in CAMPOS_SIN_TEXTO
                  and c != (ficha.get("lista") or [None])[0]]
    soltados = []
    for campo in reversed(opcionales):
        if _cuentapalabras(datos) <= caben:
            break
        if str(datos.get(campo) or "").strip():
            soltados.append(campo)
            datos[campo] = ""
    if soltados:
        avisos.append(
            f"se quita {', '.join(soltados)} para que quepa en los "
            f"{techo:.0f} s que puede estar puesta")
    total = _cuentapalabras(datos)
    if total > caben:
        avisos.append(
            f"{total} palabras: no se pueden leer en los {techo:.0f} s que "
            f"como mucho está puesta una cartela en este vídeo (caben "
            f"{caben}) — acórtala a mano")
    return datos, avisos


def validar(plantilla, datos, params=None):
    """Recorta y limpia los datos de una cartela. -> (datos, avisos)

    Se valida ANTES de dibujar y no al dibujar: así el aviso llega a la
    pantalla con nombre y apellidos («S013: 'texto' recortado a 95») en
    vez de aparecer como una cartela con la letra rara que nadie sabe
    por qué salió así.

    EL PRESUPUESTO DE PALABRAS SE AVISA, NO SE RECORTA. El tope de
    caracteres de cada campo sí recorta —ahí lo que se corta es un
    desbordamiento—, pero una cartela de veinte palabras no se arregla
    cortándola por la mitad: se arregla escribiendo otra cosa.
    """
    ficha = plantilla_de(plantilla)
    campos, avisos, salida = ficha["campos"], [], {}
    lista = ficha.get("lista")
    datos, avisos = _ajustar_al_presupuesto(ficha, datos, params, avisos)
    for campo, (obligatorio, tope) in campos.items():
        crudo = (datos or {}).get(campo)
        if lista and campo == lista[0]:
            valores = [str(v).strip() for v in (crudo or [])
                       if str(v).strip()]
            if len(valores) > lista[2]:
                avisos.append(f"'{campo}': {len(valores)} elementos, se "
                              f"quedan {lista[2]}")
                valores = valores[:lista[2]]
            if len(valores) < lista[1]:
                if obligatorio:
                    return None, [f"'{campo}' necesita al menos {lista[1]} "
                                  "elementos"]
                continue
            recortados = []
            for valor in valores:
                if len(valor) > tope:
                    avisos.append(f"'{campo}': un elemento recortado a "
                                  f"{tope}")
                    valor = valor[:tope].rstrip()
                recortados.append(valor)
            salida[campo] = recortados
            continue
        texto = str(crudo or "").strip()
        if campo == "icono":
            # el icono es una LISTA CERRADA, no un texto: uno inventado
            # no se puede dibujar, y dejarlo pasar dejaría la cartela
            # sin él sin decir por qué
            if texto and texto not in ICONOS:
                avisos.append(f"icono desconocido '{texto}', la cartela va "
                              "sin él")
                texto = ""
            if texto:
                salida[campo] = texto
            continue
        if not texto:
            if obligatorio:
                return None, [f"falta '{campo}', que es obligatorio en "
                              f"'{plantilla}'"]
            continue
        if len(texto) > tope:
            avisos.append(f"'{campo}' recortado a {tope} caracteres")
            texto = texto[:tope].rstrip()
        salida[campo] = texto
    return salida, avisos


def repartir(escenas, plan_bruto, avisar_tope=True, ocupacion=None):
    """Aplica el plan del agente respetando el suelo y el techo.

    El agente decide SIN CUOTA (cartela solo cuando el tramo la
    merece), pero sin suelo de separación un guion con cuatro cifras
    seguidas encadena cuatro pantallas de texto — y sin techo, un guion
    de frases redondas convierte el vídeo en una presentación. Las dos
    reglas se aplican aquí, en orden de vídeo, y lo descartado se dice.

    `ocupacion` ({sid: (desde, hasta)}, de `ocupacion_de`) dice qué
    cartelas ocupan más de un plano porque sus palabras se dicen a
    caballo de dos: las dos reglas cuentan PLANOS y no cartelas.
    """
    plan = {k: v for k, v in (plan_bruto or {}).items() if v}
    ocupacion = ocupacion or {}
    puestas, avisos, ultima, ocupados = {}, [], -10 ** 9, 0
    tope = max(1, int(len(escenas) * FRACCION_MAXIMA)) if escenas else 0
    for indice, escena in enumerate(escenas or []):
        sid = escena.get("id")
        ficha = plan.get(sid)
        if not ficha:
            continue
        desde, hasta = ocupacion.get(sid) or (indice, indice)
        # El techo cuenta los planos que la cartela OCUPA, no las
        # cartelas: mide cuánto rato del vídeo tiene texto encima.
        cuantos = max(1, hasta - desde + 1)
        if desde - ultima < SEPARACION_MINIMA:
            avisos.append(f"{sid}: descartada, a menos de {SEPARACION_MINIMA} "
                          "planos de la anterior")
            continue
        if ocupados + cuantos > tope:
            if avisar_tope:
                avisos.append(f"{sid}: descartada, ya hay {ocupados} planos "
                              f"de cartela ({int(FRACCION_MAXIMA * 100)}% de "
                              "los planos es el techo)")
            continue
        puestas[sid] = ficha
        ultima, ocupados = hasta, ocupados + cuantos
    return puestas, avisos


# ------------------------------------------------------------- el agente

INSTRUCCION = """Eres el grafista de un video de animacion narrada. Decides que
tramos de la narracion se cuentan MEJOR con una cartela que con un dibujo.

Una cartela es texto que se escribe palabra a palabra ENCIMA de la imagen del
plano, que se oscurece para poder leerlo. El sitio se sigue viendo detras, asi
que el montaje no se para: por eso NO tienes que elegir fondo -- todas van sobre
la imagen -- y por eso una cartela no "gasta" un plano, lo remata.

Lo que si decides es DONDE va y QUE pone.

TITULO: {titulo}

===========================================================================
EL IDIOMA DEL VIDEO ES: {idioma}
===========================================================================
TODO lo que escribas -- cada campo de cada cartela -- va en {idioma} y en
ningun otro idioma. Estas instrucciones estan en castellano porque son para ti,
no para el video: no las tomes como el idioma de salida. La narracion que ves
abajo esta en {idioma} y es la que manda.

Y escribelo BIEN escrito en ese idioma: con sus tildes, sus enyes, sus signos
de apertura y su puntuacion. El dibujado pone el texto en caja alta, y una
tilde escrita se conserva.
===========================================================================

LAS PLANTILLAS QUE PUEDES USAR
{catalogo}

LOS ICONOS, cuando la plantilla admite uno (campo "icono", siempre opcional):
{iconos}
Un icono solo si de verdad dice algo del texto -- un candado abierto para una
contrasena que no protegia, una base de datos para un recuento de cuentas --.
Ninguno si no lo hay: un icono decorativo distrae de lo que hay que leer.

COMO SE ELIGE
- La cartela NO ilustra: REMATA. Se pone donde el dibujo diria menos que el
  texto -- una cifra, una cita literal, una frase que cierra un tramo, una
  enumeracion, una palabra que hay que definir.
- NO hay cuota. Si el guion no pide ninguna, devuelve la lista vacia: es una
  respuesta correcta. Un video de treinta planos rara vez pide mas de tres o
  cuatro cartelas.
- Nunca dos seguidas ni casi seguidas: entre dos cartelas tiene que haber al
  menos {separacion} planos. Si dudas entre dos vecinas, elige la mejor.
- El texto de la cartela NO repite la narracion palabra por palabra: la
  DESTILA. Lo que se lee y lo que se oye a la vez tiene que sumar, no competir.
  La excepcion es 'cita', donde el texto SI es lo que se dijo.
- CORTO, y esto es lo que mas se incumple. El tope de caracteres de cada campo
  es un LIMITE, no un objetivo: apuntar a el produce cartelas de tres renglones
  que se leen como un parrafo y tapan el plano.

  Y NO ES UN CONSEJO: cada plano de la lista de abajo trae escrito CUANTAS
  PALABRAS CABEN en el, calculado con su duracion real (lo que tarda en
  escribirse mas lo que tiene que quedarse puesta para poder leerse). Ese
  numero manda sobre todo lo demas. Si lo que quieres decir no cabe en su
  plano, la respuesta NO es escribirlo igual: es decirlo mas corto, o poner la
  cartela en otro plano que dure mas, o no ponerla. Una cartela que no se puede
  leer es peor que ninguna -- tapa el plano y no aporta.

  EL LIMITE DURO son {palabras_maximas} PALABRAS EN TODA LA CARTELA, sumando
  todos sus campos. Sale de que ninguna cartela esta en pantalla mas de
  {segundos_maximos} segundos: si su plano es corto puede quedarse un poco mas
  sobre los siguientes de SU MISMO tramo del guion, pero ahi se acaba -- mas
  tiempo seria el montaje parado. Pasarse de esas palabras no alarga la cartela,
  la deja sin poder leerse.

  El presupuesto por campo, en PALABRAS:
      titular o tesis     4 a 7 palabras. Ocho ya es una frase larga.
      pie de una cifra    3 a 6 palabras
      nota al pie         hasta 8, y muchas veces sobra: dejala vacia
      linea de una lista  3 a 6 palabras cada una

  Una cartela se lee en el tiempo que dura un plano y compitiendo con la voz.
  Si no cabe en un vistazo, no es una cartela: es un parrafo sobre negro.
  Quita adjetivos, quita subordinadas, quita el verbo si se entiende sin el.
  Escribe la mitad de lo que te pida el cuerpo y quedara el doble de bien.

- MEJOR LAS PALABRAS QUE YA SE OYEN. La cartela se ESCRIBE palabra a palabra
  al ritmo al que el narrador las dice: cada palabra de la cartela que aparezca
  en la narracion de su plano entra EXACTAMENTE cuando se pronuncia. Asi que la
  version que mejor funciona casi siempre es la frase corta que el propio
  narrador dice en ese tramo, recortada a su nucleo. Leer justo lo que se esta
  oyendo, escribiendose, es lo que hace que el plano remate; leer otra cosa
  parecida obliga a atender a dos textos. Cuando el tramo tenga una frase que ya
  sea el golpe, usala tal cual.
- Y EN EL MISMO ORDEN EN QUE SE OYEN. Esto es tan importante como elegirlas.
  La cartela se escribe de izquierda a derecha al ritmo de la voz, asi que cada
  palabra entra cuando se dice: si las pones en otro orden que el narrador,
  NINGUNA sincronia puede salir bien y el texto entra a destiempo. Quita todo lo
  que quieras --sobra casi todo-- pero lo que dejes tiene que ir en el orden en
  que se oye.

  El narrador dice «...y se abrio la puerta». Escribe «LA PUERTA SE ABRIO», no
  «SE ABRIO LA PUERTA»: las mismas tres palabras, y solo una de las dos se puede
  sincronizar.

  Vale igual para los CONCEPTOS aunque cambies las palabras: lo que pongas
  primero tiene que ser lo que se oye primero. Y vale entre CAMPOS de la misma
  cartela: se dibujan en el orden en que la plantilla los coloca, asi que el
  campo de arriba tiene que decir lo que se oye antes.

- Y PONLA EN EL PLANO DONDE SE DICE, no en el siguiente. Este es el error que
  mas se ha visto: la cifra se menciona en un plano y la cartela se pone en el
  de despues, asi que el espectador lee en pantalla algo que ya ha oido hace
  cuatro segundos y la cartela llega tarde a su propio golpe. Si lo que quieres
  rotular se dice a caballo entre dos planos, elige AQUEL EN EL QUE EMPIEZA.
- Las cifras, tal y como quieras que se lean. Si una cifra larga cabe mejor
  abreviada ("30M" en vez de "30.000.000"), escribela ya abreviada. Destilar
  asi es lo que se quiere: el motor sabe sincronizar un texto destilado, asi
  que no alargues la cartela para parecerte mas al audio. Lo que el motor NO
  puede hacer es reordenarla: recorta cuanto quieras, pero en el orden de la
  voz (ver la vineta del orden, mas arriba).
- Sin punto final, salvo que sean varias frases. Sin comillas en 'cita': las
  pone el dibujo.
- 'capitulo' solo en el PRIMER plano de un capitulo, y solo si el plano trae
  capitulo marcado.

PLANOS. Cada uno con su duracion y lo que se narra en el:
{planos}

DEVUELVE ESTE JSON:

{{
  "cartelas": {{
    "<id de plano>": {{
      "plantilla": "<una de las de arriba>",
      "datos": {{ "<campo>": "<valor>", ... }},
      "por_que": "<en pocas palabras, por que este tramo pide cartela"
    }}
  }}
}}

Solo los planos que lleven cartela. Los demas no se nombran.
"""


def _catalogo_para_el_agente(activas=None):
    lineas = []
    for pid in plantillas_elegibles():
        ficha = PLANTILLAS[pid]
        if activas and pid not in activas:
            continue
        campos = ", ".join(
            f"{c}{'' if v[0] else ' (opcional)'} [max {v[1]} caracteres]"
            for c, v in ficha["campos"].items())
        lista = ficha.get("lista")
        if lista:
            campos += (f" -- '{lista[0]}' es una LISTA de {lista[1]} a "
                       f"{lista[2]}")
        lineas.append(f"- {pid}: {ficha['descripcion']}\n"
                      f"    cuando: {ficha['cuando']}\n"
                      f"    campos: {campos}")
    return "\n".join(lineas)


def _planos_legibles(escenas):
    """Los planos para el agente: cuánto duran, QUÉ CABE, y qué dicen.

    El presupuesto de palabras ya estaba en la instrucción, pero como
    regla general. Una regla general contra un plano concreto de 2,5 s
    no dice nada, y por eso salió una definición de trece palabras en
    uno de 2,5. Aquí se tocan: cada plano lleva SU número, calculado
    con la misma cuenta que después decide si la cartela cabe. Pasarse
    ya no es ignorar un consejo, es contradecir un dato que tiene
    delante.
    """
    lineas = []
    for escena in escenas:
        marca = (f" [empieza capitulo: {escena['capitulo']}]"
                 if escena.get("capitulo") else "")
        duracion = float(escena.get("duracion") or 0)
        lineas.append(
            f"[{escena.get('id')}] {duracion:.1f}s · caben "
            f"{palabras_que_caben(duracion)} palabras{marca}\n"
            f"    {str(escena.get('narracion') or '').strip()}")
    return "\n".join(lineas)


def _limpiar(datos, ids, activas=None, params=None):
    """Valida la propuesta contra las plantillas REALES y sus topes."""
    salida, avisos = {}, []
    crudo = datos.get("cartelas") if isinstance(datos, dict) else None
    crudo = crudo if isinstance(crudo, dict) else {}
    for sid, ficha in crudo.items():
        sid = str(sid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        if not isinstance(ficha, dict):
            continue
        plantilla = str(ficha.get("plantilla") or "").strip()
        if plantilla not in PLANTILLAS:
            avisos.append(f"{sid}: plantilla desconocida '{plantilla}', "
                          "se ignora")
            continue
        if activas and plantilla not in activas:
            avisos.append(f"{sid}: '{plantilla}' está apagada en este vídeo")
            continue
        limpios, mas = validar(plantilla, ficha.get("datos"), params)
        if limpios is None:
            avisos.extend(f"{sid}: {m}" for m in mas)
            continue
        avisos.extend(f"{sid}: {m}" for m in mas)
        salida[sid] = {"plantilla": plantilla, "fondo": fondo_de(ficha),
                       "datos": limpios,
                       "por_que": str(ficha.get("por_que") or "").strip()}
    return salida, avisos


def avisos_de_orden(plan, escenas, idioma=None):
    """Las cartelas que van en otro orden que la voz. -> [aviso]

    Se mira DESPUÉS de repartir y contra la VENTANA de tres planos que
    usa el anclaje. Se AVISA y ya: ni se reescribe el texto, ni se
    reordena, ni se vuelve a llamar al agente, ni se descarta la
    cartela — la misma doctrina que el presupuesto de palabras («se
    avisa, no se recorta»): una cartela en otro orden no se arregla
    permutando sus palabras, se arregla escribiendo otra cosa.
    """
    avisos = []
    por_id = {e.get("id"): i for i, e in enumerate(escenas or [])
              if e.get("id")}
    for sid, ficha in (plan or {}).items():
        indice = por_id.get(sid)
        if indice is None:
            continue
        narracion = (escenas[indice] or {}).get("narracion") or ""
        if not narracion:
            continue
        sueltas = fuera_de_orden(palabras_dibujadas(ficha), narracion, idioma)
        for palabra, anterior in sueltas:
            # Con `anterior` se puede decir CONTRA QUÉ está desordenada,
            # que es lo que hace el aviso accionable. Sin ella se dice lo
            # que se sabe y nada más: inventar una referencia sería peor.
            donde = (f"se dice ANTES que «{anterior}»" if anterior
                     else "se dice en otro momento del plano")
            avisos.append(
                f"{sid}: «{palabra}» {donde}, así que la cartela va en otro "
                f"orden que la voz y esa palabra entra a destiempo. "
                f"Escríbela en el orden en que se oye.")
    return avisos


def params_defecto() -> dict:
    return {}


def plan_de(params_assets: dict) -> dict:
    """Las cartelas guardadas, POR UNIDAD: {"S003": {plantilla, datos}}.

    Vive en `params.unidades[escena].cartela` porque todo lo que no es
    ese bloque entra en la firma global del paso: convertir S003 en
    cartela ensucia S003 y nada más.
    """
    bloque = (params_assets or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        ficha = (datos or {}).get("cartela") if isinstance(datos, dict) \
            else None
        if isinstance(ficha, dict) and ficha.get("plantilla"):
            plan[str(uid)] = ficha
    return plan


def proponer(proyecto: Proyecto, params: dict, trabajo,
             plantillas=None) -> dict:
    """Lee el guion y decide qué tramos se cuentan mejor como cartela.

    Proponer no es aprobar: lo que devuelve se repasa y se guarda con
    PUT /cartelas (o se aplica desde la receta). No necesita ver ninguna
    imagen — decide con el GUION delante, y por eso puede correr antes
    de generar los planos, que es justo lo que evita pagar una imagen
    para un plano que va a ser una cartela.

    ``plantillas`` es la allowlist que decide el usuario (vive en los
    params de rótulos); si nadie la pasó se mira en ``params``.
    """
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    duraciones = {v.get("id"): v.get("duracion")
                  for v in (voz or {}).get("escenas", [])}
    legibles = [{"id": e["id"],
                 "duracion": float(duraciones.get(e["id"], 0) or 0),
                 "narracion": str(e.get("narracion", ""))}
                for e in escenas]
    # EL IDIOMA VA EXPLÍCITO (regla del original): sin decírselo, el
    # agente escribe las cartelas en el idioma de su propio ejemplo.
    idioma = {"es": "español", "en": "inglés"}.get(
        str(proyecto.leer().get("idioma", "es")).lower(), "español")
    titulo = str(proyecto.leer().get("nombre") or proyecto.id)
    ids = {e["id"] for e in legibles}

    trabajo.avance(f"leyendo los {len(legibles)} planos para decidir "
                   "las cartelas")
    llamada = llm.rol_config("cartelas", comun.ajustes_llm())
    llamada.sistema = ("Decides qué tramos de un vídeo narrado se "
                       "cuentan mejor con una cartela de texto que con "
                       "un dibujo.")
    # QUÉ PLANTILLAS puede usar viene de fuera (vive en los params de
    # rótulos, con el resto del grafismo): limitan el catálogo del
    # prompt Y el saneado posterior, como en el original, que la pasaba
    # explícita aparte del saco de assets (de ahí sale palabras_maximas).
    if plantillas is None:
        plantillas = params.get("plantillas_cartela") or []
    activas = set(plantillas) or None
    llamada.instruccion = INSTRUCCION.format(
        palabras_maximas=palabras_maximas(params),
        segundos_maximos=round(techo_de(params)),
        titulo=titulo, idioma=idioma,
        catalogo=_catalogo_para_el_agente(activas),
        iconos=", ".join(sorted(ICONOS)),
        separacion=SEPARACION_MINIMA,
        planos=_planos_legibles(legibles))
    llamada.contexto = "cartelas"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    bruto, avisos = _limpiar(crudo, ids, activas, params)
    # UNA llamada con TODOS los planos delante: las reglas del reparto
    # (separación y techo) se miden sobre el vídeo ENTERO, y con tandas
    # la segunda no veía lo que había decidido la primera.
    plan, mas = repartir(legibles, bruto)
    avisos.extend(mas)
    # EL ORDEN, comprobado en código y no solo pedido en el prompt: lo
    # que se pide en un prompt se cumple casi siempre; «casi» es justo
    # lo que hace falta comprobar, y este fallo no se ve hasta tener el
    # vídeo montado.
    avisos.extend(avisos_de_orden(plan, legibles, idioma))
    trabajo.avance(f"{len(plan)} de {len(legibles)} planos serían cartela")
    return {"plan": plan, "avisos": avisos,
            "planos": len(legibles), "cartelas": len(plan),
            "max_cartelas": max(1, int(len(legibles) * FRACCION_MAXIMA))}
