"""Prueba de humo de las rutas de la Fase G, sin tocar servicios de pago.

Sonido (música, efectos, banda, vetados) y transiciones: GET/PUT y los
errores honrados (400 cuando falta voz o clave). Ejecutar:

    python pruebas/humo_faseg.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_faseg_")
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


def get(ruta: str):
    return cliente.get(ruta)


def put(ruta: str, cuerpo: dict):
    return cliente.put(ruta, json=cuerpo)


def post(ruta: str, cuerpo: dict | None = None):
    return cliente.post(ruta, json=cuerpo or {})


# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

r = post("/api/proyectos", {"nombre": "Fase G", "canal": "pruebas"})
check("crear proyecto", r.status_code == 201, str(r.text)[:120])
pid = r.json()["id"]

# -------------------------------------------------------------------- sonido

r = get(f"/api/proyectos/{pid}/sonido")
ficha = r.json()
check("GET sonido vacío", r.status_code == 200
      and ficha["activo"] is True
      and ficha["musica"] == {}
      and ficha["efectos"] == []
      and ficha["lufs"] == -23.0)
check("GET sonido: 5 papeles y ánimos",
      set(ficha["papeles"]) == {"transicion_suave", "transicion_acento",
                                "entrada_cartela", "tecla", "retorno"}
      and len(ficha["animos"]) >= 5
      and ficha["hay_jamendo"] is False
      and ficha["hay_freesound"] is False)
check("GET sonido: resumen honrado sin nada surtido",
      ficha["resumen"] != "" and ficha["vetados"] == []
      and ficha["creditos"] == [])

r = put(f"/api/proyectos/{pid}/sonido",
        {"activo": False, "lufs": 99.0, "musica_db": -3, "efectos_db": 2})
ficha = r.json()
check("PUT sonido: interruptor y lufs encasillado", r.status_code == 200
      and ficha["activo"] is False
      and ficha["lufs"] == -10.0
      and ficha["musica_db"] == -3.0
      and ficha["efectos_db"] == 2.0)

r = put(f"/api/proyectos/{pid}/sonido", {"musica": "no-es-un-tema"})
check("PUT sonido rechaza musica rara - 400", r.status_code == 400)

r = put(f"/api/proyectos/{pid}/sonido", {"musica": {"id": "x"}})
check("PUT sonido tema sin URL de descarga - 502 honrado",
      r.status_code == 502, str(r.text)[:120])

r = get(f"/api/proyectos/{pid}/sonido/arco")
check("GET arco sin voz - 400 honrado", r.status_code == 400)

r = post(f"/api/proyectos/{pid}/sonido/banda")
check("POST banda sin voz - 400", r.status_code == 400)

r = post(f"/api/proyectos/{pid}/sonido/efectos")
check("POST efectos sin clave FreeSound - 400", r.status_code == 400)

r = post(f"/api/proyectos/{pid}/sonido/musica", {"animo": "epico"})
check("POST buscar música sin clave Jamendo - 400", r.status_code == 400)

# ------------------------------------------------------------------- vetados

efecto = {"fuente": "freesound", "id": "777", "titulo": "whoosh largo",
          "autor": "alguien"}
r = post(f"/api/proyectos/{pid}/sonido/vetados",
         {"efecto": efecto, "papel": "transicion_suave"})
check("vetar un efecto", r.status_code == 200 and r.json()["ok"] is True
      and len(r.json()["vetados"]) == 1, str(r.text)[:120])

r = post(f"/api/proyectos/{pid}/sonido/vetados",
         {"quitar": True, "efecto": {"fuente": "freesound", "id": "777"}})
check("desvetar el efecto", r.status_code == 200 and r.json()["ok"] is True
      and r.json()["vetados"] == [])

r = get(f"/api/proyectos/{pid}/sonido")
check("GET sonido refleja los vetados vacíos", r.json()["vetados"] == [])

# ------------------------------------------------------------- banco (oír)

r = get("/api/proyectos/efectos-banco/nada.mp3")
check("efecto del banco inexistente - 404", r.status_code == 404)

r = get("/api/proyectos/efectos-banco/..%2Fclaves.json")
check("efectos-banco no se sale del banco - 404", r.status_code == 404)

# ------------------------------------------------------------- transiciones

r = get(f"/api/proyectos/{pid}/transiciones")
ficha = r.json()
check("GET transiciones: catálogo de 15, 6 de fábrica",
      r.status_code == 200
      and len(ficha["transiciones"]) == 15
      and len(ficha["por_defecto"]) == 6
      and ficha["todas_de_fabrica"] is True)
check("GET transiciones: cada carta con su xfade",
      all(t.get("xfade") for t in ficha["transiciones"]))
check("GET transiciones: acento derivado (3 colores) y reparto vacío sin voz",
      len(ficha["acento"]["acento"]) == 3
      and ficha["reparto"] == []
      and ficha["duracion"] == 0.4)

r = put(f"/api/proyectos/{pid}/transiciones",
        {"transiciones": ["fundido", "glitch", "ese-no-existe"],
         "duracion": 9.0})
ficha = r.json()
check("PUT transiciones filtra y encasilla la duración",
      r.status_code == 200
      and ficha["duracion"] == 1.5
      and ficha["todas_de_fabrica"] is False
      and {t["id"] for t in ficha["transiciones"] if t["puesta"]}
      == {"fundido", "glitch"})

r = get(f"/api/proyectos/{pid}/transiciones")
check("transiciones persistidas",
      r.json()["duracion"] == 1.5 and not r.json()["todas_de_fabrica"])

r = put(f"/api/proyectos/{pid}/transiciones", {"transiciones": []})
check("PUT transiciones vacío = las de fábrica",
      r.json()["todas_de_fabrica"] is True)

r = put(f"/api/proyectos/{pid}/transiciones", {"transiciones": "no"})
check("PUT transiciones rechaza cuerpo raro - 400", r.status_code == 400)

# -------------------------------------------------------------------- repaso

r = get(f"/api/proyectos/{pid}/repaso")
cat = r.json()["catalogo"]
cat = cat.get("ambitos", cat) if isinstance(cat, dict) else {}
check("repaso: los ámbitos nuevos de sonido están en el catálogo",
      {"transicion", "musica", "efectos"} <= set(cat),
      str(sorted(cat))[:120])

# ------------------------------------------------------------------- resumen

print()
if fallos:
    print(f"{len(fallos)} FALLO(S): " + ", ".join(fallos))
    sys.exit(1)
print("fase G en verde")
