"""Guía de estilo ESCRITA del proyecto: la biblia con números.

Réplica del camino «estilo descrito» del original (`pasos/estilo.py`,
`guia_de_descripcion`): esta réplica no baja vídeos de YouTube, así que
la guía nace de las palabras del canal — el estilo gráfico declarado en
Configuración y lo que el proyecto pida encima — y no de fotogramas.

Por qué una guía aparte del campo `estilo`: el texto libre dice
«estilo cómic europeo» y el generador pone lo que pone por defecto en
cada hueco — manos realistas, piel con degradado, sombra proyectada.
La guía CONVERTI la intención en decisiones contables: cuántos píxeles
de contorno, cuántos dedos, cuántos tonos por superficie. Un número se
puede obedecer; «estilizado» no.

La ficha que sale aquí la leen: el prompt de cada plano (p6), el
grafismo (la paleta) y la pantalla (el resumen). 'peticion' es la
corrección de ESTA pasada («más contraste») y va la última y con
precedencia dicha, así que gana si choca.
"""
from __future__ import annotations

import re

from ..nucleo.proyecto import Proyecto
from . import comun
from ..motores import llm

PASO = "guia_estilo"

SISTEMA = """Eres director de arte. Te dan en palabras el estilo visual que \
quiere un canal y escribes la guía de estilo que permite dibujar sus planos.

LO QUE HAY QUE HACER CON ESO
Convertir la intención en decisiones de dibujo. Donde el canal dijo
"estilo cómic europeo" tú tienes que decir cuántos píxeles de
contorno, de qué color y con cuántos tonos por superficie.

Todo lo que el canal no haya dicho lo eliges TÚ, coherente con lo que
sí dijo. No dejes huecos: esta guía va a ser la única descripción del
dibujo, y lo que no fije lo pondrá el generador por su cuenta.

CÓMO SE MIRA
La lee un generador de imágenes que, en todo lo que no fijes, pone lo
que pone por defecto: manos realistas de cinco dedos, piel con
degradado, sombra proyectada, ojos con brillo. CADA HUECO QUE DEJES
sale dibujado como no toca. Por eso:
- CUENTA. Números, no adjetivos: cuántos dedos, cuántos tonos de piel,
  cuántos píxeles de contorno, cuántas cabezas de altura.
- Di lo que NO hay tanto como lo que hay: que no haya nariz, que no
  haya sombra, son decisiones de estilo igual de fuertes.
- No nombres series, estudios ni autores: describe el DIBUJO con sus
  números. Un nombre propio en un prompt de imagen es una lotería.
- No te salgas de lo pedido: si el canal dijo "blanco y negro", la
  paleta es de grises.

Decide con números: el trazo (grosor, color, uniforme o modulado, si
lo llevan los fondos), el relleno (plano o degradado, textura,
sombreado), la paleta (10-16 hex, ordenados por superficie, bases y
acentos), los personajes (cabezas de altura, cabeza, cuerpo, pelo,
ropa), LAS MANOS aparte (número de dedos con cifra, color, contorno,
tamaño relativo; es lo segundo que más canta cuando falla), LA CARA
aparte (con qué se rellena la piel, ojos, cejas, nariz, boca; es lo
primero), los fondos (detalle y profundidad), la luz (de dónde viene,
cómo se pintan las sombras, contraste), la composición (aire,
horizonte) y el acabado (grano, limpieza).

Devuelve SOLO JSON:
{"guia": "<el párrafo que se pega DENTRO del prompt de imagen. En
INGLÉS, en imperativo, sin mencionar referencias ni nombres ajenos.
Entre 260 y 400 palabras: trazo, relleno, paleta, construcción del
personaje, cara, manos, fondo, luz y acabado, cada uno con su número.",
 "paleta": ["#rrggbb", "... de diez a dieciséis, dominantes primero"],
 "trazo": "...", "relleno": "...", "personajes": "...", "caras": "...",
 "manos": "...", "fondos": "...", "luz": "...", "composicion": "...",
 "acabado": "...",
 "evitar": "frases en INGLES con lo que NO debe aparecer nunca, en
negativo y concreto, empezando por lo que el generador pone por defecto
y en ESTE estilo lo rompe. LAS MANOS van primeras si no son de cinco
dedos anatómicos.",
 "resumen_es": "<una línea en castellano para reconocer el estilo en un
desplegable>"}"""

