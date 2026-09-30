"""Prueba de humo del motor de reglas transversales (motores/reglas.py).

Una regla transversal es lo aprendido de un fallo humano en UN vídeo,
destilado para que no vuelva a pasar en NINGUNO. Lo que se comprueba
sin gastar nada:

- el fichero `reglas.json` llega VERBATIM del original (el contenido
  ES la funcionalidad) y vive junto al motor, que lo lee y escribe
- `para` ordena por prioridad y `bloque_prompt` devuelve el párrafo
  (o "" cuando el ámbito no tiene reglas: montaje y voz están vacíos)
- `anadir` rechaza ámbitos desconocidos, sella la fecha, y re-añadir
  un id ACTUALIZA y acumula orígenes en vez de duplicar — y todo sobre
  una COPIA: la prueba jamás escribe el fichero del repo
- las reglas entran donde las demás leyes generales:
  * p6 `prompt_de`: pegadas a la guía (ANTES del Shot type), con la
    línea de dato del idioma al lado («The language of this film
    is Spanish.»), que solo sale cuando el idioma se sabe decir
  * p6 `_capas_catalogo`: las de reparto pegadas a la capa de
    «Characters in frame», y solo si hay quien dibujar
  * moodboard `prompt_de_eje`: igual que un plano (fallo del
    original: los tres cuerpos salieron sonriendo con la regla
    escrita y sin llegar), y «No watermarks.» sigue siendo lo último
- el CLI `listar` (el único que hay) lista por ámbito y cuenta

Ejecutar:

    python -X utf8 pruebas/humo_reglas.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_reglas_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.motores import reglas  # noqa: E402
from app.pasos import moodboard, p2_brief, p6_assets  # noqa: E402

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


# ------------------------------------------------- el fichero de aprendizaje

datos = reglas.cargar()
check("el fichero vive junto al motor y trae lo aprendido",
      Path(reglas.RUTA).parent == Path(reglas.__file__).parent
      and datos.get("version") == 1
      and len(datos.get("reglas", [])) == 18,
      str(len(datos.get("reglas", []))))
ambitos_con_reglas = {r["ambito"] for r in datos["reglas"]}
check("los ámbitos son los del original (y montaje/voz aún vacíos)",
      ambitos_con_reglas <= set(reglas.AMBITOS)
      and ambitos_con_reglas == {"prompt_imagen", "referencias", "reparto",
                                 "blockout", "plan_escenas", "storyboard"},
      str(sorted(ambitos_con_reglas)))

# ------------------------------------------------------------------ lectura

texto = reglas.para("prompt_imagen")
completas = reglas.para("prompt_imagen", como_texto=False)
check("para ordena por prioridad y devuelve el texto de la regla",
      len(texto) >= 4 and all(isinstance(x, str) and x for x in texto)
      and [r["prioridad"] for r in completas]
      == sorted(r["prioridad"] for r in completas),
      f"{len(texto)} reglas de prompt_imagen")
check("bloque_prompt es el párrafo (o '' sin reglas)",
      reglas.bloque_prompt("prompt_imagen") == " ".join(texto)
      and reglas.bloque_prompt("montaje") == ""
      and reglas.bloque_prompt("voz") == "")

# la primera regla del ámbito, para buscarla en los prompts
regla_imagen = texto[0]
regla_reparto = reglas.para("reparto")[0]

# ----------------------------------------------------------------- anadir

# sobre una COPIA: el fichero del repo es aprendizaje y no se toca
_tmp = Path(tempfile.mkdtemp(prefix="estudio_reglas_anadir_"))
_copia = _tmp / "reglas.json"
shutil.copy(reglas.RUTA, _copia)
_antes = Path(reglas.RUTA).read_bytes()
_ruta_de_verdad = reglas.RUTA
reglas.RUTA = str(_copia)
try:
    try:
        reglas.anadir(id="prueba", ambito="inventado", regla="x")
        check("anadir rechaza el ámbito desconocido", False)
    except ValueError:
        check("anadir rechaza el ámbito desconocido", True)
    reglas.anadir(id="regla-de-prueba", ambito="montaje",
                  regla="cortar en la mirada", por_que="porque",
                  origen={"proyecto": "p1", "feedback": "se cortaba tarde"})
    ficha = next(r for r in reglas.cargar()["reglas"]
                 if r["id"] == "regla-de-prueba")
    check("la regla nueva lleva su fecha y su origen",
          ficha["regla"] == "cortar en la mirada"
          and ficha["fecha"] == date.today().isoformat()
          and ficha["origen"]["proyecto"] == "p1")
    reglas.anadir(id="regla-de-prueba", ambito="montaje",
                  regla="cortar en la mirada, siempre",
                  origen={"proyecto": "p2"})
    ficha = next(r for r in reglas.cargar()["reglas"]
                 if r["id"] == "regla-de-prueba")
    check("re-añadir ACTUALIZA y acumula orígenes, no duplica",
          ficha["regla"] == "cortar en la mirada, siempre"
          and ficha["origenes_extra"] == [{"proyecto": "p2"}]
          and sum(1 for r in reglas.cargar()["reglas"]
                  if r["id"] == "regla-de-prueba") == 1)
finally:
    reglas.RUTA = _ruta_de_verdad
check("la prueba no ha tocado el fichero del repo",
      Path(reglas.RUTA).read_bytes() == _antes)

# ------------------------------------------------- p6: el prompt del plano

ESCES = [{"id": "S001", "titulo": "una", "narracion": "hola que tal"}]
con = p6_assets.prompt_de(ESCES[0], {}, {"estilo": "flat cartoon"},
                          carta={"encuadre": "wide establishing shot"},
                          frase="hola", idioma="es")
check("p6: las reglas viajan pegadas al estilo, ANTES del Shot type",
      regla_imagen[:60] in con
      and 0 < con.index(regla_imagen[:60]) < con.index("Shot type:"),
      con[:80])
check("p6: la línea de dato del idioma, pegada a la regla",
      "The language of this film is Spanish." in con
      and con.index("The language of this film is Spanish.")
      < con.index("Shot type:"))
sin_idioma = p6_assets.prompt_de(ESCES[0], {}, {}, frase="hola")
check("p6: sin idioma conocido, la línea no sale (mejor nada que un código)",
      "The language of this film is" not in sin_idioma
      and "The language of this film is" not in p6_assets.prompt_de(
          ESCES[0], {}, {}, frase="hola", idioma="xx"))

# ------------------------------------------------- p6: las reglas de reparto

CATALOGO = {"catalogo": {
    "reparto": {"A1": {"descripcion": "a woman in a red coat"}},
    "sets": {"casa": {"descripcion": "a small kitchen",
                      "luz": "morning light through one window"}},
    "beats": [{"desde": "S001", "hasta": "S001", "set": "casa",
               "personajes": ["A1"], "tono": "calm", "accion": "she waits"}],
}}
con_catalogo = p6_assets.prompt_de(ESCES[0], {}, CATALOGO,
                                   carta={"encuadre": "medium shot"},
                                   frase="hola", idioma="es")
check("p6: las de reparto van PEGADAS a «Characters in frame»",
      "Characters in frame" in con_catalogo
      and regla_reparto[:60] in con_catalogo
      and 0 < con_catalogo.index("Characters in frame")
      < con_catalogo.index(regla_reparto[:60]))
sin_gente = dict(CATALOGO)
sin_gente["catalogo"] = {**CATALOGO["catalogo"],
                         "beats": [{"desde": "S001", "hasta": "S001",
                                    "set": "casa", "personajes": []}]}
vacio = p6_assets.prompt_de(ESCES[0], {}, sin_gente, frase="hola")
check("p6: sin nadie en cuadro no viaja el bloque de reparto",
      "Characters in frame" not in vacio
      and regla_reparto[:60] not in vacio)

# ------------------------------------------------- moodboard: como un plano

FICHA_GUIA = {"guia": "Flat vector cartoon, 3px uniform black outline, "
                      "four flat tones per surface.", "evitar": "gradients"}
lam = moodboard.prompt_de_eje("cara", FICHA_GUIA, peticion="thinner arms",
                              idioma="en")
check("moodboard: las reglas van en la lámina igual que en un plano",
      regla_imagen[:60] in lam
      and lam.index("Correction, this takes priority:")
      < lam.index(regla_imagen[:60])
      and "The language of this production is English." in lam,
      lam[:80])
check("moodboard: «No watermarks.» sigue siendo lo último",
      lam.rstrip().endswith("No watermarks."))

# ------------------------------------------------------------- el nombre EN

check("nombre_idioma_en: la tabla única, y '' si no se sabe decir",
      p2_brief.nombre_idioma_en("es") == "Spanish"
      and p2_brief.nombre_idioma_en("EN") == "English"
      and p2_brief.nombre_idioma_en("fr") == ""
      and p2_brief.nombre_idioma_en("") == "")

# ------------------------------------------------------------------ el CLI

salida = io.StringIO()
try:
    sys.argv = ["reglas.py", "listar"]
    with redirect_stdout(salida):
        reglas.main()
except SystemExit as e:
    check("CLI listar: argparse termina limpio", e.code in (0, None))
listado = salida.getvalue()
check("CLI listar: por ámbitos, con el origen del feedback y el total",
      "=== prompt_imagen ===" in listado
      and "=== reparto ===" in listado
      and "[hora-del-dia-explicita]" in listado
      and listado.rstrip().endswith(f"{len(datos['reglas'])} reglas"))
salida = io.StringIO()
sys.argv = ["reglas.py", "listar", "--ambito", "reparto"]
with redirect_stdout(salida):
    reglas.main()
solo = salida.getvalue()
check("CLI listar --ambito: solo las de ese ámbito",
      "=== reparto ===" in solo and "prompt_imagen" not in solo
      and solo.rstrip().endswith(
          f"{len(reglas.para('reparto', como_texto=False))} reglas"))
sys.argv = [sys.argv[0]]

# ---------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("reglas en verde")
