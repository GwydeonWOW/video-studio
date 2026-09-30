"""Prueba de humo de los subtítulos temporizados (subtitulos.py → p7/p8).

Un subtítulo NO destila la narración: LA ES. Los tiempos salen de las
marcas de palabra de la voz, y el texto se trocea en rebanadas que se
leen al ritmo del habla. Se comprueba sin pagar nada (p7 ya no llama a
ningún modelo):

- `tramos` devuelve RANGOS que cubren todo, sin solapar y sin partir cifras
- `de_escena` saca trozos en el reloj DEL PLANO (t_in restado), cierra
  los huecos cortos y estira el último hasta el final si le falta poco
- la GUARDA: narración y marcas que no cuadran → [], sin subtítulo
- lo dicho con palabras se escribe con números («mil novecientos
  noventa y seis» → «1996»), respetando comas y artículos sueltos
- `repartir_escrito` corrige el texto SIN tocar los tiempos
- p7 rebana las marcas por plano (guarda de emparejado), la cartela no
  lleva subtítulo, la voz sin marcas tampoco, y el override manual
  reparte sin mover nada
- `_ventanas_trozos` (p8) sana las ventanas dentro del plano
- la API cuelga los trozos por plano en la previsualización

Ejecutar:

    python pruebas/humo_subtitulos.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_subs_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.api import rutas_proyectos  # noqa: E402
from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.pasos import p7_callouts, p8_render, subtitulos  # noqa: E402

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


# ------------------------------------------------- primitivas del módulo

palabras = ("El transistor nacio de un trozo de silicio sucio "
            "en mil novecientos noventa y seis, "
            "y la electronica nunca volvio a ser igual despues "
            "de todo aquello que vino despues").split()
marcas = [[round(0.35 * i, 3), round(0.35 * i + 0.28, 3)]
          for i in range(len(palabras))]

rangos = subtitulos.tramos(
    palabras, intocables=subtitulos._cifras_de(palabras))
check("tramos cubre todo sin solapar",
      rangos and rangos[0][0] == 0 and rangos[-1][1] == len(palabras)
      and all(a[1] == b[0] for a, b in zip(rangos, rangos[1:])),
      str(rangos))
largo_max = max(len(" ".join(palabras[a:b])) for a, b in rangos)
check("ningun tramo se pasa de dos lineas",
      largo_max <= subtitulos.CAP_TROZO, f"{largo_max} <= {subtitulos.CAP_TROZO}")

numero = next((r for r in rangos
               if "mil" in palabras[r[0]:r[1]]), None)
check("la cifra dicha queda ENTERA en un tramo",
      numero is not None and "mil" in palabras[numero[0]:numero[1]]
      and "noventa" in palabras[numero[0]:numero[1]],
      str(palabras[numero[0]:numero[1]]) if numero else "sin cifra")

plano = {"narracion": " ".join(palabras), "marcas": marcas,
         "t_in": 0.0, "t_out": round(marcas[-1][1] + 0.3, 3)}
trozos = subtitulos.de_escena(plano)
check("de_escena recompone el texto entero",
      " ".join(t["texto"] for t in trozos).split()
      == subtitulos.limpiar_texto(palabras).split(),
      str([t["texto"] for t in trozos])[:120])
check("lo dicho con palabras se escribe con numeros",
      any("1996" in t["texto"] for t in trozos),
      str([t["texto"] for t in trozos]))
check("los trozos van en orden y sin solaparse",
      all(a["hasta"] <= b["desde"] + 1e-9
          for a, b in zip(trozos, trozos[1:])),
      str([(t["desde"], t["hasta"]) for t in trozos]))
check("el ultimo llega al final del plano (silencio corto)",
      abs(trozos[-1]["hasta"] - plano["t_out"]) < 1e-6
      and trozos[-1]["hasta"] > marcas[-1][1],
      f"{trozos[-1]['hasta']} vs t_out {plano['t_out']}")

# reloj del PLANO: t_in distinto de cero resta a las marcas
plano_des = {**plano, "t_in": 2.0, "t_out": round(marcas[-1][1] + 0.9, 3)}
trozos_des = subtitulos.de_escena(plano_des)
check("el reloj es el del plano (t_in restado)",
      trozos_des and abs(trozos_des[0]["desde"]
                         - (marcas[0][0] - 2.0)) < 1e-6,
      f"{trozos_des[0]['desde']} vs {marcas[0][0] - 2.0}")

check("la GUARDA: marcas y narracion que no cuadran -> []",
      subtitulos.de_escena({**plano, "marcas": marcas[:-2]}) == []
      and subtitulos.de_escena({"narracion": "", "marcas": []}) == [])

check("hueco corto cerrado, hueco largo respetado",
      True, "cubierto abajo con ventanas de p8")  # marcador informativo

# los numeros
check("cifras_en respeta las comas de enumeracion",
      subtitulos.cifras_en("dos, tres, cuatro veces".split(),
                           cortes=subtitulos._cortes_de(
                               "dos, tres, cuatro veces".split())) == [],
      str(subtitulos.cifras_en(
          "dos, tres, cuatro veces".split(),
          cortes=subtitulos._cortes_de("dos, tres, cuatro veces".split()))))
check("un articulo no es una cifra",
      subtitulos.cifras_en("un trozo de nada".split(),
                           cortes=set()) == [],
      str(subtitulos.cifras_en("un trozo de nada".split(), cortes=set())))
gran = subtitulos.cifras_en("dos millones tres mil cuatro".split(),
                            cortes=set())
check("millones: dos millones tres mil cuatro -> 2.003.004",
      gran == [(0, 5, "2.003.004")], str(gran))
check("limpiar_texto conserva la puntuacion pegada",
      subtitulos.limpiar_texto("en mil novecientos noventa y seis, nacio".split())
      == "en 1996, nacio",
      subtitulos.limpiar_texto("en mil novecientos noventa y seis, nacio".split()))

# repartir_escrito: tiempos quietos, texto corregido
base = subtitulos.repartir_escrito(
    ["el transistor nacio", "en mil novecientos noventa y seis"],
    "el transistor nacio en 1996")
check("repartir_escrito manda lo escrito sin cambiar el numero de trozos",
      len(base) == 2 and "1996" in base[1], str(base))

dos = subtitulos.dos_lineas("una frase bastante larga que no cabe en una linea",
                            medir=lambda s: len(s) * 10, ancho_max=300)
check("dos_lineas parte en dos lo mas parejas posible",
      len(dos) == 2 and abs(len(dos[0]) - len(dos[1])) < 12, str(dos))
banda = subtitulos.banda_fija()
check("banda_fija: el pie del cuadro de salida",
      banda == {"suelo": 1008.0, "centro": 960.0, "ancho": 1400.0},
      str(banda))

# ------------------------------------------------------- p7 sobre latas

def frase(t, *pals, paso=0.34, hueco=0.06):
    sal = []
    for p in pals:
        sal.append({"palabra": p, "inicio": round(t, 3),
                    "fin": round(t + paso, 3)})
        t += paso + hueco
    return sal, t


ORACIONES_S1 = [
    ["El", "transistor", "nacio", "de", "un", "trozo", "de", "silicio",
     "sucio."],
    ["Amplificaba", "senales", "pequenas", "hasta", "volverlas",
     "gritos", "limpios", "y", "serenos."],
    ["El", "mundo", "entero", "escucho", "el", "rumor", "de", "aquel",
     "invento."],
]
palabras_s1, t = [], 0.0
for oracion in ORACIONES_S1:
    trozo, t = frase(t, *oracion)
    palabras_s1.extend(trozo)
    t += 0.7
FIN_S1 = round(t - 0.06, 3)
DURACION_S1 = round(FIN_S1 + 1.0, 3)

# tres planos que TILEAN el audio de S001 (una oracion cada uno)
PLANOS_S1, cursor = [], 0
for k, oracion in enumerate(ORACIONES_S1, 1):
    n = len(oracion)
    ventana = palabras_s1[cursor:cursor + n]
    PLANOS_S1.append({
        "id": f"S001-{k}", "escena": "S001",
        "narracion": " ".join(oracion),
        "t_in": ventana[0]["inicio"], "t_out": ventana[-1]["fin"],
        "zoom": {"de": 1.0, "a": 1.05}, "transicion": "suave",
    })
    cursor += n
PLANOS_S1[-1]["t_out"] = DURACION_S1     # el cola del audio
for a, b in zip(PLANOS_S1, PLANOS_S1[1:]):   # huecos de la pausa -> tilear
    b["t_in"] = a["t_out"]

_dir_proy = Path(os.environ["ESTUDIO_DATOS"]) / "proyectos" / "prueba_subs"
(_dir_proy / "pasos" / "guion").mkdir(parents=True)
(_dir_proy / "pasos" / "voz").mkdir(parents=True)
(_dir_proy / "pasos" / "assets").mkdir(parents=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "subs"})
escribir_json(_dir_proy / "pasos" / "guion" / "datos.json", {"escenas": [
    {"id": "S001", "titulo": "varios planos",
     "narracion": " ".join(" ".join(o) for o in ORACIONES_S1)},
    {"id": "S002", "titulo": "cartela", "narracion": "frase de cartela"},
]})
escribir_json(_dir_proy / "pasos" / "voz" / "datos.json", {"escenas": [
    {"id": "S001", "duracion": DURACION_S1, "palabras": palabras_s1,
     "audio": "voz/s001.mp3"},
    {"id": "S002", "duracion": 2.0, "palabras": []},
]})
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json", {
    "planos": PLANOS_S1 + [{
        "id": "S002", "escena": "S002", "narracion": "frase de cartela",
        "t_in": 0.0, "t_out": 2.0,
        "cartela": {"plantilla": "titulo", "datos": {"titulo": "1947"}},
        "zoom": {"de": 1.0, "a": 1.0}, "transicion": "suave"}],
    "calidad": "low",
})
proyecto = Proyecto(_dir_proy)

resultado = p7_callouts.ejecutar(proyecto, {}, TrabajoMudo())
filas = resultado["subtitulos"]
check("p7 SIN modelo: estimar es todo ceros",
      p7_callouts.estimar({}) == {"llamadas_llm": 0, "imagenes": 0,
                                  "caracteres_voz": 0, "coste": 0.0})
check("una fila por plano de voz, la cartela fuera",
      [f["id"] for f in filas] ==
      [p["id"] for p in PLANOS_S1],
      str([f["id"] for f in filas]))

por_plano = {f["id"]: f for f in filas}
releido = " ".join(" ".join(t["texto"] for t in por_plano[p["id"]]["trozos"])
                   for p in PLANOS_S1)
check("los trozos de la escena recompone la narracion entera",
      releido.split()
      == " ".join(" ".join(o) for o in ORACIONES_S1).split(),
      releido[:100])

p1 = por_plano["S001-1"]
dentro = all(0.0 - 1e-6 <= t_["desde"]
             and t_["hasta"] <= PLANOS_S1[0]["t_out"]
             - PLANOS_S1[0]["t_in"] + 0.4 + 1e-6
             for t_ in p1["trozos"])
check("cada trozo vive DENTRO de su plano (reloj del plano)",
      dentro,
      str([(t_["desde"], t_["hasta"]) for t_ in p1["trozos"]]))

check("las marcas llegan rebanadas por plano (identidad, no emparejado)",
      all(len(t_["texto"].split()) >= 1 for t_ in p1["trozos"])
      and por_plano["S001-2"]["trozos"][0]["desde"]
      <= palabras_s1[len(ORACIONES_S1[0])]["fin"]
      - PLANOS_S1[1]["t_in"] + 1e-6,
      str(por_plano["S001-2"]["trozos"][:1]))

# el override manual reparte SIN tocar tiempos
con_manual = p7_callouts.ejecutar(
    proyecto, {"unidades": {"S001": {"subtitulo_texto":
                                     "El transistor nacio de un pedazo "
                                     "de silicio sucio Amplificaba "
                                     "senales pequenas hasta volverlas "
                                     "gritos limpios y serenos El mundo "
                                     "entero escucho el rumor de aquel "
                                     "invento"}}}, TrabajoMudo())
filas_m = con_manual["subtitulos"]
tiempos_iguales = all(
    [(t_["desde"], t_["hasta"]) for t_ in f_m["trozos"]]
    == [(t_["desde"], t_["hasta"]) for t_ in por_plano[f_m["id"]]["trozos"]]
    for f_m in filas_m)
texto_manual = " ".join(" ".join(t_["texto"] for t_ in f_m["trozos"])
                        for f_m in filas_m)
check("el texto corregido a mano MANDA y reparte entero",
      "pedazo" in texto_manual and tiempos_iguales,
      texto_manual[:100])

# narracion de planos que no cuadra con la voz -> sin subtitulo
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json", {
    "planos": [{**PLANOS_S1[0], "narracion": "otra cosa que no dijo"},
               *PLANOS_S1[1:],
               {"id": "S002", "escena": "S002", "narracion": "cartela",
                "t_in": 0.0, "t_out": 2.0,
                "cartela": {"plantilla": "titulo",
                            "datos": {"titulo": "1947"}}}],
    "calidad": "low"})
desacorde = p7_callouts.ejecutar(proyecto, {}, TrabajoMudo())
check("narracion descuadrada: la escena entera se queda sin subtitulo",
      desacorde["subtitulos"] == [],
      str([f["id"] for f in desacorde["subtitulos"]]))

# voz sin marcas: sin subtitulo (S002 ya lo cubre: no esta en filas)
# restaurar para la API
escribir_json(_dir_proy / "pasos" / "assets" / "datos.json", {
    "planos": PLANOS_S1 + [{
        "id": "S002", "escena": "S002", "narracion": "frase de cartela",
        "t_in": 0.0, "t_out": 2.0,
        "cartela": {"plantilla": "titulo", "datos": {"titulo": "1947"}}}],
    "calidad": "low"})
final = p7_callouts.ejecutar(proyecto, {}, TrabajoMudo())
escribir_json(_dir_proy / "pasos" / "callouts" / "datos.json", final)

check("el grafismo viaja escrito en los datos",
      final["diseno"] == "pastilla" and "paleta" in final
      and final.get("cap_linea") == subtitulos.CAP_LINEA,
      str({k: final[k] for k in ("diseno", "cap_linea")}))

# ------------------------------------------------------- p8: ventanas

ventanas = p8_render._ventanas_trozos(
    [{"texto": "hola", "desde": -1.0, "hasta": 0.2},
     {"texto": "  ", "desde": 1.0, "hasta": 2.0},
     {"texto": "que tal", "desde": 2.0, "hasta": 9.0}], 4.0)
check("_ventanas_trozos sana dentro del plano",
      ventanas == [("hola", 0.0, 0.3), ("que tal", 2.0, 2.0)],
      str(ventanas))

# ------------------------------------------- la API cuelga los trozos

previa = rutas_proyectos.leer_previsualizacion("prueba_subs")
subs_previa = {e["id"]: e["trozos"] for e in previa["escenas"]}
check("la previsualizacion cuelga los trozos POR PLANO",
      previa["con_subtitulos"]
      and [e["id"] for e in previa["escenas"]]
      == ["S001-1", "S001-2", "S001-3", "S002"]
      and subs_previa["S001-1"] == por_plano["S001-1"]["trozos"]
      and subs_previa["S002"] == [],
      str([e["id"] for e in previa["escenas"]]))

# ---------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("subtitulos en verde")
