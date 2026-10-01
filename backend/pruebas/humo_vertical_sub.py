"""Sonda puntual: subtítulos verticales caben en 1080 con el tope nuevo.

Réplica del repro del verificador (trozos legales, mayúsculas anchas)
contra el código real: p7 trocea con los topes del formato y p8 dibuja
con el cuerpo crecido. Sale 0 si ningún PNG se sale del lienzo.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from app.pasos import p7_callouts, p8_render, subtitulos

fallos = 0


def probar(salida, lienzo, banda, tam, etiqueta):
    global fallos
    cap = p7_callouts.cap_linea_de(tam, salida)
    cap_trozo = cap if subtitulos.es_vertical(salida) else None
    texto = ("LOS RESULTADOS DE LA ENCUESTA DE CALIDAD DE ESTE TRIMESTRE "
             "SON CLARAMENTE POSITIVOS EN TODAS LAS REGIONES DEL PAIS "
             "SEGUN LOS DATOS PUBLICADOS ESTA MISMA SEMANA")
    palabras = texto.split()
    marcas = [[i * 0.4, i * 0.4 + 0.35] for i in range(len(palabras))]
    plano = {"id": "P001", "narracion": texto, "marcas": marcas,
             "t_in": 0, "t_out": len(palabras) * 0.4}
    trozos = subtitulos.de_escena(plano, cap_linea=cap, cap_trozo=cap_trozo,
                                  idioma="es")
    escala = subtitulos.escala_subtitulo(salida)
    print(f"== {etiqueta}: cap_linea={cap} cap_trozo={cap_trozo} "
          f"escala={escala} trozos={len(trozos)}")
    temporal = Path(tempfile.mkdtemp(prefix="sonda_sub_"))
    for k, trozo in enumerate(trozos):
        png = p8_render._subtitulo_png(trozo["texto"], temporal / f"s{k}.png",
                                       tam=tam, ancho_max=banda,
                                       lienzo=lienzo, escala=escala)
        if png is None:
            continue
        ancho_png = Image.open(png).width
        margen = (lienzo - ancho_png) / 2
        estado = "cabe" if margen >= 0 else "SE SALE"
        print(f"   [{estado}] {len(trozo['texto'])} chars -> "
              f"png={ancho_png}px margen/lado={margen:+.0f}px")
        if margen < 0:
            fallos += 1


# el defecto de siempre no se toca: horizontal = 38, sin escala
assert p7_callouts.cap_linea_de("normal") == 38, "el cap horizontal cambió"
assert p7_callouts.cap_linea_de("normal", [1920, 1080]) == 38
assert subtitulos.escala_subtitulo(None) == 1.0
assert subtitulos.escala_subtitulo([1920, 1080]) == 1.0
assert subtitulos.escala_subtitulo([1080, 1920]) == 1.35

banda_v = subtitulos.banda_fija(1080, 1920)
assert banda_v["ancho"] == 936, banda_v
assert banda_v["suelo"] == round(1920 * (1 - 1 / 3), 1), banda_v
assert subtitulos.banda_fija()["suelo"] == 1080 - 72  # horizontal igual

probar([1080, 1920], 1080, 936, "normal", "vertical normal")
probar([1080, 1920], 1080, 936, "grande", "vertical grande")
probar([1080, 1920], 1080, 936, "pequeno", "vertical pequeno")
probar([1920, 1080], 1920, 1400, "normal", "horizontal control")

if fallos:
    print(f"\n{fallos} PNG fuera del lienzo")
    sys.exit(1)
print("\nOK — sonda subtítulos verticales")
