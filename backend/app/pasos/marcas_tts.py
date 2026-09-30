"""Anotaciones de voz: lo que el guion le dice al TTS y que no se locuta.

Para que
--------
Un guion bien puntuado ya se lee con un ritmo razonable, pero la puntuacion
no distingue entre dos puntos que significan cosas distintas. El punto que
cierra el gancho y el punto que separa dos frases del mismo parrafo se
escriben igual, y el sintetizador los locuta igual: media pausa. Resultado,
el gancho y la entrada del documental salen pegados y suena a que el locutor
no se ha enterado de que ha empezado otra cosa.

Aqui vive el vocabulario de etiquetas que el redactor puede meter en el
texto, y las dos operaciones que hacen falta para que ese texto conviva con
el resto del Estudio:

    limpiar(texto)   el texto tal y como se OYE, sin etiquetas. Es el que
                     cuenta palabras, el que se compara con el material de
                     partida y, sobre todo, el que reparte las marcas de
                     palabra entre escenas.
    sanear(texto)    el texto tal y como se MANDA al motor de voz: solo
                     etiquetas del vocabulario, en rango, y sin encadenar
                     dos silencios seguidos.

El vocabulario aqui es UNO: `<break>`. El original (Cartesia) admitia
speed, volume, emotion y spell; ElevenLabs NO las soporta, y una etiqueta
desconocida no da error: se LOCUTA en voz alta (o ensucia la alineacion),
asi que sanear() las BORRA todas menos `<break>`. Un aviso que nadie lee
acaba en un video que dice «menor que pausa».

Lo que se respeta del original (lecciones medidas alli)
-------------------------------------------------------
1. Las etiquetas de pausa NO salen en las marcas de palabra: el motor
   devuelve las palabras habladas y nada mas. El montaje entero se
   sincroniza con esas marcas, asi que esto es lo que hace viable la idea.
2. Una etiqueta DESCONOCIDA se locuta en voz alta: por eso sanear() borra y
   no avisa de lo que no reconoce.
3. Un silencio es ADITIVO sobre la pausa natural de la puntuacion, no
   absoluto.
4. Cada <break> parte la generacion: muchos convierten la toma continua en
   una lectura frase a frase (ver revisar_conjunto).
5. Un bloque que solo tiene etiquetas no es un bloque: no se locuta nada.

Formato de ElevenLabs
---------------------
ElevenLabs escribe los silencios en SEGUNDOS (`<break time="0.9s"/>`).
Aqui dentro se trabaja en milisegundos (como el original, y como los
params pausa_gancho_ms/pausa_seccion_ms), y `para_tts()` reescribe la
etiqueta al formato del motor justo antes de mandarla.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ vocabulario

#: Silencio, en milisegundos, que puede pedir una etiqueta <break>. Por
#: abajo, menos de 100 ms no se distingue de la pausa que ya deja la coma.
#: Por arriba, 2,5 s en una narracion en off ya no es una pausa: es un fallo
#: de reproduccion. (ElevenLabs admite hasta 3 s; nos quedamos mas cortos.)
BREAK_MIN_MS = 100
BREAK_MAX_MS = 2500

#: Cuantos silencios por escena son demasiados. La voz se graba en UNA toma
#: continua a proposito: frase a frase cada linea arranca en frio y el
#: corte se oye. Un <break> parte la generacion, asi que un guion con un
#: silencio en cada escena desanda esa decision sin decirlo y devuelve el
#: sonido de lista leida que se arreglo en su dia.
DENSIDAD_MAXIMA = 0.5

# ---------------------------------------------------------------- reconocedores

_BREAK = re.compile(r'<break\s+time="(\d+(?:\.\d+)?)\s*(ms|s)"\s*/>', re.I)

#: Cualquier cosa con forma de etiqueta, valida o no. Se usa para BORRAR lo
#: que no se reconozca, porque lo que no se reconoce se locuta (leccion 2).
_ALGO_ASI = re.compile(r'<[^<>]*>')


def _numero(texto, por_defecto=0.0):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return por_defecto


def _ms_de(valor, unidad):
    """('900', 'ms') -> 900.0; ('1.5', 's') -> 1500.0."""
    return valor if str(unidad).lower() != "s" else valor * 1000.0


def _formatear_ms(ms: float) -> str:
    return str(int(round(ms)))


# ------------------------------------------------------------------- limpiar

def limpiar(texto) -> str:
    """El texto tal y como se OYE: sin etiquetas y sin dobles espacios.

    Este es el texto con el que trabaja TODO lo que no sea la llamada al
    motor de voz. En particular el reparto de marcas de palabra entre
    escenas, que empareja lo que el guion dice con lo que el motor
    devolvio: como el motor no devuelve las etiquetas, dejarlas aqui
    meteria tokens que no existen y cada uno se comeria una palabra real,
    desplazando todos los cortes siguientes.
    """
    plano = _ALGO_ASI.sub(" ", str(texto or ""))
    # la etiqueta se comia el espacio que la separaba de la palabra siguiente
    return " ".join(plano.split())


def hay_marcas(texto) -> bool:
    """True si el texto lleva alguna anotacion de voz."""
    return bool(_ALGO_ASI.search(str(texto or "")))


def contar_palabras(texto) -> int:
    """Palabras que se locutan, sin contar las etiquetas."""
    return len(limpiar(texto).split())


# -------------------------------------------------------------------- sanear

def trocear(texto) -> list[tuple[str, object]]:
    """[(clase, pieza)] recorriendo el texto una vez.

    clase es 'texto', 'break' (pieza: milisegundos float) o 'basura'.
    """
    piezas, posicion = [], 0
    for encontrado in _ALGO_ASI.finditer(str(texto or "")):
        if encontrado.start() > posicion:
            piezas.append(("texto", texto[posicion:encontrado.start()]))
        posicion = encontrado.end()
        salto = _BREAK.fullmatch(encontrado.group(0))
        if salto:
            piezas.append(("break",
                           _ms_de(_numero(salto.group(1)), salto.group(2))))
        else:
            piezas.append(("basura", encontrado.group(0)))
    if posicion < len(str(texto or "")):
        piezas.append(("texto", str(texto)[posicion:]))
    return piezas


def sanear(texto, avisos=None) -> str:
    """El texto tal y como se MANDA al motor de voz.

    Deja solo `<break>` dentro de rango, sin encadenar dos silencios
    seguidos, y BORRA cualquier otra etiqueta (el original las admitia en
    Cartesia; ElevenLabs las locutaria en voz alta). Si 'avisos' es una
    lista, se le anade lo que se haya tenido que corregir.

    Es idempotente: sanear(sanear(x)) == sanear(x).
    """
    apunta = avisos.append if isinstance(avisos, list) else (lambda _: None)
    crudo = str(texto or "")
    if not crudo.strip():
        return ""

    salida = []
    ultimo_break = None  # indice en 'salida' del ultimo silencio, si va seguido
    for clase, pieza in trocear(crudo):
        if clase == "texto":
            if str(pieza).strip():
                ultimo_break = None
            salida.append(str(pieza))
        elif clase == "break":
            ms = float(pieza)
            if ms < BREAK_MIN_MS:
                apunta(f"silencio de {int(ms)} ms: por debajo de "
                       f"{BREAK_MIN_MS} ms no se distingue de la pausa que "
                       f"ya deja la puntuacion")
                continue
            if ms > BREAK_MAX_MS:
                apunta(f"silencio de {int(ms)} ms recortado a "
                       f"{BREAK_MAX_MS} ms: mas que eso en una narracion "
                       f"suena a fallo de reproduccion")
                ms = BREAK_MAX_MS
            if ultimo_break is not None:
                # dos silencios casi pegados es de lo poco que la
                # documentacion de los TTS desaconseja explicitamente
                previo = _BREAK.fullmatch(salida[ultimo_break])
                juntos = min(BREAK_MAX_MS,
                             _numero(previo.group(1)) + ms)
                salida[ultimo_break] = f'<break time="{_formatear_ms(juntos)}ms"/>'
                apunta("dos silencios seguidos fundidos en uno")
                continue
            salida.append(f'<break time="{_formatear_ms(ms)}ms"/>')
            ultimo_break = len(salida) - 1
        else:  # basura
            # No se avisa y ya: se BORRA. Una etiqueta que el motor no
            # reconoce la LOCUTA, y un video que dice «menor que pausa» es
            # mucho peor que un guion al que le falta un silencio.
            apunta(f"anotacion {pieza.strip()!r} fuera del vocabulario, "
                   f"quitada antes de que el locutor la lea en voz alta")

    final = "".join(salida).strip()
    # Un silencio al final de la escena SI vale, y es el caso principal: la
    # pausa entre el gancho y la entrada del documental es justo eso. No se
    # toca. Y no choca con el aire que mete la pista despues de sintetizar
    # (espaciar): aquel ensancha hasta un MINIMO midiendo la pausa real.
    #
    # una escena que solo tiene etiquetas no es una escena: no se locuta
    # nada, y dejar el silencio suelto seria colgarlo de la escena de al lado
    if not limpiar(final):
        return ""
    return final


# -------------------------------------------------------------------- revisar

def revisar(texto) -> list[str]:
    """Lo que habria que decirle a una persona sobre las anotaciones del
    texto. sanear() ya deja el texto utilizable; esto es para el aviso que
    sube a la interfaz."""
    problemas = []
    sanear(texto, problemas)
    return problemas


def silencio_final(texto) -> float:
    """Milisegundos de silencio que quedan detras de la ultima palabra."""
    total = 0.0
    for clase, pieza in reversed(trocear(str(texto or ""))):
        if clase == "break":
            total += float(pieza)
        elif clase == "texto" and str(pieza).strip():
            break
    return total


def pausa_al_final(texto, ms) -> str:
    """La escena termina con al menos 'ms' de silencio, cueste lo que cueste.

    Existe porque hay una pausa que no puede depender de que el redactor se
    acuerde: la del gancho a la entrada del documental. El gancho esta
    ESCRITO para que despues haya aire -- es una frase que remata y se queda
    colgando -- y si el aire no esta, la escena siguiente le pisa el final
    y el recurso no funciona. Las demas pausas son criterio; esta es
    estructura.

    Si ya hay silencio suficiente no se toca nada. Si hay pero se queda
    corto, se sustituye en vez de sumarle otro: dos silencios casi pegados
    es de lo poco que la documentacion desaconseja explicitamente.
    """
    crudo = str(texto or "")
    if ms <= 0 or not limpiar(crudo):
        return crudo
    if silencio_final(crudo) >= ms:
        return crudo
    # se reconstruye SIN los silencios de cola y se pone uno solo
    # (sustituir, no sumar: dos silencios pegados es de lo poco que la
    # documentacion desaconseja explicitamente)
    piezas = trocear(crudo)
    ultimo_texto = max(k for k, (clase, pieza) in enumerate(piezas)
                       if clase == "texto" and str(pieza).strip())
    rehecho = _rearmar(piezas[:ultimo_texto + 1]) \
        + f'<break time="{_formatear_ms(ms)}ms"/>'
    return sanear(rehecho)


def _rearmar(piezas) -> str:
    """Vuelve a escribir el texto a partir de [(clase, pieza)] de trocear()."""
    trozos = []
    for clase, pieza in piezas:
        if clase in ("texto", "basura"):
            trozos.append(str(pieza))
        elif clase == "break":
            trozos.append(f'<break time="{_formatear_ms(float(pieza))}ms"/>')
    return "".join(trozos)


def revisar_conjunto(escenas) -> list[str]:
    """Problemas que solo se ven mirando el guion ENTERO.

    Uno solo, pero es el que puede estropear la toma: pasarse de silencios.
    Cada <break> parte la generacion, asi que muchos convierten la toma
    continua en una lectura frase a frase, que es exactamente lo que no se
    quiere.
    """
    textos = [str((e.get("narracion") if isinstance(e, dict) else e) or "")
              for e in escenas or []]
    if not textos:
        return []
    silencios = sum(1 for t in textos
                    for clase, _ in trocear(t) if clase == "break")
    tope = int(len(textos) * DENSIDAD_MAXIMA)
    if silencios <= max(1, tope):
        return []
    return [f"{silencios} silencios para {len(textos)} escenas. Cada "
            f"<break> parte la generacion, asi que a esa densidad la toma "
            f"deja de sonar continua y vuelve a sonar a lista leida. Deja "
            f"como mucho {max(1, tope)}, en los sitios donde el relato "
            f"cambia de marcha de verdad"]


def resumen(escenas) -> dict:
    """Cuantos silencios hay en una lista de escenas (para la bitacora)."""
    cuenta = 0
    for escena in escenas or []:
        texto = escena.get("narracion") if isinstance(escena, dict) else escena
        cuenta += sum(1 for clase, _ in trocear(str(texto or ""))
                      if clase == "break")
    return {"break": cuenta}


# ---------------------------------------------------- filtro de marcas de vuelta

def texto_de_marca(palabra):
    """La palabra hablada que hay detras de una marca, o None si no hay.

    El motor de voz devuelve las palabras que dijo; si alguna llegara con
    restos de etiqueta (angulos dentro del token), no se TIRA el token --
    eso dejaria la escena con una palabra menos de las que espera el
    reparto, y de ahi en adelante cada corte caeria una palabra antes --:
    se le quita la etiqueta y se queda la palabra. Lo que si se tira es
    cualquier cosa que SIGA con angulos: solo puede ser una etiqueta que
    no deberia estar ahi.
    """
    trozo = str(palabra or "")
    if "<" not in trozo and ">" not in trozo:
        return trozo
    limpio = _ALGO_ASI.sub("", trozo).strip()
    if "<" in limpio:
        # etiqueta SIN CERRAR pegada a la palabra ("palabra<break"): la
        # palabra es real y se queda; lo que sigue al angulo, fuera
        limpio = limpio.split("<", 1)[0].strip()
    if not limpio or "<" in limpio or ">" in limpio:
        return None
    return limpio


def es_token_de_etiqueta(palabra) -> bool:
    """True si esta marca no lleva ninguna palabra hablada dentro."""
    return texto_de_marca(palabra) is None


# -------------------------------------------------------------- para el motor

def para_tts(texto) -> str:
    """Reescribe los `<break>` al formato de ElevenLabs: SEGUNDOS.

    `<break time="900ms"/>` -> `<break time="0.9s"/>`. Dentro del Estudio
    se trabaja en milisegundos; el motor los quiere en segundos.
    """

    def _cambia(encaje):
        ms = _ms_de(_numero(encaje.group(1)), encaje.group(2))
        segundos = max(0.001, round(ms / 1000.0, 3))
        texto_s = f"{segundos:.3f}".rstrip("0").rstrip(".")
        return f'<break time="{texto_s}s"/>'

    return _BREAK.sub(_cambia, str(texto or ""))


# ------------------------------------------------------- instrucciones al modelo

#: Repertorio en terminos de GUION, no de milisegundos. Un redactor sabe
#: cuando acaba el gancho; no sabe si eso son 600 u 800 ms.
PAUSAS = (
    ("del gancho a la entrada del documental", 900),
    ("cambio de capitulo o salto grande de tiempo o de lugar", 700),
    ("justo antes de una revelacion, una cifra que pesa o un giro", 400),
    ("suspense dentro de una frase, detras de una coma o de puntos "
     "suspensivos", 250),
)


def instrucciones() -> str:
    """Bloque de reglas de anotacion para el prompt del guion."""
    lineas = [
        "== ANOTACIONES DE VOZ (van dentro de la narracion) ==",
        "El guion no se lee: lo locuta un sintetizador. La puntuacion normal "
        "ya da el ritmo basico y es la primera herramienta: escribe frases "
        "bien puntuadas ANTES de pensar en ninguna etiqueta. Las etiquetas "
        "son para lo que la puntuacion no distingue, que es cuando el "
        "relato cambia de marcha.",
        "",
        "SILENCIO. `<break time=\"700ms\"/>` mete una pausa donde va. Es la "
        "unica etiqueta que existe y casi siempre la unica que hace falta. "
        "Cuanto:",
    ]
    lineas.extend(f"  - {motivo}: <break time=\"{ms}ms\"/>"
                  for motivo, ms in PAUSAS)
    lineas.extend([
        f"  El maximo es {BREAK_MAX_MS} ms. No pongas dos seguidos.",
        "",
        "MEDIDA. Un silencio cada dos o tres escenas como mucho, y solo "
        "donde el relato cambia de marcha de verdad. Un guion con una pausa "
        "en cada escena no suena solemne: suena a que el locutor duda.",
        "",
        "NADA MAS. Esta es la unica etiqueta que existe. Cualquier otra "
        "cosa entre < y > la LOCUTA el sintetizador en voz alta, asi que no "
        "te inventes ninguna. Y no cuenta como palabra: la horquilla se "
        "mide sobre lo que se oye.",
    ])
    return "\n".join(lineas)
