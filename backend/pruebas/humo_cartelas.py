"""Prueba de humo de las cartelas completas (cartelas.py → p6/p7/API).

Una cartela es un plano de TEXTO escrito palabra a palabra SOBRE la
imagen del plano, decidida antes de pagar las imágenes. Se comprueba
sin gastar nada:

- el catálogo expone las plantillas con campos {obligatorio, tope},
  lista (enumeración) y muestra SVG dibujada por el MISMO código
- `validar`: la lista de líneas viaja ENTERA (2..4), el icono es un
  catálogo cerrado (uno inventado se suelta con aviso), el tope recorta
- `fotograma` con zoom escala el fotograma COMPUESTO (texto+velo+base
  juntos, como el grupo del zoom del original)
- `secuencia` escribe los f%05d.png que come ffmpeg y `tiempos_de_
  escritura` devuelve los segundos del DIBUJADO (lo que oye el teclado)
- p6 `_marcar_cartelas`: la cartela se MUDA al plano donde se dicen sus
  palabras, FUNDE los que estira, y realterna el zoom tras el hueco
- p7: el plano de cartela no lleva subtítulo PERO sus palabras se
  consumen (si no, la escena entera los perdería)
- la API guarda listas, enseña iconos/defecto y dibuja la vista

Ejecutar:

    python pruebas/humo_cartelas.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_cartelas_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.api import rutas_proyectos  # noqa: E402
from app.motores import llm as motor_llm  # noqa: E402
from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.pasos import cartelas, p6_assets, p7_callouts  # noqa: E402

from fastapi import HTTPException  # noqa: E402

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


class TrabajoMudo:
    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass


# ------------------------------------------------------------- el catálogo

catalogo = cartelas.catalogo_plantillas()
check("el catálogo trae las plantillas como LISTA con todo",
      isinstance(catalogo, list) and len(catalogo) >= 4
      and all(p["svg"].startswith("<svg")
              and isinstance(p["campos"], dict)
              and all(isinstance(v, dict) and {"obligatorio", "tope"} <= v.keys()
                      for v in p["campos"].values())
              for p in catalogo),
      str([p["id"] for p in catalogo]))
ids_catalogo = {p["id"] for p in catalogo}
check("las plantillas de siempre están y tesis es la de respaldo",
      {"tesis", "cifra", "cita", "enumeracion"} <= ids_catalogo
      and cartelas.PLANTILLA_POR_DEFECTO == "tesis")
enum = next(p for p in catalogo if p["id"] == "enumeracion")
check("la enumeración declara su campo de lista (2..4 líneas)",
      enum.get("lista") and enum["lista"][0] == "lineas"
      and enum["lista"][1] == 2 and enum["lista"][2] == 4,
      str(enum.get("lista")))

# ------------------------------------------------------------- validación

valores, motivos = cartelas.validar(
    "enumeracion", {"titulo": "Tres reglas", "lineas": ["una", "dos"]})
check("las líneas viajan ENTERAS (lista, no texto)",
      valores == {"titulo": "Tres reglas", "lineas": ["una", "dos"]},
      str(valores))
valores, motivos = cartelas.validar(
    "enumeracion", {"titulo": "T", "lineas": ["a", "b", "c", "d", "e"]})
check("más líneas de la cuenta: se quedan las cuatro y avisa",
      valores is not None and len(valores["lineas"]) == 4
      and any("elementos" in m for m in motivos), str(motivos))
valores, motivos = cartelas.validar(
    "enumeracion", {"titulo": "T", "lineas": ["una"]})
check("menos líneas del suelo: no guarda, explica",
      valores is None and any("al menos" in m for m in motivos),
      str(motivos))
valores, motivos = cartelas.validar(
    "tesis", {"texto": "x" * 300, "icono": "inventado"})
check("el tope recorta y el icono inventado se suelta con aviso",
      valores is not None and len(valores["texto"]) == 95
      and "icono" not in valores
      and any("icono" in m for m in motivos), str(motivos))
valores, _ = cartelas.validar(
    "tesis", {"texto": "la tesis", "icono": "candado"})
check("el icono del catálogo se queda", valores.get("icono") == "candado")

# ------------------------------------------------------------ sobre imagen

ficha = {"plantilla": "tesis", "datos": {"texto": "tres cuatro"}}
check("hoy TODAS van sobre imagen (pagan su foto)",
      cartelas.TODAS_SOBRE_IMAGEN
      and cartelas.sobre_imagen({"cartela": ficha})
      and not cartelas.sin_imagen({"cartela": ficha}))

# ------------------------------------------------------- dibujo: svg/pil/zoom

svg = cartelas.svg_carta(ficha, duracion=3.0, animada=True)
check("svg_carta animada con tiempos dibuja texto",
      svg.startswith("<svg") and "<text" in svg)
png = cartelas.png_carta(ficha, duracion=3.0)
check("png_carta quieta, tamaño del cuadro de salida",
      png.size == (1920, 1080) and png.mode == "RGB", str(png.size))

f0 = cartelas.fotograma(ficha, 0.0, duracion=3.0, zoom=(1.0, 1.06))
f_fin = cartelas.fotograma(ficha, 3.0, duracion=3.0, zoom=(1.0, 1.06))
check("el zoom escala el fotograma COMPUESTO (t=1 vs t=0 difieren)",
      f0.size == (1920, 1080) and f_fin.size == (1920, 1080)
      and list(f0.getdata()) != list(f_fin.getdata()))

_carpeta = Path(tempfile.mkdtemp(prefix="estudio_cartelas_seq_"))
cuantos = cartelas.secuencia(_carpeta, ficha, 0.4, fps=10,
                             tiempos=[0.2, 0.8], zoom=(1.0, 1.05))
escritos = sorted(p.name for p in _carpeta.glob("f*.png"))
check("secuencia escribe los f%05d.png de ffmpeg",
      cuantos == 5 and escritos == [f"f{i:05d}.png" for i in range(5)],
      str(escritos))

palabras_teclas = cartelas.tiempos_de_escritura(ficha, 3.0,
                                                tiempos=[0.2, 0.8])
check("tiempos_de_escritura: las palabras del DIBUJADO con SUS tiempos",
      [p.lower() for _, p in palabras_teclas][:2] == ["tres", "cuatro"]
      and all(0.0 <= s <= 3.0 for s, _ in palabras_teclas),
      str(palabras_teclas))

# ------------------------------------------- p6: la fusión sobre el corte

PALABRAS = ["uno", "dos", "tres", "cuatro", "cinco", "seis"]
palabras = [{"palabra": w, "inicio": round(0.5 * i, 3),
             "fin": round(0.5 * i + 0.4, 3)}
            for i, w in enumerate(PALABRAS)]
DURACION = 3.3

PLANOS, cursor = [], 0
for k, (cuales, t_in, t_out) in enumerate(
        [(["uno", "dos"], 0.0, 1.0), (["tres", "cuatro"], 1.0, 2.0),
         (["cinco", "seis"], 2.0, DURACION)], 1):
    ventana = palabras[cursor:cursor + len(cuales)]
    PLANOS.append({
        "id": f"S001-{k}", "escena": "S001",
        "narracion": " ".join(cuales),
        "marcas": [[w["inicio"], w["fin"]] for w in ventana],
        "t_in": t_in, "t_out": t_out,
        "corte": "suave", "transicion": "suave",
        "zoom": ({"tipo": "in", "de": 1.0, "a": 1.05} if k < 3
                 else {"tipo": "out", "de": 1.05, "a": 1.0}),
    })
    cursor += len(cuales)

unidades = {"S001": {"cartela": ficha}}
# muta PLANOS a propósito: así se ve la fusión de verdad
fichas, _avisos = p6_assets._marcar_cartelas(PLANOS, unidades, TrabajoMudo(),
                                             limitar=False)

quedan = [p["id"] for p in PLANOS]
hogar = next(p for p in PLANOS if p.get("cartela"))
check("la cartela se MUDA al plano donde se dicen sus palabras",
      hogar["id"] == "S001-2", str(quedan))
check("FUNDE el tramo que estira (la cola de lectura se lo lleva)",
      quedan == ["S001-1", "S001-2"]
      and hogar["narracion"] == "tres cuatro cinco seis"
      and len(hogar["marcas"]) == 4
      and abs(hogar["t_out"] - DURACION) < 1e-6
      and abs(hogar["duracion"] - (DURACION - 1.0)) < 1e-6,
      str((quedan, hogar["narracion"], hogar["duracion"])))
escritura = hogar.get("escritura")
check("la ESCRITURA viaja con sus tiempos (el reloj del render)",
      isinstance(escritura, dict)
      and isinstance(escritura.get("tiempos"), list)
      and 2 <= len(escritura["tiempos"]) <= 4
      and all(0.0 <= float(s) <= hogar["duracion"] + 1e-6
              for s in escritura["tiempos"] if s is not None),
      str(escritura))
check("el informe cuenta los planos fundidos y los absorbidos",
      len(fichas) == 1 and fichas[0]["planos"] == 2
      and fichas[0]["absorbidos"] == ["S001-3"], str(fichas))
zooms = [p["zoom"]["tipo"] for p in PLANOS]
check("el zoom realterna tras el hueco que dejó la fusión",
      zooms == ["in", "out"]
      and PLANOS[1]["zoom"]["de"] > PLANOS[1]["zoom"]["a"],
      str([(z, PLANOS[1]["zoom"]) for z in zooms]))

# sin cartela no toca nada
planos_solo = [dict(p) for p in
               [{"id": "S001-1", "escena": "S001", "narracion": "uno",
                 "t_in": 0.0, "t_out": 1.0}]]
check("sin cartelas, _marcar_cartelas no hace nada",
      p6_assets._marcar_cartelas(planos_solo, {}, TrabajoMudo())
      == ([], []))

# ----------------------------------------------- p7: la cartela no lleva sub

_dir_proy = Path(os.environ["ESTUDIO_DATOS"]) / "proyectos" / "prueba_cart"
(_dir_proy / "pasos" / "guion").mkdir(parents=True)
(_dir_proy / "pasos" / "voz").mkdir(parents=True)
(_dir_proy / "pasos" / "assets").mkdir(parents=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "cartelas"})
escribir_json(_dir_proy / "pasos" / "guion" / "datos.json", {"escenas": [
    {"id": "S001", "titulo": "con cartela", "narracion": " ".join(PALABRAS)}]})
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": DURACION, "palabras": palabras,
     "audio": "voz/s001.mp3"}]})
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json",
              {"planos": PLANOS, "calidad": "low"})
proyecto = Proyecto(_dir_proy)

resultado = p7_callouts.ejecutar(proyecto, {}, TrabajoMudo())
check("p7: subtítulo para el plano normal, NADA para la cartela",
      [f["id"] for f in resultado["subtitulos"]] == ["S001-1"]
      and resultado["subtitulos"][0]["trozos"],
      str([f["id"] for f in resultado["subtitulos"]]))

# ------------------------------------------------------------- la API

guardado = rutas_proyectos.guardar_cartelas(
    "prueba_cart", {"plan": {"S001": {
        "plantilla": "enumeracion",
        "datos": {"titulo": "Tres reglas",
                  "lineas": ["una", "dos", "tres"]}}}})
check("PUT guarda una enumeración y las líneas llegan LISTA",
      guardado["tocados"] == ["S001"]
      and guardado["plan"]["S001"]["datos"]["lineas"]
      == ["una", "dos", "tres"], str(guardado.get("avisos")))
guardado = rutas_proyectos.guardar_cartelas(
    "prueba_cart", {"plan": {"S001": {
        "plantilla": "tesis", "datos": {"texto": "la tesis de hoy",
                                        "icono": "inventado"}}}})
check("PUT con icono inventado: guarda sin él y lo dice",
      "S001" in guardado["tocados"]
      and not guardado["plan"]["S001"]["datos"].get("icono")
      and any("icono" in m for m in guardado["avisos"]),
      str(guardado["avisos"]))

# la lista de plantillas permitidas (lo que el agente puede usar)
try:
    rutas_proyectos.guardar_cartelas("prueba_cart", {"plan": {"S001": {
        "plantilla": "no-existe", "datos": {"texto": "x"}}}})
    check("PUT rechaza plantilla desconocida - 400", False)
except HTTPException as e:
    check("PUT rechaza plantilla desconocida - 400",
          e.status_code == 400 and "Las que hay son" in str(e.detail),
          str(e.detail)[:80])

try:
    rutas_proyectos.guardar_cartelas(
        "prueba_cart", {"plantillas": ["tesis", "no-existe"]})
    check("PUT rechaza allowlist con desconocidas - 400", False)
except HTTPException as e:
    check("PUT rechaza allowlist con desconocidas - 400",
          e.status_code == 400, str(e.detail)[:80])

obsoletos_antes = set(rutas_proyectos.leer_cartelas("prueba_cart")["obsoletos"])
guardado = rutas_proyectos.guardar_cartelas(
    "prueba_cart", {"plantillas": ["tesis", "cifra"]})
check("PUT guarda la allowlist sin ensuciar assets",
      guardado["guardado"] == ["plantillas"]
      and guardado["tocados"] == []
      and guardado["plantillas_activas"] == ["tesis", "cifra"]
      and set(guardado["obsoletos"]) == obsoletos_antes,
      str((guardado["guardado"], guardado["plantillas_activas"]))[:100])
leido = rutas_proyectos.leer_cartelas("prueba_cart")
check("GET enseña la allowlist guardada",
      leido["plantillas_activas"] == ["tesis", "cifra"],
      str(leido["plantillas_activas"]))
catalogo_agente = cartelas._catalogo_para_el_agente({"tesis"})
check("el catálogo del agente obedece la allowlist",
      "- tesis:" in catalogo_agente and "- cifra:" not in catalogo_agente,
      str(catalogo_agente)[:60])

# y de PUNTA A PUNTA: la RUTA tiene que alimentar al agente con la
# allowlist guardada (vive en los params de RÓTULOS, no en assets)
rutas_proyectos.guardar_cartelas("prueba_cart", {"plantillas": ["tesis"]})
_llamar_de_verdad, capturado = motor_llm.llamar_json, {}
motor_llm.llamar_json = (lambda llamada, *a, **k:
                         capturado.__setitem__("i", llamada.instruccion)
                         or {"cartelas": {}})
try:
    _trabajo = rutas_proyectos.proponer_cartelas("prueba_cart")
    while (rutas_proyectos.GESTOR.estado(_trabajo["id"]).get("estado")
           not in ("hecho", "fallo")):
        time.sleep(0.05)
finally:
    motor_llm.llamar_json = _llamar_de_verdad
check("POST /cartelas/plan obedece la allowlist guardada",
      rutas_proyectos.GESTOR.estado(_trabajo["id"]).get("estado") == "hecho"
      and "- tesis:" in (capturado.get("i") or "")
      and "- cifra:" not in (capturado.get("i") or ""),
      rutas_proyectos.GESTOR.estado(_trabajo["id"]).get("estado", "?"))

leido = rutas_proyectos.leer_cartelas("prueba_cart")
check("GET enseña el catálogo, los iconos CERRADOS y la de defecto",
      isinstance(leido["plantillas"], list)
      and "candado" in leido["iconos"]
      and leido["defecto"] == "tesis"
      and leido["max_cartelas"] >= 1,
      str((leido["defecto"], len(leido["plantillas"]))))
vista = rutas_proyectos.vista_cartela("prueba_cart", "S001")
check("la vista es el SVG que dibuja el render",
      vista.media_type == "image/svg+xml"
      and vista.body.startswith(b"<svg"))

# ---------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("cartelas en verde")
