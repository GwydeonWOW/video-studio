"""Prueba de humo de las rutas de la Fase F, sin tocar servicios de pago.

Catálogo, encuadres, guía, moodboard y conservación: GET/PUT y los
errores honrados (400 cuando falta material). Ejecutar:

    python pruebas/humo_fasef.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_fasef_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" — {detalle}" if detalle else ""))
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


# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})


def get(ruta: str):
    return cliente.get(ruta)


def put(ruta: str, cuerpo: dict):
    return cliente.put(ruta, json=cuerpo)


def post(ruta: str, cuerpo: dict | None = None):
    return cliente.post(ruta, json=cuerpo or {})


r = post("/api/proyectos", {"nombre": "Fase F", "canal": "pruebas"})
check("crear proyecto", r.status_code == 201, str(r.text)[:120])
pid = r.json()["id"]

# ------------------------------------------------------------------ catálogo

r = get(f"/api/proyectos/{pid}/catalogo")
check("GET catalogo vacío", r.status_code == 200
      and r.json()["catalogo"]["reparto"] == {})

r = put(f"/api/proyectos/{pid}/catalogo",
        {"catalogo": {
            "reparto": {"Ana": {"descripcion": "a tall woman in a red coat",
                                "papel": "narradora"}},
            "sets": {"calle": {"descripcion": "a narrow street",
                               "luz": "dusk"}},
            "beats": [{"desde": "S001", "hasta": "S003", "set": "calle",
                       "personajes": ["ana"], "tono": "tenso",
                       "accion": "she runs"}]}})
check("PUT catalogo guarda reparto", r.status_code == 200
      and "ana" in r.json()["catalogo"]["reparto"])
check("PUT catalogo avisa del beat huérfano (sin guion)",
      bool(r.json()["avisos"]), str(r.json().get("avisos"))[:120])

r = get(f"/api/proyectos/{pid}/catalogo")
check("catálogo persistido", "ana" in r.json()["catalogo"]["reparto"])

r = put(f"/api/proyectos/{pid}/catalogo", {"catalogo": "no"})
check("PUT catalogo rechaza cuerpo raro", r.status_code == 400)

# ----------------------------------------------------------------- encuadres

r = get(f"/api/proyectos/{pid}/encuadres")
check("GET encuadres", r.status_code == 200
      and len(r.json()["catalogo"]) == 15
      and r.json()["reparto"] == {})

r = put(f"/api/proyectos/{pid}/encuadres", {"plan": {"S001": "retrato"}})
check("PUT encuadres sin guion - 400 honrado", r.status_code == 400)

r = put(f"/api/proyectos/{pid}/encuadres", {"plan": {}})
check("PUT encuadres vacío - 400", r.status_code == 400)

# ---------------------------------------------------------------------- guía

r = get(f"/api/proyectos/{pid}/guia")
check("GET guia vacía", r.status_code == 200
      and r.json()["guia"] == {}
      and r.json()["moodboard"]["estado"] == "falta")

r = put(f"/api/proyectos/{pid}/guia",
        {"guia": {"guia": "2px uniform black outlines, flat colors.",
                  "evitar": "no gradients, no cast shadows",
                  "paleta": ["#1a1a1a", "#F5F0E6", "zzz"],
                  "manos": "five fingers, small, outlined",
                  "resumen_es": "plano con contorno negro"}})
cuerpo = r.json()
check("PUT guia filtra la paleta", r.status_code == 200
      and cuerpo["guia"]["paleta"] == ["#1a1a1a", "#f5f0e6"],
      str(cuerpo.get("guia", {}).get("paleta")))

r = get(f"/api/proyectos/{pid}/guia")
check("guía persistida con clave de moodboard",
      len(r.json()["moodboard"]["clave"]) == 16)

# ----------------------------------------------------------------- moodboard

r = get(f"/api/proyectos/{pid}/moodboard")
ficha = r.json()
check("GET moodboard posible (hay guía)", ficha["posible"] is True)
check("moodboard: 6 ejes, todos sin dibujar",
      len(ficha["ejes"]) == 6 and all(not e["hay"] for e in ficha["ejes"]))

r = post(f"/api/proyectos/{pid}/moodboard/aprobar")
check("aprobar sin propuesta - 400", r.status_code == 400)

r = get(f"/api/proyectos/{pid}/moodboard/cara/imagen")
check("lámina inexistente - 404", r.status_code == 404)

# -------------------------------------------------------------- conservación

r = post(f"/api/proyectos/{pid}/conservacion")
check("POST conservacion encola", r.status_code == 202)
ficha = esperar_trabajo(r.json()["id"])
check("conservación sin voz grabada: posible False honrado",
      ficha["estado"] == "hecho"
      and ficha["resultado"]["posible"] is False
      and "voz" in ficha["resultado"]["por_que_no"],
      str(ficha.get("resultado"))[:160])

r = post(f"/api/proyectos/{pid}/conservacion/aplicar", {"posible": False})
check("aplicar un plan imposible - 400", r.status_code == 400)

# ------------------------------------------------------------------- resumen

print()
if fallos:
    print(f"{len(fallos)} FALLO(S): " + ", ".join(fallos))
    sys.exit(1)
print("fase F en verde")
