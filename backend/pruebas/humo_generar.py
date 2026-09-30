"""Prueba de humo del botón «generar» y del cierre del modo light.

Cuatro piezas que son UNA doctrina: lo que la pantalla dice que va a
pasar es lo que pasa. Se comprueba todo SIN claves de pago (el doble
del modelo devuelve lata y los pasos de voz están parcheados):

- el PLAN (GET /generar): las pestañas con Origen delante si falta el
  material, lo que se salta, el coste de los `estimar` de cada paso y
  los «?» dichos en sin_saber (no inventados), la puerta del guion
  como impedimento DICHO, y las tandas del botón (vídeo = mirar sin
  montar)
- la CADENA (POST /generar): UN trabajo que recorre las pestañas,
  guarda los params ANTES de lanzar, salta lo al día (el modo
  pendiente ES el retomar), para sin fallo ante el guion sin aprobar
  y sigue tras aprobar; 400 si no hay nada pendiente y a lo malforme
- el VÍDEO LIGHT (POST /presets-light/{prid}/video): un proyecto
  NORMAL con el estilo aplicado por el MISMO código del botón del
  editor y el encargo sembrado en los cajones de siempre
- RETOMAR y DESCARTAR talleres: el encargo del cuerpo refresca, se
  rellama con retomar=True; un taller huérfano se tira a la papelera
  y el de un estilo guardado no (409)
- la ESTIMACIÓN previa (POST /estimacion): la misma aritmética de los
  pasos, sin proyecto delante

Ejecutar:

    python pruebas/humo_generar.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_generar_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import rutas_presets  # noqa: E402
from app.config import AJUSTES  # noqa: E402
from app.main import app  # noqa: E402
from app.motores import llm  # noqa: E402
from app.nucleo.proyecto import Proyecto  # noqa: E402
from app.pasos import (p4_voz, p5_revision_audio, p3_guion, presets_canal,  # noqa: E402
                       presets_light, registro)

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


cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

TEXTO = ("La historia del pinyin cuenta cómo se escribió en latín lo que "
         "sonaba en chino. " * 10).strip()

# ------------------------------------------------------- A: el plan
#
# Antes de pulsar el botón: qué se va a hacer, qué se salta y cuánto
# cuesta. Sin material el plan antepone Origen — que la cadena reviente
# en el brief es un fallo que se ve a simple vista aquí.

pid = cliente.post("/api/proyectos",
                   json={"nombre": "Generar"}).json()["id"]

plan = cliente.get(f"/api/proyectos/{pid}/generar").json()
check("plan por defecto: la cadena COMPLETA con Origen delante",
      plan["pestanas"] == ["origen", "guion", "voz", "montaje"],
      str(plan["pestanas"]))
ids_plan = [t["id"] for f in plan["fases"] for t in f["tareas"]]
check("las 8 tareas en orden de grafo",
      ids_plan == ["ingesta", "brief", "guion", "voz", "revision_audio",
                   "assets", "callouts", "render"], str(ids_plan))
check("todo vacío: las 8 pendientes y ninguna al día",
      plan["pendientes"] == 8
      and all(t["se_hace"] and not t["al_dia"]
              for f in plan["fases"] for t in f["tareas"]),
      str(plan["pendientes"]))
check("el coste dice lo que no sabe (imágenes y voz) en vez de inventarlo",
      "assets" in plan["coste"]["sin_saber"]
      and "voz" in plan["coste"]["sin_saber"],
      str(plan["coste"]))
check("el coste de LLM sale de los estimar de los pasos",
      plan["coste"]["llamadas_llm"] >= 2 and plan["coste"]["usd_llm"] > 0,
      str(plan["coste"]["llamadas_llm"]))
check("la puerta del guion se DICE antes de pulsar",
      len(plan["impedimentos"]) == 1
      and plan["impedimentos"][0]["tarea"] == "voz",
      str(plan["impedimentos"])[:120])
check("el plan lleva el catálogo de tandas",
      sorted(plan["tandas"]) == ["guion", "render", "video", "voz"])

plan_video = cliente.get(
    f"/api/proyectos/{pid}/generar",
    params={"tanda": "video"}).json()
ids_video = [t["id"] for f in plan_video["fases"] for t in f["tareas"]]
check("tanda vídeo: mirar sin montar (Origen + sólo imágenes)",
      plan_video["pestanas"] == ["origen", "montaje"]
      and ids_video == ["ingesta", "assets"]
      and plan_video["pendientes"] == 2
      and plan_video["impedimentos"] == [], str(ids_video))

plan_render = cliente.get(
    f"/api/proyectos/{pid}/generar",
    params={"tanda": "render"}).json()
ids_render = [t["id"] for f in plan_render["fases"] for t in f["tareas"]]
check("tanda render: el montaje entero",
      ids_render == ["ingesta", "assets", "callouts", "render"],
      str(ids_render))

for params_query, motivo in [
        ({"tanda": "noexiste"}, "tanda desconocida"),
        ({"pestanas": "guion,marciano"}, "pestaña desconocida"),
        ({"modo": "ya"}, "modo que no es")]:
    r = cliente.get(f"/api/proyectos/{pid}/generar", params=params_query)
    check(f"el plan rechaza la {motivo}", r.status_code == 400,
          str(r.status_code))
r = cliente.get("/api/proyectos/marciano/generar")
check("plan de un proyecto que no existe: 404", r.status_code == 404)

# ------------------------------------------------------ B: la cadena
#
# UN trabajo que recorre varias pestañas. El doble del modelo devuelve
# brief y guion de lata; la voz va parcheada porque el dinero de verdad
# no se toca en una prueba.

registro_llamadas: list[str] = []
respuestas_guion: list[dict] = []
_llamar_json_real = llm.llamar_json


def llamar_json_falso(llamada, **_):
    registro_llamadas.append(getattr(llamada, "contexto", ""))
    if getattr(llamada, "contexto", "") == "brief":
        return {"puntos": ["un punto", "otro punto"], "tono": "cercano",
                "formato": {"min": 20, "max": 40}}
    return respuestas_guion.pop(0)


def guion_lata(n_escenas: int, n_palabras: int) -> dict:
    return {"escenas": [
        {"id": f"S{i:03d}", "titulo": f"escena {i}",
         "narracion": " ".join(f"palabra{j}" for j in range(n_palabras)),
         "visual": "un plano", "texto_pantalla": "rotulo",
         "duracion_estimada": 10}
        for i in range(1, n_escenas + 1)]}


llm.llamar_json = llamar_json_falso
respuestas_guion[:] = [guion_lata(4, 10), guion_lata(4, 30),
                       guion_lata(4, 30)]

r = cliente.post(f"/api/proyectos/{pid}/generar", json={
    "tanda": "guion",
    "params": {"ingesta": {"texto": TEXTO, "titulo": "El pinyin"},
               "guion": {"duracion_min": 1}}})
check("la cadena arranca en UN trabajo (202)", r.status_code == 202,
      str(r.status_code))
cuerpo = r.json()
check("la tanda guion se ensancha con Origen delante",
      cuerpo["pestanas"] == ["origen", "guion"]
      and cuerpo["modo"] == "pendiente"
      and cuerpo["plan"]["pendientes"] == 3, str(cuerpo["pestanas"]))
ficha = esperar_trabajo(cuerpo["trabajo"]["id"])
check("la cadena termina hecha", ficha["estado"] == "hecho",
      str(ficha)[:200])
check("la cadena corrió ingesta, brief y guion",
      ficha.get("resultado", {}).get("hechos")
      == ["ingesta", "brief", "guion"],
      str(ficha.get("resultado"))[:150])
pasos = cliente.get(f"/api/proyectos/{pid}/pasos").json()["pasos"]
check("los params del cuerpo quedaron guardados ANTES de correr",
      pasos["ingesta"]["params"].get("titulo") == "El pinyin"
      and pasos["guion"]["params"].get("duracion_min") == 1,
      str(pasos["ingesta"]["params"])[:120])
check("el guion está al día en el disco",
      pasos["guion"].get("estado") == "ok", str(pasos["guion"])[:120])

# el modo pendiente ES el retomar: nada pendiente -> 400 con la pista
r = cliente.post(f"/api/proyectos/{pid}/generar", json={"tanda": "guion"})
check("nada pendiente: 400 con la pista del modo todo",
      r.status_code == 400 and "todo" in r.json().get("error", ""),
      str(r.status_code) + " " + r.text[:120])
plan_ya = cliente.get(f"/api/proyectos/{pid}/generar",
                      params={"tanda": "guion"}).json()
check("el plan de lo al día dice que no hay nada que hacer",
      plan_ya["pendientes"] == 0
      and all(t["al_dia"] and not t["se_hace"]
              for f in plan_ya["fases"] for t in f["tareas"]))

# la puerta del guion: la cadena PARA sin fallo antes de pagar la voz
r = cliente.post(f"/api/proyectos/{pid}/generar", json={"tanda": "voz"})
check("la voz sin aprobar no bloquea el lanzamiento (202)",
      r.status_code == 202, str(r.status_code))
ficha = esperar_trabajo(r.json()["trabajo"]["id"])
check("el trabajo acaba HECHO: la parada no es un fallo",
      ficha["estado"] == "hecho" and ficha["resultado"]["paro"]
      == "guion_sin_aprobar" and ficha["resultado"]["hechos"] == [],
      str(ficha.get("resultado"))[:150])

# aprobado el guion, la misma tanda corre voz y revisión (parcheadas:
# aquí no se paga ElevenLabs)
cliente.post(f"/api/proyectos/{pid}/pasos/guion/aprobar")
_ejecutar_voz_real, _ejecutar_rev_real = (p4_voz.ejecutar,
                                          p5_revision_audio.ejecutar)
p4_voz.ejecutar = lambda proyecto, params, trabajo, **_: {
    "escenas": [{"id": "S001", "audio": "toma.mp3", "duracion": 5.0}]}
p5_revision_audio.ejecutar = lambda proyecto, params, trabajo, **_: {
    "comentarios": []}
r = cliente.post(f"/api/proyectos/{pid}/generar", json={"tanda": "voz"})
ficha = esperar_trabajo(r.json()["trabajo"]["id"])
check("aprobado el guion, la cadena corre voz y revisión",
      ficha["estado"] == "hecho"
      and ficha["resultado"]["hechos"] == ["voz", "revision_audio"]
      and ficha["resultado"]["paro"] is None,
      str(ficha.get("resultado"))[:150])
check("la voz quedó al día en el disco (el retomar la saltará)",
      cliente.get(f"/api/proyectos/{pid}/pasos").json()["pasos"][
          "voz"]["estado"] == "ok")
p4_voz.ejecutar, p5_revision_audio.ejecutar = (_ejecutar_voz_real,
                                               _ejecutar_rev_real)

# los params malformes se rechazan ANTES de guardar nada
r = cliente.post(f"/api/proyectos/{pid}/generar", json={
    "tanda": "guion", "params": {"guion": {"cta": "suscribete"}},
    "modo": "todo"})
check("una caja de llamadas que no son objetos: 400", r.status_code == 400)
r = cliente.post(f"/api/proyectos/{pid}/generar", json={
    "tanda": "guion", "params": {"ingesta": {}}, "modo": "todo"})
check("params vacíos: 400", r.status_code == 400)
r = cliente.post("/api/proyectos/marciano/generar", json={"tanda": "voz"})
check("la cadena de un proyecto que no existe: 404", r.status_code == 404)
llm.llamar_json = _llamar_json_real

# ------------------------------------------- C: el vídeo light
#
# El estilo guardado se convierte en un proyecto NORMAL con el estilo
# aplicado por el MISMO código del botón del editor.

tid_taller = rutas_presets._crear_taller(presets_light.validar_encargo({
    "nombre": "Canal de humo", "idioma": "es",
    "estilo_prompt": "líneas limpias y dos colores planos",
    "tono_prompt": "seco y sin adjetivos, que los datos hablen solos",
    "voz_prompt": "grave, pausada, sin dramatismo"})).id
preset = presets_canal.guardar(
    "canal", "Canal de humo",
    {"guion": {"idioma": "en", "tono": "cercano"},
     "origen": {"taller": tid_taller, "idioma": "en"}})
prid = preset["id"]

r = cliente.post(f"/api/presets-light/{prid}/video", json={
    "encargo": {"nombre": "El pinyin en cinco",
                "material": TEXTO[:300], "duracion_min": 5,
                "cta": {"cta_medio": {"puesto": True,
                                      "texto": "que se suscriba"}}}})
check("el vídeo light nace (201)", r.status_code == 201,
      str(r.status_code) + " " + str(r.json())[:150])
nuevo = r.json()
vid = nuevo["proyecto"]["id"]
check("el estilo aplicado es el del preset",
      nuevo["estilo"]["id"] == prid and nuevo["aplicado"],
      str(nuevo["aplicado"]))
check("el proyecto recuerda de dónde nació",
      Proyecto(AJUSTES.carpeta_proyectos / vid).leer().get("estilo_light")
      == prid)
pasos = cliente.get(f"/api/proyectos/{vid}/pasos").json()["pasos"]
check("el material y la duración van a los cajones de siempre",
      pasos["ingesta"]["params"].get("texto") == TEXTO[:300].strip()
      and pasos["guion"]["params"].get("duracion_min") == 5,
      str(pasos["ingesta"]["params"])[:100])
check("las llamadas a la acción viajan normalizadas",
      pasos["guion"]["params"]["cta"]["cta_medio"]
      == {"puesto": True, "texto": "que se suscriba"})
check("el idioma lo hereda del estilo",
      Proyecto(AJUSTES.carpeta_proyectos / vid).leer().get("idioma")
      == "en")

# lo que no se puede sembrar se DICE en un aviso, no se calla
r = cliente.post(f"/api/presets-light/{prid}/video", json={
    "encargo": {"material": "", "duracion_min": 999,
                "cta": {"presentacion": "hola"}}})
avisos = r.json()["avisos"]
check("el material vacío, la duración loca y la caja mala: avisos",
      r.status_code == 201 and len(avisos) == 3
      and any("duración" in a for a in avisos)
      and any("llamadas" in a for a in avisos), str(avisos)[:200])

r = cliente.post("/api/presets-light/marciano/video", json={})
check("un estilo que no existe: 404", r.status_code == 404)
prid_guion = presets_canal.guardar("guion", "Un guion suelto",
                                   {"idioma": "es"})["id"]
r = cliente.post(f"/api/presets-light/{prid_guion}/video", json={})
check("un preset que no es de canal: 400", r.status_code == 400)

# ------------------------------- D: retomar el taller, descartar talleres
#
# Un fallo de red a mitad de la guía tiene que ser volver a pulsar, no
# rehacer el tono que ya estaba escrito.

llamadas_taller: list[dict] = []
_correr_taller_real = rutas_presets._correr_taller


def correr_taller_falso(taller, prid_, solo=None, retomar=False,
                        extra_encargo=None):
    llamadas_taller.append({"taller": taller.id, "retomar": retomar})
    return lambda trabajo: {"taller": taller.id, "de mentira": True}


rutas_presets._correr_taller = correr_taller_falso

encargo = {"nombre": "Canal de humo", "idioma": "es",
           "estilo_prompt": "líneas limpias y dos colores planos",
           "tono_prompt": "seco y sin adjetivos, que los datos hablen solos",
           "voz_prompt": "grave, pausada, sin dramatismo"}
r = cliente.post("/api/presets-light", json={"encargo": encargo})
check("un taller nuevo arranca (202, retomado False)",
      r.status_code == 202 and r.json()["retomado"] is False,
      str(r.json())[:150])
t1 = r.json()["taller"]
check("el trabajo del taller es el parche (nada se genera de verdad)",
      esperar_trabajo(r.json()["trabajo"]["id"])["estado"] == "hecho")

encargo_retocado = dict(encargo, nombre="Canal retocado",
                        tono_prompt="más seco")
r = cliente.post("/api/presets-light",
                 json={"taller": t1, "encargo": encargo_retocado})
check("retomar el taller: 202 y retomado True",
      r.status_code == 202 and r.json()["retomado"] is True,
      str(r.json())[:150])
check("se rellama al motor con retomar=True",
      llamadas_taller[-1] == {"taller": t1, "retomar": True},
      str(llamadas_taller[-1]))
check("el encargo del cuerpo REFRESCA el del taller",
      Proyecto(AJUSTES.carpeta_proyectos / t1).leer()[
          "encargo"]["nombre"] == "Canal retocado")
esperar_trabajo(r.json()["trabajo"]["id"])

# descartar: el taller de un estilo guardado es una pieza de él (409);
# el huérfano se va a la PAPELERA, no al vacío
r = cliente.delete(f"/api/presets-light/talleres/{tid_taller}")
check("el taller de un estilo guardado no se tira (409)",
      r.status_code == 409, str(r.status_code))
r = cliente.delete(f"/api/presets-light/talleres/{t1}")
check("el taller huérfano se descarta (204)", r.status_code == 204,
      str(r.status_code))
check("el taller huérfano acaba en la papelera de proyectos",
      (AJUSTES.datos / "papelera" / t1).exists()
      and not (AJUSTES.carpeta_proyectos / t1).exists())
r = cliente.delete(f"/api/presets-light/talleres/{t1}")
check("descartar dos veces: 404", r.status_code == 404)
r = cliente.delete(f"/api/presets-light/talleres/{pid}")
check("un proyecto normal no es un taller: 400", r.status_code == 400)

rutas_presets._correr_taller = _correr_taller_real

# -------------------------------------------------- E: la estimación
#
# Sin proyecto delante: la misma aritmética de los pasos para saber si
# el vídeo merece la pena ANTES de crear nada.

est = cliente.post("/api/estimacion",
                   json={"duracion_min": 10, "ritmo": "medio"}).json()
check("diez minutos son 600 s y 1560 palabras (ritmo del paso)",
      est["duracion_objetivo_s"] == 600
      and est["palabras"]["objetivo"] == 1560
      and est["palabras"]["minimo"] < 1560 < est["palabras"]["maximo"],
      str(est["palabras"])[:120])
check("las escenas salen de la horquilla del ritmo medio",
      est["palabras"]["escenas"] == 22, str(est["palabras"]["escenas"]))
check("los planos salen del corte 3-6 s (la media 4,5)",
      est["planos"]["total"] == 133 and est["planos"]["media_s"] == 4.5,
      str(est["planos"]))
check("el dinero suma imágenes, voz y dos llamadas",
      est["coste"]["usd_imagenes"] == round(133 * 0.015, 3)
      and est["coste"]["usd_tts"] == round(round(1560 * 6.1) / 6667, 3)
      and est["coste"]["usd_llm"] == 0.008
      and est["coste"]["usd_total"] > 3, str(est["coste"]))

est = cliente.post("/api/estimacion",
                   json={"ritmo_min": 6, "ritmo_max": 15}).json()
check("sin ritmo escrito se deduce de la horquilla (muy rápido)",
      est["ritmo"]["id"] == "muy_rapido", str(est["ritmo"]))
est = cliente.post("/api/estimacion", json={"duracion_min": 9999}).json()
check("la duración se acota a los 180 minutos",
      est["duracion_min"] == 180, str(est["duracion_min"]))
r = cliente.post("/api/estimacion", json={"duracion_min": "nada"})
check("una duración que no es un número: 400", r.status_code == 400)

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("generar, vídeo light y talleres: todo verde")
