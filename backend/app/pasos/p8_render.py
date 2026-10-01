"""Paso 8 — render: compone el vídeo con ffmpeg.

Por escena (duracion = la REAL de su audio):
1. La imagen del plano se anima con un movimiento de camara suave
   (zoompan Ken Burns, alternando acercarse/alejarse por escena).
2. Los subtitulos (si los hay) entran trozo a trozo en su instante,
   en la banda del pie del cuadro, quietos (PNG de PIL con fundido).
3. El audio de la escena viaja con el segmento.

Despues, dos caminos:
    sin extras     concat de segmentos (mismos codecs, sin recodificar) y
                   masterizacion loudnorm en dos pasadas.
    con sonido     la voz se concatena aparte y se mezcla con la musica
                   (cama o tema suelto, con ducking de llave aplanada) y
                   los efectos (pista numpy igualada por papel), todo segun
                   `sonido.filtro_de_mezcla`; el video se une con las
                   TRANSICIONES que reparte `transiciones.resolver`
                   (xfade de ffmpeg, determinista por semilla).

Sin shell=True en NINGUNA llamada: listas de argumentos siempre
(docs/AUDITORIA.md H2).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from ..config import AJUSTES
from ..nucleo import grafismo
from ..nucleo.proyecto import Proyecto
from . import (cartelas, comun, p2_brief, p4_voz, sonido, subtitulos,
               transiciones)

FPS = 30
ANCHO, ALTO = 1920, 1080
CALIDADES = {"borrador": {"preset": "veryfast", "crf": "26"},
             "estandar": {"preset": "medium", "crf": "22"},
             "detalle": {"preset": "slow", "crf": "18"}}

#: La banda del subtítulo: el pie del cuadro, QUIETA (fuera del zoom).
#: Mismo margen y mismo ancho que `subtitulos.banda_fija`.
SUB_MARGEN = 72
SUB_ANCHO = 1400
#: El fundido del trozo: entra en 0,32 s y sale en 0,30 (del original).
SUB_ENTRADA = 0.32
SUB_SALIDA = 0.30

#: fuentes candidatas para los rotulos (contenedor trae DejaVu)
FUENTES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def params_defecto() -> dict:
    return {"calidad": "estandar", "resolucion": "1920x1080", "fps": FPS,
            # sonido: lo que se decidió una vez en la pantalla de Sonido y
            # viaja en los params del render (la firma sólo del render)
            "sonido": True, "musica": {}, "musica_lufs": sonido.MUSICA_LUFS,
            "musica_db": 0.0, "efectos_db": 0.0, "efectos": {},
            "transiciones": [], "duracion_transicion": 0.4}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


def _fuente() -> str:
    for fuente in FUENTES:
        if Path(fuente).is_file():
            return fuente
    return ""


def _color(valor) -> tuple:
    """Un color de la paleta ('#eab308' o 'rgba(10,12,16,0.78)') a tupla PIL."""
    import re
    texto = str(valor or "").strip()
    if texto.startswith("rgba"):
        numeros = re.findall(r"[\d.]+", texto)
        if len(numeros) >= 3:
            alpha = int(float(numeros[3]) * 255) if len(numeros) > 3 else 255
            return (int(float(numeros[0])), int(float(numeros[1])),
                    int(float(numeros[2])), alpha)
    else:
        texto = texto.lstrip("#")
        if len(texto) >= 6:
            return (int(texto[0:2], 16), int(texto[2:4], 16),
                    int(texto[4:6], 16), 255)
    return (10, 12, 16, 190)


def _fuente_de(tamano: int):
    from PIL import ImageFont
    ruta = _fuente()
    return (ImageFont.truetype(ruta, tamano) if ruta
            else ImageFont.load_default())


def _rotulo_png(texto: str, destino: Path, ancho_max: int = 1400,
                diseno: str = "pastilla", paleta: dict | None = None,
                tam=1.0, lienzo: int = ANCHO) -> Path:
    """Dibuja el rotulo con el SET DE DISENO y la paleta del vídeo.

    Es el mismo dibujo que grafismo.svg_rotulo (la pantalla ensena el
    SVG, el render paga el PNG): que difieran seria una pantalla que
    miente. `lienzo` es el ancho del cuadro de SALIDA (el 9:16 vertical
    centra sus rótulos en menos ancho).
    """
    from PIL import Image, ImageDraw
    from ..nucleo import grafismo
    paleta = paleta or dict(grafismo.PALETA_DEFECTO)
    caja = grafismo.SETS_DISENO.get(diseno,
                                     grafismo.SETS_DISENO["pastilla"])["caja"]
    escala = (grafismo.tamano_de(tam) if isinstance(tam, str)
              else float(tam or 1.0))
    tamano = int(64 * escala)
    fuente = _fuente_de(tamano)
    # partir en lineas midiendo de verdad (no a ojo de caracteres)
    prueba = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lineas, actual = [], ""
    for palabra in str(texto or "").split():
        candidata = f"{actual} {palabra}".strip()
        if prueba.textbbox((0, 0), candidata, font=fuente)[2] > ancho_max \
                and actual:
            lineas.append(actual)
            actual = palabra
        else:
            actual = candidata
    if actual:
        lineas.append(actual)
    alto_linea = tamano + 26
    margen = 30
    imagen = Image.new("RGBA", (lienzo,
                                len(lineas) * alto_linea + 2 * margen),
                       (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    velo = _color(paleta.get("velo"))
    acento = _color(paleta.get("acento"))
    tinta = _color(paleta.get("texto"))
    y = margen
    for linea in lineas:
        bbox = dibujo.textbbox((0, 0), linea, font=fuente)
        ancho_linea = bbox[2] - bbox[0]
        x0 = (lienzo - ancho_linea) // 2
        if caja == "pastilla":
            dibujo.rounded_rectangle(
                [x0 - 28, y - 10, x0 + ancho_linea + 28, y + tamano + 14],
                radius=18, fill=velo)
        elif caja == "barra":
            dibujo.rectangle([x0 - 28, y - 10, x0 - 20, y + tamano + 14],
                             fill=acento)
        elif caja == "pleno":
            dibujo.rectangle([0, y - 10, lienzo, y + tamano + 14], fill=velo)
            dibujo.rectangle([0, y - 10, 14, y + tamano + 14], fill=acento)
        else:  # sombra: sin caja, texto claro con sombra suave
            sombra = tuple(max(0, c - 60) for c in tinta[:3]) + (170,)
            dibujo.text((x0 + 3, y + 4), linea, font=fuente, fill=sombra)
        dibujo.text((x0, y), linea, font=fuente, fill=tinta)
        y += alto_linea
    caja_real = imagen.getbbox()
    if caja_real:
        imagen = imagen.crop(caja_real)
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino)
    return destino


def _subtitulo_png(texto: str, destino: Path, paleta: dict | None = None,
                   tam: str = "normal", diseno: str = "pastilla",
                   ancho_max: int = SUB_ANCHO,
                   lienzo: int = ANCHO, escala: float = 1.0) -> Path | None:
    """Un TROZO de subtítulo dibujado: una o dos líneas PAREJAS, en caja.

    El reparto de líneas lo decide `subtitulos.dos_lineas` midiendo con
    la fuente de verdad (llenar la primera y dejar huérfana la última
    canta en un bloque centrado), y la caja es UNA por trozo, no una por
    renglón: dos cajas de anchos distintos apiladas dibujan un escalón
    y eso convierte un subtítulo en un cartel. El texto se ancla por
    abajo en el overlay (y=H-h-margen), así que un trozo de una línea y
    otro de dos acaban a la misma altura.

    `escala` es la del formato (`subtitulos.escala_subtitulo`): en
    vertical el cuerpo crece con la pantalla, y quien troceó contó con
    ese cuerpo — dibujarlo más pequeño aquí partiría la calibración.
    """
    from PIL import Image, ImageDraw
    from ..nucleo import grafismo
    paleta = paleta or dict(grafismo.PALETA_DEFECTO)
    caja = grafismo.SETS_DISENO.get(diseno,
                                     grafismo.SETS_DISENO["pastilla"])["caja"]
    tamano = int(52 * grafismo.tamano_de(tam) * escala)
    fuente = _fuente_de(tamano)
    prueba = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    def medir(cadena: str) -> int:
        return prueba.textbbox((0, 0), cadena, font=fuente)[2]

    lineas = subtitulos.dos_lineas(texto, medir, ancho_max)
    if not lineas:
        return None
    salto = int(tamano * 1.28)
    aire_x, aire_y = int(tamano * 0.62), int(tamano * 0.24)
    ancho_texto = max(medir(linea) for linea in lineas)
    ancho = lienzo if caja == "pleno" else ancho_texto + 2 * aire_x
    alto = 2 * aire_y + salto * (len(lineas) - 1) + tamano + tamano // 4
    imagen = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    velo = _color(paleta.get("velo"))
    acento = _color(paleta.get("acento"))
    tinta = _color(paleta.get("texto"))
    if caja == "sombra":
        pass          # sin caja: texto claro con sombra suave, dos capas
    elif caja == "pleno":
        dibujo.rectangle([0, 0, ancho, alto], fill=velo)
        dibujo.rectangle([0, 0, 14, alto], fill=acento)
    elif caja == "barra":
        dibujo.rounded_rectangle([0, 0, ancho, alto], radius=4, fill=velo)
        dibujo.rectangle([aire_x // 2, aire_y // 2, aire_x // 2 + 8,
                          alto - aire_y // 2], fill=acento)
    else:             # pastilla: la caja ligera del canal
        dibujo.rounded_rectangle([0, 0, ancho, alto], radius=18, fill=velo)
    y = aire_y
    for linea in lineas:
        bbox = dibujo.textbbox((0, 0), linea, font=fuente)
        x0 = (ancho - (bbox[2] - bbox[0])) // 2 - bbox[0]
        if caja == "sombra":
            sombra = tuple(max(0, c - 60) for c in tinta[:3]) + (170,)
            dibujo.text((x0 + 3, y + 4), linea, font=fuente, fill=sombra)
        dibujo.text((x0, y), linea, font=fuente, fill=tinta)
        y += salto
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino)
    return destino


def _ventanas_trozos(trozos: list, duracion: float) -> list:
    """[(texto, desde, dura)] — las ventanas saneadas de los trozos.

    Pura (sin ffmpeg), para poder probar el ritmo sin renderizar: cada
    trozo queda DENTRO del plano y con duración suficiente para que el
    fundido no se coma el texto.
    """
    salida = []
    for trozo in trozos or []:
        if not isinstance(trozo, dict):
            continue
        texto = " ".join(str(trozo.get("texto") or "").split())
        if not texto:
            continue
        desde = max(0.0, float(trozo.get("desde") or 0.0))
        hasta = max(desde, float(trozo.get("hasta") or desde))
        desde = min(desde, max(0.0, duracion - 0.3))
        hasta = min(max(hasta, desde + 0.3), duracion)
        if hasta - desde < 0.3:
            continue
        salida.append((texto, round(desde, 3), round(hasta - desde, 3)))
    return salida


def _segmento(proyecto: Proyecto, plano: dict, escena: dict,
              trozos: list | None, destino: Path, calidad: str, trabajo,
              cfg_grafismo: dict | None = None,
              tamano: tuple | None = None,
              sub_ancho: int = SUB_ANCHO) -> Path:
    """Un segmento de vídeo: imagen animada + subtítulos + su audio.

    El plano lleva su ventana `t_in`/`t_out` DENTRO del audio de la
    escena (el corte de `segmentar`): el audio se corta a esa ventana y
    la imagen dura lo mismo. El plano de CARTELA se pinta FOTOGRAMA A
    FOTOGRAMA — el texto se escribe al ritmo de la voz, sobre la imagen
    del plano con su velo y su Ken Burns (los tiempos los dejó p6 en
    `escritura`) — y no lleva subtítulo (la cartela ES el texto).

    Los TROZOS de subtítulo llegan en reloj del plano (los dejó p7 con
    las marcas de la voz): cada uno es un PNG con su fundido, montado a
    la banda del pie, quieto — fuera del zoom.

    `tamano` es el cuadro de SALIDA (el 9:16 vertical monta sus planos
    a 1080x1920) y `sub_ancho` el ancho de la banda del subtítulo en
    ese cuadro.
    """
    ancho, alto = tamano or (ANCHO, ALTO)
    cfg = cfg_grafismo or {}
    audio = proyecto.ruta(escena["audio"])
    t_in = max(0.0, float(plano.get("t_in") or 0.0))
    t_out = float(plano.get("t_out") or 0.0) \
        or float(escena["duracion"])
    duracion = max(0.1, t_out - t_in)
    ajustes = CALIDADES.get(calidad, CALIDADES["estandar"])
    cartela = plano.get("cartela")
    if cartela:
        escritura = plano.get("escritura") if isinstance(
            plano.get("escritura"), dict) else {}
        zoom_cfg = plano.get("zoom") if isinstance(plano.get("zoom"), dict) \
            else None
        par_zoom = ((float(zoom_cfg["de"]), float(zoom_cfg["a"]))
                    if zoom_cfg and zoom_cfg.get("de") is not None
                    and zoom_cfg.get("a") is not None else None)
        base = (proyecto.ruta(plano["imagen"])
                if plano.get("imagen") else None)
        fotogramas = destino.parent / f"{plano['id']}_frames"
        trabajo.avance(f"cartela {plano['id']}: fotograma a fotograma")
        cartelas.secuencia(
            fotogramas, cartela, duracion, fps=FPS,
            paleta=cfg.get("paleta"), semilla=_semilla_de(proyecto),
            tiempos=escritura.get("tiempos") or None,
            base=base, zoom=par_zoom, tamano=(ancho, alto))
        orden = [comun.ffmpeg(), "-y", "-loglevel", "error",
                 "-framerate", str(FPS), "-i",
                 str(fotogramas / "f%05d.png"),
                 "-ss", f"{t_in:.3f}", "-t", f"{duracion:.3f}",
                 "-i", str(audio),
                 "-vf", "setsar=1", "-r", str(FPS),
                 "-map", "0:v", "-map", "1:a",
                 "-c:v", "libx264", "-preset", ajustes["preset"],
                 "-crf", ajustes["crf"], "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{duracion:.3f}", str(destino)]
        proceso = subprocess.run(orden, capture_output=True, text=True,
                                 timeout=1800)
        if proceso.returncode != 0 or not destino.exists():
            raise RuntimeError(f"ffmpeg fallo en {plano['id']}: "
                               f"{proceso.stderr[-400:]}")
        return destino
    imagen = proyecto.ruta(plano["imagen"])
    # el zoom del PLAN (segmentar.alternar_zoom: acercar/alejar alternado,
    # un cierre sutil de 95 % que empuja sin que se vea empujar)
    zoom_cfg = plano.get("zoom") if isinstance(plano.get("zoom"), dict) \
        else None
    if zoom_cfg and zoom_cfg.get("de") is not None \
            and zoom_cfg.get("a") is not None:
        de, hasta = float(zoom_cfg["de"]), float(zoom_cfg["a"])
    else:
        # planos viejos sin plan: alterna por hash, como siempre
        hasta = 1.09 if hash(plano["id"]) % 2 == 0 else 1.0
        de = 1.0 if hasta > 1.0 else 1.09
    rampa = f"{de}+({hasta}-{de})*on/({duracion:g}*{FPS})"
    if hasta >= de:
        zoom = f"'min({rampa},{max(de, hasta)})'"
    else:
        zoom = f"'max({rampa},{min(de, hasta)})'"
    filtros = [
        # escalar de mas y encoger con zoompan: sin escalones
        f"scale={ancho * 2}:{alto * 2}",
        f"zoompan=z={zoom}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={ancho}x{alto}:fps={FPS}",
        "setsar=1",
    ]
    orden = [comun.ffmpeg(), "-y", "-loglevel", "error",
             "-loop", "1", "-t", f"{duracion:.3f}", "-i", str(imagen),
             "-ss", f"{t_in:.3f}", "-t", f"{duracion:.3f}", "-i", str(audio)]
    base = f"[0:v]{','.join(filtros)}"
    ventanas = _ventanas_trozos(trozos or [], duracion)
    if ventanas:
        # el cuerpo del subtítulo crece con la pantalla en vertical, y
        # la banda sube a un tercio: en un móvil el pie lo tapan los
        # controles y la mirada está en el centro (`subtitulos.escala_
        # subtitulo` y `banda_fija`, las mismas cuentas que troceó p7)
        sub_escala = subtitulos.escala_subtitulo((ancho, alto))
        y_sub = ("2*H/3-h" if subtitulos.es_vertical((ancho, alto))
                 else f"H-h-{SUB_MARGEN}")
        # un PNG por trozo, encadenados sobre la banda del pie; el audio
        # es SIEMPRE la entrada 1 (los PNGs entran detrás)
        partes, previo, entrada = [], "[base]", 2
        for k, (texto, desde, dura) in enumerate(ventanas):
            # la alfa del velo es cosa SOLO del subtítulo (`subtitulo_caja`
            # en los datos de callouts): la paleta la comparten cartelas y
            # rótulo, y este mando no quiere tocarlos
            paleta_sub = cfg.get("paleta")
            if cfg.get("subtitulo_caja") not in (None, "auto"):
                paleta_sub = grafismo.con_opacidad(paleta_sub or {},
                                                   cfg["subtitulo_caja"])
            png = _subtitulo_png(
                texto, destino.parent / f"{plano['id']}_sub{k + 1}.png",
                paleta=paleta_sub, tam=cfg.get("tam", "normal"),
                diseno=cfg.get("diseno", "pastilla"),
                ancho_max=sub_ancho, lienzo=ancho, escala=sub_escala)
            if png is None:
                continue
            orden += ["-loop", "1", "-t", f"{dura:.3f}", "-i", str(png)]
            entra = min(SUB_ENTRADA, dura / 3)
            sale = min(SUB_SALIDA, dura / 3)
            partes.append(
                f"[{entrada}:v]format=rgba,"
                f"fade=t=in:st=0:d={entra:.2f}:alpha=1,"
                f"fade=t=out:st={dura - sale:.2f}:d={sale:.2f}:alpha=1,"
                f"setpts=PTS+{desde:.3f}/TB[s{k}];"
                f"{previo}[s{k}]overlay=x=(W-w)/2:y={y_sub}"
                f":shortest=0[o{k}]")
            previo = f"[o{k}]"
            entrada += 1
        if partes:
            grafo = f"{base}[base];" + ";".join(partes)
            etiqueta_salida = previo
        else:
            grafo = f"{base}[v]"
            etiqueta_salida = "[v]"
        indice_audio = "1:a"
    else:
        grafo = f"{base}[v]"
        etiqueta_salida = "[v]"
        indice_audio = "1:a"
    orden += ["-filter_complex", grafo,
              "-map", etiqueta_salida, "-map", indice_audio,
              "-c:v", "libx264", "-preset", ajustes["preset"],
              "-crf", ajustes["crf"], "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k",
              "-t", f"{duracion:.3f}", str(destino)]
    proceso = subprocess.run(orden, capture_output=True, text=True,
                             timeout=1800)
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(f"ffmpeg fallo en {plano['id']}: "
                           f"{proceso.stderr[-400:]}")
    return destino


def _voz_wav(proyecto: Proyecto, voz: dict, destino: Path) -> Path:
    """Concatena los audios de escena en un WAV 48k estéreo.

    Con N entradas y `concat` de filtro (no del demuxor): los TTS pueden
    venir mezclados en frecuencia y el demuxor exige ficheros idénticos.
    """
    rutas = [proyecto.ruta(e["audio"]) for e in voz["escenas"]]
    orden = [comun.ffmpeg(), "-y", "-loglevel", "error"]
    for ruta in rutas:
        orden += ["-i", str(ruta)]
    trozos = [f"[{i}:a]aresample={sonido.FRECUENCIA},"
              f"aformat=channel_layouts=stereo[a{i}]"
              for i in range(len(rutas))]
    grafo = ";".join(trozos + ["".join(f"[a{i}]" for i in range(len(rutas)))
                               + f"concat=n={len(rutas)}:v=0:a=1[voz]"])
    orden += ["-filter_complex", grafo, "-map", "[voz]",
              "-c:a", "pcm_s16le", str(destino)]
    proceso = subprocess.run(orden, capture_output=True, text=True,
                             timeout=3600)
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(f"fallo al concatenar la voz: {proceso.stderr[-400:]}")
    return destino


def _medir_master(ruta: Path) -> dict | None:
    """La primera pasada del master: mide, no toca. None si no sale."""
    proceso = subprocess.run(
        [comun.ffmpeg(), "-hide_banner", "-nostats", "-i", str(ruta),
         "-af", sonido.filtro_master(), "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    bloque = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proceso.stderr or "")
    if not bloque:
        return None
    try:
        return json.loads(bloque[-1])
    except ValueError:
        return None


def _montar_audio(proyecto: Proyecto, voz: dict, params: dict, cortes: list,
                  reparto: dict, total: float, temporal: Path, trabajo) -> Path:
    """La mezcla entera: voz + música (con ducking) + efectos. A WAV.

    De aquí sale el audio FINAL ya masterizado (dos pasadas: medir, y
    aplicar una ganancia constante — una sola pasada es adaptativa y se
    oye como bombeo). Lo que falte (un tema que ya no está, sin claves)
    se degrada: sale sin eso y el trabajo lo cuenta.
    """
    con_sonido = bool(params.get("sonido", True))
    musica = (params.get("musica") or {}) if con_sonido else {}
    surtido = (params.get("efectos") or {}) if con_sonido else {}
    voz_wav = _voz_wav(proyecto, voz, temporal / "voz.wav")

    entradas = ["-i", str(voz_wav)]
    con_musica = con_efectos = False
    cama = False
    if musica:
        try:
            if musica.get("tramos"):
                trabajo.avance("montando la cama de música por tramos")
                pista, faltan = sonido.construir_cama(
                    musica, total, temporal / "musica.wav")
                if faltan:
                    trabajo.avance(f"cama: faltaban {len(faltan)} tema(s); "
                                   "sigue con los que hay")
                if pista:
                    entradas += ["-i", str(pista)]
                    con_musica, cama = True, True
            elif musica.get("id"):
                tema = sonido.traer(musica, "musica")
                entradas += ["-i", str(tema)]
                con_musica = True
        except Exception as fallo:            # degradar antes que tumbar
            trabajo.avance(f"sin música: {str(fallo)[:160]}")
    if surtido:
        try:
            cartela_de = {}
            assets = p2_brief.proyecto_leer_datos(proyecto, "assets")
            for p in assets.get("planos", []):
                if isinstance(p, dict) and p.get("cartela"):
                    # por escena Y por plano: los cortes viajan con id de
                    # plano y el efecto no puede quedarse mirando una
                    # clave que ya no existe. Viaja la ficha y los
                    # tiempos de `escritura` (los dejó p6): con ellos el
                    # tecleo de la máquina de escribir cae donde caen
                    # las palabras de verdad.
                    escritura = p.get("escritura") if isinstance(
                        p.get("escritura"), dict) else {}
                    ficha = {"cartela": p["cartela"],
                             "tiempos": escritura.get("tiempos") or []}
                    cartela_de[str(p.get("id") or p.get("escena"))] = ficha
                    cartela_de[str(p.get("escena"))] = ficha
            trabajo.avance("mezclando los efectos del banco")
            lista = sonido.eventos(cortes, reparto, params,
                                   semilla=_semilla_de(proyecto),
                                   cartela_de=cartela_de)
            if lista:
                pista, usados = sonido.pista_de_efectos(
                    lista, total, temporal / "efectos.wav")
                trabajo.avance(f"{usados} efectos colocados")
                entradas += ["-i", str(pista)]
                con_efectos = True
        except Exception as fallo:
            trabajo.avance(f"sin efectos: {str(fallo)[:160]}")

    if not con_musica and not con_efectos:
        return voz_wav
    grafo = sonido.filtro_de_mezcla(
        con_musica, con_efectos, total,
        lufs=float(params.get("musica_lufs") or sonido.MUSICA_LUFS),
        ya_normalizada=cama,
        ajuste_db=float(params.get("musica_db") or 0.0),
        efectos_db=float(params.get("efectos_db") or 0.0))
    mezcla = temporal / "mezcla.wav"
    proceso = subprocess.run(
        [comun.ffmpeg(), "-y", "-loglevel", "error", *entradas,
         "-filter_complex", grafo, "-map", "[salida]", "-c:a", "pcm_s16le",
         str(mezcla)],
        capture_output=True, text=True, timeout=3600)
    if proceso.returncode != 0 or not mezcla.exists():
        raise RuntimeError(f"fallo al mezclar el audio: {proceso.stderr[-400:]}")
    return mezcla


def _semilla_de(proyecto: Proyecto) -> int:
    return int.from_bytes(hashlib.sha1(proyecto.id.encode()).digest()[:8],
                          "big")


def _unir_con_transiciones(segmentos: list[Path], reparto: dict, sids: list,
                            calidad: str, destino: Path) -> Path:
    """La cadena de xfade: qué efecto de ffmpeg lleva cada corte.

    Los cortes secos se unen con `concat` dentro del mismo grafo: en cuanto
    hay UNA transición todo el vídeo se re-codifica una vez (no por junta),
    y la duración de cada transición se recorta a lo que DE VERDAD duran
    los segmentos codificados.
    """
    ajustes = CALIDADES.get(calidad, CALIDADES["estandar"])
    duraciones = [comun.duracion_de(s) for s in segmentos]
    orden = [comun.ffmpeg(), "-y", "-loglevel", "error"]
    for s in segmentos:
        orden += ["-i", str(s)]
    partes, total = [], duraciones[0] if duraciones else 0.0
    previo = "[0:v]"
    for i in range(1, len(segmentos)):
        ficha = reparto.get(sids[i]) or {}
        efecto, dura = ficha.get("xfade"), float(ficha.get("duracion") or 0)
        dura = min(dura, duraciones[i - 1] * 0.9, duraciones[i] * 0.9)
        etiqueta = f"[v{i}]"
        if not efecto or dura <= 0.01:
            partes.append(f"{previo}[{i}:v]concat=n=2:v=1:a=0{etiqueta}")
            total += duraciones[i]
        else:
            offset = max(0.0, total - dura)
            partes.append(f"{previo}[{i}:v]xfade=transition={efecto}"
                          f":duration={dura:.3f}:offset={offset:.3f}{etiqueta}")
            total += duraciones[i] - dura
        previo = etiqueta
    orden += ["-filter_complex", ";".join(partes), "-map", previo,
              "-c:v", "libx264", "-preset", ajustes["preset"],
              "-crf", ajustes["crf"], "-pix_fmt", "yuv420p", "-r", str(FPS),
              "-an", str(destino)]
    proceso = subprocess.run(orden, capture_output=True, text=True,
                             timeout=3600)
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(f"fallo al unir con transiciones: "
                           f"{proceso.stderr[-400:]}")
    return destino


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    assets = p2_brief.proyecto_leer_datos(proyecto, "assets")
    callouts = p2_brief.proyecto_leer_datos(proyecto, "callouts")
    if not voz.get("escenas") or not assets.get("planos"):
        raise ValueError("falta voz o assets: genera primero los pasos previos")
    calidad = params.get("calidad", "estandar")
    voz_de = {v["id"]: v for v in voz["escenas"]}
    # cada escena empieza DONDE acaba la anterior en la pista de voz
    offset_de, acumulado = {}, 0.0
    for v in voz["escenas"]:
        offset_de[v["id"]] = acumulado
        acumulado += float(v["duracion"])
    planos = [p for p in assets["planos"] if isinstance(p, dict)]
    for p in planos:
        p.setdefault("id", p.get("escena", ""))
        p.setdefault("escena", p["id"])
    # LOS TROZOS DE SUBTÍTULO van por plano y en reloj de plano: no hay
    # nada que recolocar — los dejó p7 con las marcas de la voz
    subs_de = {str(f.get("id")): f.get("trozos") or []
               for f in callouts.get("subtitulos", [])
               if isinstance(f, dict)}
    # el grafismo del vídeo, ESCRITO en los datos de callouts al generarse:
    # el render no relee params de otro paso (una vista vieja tiene que
    # poder reproducir qué diseño dibujó)
    cfg_grafismo = {"diseno": callouts.get("diseno", "pastilla"),
                    "paleta": callouts.get("paleta") or {},
                    "tam": callouts.get("subtitulo_tam", "normal"),
                    "subtitulo_caja": callouts.get("subtitulo_caja", "auto")}
    # EL CUADRO DE SALIDA: el porte con el que p6 pidió las imágenes (lo
    # apuntó en sus datos) o, si no lo apuntó, el que dicta el brief.
    # El param «resolucion» de abajo es cosmético (lo lee la ficha del
    # paso); el cuadro de verdad sale de aquí, y los proyectos de antes
    # de que existiera el mando siguen saliendo a 1920x1080.
    ficha_formato = comun.ficha_formato(assets.get("formato")
                                        or p4_voz.formato_de_salida(proyecto))
    ancho, alto = ficha_formato["salida"]
    sub_ancho = min(SUB_ANCHO, ancho - 2 * SUB_MARGEN)
    temporal = Path(tempfile.mkdtemp(prefix="render_"))
    segmentos, sids, cortes = [], [], []
    total = 0.0
    for indice, plano in enumerate(planos, start=1):
        trabajo.comprobar_cancelacion()
        sid = plano["escena"]
        escena = voz_de.get(sid)
        if escena is None:
            raise ValueError(f"el plano {plano['id']} no tiene voz "
                             f"(escena {sid} sin audio)")
        if not plano.get("cartela") and not plano.get("imagen"):
            raise ValueError(f"el plano {plano['id']} no tiene imagen")
        dur = (max(0.0, float(plano.get("t_out") or 0.0)
                   - float(plano.get("t_in") or 0.0))
               or float(escena["duracion"]))
        trabajo.avance(f"renderizando {indice}/{len(planos)}: "
                       f"{plano['id']} ({round(dur, 1)} s)")
        destino = temporal / f"{indice:04d}_{plano['id']}.mp4"
        _segmento(proyecto, plano, escena, subs_de.get(plano["id"]),
                  destino, calidad, trabajo, cfg_grafismo,
                  tamano=(ancho, alto), sub_ancho=sub_ancho)
        segmentos.append(destino)
        sids.append(plano["id"])
        # el CORTE en tiempo global del vídeo: con la ranura que dejó
        # escrita el corte del guion (suave/acento), si la dejó
        global_in = offset_de.get(sid, 0.0) + float(plano.get("t_in") or 0.0)
        cortes.append({"id": plano["id"], "escena": sid,
                       "t_in": round(global_in, 3),
                       "t_out": round(global_in + dur, 3),
                       "duracion": dur,
                       **({"transicion": plano["transicion"]}
                          if plano.get("transicion") else {})})
        total += dur
    # QUÉ TRANSICIÓN LLEVA CADA PLANO: determinista (semilla del vídeo), y
    # sólo toca la firma del render — cambiar la paleta no toca las imágenes
    reparto = transiciones.resolver(cortes, params, semilla=_semilla_de(proyecto))
    hay_transiciones = any(f.get("tipo") not in (None, "corte")
                           for f in reparto.values())
    destino_final = proyecto.carpeta_paso("render") / "final.mp4"
    destino_final.parent.mkdir(parents=True, exist_ok=True)
    masterizado = False

    if hay_transiciones or params.get("musica") or params.get("efectos") \
            or params.get("sonido", True) is False:
        # camino con MEZCLA aparte: la voz se concatena sola y se mezcla
        # con lo que digan los params (que puede ser «nada»: sonido False
        # es un vídeo mudo a propósito, no un descuido)
        trabajo.avance("mezclando el audio" if params.get("sonido", True)
                       else "vídeo sin sonido (a propósito)")
        audio = _montar_audio(proyecto, voz, params, cortes, reparto, total,
                              temporal, trabajo) if params.get("sonido", True) \
            else None
        trabajo.avance("uniendo los planos"
                       + (" con transiciones" if hay_transiciones else ""))
        if hay_transiciones:
            video = _unir_con_transiciones(segmentos, reparto, sids, calidad,
                                           temporal / "video.mp4")
        else:
            lista = temporal / "lista.txt"
            lista.write_text("".join(f"file '{s.as_posix()}'\n"
                                     for s in segmentos), encoding="utf-8")
            video = temporal / "bruto.mp4"
            proceso = subprocess.run(
                [comun.ffmpeg(), "-y", "-loglevel", "error", "-f", "concat",
                 "-safe", "0", "-i", str(lista), "-c", "copy", str(video)],
                capture_output=True, text=True, timeout=3600)
            if proceso.returncode != 0:
                raise RuntimeError(f"fallo al concatenar: {proceso.stderr[-400:]}")
        # master en dos pasadas: medir, y aplicar una ganancia CONSTANTE
        trabajo.avance("masterizando audio")
        filtros = None
        if audio is not None:
            medida = _medir_master(audio)
            if medida:
                filtros = sonido.filtro_master(medida)
                masterizado = True
            else:
                trabajo.avance("la medida del master falló; sale sin masterizar")
        orden = [comun.ffmpeg(), "-y", "-loglevel", "error",
                 "-i", str(video)] + (["-i", str(audio)] if audio else [])
        orden += ["-map", "0:v"]
        if audio is not None:
            orden += ["-map", "1:a"]
            if filtros:
                orden += ["-af", filtros]
            orden += ["-c:a", "aac", "-b:a", "192k"]
        else:
            orden += ["-an"]
        orden += ["-c:v", "copy", "-movflags", "+faststart",
                  str(destino_final)]
        proceso = subprocess.run(orden, capture_output=True, text=True,
                                 timeout=3600)
        if proceso.returncode != 0 or not destino_final.exists():
            raise RuntimeError(f"fallo al montar el vídeo final: "
                               f"{proceso.stderr[-400:]}")
    else:
        # camino rápido de siempre: concat en copia + loudnorm en una pasada
        trabajo.avance("concatenando segmentos")
        lista = temporal / "lista.txt"
        lista.write_text("".join(f"file '{s.as_posix()}'\n" for s in segmentos),
                         encoding="utf-8")
        bruto = temporal / "bruto.mp4"
        proceso = subprocess.run(
            [comun.ffmpeg(), "-y", "-loglevel", "error", "-f", "concat",
             "-safe", "0", "-i", str(lista), "-c", "copy", str(bruto)],
            capture_output=True, text=True, timeout=3600)
        if proceso.returncode != 0:
            raise RuntimeError(f"fallo al concatenar: {proceso.stderr[-400:]}")
        # masterizacion de audio (una pasada; si loudnorm falla, sale sin
        # master — degradar antes que tumbar, como el original)
        trabajo.avance("masterizando audio")
        proceso = subprocess.run(
            [comun.ffmpeg(), "-y", "-loglevel", "error", "-i", str(bruto),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", str(destino_final)],
            capture_output=True, text=True, timeout=3600)
        if proceso.returncode != 0 or not destino_final.exists():
            trabajo.avance("loudnorm fallo; el vídeo sale sin masterizar")
            destino_final = bruto
        masterizado = destino_final != bruto
    duracion = comun.duracion_de(destino_final)
    trabajo.avance(f"vídeo listo: {round(duracion)} s, "
                   f"{destino_final.name}")
    return {"video": "pasos/render/final.mp4", "duracion": duracion,
            "fps": FPS, "resolucion": f"{ancho}x{alto}",
            "escenas": len(voz["escenas"]), "planos": len(segmentos),
            "masterizado": masterizado,
            "sonido": sonido.describir(params),
            "transiciones": transiciones.describir(params)}
