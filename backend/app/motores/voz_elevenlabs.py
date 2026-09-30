"""Voz: ElevenLabs (sustituye a Cartesia en el original).

Usos:
- `voces()`: catalogo de voces de la cuenta (para elegir en el estilo).
- `hablar()`: TTS de una narracion -> mp3 en disco + duracion.
- `hablar_con_marcas()`: TTS con alineacion por caracter -> marcas de tiempo
  por palabra. Es lo que permite repasar el guion contra el audio y medir la
  duracion real de cada seccion sin estimaciones.

Endpoint: https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps
Modelo por defecto: eleven_multilingual_v2 (espanol natural). Para borradores
internos se puede usar eleven_flash (mas barato y rapido).
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

TIEMPO_FUERA_S = 300
BASE = "https://api.elevenlabs.io/v1"

MODELOS = {
    "multilingual": "eleven_multilingual_v2",
    "flash": "eleven_flash_v2_5",
    "v3": "eleven_v3",
}

#: Limite de la API por peticion; las narraciones largas se parten por
#: frases y se concatenan las marcas.
TOPE_CARACTERES = 4500


class ErrorVoz(RuntimeError):
    """Fallo de ElevenLabs con texto para humano."""


def clave(claves: dict | None = None) -> str:
    if claves and claves.get("elevenlabs"):
        return str(claves["elevenlabs"])
    return os.environ.get("ESTUDIO_ELEVENLABS_KEY", "")


def _cabeceras(clave_: str) -> dict:
    return {"xi-api-key": clave_, "Content-Type": "application/json"}


def voces(claves: dict | None = None) -> list[dict]:
    """Voces disponibles: [{voice_id, nombre, idiomas, etiquetas}]."""
    clave_ = clave(claves)
    if not clave_:
        return []
    try:
        respuesta = requests.get(f"{BASE}/voices",
                                 headers=_cabeceras(clave_), timeout=30)
        if respuesta.status_code != 200:
            raise ErrorVoz(f"{respuesta.status_code}: {respuesta.text[:200]}")
        lista = []
        for voz in respuesta.json().get("voices", []):
            lista.append({
                "voice_id": voz.get("voice_id", ""),
                "nombre": voz.get("name", ""),
                "etiquetas": voz.get("labels", {}) or {},
                "idiomas": [p.get("language_id", "")
                            for p in voz.get("fine_tuning", {})
                            .get("language", []) or []],
            })
        return lista
    except requests.RequestException as fallo:
        raise ErrorVoz(f"red: {fallo}") from fallo


def probar(claves: dict | None = None) -> dict:
    """Prueba de clave sin coste: leer el catalogo de voces."""
    clave_ = clave(claves)
    if not clave_:
        return {"ok": False, "detalle": "sin clave"}
    try:
        respuesta = requests.get(f"{BASE}/user", headers=_cabeceras(clave_),
                                 timeout=30)
        if respuesta.status_code == 200:
            cuota = respuesta.json().get("subscription", {})
            return {"ok": True,
                    "detalle": f"cuota {cuota.get('character_count', '?')}/"
                               f"{cuota.get('character_limit', '?')}"}
        return {"ok": False,
                "detalle": f"{respuesta.status_code}: {respuesta.text[:200]}"}
    except requests.RequestException as fallo:
        return {"ok": False, "detalle": f"red: {fallo}"}


def _modelo_de(nombre: str) -> str:
    return MODELOS.get(nombre, nombre if nombre.startswith("eleven")
                       else MODELOS["multilingual"])


def hablar(narracion: str, voz: str, destino: Path, claves: dict | None = None,
           modelo: str = "multilingual", estabilidad: float = 0.5,
           similitud: float = 0.75, velocidad: float = 1.0) -> Path:
    """Genera el audio de una narracion entera y lo escribe en `destino`.

    Devuelve la ruta. La duracion se lee despues con ffprobe (voz.__len__).
    """
    mp3, _marcas = _generar(narracion, voz, claves, modelo, estabilidad,
                            similitud, velocidad, con_marcas=False)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(mp3)
    return destino


def hablar_con_marcas(narracion: str, voz: str, destino: Path,
                      claves: dict | None = None,
                      modelo: str = "multilingual", estabilidad: float = 0.5,
                      similitud: float = 0.75,
                      velocidad: float = 1.0) -> dict:
    """Genera audio + marcas de tiempo por palabra.

    Devuelve {"ruta": Path, "duracion": float, "palabras": [
        {"palabra": str, "inicio": s, "fin": s}, ...]}
    """
    mp3, marcas = _generar(narracion, voz, claves, modelo, estabilidad,
                           similitud, velocidad, con_marcas=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(mp3)
    duracion = marcas.get("audio_duration") or 0.0
    # _generar ya rebana la alineacion por caracter en palabras (trozo a
    # trozo, con su desplazamiento): esas son las marcas. (Llamar aqui a
    # _palabras_de con este dict devolvia [] siempre: sin las columnas de
    # alineacion cruda, la voz llegaba SIN marcas y todo lo que cuelga de
    # ellas —planos por escena, subtitulos— se quedaba sin combustible.)
    palabras = marcas.get("palabras") or []
    return {"ruta": destino, "duracion": round(duracion, 3), "palabras": palabras}


def _palabras_de(marcas: dict, narracion: str) -> list[dict]:
    """Convierte la alineacion por caracter en marcas por palabra."""
    inicios = marcas.get("character_start_times_seconds") or []
    finales = marcas.get("character_end_times_seconds") or []
    texto = marcas.get("normalized_text") or narracion
    if len(inicios) < len(texto) or len(finales) < len(texto):
        return []
    palabras, actual, arranque = [], "", None
    for indice, caracter in enumerate(texto):
        if caracter.isspace():
            if actual and arranque is not None:
                palabras.append({"palabra": actual, "inicio": arranque,
                                 "fin": finales[indice - 1]})
            actual, arranque = "", None
        else:
            if arranque is None:
                arranque = inicios[indice]
            actual += caracter
    if actual and arranque is not None:
        palabras.append({"palabra": actual, "inicio": arranque,
                         "fin": finales[len(texto) - 1]})
    return [{"palabra": p["palabra"], "inicio": round(p["inicio"], 3),
             "fin": round(p["fin"], 3)} for p in palabras]


def _partir(narracion: str) -> list[str]:
    """Parte narraciones largas en trozos por debajo del tope, por frases."""
    texto = narracion.strip()
    if len(texto) <= TOPE_CARACTERES:
        return [texto]
    trozos, actual = [], ""
    import re
    frases = re.split(r"(?<=[.!?;:])\s+", texto)
    for frase in frases:
        if len(actual) + len(frase) + 1 > TOPE_CARACTERES and actual:
            trozos.append(actual.strip())
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


def _generar(narracion: str, voz: str, claves: dict | None, modelo: str,
             estabilidad: float, similitud: float, velocidad: float,
             con_marcas: bool) -> tuple[bytes, dict]:
    clave_ = clave(claves)
    if not clave_:
        raise ErrorVoz("falta la clave de ElevenLabs "
                       "(ESTUDIO_ELEVENLABS_KEY o secretos/claves.json)")
    trozos = _partir(narracion)
    audio_total, palabras_total, duracion_total = b"", [], 0.0
    for trozo in trozos:
        url = (f"{BASE}/text-to-speech/{voz}/with-timestamps" if con_marcas
               else f"{BASE}/text-to-speech/{voz}")
        cuerpo = {
            "text": trozo,
            "model_id": _modelo_de(modelo),
            "voice_settings": {
                "stability": estabilidad,
                "similarity_boost": similitud,
                "speed": velocidad,
            },
        }
        try:
            respuesta = requests.post(
                url, headers=_cabeceras(clave_), params={
                    "output_format": "mp3_44100_128"},
                json=cuerpo, timeout=TIEMPO_FUERA_S)
        except requests.RequestException as fallo:
            raise ErrorVoz(f"red: {fallo}") from fallo
        if respuesta.status_code != 200:
            raise ErrorVoz(f"ElevenLabs {respuesta.status_code}: "
                           f"{respuesta.text[:200]}")
        if con_marcas:
            cuerpo_json = respuesta.json()
            audio = base64.b64decode(cuerpo_json.get("audio_base64", ""))
            marcas = cuerpo_json.get("normalized_alignment") or \
                cuerpo_json.get("alignment") or {}
            desplazamiento = duracion_total
            for palabra in _palabras_de(marcas, trozo):
                palabras_total.append({
                    "palabra": palabra["palabra"],
                    "inicio": round(palabra["inicio"] + desplazamiento, 3),
                    "fin": round(palabra["fin"] + desplazamiento, 3)})
            duracion_total += float(marcas.get("audio_duration")
                                    or _durar(audio))
        else:
            audio = respuesta.content
        audio_total += audio
    if con_marcas:
        return audio_total, {"audio_duration": duracion_total,
                             "palabras": palabras_total}
    return audio_total, {}


def _durar(mp3: bytes) -> float:
    """Duracion aproximada de un mp3 en bytes sin ffprobe (por si acaso)."""
    # 128 kbps -> 16 KB/s; suficiente como ultimo recurso de respaldo
    return len(mp3) / 16000.0


def personajes_de(claves: dict | None = None) -> int:
    """Caracteres consumidos/limite de la suscripcion (para la UI)."""
    clave_ = clave(claves)
    if not clave_:
        return 0
    try:
        respuesta = requests.get(f"{BASE}/user", headers=_cabeceras(clave_),
                                 timeout=30)
        sub = respuesta.json().get("subscription", {})
        return int(sub.get("character_count", 0))
    except (requests.RequestException, ValueError):
        return 0


# ------------------------------------------------- toma continua (del original)
#
# Lo que sigue se porto de motores/voz_cartesia/voz.py: sintetizar el video
# ENTERO en una toma y ensanchar despues los silencios entre escenas con
# ruido de sala. Sintetizar escena a escena suena a robot leyendo una lista:
# cada frase arranca en frio, sin memoria de la anterior, y en el montaje se
# oyen los empalmes. Con una toma unica la entonacion fluye de una escena a
# la siguiente y los cortes se deducen de las marcas de palabra, que son
# exactas.

SR = 44100

#: Milisegundos de fundido al pegar el relleno. Sin esto, el salto de
#: amplitud en el empalme suena como un chasquido, que es peor que el
#: problema original.
FUNDIDO_MS = 12


def wav_de_pcm(pcm: bytes) -> bytes:
    """Cabecera WAV PCM s16le mono sobre PCM crudo."""
    import struct
    cabecera = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    cabecera += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
    cabecera += b"data" + struct.pack("<I", len(pcm))
    return cabecera + pcm


def pcm_de_mp3(mp3: bytes, ffmpeg: str = "ffmpeg") -> bytes:
    """Decodifica audio (mp3) a PCM s16le mono 44.1k para poder trocearlo.

    El espaciado trabaja sobre PCM crudo: insertar bytes en mitad de un mp3
    no es posible sin re-codificar. ffmpeg autodetecta el formato de
    entrada, asi que tambien traga el wav que dejan algunas pruebas.
    """
    import subprocess
    proceso = subprocess.run(
        [ffmpeg, "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le",
         "-ac", "1", "-ar", str(SR), "pipe:1"],
        input=mp3, capture_output=True, timeout=600)
    if proceso.returncode != 0 or not proceso.stdout:
        raise ErrorVoz(f"decodificar audio: "
                       f"{proceso.stderr.decode('utf-8', 'ignore')[-300:]}")
    return proceso.stdout


def _relleno_de_sala(pcm: bytes, desde_seg: float, hasta_seg: float,
                     duracion: float) -> bytes:
    """Ruido de sala para rellenar un hueco, sacado de la PROPIA pausa.

    Antes se insertaban ceros. Una toma continua tiene su suelo de ruido, y
    cortarlo a cero durante mas de un segundo se oye como un corte: el
    fondo desaparece de golpe y vuelve. Con muchas escenas y un segundo de
    hueco eran decenas de segundos de vacio digital, uno en cada frontera.

    La mejor muestra de ruido de sala es la de la pausa que se esta
    ensanchando, asi que se toma de ahi y se repite. Se alterna con su
    reverso para que la repeticion no cree un patron audible.
    """
    bytes_por_seg = SR * 2
    necesarios = int(duracion * bytes_por_seg) & ~1
    if necesarios <= 0:
        return b""
    # semilla: el centro de la pausa natural, hasta 200 ms
    ancho = max(0.0, hasta_seg - desde_seg)
    if ancho < 0.04:
        return b"\x00" * necesarios      # no hay pausa de la que sacar nada
    toma = min(0.2, ancho * 0.8)
    centro = (desde_seg + hasta_seg) / 2.0
    ini = int((centro - toma / 2) * bytes_por_seg) & ~1
    fin = (ini + (int(toma * bytes_por_seg) & ~1))
    semilla = pcm[max(0, ini):min(len(pcm), fin)]
    if len(semilla) < 4:
        return b"\x00" * necesarios

    reverso = semilla[::-1]
    # el reverso de un buffer de bytes invierte tambien los dos bytes de
    # cada muestra: se rehace por pares para que siga siendo audio y no
    # ruido blanco
    reverso = b"".join(reverso[i:i + 2][::-1]
                       for i in range(0, len(reverso) - 1, 2))
    trozos, largo, vuelta = [], 0, 0
    while largo < necesarios:
        pieza = semilla if vuelta % 2 == 0 else reverso
        trozos.append(pieza)
        largo += len(pieza)
        vuelta += 1
    relleno = bytearray(b"".join(trozos)[:necesarios])

    # fundido de entrada y de salida sobre el relleno
    muestras = FUNDIDO_MS * SR // 1000
    for i in range(min(muestras, len(relleno) // 2)):
        factor = i / muestras
        for pos in (i * 2, len(relleno) - 2 - i * 2):
            valor = int.from_bytes(relleno[pos:pos + 2], "little", signed=True)
            relleno[pos:pos + 2] = int(
                valor * factor).to_bytes(2, "little", signed=True)
    return bytes(relleno)


def espaciar(pcm: bytes, reparto: dict, hueco_minimo: float = 1.0,
             orden: list | None = None) -> tuple[bytes, list]:
    """Ensancha los silencios ENTRE escenas sin re-sintetizar nada.

    Una lectura continua encadena las frases con pausas cortas. Trocear la
    sintesis lo arreglaria pero devolveria el problema de origen: cada
    frase arrancando en frio. Aqui se conserva la toma tal cual y solo se
    estira el silencio en los cortes, asi que la prosodia queda intacta.

    `reparto` es {escena_id: [palabra, ...]} con marcas en el reloj de la
    TOMA; `orden` (por defecto, el de insercion) dice que escena va antes.

    Devuelve (pcm_nuevo, desplazamientos): el retardo acumulado a aplicar
    a cada marca segun el instante en que caiga.
    """
    bytes_por_seg = SR * 2
    ids = list(orden) if orden is not None else list(reparto)
    con_voz = [sid for sid in ids if reparto.get(sid)]

    # Cortes: (instante original, silencio a insertar, pausa natural)
    cortes = []
    for anterior, siguiente in zip(con_voz, con_voz[1:]):
        fin = reparto[anterior][-1]["fin"]
        inicio = reparto[siguiente][0]["inicio"]
        falta = hueco_minimo - (inicio - fin)
        if falta > 0.01:
            cortes.append((fin + (inicio - fin) / 2, falta, fin, inicio))

    if not cortes:
        return pcm, []

    trozos, anterior_byte, acumulado = [], 0, 0.0
    desplazamientos = []
    for instante, silencio, desde, hasta in cortes:
        corte_byte = int(instante * bytes_por_seg) & ~1   # alineado a muestra
        trozos.append(pcm[anterior_byte:corte_byte])
        trozos.append(_relleno_de_sala(pcm, desde, hasta, silencio))
        anterior_byte = corte_byte
        acumulado += silencio
        desplazamientos.append(
            {"desde": instante, "retardo": round(acumulado, 3)})
    trozos.append(pcm[anterior_byte:])

    return b"".join(trozos), desplazamientos


def aplicar_desplazamiento(instante: float, desplazamientos: list) -> float:
    """El instante con el retardo acumulado que le toca."""
    retardo = 0.0
    for d in desplazamientos:
        if instante >= d["desde"]:
            retardo = d["retardo"]
    return round(instante + retardo, 3)


def _normalizar(palabra: str) -> str:
    import re as _re
    return _re.sub(r"[^\wáéíóúüñ]", "", palabra.lower())


def repartir_palabras(escenas: list, palabras: list) -> dict:
    """Asigna a cada escena el tramo de marcas que le corresponde.

    Se recorre la lista devuelta por el motor en orden y se van consumiendo
    las palabras de cada escena (la narracion LIMPIA, sin etiquetas). Se
    compara normalizado porque el modelo puede devolver la puntuacion
    pegada o separada, y un desajuste de un token desplazaria todos los
    cortes siguientes. Ventana de tolerancia de 3 por si parte o une.
    """
    reparto: dict[str, list] = {}
    i = 0
    for escena in escenas:
        esperadas = [_normalizar(p) for p in
                     str(escena.get("narracion") or "").split()]
        esperadas = [p for p in esperadas if p]
        tramo = []
        for esperada in esperadas:
            j = i
            while j < min(i + 3, len(palabras)):
                if _normalizar(palabras[j]["palabra"]) == esperada:
                    break
                j += 1
            if j < min(i + 3, len(palabras)):
                tramo.extend(palabras[i:j + 1])
                i = j + 1
            elif i < len(palabras):
                tramo.append(palabras[i])
                i += 1
        reparto[escena.get("id") or ""] = tramo
    # Lo que sobre se cuelga de la ultima escena con texto
    if i < len(palabras) and reparto:
        con_texto = [e.get("id") for e in escenas
                     if str(e.get("narracion") or "").strip()]
        if con_texto:
            reparto[con_texto[-1]].extend(palabras[i:])
    return reparto

