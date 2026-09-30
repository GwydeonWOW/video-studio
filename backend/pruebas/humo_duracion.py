"""Prueba de humo de la duración configurable del vídeo.

El guion obedece MINUTOS traducidos a PALABRAS: la duración pedida se
vuelve presupuesto (a 2,6 palabras/s) con horquilla ±30 %, el prompt
lleva el reparto con su aritmética (N x M ≈ total), el techo de tokens
crece con el vídeo y un reintento con correcciones — que viajan con el
texto que corrigen — arregla el largo si se sale de la horquilla, y
gana el intento MÁS CERCANO al objetivo. Sin proyectos con duración
(modo viejo con «escenas») nada de esto aparece.

Sin claves de pago: `llm.llamar_json` se sustituye por un doble que
devuelve brief y guiones de latas con las palabras contadas.
Ejecutar:

    python pruebas/humo_duracion.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_duracion_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.motores import llm  # noqa: E402
from app.pasos import p3_guion  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


def esperar_trabajo(tid: str, tope_s: float = 30.0) -> dict:
    limite = time.time() + tope_s
    while time.time() < limite:
        ficha = cliente.get(f"/api/trabajos/{tid}").json()
        if ficha.get("estado") in ("hecho", "fallo", "cancelado"):
            return ficha
        time.sleep(0.1)
    return {"estado": "timeout"}


cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# ------------------------------------------------------ la aritmética pura

check("params por defecto del guion: duración, no escenas",
      p3_guion.params_defecto()["duracion_min"] == 10
      and "escenas" not in p3_guion.params_defecto(),
      str(p3_guion.params_defecto()))

h = p3_guion._horquilla(40, {"min": 20, "max": 40})
# 40 min = 2400 s x 2,6 = 6240 palabras; ±30 % -> 4368..8112; escenas
# de ~78 palabras (30 s de media) -> 80 escenas
check("horquilla de 40 min: 6240 palabras (4368-8112)",
      h["objetivo"] == 6240 and h["min"] == 4368 and h["max"] == 8112,
      str(h))
check("reparto: 80 escenas de 78 palabras",
      h["escenas"] == 80 and h["palabras_escena"] == 78, str(h))
check("sin duración no hay horquilla (modo viejo)",
      p3_guion._horquilla(None, None) is None
      and p3_guion._horquilla(0, None) is None)

# ------------------------------------------------- el doble del modelo

def palabras(n: int) -> str:
    return " ".join(f"palabra{i}" for i in range(n))


def guion_lata(n_escenas: int, n_palabras: int) -> dict:
    return {"escenas": [
        {"id": f"S{i:03d}", "titulo": f"escena {i}",
         "narracion": palabras(n_palabras), "visual": "un plano",
         "texto_pantalla": "rotulo", "duracion_estimada": 10}
        for i in range(1, n_escenas + 1)]}


registro_llamadas: list[dict] = []
respuestas_guion: list[dict] = []
_llamar_json_real = llm.llamar_json


def llamar_json_falso(llamada, claves=None, **_):
    registro_llamadas.append({
        "contexto": getattr(llamada, "contexto", ""),
        "instruccion": getattr(llamada, "instruccion", ""),
        "max_tokens": getattr(llamada, "max_tokens", None),
    })
    if getattr(llamada, "contexto", "") == "brief":
        return {"puntos": ["un punto", "otro punto", "y otro"],
                "tono": "cercano", "formato": {"min": 20, "max": 40}}
    return respuestas_guion.pop(0)


llm.llamar_json = llamar_json_falso

# ------------------------------------------------- proyecto hasta el guion

TEXTO = ("La historia del transistor cuenta cómo un trozo de silicio "
         "aprendió a amplificar. " * 12).strip()

r = cliente.post("/api/proyectos", json={"nombre": "Duración"})
pid = r.json()["id"]
pasos = cliente.get(f"/api/proyectos/{pid}/pasos").json()
check("proyecto nuevo siembra duracion_min=10",
      pasos["pasos"]["guion"]["params"].get("duracion_min") == 10,
      str(pasos["pasos"]["guion"]["params"]))

cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
            json={"texto": TEXTO, "titulo": "El transistor"})
ficha = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/ingesta/ejecutar", json={}).json()["id"])
check("ingesta hecha", ficha["estado"] == "hecho", str(ficha)[:150])

ficha = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/brief/ejecutar", json={}).json()["id"])
check("brief hecho", ficha["estado"] == "hecho", str(ficha)[:150])

estimacion = cliente.get(
    f"/api/proyectos/{pid}/pasos/guion/estimacion").json()
check("estimación con duración cuenta el reintento (2 llamadas)",
      estimacion.get("llamadas_llm") == 2, str(estimacion))

# --------------------------------------------- 40 min: corto -> corrección

cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
            json={"duracion_min": 40})
registro_llamadas.clear()
respuestas_guion[:] = [
    guion_lata(4, 30),     # 120 palabras: muy por debajo de 4368
    guion_lata(80, 78),    # 6240: clavado en el objetivo
]
ficha = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/guion/ejecutar", json={}).json()["id"])
check("guion de 40 min hecho", ficha["estado"] == "hecho",
      str(ficha)[:200])

guion = [c for c in registro_llamadas if c["contexto"] == "guion"]
check("el corto disparó el reintento (2 llamadas al guion)",
      len(guion) == 2, str(len(guion)))
if len(guion) == 2:
    check("la primera lleva la sección LONGITUD con sus cifras",
          "LONGITUD DEL VÍDEO" in guion[0]["instruccion"]
          and "4368" in guion[0]["instruccion"]
          and "8112" in guion[0]["instruccion"]
          and "80 x 78" in guion[0]["instruccion"])
    check("la corrección VIAJA con el texto corregido",
          "CORRECCIONES AL INTENTO ANTERIOR" in guion[1]["instruccion"]
          and "S001 (30 pal.)" in guion[1]["instruccion"])
    check("el techo de tokens crece con el vídeo (6240 x 2,5)",
          guion[0]["max_tokens"] == 15600, str(guion[0]["max_tokens"]))

datos = cliente.get(f"/api/proyectos/{pid}/pasos/guion").json()["datos"]
check("gana el intento más cercano: 6240 palabras, no las 120 del corto",
      datos.get("horquilla", {}).get("palabras") == 6240, str(datos.get("horquilla")))
check("horquilla guardada en los datos",
      datos.get("horquilla", {}).get("min") == 4368
      and datos.get("horquilla", {}).get("max") == 8112
      and datos.get("horquilla", {}).get("objetivo") == 6240,
      str(datos.get("horquilla")))
check("80 escenas renumeradas S001..S080",
      len(datos["escenas"]) == 80
      and datos["escenas"][0]["id"] == "S001"
      and datos["escenas"][-1]["id"] == "S080",
      f"{len(datos['escenas'])} escenas")

# ------------------------------------- si ya está en la horquilla, no reintenta

registro_llamadas.clear()
respuestas_guion[:] = [guion_lata(80, 78)]
ficha = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/guion/ejecutar", json={}).json()["id"])
check("regenerar con el largo bien: hecho y SIN reintento",
      ficha["estado"] == "hecho"
      and len([c for c in registro_llamadas if c["contexto"] == "guion"]) == 1,
      str(ficha)[:150])

# --------------------------------------------- modo viejo: manda «escenas»

cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
            json={"escenas": 5})
registro_llamadas.clear()
respuestas_guion[:] = [guion_lata(5, 60)]
ficha = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/guion/ejecutar", json={}).json()["id"])
check("guion viejo (escenas) hecho", ficha["estado"] == "hecho",
      str(ficha)[:150])
guion_viejo = [c for c in registro_llamadas if c["contexto"] == "guion"]
check("una sola llamada, sin sección LONGITUD ni reintento",
      len(guion_viejo) == 1
      and "LONGITUD DEL VÍDEO" not in guion_viejo[0]["instruccion"]
      and "Numero de escenas apuntado: 5" in guion_viejo[0]["instruccion"],
      str(len(guion_viejo)))
check("sin horquilla en los datos (comportamiento de siempre)",
      "horquilla" not in cliente.get(
          f"/api/proyectos/{pid}/pasos/guion").json()["datos"])

llm.llamar_json = _llamar_json_real

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("duración en verde")
