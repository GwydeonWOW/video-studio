"""Prueba de humo del corrector de planos: la nota -> encargo.

Cuando alguien rechaza una imagen con una nota, el corrector (un agente
que MIRA la imagen rechazada) la convierte en {alcance, personajes,
escena, referencias ORDENADAS con qué copiar de cada una, porque} y el
encargo se redacta con eso encima. Aquí el LLM va doblado (responde lo
que la suite le mete en RESPUESTA) y las imágenes son PNG de nada:

- `corrector.preparar` normaliza y VALIDA contra el inventario: alcance
  raro -> retoque, personajes solo del reparto y sin repetir, referencias
  que citan claves que no existen fuera, la imagen rechazada viaja
  ADJUNTA a la llamada (vision) solo si existe
- los caminos de fallo devuelven {"error"}: sin nota, sin inventario,
  agente que no contesta, respuesta que no es un objeto
- el inventario de la nota: la rechazada, los VECINOS (a tope de
  corrector.VECINOS, con su mismo_set) y el reparto; el vecino lejano no
  entra
- `prompt_de` con correccion: la descripcion del agente SUSTITUYE a la
  capa visual, sus personajes a los del beat, sus referencias entran
  como lineas «Reference: ...» y su alcance manda sobre la ultima nota;
  sin agente, la nota viaja pegada al final como siempre
- el guardián de planos repetidos tumba la tanda si dos planos acaban
  con la MISMA imagen (huella) o el MISMO encargo — salvo la
  continuacion (sigue_a), que es identica A PROPOSITO
- la semilla de params llega al reparto de cartas y al resultado
- las cadenas por set: dos sitios -> dos cadenas dentro de la tanda, el
  orden del vídeo se conserva y no se pierde ninguna operacion de gasto
- en `ejecutar`, la nota de la unidad pasa por el agente (imagen
  rechazada adjunta, encargo previo delante) y `corrector: "no"` lo
  apaga

Ejecutar:

    python pruebas/humo_corrector.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_corrector_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.motores import imagen_glm, llm  # noqa: E402
from app.motores.guion import segmentar  # noqa: E402
from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.pasos import catalogo_visual, corrector, encuadres, p6_assets  # noqa: E402

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


class TrabajoMudo:
    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass


# ------------------------------------------- dobles: LLM que obedece

RESPUESTA: dict = {}
LLAMADAS: list[dict] = []
_llamar_real = llm.llamar_json


def doble_llamar(llamada, **_):
    LLAMADAS.append({"imagenes": list(getattr(llamada, "imagenes", []) or []),
                     "instruccion": str(llamada.instruccion or "")})
    if RESPUESTA == "REVIENTA":
        raise RuntimeError("el agente se ha ido a la playa")
    return RESPUESTA


llm.llamar_json = doble_llamar

# --------------------------------------------- dobles: imágenes gratis

GENERADOR: dict = {"modo": "hash", "contador": 0, "encargos": []}
_cerrojo = threading.Lock()
_generar_real, _clave_real = imagen_glm.generar, imagen_glm.clave
_anotar_real = p6_assets.anotar_operacion
ANOTADAS: list[str] = []


def generar_falso(encargo, destino, **_):
    with _cerrojo:
        GENERADOR["contador"] += 1
        GENERADOR["encargos"].append(encargo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if GENERADOR["modo"] == "constante":
        destino.write_bytes(b"\x89PNG\r\n\x1a\nlaton")
    else:
        destino.write_bytes(b"\x89PNG\r\n\x1a\n" + hashlib.sha256(
            encargo.encode("utf-8")).digest())


def anotar_falsa(**kwargs):
    with _cerrojo:
        ANOTADAS.append(str(kwargs.get("contexto")))


imagen_glm.clave = lambda *a, **k: True
imagen_glm.generar = generar_falso
p6_assets.anotar_operacion = anotar_falsa

# ------------------------------------------------ corrector.preparar

CATALOGO = {"reparto": {"A1": {"descripcion": "hombre de gafas redondas"},
                        "B2": {"descripcion": "mujer de mono azul"}},
            "sets": {"taller": {"descripcion": "banco de trabajo",
                                 "luz": "luz de ventana"}}}
INVENTARIO = [
    {"clave": "rechazada", "que": "la imagen actual", "clase": "rechazada"},
    {"clave": "S002", "que": "el plano vecino", "clase": "continuidad",
     "mismo_set": True},
    {"clave": "reparto:A1", "que": "como es A1", "clase": "reparto",
     "nombre": "A1"},
]
ESCENA = {"id": "S001-1", "narracion": "el transistor nacio",
          "set": "taller", "personajes": ["A1"], "prompt": "old prompt",
          "encuadre": "medium shot"}

RESPUESTA = {"alcance": "RETOQUE ", "personajes": ["A1", "FANTASMA", "A1"],
             "escena": "SAME COMPUTER on the central desk.",
             "referencias": [
                 {"clave": "rechazada", "detalle": "keep the desk"},
                 {"clave": "no-existe", "detalle": "claves falsas fuera"},
                 {"clave": "rechazada", "detalle": "duplicada fuera"},
                 {"detalle": "sin clave fuera"},
                 "no soy un dict"],
             "porque": "mire la imagen"}
LLAMADAS.clear()
salida = corrector.preparar("que el ordenador sea el de antes", ESCENA,
                            CATALOGO, "flat cartoon", INVENTARIO,
                            imagen_actual="C:/algo/S001-1.png")
check("preparar normaliza el alcance raro a retoque",
      salida.get("alcance") == "retoque", str(salida.get("alcance")))
check("preparar filtra personajes al reparto y no repite",
      salida.get("personajes") == ["A1"], str(salida.get("personajes")))
check("preparar valida las referencias contra el inventario",
      [r["clave"] for r in salida.get("referencias") or []] == ["rechazada"],
      str(salida.get("referencias")))
check("la referencia conserva su clase y gana el detalle del agente",
      salida["referencias"][0]["clase"] == "rechazada"
      and salida["referencias"][0]["detalle"] == "keep the desk",
      str(salida.get("referencias")))
check("la imagen rechazada viaja ADJUNTA a la llamada (vision)",
      LLAMADAS and LLAMADAS[0]["imagenes"] == ["C:/algo/S001-1.png"],
      str(LLAMADAS[0]["imagenes"]) if LLAMADAS else "sin llamadas")
check("el encargo anterior viaja en la instruccion del agente",
      LLAMADAS and "old prompt" in LLAMADAS[0]["instruccion"])

LLAMADAS.clear()
corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("sin imagen_actual la llamada no adjunta nada",
      LLAMADAS and LLAMADAS[0]["imagenes"] == [])
RESPUESTA = {"alcance": "cualquier cosa", "escena": "x"}
salida = corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("un alcance desconocido cae en retoque",
      salida.get("alcance") == "retoque")
RESPUESTA = {"alcance": "sustituye", "escena": "otra cosa"}
salida = corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("el alcance sustituye pasa tal cual",
      salida.get("alcance") == "sustituye")

for nombre, args in [
        ("sin nota", ("", ESCENA, CATALOGO, "", INVENTARIO)),
        ("sin inventario", ("nota", ESCENA, CATALOGO, "", []))]:
    salida = corrector.preparar(*args)
    check(f"camino de error: {nombre} devuelve error",
          bool(salida.get("error")), str(salida))
RESPUESTA = "REVIENTA"
salida = corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("agente que revienta devuelve error (y quien llama sigue)",
      bool(salida.get("error")), str(salida))
RESPUESTA = ["no", "soy", "un", "dict"]
salida = corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("respuesta que no es un objeto devuelve error",
      bool(salida.get("error")), str(salida))
RESPUESTA = {"alcance": "retoque", "escena": ""}
salida = corrector.preparar("nota", ESCENA, CATALOGO, "", INVENTARIO)
check("sin descripcion del plano nuevo devuelve error",
      bool(salida.get("error")), str(salida))

# ------------------------------------ el inventario de la nota (_p6)

_dir_inv = Path(tempfile.mkdtemp(prefix="estudio_corrector_inv_"))
for pid in ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"):
    (_dir_inv / f"{pid}.png").write_bytes(b"\x89PNG" + pid.encode())
planos_inv = [{"id": f"P{k}", "escena": "S001", "narracion": f"frase {k}",
               "imagen": f"pasos/assets/imagenes/P{k}.png"}
              for k in range(9)]
params_inv = {"catalogo": {
    "beats": [{"desde": "S001", "hasta": "S001", "set": "taller"}],
    "reparto": {"A1": {"descripcion": "gafas redondas"}}}}
fichas = p6_assets._inventario_para_nota(planos_inv[4], planos_inv,
                                         params_inv, _dir_inv)
claves = [f["clave"] for f in fichas]
check("el inventario lleva la rechazada, los vecinos y el reparto",
      "rechazada" in claves and "P1" in claves and "reparto:A1" in claves,
      str(claves))
check("el vecino a tope de VECINOS entra y el lejano no",
      "P1" in claves and "P0" not in claves,
      f"VECINOS={corrector.VECINOS}")
vecino = next(f for f in fichas if f["clave"] == "P5")
check("el vecino sabe si es del mismo set", vecino.get("mismo_set") is True,
      str(vecino))
check("la ficha del reparto lleva su nombre",
      next(f for f in fichas if f["clave"] == "reparto:A1").get("nombre")
      == "A1")

# ------------------------------- prompt_de con la correccion encima

ESCENA_P = {"id": "S001", "narracion": "el transistor nacio de un silicio",
            "visual": "un taller con luz de ventana"}
UNIDADES = {"S001": {"feedback": [{"texto": "el mismo ordenador que antes"}]}}
CORREGIDO = {"alcance": "retoque", "personajes": ["A1"],
             "escena": "SAME COMPUTER on the central desk.",
             "referencias": [{"clave": "rechazada", "clase": "rechazada",
                              "detalle": "keep the desk and the window"}]}
encargo = p6_assets.prompt_de(ESCENA_P, UNIDADES, params_inv,
                              frase="el transistor nacio",
                              correccion=CORREGIDO)
check("la descripcion del agente sustituye a la capa visual",
      "SAME COMPUTER" in encargo and "un taller con luz" not in encargo,
      encargo[:120])
check("las referencias entran como lineas con su clase y su detalle",
      any(l.startswith("Reference:") and "keep the desk and the window" in l
          for l in encargo.split("\n")), encargo)
check("el alcance del agente manda en la ultima nota",
      "Correction: LOCALIZED fix" in encargo
      and "el mismo ordenador que antes" in encargo)
encargo_solo = p6_assets.prompt_de(ESCENA_P, UNIDADES, params_inv,
                                   frase="el transistor nacio")
check("los personajes del agente sustituyen a los del beat en las capas",
      "gafas redondas" in encargo and "gafas redondas" not in encargo_solo,
      encargo[-200:])
check("sin agente la nota viaja pegada al final como siempre",
      "Correction: Replace the subject" in encargo_solo
      and "el mismo ordenador que antes" in encargo_solo
      and "un taller con luz" in encargo_solo)
check("_corrector_activo se apaga con corrector: no",
      not p6_assets._corrector_activo({"corrector": "no"})
      and p6_assets._corrector_activo({})
      and not p6_assets._corrector_activo({"corrector": "NO"}))

# ------------------------------------------ el guardian, a pie de calle

_dir_gua = Path(tempfile.mkdtemp(prefix="estudio_corrector_gua_"))
(_dir_gua / "A.png").write_bytes(b"gemelo")
(_dir_gua / "B.png").write_bytes(b"gemelo")
(_dir_gua / "C.png").write_bytes(b"distinta")
gemelos = [{"id": "A", "imagen": "a", "prompt": "uno"},
           {"id": "B", "imagen": "b", "prompt": "dos"}]
check("dos huellas iguales son un grupo",
      p6_assets._planos_repetidos(gemelos, _dir_gua) == [["A", "B"]])
check("la continuacion (sigue_a) es identica A PROPOSITO: no cuenta",
      p6_assets._planos_repetidos(
          [gemelos[0], {"id": "B", "imagen": "b", "prompt": "dos",
                        "sigue_a": "A"}], _dir_gua) == [])
check("un plano copiado por id no cuenta",
      p6_assets._planos_repetidos(gemelos, _dir_gua, copiados={"B"}) == [])
(_dir_gua / "A.png").write_bytes(b"distinta-A")
(_dir_gua / "B.png").write_bytes(b"distinta-B")
check("dos encargos identicos son un grupo aunque el fichero difiera",
      p6_assets._planos_repetidos(
          [{"id": "A", "imagen": "a", "prompt": "igual"},
           {"id": "B", "imagen": "b", "prompt": "igual"}], _dir_gua)
      == [["A", "B"]])
check("la cartela sin imagen no entra",
      p6_assets._planos_repetidos(
          [{"id": "A", "imagen": "a", "prompt": "(cartela)"},
           {"id": "B", "imagen": None, "prompt": "(cartela)"}], _dir_gua)
      == [])

# ------------------------------------------------ el proyecto de latas


def _frase(t, *palabras, paso=0.30, hueco=0.05):
    sal = []
    for p in palabras:
        sal.append({"palabra": p, "inicio": round(t, 3),
                    "fin": round(t + paso, 3)})
        t += paso + hueco
    return sal, t


PALABRAS_S1 = [
    ["El", "transistor", "nacio", "de", "un", "trozo", "de", "silicio",
     "sucio."],
    ["Amplificaba", "senales", "pequenas", "hasta", "volverlas",
     "gritos", "limpios."],
    ["El", "mundo", "entero", "escucho", "el", "rumor"],
    ["Y", "la", "electronica", "nunca", "volvio", "a", "ser", "igual."],
]
palabras_s1, t = [], 0.0
for oracion in PALABRAS_S1:
    trozo, t = _frase(t, *oracion)
    palabras_s1.extend(trozo)
    t += 0.65
DURACION_S1 = round(t - 0.05 + 1.2, 3)

_dir_proy = Path(_dir_datos) / "proyectos" / "prueba_corrector"
for sub in ("guion", "voz", "assets/imagenes"):
    (_dir_proy / "pasos" / sub).mkdir(parents=True, exist_ok=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "corrector"})
escribir_json(_dir_proy / "pasos" / "guion" / "datos.json", {"escenas": [
    {"id": "S001", "titulo": "varios planos",
     "narracion": " ".join(" ".join(o) for o in PALABRAS_S1),
     "visual": "un taller con luz de ventana"},
    {"id": "S002", "titulo": "corto",
     "narracion": "frase corta", "visual": "una mesa"},
    {"id": "S003", "titulo": "sin marcas",
     "narracion": "escena sin marcas de palabra", "visual": "plano fijo"},
]})
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": DURACION_S1, "palabras": palabras_s1},
    {"id": "S002", "duracion": 2.1, "palabras": []},
    {"id": "S003", "duracion": 5.0},
]})
proyecto = Proyecto(_dir_proy)

CATALOGO_PARAMS = {"catalogo": {
    "beats": [{"desde": "S001", "hasta": "S001", "set": "taller"},
              {"desde": "S002", "hasta": "S003", "set": "oficina"}],
    "reparto": {"A1": {"descripcion": "hombre de gafas redondas"}},
    "sets": {"taller": {"descripcion": "banco de trabajo",
                         "luz": "luz de ventana"},
             "oficina": {"descripcion": "oficina amortiguada",
                          "luz": "neon"}}}}

# cadenas por set: dos sitios -> dos cadenas, orden y gasto intactos
GENERADOR.update(modo="hash", contador=0, encargos=[])
ANOTADAS.clear()
resultado = p6_assets.ejecutar(proyecto, dict(CATALOGO_PARAMS,
                                              semilla=7), TrabajoMudo())
ids = [p["id"] for p in resultado["planos"]]
check("con dos sitios la tanda acaba en orden de video",
      ids == sorted(ids, key=lambda x: (x.split("-")[0],
                                        int(x.split("-")[1])
                                        if "-" in x else 0)),
      str(ids))
check("todas las imagenes pagadas y anotadas (nada se pierde entre cadenas)",
      GENERADOR["contador"] == len(ids)
      and len(ANOTADAS) == len(ids)
      and all(p.get("imagen") for p in resultado["planos"]),
      f"generadas {GENERADOR['contador']}, anotadas {len(ANOTADAS)}, "
      f"planos {len(ids)}")
check("la semilla del reparto llega al resultado como entero estable",
      isinstance(resultado.get("semilla"), int)
      and resultado["semilla"] == p6_assets.comun.desempatar(7, proyecto.id),
      str(resultado.get("semilla")))

# el guardian tumba la tanda con dos ficheros identicos
GENERADOR.update(modo="constante", contador=0, encargos=[])
try:
    p6_assets.ejecutar(proyecto, dict(CATALOGO_PARAMS), TrabajoMudo())
    check("el guardian tumba la tanda si dos planos son identicos", False,
          "no ha saltado")
except RuntimeError as fallo:
    check("el guardian tumba la tanda si dos planos son identicos",
          "MISMA imagen" in str(fallo)
          and any(p in str(fallo) for p in ("S001-1", "S001-2")),
          str(fallo)[:160])

# la semilla de params manda en el reparto de cartas
_repartir_real = encuadres.repartir
visto: dict = {}


def repartir_espiado(*a, **k):
    visto.update(k)
    return _repartir_real(*a, **k)


encuadres.repartir = repartir_espiado
GENERADOR.update(modo="hash", contador=0, encargos=[])
p6_assets.ejecutar(proyecto, {"semilla": 7}, TrabajoMudo())
encuadres.repartir = _repartir_real
check("la semilla de params llega al reparto de cartas",
      visto.get("semilla") == "7", str(visto.get("semilla")))

# la nota de la unidad pasa por el agente dentro de ejecutar
carpeta = proyecto.carpeta_paso("assets") / "imagenes"
previos = []
for k in range(1, 7):
    pid = f"S001-{k}"
    (carpeta / f"{pid}.png").write_bytes(b"\x89PNG previo " + pid.encode())
    previos.append({"id": pid, "escena": "S001",
                    "narracion": f"previo {k}",
                    "imagen": f"pasos/assets/imagenes/{pid}.png",
                    "prompt": f"OLD PROMPT {k}"})
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json",
              {"planos": previos})
RESPUESTA = {"alcance": "retoque", "personajes": ["A1"],
             "escena": "SAME COMPUTER on the central desk.",
             "referencias": [{"clave": "rechazada",
                              "detalle": "keep the desk"}],
             "porque": "mire la imagen"}
LLAMADAS.clear()
GENERADOR.update(modo="hash", contador=0, encargos=[])
unidades = {"S001": {"feedback": [{"texto": "el mismo ordenador"}]}}
resultado = p6_assets.ejecutar(
    proyecto, {"unidades": unidades, **CATALOGO_PARAMS}, TrabajoMudo(),
    solo_escenas=["S001"])
ids_s1 = [str(p["id"]) for p in resultado["planos"]]
check("con nota y regeneracion, el agente lee cada plano de la escena",
      len(LLAMADAS) == len(ids_s1) and len(ids_s1) >= 3,
      f"{len(LLAMADAS)} llamadas, planos {ids_s1}")
check("la imagen rechazada del disco viaja adjunta al agente",
      len(LLAMADAS) == len(ids_s1)
      and all(ll["imagenes"] == [str(carpeta / f"{pid}.png")]
              for pid, ll in zip(ids_s1, LLAMADAS)),
      str([ll["imagenes"] for ll in LLAMADAS]))
check("el agente ve el encargo con el que se dibujo (la pasada anterior)",
      all(f"OLD PROMPT {pid.split('-')[-1]}" in ll["instruccion"]
          for pid, ll in zip(ids_s1, LLAMADAS)))
check("el encargo final lleva correccion, referencia y descripcion nuevas",
      all("Correction: LOCALIZED fix" in e and "Reference:" in e
          and "SAME COMPUTER" in e for e in GENERADOR["encargos"]),
      GENERADOR["encargos"][0][-200:] if GENERADOR["encargos"] else "nada")

# corrector: "no" lo apaga (la nota viaja pegada, sin agente)
RESPUESTA = {}
LLAMADAS.clear()
GENERADOR.update(modo="hash", contador=0, encargos=[])
p6_assets.ejecutar(proyecto, {"unidades": unidades, "corrector": "no",
                              **CATALOGO_PARAMS}, TrabajoMudo(),
                   solo_escenas=["S001"])
check("corrector: no apaga al agente y la nota viaja pegada",
      not LLAMADAS
      and all("Correction: Replace the subject" in e
              for e in GENERADOR["encargos"]),
      f"{len(LLAMADAS)} llamadas")

print()
if fallos:
    print(f"corrector en ROJO: {len(fallos)} fallo(s)")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)
print("corrector en verde")
