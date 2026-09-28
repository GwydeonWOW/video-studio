"""Paso 8 — render: compone el vídeo con ffmpeg.

Por escena (duracion = la REAL de su audio):
1. La imagen del plano se anima con un movimiento de camara suave
   (zoompan Ken Burns, alternando acercarse/alejarse por escena).
2. El rotulo (si lo hay) entra en su instante con fundido (PNG de PIL
   sobre el plano, alpha).
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
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief, sonido, transiciones

FPS = 30
ANCHO, ALTO = 1920, 1080
CALIDADES = {"borrador": {"preset": "veryfast", "crf": "26"},
             "estandar": {"preset": "medium", "crf": "22"},
             "detalle": {"preset": "slow", "crf": "18"}}

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
                tam=1.0) -> Path:
    """Dibuja el rotulo con el SET DE DISENO y la paleta del vídeo.

    Es el mismo dibujo que grafismo.svg_rotulo (la pantalla ensena el
    SVG, el render paga el PNG): que difieran seria una pantalla que
    miente.
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
    imagen = Image.new("RGBA", (ANCHO, len(lineas) * alto_linea + 2 * margen),
                       (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    velo = _color(paleta.get("velo"))
    acento = _color(paleta.get("acento"))
    tinta = _color(paleta.get("texto"))
    y = margen
    for linea in lineas:
        bbox = dibujo.textbbox((0, 0), linea, font=fuente)
        ancho_linea = bbox[2] - bbox[0]
        x0 = (ANCHO - ancho_linea) // 2
        if caja == "pastilla":
            dibujo.rounded_rectangle(
                [x0 - 28, y - 10, x0 + ancho_linea + 28, y + tamano + 14],
                radius=18, fill=velo)
        elif caja == "barra":
            dibujo.rectangle([x0 - 28, y - 10, x0 - 20, y + tamano + 14],
                             fill=acento)
        elif caja == "pleno":
            dibujo.rectangle([0, y - 10, ANCHO, y + tamano + 14], fill=velo)
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


def _cartela_png(plantilla: str, datos: dict | None, destino: Path,
                 paleta: dict | None = None) -> Path:
    """Una cartela completa (1920x1080): el plano entero ES texto.

    El mismo dibujo que grafismo.svg_cartela, en raster para ffmpeg.
    Sin marca de tiempo de lectura: esa es de la pantalla, no del vídeo.
    """
    from PIL import Image, ImageDraw
    from ..nucleo import grafismo
    paleta = paleta or dict(grafismo.PALETA_DEFECTO)
    datos = datos or {}
    imagen = Image.new("RGB", (ANCHO, ALTO), _color(paleta.get("fondo"))[:3])
    dibujo = ImageDraw.Draw(imagen)
    acento = _color(paleta.get("acento"))[:3]
    tinta = _color(paleta.get("texto"))[:3]
    cx, cy = ANCHO // 2, ALTO // 2

    def centro(texto, cy_, tamano, color):
        fuente = _fuente_de(tamano)
        bbox = dibujo.textbbox((0, 0), str(texto), font=fuente)
        ancho, alto = bbox[2] - bbox[0], bbox[3] - bbox[1]
        dibujo.text(((ANCHO - ancho) // 2 - bbox[0], cy_ - alto // 2 - bbox[1]),
                    str(texto), font=fuente, fill=color)

    if plantilla == "cita":
        centro("“", cy - 130, 150, acento)
        centro(datos.get("texto", ""), cy + 20, 72, tinta)
        if datos.get("autor"):
            centro(f"— {datos['autor']}", cy + 150, 38, acento)
    elif plantilla == "dato":
        centro(datos.get("cifra", ""), cy - 30, 220, acento)
        if datos.get("pie"):
            centro(datos.get("pie", ""), cy + 170, 52, tinta)
    elif plantilla == "capitulo":
        centro(f"C A P Í T U L O  {datos.get('numero', '')}", cy - 120, 44,
               acento)
        dibujo.rectangle([cx - 90, cy - 60, cx + 90, cy - 56], fill=acento)
        centro(datos.get("titulo", ""), cy + 70, 96, tinta)
    elif plantilla == "cierre":
        centro(datos.get("titulo", ""), cy - 30, 110, tinta)
        if datos.get("sub"):
            centro(datos.get("sub", ""), cy + 120, 48, acento)
    else:  # titulo
        dibujo.rectangle([cx - 70, cy - 170, cx + 70, cy - 164], fill=acento)
        centro(datos.get("titulo", ""), cy, 130, tinta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino)
    return destino


def _segmento(proyecto: Proyecto, escena: dict, plano: dict, rotulo: dict | None,
              destino: Path, calidad: str, trabajo,
              cfg_grafismo: dict | None = None) -> Path:
    """Un segmento de video: imagen animada + rotulo + audio de la escena.

    Los planos de CARTELA no traen imagen: el plano entero es un PNG de
    texto (la misma plantilla que ensena la pantalla), estatico.
    """
    cfg = cfg_grafismo or {}
    audio = proyecto.ruta(escena["audio"])
    duracion = float(escena["duracion"])
    ajustes = CALIDADES.get(calidad, CALIDADES["estandar"])
    cartela = plano.get("cartela")
    if cartela:
        png = _cartela_png(cartela.get("plantilla", "titulo"),
                           cartela.get("datos", {}),
                           destino.parent / f"{plano['escena']}_cartela.png",
                           paleta=cfg.get("paleta"))
        orden = [comun.ffmpeg(), "-y", "-loglevel", "error",
                 "-loop", "1", "-t", f"{duracion:.3f}", "-i", str(png),
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
            raise RuntimeError(f"ffmpeg fallo en {plano['escena']}: "
                               f"{proceso.stderr[-400:]}")
        return destino
    imagen = proyecto.ruta(plano["imagen"])
    zoom_entra = hash(plano["escena"]) % 2 == 0  # alterna acercar/alejar
    if zoom_entra:
        expresion = "'min(1.0+0.09*on/({d}*{f}),1.09)'"
    else:
        expresion = "'max(1.09-0.09*on/({d}*{f}),1.0)'"
    zoom = expresion.format(d=duracion, f=FPS)
    filtros = [
        # escalar de mas y encoger con zoompan: sin escalones
        f"scale={ANCHO * 2}:{ALTO * 2}",
        f"zoompan=z={zoom}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={ANCHO}x{ALTO}:fps={FPS}",
        "setsar=1",
    ]
    orden = [comun.ffmpeg(), "-y", "-loglevel", "error",
             "-loop", "1", "-t", f"{duracion:.3f}", "-i", str(imagen)]
    base = f"[0:v]{','.join(filtros)}"
    if rotulo:
        png = _rotulo_png(rotulo["texto"],
                          destino.parent / f"{plano['escena']}_rotulo.png",
                          diseno=cfg.get("diseno", "pastilla"),
                          paleta=cfg.get("paleta"),
                          tam=cfg.get("tam", "normal"))
        aparece = float(rotulo.get("aparece", 0.0))
        dura = float(rotulo.get("dura", 4.0))
        dura = min(dura, max(0.8, duracion - aparece))
        fundido = min(0.35, dura / 3)
        orden += ["-loop", "1", "-t", f"{dura:.3f}", "-i", str(png)]
        grafo = (
            f"{base}[base];"
            f"[1:v]format=rgba,"
            f"fade=t=in:st=0:d={fundido:.2f}:alpha=1,"
            f"fade=t=out:st={dura - fundido:.2f}:d={fundido:.2f}:alpha=1,"
            f"setpts=PTS+{aparece:.2f}/TB[r];"
            f"[base][r]overlay=x=(W-w)/2:y=H-h-90:shortest=0[v]")
        indice_audio = "2:a"
    else:
        grafo = f"{base}[v]"
        indice_audio = "1:a"
    orden += ["-i", str(audio),
              "-filter_complex", grafo,
              "-map", "[v]", "-map", indice_audio,
              "-c:v", "libx264", "-preset", ajustes["preset"],
              "-crf", ajustes["crf"], "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k",
              "-t", f"{duracion:.3f}", str(destino)]
    proceso = subprocess.run(orden, capture_output=True, text=True,
                             timeout=1800)
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(f"ffmpeg fallo en {plano['escena']}: "
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
                    cartela_de[str(p.get("escena"))] = True
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
    planos_de = {p["escena"]: p for p in assets["planos"]}
    rotulos_de = {r["id"]: r for r in callouts.get("rotulos", [])}
    # el grafismo del vídeo, ESCRITO en los datos de callouts al generarse:
    # el render no relee params de otro paso (una vista vieja tiene que
    # poder reproducir qué diseño dibujó)
    cfg_grafismo = {"diseno": callouts.get("diseno", "pastilla"),
                    "paleta": callouts.get("paleta") or {},
                    "tam": callouts.get("subtitulo_tam", "normal")}
    temporal = Path(tempfile.mkdtemp(prefix="render_"))
    segmentos, sids, cortes = [], [], []
    total = 0.0
    for indice, escena in enumerate(voz["escenas"], start=1):
        trabajo.comprobar_cancelacion()
        plano = planos_de.get(escena["id"])
        if not plano:
            raise ValueError(f"la escena {escena['id']} no tiene imagen")
        trabajo.avance(f"renderizando {indice}/{len(voz['escenas'])}: "
                       f"{escena['id']} ({escena['duracion']} s)")
        destino = temporal / f"{indice:04d}_{escena['id']}.mp4"
        _segmento(proyecto, escena, plano, rotulos_de.get(escena["id"]),
                  destino, calidad, trabajo, cfg_grafismo)
        segmentos.append(destino)
        sids.append(escena["id"])
        dur = float(escena["duracion"])
        cortes.append({"id": escena["id"], "t_in": round(total, 3),
                       "t_out": round(total + dur, 3),
                       "duracion": dur})
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
            "fps": FPS, "resolucion": f"{ANCHO}x{ALTO}",
            "escenas": len(segmentos), "masterizado": masterizado,
            "sonido": sonido.describir(params),
            "transiciones": transiciones.describir(params)}