#: campos de texto que se guardan tal cual (recortados)
CAMPOS = ("trazo", "relleno", "personajes", "caras", "manos", "fondos",
          "luz", "composicion", "acabado", "evitar", "resumen_es")


def guia_de(params_assets: dict) -> dict:
    """La guía guardada en params de assets (o {})."""
    ficha = (params_assets or {}).get("guia")
    return ficha if isinstance(ficha, dict) else {}


def proponer(proyecto: Proyecto, params: dict, trabajo,
             descripcion: str = "", peticion: str = "") -> dict:
    """Escribe la guía a partir de la descripción del estilo. -> ficha.

    'descripcion' es lo que se pide AHORA (si viene vacía se usa el
    estilo del canal + el estilo del proyecto); 'peticion' es la
    corrección de ESTA pasada y manda al final.
    """
    base = " ".join(str(descripcion or "").split())
    if not base:
        base = " ".join(str((params or {}).get("estilo", "")).split())
    if len(base) < 8:
        raise ValueError("para escribir la guía hace falta material: "
                         "describe el estilo gráfico con algo más de detalle "
                         "(con dos palabras se lo inventa todo)")

    encargo = [f'LO QUE HA PEDIDO EL CANAL, tal cual lo escribió:\n"{base}"']
    peticion = " ".join(str(peticion or "").split())
    if peticion:
        encargo.append(f'\nCORRECCIÓN DE ESTA PASADA, que manda sobre lo de '
                       f'arriba si chocan:\n"{peticion}"')
    encargo.append(f"\nIdioma del vídeo: {proyecto.idioma or 'es'}.")

    trabajo.avance("escribiendo la guía de estilo con números")
    llamada = llm.rol_config("guia_estilo", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = "\n".join(encargo)
    llamada.contexto = "guia_estilo"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())
    if not isinstance(crudo, dict):
        raise ValueError("la respuesta no es la ficha de guía esperada")

    guia = " ".join(str(crudo.get("guia") or "").split())
    if not guia:
        raise ValueError("el modelo no ha devuelto ninguna guía de estilo")
    ficha = {"guia": guia}
    for campo in CAMPOS:
        ficha[campo] = " ".join(str(crudo.get(campo) or "").split())
    paleta = []
    for color in (crudo.get("paleta") or []):
        texto = str(color).strip().lower()
        if _hex(texto):
            paleta.append(texto)
        if len(paleta) >= 16:
            break
    ficha["paleta"] = paleta
    ficha["descripcion"] = base
    ficha["peticion"] = peticion
    trabajo.avance(f"guía escrita: {len(guia.split())} palabras, "
                   f"{len(paleta)} colores")
    return {"guia": ficha, "palabras": len(guia.split()),
            "colores": len(paleta)}


def _hex(texto: str) -> bool:
    return bool(re.match(r"^#[0-9a-f]{6}$", texto))


#: El bloque de estilo que viaja en el prompt de cada plano. La guía
#: ENTERA si existe (es la biblia); si no, el texto libre de siempre.
def bloque_de_estilo(params_assets: dict) -> str:
    ficha = guia_de(params_assets)
    if ficha.get("guia"):
        partes = [f"Style guide (obey every number): {ficha['guia']}"]
        if ficha.get("evitar"):
            partes.append(f"Never: {ficha['evitar']}")
        return "\n".join(partes)
    return " ".join(str((params_assets or {}).get("estilo", "")).split())
