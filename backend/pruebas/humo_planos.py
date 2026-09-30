"""Prueba de humo del ritmo de montaje: planos por escena (segmentar).

UNA ESCENA, VARIOS PLANOS: las marcas de palabra de la voz se cortan en
planos de 3–6 s sobre las pausas reales. Se comprueba sin pagar nada
(`imagen_glm.generar` sustituido por un doble que escribe un PNG de
nada):

- el corte respeta la horquilla y las ventanas TILEAN el audio
  (t_out de un plano == t_in del siguiente, el último se lleva el cola)
- los planos vecinos piden imágenes DISTINTAS (capa frase)
- la cartela es UN plano de texto ESCRITO sobre su imagen (la paga)
- la voz sin marcas de palabra (cata/vieja) es UN plano, como siempre
- regrabar la voz (+80 ms) HEREDA el corte: no se re-corta ni se tiran
  las imágenes; si el texto cambió demasiado, corte de cero
- regenerar_plano devuelve TODOS los planos de la escena
- la API empalma el bloque por unidad (rutas_proyectos) sin desordenar

Ejecutar:

    python pruebas/humo_planos.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_planos_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.api import rutas_proyectos  # noqa: E402
from app.motores import imagen_glm  # noqa: E402
from app.motores.guion import segmentar  # noqa: E402
from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.pasos import p6_assets  # noqa: E402

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


# ------------------------------------------------- la voz con sus marcas

def frase(t: float, *palabras: str, paso: float = 0.30, hueco: float = 0.05):
    """[(palabra, inicio, fin)] seguidas; devuelve (palabras, t_final)."""
    sal = []
    for p in palabras:
        sal.append({"palabra": p, "inicio": round(t, 3),
                    "fin": round(t + paso, 3)})
        t += paso + hueco
    return sal, t


PALABRAS_S1: list[list[str]] = [
    ["El", "transistor", "nacio", "de", "un", "trozo", "de", "silicio",
     "sucio."],
    ["Amplificaba", "senales", "pequenas", "hasta", "volverlas",
     "gritos", "limpios", "y", "serenos."],
    ["El", "mundo", "entero", "escucho", "el", "rumor", "de", "aquel",
     "invento."],
    ["Y", "la", "electronica", "nunca", "volvio", "a", "ser", "igual",
     "despues."],
]

palabras_s1: list[dict] = []
t = 0.0
for oracion in PALABRAS_S1:
    trozo, t = frase(t, *oracion)
    palabras_s1.extend(trozo)
    t += 0.65            # la pausa real: aquí debe cortar
FIN_PALABRAS = round(t - 0.05, 3)     # fin de la última palabra
DURACION_S1 = round(FIN_PALABRAS + 1.2, 3)   # el silencio final es del último

# ------------------------------------------------- el proyecto de latas

_dir_proy = Path(_dir_datos) / "proyectos" / "prueba_planos"
(_dir_proy / "pasos" / "guion").mkdir(parents=True)
(_dir_proy / "pasos" / "voz").mkdir(parents=True)
(_dir_proy / "pasos" / "assets").mkdir(parents=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "planos"})
escribir_json(_dir_proy / "pasos" / "guion" / "datos.json", {"escenas": [
    {"id": "S001", "titulo": "varios planos",
     "narracion": " ".join(" ".join(o) for o in PALABRAS_S1),
     "visual": "un taller con luz de ventana"},
    {"id": "S002", "titulo": "cartela",
     "narracion": "frase corta para texto", "visual": ""},
    {"id": "S003", "titulo": "voz vieja sin marcas",
     "narracion": "escena sin marcas de palabra", "visual": "un plano fijo"},
]})
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": DURACION_S1, "palabras": palabras_s1},
    {"id": "S002", "duracion": 2.1, "palabras": []},
    {"id": "S003", "duracion": 5.0},
]})
proyecto = Proyecto(_dir_proy)

# --------------------------------------------- dobles: imágenes gratis

encargos: list[str] = []
_clave_real, _generar_real = imagen_glm.clave, imagen_glm.generar
_anotar_real = p6_assets.anotar_operacion


def generar_falso(encargo, destino, **_):
    encargos.append(encargo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # bytes DISTINTOS por encargo: el guardian de planos repetidos
    # tumba la tanda si dos ficheros acaban identicos, y un doble que
    # escribe siempre lo mismo lo dispararia sin haber fallo ninguno
    import hashlib
    destino.write_bytes(b"\x89PNG\r\n\x1a\n"
                        + hashlib.sha256(encargo.encode("utf-8")).digest())


imagen_glm.clave = lambda *a, **k: True
imagen_glm.generar = generar_falso
p6_assets.anotar_operacion = lambda **_: None

llamadas = {"heredar": 0, "segmentar": 0}
_heredar_real, _segmentar_real = segmentar.heredar, segmentar.segmentar


def heredar_espiado(*a, **k):
    llamadas["heredar"] += 1
    return _heredar_real(*a, **k)


def segmentar_espiado(*a, **k):
    llamadas["segmentar"] += 1
    return _segmentar_real(*a, **k)


segmentar.heredar = heredar_espiado
segmentar.segmentar = segmentar_espiado

PARAMS = {"calidad": "low", "estilo": "",
          "unidades": {"S002": {"cartela": {"plantilla": "cifra",
                                             "datos": {"cifra": "1947",
                                                       "label": "el transistor"}}}}}

# ------------------------------------------------------- el primer corte

resultado = p6_assets.ejecutar(proyecto, PARAMS, TrabajoMudo())
planos = resultado["planos"]
de_s1 = [p for p in planos if p["escena"] == "S001"]
de_s2 = [p for p in planos if p["escena"] == "S002"]
de_s3 = [p for p in planos if p["escena"] == "S003"]

check("S001 sale en varios planos", len(de_s1) == 4,
      " / ".join(p["id"] for p in de_s1))
check("los planos de una escena llevan sub-id",
      [p["id"] for p in de_s1] == [f"S001-{k}" for k in range(1, 5)],
      str([p["id"] for p in de_s1]))
check("el corte fue FRESCO (nada que heredar la primera vez)",
      llamadas["heredar"] == 0 and llamadas["segmentar"] >= 1,
      str(llamadas))

duraciones = [p["duracion"] for p in de_s1]
check("las duraciones obedecen la horquilla 3–6 s",
      all(3.0 - 0.05 <= d <= 6.0 + 0.05 for d in duraciones),
      str(duraciones))

check("las ventanas TILEAN el audio sin solaparse",
      de_s1[0]["t_in"] == 0.0
      and all(abs(a["t_out"] - b["t_in"]) <= 0.011
              for a, b in zip(de_s1, de_s1[1:])),
      " / ".join(f"{p['t_in']}-{p['t_out']}" for p in de_s1))
check("el ULTIMO plano se lleva el silencio final",
      abs(de_s1[-1]["t_out"] - DURACION_S1) < 0.01,
      f"{de_s1[-1]['t_out']} vs {DURACION_S1}")

releido = " ".join(p["narracion"] for p in de_s1).split()
original = " ".join(" ".join(o) for o in PALABRAS_S1).split()
check("la narracion de los planos recompone la escena",
      releido == original, str(releido)[:80])

check("vecinos con imagen DISTINTA (la capa frase distingue)",
      len({p["prompt"] for p in de_s1}) == len(de_s1),
      str(len({p["prompt"] for p in de_s1})))

check("S002 cartela: UN plano de texto ESCRITO sobre su imagen (la paga)",
      len(de_s2) == 1 and de_s2[0]["id"] == "S002"
      and de_s2[0].get("imagen") is not None
      and (de_s2[0].get("cartela") or {}).get("plantilla") == "cifra"
      and isinstance(de_s2[0].get("escritura"), dict),
      str(de_s2)[:120])
check("S003 sin marcas: la escena entera es UN plano (como siempre)",
      len(de_s3) == 1 and de_s3[0]["id"] == "S003"
      and de_s3[0]["t_in"] == 0.0
      and abs(de_s3[0]["t_out"] - 5.0) < 0.01,
      str(de_s3)[:120])

informe = resultado.get("informe") or {}
check("informe del ritmo guardado con su horquilla",
      informe.get("horquilla") == [3.0, 6.0]
      and informe.get("planos") == len(de_s1)
      and informe.get("fuera_de_rango") == 0,
      str(informe)[:160])
check("el ritmo viaja en los datos", resultado.get("ritmo") == {
    "minimo": 3.0, "maximo": 6.0}, str(resultado.get("ritmo")))

check("zoom y transicion en cada plano",
      all(isinstance(p.get("zoom"), dict) and "de" in p["zoom"]
          and "a" in p["zoom"] and p.get("transicion")
          in ("suave", "acento", "corte") for p in planos),
      str(planos[0].get("zoom")))

# --------------------------------------------- regrabar la voz: HEREDAR

escribir_json(_dir_proy / "pasos" / "assets" / "datos.json", resultado)
llamadas.update(heredar=0, segmentar=0)
encargos.clear()
desplazadas = [{"palabra": w["palabra"],
                "inicio": round(w["inicio"] + 0.08, 3),
                "fin": round(w["fin"] + 0.08, 3)} for w in palabras_s1]
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": round(DURACION_S1 + 0.08, 3),
     "palabras": desplazadas},
    {"id": "S002", "duracion": 2.1, "palabras": []},
    {"id": "S003", "duracion": 5.0},
]})

regrabado = p6_assets.ejecutar(proyecto, PARAMS, TrabajoMudo())
de_s1b = [p for p in regrabado["planos"] if p["escena"] == "S001"]
check("regrabar (+80 ms) HEREDA el corte: mismo numero de planos",
      len(de_s1b) == len(de_s1) and llamadas["heredar"] >= 1
      and llamadas["segmentar"] == 0,
      f"{len(de_s1b)} planos, espia {llamadas}")
check("y las mismas fronteras de texto",
      [p["narracion"] for p in de_s1b] == [p["narracion"] for p in de_s1],
      str([p["narracion"] for p in de_s1b])[:100])

# el texto cambió demasiado: heredar declina y se corta de cero
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json", regrabado)
llamadas.update(heredar=0, segmentar=0)
cambiadas = [dict(w) for w in desplazadas]
for w in cambiadas[: 2 * len(cambiadas) // 3]:
    w["palabra"] = "otra"
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": round(DURACION_S1 + 0.08, 3),
     "palabras": cambiadas},
    {"id": "S002", "duracion": 2.1, "palabras": []},
    {"id": "S003", "duracion": 5.0},
]})
rotado = p6_assets.ejecutar(proyecto, PARAMS, TrabajoMudo())
check("texto irreconocible: heredar declina y se corta de cero",
      llamadas["heredar"] >= 1 and llamadas["segmentar"] >= 1,
      str(llamadas))

# ------------------------------------------------ regenerar UNA escena

unico = p6_assets.regenerar_plano(proyecto, "S003",
                                  {"calidad": "low", "estilo": ""})
check("regenerar_plano devuelve TODOS los planos de esa escena",
      isinstance(unico, list) and len(unico) == 1
      and unico[0]["escena"] == "S003", str(unico)[:120])

# --------------------------- la API empalma bloques por unidad, en orden

datos = {"planos": [{"id": "S001-1", "escena": "S001"},
                    {"id": "S001-2", "escena": "S001"},
                    {"id": "S002", "escena": "S002"}],
         "calidad": "low"}
check("_contar_unidades cuenta ESCENAS, no filas",
      rutas_proyectos._contar_unidades(datos) == 2,
      str(rutas_proyectos._contar_unidades(datos)))

rutas_proyectos._sustituir_unidad(datos, "S001",
                                  [{"id": "S001-1", "escena": "S001"},
                                   {"id": "S001-2", "escena": "S001"},
                                   {"id": "S001-3", "escena": "S001"}])
check("_sustituir_unidad empalma el BLOQUE donde estaba la escena",
      [p["id"] for p in datos["planos"]] ==
      ["S001-1", "S001-2", "S001-3", "S002"],
      str([p["id"] for p in datos["planos"]]))

rutas_proyectos._sustituir_unidad(datos, "S009",
                                  [{"id": "S009", "escena": "S009"}])
check("una unidad NUEVA entra al final",
      [p["id"] for p in datos["planos"]][-1] == "S009",
      str([p["id"] for p in datos["planos"]]))

mezcla = rutas_proyectos._fusionar_unidades(
    {"planos": [{"id": "S001-1", "escena": "S001"},
                {"id": "S001-2", "escena": "S001"},
                {"id": "S002", "escena": "S002"}], "calidad": "low"},
    {"planos": [{"id": "S001-1", "escena": "S001"},
                {"id": "S001-2", "escena": "S001"}], "calidad": "low"},
    ["S001"])
check("_fusionar_unidades conserva las escenas NO regeneradas",
      [p["id"] for p in mezcla["planos"]] ==
      ["S001-1", "S001-2", "S002"],
      str([p["id"] for p in mezcla["planos"]]))

# ------------------------------------------------------ devolver dobles

imagen_glm.clave, imagen_glm.generar = _clave_real, _generar_real
p6_assets.anotar_operacion = _anotar_real
segmentar.heredar, segmentar.segmentar = _heredar_real, _segmentar_real

# ---------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("planos en verde")
