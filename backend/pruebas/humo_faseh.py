"""Prueba de humo de las rutas de la Fase H, sin tocar servicios de pago.

Presets de locución, presets de canal (CRUD, papelera, aplicar) y el modo
light (ficha, plan y errores honrados). La generación completa del taller
necesita claves de pago y no se prueba aquí. Ejecutar:

    python pruebas/humo_faseh.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_faseh_")
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


def post(ruta: str, cuerpo: dict | None = None):
    return cliente.post(ruta, json=cuerpo or {})


def delete(ruta: str):
    return cliente.delete(ruta)


# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# ------------------------------------------------------- tonos de locución

r = get("/api/presets")
tonos = r.json()
check("GET presets: 8 tonos", r.status_code == 200 and len(tonos) == 8,
      str(r.text)[:120])
check("GET presets: ids y nombres",
      all(t.get("id") and t.get("nombre") and t.get("voces_nombres")
          for t in tonos))
check("GET presets: documental_sobrio primero",
      any(t["id"] == "documental_sobrio" for t in tonos))

r = get("/api/presets/documental_sobrio")
ficha = r.json()
check("GET preset voz: mandos", r.status_code == 200
      and ficha["estabilidad"] == 0.65 and ficha["velocidad"] == 0.9
      and 0.7 <= ficha["velocidad"] <= 1.2)

r = get("/api/presets/ese-no-existe")
check("GET preset voz desconocido: 400 honrado",
      r.status_code == 400 and "desconocido" in r.json().get("error", ""))

# ------------------------------------------------------------ presets canal

r = get("/api/presets-canal")
ficha = r.json()
check("GET presets-canal vacío", r.status_code == 200
      and ficha["total"] == 0 and ficha["papelera"] == []
      and len(ficha["tipos"]) == 5
      and set(ficha["presets"]) == {"guion", "estilo", "rotulos", "voz",
                                    "canal"})

r = post("/api/presets-canal", {"tipo": "guion", "nombre": "Sobrio",
                                "datos": {"tono": "tono serio de prueba",
                                          "idioma": "es",
                                          "ritmo_min": 8, "ritmo_max": 12}})
check("POST preset guion: 201", r.status_code == 201, str(r.text)[:120])
prid = r.json()["id"]

r = post("/api/presets-canal", {"tipo": "guion", "nombre": "Roto",
                                "datos": {"guion": "clave que no existe"}})
check("POST preset clave inválida: 400 que dice lo que guarda",
      r.status_code == 400 and "no sabe guardar" in r.json().get("error", ""))

r = post("/api/presets-canal", {"tipo": "flan", "nombre": "X", "datos": {}})
check("POST preset tipo inválido: 400", r.status_code == 400)

# el estilo: su guardado siembra ficheros y la miniatura de la ficha
# tiene que salir como NOMBRE, no como una Path (eso reventaba el JSON)
r = post("/api/presets-canal", {"tipo": "estilo", "nombre": "Cálido",
                                "datos": {"estilo": "cálido, orgánico, "
                                                    "luz de tarde"}})
check("POST preset estilo: 201 con miniatura serializable",
      r.status_code == 201
      and isinstance(r.json().get("miniatura"), str),
      str(r.text)[:160])
estilo_id = r.json()["id"]

r = get(f"/api/presets-canal/{estilo_id}")
check("GET preset estilo releeído", r.status_code == 200
      and r.json()["tipo"] == "estilo"
      and isinstance(r.json().get("miniatura"), str))

r = post("/api/presets-canal", {"tipo": "estilo", "nombre": "Flaco",
                                "datos": {}})
check("POST preset estilo sin material: 400 honrado",
      r.status_code == 400 and "estilo" in r.json().get("error", ""))

# fuera del recuento: el resto de la prueba asume la tabla vacía
delete(f"/api/presets-canal/{estilo_id}")
delete(f"/api/presets-canal/{estilo_id}/papelera?confirmar=true")

r = get(f"/api/presets-canal/{prid}")
check("GET preset por id", r.status_code == 200
      and r.json()["nombre"] == "Sobrio"
      and r.json()["datos"]["ritmo_min"] == 8)

r = put(f"/api/presets-canal/{prid}", {"nombre": "Sobrio 2",
                                       "nota": "prueba"})
check("PUT renombrar", r.status_code == 200
      and r.json()["nombre"] == "Sobrio 2")

r = get(f"/api/presets-canal/{prid}/miniatura")
check("GET miniatura sin cara: 404", r.status_code == 404)

r = get(f"/api/presets-canal/{prid}/fichero/..%2Fproyecto.json")
check("GET fichero con ..: 404", r.status_code in (404, 400))

# aplicar a un proyecto
r = post("/api/proyectos", {"nombre": "Fase H", "canal": "pruebas"})
pid = r.json()["id"]
r = post(f"/api/presets-canal/{prid}/aplicar", {"proyecto": pid})
respuesta = r.json()
check("POST aplicar: escribe params", r.status_code == 200
      and "brief" in respuesta["cambios"]
      and respuesta["cambios"]["brief"]["tono"] == "tono serio de prueba",
      str(r.text)[:160])

r = post(f"/api/presets-canal/{prid}/aplicar", {"proyecto": "ese-no"})
check("POST aplicar proyecto desconocido: 404", r.status_code == 404)

r = get(f"/api/proyectos/{pid}/pasos")
check("aplicar se ve en el paso",
      r.status_code == 200
      and r.json()["pasos"]["brief"]["params"]["tono"]
      == "tono serio de prueba",
      str(r.text)[:160])

# papelera propia
r = delete(f"/api/presets-canal/{prid}")
check("DELETE apartar", r.status_code == 200 and "apartado" in r.json())

r = get(f"/api/presets-canal/{prid}/peso")
check("GET peso del apartado", r.status_code == 200
      and r.json().get("nombre") == "Sobrio 2")

r = delete(f"/api/presets-canal/{prid}/papelera")
check("borrar sin confirmar: 400", r.status_code == 400)

r = post(f"/api/presets-canal/{prid}/restaurar")
check("POST restaurar", r.status_code == 201)

r = delete(f"/api/presets-canal/{prid}")
r = delete(f"/api/presets-canal/{prid}/papelera?confirmar=true")
check("borrar confirmando", r.status_code == 200
      and get("/api/presets-canal").json()["total"] == 0)

# ---------------------------------------------------------------- modo light

r = get("/api/presets-light")
ficha = r.json()
check("GET presets-light", r.status_code == 200
      and len(ficha["ritmos"]) == 5
      and ficha["ritmo_defecto"] == "medio"
      and ficha["plan"]["tareas"]
      and ficha["hay_glm"] is False
      and ficha["hay_elevenlabs"] is False)

encargo = {"nombre": "Canal de Prueba",
           "estilo_prompt": "documental sobrio de archivo en azul",
           "tono_prompt": "seco y periodistico, sin adjetivos",
           "voz_prompt": "grave, pausada, sin dramatismo",
           "idioma": "es", "ritmo": "medio"}
r = post("/api/presets-light/plan", {"encargo": encargo})
plan = r.json()
check("POST plan: 6 tareas en 3 tandas", r.status_code == 200
      and len(plan["tareas"]) == 6
      and [len(t) for t in plan["tandas"]] == [3, 2, 1]
      and plan["segundos"] > 0 and plan["imagenes"] > 0,
      str(r.text)[:160])

r = post("/api/presets-light", {"encargo": {**encargo,
                                            "estilo_prompt": "corto"}})
check("POST crear encargo corto: 400 honrado",
      r.status_code == 400 and "estilo" in r.json().get("error", ""),
      str(r.text)[:160])

r = post("/api/presets-light", {"encargo": {**encargo, "idioma": "fr"}})
check("POST crear idioma raro: 400", r.status_code == 400
      and "idioma" in r.json().get("error", ""))

# ---------------------------------------------- un preset canal en la galería

r = post("/api/presets-canal", {
    "tipo": "canal", "nombre": "Canal Congelado",
    "datos": {"guion": {"tono": "tono de taller", "idioma": "es"},
              "voz": {"voz": "una-voz", "modelo": "multilingual",
                      "estabilidad": 0.4, "similitud": 0.75,
                      "velocidad": 1.0},
              "estilo": {"estilo": "minimalista suizo, tipografía grande"},
              "origen": {"estilo_prompt": encargo["estilo_prompt"],
                         "tono_prompt": encargo["tono_prompt"],
                         "voz_prompt": encargo["voz_prompt"],
                         "idioma": "es", "ritmo": "medio"}}})
check("POST preset canal: 201", r.status_code == 201, str(r.text)[:160])
canal_id = r.json()["id"]

r = get(f"/api/presets-canal/{canal_id}")
vinetas = r.json().get("vinetas") or []
check("vinetas: pares {icono, texto}",
      bool(vinetas)
      and all(set(v) == {"icono", "texto"}
              and all(isinstance(x, str) for x in v.values())
              for v in vinetas)
      and any(v["icono"] == "🌐" for v in vinetas)
      and any(v["icono"] == "🎨" for v in vinetas))

r = get("/api/presets-light")
check("canal en la galería light",
      any(p["id"] == canal_id
          for p in r.json()["presets"]))

r = get(f"/api/presets-light/{canal_id}")
ficha = r.json()
check("GET ficha light: encargo y taller muerto",
      r.status_code == 200
      and ficha["encargo"]["estilo_prompt"] == encargo["estilo_prompt"]
      and ficha["taller"] == "" and ficha["activo"] is None)

r = post(f"/api/presets-light/{canal_id}/regenerar",
         {"parte": "estilo", "feedback": "mas claro"})
check("regenerar sin taller: 404 que propone duplicar",
      r.status_code == 404 and "duplica" in r.json().get("error", ""))

r = post(f"/api/presets-light/{canal_id}/regenerar", {"parte": "nada"})
check("regenerar parte rara: 400", r.status_code == 400)

# ------------------------------------------------ taller oculto de la lista

r = post("/api/proyectos", {"nombre": "Visible", "canal": "pruebas"})
pid_v = r.json()["id"]
raiz_v = Path(_dir_datos) / "datos" / "proyectos" / pid_v
datos_p = json.loads((raiz_v / "proyecto.json").read_text(encoding="utf-8"))
datos_p["taller"] = True
(raiz_v / "proyecto.json").write_text(json.dumps(datos_p), encoding="utf-8")

ids = [p["id"] for p in get("/api/proyectos").json()]
check("el taller no sale en la lista de proyectos",
      pid_v not in ids and pid in ids)

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("fase H en verde")
