"""Prueba de humo del medidor de coste: anotar, leer y desglosar.

Los defectos que vigila (los dos se colaron a la vez): el global caía en
una carpeta relativa al directorio de arranque —ignorando `ESTUDIO_DATOS`,
que es donde lee la API— y el coste de un vídeo nunca llegaba a su
`coste.jsonl` porque ningún motor le pasaba la carpeta al medidor: la
pantalla del coste daba cero aunque el LLM hubiese gastado. Se prueba el
ciclo entero: anotar por operación (llm/imagen/voz), la derivación de la
carpeta desde el id, el desglose por vídeo del global, el límite de
eventos, que un «proyecto» que no es un id válido no fabrica carpetas, y
las tarifas por HTTP. Ejecutar:

    python pruebas/humo_coste.py

Sale 0 si todo verde; imprime cada chequeo.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# datos aislados ANTES de importar la app: el medidor escribe ahí
_raiz = Path(__file__).resolve().parent.parent
_dir = tempfile.mkdtemp(prefix="estudio_humo_coste_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AJUSTES  # noqa: E402
from app.main import app  # noqa: E402
from app.nucleo import coste  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" — {detalle}" if detalle and not condicion else ""))
    if not condicion:
        fallos.append(nombre)


def _leer(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in
            ruta.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------- anotar

# una operación de cada tipo, pasando SOLO el id del proyecto: el medidor
# deriva la carpeta (los motores no la conocen)
coste.anotar_operacion(proyecto="coste_a", operacion="llm", proveedor="glm",
                       modelo="glm-4.6", entrada=1000, salida=500,
                       contexto="guion")
coste.anotar_operacion(proyecto="coste_a", operacion="imagen", proveedor="glm",
                       calidad="low", contexto="assets:escena:S01")
coste.anotar_operacion(proyecto="coste_b", operacion="voz",
                       proveedor="elevenlabs", caracteres=900, contexto="voz")

base = AJUSTES.datos
global_ = _leer(base / "coste_global.jsonl")
check("el global vive en ESTUDIO_DATOS (no en el cwd)", len(global_) == 3,
      str(base))

dir_a = base / "proyectos" / "coste_a"
lineas_a = _leer(dir_a / "coste.jsonl")
check("el coste.jsonl del vídeo recibe sus operaciones", len(lineas_a) == 2)
check("la carpeta del vídeo solo lleva lo suyo",
      all(e["proyecto"] == "coste_a" for e in lineas_a))
check("el otro vídeo también tiene la suya",
      (base / "proyectos" / "coste_b" / "coste.jsonl").is_file())

# un «proyecto» que no es un id válido (un título, por ejemplo): solo
# global — no fabrica carpetas con espacios o mayúsculas
coste.anotar_operacion(proyecto="Mi Vídeo (borrador)", operacion="llm",
                       proveedor="glm", entrada=10, salida=10)
check("un proyecto inválido solo anota en el global",
      len(_leer(base / "coste_global.jsonl")) == 4
      and not (base / "proyectos" / "Mi Vídeo (borrador)").exists())

# ------------------------------------------------------------------ desglose

ficha = coste.global_(base)
check("el global suma las cuatro operaciones", ficha["operaciones"] == 4)
por = ficha["por_proyecto"]
check("el desglose va del que más gastó al que menos",
      por == sorted(por, key=lambda f: f["coste"], reverse=True)
      and por[0]["proyecto"] == "coste_b",     # voz 900 car × 0,15 $/k = 0,135
      str([(f["proyecto"], f["coste"]) for f in por]))
ficha_a = next(f for f in por if f["proyecto"] == "coste_a")
check("la ficha del vídeo desglosa por operación",
      set(ficha_a["por_operacion"]) == {"llm", "imagen"})
check("cada ficha cuadra con el coste.jsonl del vídeo",
      abs(ficha_a["coste"] - coste.de_proyecto(dir_a)["coste"]) < 1e-9)
check("lo anotado sin id válido queda agrupado aparte",
      len(por) == 3 and any(f["proyecto"] == "Mi Vídeo (borrador)"
                            for f in por))

recortada = coste.global_(base, limite=1)
check("el límite recorta los eventos del global",
      recortada["operaciones"] == 1 and len(recortada["por_proyecto"]) == 1)

# ----------------------------------------------------------------- por HTTP

r = cliente.get("/api/coste/global")
check("GET /api/coste/global trae el desglose",
      r.status_code == 200 and "por_proyecto" in r.json()
      and r.json()["operaciones"] == 4)
r = cliente.get("/api/coste/global", params={"limite": 2})
check("el límite llega por query", r.json()["operaciones"] == 2)

r = cliente.put("/api/coste/tarifas", json={"glm/imagen": {"low": 0.02}})
check("PUT /api/coste/tarifas mezcla sin perder el resto",
      r.status_code == 200 and r.json()["glm/imagen"]["low"] == 0.02
      and r.json()["glm/tokens"] == coste.TARIFAS_DEFECTO["glm/tokens"])

# y la tarifa recién escrita manda en la operación siguiente
coste.anotar_operacion(proyecto="coste_a", operacion="imagen", proveedor="glm",
                       calidad="low", contexto="assets:escena:S02")
ultimas = _leer(dir_a / "coste.jsonl")
check("la tarifa escrita manda en el coste calculado",
      abs(ultimas[-1]["coste"] - 0.02) < 1e-9,
      f"coste={ultimas[-1]['coste']}")

# --------------------------------------------------------------------- sale

if fallos:
    print(f"\n{len(fallos)} fallo(s): " + ", ".join(fallos))
    sys.exit(1)
print("\nOK — humo del medidor de coste")
