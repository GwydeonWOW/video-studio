"""Prueba de humo de la API completa, sin tocar servicios de pago.

Cubre: instalación/login, proyectos, params, ejecución del paso gratis
(ingesta), versiones + revertir, servicio de archivos con Range, control
de sesión y de Origin. Ejecutar:

    python pruebas/humo_api.py

Sale 0 si todo verde; imprime cada chequeo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# datos aislados ANTES de importar la app (AJUSTES se congela al arrancar)
_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_humo_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" — {detalle}" if detalle and not condicion else ""))
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


TEXTO = ("La historia del transistor comienza en 1947 en los Bell Labs, "
         "cuando Bardeen, Brattain y Shockley construyeron el primero "
         "con punteras de oro sobre germanio. " * 3)

# ---------------------------------------------------------------- instalación
r = cliente.get("/api/auth/estado").json()
check("estado inicial: pide instalación", r["instalacion"] is True)

r = cliente.post("/api/auth/instalar", json={"contrasena": "corta"})
check("instalar rechaza contraseña corta", r.status_code == 400)

r = cliente.post("/api/auth/instalar",
                 json={"contrasena": "una-clave-de-prueba-42"})
check("instalar fija la contraseña", r.status_code == 200
      and cliente.cookies.get("estudio_sesion"))

r = cliente.get("/api/auth/estado").json()
check("estado tras instalar: autenticado", r["autenticado"] is True)

# ------------------------------------------------------------------ proyectos
r = cliente.get("/api/proyectos")
check("listar proyectos vacío", r.status_code == 200 and r.json() == [])

r = cliente.post("/api/proyectos", json={"nombre": "Prueba Áudio y Vídeo"})
check("crear proyecto", r.status_code == 201, r.text)
pid = r.json()["id"]
check("slug sin acentos", pid == "prueba-audio-y-video", pid)

pasos = cliente.get(f"/api/proyectos/{pid}/pasos").json()
check("8 pasos en el grafo", len(pasos["pasos"]) == 8)
check("params sembrados al crear",
      pasos["pasos"]["ingesta"]["params"].get("texto") == "")
check("estado inicial vacío",
      pasos["pasos"]["ingesta"]["estado"] == "vacio")

r = cliente.post("/api/proyectos", json={"nombre": "x"})
check("segundo proyecto no pisa el id", r.status_code == 201
      and r.json()["id"] != pid)

# --------------------------------------------------------------------- params
r = cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
                json={"texto": TEXTO, "titulo": "El transistor"})
# nada ha corrido aun: no hay material aguas abajo que quede obsoleto
check("guardar params", r.status_code == 200
      and r.json()["obsoletos_al_regenerar"] == [], r.text)

r = cliente.put(f"/api/proyectos/{pid}/pasos/paso_inventado/params",
                json={"a": 1})
check("params de paso desconocido -> 404", r.status_code == 404)

# ------------------------------------------------------------------- ejecutar
r = cliente.post(f"/api/proyectos/{pid}/pasos/ingesta/ejecutar", json={})
check("lanzar ingesta (202 + trabajo)", r.status_code == 202, r.text)
tid = r.json()["id"]
ficha = esperar_trabajo(tid)
check("ingesta termina bien", ficha["estado"] == "hecho",
      str(ficha.get("error", ""))[:200])

ficha = cliente.get(f"/api/proyectos/{pid}/pasos/ingesta").json()
check("datos de ingesta escritos", ficha["datos"]["palabras"] > 50)
check("ingesta queda ok y v1", ficha["estado"] == "ok"
      and ficha["version"] == 1)

# versiones y revertir
cliente.post(f"/api/proyectos/{pid}/pasos/ingesta/ejecutar", json={})
ficha = esperar_trabajo(cliente.get(f"/api/trabajos").json()[-1]["id"])
check("segunda pasada -> v2", cliente.get(
    f"/api/proyectos/{pid}/pasos/ingesta").json()["version"] == 2)
versiones = cliente.get(f"/api/proyectos/{pid}/pasos/ingesta/versiones").json()
check("historial de versiones", len(versiones) == 2, str(versiones)[:200])

r = cliente.post(f"/api/proyectos/{pid}/pasos/ingesta/revertir",
                 json={"version": 1})
check("revertir a v1", r.status_code == 200
      and r.json()["version"] == 1, r.text)

# cambiar params de un paso YA corrido lo deja obsoleto (firma distinta)
r = cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
                json={"texto": TEXTO, "titulo": "Otro título"})
check("params nuevos -> paso obsoleto", r.status_code == 200
      and r.json()["estado"] == "obsoleto", r.text)

# ------------------------------------------------- puerta guion -> voz
r = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", json={})
check("voz sin guion aprobado -> 409", r.status_code == 409, r.text)

r = cliente.post(f"/api/proyectos/{pid}/pasos/guion/aprobar")
check("aprobar guion vacio -> 400", r.status_code == 400, r.text)

r = cliente.post(f"/api/proyectos/{pid}/pasos/brief/aprobar")
check("aprobar paso no aprobable -> 400", r.status_code == 400, r.text)

r = cliente.get(f"/api/proyectos/{pid}/pasos").json()
check("resumen expone 'aprobado' en falso",
      r["pasos"]["guion"]["aprobado"] is False)

# ciclo del acta a nivel de estado (sin LLM): aprobar -> version nueva o
# reversion la revocan; la voz vuelve a quedar cerrada
from app.config import AJUSTES  # noqa: E402
from app.nucleo.estado import Estado  # noqa: E402
from app.nucleo.proyecto import Proyecto  # noqa: E402

pr = Proyecto(AJUSTES.carpeta_proyectos / pid)
est = Estado(pr)
ESCENA = {"id": "S001", "titulo": "t", "narracion": "hola",
          "visual": "v", "texto_pantalla": "p", "duracion_estimada": 2}
est.completar("guion", {"escenas": 8}, {"escenas": [ESCENA]})
check("aprobar deja acta v1", est.aprobar("guion")["version"] == 1
      and est.esta_aprobado("guion"))
est.completar("guion", {"escenas": 8}, {"escenas": [dict(ESCENA, narracion="hola 2")]})
check("version nueva revoca el acta", not est.esta_aprobado("guion"))
est.aprobar("guion")
est.revertir("guion", 1)
check("revertir revoca el acta", not est.esta_aprobado("guion"))
r = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", json={})
check("voz sigue cerrada tras revocar -> 409", r.status_code == 409, r.text)

# y el camino positivo: aprobar por la API abre la puerta (el trabajo
# fallará luego por falta de clave de ElevenLabs, pero ya sin gastar)
r = cliente.post(f"/api/proyectos/{pid}/pasos/guion/aprobar")
check("aprobar por la API -> acta", r.status_code == 200
      and r.json()["aprobado"] is True and r.json()["version"] == 1, r.text)
r = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", json={})
check("voz con guion aprobado -> 202", r.status_code == 202, r.text)
ficha = esperar_trabajo(r.json()["id"])
check("trabajo de voz sin clave -> fallo limpio", ficha["estado"] == "fallo"
      and "ElevenLabs" in str(ficha.get("error", "")), str(ficha)[:200])

# ------------------------------------------------------------------- archivos
r = cliente.get(f"/a/{pid}/proyecto.json")
check("servir archivo del proyecto", r.status_code == 200
      and r.json()["id"] == pid)

r = cliente.get(f"/a/{pid}/pasos/ingesta/datos.json", headers={"Range": "bytes=0-49"})
check("Range parcial -> 206", r.status_code == 206 and len(r.content) == 50,
      f"{r.status_code} {len(r.content)}")

r = cliente.get(f"/a/{pid}/pasos/ingesta/datos.json",
                headers={"Range": "bytes=999999-"})
check("Range imposible -> 416", r.status_code == 416)

r = cliente.get(f"/a/{pid}/..%2f..%2f..%2fdatos%2fcredenciales.json")
check("escape de directorio -> 404", r.status_code == 404)

r = cliente.get(f"/a/{pid}/../credenciales.json")
check("ruta relativa cruda -> 404", r.status_code == 404)

# ----------------------------------------------------------- seguridad HTTP
ajena = TestClient(app)          # sin cookie
r = ajena.get("/api/proyectos")
check("sin sesión -> 401", r.status_code == 401)

r = cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
                json={"texto": "x"}, headers={"Origin": "https://malo.example"})
check("Origin ajeno en mutación -> 403", r.status_code == 403)

r = cliente.post("/api/auth/login", json={"contrasena": "no-es-la-clave"})
check("login con contraseña mala -> 401", r.status_code == 401)

r = cliente.post("/api/auth/logout")
check("logout", r.status_code == 200)
r = cliente.get("/api/proyectos")
check("tras logout -> 401", r.status_code == 401)

# ------------------------------------------------------------------ bitácora
cliente.post("/api/auth/login", json={"contrasena": "una-clave-de-prueba-42"})
eventos = cliente.get(f"/api/proyectos/{pid}/bitacora").json()
check("bitácora registra el ciclo", any(e["evento"] == "paso_completado"
                                        for e in eventos), str(eventos)[:200])

print()
if fallos:
    print(f"{len(fallos)} FALLOS: {', '.join(fallos)}")
    sys.exit(1)
print("TODO VERDE")
