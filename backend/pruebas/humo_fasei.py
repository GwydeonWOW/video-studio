"""Prueba de humo del asistente (Fase I), sin tocar servicios de pago.

Con ESTUDIO_SIMULAR=1 el asistente contesta sin llamar a ningún LLM: se
prueban las rutas (estado, foto, charlas, mensajes, cancelación, cierre)
y las validaciones. Ejecutar:

    python pruebas/humo_fasei.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_fasei_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
os.environ["ESTUDIO_SIMULAR"] = "1"
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


# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# ------------------------------------------------------------- estado global

r = cliente.get("/api/asistente")
check("GET /api/asistente", r.status_code == 200, str(r.status_code))
ficha = r.json() if r.status_code == 200 else {}
check("asistente listo en simulado", ficha.get("listo") is True,
      str(ficha)[:120])
check("asistente informa del modelo", bool(ficha.get("modelo")),
      str(ficha.get("modelo")))
check("asistente dice que simula", ficha.get("simulado") is True)

r = cliente.post("/api/asistente/probar")
check("POST /probar responde", r.status_code == 200, str(r.status_code))
prueba = r.json() if r.status_code == 200 else {}
check("probar sin clave es honesto",
      prueba.get("ok") is False and "sin clave" in str(prueba.get("detalle")),
      str(prueba)[:120])

# ------------------------------------------------------------------- la foto

r = cliente.get("/api/asistente/foto")
check("GET /api/asistente/foto", r.status_code == 200, str(r.status_code))
foto = str(r.json().get("foto", "")) if r.status_code == 200 else ""
check("la foto menciona claves", "claves" in foto, foto[:80])
check("la foto menciona simulado", "simulado" in foto)
check("la foto NO filtra ninguna clave real",
      "sk-" not in foto and "Bearer" not in foto)

# ------------------------------------------------ abrir charla y preguntar

r = cliente.post("/api/asistente/charlas")
check("POST /charlas crea 201", r.status_code == 201, str(r.status_code))
charla = r.json() if r.status_code == 201 else {}
cid = str(charla.get("id", ""))
check("la charla nueva está vacía y libre",
      cid and charla.get("turnos") == [] and charla.get("ocupada") is False,
      str(charla)[:120])

pregunta = {"texto": "¿qué pasos tiene el estudio?",
            "proyecto": "no-existe",
            "pantalla": {"pestana": "guion", "url": "#/x",
                         "errores": {"voz": "sin clave"}}}
r = cliente.post(f"/api/asistente/charlas/{cid}/mensajes", json=pregunta)
check("POST /mensajes acepta 202", r.status_code == 202, str(r.status_code))
respuesta = r.json() if r.status_code == 202 else {}
turnos = respuesta.get("turnos") or []
# en simulado la respuesta puede ganarle a la serialización del 202
check("el 202 devuelve tu turno y el del asistente",
      len(turnos) == 2 and turnos[0].get("quien") == "tu"
      and turnos[1].get("quien") == "asistente"
      and turnos[1].get("estado") in ("pensando", "listo"),
      str(turnos)[:160])

# sondeo como hace la pantalla: hasta listo o hartazgo
final: dict = {}
for _ in range(100):
    r = cliente.get(f"/api/asistente/charlas/{cid}")
    if r.status_code != 200:
        break
    final = r.json()
    if not final.get("ocupada"):
        break
    time.sleep(0.05)
check("el turno termina de pensar", r.status_code == 200
      and final.get("turnos"), str(r.status_code))
if final.get("turnos"):
    ultimo = final["turnos"][-1]
    check("la respuesta llega lista y simulada",
          ultimo.get("estado") == "listo"
          and "(simulado)" in str(ultimo.get("texto", "")),
          str(ultimo)[:160])
    check("la respuesta menciona la pregunta",
          "estudio" in str(ultimo.get("texto", "")).lower())

# preguntar con el proyecto abierto en pantalla no debe romper la foto
r = cliente.post(f"/api/asistente/charlas/{cid}/mensajes",
                 json={"texto": "otra", "pantalla": {"pestana": "voz"}})
check("segunda pregunta en la misma charla", r.status_code == 202,
      str(r.status_code))
for _ in range(100):
    r = cliente.get(f"/api/asistente/charlas/{cid}")
    if r.status_code != 200 or not r.json().get("ocupada"):
        break
    time.sleep(0.05)
final = r.json() if r.status_code == 200 else {}
check("la charla conserva el historial",
      len(final.get("turnos", [])) == 4, str(len(final.get("turnos", []))))

# ------------------------------------------------------------ validaciones

r = cliente.post(f"/api/asistente/charlas/{cid}/mensajes", json={"texto": "  "})
check("pregunta vacía -> 400", r.status_code == 400, str(r.status_code))

r = cliente.post(f"/api/asistente/charlas/{cid}/mensajes",
                 json={"texto": "x" * 20001})
check("pregunta kilométrica -> 400", r.status_code == 400, str(r.status_code))

r = cliente.get("/api/asistente/charlas/charla-fantasma")
check("charla que no existe -> 404", r.status_code == 404, str(r.status_code))

r = cliente.post("/api/asistente/charlas/{cid}/cancelar"
                 .replace("{cid}", cid))
check("cancelar una charla tranquila no hace nada",
      r.status_code == 200 and r.json().get("cancelado") is False,
      str(r.status_code))

# ------------------------------------------------------------- cierre

r = cliente.delete(f"/api/asistente/charlas/{cid}")
check("DELETE cierra la charla", r.status_code == 200
      and r.json().get("cerrada") is True, str(r.status_code))
r = cliente.get(f"/api/asistente/charlas/{cid}")
check("la charla cerrada ya no está", r.status_code == 404, str(r.status_code))

# -------------------------------------------------------------- resumen

print()
if fallos:
    print(f"FALLOS: {len(fallos)} -> " + ", ".join(fallos))
    sys.exit(1)
print("fase I en verde")
