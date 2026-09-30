"""Prueba de humo de las llamadas a la acción (cta.py -> guion).

Tres casillas INDEPENDIENTES y APAGADAS por defecto; lo escrito es una
INDICACIÓN que el redactor redacta con las palabras de cada vídeo, y la
sección del prompt se construye ANTES de escribir para que la escena
anterior prepare la petición. Se comprueba todo SIN claves de pago (el
doble del modelo devuelve guiones de lata):

- normalizar: nada guardado -> tres apagadas; estricto tira de lo que
  no es objeto y del texto que no es una frase; blando recorta y sigue
- activos/describir: la línea de bitácora
- bloque_para_guion: sin puestos no hay sección; con texto viaja el
  pedido; sin texto, el patrón por omisión; dos llamadas -> aviso de
  que no se repitan
- params: el guion siembra la caja apagada; la API la valida (400 a lo
  malforme) y el prompt SOLO lleva la sección cuando hay algo puesto —
  un proyecto sin la caja (los de antes) sale exactamente igual

Ejecutar:

    python pruebas/humo_cta.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_cta_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.motores import llm  # noqa: E402
from app.pasos import cta, p3_guion  # noqa: E402

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


# ---------------------------------------------------------- el módulo puro

apagadas = cta.normalizar(None)
check("sin nada guardado, los tres momentos APAGADOS",
      list(apagadas) == list(cta.MOMENTOS)
      and all(not v["puesto"] and v["texto"] == "" for v in apagadas.values()),
      str(apagadas))

parcial = cta.normalizar({"cta_final": {"puesto": True,
                                        "texto": "que se  suscriba "}})
check("normalizar respeta lo que no viene y plancha el texto",
      parcial["cta_final"] == {"puesto": True, "texto": "que se suscriba"}
      and not parcial["presentacion"]["puesto"]
      and not parcial["cta_medio"]["puesto"],
      str(parcial))

check("normalizar devuelve copias independientes",
      apagadas["presentacion"] is not cta.POR_DEFECTO["presentacion"]
      and apagadas is not cta.POR_DEFECTO)

for nombre, crudo in [
    ("la caja entera que no es objeto", "suscribete"),
    ("un momento que no es objeto", {"cta_medio": "que comente"}),
]:
    try:
        cta.normalizar(crudo, estricto=True)
        check(f"estricto tira de: {nombre}", False)
    except ValueError:
        check(f"estricto tira de: {nombre}", True)

try:
    cta.normalizar({"presentacion": {"puesto": True, "texto": "x" * 601}},
                   estricto=True)
    check("estricto tira del texto que ya no es una frase", False)
except ValueError:
    check("estricto tira del texto que ya no es una frase", True)

blando = cta.normalizar({"cta_medio": 7, "presentacion":
                         {"puesto": True, "texto": "y" * 900}},
                        estricto=False)
check("blando no tira: recorta y tira lo que no entiende",
      blando["cta_medio"]["puesto"] is False
      and len(blando["presentacion"]["texto"]) == cta.MAX_TEXTO,
      str({k: (v["puesto"], len(v["texto"])) for k, v in blando.items()}))

ficha = {"presentacion": {"puesto": True, "texto": ""},
         "cta_medio": {"puesto": True, "texto": "que visite mi web"},
         "cta_final": {"puesto": True, "texto": "que se suscriba"}}
check("activos lista los momentos puestos",
      [m for m, _ in cta.activos(ficha)] == list(cta.MOMENTOS))
check("describir dice qué lleva el vídeo",
      cta.describir(ficha) == "la presentación, la llamada a la acción de "
                              "mitad, la llamada a la acción del cierre"
      and cta.describir(None) == "sin presentación ni llamadas a la acción",
      cta.describir(ficha))

check("sin puestos no hay sección de prompt",
      cta.bloque_para_guion(cta.normalizar(None)) == "")

seccion = cta.bloque_para_guion(ficha)
check("la sección lleva los sitios y los pedidos",
      "LA PRESENTACIÓN Y LAS LLAMADAS A LA ACCIÓN" in seccion
      and "PRIMERA ESCENA DESPUÉS DEL GANCHO" in seccion
      and "A MITAD DEL VÍDEO" in seccion
      and "ÚLTIMA ESCENA" in seccion
      and "que se suscriba" in seccion,
      seccion[:120])
check("la presentación sin texto viaja por omisión (no el patrón)",
      "PATRÓN" not in seccion and "quién eres" in seccion)
check("las llamadas con texto viajan tal cual",
      "que visite mi web" in seccion and "qué pide" in seccion.lower())
con_patron = cta.bloque_para_guion(
    {"presentacion": {"puesto": True, "texto": "que se sepa quién soy"}})
check("la presentación CON texto viaja como PATRÓN a adaptar",
      "PATRÓN" in con_patron and "«que se sepa quién soy»" in con_patron)
check("dos llamadas -> aviso de que no se repiten",
      "NO SE REPITEN" in seccion)
check("una llamada sola no lleva el aviso de repetición",
      "NO SE REPITEN" not in cta.bloque_para_guion(
          {"cta_final": {"puesto": True, "texto": "que comente"}}))

# --------------------------------------------------- el doble del modelo

registro_llamadas: list[dict] = []
respuestas_guion: list[dict] = []
_llamar_json_real = llm.llamar_json


def llamar_json_falso(llamada, claves=None, **_):
    registro_llamadas.append({
        "contexto": getattr(llamada, "contexto", ""),
        "instruccion": getattr(llamada, "instruccion", ""),
    })
    if getattr(llamada, "contexto", "") == "brief":
        return {"puntos": ["un punto", "otro punto"],
                "tono": "cercano", "formato": {"min": 20, "max": 40}}
    return respuestas_guion.pop(0)


llm.llamar_json = llamar_json_falso


def guion_lata(n_escenas: int, n_palabras: int) -> dict:
    return {"escenas": [
        {"id": f"S{i:03d}", "titulo": f"escena {i}",
         "narracion": " ".join(f"palabra{j}" for j in range(n_palabras)),
         "visual": "un plano", "texto_pantalla": "rotulo",
         "duracion_estimada": 10}
        for i in range(1, n_escenas + 1)]}


# ------------------------------------------------ proyecto hasta el guion

TEXTO = ("La historia del pinyin cuenta cómo se escribió en latín lo que "
         "sonaba en chino. " * 10).strip()

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})
r = cliente.post("/api/proyectos", json={"nombre": "CTAs"})
pid = r.json()["id"]
pasos = cliente.get(f"/api/proyectos/{pid}/pasos").json()
cta_guardado = pasos["pasos"]["guion"]["params"].get("cta")
check("proyecto nuevo siembra la caja APAGADA",
      cta_guardado == cta.POR_DEFECTO, str(cta_guardado))

cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
            json={"texto": TEXTO, "titulo": "El pinyin"})
ficha_trabajo = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/ingesta/ejecutar", json={}).json()["id"])
check("ingesta hecha", ficha_trabajo["estado"] == "hecho",
      str(ficha_trabajo)[:150])
ficha_trabajo = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/brief/ejecutar", json={}).json()["id"])
check("brief hecho", ficha_trabajo["estado"] == "hecho",
      str(ficha_trabajo)[:150])

# la API valida la caja: a lo malforme, 400 y sin guardar nada
params_antes = cliente.get(
    f"/api/proyectos/{pid}/pasos").json()["pasos"]["guion"]["params"]
r = cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
                json={"duracion_min": 10, "cta": {"cta_medio": "que comente"}})
check("la API rechaza una caja que no son objetos",
      r.status_code == 400, str(r.status_code))
r = cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
                json={"duracion_min": 10, "cta": {"presentacion": {
                    "puesto": True, "texto": "x" * 900}}})
check("la API rechaza el texto que ya no es una frase",
      r.status_code == 400, str(r.status_code))
check("lo rechazado no se guardó",
      cliente.get(f"/api/proyectos/{pid}/pasos").json()[
          "pasos"]["guion"]["params"] == params_antes)

# ------------------------------------------------------- el prompt del guion

registro_llamadas.clear()
respuestas_guion[:] = [guion_lata(4, 10), guion_lata(4, 30)]
cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
            json={"duracion_min": 1,
                  "cta": {"presentacion": {"puesto": True, "texto": "que se "
                                   "sepa quién soy"},
                          "cta_final": {"puesto": True,
                                        "texto": "que se suscriba"}}})
ficha_trabajo = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/guion/ejecutar", json={}).json()["id"])
check("guion con llamadas hecho", ficha_trabajo["estado"] == "hecho",
      str(ficha_trabajo)[:200])
guion_llamadas = [c for c in registro_llamadas if c["contexto"] == "guion"]
check("la sección viaja en TODOS los intentos (también el reintento)",
      len(guion_llamadas) == 2
      and all("LA PRESENTACIÓN Y LAS LLAMADAS A LA ACCIÓN" in c["instruccion"]
              and "que se suscriba" in c["instruccion"]
              for c in guion_llamadas),
      f"{len(guion_llamadas)} llamadas")

# sin la caja (proyectos de antes de que existiera): prompt igual
registro_llamadas.clear()
respuestas_guion[:] = [guion_lata(4, 10), guion_lata(4, 30)]
cliente.put(f"/api/proyectos/{pid}/pasos/guion/params",
            json={"duracion_min": 1})
ficha_trabajo = esperar_trabajo(cliente.post(
    f"/api/proyectos/{pid}/pasos/guion/ejecutar", json={}).json()["id"])
check("guion sin caja hecho (modo de siempre)", ficha_trabajo["estado"]
      == "hecho", str(ficha_trabajo)[:200])
guion_llamadas = [c for c in registro_llamadas if c["contexto"] == "guion"]
check("sin puestos NO hay sección en el prompt",
      all("LLAMADAS A LA ACCIÓN" not in c["instruccion"]
          for c in guion_llamadas),
      f"{len(guion_llamadas)} llamadas")

llm.llamar_json = _llamar_json_real

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("llamadas a la acción: todo verde")
