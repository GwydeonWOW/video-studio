"""Prueba de humo de la Fase L: imágenes de referencia para el estilo.

El kit visual del canal: subida al buzón (base64 en JSON, como las
capturas), servido con el candado de siempre, siembra en el taller al
crear, la guía que nace del material, el rehacer del estilo con material
nuevo y el arreglo del salto de tareas (retomar). Sin claves de pago:
los trabajos del taller fallan limpio, pero TODO lo que decide la fuente
pasa antes de llamar a nada. Ejecutar:

    python pruebas/humo_fasel.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_fasel_")
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


def post(ruta: str, cuerpo: dict | None = None):
    return cliente.post(ruta, json=cuerpo or {})


def esperar_trabajo(tid: str, tope_s: float = 30.0) -> dict:
    limite = time.time() + tope_s
    while time.time() < limite:
        ficha = cliente.get(f"/api/trabajos/{tid}").json()
        if ficha.get("estado") in ("hecho", "fallo", "cancelado"):
            return ficha
        time.sleep(0.1)
    return {"estado": "timeout"}


# una imagen PNG de verdad (1x1) para que el servido y la lectura digan png
PNG_1X1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
           "nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# --------------------------------------------------------------- la ficha

r = cliente.get("/api/presets-light").json()
check("ficha enseña el tope de imágenes", r.get("max_imagenes_estilo") == 24,
      str(r.get("max_imagenes_estilo")))

# ------------------------------------------------- subir al buzón (base64)

entradas = [
    {"nombre": "kit01.png", "datos": f"data:image/png;base64,{PNG_1X1}"},
    {"nombre": "kit02.PNG", "datos": PNG_1X1},          # sin data-URL
    {"nombre": "malo.txt", "datos": base64.b64encode(b"hola").decode()},
]
r = post("/api/presets-light/imagenes", {"imagenes": entradas})
respuesta = r.json()
check("subir acepta 2 y avisa del .txt", r.status_code == 200
      and len(respuesta["imagenes"]) == 2
      and len(respuesta["avisos"]) == 1
      and respuesta["tope"] == 24, str(r.text)[:200])
check("nombre de servidor: uuid corto con extensión",
      all(len(i["nombre"]) == 16 and i["nombre"].endswith(".png")
          and i["bytes"] > 0 and i["origen"] for i in respuesta["imagenes"]))
n1 = respuesta["imagenes"][0]["nombre"]
n2 = respuesta["imagenes"][1]["nombre"]

r = post("/api/presets-light/imagenes", {"imagenes": [
    {"nombre": "gigante.png",
     "datos": base64.b64encode(b"\x89PNG" + b"0" * (10 * 1024 * 1024 + 11)
                               ).decode()}]})
check("más de 10 MB se queda en avisos", r.status_code == 200
      and r.json()["imagenes"] == [] and "MB" in r.json()["avisos"][0])

# ------------------------------------------------------- servir del buzón

r = cliente.get(f"/api/presets-light/imagenes/{n1}")
check("GET imagen del buzón", r.status_code == 200
      and r.headers.get("content-type") == "image/png")
r = cliente.get("/api/presets-light/imagenes/no-existe.png")
check("GET imagen desconocida: 404", r.status_code == 404)
r = cliente.get("/api/presets-light/imagenes/..%2f..%2fproyecto.json")
check("escape del buzón: 404", r.status_code == 404)

r = cliente.delete(f"/api/presets-light/imagenes/{n2}")
check("DELETE quita del buzón", r.status_code == 200
      and r.json()["borrada"] == n2)
check("lo borrado ya no se sirve",
      cliente.get(f"/api/presets-light/imagenes/{n2}").status_code == 404)

# -------------------------------------------------------- validación nueva

BASE = {"nombre": "Canal Kit", "tono_prompt": "seco y periodistico",
        "voz_prompt": "grave, pausada", "idioma": "es", "ritmo": "medio"}

r = post("/api/presets-light", {"encargo": {**BASE, "estilo_prompt": ""}})
check("crear sin estilo ni imágenes: 400 que pide material",
      r.status_code == 400 and "adjunta" in r.json().get("error", ""),
      str(r.text)[:160])

r = post("/api/presets-light", {"encargo": {**BASE, "estilo_prompt": "corto",
                                            "estilo_imagenes": [n1]}})
check("prompt corto CON imágenes: 400 (opcional pero no dos palabras)",
      r.status_code == 400 and "opcional" in r.json().get("error", ""))

r = post("/api/presets-light", {"encargo": {**BASE, "estilo_imagenes":
                                            [n1] * 25}})
check("tope de imágenes: 400", r.status_code == 400
      and "tope" in r.json().get("error", ""))

# subo otra (la borré arriba) y el plan sigue saliendo con imágenes
post("/api/presets-light/imagenes", {"imagenes": [
    {"nombre": "kit02.png", "datos": PNG_1X1}]})
r = cliente.get("/api/presets-light/imagenes").json()  # no existe: solo nombres

# recuperar los nombres vivos del buzón
from app.config import AJUSTES  # noqa: E402
buzon = AJUSTES.carpeta_proyectos / "_imagenes_aportadas"
vivas = sorted(p.name for p in buzon.iterdir() if p.is_file())
check("en el buzón quedan 2 vivas", len(vivas) == 2, str(vivas))
b1, b2 = vivas

r = post("/api/presets-light/plan", {"encargo": {
    **BASE, "estilo_prompt": "", "estilo_imagenes": [b1, b2]}})
check("plan con imágenes y sin texto: sale entero",
      r.status_code == 200 and len(r.json()["tareas"]) == 6, str(r.text)[:160])

# ------------------------------------------- crear: siembra ANTES de pagar

r = post("/api/presets-light", {"encargo": {
    **BASE, "estilo_prompt": "", "estilo_imagenes": [b1, b2]}})
check("crear con imágenes: 202", r.status_code == 202, str(r.text)[:160])
tid = r.json()["trabajo"]["id"] if "trabajo" in r.json() \
    else r.json()["id"]

# el taller es el proyecto oculto nuevo con taller: true
proyectos_dir = AJUSTES.carpeta_proyectos
talleres = [p for p in proyectos_dir.iterdir()
            if (p / "proyecto.json").is_file()
            and json.loads((p / "proyecto.json").read_text(
                encoding="utf-8")).get("taller")]
check("el taller existe y está oculto (_ o flag)", len(talleres) == 1)
taller_dir = talleres[0]
sembradas = sorted(x.name for x in (taller_dir / "estilo" / "aportadas")
                   .iterdir()) if (taller_dir / "estilo" / "aportadas"
                                   ).is_dir() else []
check("siembra renombrando en orden", sembradas
      == [f"01_{b1}", f"02_{b2}"], str(sembradas))
check("el buzón queda vacío tras sembrar",
      list(buzon.iterdir()) == [], str(list(buzon.iterdir())))

ficha = esperar_trabajo(tid)
check("sin claves el taller falla limpio (no catastrófico)",
      ficha["estado"] == "fallo", str(ficha.get("error", ""))[:120])

# ------------------------------ congelado a mano + rehacer con material nuevo

r = post("/api/presets-canal", {
    "tipo": "canal", "nombre": "Canal Kit",
    "datos": {"guion": {"tono": "tono de taller", "idioma": "es"},
              "voz": {"voz": "una-voz", "modelo": "multilingual",
                      "estabilidad": 0.4, "similitud": 0.75,
                      "velocidad": 1.0},
              "estilo": {"estilo": "el que sale del kit"},
              "origen": {"estilo_prompt": "",
                         "estilo_imagenes": sembradas,
                         "tono_prompt": BASE["tono_prompt"],
                         "voz_prompt": BASE["voz_prompt"],
                         "idioma": "es", "ritmo": "medio",
                         "taller": taller_dir.name}}})
check("preset canal con material en el origen: 201", r.status_code == 201,
      str(r.text)[:160])
prid = r.json()["id"]

r = cliente.get(f"/api/presets-light/{prid}")
ficha = r.json()
check("la ficha enseña las sembradas y el tope",
      ficha["estilo_imagenes"] == sembradas
      and ficha["max_imagenes_estilo"] == 24, str(ficha.get("estilo_imagenes")))

r = cliente.get(f"/api/presets-light/{prid}/aportadas/{sembradas[0]}")
check("GET aportada del taller", r.status_code == 200
      and r.headers.get("content-type") == "image/png")
r = cliente.get(f"/api/presets-light/{prid}/aportadas/..%2fproyecto.json")
check("escape del taller: 404", r.status_code == 404)

r = post(f"/api/presets-light/{prid}/regenerar",
         {"parte": "voz", "feedback": "otra", "origen": {"estilo_prompt": "x"}})
check("regenerar voz con origen: 400", r.status_code == 400)

# material nuevo: una imagen fresca al buzón
r = post("/api/presets-light/imagenes", {"imagenes": [
    {"nombre": "nuevo.png", "datos": PNG_1X1}]})
nueva = r.json()["imagenes"][0]["nombre"]
r = post(f"/api/presets-light/{prid}/regenerar",
         {"parte": "estilo", "feedback": "",
          "origen": {"estilo_prompt": "", "estilo_imagenes": [nueva]}})
check("regenerar estilo con material nuevo: 202 + material",
      r.status_code == 202 and r.json().get("material") is True, str(r.text)[:160])
sembradas_2 = sorted(x.name for x in (taller_dir / "estilo" / "aportadas")
                     .iterdir())
check("el kit sembrado se REEMPLAZA entero", sembradas_2 == [f"01_{nueva}"],
      str(sembradas_2))
check("bitácora del taller anota el rehacer", any(
    json.loads(linea).get("evento") == "preset_light_regenerar"
    for linea in (taller_dir / "bitacora.jsonl").read_text(
        encoding="utf-8").splitlines() if linea.strip()))

# fuente nueva solo escrita: el material deja de ser la fuente
r = post(f"/api/presets-light/{prid}/regenerar",
         {"parte": "estilo", "feedback": "",
          "origen": {"estilo_prompt": "documental nordico azul de archivo"}})
check("regenerar estilo solo texto: 202", r.status_code == 202)
check("las sembradas se retiran al cambiar la fuente a texto",
      not (taller_dir / "estilo" / "aportadas").exists())
encargo_taller = json.loads((taller_dir / "proyecto.json").read_text(
    encoding="utf-8"))["encargo"]
check("el encargo del taller queda coherente",
      encargo_taller["estilo_prompt"] == "documental nordico azul de archivo"
      and "estilo_imagenes" not in encargo_taller, str(encargo_taller)[:120])

# -------------------------------------- rehacer NO salta lo ya hecho (fix)

from app.api import rutas_presets as rp  # noqa: E402
from app.nucleo.estado import Estado  # noqa: E402
from app.pasos import presets_light  # noqa: E402

encargo_prueba = presets_light.validar_encargo({
    **BASE, "estilo_prompt": "acuarela suave de archivo"})
taller_prueba = rp._crear_taller(encargo_prueba)
tarea_tono = next(t for t in presets_light.TAREAS if t["id"] == "tono")


class TrabajoFalso:
    def avance(self, _mensaje):
        pass

    def comprobar_cancelacion(self):
        pass


llamadas = []
real = rp._TAREAS["tono"]


def tono_falso(_t, estado, _e, _tr):
    llamadas.append(1)
    estado.actualizar_params("brief", {"tono": "tono falso"})


rp._TAREAS["tono"] = tono_falso
try:
    rp._correr_tanda(taller_prueba, Estado(taller_prueba), encargo_prueba,
                     [tarea_tono], TrabajoFalso())
    rp._correr_tanda(taller_prueba, Estado(taller_prueba), encargo_prueba,
                     [tarea_tono], TrabajoFalso())
    check("rehacer VUELVE a correr la tarea (fallo del porte arreglado)",
          len(llamadas) == 2, str(len(llamadas)))
    rp._correr_tanda(taller_prueba, Estado(taller_prueba), encargo_prueba,
                     [tarea_tono], TrabajoFalso(), retomar=True)
    check("solo retomar salta lo ya hecho", len(llamadas) == 2, str(len(llamadas)))
finally:
    rp._TAREAS["tono"] = real

# --------------------------------------------- multimodal en la capa LLM

from app.motores import llm  # noqa: E402

png_temp = Path(tempfile.mkstemp(suffix=".png")[1])
png_temp.write_bytes(base64.b64decode(PNG_1X1))
llamada = llm.Llamada(proveedor="glm", modelo="glm-5.3", instruccion="hola",
                      imagenes=[str(png_temp)])
llm._resolver_vision(llamada)
check("glm con imágenes cambia al modelo con visión",
      llamada.modelo == "glm-5.3v", llamada.modelo)
llamada = llm.Llamada(proveedor="openai", modelo="gpt-6-sol",
                      instruccion="hola", imagenes=[str(png_temp)])
llm._resolver_vision(llamada)
check("openai no declara visión: se queda con el suyo",
      llamada.modelo == "gpt-6-sol", llamada.modelo)
bloques = llm._contenido_user(llamada, "openai")
check("bloques openai: texto + image_url con data-URL",
      bloques[0]["type"] == "text"
      and bloques[1]["image_url"]["url"].startswith("data:image/png;base64,"))
check("bloques anthropic: base64 con media_type",
      llm._contenido_user(llamada, "anthropic")[1]["source"]["media_type"]
      == "image/png")
check("bloques codex: input_image",
      llm._contenido_user(llamada, "codex")[1]["type"] == "input_image")
check("sin imágenes el contenido es texto plano",
      llm._contenido_user(llm.Llamada(proveedor="glm", modelo="glm-5.3",
                                       instruccion="hola"), "openai") == "hola")

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("fase L en verde")
