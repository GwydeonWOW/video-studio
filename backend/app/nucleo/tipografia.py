"""Medir texto con la fuente de verdad, y partirlo para que quepa.

Puerto del `tipografia.py` del original: aquí no hay ninguna decisión
de diseño, solo la cuenta. Qué letra y qué tamaño lleva cada cosa lo
deciden las plantillas de las cartelas (`pasos/cartelas.py`); lo que
hay aquí es el metro — medir con la MISMA fuente con la que se dibuja,
partir en líneas y bajar el tamaño hasta que el texto quepa en su caja.

Lo que hace que una cartela no pueda salir rota: la plantilla pide un
tamaño y este texto concreto se queda con el que de verdad entra. Sin
esto, una cifra de dos dígitos y una de siete se dibujan igual de
grandes y la segunda se sale del cuadro.

LAS FUENTES se resuelven por candidatos (como `p8_render.FUENTES`):
el render corre en el servidor (Linux con DejaVu) y se prueba en
Windows (Arial/Verdana). `ESTUDIO_FUENTES` apunta a una carpeta propia
si las de siempre no están. Medir con una fuente y dibujar con otra da
una cuenta bien y un número mal.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

#: Carpeta de fuentes propias (opcional): se mira ANTES que el sistema.
CARPETA_FUENTES = os.environ.get("ESTUDIO_FUENTES") or ""


#: Las familias: parejas (normal, negrita) en orden de preferencia. La
#: primera pareja cuya NORMAL exista es la que mide y la que dibuja (la
#: negrita cae a la normal si falta: mejor negrita fingida que otra letra).
_FAMILIAS = {
    "verdana": [("verdana.ttf", "verdanab.ttf"),
                ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
                ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
                ("arial.ttf", "arialbd.ttf")],
    "arial": [("arial.ttf", "arialbd.ttf"),
              ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
              ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")],
    "mono": [("consola.ttf", "consolab.ttf"),
             ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf")],
}

_resueltas: dict[str, tuple[str, str]] = {}
_fuentes: dict[tuple, ImageFont.FreeTypeFont] = {}


def _rutas_de(nombre_fichero: str) -> list[str]:
    """Dónde puede estar ese fichero: carpeta propia y luego el sistema."""
    salidas = []
    if CARPETA_FUENTES:
        salidas.append(str(Path(CARPETA_FUENTES) / nombre_fichero))
    salidas.extend(str(Path(base) / nombre_fichero) for base in (
        r"C:\Windows\Fonts",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/dejavu",
        "/System/Library/Fonts/Supplemental",
    ))
    return salidas


def _resolver(nombre: str) -> tuple[str, str]:
    """La pareja (normal, negrita) que existe de esa familia."""
    if nombre in _resueltas:
        return _resueltas[nombre]
    par = ("", "")
    for normal, negrita in (_FAMILIAS.get(nombre) or _FAMILIAS["verdana"]):
        ruta_normal = next((r for r in _rutas_de(normal)
                            if Path(r).is_file()), "")
        if not ruta_normal:
            continue
        ruta_negrita = next((r for r in _rutas_de(negrita)
                             if Path(r).is_file()), ruta_normal)
        par = (ruta_normal, ruta_negrita)
        break
    _resueltas[nombre] = par
    return par


def fuente(nombre: str, tam, negrita: bool = False) -> ImageFont.FreeTypeFont:
    """Fuente real del sistema, la MISMA con la que se rasteriza."""
    clave = (str(nombre).lower(), int(tam), bool(negrita))
    if clave not in _fuentes:
        normal, gruesa = _resolver(clave[0])
        ruta = gruesa if negrita else normal
        _fuentes[clave] = (ImageFont.truetype(ruta, int(tam)) if ruta
                           else ImageFont.load_default())
    return _fuentes[clave]


#: Lo que la medida se queda corta respecto a lo que dibuja un
#: navegador con el SVG de la vista (medido en el original: hasta un
#: 2,6 % corto). 4 % de margen cubre el peor caso con holgura.
MARGEN_MEDIDA = 1.04


def medir(texto, nombre, tam, negrita=False, espaciado=0) -> tuple[int, int]:
    """Ancho y alto en píxeles del texto, medidos con la fuente de verdad.

    Se mide el AVANCE (`getlength`) y no la caja de tinta: la caja
    acaba en el último píxel pintado y una «o» final pinta menos ancho
    del que ocupa — la caja salía corta y el texto se salía por la
    derecha. El espaciado se cuenta por cada letra, no por los huecos.
    """
    tipo = fuente(nombre, tam, negrita)
    try:
        avance = tipo.getlength(str(texto))
    except AttributeError:                 # Pillow antiguo
        caja = tipo.getbbox(str(texto))
        avance = caja[2] - caja[0]
    ancho = avance * MARGEN_MEDIDA + espaciado * len(str(texto))
    return int(round(ancho)), int(tam * 1.25)


def partir(texto, nombre, tam, negrita, espaciado, ancho_max) -> list[str]:
    """Parte el texto en líneas que quepan en `ancho_max`."""
    palabras = str(texto).split()
    lineas, actual = [], ""
    for palabra in palabras:
        prueba = (actual + " " + palabra).strip()
        if (medir(prueba, nombre, tam, negrita, espaciado)[0] <= ancho_max
                or not actual):
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def escapar(texto) -> str:
    """El texto, listo para meterlo dentro de un SVG."""
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def encajar(texto, nombre, tam, negrita, espaciado, ancho_max, alto_max,
            minimo=None, interlineado=1.25, lineas_max=None):
    """Baja el tamaño hasta que el texto quepa en la caja. -> (lineas, tam)

    SE COMPRUEBA EL ANCHO DE CADA LÍNEA, no solo el alto: un texto que
    no se puede partir («30.000.000», una palabra larga) deja a `partir`
    una sola línea igual de larga pase lo que pase, y sin mirar su
    ancho la cifra se salía por los dos lados del cuadro.

    `lineas_max` es el tope de renglones: un pie de cifra en cuatro
    líneas cabe de alto y se lee fatal. El suelo es el 45 % del tamaño
    pedido salvo que se diga otro — por debajo el rótulo deja de
    leerse a tamaño de vídeo.
    """
    texto = str(texto or "")
    suelo = int(minimo if minimo is not None else max(12, tam * 0.45))
    actual = max(int(tam), suelo)
    while True:
        lineas = partir(texto, nombre, actual, negrita, espaciado, ancho_max)
        cabe = (len(lineas) * int(actual * interlineado) <= alto_max
                and (lineas_max is None or len(lineas) <= lineas_max)
                and all(medir(linea, nombre, actual, negrita, espaciado)[0]
                        <= ancho_max for linea in lineas))
        if cabe or actual <= suelo:
            return lineas, actual
        actual = min(actual - 1, int(actual * 0.94))


def encajar_pocas_lineas(texto, nombre, tam, negrita, espaciado, ancho_max,
                         alto_max, lineas=(1, 2), minimo=None,
                         interlineado=1.25):
    """Como `encajar`, pero probando primero a meterlo en UNA línea.

    Un pie de cartela partido en dos se lee peor que el mismo pie una
    pizca más pequeño de un tirón; en tres, mal a secas. Se intenta con
    una línea bajando bastante el tamaño y solo si ahí no cabe se
    admite la segunda, con el suelo más alto.
    """
    for indice, tope in enumerate(lineas):
        suelo = int(minimo if minimo is not None
                    else max(14, tam * (0.52 if indice == 0 else 0.42)))
        hechas, usado = encajar(texto, nombre, tam, negrita, espaciado,
                                ancho_max, alto_max, minimo=suelo,
                                interlineado=interlineado, lineas_max=tope)
        if len(hechas) <= tope and usado > suelo:
            return hechas, usado
    return encajar(texto, nombre, tam, negrita, espaciado, ancho_max,
                   alto_max, minimo=minimo, interlineado=interlineado,
                   lineas_max=lineas[-1] if lineas else None)
