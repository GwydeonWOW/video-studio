"""Música de fondo y efectos: de dónde salen, cómo se eligen y cómo se mezclan.

ADAPTACIÓN DEL ORIGINAL (pasos/sonido.py del estudio de referencia)
--------------------------------------------------------------------
El contrato se mantiene entero: dos momentos separados (SURTIR, con la red
delante y una persona eligiendo; RENDERIZAR, que sólo lee del banco), el
banco es del CANAL, los vetados viven junto al banco, y el mismo plan
suena igual siempre. Lo que cambia es el MOTOR: aquí el render es ffmpeg
directo (segmentos + concat/xfade), así que:

    · la cama y la mezcla se construyen con el mismo grafo de ffmpeg
      (loudnorm por tramo, acrossfade, ducking con la llave aplanada) pero
      sobre una pista de voz que sale de concatenar los audios de escena;
    · NO hay máquina de escribir: las cartelas de este motor se dibujan
      de una pieza (no letra a letra), así que unos golpes de tecla
      sonarían cuando no se está escribiendo — exactamente el fallo que
      el original evitó a propósito. En su lugar hay un papel
      «entrada_cartela»: un aire suave cuando el plano que entra ES una
      cartela, que sí es lo que se ve.

DE DÓNDE SALE EL AUDIO
----------------------
    música    Jamendo API v3.0      https://api.jamendo.com/v3.0/tracks/
    efectos   Freesound API v2      https://freesound.org/apiv2/search/text/

Las claves viven en el cajón de secretos del estudio (Configuración) o en
el entorno (ESTUDIO_JAMENDO_ID / ESTUDIO_FREESOUND_KEY), nunca en el repo.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import requests

try:
    from ..config import AJUSTES
    from . import comun
except ImportError:
    from config import AJUSTES               # type: ignore
    from pasos import comun                  # type: ignore


def banco(*partes) -> Path:
    """Donde viven los ficheros ya descargados (del CANAL, no del vídeo)."""
    ruta = Path(AJUSTES.datos).joinpath("banco", "audio", *partes)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta


def _claves() -> dict:
    """Jamendo/FreeSound del cajón de secretos o del entorno."""
    from ..nucleo.claves import leer_claves
    claves = leer_claves(AJUSTES.carpeta_claves)
    salida = {}
    if claves.get("jamendo"):
        salida["JAMENDO_CLIENT_ID"] = claves["jamendo"]
    if claves.get("freesound"):
        salida["FREESOUND_API_KEY"] = claves["freesound"]
    for nombre, variable in (("JAMENDO_CLIENT_ID", "ESTUDIO_JAMENDO_ID"),
                             ("FREESOUND_API_KEY", "ESTUDIO_FREESOUND_KEY")):
        valor = os.environ.get(variable, "")
        if valor and nombre not in salida:
            salida[nombre] = valor.strip()
    return salida


def hay_claves() -> tuple[bool, bool]:
    """Si se puede salir a buscar. Renderizar NO lo necesita."""
    claves = _claves()
    return bool(claves.get("JAMENDO_CLIENT_ID")), bool(claves.get("FREESOUND_API_KEY"))


def desempatar(semilla, *clave) -> int:
    """Un entero estable de una semilla y unas claves (elecciones sin azar)."""
    texto = "|".join(str(p or "") for p in (semilla, *clave))
    return int.from_bytes(hashlib.sha1(texto.encode("utf-8")).digest()[:8], "big")


# ===========================================================================
# LOS PAPELES DE EFECTO
#
# Un papel no es «un sonido»: es un HUECO del montaje con lo que hay que
# pedirle a Freesound para llenarlo y cómo tiene que sonar cuando entre.

PAPELES = {
    "transicion_suave": {
        "nombre": "Aire de transición",
        "descripcion": "Un barrido corto y suave para los encadenados que cierran frase.",
        "consultas": ("soft whoosh transition", "airy swoosh", "subtle swish transition",
                      "gentle whoosh"),
        "duracion": (0.3, 2.5), "ganancia": 0.55, "cuantos": 6,
    },
    "transicion_acento": {
        "nombre": "Golpe de transición",
        "descripcion": "El impacto de los acentos, cada pocos planos. Se nota.",
        "consultas": ("cinematic whoosh impact", "transition hit braam",
                      "riser impact short", "whoosh boom transition"),
        "duracion": (0.3, 3.0), "ganancia": 0.8, "cuantos": 6,
    },
    "entrada_cartela": {
        "nombre": "Entrada de cartela",
        "descripcion": "Un aire con cuerpo cuando el plano que entra es una cartela.",
        "consultas": ("cinematic title card whoosh", "soft impact thud short",
                      "elegant swoosh intro"),
        "duracion": (0.3, 2.0), "ganancia": 0.6, "cuantos": 4,
    },
    "tecla": {
        "nombre": "Tecla de escribir",
        "descripcion": "El tecleo de la cartela: un golpe por tecla, palabra a palabra.",
        "consultas": ("typewriter single key press", "typewriter key click",
                      "mechanical keyboard single click"),
        "duracion": (0.05, 0.6), "ganancia": 0.32, "cuantos": 4,
    },
    "retorno": {
        "nombre": "Retorno de carro",
        "descripcion": "El ding del carro al terminar de escribir la cartela.",
        "consultas": ("typewriter carriage return bell", "typewriter ding return"),
        "duracion": (0.3, 3.0), "ganancia": 0.5, "cuantos": 3,
    },
}

#: EL TECLEO de una cartela: a cuántas teclas por segundo tira como
#: mucho, y cuántas por palabra — los topes que evitan una metralleta
#: cuando una palabra entra con un hueco largo.
TECLAS_POR_SEGUNDO = 16.0
TECLAS_POR_PALABRA = 6

#: DÓNDE CAE EL GOLPE del efecto dentro de la transición que se VE, en
#: fracción de su duración. 0,5: el ojo lee el cambio en la mitad de la
#: mezcla, y con esto el sonido y la imagen dicen «ha pasado algo» en el
#: mismo instante. Es el único número de esto.
ANCLA_TRANSICION = 0.5

#: A cuánto por debajo del pico se considera que el efecto YA ESTÁ SONANDO.
GOLPE_UMBRAL_DB = -6.0

#: Objetivo de la música (LUFS) y pico de los efectos (dBFS).
MUSICA_LUFS = -23.0
EFECTOS_PICO_DB = -6.0

FRECUENCIA = 48000

#: Lo medido de cada fichero, que no cambia: se abre una vez por render.
_GOLPES: dict[str, float] = {}


def golpe_de(ruta) -> float:
    """Cuánto tarda ese efecto en GOLPEAR desde el principio del fichero (s).

    Un barrido no suena en su primer milisegundo: sube y pega, y ese retardo
    va de 0,05 s a 0,90 s según el fichero. Colocar los efectos por su
    primera muestra es colocarlos en cualquier sitio; lo que se fija es
    dónde cae el GOLPE. Devuelve 0,0 si no se puede leer (y entonces el
    evento no se mezcla, así que el número da igual): reventar aquí sería
    tumbar un render por un efecto que ni suena.
    """
    if not ruta:
        return 0.0
    clave = os.path.normcase(os.path.abspath(str(ruta)))
    if clave in _GOLPES:
        return _GOLPES[clave]
    valor = 0.0
    try:
        muestras = _leer(_a_wav(str(ruta)))
        env = np.abs(muestras).max(axis=1) if muestras.ndim > 1 else np.abs(muestras)
        pico = float(env.max()) if len(env) else 0.0
        if pico > 0:
            umbral = pico * (10.0 ** (GOLPE_UMBRAL_DB / 20.0))
            arriba = np.nonzero(env >= umbral)[0]
            if len(arriba):
                valor = float(arriba[0]) / FRECUENCIA
    except Exception:                                       # noqa: BLE001
        valor = 0.0
    _GOLPES[clave] = valor
    return valor


# ------------------------------------------------------------------ Jamendo

ANIMOS = {
    "oscuro": "dark cinematic", "tension": "tense suspense",
    "epico": "epic cinematic", "sobrio": "documentary ambient",
    "esperanzador": "uplifting hopeful", "corporativo": "corporate clean",
    "melancolico": "melancholic piano", "misterioso": "mysterious ambient",
}


def _pedir_a_jamendo(params) -> list:
    respuesta = requests.get("https://api.jamendo.com/v3.0/tracks/",
                             params=params, timeout=45)
    respuesta.raise_for_status()
    datos = respuesta.json()
    cabecera = datos.get("headers") or {}
    if cabecera.get("status") != "success":
        raise RuntimeError(f"Jamendo: {cabecera.get('error_message') or cabecera}")
    return datos.get("results") or []


def buscar_musica(animo="sobrio", duracion_s=0, cuantas=12, velocidad="low",
                  instrumental=True, extra="") -> list[dict]:
    """Temas de Jamendo que encajan con el tono del vídeo.

    POR QUÉ ESTO ES UNA ESCALERA Y NO UNA CONSULTA: en Jamendo `fuzzytags`
    no se lleva bien con los filtros duros (combinado con durationbetween o
    audiodownload_allowed devuelve CERO resultados con status: success).
    Se pregunta de lo más estricto a lo más suelto y se para en cuanto hay
    material; lo innegociable (que el tema se pueda bajar) se comprueba
    aquí mirando `audiodownload`.
    """
    claves = _claves()
    if not claves.get("JAMENDO_CLIENT_ID"):
        raise RuntimeError("falta la clave de Jamendo (Configuración)")
    etiquetas = ANIMOS.get(animo, animo)
    if extra:
        etiquetas = f"{etiquetas} {extra}".strip()
    tope = max(1, min(50, int(cuantas)))
    comun_params = {"client_id": claves["JAMENDO_CLIENT_ID"], "format": "json",
                    "limit": tope * 2, "include": "musicinfo licenses",
                    "boost": "popularity_total"}
    if instrumental:
        comun_params["vocalinstrumental"] = "instrumental"
    minimo = int(max(60, min((duracion_s or 0) * 0.45, 420))) if duracion_s else 0

    escalera = [
        {"fuzzytags": etiquetas, "speed": velocidad,
         "audiodownload_allowed": "true", "ccnd": "false"},
        {"fuzzytags": etiquetas, "speed": velocidad},
        {"fuzzytags": etiquetas},
        {"fuzzytags": etiquetas.split()[0] if etiquetas.split() else "ambient",
         "speed": velocidad},
    ]
    vistos, salida = set(), []
    for extra_params in escalera:
        params = dict(comun_params)
        params.update(extra_params)
        for track in _pedir_a_jamendo(params):
            ficha = _ficha_musica(track)
            if not ficha["descarga"] or ficha["id"] in vistos:
                continue
            vistos.add(ficha["id"])
            salida.append(ficha)
        if len(salida) >= tope:
            break
    salida.sort(key=lambda f: (f["duracion"] < minimo, -f["duracion"]))
    return salida[:tope]


def _ficha_musica(track) -> dict:
    info = track.get("musicinfo") or {}
    etiquetas = info.get("tags") or {}
    return {
        "fuente": "jamendo",
        "id": str(track.get("id")),
        "titulo": track.get("name") or "",
        "artista": track.get("artist_name") or "",
        "duracion": float(track.get("duration") or 0),
        "descarga": track.get("audiodownload") or "",
        "escucha": track.get("audio") or track.get("audiodownload") or "",
        "licencia": track.get("license_ccurl") or "",
        "generos": list(etiquetas.get("genres") or []),
        "instrumentos": list(etiquetas.get("instruments") or [])[:6],
        "vocal": info.get("vocalinstrumental") or "",
        "velocidad": info.get("speed") or "",
    }


# ------------------------------------------------- la banda sonora, sin manos
#
# NADIE ELIGE UNA CANCIÓN: el RITMO del montaje (cuántos planos por minuto,
# dónde se acelera) es exactamente la información con la que un montador
# elige la música. El vídeo se parte en TRAMOS, cada tramo pide su ánimo, y
# los temas se encadenan con un fundido largo: una CAMA continua que cambia
# de color cuando cambia el relato.

SEGUNDOS_POR_TRAMO = 150.0
TRAMOS_MIN, TRAMOS_MAX = 2, 6
CRUCE_S = 6.0

#: Ganancia de la cama sobre su -23 LUFS, ya normalizada.
CAMA_GANANCIA_DB = -1.0

#: CUÁNTA MÚSICA, sobre su -23 LUFS. Se aplica a las dos entradas (la cama
#: encadenada y el tema suelto); +dB se oye alta en las pausas, -dB la
#: entierra bajo la voz.
MUSICA_SUBIDA_DB = -2.0

# ===========================================================================
# EL DUCKING: la llave NO es la voz tal cual
#
# La envolvente de una voz no es una meseta: cae al final de cada frase, y
# un compresor de cadena lateral con la llave tal cual sube la música justo
# cuando suena la última palabra (donde suele estar el dato). La cura es
# APLANAR LA LLAVE: se sube 16 dB y se limita; el ducking pasa a ser binario
# (hay voz / no hay voz) y la profundidad queda constante.
# ===========================================================================

DUCK_LLAVE_SUBIDA_DB = 16
DUCK_LLAVE_TECHO = 0.7
DUCK_UMBRAL = 0.05
DUCK_RATIO = 6
DUCK_ATAQUE_MS = 15
DUCK_CAIDA_MS = 1200

# El master: a cuánto sale el vídeo. Dos pasadas (medir, y luego aplicar
# una ganancia CONSTANTE): un loudnorm de una sola pasada es adaptativo y
# sobre voz+música se oye como bombeo.
MASTER_LUFS = -14.0
MASTER_TP = -1.0
MASTER_LRA = 11.0


def filtro_master(medida=None) -> str:
    """El último eslabón de la mezcla: el nivel de salida.

    Sin `medida` sale el filtro de ANÁLISIS (no toca nada); con ella, el
    que aplica la ganancia constante.
    """
    base = f"loudnorm=I={MASTER_LUFS:g}:TP={MASTER_TP:g}:LRA={MASTER_LRA:g}"
    if not medida:
        return base + ":print_format=json"
    return base + ":" + ":".join([
        f"measured_I={float(medida['input_i']):.2f}",
        f"measured_TP={float(medida['input_tp']):.2f}",
        f"measured_LRA={float(medida['input_lra']):.2f}",
        f"measured_thresh={float(medida['input_thresh']):.2f}",
        "linear=true", "print_format=summary"])


#: Las tres bandas con las que se juzga un tema SIN OÍRLO. La de en medio
#: es la de la VOZ: un tema con muchos medios se pelea con el narrador por
#: el mismo sitio del espectro.
BANDAS = {"graves": (20.0, 250.0), "medios": (250.0, 4000.0),
          "agudos": (4000.0, 16000.0)}


def arco_del_video(escenas, duracion_s=0.0) -> list[dict]:
    """En qué tramos se parte el vídeo y qué ánimo pide cada uno, POR EL RITMO.

    Se mide la densidad de plano (cuántos cortes por segundo hay en el
    tramo), que es la medida honesta del ritmo de un montaje, y se traduce
    a ánimo con la posición (la apertura engancha, el cierre cierra).
    Nada aleatorio: el mismo plan da el mismo arco siempre.
    """
    escenas = [e for e in (escenas or []) if e.get("t_in") is not None]
    if not escenas:
        return []
    origen = float(escenas[0].get("t_in") or 0.0)
    fin = float(escenas[-1].get("t_out") or escenas[-1].get("t_in") or 0.0)
    total = float(duracion_s or (fin - origen)) or 1.0
    cuantos = int(max(TRAMOS_MIN, min(TRAMOS_MAX, round(total / SEGUNDOS_POR_TRAMO))))

    tramos = []
    for i in range(cuantos):
        desde = total * i / cuantos
        hasta = total * (i + 1) / cuantos
        dentro = [e for e in escenas
                  if desde <= float(e.get("t_in") or 0.0) - origen < hasta]
        largo = max(0.001, hasta - desde)
        tramos.append({"i": i, "desde": round(desde, 2), "hasta": round(hasta, 2),
                       "fraccion": 1.0 / cuantos, "planos": len(dentro),
                       "densidad": round(len(dentro) / largo, 3)})

    # contra la densidad MEDIA del vídeo: con tres tramos la mediana ES uno
    # de ellos, y ese nunca podría salir rápido
    media = len(escenas) / max(0.001, total)
    for tramo in tramos:
        rapido = tramo["densidad"] > media
        primero, ultimo = tramo["i"] == 0, tramo["i"] == cuantos - 1
        if primero:
            tramo["animo"] = "tension" if rapido else "misterioso"
            tramo["por_que"] = ("abre y el montaje ya va rápido: engancha"
                                if rapido else "abre despacio: intriga")
        elif ultimo:
            tramo["animo"] = "epico" if rapido else "melancolico"
            tramo["por_que"] = ("cierra acelerando: remate"
                                if rapido else "cierra bajando: poso")
        else:
            tramo["animo"] = "tension" if rapido else "sobrio"
            tramo["por_que"] = (f"{tramo['planos']} planos, "
                                + ("por encima" if rapido else "por debajo")
                                + " del ritmo medio")
        tramo["velocidad"] = ("high" if tramo["densidad"] > media * 1.25
                              else "low" if tramo["densidad"] < media * 0.8
                              else "medium")
    return tramos


def medir(ruta) -> dict:
    """Cómo suena un tema, en números. Sin oírlo y sin llamar a nadie."""
    muestras = _leer(_a_wav(str(ruta)))
    if not len(muestras):
        return {"lufs": -99.0, "graves": -99.0, "medios": -99.0, "agudos": -99.0}
    mono = muestras.mean(axis=1)
    centro = len(mono) // 2
    ancho = min(len(mono), FRECUENCIA * 30)
    trozo = mono[max(0, centro - ancho // 2):centro + ancho // 2]
    espectro = np.abs(np.fft.rfft(trozo * np.hanning(len(trozo)))) ** 2
    hercios = np.fft.rfftfreq(len(trozo), 1.0 / FRECUENCIA)
    total = float(espectro.sum()) or 1.0
    ficha = {}
    for nombre, (bajo, alto) in BANDAS.items():
        dentro = espectro[(hercios >= bajo) & (hercios < alto)].sum()
        ficha[nombre] = round(10.0 * np.log10(max(dentro / total, 1e-9)), 1)
    rms = float(np.sqrt(np.mean(np.square(trozo)))) or 1e-9
    ficha["lufs"] = round(20.0 * np.log10(rms), 1)
    return ficha


def puntuar(ficha_medida) -> float:
    """Cuánto le conviene este tema a una voz encima. Más alto, mejor.

    Graves menos medios: premia lo que suena lleno abajo y deja libre la
    banda de la voz.
    """
    m = ficha_medida or {}
    return float(m.get("graves", -99)) - float(m.get("medios", -99))


def elegir_tema(candidatos, evitar=()) -> dict | None:
    """El mejor candidato para llevar voz encima, y por qué. Sin oír nada."""
    evitar = {str(i) for i in (evitar or [])}
    mejor, mejor_punto = None, None
    for ficha in candidatos or []:
        if str(ficha.get("id")) in evitar:
            continue
        try:
            ruta = traer(ficha, "musica")
            medida = medir(ruta)
        except Exception as fallo:                     # un tema caído no corta
            ficha["error"] = str(fallo)[:120]
            continue
        punto = puntuar(medida)
        ficha["medida"] = medida
        ficha["punto"] = round(punto, 1)
        if mejor_punto is None or punto > mejor_punto:
            mejor, mejor_punto = ficha, punto
    return mejor


def montar_banda(escenas, duracion_s, avisar=None, tramos=None) -> dict:
    """La banda sonora entera, decidida sola. Devuelve la ficha para params.

    NO deja fichero de audio: deja escrito QUÉ tema va en cada tramo. La
    cama se construye al renderizar (`construir_cama`), sin salir a la red,
    desde los ficheros que esto ha dejado en el banco.
    """
    avisar = avisar or (lambda *a, **k: None)
    arco = tramos or arco_del_video(escenas, duracion_s)
    if not arco:
        raise RuntimeError("no hay planos con tiempos: no se puede leer el ritmo")
    puestos, usados = [], []
    for tramo in arco:
        avisar(0.1 + 0.8 * tramo["i"] / max(1, len(arco)),
               f"tramo {tramo['i'] + 1} de {len(arco)}: buscando algo "
               f"«{tramo['animo']}»")
        candidatos = buscar_musica(animo=tramo["animo"], cuantas=6,
                                   duracion_s=(tramo["hasta"] - tramo["desde"]),
                                   velocidad=tramo["velocidad"])
        elegido = elegir_tema(candidatos, evitar=usados)
        if elegido is None:
            raise RuntimeError(f"tramo {tramo['i'] + 1}: Jamendo no ha devuelto "
                               f"ningún tema «{tramo['animo']}» que se pueda bajar")
        usados.append(str(elegido["id"]))
        puestos.append({**{k: elegido.get(k) for k in
                           ("fuente", "id", "titulo", "artista", "licencia",
                            "duracion", "medida", "punto")},
                        "animo": tramo["animo"], "velocidad": tramo["velocidad"],
                        "fraccion": tramo["fraccion"], "planos": tramo["planos"],
                        "por_que": tramo["por_que"]})
    return {"tramos": puestos, "ganancia_db": CAMA_GANANCIA_DB,
            "cruce_s": CRUCE_S, "modo": "cama"}


def construir_cama(ficha, duracion_s, destino) -> tuple:
    """Encadena los temas de los tramos en UNA pista del largo del vídeo.

    No sale a la red: coge del banco lo que dicen los params. Si falta
    algún fichero se sigue con los que haya y se dice cuáles faltaban.
      · loudnorm a -23 en CADA tramo antes de encadenar, o se oye el salto
      · `-stream_loop` cuando el tema es más corto que su tramo
      · `acrossfade` de seis segundos: cambio de tema = cambio de escena
      · relleno y recorte al largo EXACTO, con fundidos de entrada/salida
    """
    tramos = [t for t in (ficha or {}).get("tramos") or [] if t.get("id")]
    if not tramos:
        return None, []
    cruce = float((ficha or {}).get("cruce_s") or CRUCE_S)
    total = float(duracion_s)
    carpeta = Path(destino).parent
    carpeta.mkdir(parents=True, exist_ok=True)

    trozos, faltan = [], []
    for tramo in tramos:
        origen = banco("musica", _nombre_de(tramo))
        if not origen.exists():
            faltan.append(tramo.get("titulo") or tramo.get("id"))
            continue
        cola = cruce if tramo is not tramos[-1] else 0.0
        quiere = max(1.0, total * float(tramo.get("fraccion") or 0) + cola)
        trozo = carpeta / f"tramo{len(trozos)}.wav"
        corto = float(tramo.get("duracion") or 0) < quiere + 1
        orden = [comun.ffmpeg(), "-y", "-loglevel", "error"]
        if corto:
            orden += ["-stream_loop", "3"]
        orden += ["-i", str(origen), "-t", f"{quiere:.2f}",
                  "-af", f"loudnorm=I={MUSICA_LUFS:.0f}:TP=-2:LRA=11",
                  "-ar", str(FRECUENCIA), "-ac", "2", str(trozo)]
        subprocess.run(orden, capture_output=True, text=True, timeout=600,
                       check=True)
        trozos.append(trozo)
    if not trozos:
        return None, faltan

    cadena = trozos[0]
    for indice in range(1, len(trozos)):
        siguiente = carpeta / f"cadena{indice}.wav"
        subprocess.run(
            [comun.ffmpeg(), "-y", "-loglevel", "error",
             "-i", str(cadena), "-i", str(trozos[indice]), "-filter_complex",
             f"[0:a][1:a]acrossfade=d={cruce:g}:c1=tri:c2=tri", str(siguiente)],
            capture_output=True, text=True, timeout=600, check=True)
        cadena = siguiente
    salida = float(min(cruce, max(1.0, total * 0.05)))
    subprocess.run(
        [comun.ffmpeg(), "-y", "-loglevel", "error", "-i", str(cadena), "-af",
         f"apad=whole_dur={total + 1:.2f},atrim=0:{total:.3f},"
         f"afade=t=in:st=0:d=3,afade=t=out:st={max(0.0, total - salida):.2f}:d={salida:g}",
         "-ar", str(FRECUENCIA), "-ac", "2", str(destino)],
        capture_output=True, text=True, timeout=600, check=True)
    return destino, faltan


# ---------------------------------------------------------------- Freesound

def buscar_efectos(consulta, dur_min=0.2, dur_max=8.0, cuantos=15) -> list[dict]:
    """Efectos de Freesound para una consulta, ordenados por descargas."""
    claves = _claves()
    if not claves.get("FREESOUND_API_KEY"):
        raise RuntimeError("falta la clave de FreeSound (Configuración)")
    respuesta = requests.get(
        "https://freesound.org/apiv2/search/text/", timeout=45,
        headers={"Authorization": "Token " + claves["FREESOUND_API_KEY"]},
        params={"query": consulta,
                "filter": f"duration:[{dur_min} TO {dur_max}]",
                "fields": ("id,name,tags,duration,license,username,url,previews,"
                           "ac_analysis"),
                "sort": "downloads_desc",
                "page_size": max(1, min(50, int(cuantos)))})
    if respuesta.status_code != 200:
        raise RuntimeError(f"Freesound {respuesta.status_code}: "
                           f"{respuesta.text[:200]}")
    return [_ficha_efecto(s) for s in respuesta.json().get("results") or []]


def _ficha_efecto(crudo) -> dict:
    ac = crudo.get("ac_analysis") or {}
    previos = crudo.get("previews") or {}
    return {
        "fuente": "freesound",
        "id": str(crudo.get("id")),
        "titulo": crudo.get("name") or "",
        "autor": crudo.get("username") or "",
        "duracion": float(crudo.get("duration") or 0),
        "licencia": crudo.get("license") or "",
        "pagina": crudo.get("url") or "",
        # el preview de alta basta con el token; el WAV original pide OAuth2
        "descarga": previos.get("preview-hq-mp3") or "",
        "escucha": previos.get("preview-hq-mp3") or "",
        "etiquetas": list(crudo.get("tags") or [])[:8],
        # cómo SUENA, cuando Freesound lo tiene analizado: viaja para poder
        # elegir mirando, no para filtrar
        "brillo": ac.get("ac_brightness"),
        "dureza": ac.get("ac_hardness"),
        "reverb": ac.get("ac_reverb"),
    }


# ------------------------------------------------------------------- banco

def _nombre_de(ficha, extension=".mp3") -> str:
    return f"{ficha.get('fuente', 'x')}_{ficha.get('id', '0')}{extension}"


def clave_de(ficha) -> str:
    """El identificador de un efecto: de dónde sale y su id allí.

    Es lo mismo con lo que se guarda en el banco, sin extensión: identifica
    un SONIDO, no un papel (un láser vetado como golpe tampoco puede volver
    como aire).
    """
    if isinstance(ficha, str):
        return ficha.strip()
    return _nombre_de(ficha or {}, "")


# ------------------------------------------------------------- los vetados
#
# UN EFECTO QUE NO GUSTA SE VETA, NO SE BORRA: borrar el fichero sólo
# consigue que la siguiente búsqueda lo vuelva a bajar (Freesound ordena
# por descargas). Es del CANAL, como el banco: un sonido que no gusta no
# gusta en el vídeo siguiente tampoco. Y muerde en los DOS sitios:
#     surtir()   no lo baja ni lo mete en el surtido  -> no vuelve
#     elegir()   no lo reparte aunque esté en el surtido -> deja de sonar YA

def _fichero_vetados() -> Path:
    return banco("efectos", "vetados.json")


def vetados() -> dict:
    """Los efectos vetados del canal: {clave: ficha}."""
    ruta = _fichero_vetados()
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return {}
    fuera = {}
    for ficha in (datos or {}).get("vetados") or []:
        if isinstance(ficha, dict) and ficha.get("clave"):
            fuera[str(ficha["clave"])] = ficha
    return fuera


def esta_vetado(ficha, lista=None) -> bool:
    clave = clave_de(ficha)
    return bool(clave) and clave in (vetados() if lista is None else lista)


def _guardar_vetados(fichas) -> None:
    ruta = _fichero_vetados()
    temporal = str(ruta) + ".parcial"
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump({"vetados": [fichas[k] for k in sorted(fichas)]}, fh,
                  ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)


def vetar(ficha, papel=None, motivo="") -> dict:
    """Prohíbe este efecto en TODO el canal. Devuelve la ficha del veto."""
    clave = clave_de(ficha)
    if not clave or clave.endswith("_0") or clave.startswith("x_"):
        raise ValueError("ese efecto no trae fuente e id: no se puede vetar")
    lista = vetados()
    entrada = {
        "clave": clave,
        "titulo": (ficha.get("titulo") if isinstance(ficha, dict) else "") or "",
        "autor": (ficha.get("autor") if isinstance(ficha, dict) else "") or "",
        "papel": str(papel or (ficha.get("papel") if isinstance(ficha, dict) else "") or ""),
        "motivo": str(motivo or "")[:200],
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    lista[clave] = entrada
    _guardar_vetados(lista)
    return entrada


def desvetar(ficha) -> bool:
    """Levanta el veto. -> si había algo que levantar."""
    clave = clave_de(ficha)
    lista = vetados()
    if clave not in lista:
        return False
    lista.pop(clave)
    _guardar_vetados(lista)
    return True


#: Por encima de qué frecuencia se cuenta el brillo de un efecto, en Hz.
AGUDO_HZ = 4000.0


def _medida_de(ruta, fichero, clave, calcular):
    """Una medida cara de un efecto, cacheada por fichero y fecha.

    Cada medida vive en su fichero (`agudeza.json`, `nivel.json`) bajo su
    propia clave. Nada de esto levanta nunca: una medida que no sale
    devuelve None y quien llama decide.
    """
    if not ruta or not os.path.exists(ruta):
        return None
    nombre = os.path.basename(str(ruta))
    sello = f"{os.path.getmtime(ruta):.0f}:{os.path.getsize(ruta)}"
    cache_ruta = banco("efectos", fichero)
    cache = {}
    if cache_ruta.exists():
        try:
            with open(cache_ruta, "r", encoding="utf-8-sig") as fh:
                cache = json.load(fh) or {}
        except (OSError, ValueError):
            cache = {}
    guardado = cache.get(nombre)
    if isinstance(guardado, dict) and guardado.get("sello") == sello:
        return guardado.get(clave)
    try:
        muestras = _leer(_a_wav(str(ruta)))
    except Exception:                                        # noqa: BLE001
        return None                # un efecto ilegible no tumba la pantalla
    mono = muestras.mean(axis=1) if muestras.ndim > 1 else muestras
    if len(mono) < 64:
        return None
    valor = calcular(mono)
    if valor is None:
        return None
    cache[nombre] = {"sello": sello, clave: valor}
    try:
        temporal = str(cache_ruta) + ".parcial"
        with open(temporal, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
        os.replace(temporal, cache_ruta)
    except OSError:
        pass                       # sin caché se recalcula, no se rompe
    return valor


def agudeza(ficha):
    """Cuánta energía del efecto está por encima de 4 kHz, de 0 a 1. O None.

    PARA ENCONTRAR «ESE QUE SUENA COMO UN LÁSER»: un láser es un barrido
    fino y agudo, y un aire de transición es un soplo con cuerpo. NO decide
    nada (lo dice un oído): sólo pone el candidato arriba del todo.
    """
    def calcular(mono):
        espectro = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
        hz = np.fft.rfftfreq(len(mono), 1.0 / FRECUENCIA)
        total = float((espectro ** 2).sum())
        if total <= 0:
            return None
        return round(float((espectro[hz > AGUDO_HZ] ** 2).sum()) / total, 4)

    ruta = ficha if isinstance(ficha, str) else banco("efectos", _nombre_de(ficha))
    return _medida_de(ruta, "agudeza.json", "agudo", calcular)


#: ------------------------------------------------------ CUÁNTO SUENA UNO
#:
#: Los seis barridos de un papel salen de un banco de stock masterizado
#: como le dio la gana a quien lo subió: hay 20 dB de diferencia entre dos
#: sonidos que hacen lo mismo. La ganancia del papel es la misma para
#: todos, así que hay que IGUALARLOS, y midiéndolo como el oído:
#: ponderación K (la del LUFS) y el máximo en ventanas de 400 ms (lo que
#: molesta es el momento más fuerte, no el promedio).
EFECTOS_VENTANA_S = 0.4
EFECTOS_CORRECCION_MAX_DB = 12.0

#: K-weighting de ITU-R BS.1770 a 48 kHz, aplicado por FFT (aquí sólo
#: interesa la energía, no la fase).
_K_ETAPA1_B = (1.53512485958697, -2.69169618940638, 1.19839281085285)
_K_ETAPA1_A = (1.0, -1.69065929318241, 0.73248077421585)
_K_ETAPA2_B = (1.0, -2.0, 1.0)
_K_ETAPA2_A = (1.0, -1.99004745483398, 0.99007225036621)


def _respuesta_biquad(b, a, w):
    z = np.exp(-1j * w)
    return ((b[0] + b[1] * z + b[2] * z ** 2)
            / (a[0] + a[1] * z + a[2] * z ** 2))


def _k_ponderado(mono):
    n = len(mono)
    hz = np.fft.rfftfreq(n, 1.0 / FRECUENCIA)
    w = 2 * np.pi * hz / FRECUENCIA
    h = (_respuesta_biquad(_K_ETAPA1_B, _K_ETAPA1_A, w)
         * _respuesta_biquad(_K_ETAPA2_B, _K_ETAPA2_A, w))
    return np.fft.irfft(np.fft.rfft(mono) * h, n=n)


def nivel_de(ruta):
    """Lo fuerte que suena ese efecto, en LUFS momentáneo máximo. O None.

    Es la cifra con la que `pista_de_efectos` iguala los ficheros de un
    mismo papel. Cacheado: son dos FFT por efecto y esto corre en cada
    render. None cuando no se puede leer, y entonces no se corrige.
    """
    def calcular(mono):
        y = _k_ponderado(mono)
        ventana = max(1, int(EFECTOS_VENTANA_S * FRECUENCIA))
        if len(y) <= ventana:
            # UN FICHERO MÁS CORTO QUE LA VENTANA SE MIDE ENTERO: rellenar
            # repartiría la energía de una tecla de 50 ms sobre 400.
            energia = float(np.mean(y ** 2))
        else:
            salto = max(1, ventana // 4)
            acumulado = np.concatenate(([0.0], np.cumsum(y.astype(np.float64) ** 2)))
            inicios = np.arange(0, len(y) - ventana + 1, salto)
            energia = float(np.max(
                (acumulado[inicios + ventana] - acumulado[inicios]) / ventana))
        return round(-0.691 + 10.0 * float(np.log10(max(energia, 1e-12))), 2)

    return _medida_de(ruta, "nivel.json", "lufs", calcular)


def traer(ficha, familia) -> Path:
    """Descarga el fichero al banco si no está, y devuelve su ruta.

    Idempotente: un fichero que ya está no se vuelve a pedir. El banco es
    del canal, así que el segundo vídeo no baja nada.
    """
    destino = banco(familia, _nombre_de(ficha))
    if destino.exists() and destino.stat().st_size > 2000:
        return destino
    url = (ficha or {}).get("descarga") or ""
    if not url:
        raise RuntimeError(f"{(ficha or {}).get('id')}: no trae URL de descarga")
    cabeceras = {}
    if ficha.get("fuente") == "freesound":
        claves = _claves()
        if claves.get("FREESOUND_API_KEY"):
            cabeceras["Authorization"] = "Token " + claves["FREESOUND_API_KEY"]
    respuesta = requests.get(url, timeout=180, headers=cabeceras, stream=True)
    respuesta.raise_for_status()
    temporal = str(destino) + ".parcial"
    with open(temporal, "wb") as fh:
        for trozo in respuesta.iter_content(1 << 16):
            fh.write(trozo)
    os.replace(temporal, destino)
    return destino


def surtir(papel, cuantos=None, salteado=0) -> list[dict]:
    """Busca efectos para un papel y los deja descargados. Devuelve sus fichas.

    Recorre las VARIAS consultas del papel (con una sola, Freesound
    devuelve los mismos diez ficheros a todo el mundo), y LO VETADO NO
    VUELVE.
    """
    ficha_papel = PAPELES.get(papel)
    if not ficha_papel:
        raise RuntimeError(f"papel de efecto desconocido: {papel}")
    cuantos = int(cuantos or ficha_papel["cuantos"])
    dur_min, dur_max = ficha_papel["duracion"]
    vistos, salida = set(), []
    fuera = vetados()
    consultas = list(ficha_papel["consultas"])
    for indice in range(len(consultas)):
        consulta = consultas[(indice + int(salteado)) % len(consultas)]
        for ficha in buscar_efectos(consulta, dur_min, dur_max, cuantos * 2):
            if ficha["id"] in vistos or not ficha.get("descarga"):
                continue
            if clave_de(ficha) in fuera:
                vistos.add(ficha["id"])
                continue
            vistos.add(ficha["id"])
            try:
                traer(ficha, "efectos")
            except Exception as fallo:                # un sonido caído no corta
                ficha["error"] = str(fallo)[:120]
                continue
            ficha["papel"] = papel
            salida.append(ficha)
            if len(salida) >= cuantos:
                return salida
    return salida


def elegir(fichas, semilla, *clave, vetados_de=None):
    """Un elemento del surtido, elegido SIN azar de verdad.

    Dos renders del mismo plan tienen que sonar igual: la elección sale de
    la semilla y de la clave del hueco. Y SI EL QUE TOCA ESTÁ VETADO, SE
    PASA AL SIGUIENTE (no se filtra antes de indexar): avanzando, los
    huecos que no habían elegido el vetado suenan exactamente igual que
    antes. Vetar uno tiene que quitar uno.
    """
    fichas = [f for f in (fichas or []) if f]
    if not fichas:
        return None
    fuera = vetados() if vetados_de is None else vetados_de
    arranque = desempatar(semilla, *clave) % len(fichas)
    for salto in range(len(fichas)):
        ficha = fichas[(arranque + salto) % len(fichas)]
        if not fuera or clave_de(ficha) not in fuera:
            return ficha
    return None                    # todas vetadas: ese hueco se queda mudo


# ------------------------------------------------------------------ eventos

def eventos(cortes, reparto, params, semilla=0, cartela_de=None) -> list[dict]:
    """Cuándo suena cada cosa. Devuelve [{t, papel, ficha, ganancia}] ordenado.

    `cortes` son los cortes con tiempos (id, t_in, t_out — el reloj del
    vídeo ya montado) y `reparto` es lo que devuelve
    `transiciones.resolver` (qué transición lleva cada plano y cuánto
    dura). Las cartelas (`cartela_de`, {sid: bool}) aportan su papel propio
    de entrada: un aire cuando el plano que entra ES una cartela.
    """
    surtido = (params or {}).get("efectos") or {}
    if not surtido:
        return []
    cartela_de = cartela_de or {}
    prohibidos = vetados()
    fuera = []

    for corte in cortes or []:
        sid = corte.get("id")
        inicio = float(corte.get("t_in") or 0.0)

        # 1. LA TRANSICIÓN, colocada por su GOLPE y no por su primera
        #    muestra. El fichero empieza a sonar `golpe_de` segundos antes
        #    de pegar; lo que se fija es dónde cae el golpe — en el centro
        #    de la mezcla visual (`ANCLA_TRANSICION`) — y el arranque del
        #    fichero sale de restar.
        trans = (reparto or {}).get(sid) or {}
        if trans.get("tipo") and trans["tipo"] != "corte":
            papel = ("transicion_acento" if trans.get("ranura") == "acento"
                     else "transicion_suave")
            ficha = elegir(surtido.get(papel), semilla, sid, papel,
                           vetados_de=prohibidos)
            if ficha:
                diana = inicio + ANCLA_TRANSICION * float(trans.get("duracion") or 0.0)
                golpe = golpe_de(banco("efectos", _nombre_de(ficha)))
                fuera.append({"t": max(0.0, diana - golpe),
                              "papel": papel, "ficha": ficha,
                              "ganancia": PAPELES[papel]["ganancia"]})

        # 2. la entrada de una CARTELA: el plano entero ES texto, y un
        #    aire con cuerpo anuncia que empieza algo distinto
        if cartela_de.get(sid) and trans.get("tipo") != "corte":
            ficha = elegir(surtido.get("entrada_cartela"), semilla, sid,
                           "cartela", vetados_de=prohibidos)
            if ficha:
                golpe = golpe_de(banco("efectos", _nombre_de(ficha)))
                fuera.append({"t": max(0.0, inicio + 0.15 - golpe),
                              "papel": "entrada_cartela", "ficha": ficha,
                              "ganancia": PAPELES["entrada_cartela"]["ganancia"]})

        # 3. EL TECLEO de la cartela: una tecla por golpe mientras se
        #    escribe, palabra a palabra, y el retorno del carro al
        #    acabar. Los tiempos son los MISMO que dibuja el render
        #    (los dejó p6 en `escritura`): con una cuenta paralela se
        #    oiría escribir cuando no se escribe. Sin banco de teclas
        #    no pasa nada — la cartela se escribe en silencio.
        en_plano = cartela_de.get(sid)
        if isinstance(en_plano, dict) and surtido.get("tecla"):
            from . import cartelas as _cartelas      # noqa: PLC0415
            cartela = en_plano.get("cartela") or {}
            duracion = float(corte.get("duracion") or 0.0)
            tiempos = [float(x) for x in (en_plano.get("tiempos") or [])
                       if x is not None]
            try:
                palabras = _cartelas.tiempos_de_escritura(
                    cartela, duracion, tiempos=tiempos)
            except Exception:                                # noqa: BLE001
                palabras = []
            for orden, (cuando, palabra) in enumerate(palabras):
                siguiente = (palabras[orden + 1][0]
                             if orden + 1 < len(palabras) else cuando + 0.5)
                hueco = max(0.04, min(siguiente - cuando, 0.5))
                cuantas = max(1, min(TECLAS_POR_PALABRA,
                                     len(str(palabra).strip()),
                                     int(hueco * TECLAS_POR_SEGUNDO)))
                for golpe in range(cuantas):
                    ficha = elegir(surtido.get("tecla"), semilla, sid,
                                   orden, golpe, vetados_de=prohibidos)
                    if not ficha:
                        break              # banco agotado: ni metralleta
                    variacion = desempatar(semilla, sid, orden, golpe,
                                           "vol") % 100
                    fuera.append({
                        "t": max(0.0, inicio + cuando
                                 + hueco * golpe / float(cuantas)),
                        "papel": "tecla", "ficha": ficha,
                        "ganancia": PAPELES["tecla"]["ganancia"]
                        * (0.78 + 0.22 * variacion / 99.0)})
            if palabras and surtido.get("retorno"):
                ficha = elegir(surtido.get("retorno"), semilla, sid,
                               "retorno", vetados_de=prohibidos)
                if ficha:
                    fuera.append({
                        "t": max(0.0, inicio + palabras[-1][0] + 0.32),
                        "papel": "retorno", "ficha": ficha,
                        "ganancia": PAPELES["retorno"]["ganancia"]})
    return sorted(fuera, key=lambda e: e["t"])


# ------------------------------------------------------------------ mezcla

def _a_wav(origen, destino=None) -> str:
    """Decodifica a WAV 48k estéreo. Se cachea al lado del fichero del banco."""
    destino = destino or os.path.splitext(str(origen))[0] + f".{FRECUENCIA}.wav"
    if os.path.exists(destino) and \
            os.path.getmtime(destino) >= os.path.getmtime(origen):
        return destino
    proceso = subprocess.run(
        [comun.ffmpeg(), "-y", "-loglevel", "error", "-i", str(origen),
         "-ac", "2", "-ar", str(FRECUENCIA), "-c:a", "pcm_s16le", destino],
        capture_output=True, text=True, timeout=300)
    if proceso.returncode != 0 or not os.path.exists(destino):
        raise RuntimeError(f"no se pudo decodificar {os.path.basename(str(origen))}: "
                           f"{proceso.stderr[-200:]}")
    return destino


def _leer(ruta):
    """El WAV como float32 estéreo en -1..1."""
    import wave                                        # noqa: PLC0415
    with wave.open(str(ruta), "rb") as fh:
        canales, ancho = fh.getnchannels(), fh.getsampwidth()
        crudo = fh.readframes(fh.getnframes())
    if ancho != 2:
        raise RuntimeError(f"{os.path.basename(str(ruta))}: se esperaba PCM de 16 bits")
    datos = np.frombuffer(crudo, dtype="<i2").astype(np.float32) / 32768.0
    if canales == 1:
        return np.stack([datos, datos], axis=1)
    return datos.reshape(-1, 2)[:, :2]


def _escribir(ruta, muestras) -> str:
    import wave                                        # noqa: PLC0415
    pcm = np.clip(muestras, -1.0, 1.0) * 32767.0
    with wave.open(str(ruta), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(FRECUENCIA)
        fh.writeframes(pcm.astype("<i2").tobytes())
    return str(ruta)


def igualar_por_papel(lista) -> dict:
    """Cuánto hay que corregir cada fichero para que su papel suene parejo.

    -> {ruta: factor} (1.0 = se queda como está). La referencia es la
    MEDIANA de su papel: con ella la clase se queda donde estaba (donde se
    calibró su ganancia de oído) y lo único que desaparece es la
    diferencia. Un fichero que no se puede medir se queda en 1.0.
    """
    por_papel = {}
    for evento in lista or []:
        ficha = evento.get("ficha") or {}
        ruta = banco("efectos", _nombre_de(ficha))
        if not ruta.exists():
            continue
        por_papel.setdefault(str(evento.get("papel") or ""), {}).setdefault(ruta, None)
    factores = {}
    for rutas in por_papel.values():
        niveles = {}
        for ruta in rutas:
            valor = nivel_de(ruta)
            if valor is not None:
                niveles[ruta] = float(valor)
        if len(niveles) < 2:
            continue                # con uno solo no hay con qué compararlo
        referencia = float(np.median(list(niveles.values())))
        for ruta, valor in niveles.items():
            db = max(-EFECTOS_CORRECCION_MAX_DB,
                     min(EFECTOS_CORRECCION_MAX_DB, referencia - valor))
            factores[ruta] = 10.0 ** (db / 20.0)
    return factores


def pista_de_efectos(lista, duracion_s, destino, igualar=True) -> tuple:
    """Suma todos los efectos en un WAV del largo del vídeo.

    En numpy y no con un grafo de ffmpeg: son decenas de eventos y ahí
    cada uno es una entrada y un `adelay` más; aquí es sumar en un buffer.
    """
    total = int(max(1, round(float(duracion_s) * FRECUENCIA)))
    bus = np.zeros((total, 2), dtype=np.float32)
    factores = igualar_por_papel(lista) if igualar else {}
    cache, usados = {}, 0
    for evento in lista or []:
        ficha = evento.get("ficha") or {}
        origen = banco("efectos", _nombre_de(ficha))
        if not origen.exists():
            continue                    # no está en el banco: se calla
        if origen not in cache:
            cache[origen] = _leer(_a_wav(origen))
        muestra = cache[origen]
        inicio = int(round(max(0.0, float(evento.get("t") or 0.0)) * FRECUENCIA))
        if inicio >= total:
            continue
        trozo = muestra[:total - inicio]
        # la corrección del FICHERO multiplica a la ganancia del EVENTO: la
        # primera iguala lo que el banco trae desigual y la segunda es la
        # intención (la clase del papel)
        ganancia = (float(evento.get("ganancia") or 1.0)
                    * factores.get(origen, 1.0))
        bus[inicio:inicio + len(trozo)] += trozo * ganancia
        usados += 1
    pico = float(np.max(np.abs(bus))) if usados else 0.0
    if pico > 0:
        # a pico -6 dBFS: los efectos acompañan, no compiten con la voz
        bus *= (10.0 ** (EFECTOS_PICO_DB / 20.0)) / pico
    _escribir(destino, bus)
    return destino, usados


def filtro_de_mezcla(con_musica, con_efectos, duracion_s, lufs=MUSICA_LUFS,
                     ya_normalizada=False, ajuste_db=0.0, efectos_db=0.0) -> str:
    """El grafo de ffmpeg que junta voz, música agachada y efectos.

    Las entradas son SÓLO audio, en este orden: [0] voz, [1] música (si la
    hay), [2] efectos (si los hay). Las tres pistas se recortan al MISMO
    largo antes de mezclarse.

    `ya_normalizada` es para la CAMA: cada tramo se normalizó por separado
    al montarla — que es lo que evita el salto de volumen al cambiar de
    tema—, así que ahí sólo se ajusta la ganancia calibrada. La subida del
    canal (`MUSICA_SUBIDA_DB`) va con el ajuste del vídeo (`ajuste_db`) en
    la misma suma: es el mando que mueve el repaso cuando alguien dice «la
    música está alta», y moverlo no toca ni una imagen ni un clip.
    """
    partes = ["[0:a]aresample=%d,aformat=channel_layouts=stereo,"
              "apad,atrim=0:%.3f[voz]" % (FRECUENCIA, duracion_s)]
    entradas = ["[vozmix]"]
    if con_musica:
        partes.append("[voz]asplit=2[vozmix][vozllave]")
        subida = MUSICA_SUBIDA_DB + float(ajuste_db or 0.0)
        nivel = (f"volume={CAMA_GANANCIA_DB + subida:g}dB"
                 if ya_normalizada
                 else f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11,"
                      f"volume={subida:g}dB")
        partes.append("[1:a]aresample=%d,aformat=channel_layouts=stereo,"
                      "atrim=0:%.3f,%s[mus]"
                      % (FRECUENCIA, duracion_s, nivel))
        # EL DUCKING, con la llave APLANADA (ver el bloque de constantes)
        partes.append(f"[vozllave]volume={DUCK_LLAVE_SUBIDA_DB:g}dB,"
                      f"alimiter=limit={DUCK_LLAVE_TECHO:g}:attack=5:release=80"
                      f"[llave]")
        partes.append(f"[mus][llave]sidechaincompress=threshold={DUCK_UMBRAL:g}:"
                      f"ratio={DUCK_RATIO:g}:attack={DUCK_ATAQUE_MS:g}:"
                      f"release={DUCK_CAIDA_MS:g}:makeup=1[musduck]")
        entradas.append("[musduck]")
    else:
        partes.append("[voz]anull[vozmix]")
    if con_efectos:
        indice = 2 if con_musica else 1
        # CUÁNTOS EFECTOS, EN ESTE VÍDEO: un número en dB sobre la pista ya
        # montada, detrás del atrim (si se aplicara al escribir el WAV, la
        # normalización a pico -6 dBFS de ahí se lo comería entero)
        try:
            trim = float(efectos_db or 0.0)
        except (TypeError, ValueError):
            trim = 0.0
        partes.append("[%d:a]aresample=%d,aformat=channel_layouts=stereo,"
                      "atrim=0:%.3f%s[sfx]"
                      % (indice, FRECUENCIA, duracion_s,
                         (f",volume={trim:g}dB") if trim else ""))
        entradas.append("[sfx]")
    # `normalize=0` porque amix divide entre el número de entradas: la voz
    # sonaría a un tercio por el hecho de haber puesto música. Y por eso
    # mismo hace falta el limitador detrás: las pistas se SUMAN.
    partes.append("%samix=inputs=%d:duration=first:normalize=0[mezcla]"
                  % ("".join(entradas), len(entradas)))
    partes.append("[mezcla]alimiter=limit=0.95:attack=5:release=50[salida]")
    return ";".join(partes)


def describir(params) -> str:
    """Frase corta con lo que va a sonar, para la pantalla."""
    p = params or {}
    if not p.get("sonido", True):
        return "sin música ni efectos"
    try:
        ajuste = float(p.get("musica_db") or 0.0)
    except (TypeError, ValueError):
        ajuste = 0.0
    trozos = []
    musica = p.get("musica") or {}
    tramos = musica.get("tramos") or []
    if tramos:
        # separador ASCII a propósito: esto acaba en consolas cp1252
        animos = " > ".join(t.get("animo") or "?" for t in tramos)
        trozos.append(f"{len(tramos)} temas encadenados ({animos}) a "
                      f"{MUSICA_LUFS + CAMA_GANANCIA_DB + MUSICA_SUBIDA_DB + ajuste:.1f} "
                      f"LUFS con ducking")
    elif musica.get("id"):
        trozos.append(f"«{musica.get('titulo') or musica['id']}» de "
                      f"{musica.get('artista') or '?'} a "
                      f"{MUSICA_LUFS + MUSICA_SUBIDA_DB + ajuste:.1f} LUFS con ducking")
    surtido = p.get("efectos") or {}
    cuantos = sum(len(v or []) for v in surtido.values())
    if cuantos:
        trozos.append(f"{cuantos} efectos en {len(surtido)} papeles")
    return " · ".join(trozos) if trozos else "sin música ni efectos"
