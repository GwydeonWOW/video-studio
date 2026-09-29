"""Prueba de humo del kit visual del canal (pantalla Estilo).

El kit CANÓNICO (no el buzón del modo light): subir a /api/estilo/imagenes
persiste en datos/_kit_canal y en estilo.json, se sirve con candado, se
quita, el tope se respeta, cada proyecto NUEVO lo hereda sembrado en
estilo/aportadas, reaplicar el estilo lo refresca y la guía se escribe
con las imágenes ADJUNTAS. Ejecutar:

    python pruebas/humo_kit.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_kit_")
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


def esperar_trabajo(tid: str, tope_s: float = 30.0) -> dict:
    limite = time.time() + tope_s
    while time.time() < limite:
        ficha = cliente.get(f"/api/trabajos/{tid}").json()
        if ficha.get("estado") in ("hecho", "fallo", "cancelado"):
            return ficha
        time.sleep(0.1)
    return {"estado": "timeout"}


PNG_1X1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
           "nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# -------------------------------------------------- subir al kit (persiste)

entradas = [
    {"nombre": "ref01.png", "datos": f"data:image/png;base64,{PNG_1X1}"},
    {"nombre": "ref02.png", "datos": PNG_1X1},  # sin data-URL
    {"nombre": "malo.txt", "datos": base64.b64encode(b"hola").decode()},
]
r = cliente.post("/api/estilo/imagenes", json={"imagenes": entradas})
cuerpo = r.json()
check("subir acepta 2 y avisa del .txt", r.status_code == 200
      and len(cuerpo["imagenes"]) == 2
      and len(cuerpo["avisos"]) == 1
      and cuerpo["tope"] == 24, str(r.text)[:200])
k1 = cuerpo["imagenes"][0]["nombre"]
k2 = cuerpo["imagenes"][1]["nombre"]

r = cliente.get("/api/estilo").json()
check("el kit persiste en el estilo del canal",
      r["kit"] == [k1, k2], str(r.get("kit")))

r = cliente.get("/api/estilo/imagenes").json()
check("listar el kit: en orden y con bytes",
      [i["nombre"] for i in r["imagenes"]] == [k1, k2]
      and all(i["bytes"] > 0 for i in r["imagenes"]))

# ------------------------------------------------------------ servir/quitar

r = cliente.get(f"/api/estilo/imagenes/{k1}")
check("GET imagen del kit", r.status_code == 200
      and r.headers.get("content-type") == "image/png")
check("imagen desconocida: 404",
      cliente.get("/api/estilo/imagenes/no-existe.png").status_code == 404)
check("escape del kit: 404",
      cliente.get("/api/estilo/imagenes/..%2f..%2festilo.json").status_code
      == 404)

r = cliente.delete(f"/api/estilo/imagenes/{k2}")
check("DELETE quita del kit", r.status_code == 200
      and r.json()["borrada"] == k2 and r.json()["kit"] == [k1])
check("lo borrado ya no se sirve",
      cliente.get(f"/api/estilo/imagenes/{k2}").status_code == 404)

# ------------------------------------------------- guardar el estilo (PUT)

r = cliente.put("/api/estilo", json={
    "nombre": "Canal Prueba", "tono": "seco", "estilo_grafico": "acuarela",
    "kit": [k1]})
check("PUT estilo define el canal y RESPETA el kit",
      r.status_code == 200 and r.json()["definido"] is True
      and r.json()["kit"] == [k1], str(r.text)[:160])

# ----------------------------------------------------------------- el tope

r = cliente.post("/api/estilo/imagenes", json={"imagenes": [
    {"nombre": f"mas{i:02d}.png", "datos": PNG_1X1} for i in range(23)]})
check("llenar hasta el tope de 24", r.status_code == 200
      and len(r.json()["imagenes"]) == 23
      and len(r.json()["kit"]) == 24, str(r.text)[:160])

r = cliente.post("/api/estilo/imagenes", json={"imagenes": [
    {"nombre": "una-de-mas.png", "datos": PNG_1X1}]})
check("sin hueco: 0 aceptadas y aviso del tope", r.status_code == 200
      and r.json()["imagenes"] == []
      and any("tope" in a for a in r.json()["avisos"]))

# dejamos el kit en 2 (la original + la primera de la tanda)
kit = cliente.get("/api/estilo").json()["kit"]
for sobra in kit[2:]:
    cliente.delete(f"/api/estilo/imagenes/{sobra}")
kit = cliente.get("/api/estilo").json()["kit"]
check("limpiando extras el kit queda en 2", len(kit) == 2, str(kit))
k1, k2 = kit

# ------------------------------------------- herencia: crear un proyecto

from app.config import AJUSTES  # noqa: E402

r = cliente.post("/api/proyectos", json={"nombre": "Video Kit"})
check("crear proyecto: 201", r.status_code == 201, str(r.text)[:160])
pid = r.json()["id"]
proyecto_dir = AJUSTES.carpeta_proyectos / pid
aportadas = sorted(x.name for x in (proyecto_dir / "estilo" / "aportadas")
                   .iterdir()) if (proyecto_dir / "estilo" / "aportadas"
                                   ).is_dir() else []
check("el kit se siembra renombrado en orden",
      aportadas == [f"01_{k1}", f"02_{k2}"], str(aportadas))
canal = sorted(x.name for x in (AJUSTES.datos / "_kit_canal").iterdir())
check("el kit del canal queda INTACTO tras sembrar",
      canal == sorted([k1, k2]), str(canal))

r = cliente.get(f"/a/{pid}/estilo/aportadas/01_{k1}")
check("la aportada se sirve al proyecto", r.status_code == 200
      and r.headers.get("content-type") == "image/png")

# ------------------------------------------- reaplicar refresca el kit

cliente.post("/api/estilo/imagenes", json={"imagenes": [
    {"nombre": "ref03.png", "datos": PNG_1X1}]})
k3 = cliente.get("/api/estilo").json()["kit"][2]

r = cliente.post(f"/api/proyectos/{pid}/aplicar-estilo")
check("reaplicar el estilo: 200", r.status_code == 200, str(r.text)[:160])
aportadas = sorted(x.name for x in (proyecto_dir / "estilo" / "aportadas")
                   .iterdir())
check("reaplicar REEMPLAZA el kit sembrado",
      aportadas == [f"01_{k1}", f"02_{k2}", f"03_{k3}"], str(aportadas))

# ------------------------------- la guía se escribe mirando las aportadas

from app.pasos import guia_estilo  # noqa: E402

capturadas: dict = {}
real = guia_estilo.proponer


def proponer_falso(_proyecto, _params, _trabajo, descripcion="",
                   imagenes=None, peticion=""):
    capturadas["descripcion"] = descripcion
    capturadas["imagenes"] = list(imagenes or [])
    capturadas["peticion"] = peticion
    return {"guia": "guia falsa", "paleta": ["#1a1a1a"]}


guia_estilo.proponer = proponer_falso
try:
    r = cliente.post(f"/api/proyectos/{pid}/guia/proponer",
                     json={"descripcion": "look del canal",
                           "peticion": "mas contraste"})
    check("proponer guía: 202", r.status_code == 202, str(r.text)[:160])
    ficha = esperar_trabajo(r.json()["id"])
    check("el trabajo de la guía termina hecho", ficha["estado"] == "hecho",
          str(ficha.get("error", ""))[:120])
    check("las aportadas viajan ADJUNTAS a la llamada",
          capturadas["imagenes"] == sorted(str(x) for x in
                                           (proyecto_dir / "estilo"
                                            / "aportadas").iterdir()),
          str(capturadas.get("imagenes")))
    check("descripcion y peticion llegan enteras",
          capturadas["descripcion"] == "look del canal"
          and capturadas["peticion"] == "mas contraste")
finally:
    guia_estilo.proponer = real

r = cliente.get(f"/api/proyectos/{pid}/guia").json()
check("GET guía enseña las aportadas", r["aportadas"] == aportadas,
      str(r.get("aportadas")))

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("kit del canal en verde")
