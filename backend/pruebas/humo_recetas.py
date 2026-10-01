"""Prueba de humo del almacén de recetas: API + resolución + cableado.

Sin tocar servicios de pago: el almacén es del canal y el vídeo que
corre una receta va con el modelo falseado y la voz parcheada. Se
prueba el ciclo entero — catálogo, guardar (y lo que fuerza), resolver
(prioridades y lo no opcional), por defecto, sobreescribir, borrar —
más el orden topológico, la tabla que pinta la pantalla y el CABLEADO:
la ficha del proyecto dice qué receta correría ahora y la ruta de
receta la obedece (la guardada por defecto recorta, quien lanza manda).
Ejecutar:

    python pruebas/humo_recetas.py

Sale 0 si todo verde; imprime cada chequeo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# almacén y datos aislados ANTES de importar la app
_raiz = Path(__file__).resolve().parent.parent
_dir = tempfile.mkdtemp(prefix="estudio_humo_recetas_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir) / "datos")
os.environ["ESTUDIO_RECETAS"] = str(Path(_dir) / "recetas.json")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AJUSTES  # noqa: E402
from app.main import app  # noqa: E402
from app.motores import llm  # noqa: E402
from app.nucleo import recetas  # noqa: E402
from app.nucleo.proyecto import Proyecto, leer_jsonl  # noqa: E402
from app.pasos import p4_voz, p5_revision_audio  # noqa: E402

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


# ------------------------------------------------------------------- catálogo

r = cliente.get("/api/recetas")
check("GET /api/recetas responde 200", r.status_code == 200)
cat = r.json()
check("el catálogo trae las pestañas y tareas",
      set(cat["pestañas"]) == set(recetas.PESTANAS)
      and {t["id"] for t in cat["tareas"]} == set(recetas.TAREAS_POR_ID))
check("el catálogo trae las tandas y ninguna receta aún",
      cat["tandas"] == recetas.TANDAS and cat["recetas"] == []
      and cat["por_defecto"] == {})

r = cliente.get("/api/proyectos/recetas")
check("la tabla del tablero sigue viva", r.status_code == 200
      and r.json()["tareas"][0]["id"] == "ingesta")

# -------------------------------------------------------------------- guardar

r = cliente.post("/api/recetas", json={"pestana": "montaje"})
check("sin nombre no se guarda", r.status_code == 400)

r = cliente.post("/api/recetas",
                 json={"pestana": "mares", "nombre": "Naufragio"})
check("pestaña desconocida no se guarda", r.status_code == 400)

r = cliente.post("/api/recetas",
                 json={"pestana": "montaje", "nombre": "Sólo imágenes",
                       "tareas": {"callouts": False, "render": False,
                                  "voz": True}})
check("tarea de otra pestaña no se guarda", r.status_code == 400)

r = cliente.post("/api/recetas",
                 json={"pestana": "montaje", "nombre": "Sólo imágenes",
                       "tareas": {"callouts": False, "render": False}})
check("guardar responde 200 con id nuevo", r.status_code == 200
      and r.json()["id"].startswith("rc"))
guardada = r.json()
check("lo no opcional se fuerza aunque no venga",
      guardada["tareas"]["assets"] is True)
check("lo que se apagó se apagó",
      guardada["tareas"]["callouts"] is False
      and guardada["tareas"]["render"] is False)

cat = cliente.get("/api/recetas").json()
check("la receta guardada aparece en el catálogo",
      [r["id"] for r in cat["recetas"]] == [guardada["id"]])

# ------------------------------------------------------------------- resolver

receta = recetas.resolver("montaje", guardada["id"])
check("resolver respeta lo guardado",
      receta["tareas"] == guardada["tareas"])
check("resolver devuelve el nombre para la bitácora",
      receta["nombre"] == "Sólo imágenes")

receta = recetas.resolver("montaje", guardada["id"], {"render": True})
check("quien lanza manda sobre lo guardado",
      receta["tareas"]["render"] is True
      and receta["tareas"]["callouts"] is False)

receta = recetas.resolver("montaje", guardada["id"], {"assets": False})
check("quien lanza NO puede apagar lo no opcional",
      receta["tareas"]["assets"] is True)

try:
    recetas.resolver("mares")
    check("resolver rechaza pestaña desconocida", False)
except recetas.ErrorReceta:
    check("resolver rechaza pestaña desconocida", True)

# ------------------------------------------------------- defecto y sobreescribir

r = cliente.post("/api/recetas",
                 json={"pestana": "voz", "nombre": "Sin revisión",
                       "tareas": {"revision_audio": False},
                       "por_defecto": True})
sin_revision = r.json()
check("guardar con por_defecto responde 200", r.status_code == 200)
check("la receta de voz forcejea la revisión apagada",
      sin_revision["tareas"] == {"voz": True,
                                 "revision_audio": False})

cat = cliente.get("/api/recetas").json()
check("el por defecto quedó apuntado",
      cat["por_defecto"].get("voz") == sin_revision["id"])

receta = recetas.resolver("voz")
check("sin pedir receta se usa la puesta por defecto",
      receta["id"] == sin_revision["id"]
      and receta["tareas"]["revision_audio"] is False)

receta = recetas.resolver("guion")
check("una pestaña sin receta cae en la de fábrica (todo)",
      receta["nombre"] == "Todo" and receta["tareas"]["guion"] is True)

r = cliente.post("/api/recetas",
                 json={"id": guardada["id"], "pestana": "montaje",
                       "nombre": "Sólo imágenes", "nota": "v2",
                       "tareas": {"render": True, "callouts": False}})
check("sobreescribir con el mismo id no duplica", r.status_code == 200
      and r.json()["id"] == guardada["id"]
      and len(cliente.get("/api/recetas").json()["recetas"]) == 2)

# --------------------------------------------------------------------- borrar

r = cliente.delete(f"/api/recetas/{guardada['id']}")
check("borrar responde 200", r.status_code == 200
      and r.json()["borrada"] == guardada["id"])
r = cliente.delete(f"/api/recetas/{guardada['id']}")
check("borrar dos veces da 404", r.status_code == 404)
check("borrar la por defecto la despega",
      "montaje" not in cliente.get("/api/recetas").json()["por_defecto"])

# ------------------------------------------------------- orden y persistencia

orden = [t["id"] for t in recetas.orden_de("guion")]
check("orden topológico: brief antes que guion", orden == ["brief", "guion"])
tandas = [[t["id"] for t in tanda] for tanda in
          recetas.tandas_de("montaje")]
check("tandas: assets sola, rótulos y montaje a la vez",
      tandas == [["assets"], ["callouts", "render"]])
check("una dependencia excluida no espera",
      [t["id"] for t in recetas.orden_de("montaje", {"render"})] == ["render"])

check("el almacén persiste en disco (leer vuelve a abrir el fichero)",
      recetas.resolver("voz")["id"] == sin_revision["id"]
      and Path(os.environ["ESTUDIO_RECETAS"]).is_file())

# -------------------------------------------------- el cableado (un vídeo)
#
# La «Sin revisión» quedó puesta por defecto para la voz. La ficha del
# proyecto tiene que CONTARLA (receta y puestas) y la ruta de receta
# OBEDECERLA — sin gastar un céntimo: el doble del modelo devuelve lata
# y la voz y su revisión van parcheadas.

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})
TEXTO = ("La historia del pinyin cuenta cómo se escribió en latín lo que "
         "sonaba en chino. " * 10).strip()

pid = cliente.post("/api/proyectos",
                   json={"nombre": "Recetas de humo"}).json()["id"]
cliente.put(f"/api/proyectos/{pid}/pasos/ingesta/params",
            json={"texto": TEXTO, "titulo": "El pinyin"})

ficha = cliente.get(f"/api/proyectos/{pid}/receta").json()
check("la ficha dice con qué receta correría cada pestaña",
      ficha["pestañas"]["voz"]["receta"]
      == {"id": sin_revision["id"], "nombre": "Sin revisión"},
      str(ficha["pestañas"]["voz"]["receta"]))
check("las puestas de la ficha son las de la receta",
      {t["id"]: t["puesta"] for t in ficha["pestañas"]["voz"]["tareas"]}
      == {"voz": True, "revision_audio": False})
check("una pestaña sin nada guardado cae en la de fábrica (Todo, id vacío)",
      ficha["pestañas"]["guion"]["receta"] == {"id": "", "nombre": "Todo"}
      and all(t["puesta"] for t in ficha["pestañas"]["guion"]["tareas"]))

respuestas_guion: list[dict] = []
_llamar_json_real = llm.llamar_json


def llamar_json_falso(llamada, **_):
    if getattr(llamada, "contexto", "") == "brief":
        return {"puntos": ["un punto", "otro punto"], "tono": "cercano",
                "formato": {"min": 20, "max": 40}}
    return respuestas_guion.pop(0)


def guion_lata(n_escenas: int) -> dict:
    return {"escenas": [
        {"id": f"S{i:03d}", "titulo": f"escena {i}",
         "narracion": " ".join(f"palabra{j}" for j in range(10)),
         "visual": "un plano", "texto_pantalla": "rotulo",
         "duracion_estimada": 10}
        for i in range(1, n_escenas + 1)]}


llm.llamar_json = llamar_json_falso
respuestas_guion[:] = [guion_lata(3), guion_lata(3), guion_lata(3)]
r = cliente.post(f"/api/proyectos/{pid}/receta/origen")
check("la receta de origen corre la ingesta", r.status_code == 202,
      str(r.status_code))
trabajo = esperar_trabajo(r.json()["id"])
check("la ingesta quedó hecha (el brief necesita su texto)",
      trabajo["estado"] == "hecho"
      and trabajo["resultado"]["hechos"] == ["ingesta"],
      str(trabajo.get("resultado"))[:150])

r = cliente.post(f"/api/proyectos/{pid}/receta/guion")
check("correr una pestaña arranca en UN trabajo (202)", r.status_code == 202,
      str(r.status_code))
trabajo = esperar_trabajo(r.json()["id"])
check("la receta de fábrica corrió brief y guion",
      trabajo["estado"] == "hecho"
      and trabajo["resultado"]["hechos"] == ["brief", "guion"],
      str(trabajo.get("resultado"))[:150])
eventos = leer_jsonl(Proyecto(AJUSTES.carpeta_proyectos / pid).fichero_bitacora)
check("la bitácora cuenta la receta con la que corrió",
      any(e.get("evento") == "receta_lanzada" and e.get("receta") == "Todo"
          and e.get("pestaña") == "guion" for e in eventos),
      str([e for e in eventos if e.get("evento") == "receta_lanzada"])[:150])
ficha = cliente.get(f"/api/proyectos/{pid}/receta").json()
guion_t = {t["id"]: t for t in ficha["pestañas"]["guion"]["tareas"]}
check("la ficha refleja el estado real de cada tarea",
      guion_t["guion"]["estado"] == "ok" and guion_t["guion"]["version"] >= 1,
      str(guion_t["guion"])[:120])

# la voz sin aprobar PARARÍA la receta: se aprueba primero, y luego se
# comprueba que la guardada por defecto RECORTA la revisión de audio
cliente.post(f"/api/proyectos/{pid}/pasos/guion/aprobar")
_ejecutar_voz_real, _ejecutar_rev_real = (p4_voz.ejecutar,
                                          p5_revision_audio.ejecutar)
p4_voz.ejecutar = lambda proyecto, params, trabajo, **_: {
    "escenas": [{"id": "S001", "audio": "toma.mp3", "duracion": 5.0}]}
p5_revision_audio.ejecutar = lambda proyecto, params, trabajo, **_: {
    "comentarios": []}
try:
    r = cliente.post(f"/api/proyectos/{pid}/receta/voz",
                     json={"modo": "todo"})
    trabajo = esperar_trabajo(r.json()["id"])
    check("la puesta por defecto recorta la revisión de la voz",
          trabajo["estado"] == "hecho"
          and trabajo["resultado"]["tareas"] == ["voz"]
          and trabajo["resultado"]["hechos"] == ["voz"],
          str(trabajo.get("resultado"))[:150])

    r = cliente.post(f"/api/proyectos/{pid}/receta/voz", json={
        "modo": "todo", "receta": sin_revision["id"],
        "tareas": {"revision_audio": True}})
    trabajo = esperar_trabajo(r.json()["id"])
    check("quien lanza manda: la revisión vuelve a entrar",
          trabajo["estado"] == "hecho"
          and trabajo["resultado"]["hechos"] == ["voz", "revision_audio"],
          str(trabajo.get("resultado"))[:150])
finally:
    p4_voz.ejecutar, p5_revision_audio.ejecutar = (_ejecutar_voz_real,
                                                   _ejecutar_rev_real)

r = cliente.post(f"/api/proyectos/{pid}/receta/montaje",
                 json={"receta": sin_revision["id"]})
check("una receta de OTRA pestaña no corre (400)", r.status_code == 400,
      r.text[:120])
r = cliente.post(f"/api/proyectos/{pid}/receta/guion",
                 json={"tareas": "todas"})
check("las tareas malformes se rechazan antes de lanzar (400)",
      r.status_code == 400, r.text[:120])
r = cliente.post(f"/api/proyectos/{pid}/receta/guion",
                 json={"modo": "ya"})
check("un modo que no es: 400", r.status_code == 400)
r = cliente.post("/api/proyectos/marciano/receta/guion")
check("la receta de un proyecto que no existe: 404", r.status_code == 404)
llm.llamar_json = _llamar_json_real

# ---------------------------------------------------------------------- cierre

if fallos:
    print(f"\n{len(fallos)} fallos: " + ", ".join(fallos))
    sys.exit(1)
print("\nOK — recetas")
