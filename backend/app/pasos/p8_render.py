"""Paso 8 — render: compone el vídeo con ffmpeg.

Por escena (duracion = la REAL de su audio):
1. La imagen del plano se anima con un movimiento de camara suave
   (zoompan Ken Burns, alternando acercarse/alejarse por escena).
2. El rotulo (si lo hay) entra en su instante con fundido (PNG de PIL
   sobre el plano, alpha).
3. El audio de la escena viaja con el segmento.

Despues: concat de segmentos (mismos codecs, sin recodificar) y una pasada
de masterizacion loudnorm (I=-16, TP=-1.5, LRA=11, norma de podcast/video).

Sin shell=True en NINGUNA llamada: listas de argumentos siempre
(docs/AUDITORIA.md H2).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..config import AJUSTES
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief

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
    return {"calidad": "estandar", "resolucion": "1920x1080", "fps": FPS}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


def _fuente() -> str:
    for fuente in FUENTES:
        if Path(fuente).is_file():
            return fuente
    return ""


def _rotulo_png(texto: str, destino: Path, ancho_max: int = 1400) -> Path:
    """Dibuja el rotulo (texto + banda semitransparente) con PIL."""
    from PIL import Image, ImageDraw, ImageFont
    fuente_ruta = _fuente()
    tamano = 64
    fuente = (ImageFont.truetype(fuente_ruta, tamano) if fuente_ruta
              else ImageFont.load_default())
    imagen = Image.new("RGBA", (ANCHO, 200), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    bbox = dibujo.textbbox((0, 0), texto, font=fuente)
    ancho_texto, alto_texto = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # partir en lineas si se pasa de ancho
    lineas = [texto]
    if ancho_texto > ancho_max:
        palabras = texto.split()
        lineas, actual = [], ""
        for palabra in palabras:
            prueba = f"{actual} {palabra}".strip()
            ancho_prueba = dibujo.textbbox((0, 0), prueba, font=fuente)[2]
            if ancho_prueba > ancho_max and actual:
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        if actual:
            lineas.append(actual)
        alto_texto = len(lineas) * (alto_texto + 14)
        imagen = Image.new("RGBA", (ANCHO, alto_texto + 60), (0, 0, 0, 0))
        dibujo = ImageDraw.Draw(imagen)
        y = 30
        for linea in lineas:
            bbox = dibujo.textbbox((0, 0), linea, font=fuente)
            ancho_linea = bbox[2] - bbox[0]
            x0 = (ANCHO - ancho_linea) // 2 - 28
            dibujo.rounded_rectangle(
                [x0, y - 12, x0 + ancho_linea + 56, y + 76], radius=18,
                fill=(10, 12, 16, 190))
            dibujo.text((x0 + 28, y), linea, font=fuente,
                        fill=(245, 247, 250, 255))
            y += alto_texto + 14
    else:
        x0 = (ANCHO - ancho_texto) // 2 - 28
        dibujo.rounded_rectangle(
            [x0, 30 - 12, x0 + ancho_texto + 56, 30 + 76], radius=18,
            fill=(10, 12, 16, 190))
        dibujo.text((x0 + 28, 30), texto, font=fuente,
                    fill=(245, 247, 250, 255))
    # recorte al contenido real
    caja = imagen.getbbox()
    imagen = imagen.crop(caja)
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino)
    return destino


def _segmento(proyecto: Proyecto, escena: dict, plano: dict, rotulo: dict | None,
              destino: Path, calidad: str, trabajo) -> Path:
    """Un segmento de video: imagen animada + rotulo + audio de la escena."""
    imagen = proyecto.ruta(plano["imagen"])
    audio = proyecto.ruta(escena["audio"])
    duracion = float(escena["duracion"])
    ajustes = CALIDADES.get(calidad, CALIDADES["estandar"])
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
                          destino.parent / f"{plano['escena']}_rotulo.png")
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


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    assets = p2_brief.proyecto_leer_datos(proyecto, "assets")
    callouts = p2_brief.proyecto_leer_datos(proyecto, "callouts")
    if not voz.get("escenas") or not assets.get("planos"):
        raise ValueError("falta voz o assets: genera primero los pasos previos")
    calidad = params.get("calidad", "estandar")
    planos_de = {p["escena"]: p for p in assets["planos"]}
    rotulos_de = {r["id"]: r for r in callouts.get("rotulos", [])}
    temporal = Path(tempfile.mkdtemp(prefix="render_"))
    segmentos = []
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
                  destino, calidad, trabajo)
        segmentos.append(destino)
        total += float(escena["duracion"])
    # concatenar (mismos codecs: copia sin recodificar)
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
    # masterizacion de audio (una pasada; si loudnorm falla, sale sin master
    # — degradar antes que tumbar, como el original)
    trabajo.avance("masterizando audio")
    destino_final = proyecto.carpeta_paso("render") / "final.mp4"
    destino_final.parent.mkdir(parents=True, exist_ok=True)
    proceso = subprocess.run(
        [comun.ffmpeg(), "-y", "-loglevel", "error", "-i", str(bruto),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", str(destino_final)],
        capture_output=True, text=True, timeout=3600)
    if proceso.returncode != 0 or not destino_final.exists():
        trabajo.avance("loudnorm fallo; el vídeo sale sin masterizar")
        destino_final = bruto
    duracion = comun.duracion_de(destino_final)
    trabajo.avance(f"vídeo listo: {round(duracion)} s, "
                   f"{destino_final.name}")
    return {"video": "pasos/render/final.mp4", "duracion": duracion,
            "fps": FPS, "resolucion": f"{ANCHO}x{ALTO}",
            "escenas": len(segmentos), "masterizado": destino_final != bruto}
