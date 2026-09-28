"""Prueba de humo de la Fase J, sin tocar servicios de pago.

Ajustes generales del servicio (la guía de inicio y su marca onboarding_visto)
y el coste global que enseña la cabecera. Ejecutar:

    python pruebas/humo_fasej.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_fasej_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


def get(ruta: str):
    return cliente.get(ruta)


def put(ruta: str, cuerpo: dict):
    return cliente.put(ruta, json=cuerpo)


# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# -------------------------------------------------------- guía de inicio

r = get("/api/ajustes")
check("GET ajustes recién instalado: guía sin ver",
      r.status_code == 200 and r.json().get("onboarding_visto") is False,
      str(r.text)[:120])

r = put("/api/ajustes", {"onboarding_visto": True})
check("PUT cerrar la guía (Empezar o Saltar)",
      r.status_code == 200 and r.json().get("onboarding_visto") is True)

r = get("/api/ajustes")
check("GET ajustes: la marca persiste", r.json().get("onboarding_visto") is True)

fichero = Path(os.environ["ESTUDIO_DATOS"]) / "ajustes.json"
datos = json.loads(fichero.read_text(encoding="utf-8"))
check("la marca vive en ajustes.json (ajuste del servidor)",
      isinstance(datos, dict) and datos.get("onboarding_visto") is True)

r = put("/api/ajustes", {"onboarding_visto": "sí"})
check("PUT valor no booleano: 400 honrado",
      r.status_code == 400 and "onboarding_visto" in r.json().get("error", ""),
      str(r.text)[:120])

r = put("/api/ajustes", {"chisme": 1})
check("PUT ajuste desconocido: 400 que lo nombra",
      r.status_code == 400 and "chisme" in r.json().get("error", ""))

r = put("/api/ajustes", {})
check("PUT vacío no rompe nada",
      r.status_code == 200 and r.json().get("onboarding_visto") is True)

# la ruta de modelos escribe su trozo sin pisar la marca de la guía
r = put("/api/ajustes/llm", {"llm": {"guion": {"proveedor": "glm",
                                               "modelo": ""}}})
check("PUT ajustes/llm no pisa la marca",
      r.status_code == 200 and r.json().get("onboarding_visto") is True
      and r.json().get("llm", {}).get("guion", {}).get("proveedor") == "glm")

r = get("/api/ajustes")
check("GET ajustes tras guardar modelos: todo junto",
      r.json().get("llm", {}).get("guion", {}).get("proveedor") == "glm"
      and r.json().get("onboarding_visto") is True)

# --------------------------------------------- claves que enseña la guía

r = get("/api/claves")
claves = r.json()
ids = {c["clave"] for c in claves}
check("GET claves: el catálogo de la guía",
      r.status_code == 200
      and {"glm", "openai", "elevenlabs", "jamendo", "freesound"} <= ids
      and all(c.get("presente") is False and c.get("mascara") == ""
              for c in claves))

r = put("/api/claves", {"glm": "una-clave-de-prueba"})
check("PUT claves desde la guía: estado con máscara",
      r.status_code == 200
      and any(c["clave"] == "glm" and c["presente"]
              and c["mascara"].endswith("ueba") for c in r.json()))

# ------------------------------------------------- coste de la cabecera

r = get("/api/coste/global")
ficha = r.json()
check("GET coste/global en vacío",
      r.status_code == 200 and ficha["operaciones"] == 0
      and ficha["coste"] == 0 and "por_operacion" in ficha
      and "por_proveedor" in ficha)

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("fase J en verde")
