"""Prueba de humo de la voz del canal (Configuración → Voces).

El canal fija UNA vez el motor y el voice_id con el que se graban sus
vídeos; la jerarquía la resuelve p4_voz EN CADA CORRIDA: lo elegido en
el vídeo manda (su pestaña de Voz, un preset, el estilo al crearlo);
un valor que sigue siendo el de FÁBRICA es uno que nadie eligió, y
entonces manda el canal; sin nada, la fábrica (Rachel).

Se prueba SIN pagar nada (el motor de ElevenLabs va doblado):

- voz_canal: leer por defecto, guardar (persistencia en ajustes.json,
  motor desconocido rechazado, voz recortada, ajustes con «voz» rota)
- API /api/ajustes/voz: GET por defecto con la lista de motores, PUT
  guarda, PUT con motor desconocido → 400, PUT vacío → 400
- la siembra: crear un vídeo siembra la voz de FÁBRICA (nunca la del
  canal), para que la de Configuración sea viva y no una copia helada
- la resolución en p4: el canal se lleva al vídeo de fábrica, cambiar
  el canal es VIVO en la siguiente corrida, lo del vídeo manda por
  mando (voz y motor se resuelven por separado), canal sin voz →
  fábrica; y la puerta del guion aprobado sigue cerrada (409)

Ejecutar:

    python pruebas/humo_voz_canal.py

Sale 0 si todo verde; imprime cada chequeo.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir = tempfile.mkdtemp(prefix="estudio_humo_voz_canal_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir) / "datos")
os.environ["ESTUDIO_ELEVENLABS_KEY"] = "clave-de-prueba"
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AJUSTES  # noqa: E402
from app.main import app  # noqa: E402
from app.nucleo import voz_canal  # noqa: E402
from app.nucleo.estado import Estado  # noqa: E402
from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.motores import voz_elevenlabs  # noqa: E402
from app.pasos import p4_voz  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" — {detalle}" if detalle and not condicion else ""))
    if not condicion:
        fallos.append(nombre)


class TrabajoMudo:
    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass


# -------------------------------------------------------- nucleo: voz_canal

por_defecto = voz_canal.leer(AJUSTES.datos)
check("sin nada guardado el canal no tiene voz",
      por_defecto == {"motor": voz_canal.MOTOR_DEFECTO, "voz": ""},
      str(por_defecto))

guardada = voz_canal.guardar(AJUSTES.datos, motor="flash",
                             voz="pNInz6obpgDQGcFmaJgB")
check("guardar devuelve la preferencia saneada",
      guardada == {"motor": "flash", "voz": "pNInz6obpgDQGcFmaJgB"}
      and voz_canal.leer(AJUSTES.datos) == guardada,
      str(guardada))
check("la preferencia persiste en ajustes.json (clave «voz»)",
      (leer := voz_canal.leer(AJUSTES.datos)) == guardada
      and (Path(AJUSTES.datos) / "ajustes.json").is_file())

rechazado = False
try:
    voz_canal.guardar(AJUSTES.datos, motor="turbina", voz="x")
except ValueError:
    rechazado = True
check("un motor desconocido se rechaza", rechazado)

voz_canal.guardar(AJUSTES.datos, motor="flash", voz="x" * 70)
check("un voice_id desaforado se recorta a 64",
      len(voz_canal.leer(AJUSTES.datos)["voz"]) == 64)

escribir_json(Path(AJUSTES.datos) / "ajustes.json", {"voz": "rota"})
check("unos ajustes con «voz» rota caen en sin preferencia",
      voz_canal.leer(AJUSTES.datos) == {"motor": voz_canal.MOTOR_DEFECTO,
                                        "voz": ""})
escribir_json(Path(AJUSTES.datos) / "ajustes.json", {})

# ------------------------------------------------------------ API del canal

r = cliente.get("/api/ajustes/voz")
check("GET /api/ajustes/voz responde 200", r.status_code == 200)
cuerpo = r.json()
check("el GET trae la preferencia y la lista de motores",
      cuerpo["voz"] == {"motor": voz_canal.MOTOR_DEFECTO, "voz": ""}
      and [m["id"] for m in cuerpo["motores"]]
      == list(voz_canal.MOTORES),
      str(cuerpo))

r = cliente.put("/api/ajustes/voz",
                json={"motor": "flash", "voz": "pNInz6obpgDQGcFmaJgB"})
check("PUT /api/ajustes/voz guarda y devuelve saneado",
      r.status_code == 200
      and r.json()["voz"] == {"motor": "flash",
                              "voz": "pNInz6obpgDQGcFmaJgB"},
      str(r.json()))
check("lo guardado por la API es lo que lee el nucleo",
      voz_canal.leer(AJUSTES.datos)["voz"] == "pNInz6obpgDQGcFmaJgB")

r = cliente.put("/api/ajustes/voz", json={"motor": "turbina", "voz": "x"})
check("PUT con motor desconocido → 400", r.status_code == 400,
      str(r.status_code))
r = cliente.put("/api/ajustes/voz", json={})
check("PUT vacío → 400 (falta el motor)", r.status_code == 400,
      str(r.status_code))

# ------------------------------------------------- la siembra y la resolución
#
# El vídeo se crea por la API (siembra real de params) y corre con el
# motor doblado: cada llamada deja la (voz, modelo) que le llegaron.

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})
pid = cliente.post("/api/proyectos",
                   json={"nombre": "Voz del canal"}).json()["id"]
proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
sembrados = (Estado(proyecto).paso("voz") or {}).get("params") or {}
check("crear siembra la voz de FÁBRICA (nunca la del canal)",
      sembrados.get("voz") == voz_canal.VOZ_FABRICA
      and sembrados.get("modelo") == voz_canal.MOTOR_DEFECTO,
      str(sembrados))

# guion de UNA escena en disco: la corrida va por la vía escena a escena
(proyecto.raiz / "pasos" / "guion").mkdir(parents=True, exist_ok=True)
escribir_json(proyecto.raiz / "pasos" / "guion" / "datos.json",
              {"escenas": [{"id": "S001", "titulo": "uno",
                            "narracion": "hola mundo"}]})

llamadas: list[tuple[str, str]] = []


def habla_doblada(texto, voz, destino, **kwargs):
    llamadas.append((voz, kwargs.get("modelo")))
    destino.write_bytes(b"MP3-DE-PRUEBA")
    return {"duracion": 1.0, "palabras": []}


voz_elevenlabs.hablar_con_marcas = habla_doblada
# sin ffprobe en la máquina de pruebas: manda la duración de la marca
p4_voz.comun.duracion_de = lambda ruta: 0.0

p4_voz.ejecutar(proyecto, sembrados, TrabajoMudo())
check("la voz del CANAL se lleva al vídeo que sigue en fábrica",
      llamadas[-1] == ("pNInz6obpgDQGcFmaJgB", "flash"), str(llamadas[-1]))

voz_canal.guardar(AJUSTES.datos, motor="v3", voz="otra-voz-del-canal")
p4_voz.ejecutar(proyecto, sembrados, TrabajoMudo())
check("cambiar la voz en Configuración es vivo en la siguiente corrida",
      llamadas[-1] == ("otra-voz-del-canal", "v3"), str(llamadas[-1]))

p4_voz.ejecutar(proyecto, {"voz": "voz-elegida", "modelo": "v3"},
                TrabajoMudo())
check("lo elegido EN el vídeo manda sobre el canal",
      llamadas[-1] == ("voz-elegida", "v3"), str(llamadas[-1]))

p4_voz.ejecutar(proyecto, {"voz": "voz-elegida",
                           "modelo": voz_canal.MOTOR_DEFECTO},
                TrabajoMudo())
check("voz y motor se resuelen por separado (el motor de fábrica cae en el canal)",
      llamadas[-1] == ("voz-elegida", "v3"), str(llamadas[-1]))

voz_canal.guardar(AJUSTES.datos, motor="flash", voz="")
p4_voz.ejecutar(proyecto, sembrados, TrabajoMudo())
check("canal sin voz: vuelve la de fábrica (y el motor del canal)",
      llamadas[-1] == (voz_canal.VOZ_FABRICA, "flash"), str(llamadas[-1]))

escribir_json(Path(AJUSTES.datos) / "ajustes.json", {})
check("sin preferencia ninguna, la fábrica entera",
      p4_voz._voz_y_motor({}) == (voz_canal.VOZ_FABRICA,
                                  voz_canal.MOTOR_DEFECTO)
      and p4_voz.params_defecto()["voz"] == voz_canal.VOZ_FABRICA)

# la puerta del guion aprobado sigue cerrada aunque el canal tenga voz
r = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar")
check("la voz por la API sigue exigiendo el guion aprobado (409)",
      r.status_code == 409, str(r.status_code))

print()
if fallos:
    print(f"{len(fallos)} FALLO(S): " + ", ".join(fallos))
    sys.exit(1)
print("voz del canal: todo verde")
