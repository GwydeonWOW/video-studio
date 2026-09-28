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
                  destino, calidad, trabajo, cfg_grafismo)
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
