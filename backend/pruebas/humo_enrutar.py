"""Prueba de humo del reparto de estilo, la obsolescencia por unidad y la reescritura encadenada.

Tres piezas que comparten una regla («lo barato primero, y que se vea»):

- `pasos/enrutar_estilo`: el vocabulario CERRADO de retoques. `_limpiar`
  valida lo que el modelo contesta (un retoque inventado, un valor que
  no está en la lista, un eje que no existe, una lámina sin petición ->
  RESPALDO: rehacer el estilo entero, que es lo de siempre), y las
  derivadas (params/láminas/imágenes/tareas/resumen) reparten sin
  inventar nada: `muestra` entra siempre que entra algo, dos láminas
  sueltas son DOS imágenes, `dibujo` + una suelta son SEIS (no siete).
  `repartir` con la frase vacía no llama al modelo, y un modelo caído
  cae al respaldo con aviso — nunca revienta.
- el mando `subtitulo_caja`: `grafismo.con_opacidad` reescribe SOLO el
  velo (el acento queda), `p7_callouts.opacidad_de_caja` traduce "auto"
  a None, y los params por defecto lo traen.
- la obsolescencia POR UNIDAD (`nucleo/estado.py`): corregir S002
  ensucia S002 en los pasos por unidad de aguas abajo y NO el render ni
  las otras escenas; rehacer la unidad (completar con `hechas`) limpia
  SOLO esa; y volver a marcar RETIRA el «vale» que hubiera.
- la cadena de la revisión de audio (`rutas_proyectos._correr_cadena`):
  comentario -> texto nuevo -> voz nueva en un gesto. Con reescritura
  que no cambia nada NO se regraba (pagar ElevenLabs por una copia), y
  con reescritura buena la escena entra en el guion en su sitio, la voz
  sube versión con `hechas=[escena]` y la marca baja a revision_audio.

Ejecutar:

    python pruebas/humo_enrutar.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_enrutar_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.api import rutas_proyectos  # noqa: E402
from app.motores import llm  # noqa: E402
from app.nucleo import grafismo  # noqa: E402
from app.nucleo.estado import Estado  # noqa: E402
from app.nucleo.proyecto import (Proyecto, escribir_json,  # noqa: E402
                                 leer_json)
from app.pasos import (enrutar_estilo, marcas_tts,  # noqa: E402
                       p4_voz, p5_revision_audio, p7_callouts)

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


# --------------------------------------------- dobles: los dos motores LLM

RESPUESTA_JSON: object = {}
RESPUESTA_TEXTO = ""
LLAMADAS_JSON = 0

_json_real = llm.llamar_json
_texto_real = llm.llamar


def doble_json(llamada, **_):
    global LLAMADAS_JSON
    LLAMADAS_JSON += 1
    if RESPUESTA_JSON == "REVIENTA":
        raise llm.ErrorLLM("el enrutador se ha ido a la playa")
    return RESPUESTA_JSON


def doble_texto(llamada, **_):
    if RESPUESTA_TEXTO == "REVIENTA":
        raise llm.ErrorLLM("el corrector se ha ido a la playa")
    return RESPUESTA_TEXTO


llm.llamar_json = doble_json
llm.llamar = doble_texto

# ------------------------------------------------ _limpiar: el vocabulario

RESPUESTA_JSON = {"retoques": [{"retoque": "caja_subtitulo", "valor": "0,6",
                                "porque": "pq"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("un retoque valido con coma decimal pasa",
      len(retoques) == 1 and retoques[0]["valor"] == 0.6 and not avisos,
      str(retoques))

RESPUESTA_JSON = {"retoques": [{"retoque": "no_existe"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("retoque inventado -> respaldo con aviso",
      retoques == [] and avisos and "no existe" in avisos[0], str(avisos))

RESPUESTA_JSON = {"retoques": [{"retoque": "set_grafismo",
                                "valor": "neon"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("valor fuera de la lista -> respaldo (un valor inventado es un "
      "param que nadie lee)",
      retoques == [] and avisos, str(avisos))

RESPUESTA_JSON = {"retoques": [{"retoque": "caja_subtitulo",
                                "valor": "medio"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("valor no numerico -> respaldo", retoques == [] and avisos)

RESPUESTA_JSON = {"retoques": [{"retoque": "una_referencia",
                                "eje": "nave", "peticion": "mas luz"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("eje que no es ninguna de las seis -> respaldo",
      retoques == [] and avisos, str(avisos))

RESPUESTA_JSON = {"retoques": [{"retoque": "una_referencia",
                                "eje": "cuerpos"}]}
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("lamina sin peticion -> respaldo (redibujarla con nada sale igual: "
      "la tarea correria y lo pedido no estaria en ningun sitio)",
      retoques == [] and avisos, str(avisos))

RESPUESTA_JSON = ["no", "soy", "un", "dict"]
retoques, avisos = enrutar_estilo._limpiar(RESPUESTA_JSON)
check("respuesta sin forma de reparto -> respaldo",
      retoques == [] and avisos)

# -------------------------------------------- las derivadas del reparto

UNA = {"retoque": "una_referencia", "eje": "cuerpos",
       "peticion": "vestidos distintos", "tareas": ("referencias",
                                                     "muestra"),
       "imagenes": 1}
DOS = {**UNA, "eje": "cara", "peticion": "menos perfil"}
CAJA = {"retoque": "caja_subtitulo", "valor": 0.6,
        "tareas": ("grafismo", "muestra"), "imagenes": 0}
DIBUJO = {"retoque": "dibujo", "tareas": ("guia", "referencias",
                                          "grafismo", "muestra"),
          "imagenes": 6}

check("params_de escribe el cajon que alguien lee",
      enrutar_estilo.params_de(
          [CAJA, {"retoque": "tamano_subtitulo", "valor": "grande",
                  "tareas": (), "imagenes": 0},
           {"retoque": "set_grafismo", "valor": "barra",
            "tareas": (), "imagenes": 0}])
      == {"callouts": {"subtitulo_caja": 0.6, "subtitulo_tam": "grande",
                       "diseno": "barra"}},
      str(enrutar_estilo.params_de([CAJA])))
check("dibujo y una_referencia no escriben params",
      enrutar_estilo.params_de([DIBUJO, UNA]) == {})

check("laminas_de recoge la lamina suelta",
      enrutar_estilo.laminas_de([UNA]) == {"cuerpos": "vestidos distintos"})
check("la misma lamina dos veces suma sus peticiones, no las pisa",
      enrutar_estilo.laminas_de(
          [UNA, {**UNA, "peticion": "menos traje"}])
      == {"cuerpos": "vestidos distintos; menos traje"},
      str(enrutar_estilo.laminas_de([UNA, {**UNA, "peticion": "menos traje"}])))
check("dibujo pide las seis: la suelta sobra y no se pierde a medias",
      enrutar_estilo.laminas_de([UNA, DIBUJO]) == {})

check("dos laminas sueltas son DOS imagenes (no un max)",
      enrutar_estilo.imagenes_de([UNA, DOS]) == 2)
check("dibujo + una suelta son SEIS (no siete)",
      enrutar_estilo.imagenes_de([UNA, DIBUJO]) == 6)
check("solo params no paga imagenes",
      enrutar_estilo.imagenes_de([CAJA]) == 0)

check("muestra entra siempre que entra algo, en el orden de siempre",
      enrutar_estilo.tareas_de([CAJA]) == ("grafismo", "muestra")
      and enrutar_estilo.tareas_de([UNA]) == ("referencias", "muestra"),
      str(enrutar_estilo.tareas_de([CAJA])))
check("sin_mando no corre nada",
      enrutar_estilo.tareas_de(
          [{"retoque": "sin_mando", "porque": "no hay mando",
            "tareas": (), "imagenes": 0}]) == ())
check("reparto vacio es el respaldo (las cuatro)",
      enrutar_estilo.tareas_de([]) == ("guia", "referencias", "grafismo",
                                       "muestra"))

resumen = enrutar_estilo.resumen_de(
    [{"retoque": "sin_mando", "porque": "el logo no se toca aqui"}])
check("el resumen de sin_mando dice el porque",
      resumen == "el logo no se toca aqui", resumen)
resumen = enrutar_estilo.resumen_de([CAJA])
check("el resumen del mando barato dice ninguna imagen",
      resumen == "se toca caja subtitulo = 0.6 · ninguna imagen", resumen)
resumen = enrutar_estilo.resumen_de([UNA])
check("el resumen de la lamina nombra su titulo legible",
      "de cuerpo entero" in resumen and "1 imagen" in resumen, resumen)

# ------------------------------------------------------- repartir entero

LLAMADAS_JSON = 0
salida = enrutar_estilo.repartir("")
check("frase vacia: sin llamada al modelo y respaldo entero",
      LLAMADAS_JSON == 0 and salida["tareas"] == ("guia", "referencias",
                                                  "grafismo", "muestra")
      and salida["retoques"] == [] and "sin nada escrito" in salida["resumen"],
      str(salida["resumen"]))

RESPUESTA_JSON = "REVIENTA"
salida = enrutar_estilo.repartir("baja la caja del subtitulo")
check("enrutador caido -> respaldo con aviso, sin reventar",
      salida["tareas"] == ("guia", "referencias", "grafismo", "muestra")
      and salida["retoques"] == [] and salida["avisos"], str(salida["avisos"]))

RESPUESTA_JSON = {"retoques": [{"retoque": "caja_subtitulo",
                                "valor": "0,6", "porque": "es la caja"}]}
salida = enrutar_estilo.repartir("baja la caja del subtitulo")
check("reparto valido: params escritos, tareas justas, cero imagenes",
      salida["params"] == {"callouts": {"subtitulo_caja": 0.6}}
      and salida["tareas"] == ("grafismo", "muestra")
      and salida["imagenes"] == 0 and not salida["avisos"],
      str(salida))

RESPUESTA_JSON = {"retoques": [{"retoque": "sin_mando",
                                "porque": "el logo va en el montage"}]}
salida = enrutar_estilo.repartir("pon el logo en la esquina")
check("sin_mando: tareas vacias y el porque en el resumen",
      salida["tareas"] == () and salida["resumen"] == salida["retoques"][0]
      .get("porque") and salida["params"] == {} and salida["imagenes"] == 0,
      str(salida))

check("describir cita el rol enrutador",
      "enrutador" in enrutar_estilo.describir()
      or "glm" in enrutar_estilo.describir(), enrutar_estilo.describir())

# --------------------------------------------- el mando subtitulo_caja

paleta = grafismo.con_opacidad(grafismo.PALETA_DEFECTO, 0.5)
check("con_opacidad reescribe SOLO la alfa del velo",
      paleta["velo"] == "rgba(10,12,16,0.5)"
      and paleta["acento"] == grafismo.PALETA_DEFECTO["acento"],
      str(paleta))
check("con_opacidad recorta el exceso a 1",
      grafismo.con_opacidad({}, 1.5)["velo"].endswith(",1.0)"))
check("con_opacidad con auto deja la paleta tal cual",
      grafismo.con_opacidad(grafismo.PALETA_DEFECTO, "auto")
      == grafismo.PALETA_DEFECTO)

check("opacidad_de_caja traduce auto a None",
      p7_callouts.opacidad_de_caja({"subtitulo_caja": "auto"}) is None
      and p7_callouts.opacidad_de_caja({}) is None
      and p7_callouts.opacidad_de_caja(
          {"subitulo_caja": 0.4}) is None)
check("opacidad_de_caja lee el numero y lo acota",
      p7_callouts.opacidad_de_caja({"subtitulo_caja": 0.4}) == 0.4
      and p7_callouts.opacidad_de_caja({"subtitulo_caja": 9}) == 1.0
      and p7_callouts.opacidad_de_caja({"subtitulo_caja": "medio"}) is None)
check("params_defecto trae la caja en auto",
      p7_callouts.params_defecto().get("subtitulo_caja") == "auto")

# --------------------------------------- obsolescencia POR UNIDAD (estado)

_dir_proy = Path(_dir_datos) / "proyectos" / "prueba_enrutar"
for sub in ("guion", "voz", "assets", "callouts"):
    (_dir_proy / "pasos" / sub).mkdir(parents=True, exist_ok=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "enrutar"})
proyecto = Proyecto(_dir_proy)
estado = Estado(proyecto)

GUION = {"escenas": [
    {"id": "S001", "titulo": "uno", "narracion": "texto uno"},
    {"id": "S002", "titulo": "dos", "narracion": "texto dos"},
    {"id": "S003", "titulo": "tres", "narracion": "texto tres"},
]}
estado.completar("guion", {}, GUION, unidades=3)
estado.completar("voz", {}, {"escenas": [
    {"id": e["id"], "duracion": 3.0, "audio": "x.mp3"}
    for e in GUION["escenas"]]}, unidades=3)

estado.marcar_obsoleto("guion", ["S002"])
fichas = {p: estado.paso(p) for p in ("guion", "voz", "assets", "callouts",
                                      "render", "revision_audio")}
check("corregir S002 ensucia S002 y SOLO S002 aguas abajo",
      all(f["obsoleto_unidades"] == ["S002"]
          for f in (fichas["guion"], fichas["voz"], fichas["assets"],
                    fichas["callouts"])),
      str({p: f.get("obsoleto_unidades") for p, f in fichas.items()}))
check("el render es un solo artefacto: la unidad no lo ensucia",
      not fichas["render"].get("obsoleto_unidades"),
      str(fichas["render"].get("obsoleto_unidades")))

estado.completar("voz", {}, {"escenas": [
    {"id": "S001", "duracion": 3.0, "audio": "x.mp3"},
    {"id": "S002", "duracion": 3.1, "audio": "x.mp3"},
    {"id": "S003", "duracion": 3.0, "audio": "x.mp3"}]},
    unidades=3, hechas=["S002"])
check("rehacer la unidad limpia SOLO esa marca (S003 sigue sucia "
      "si lo estuviera, y la que se rehizo queda limpia)",
      estado.paso("voz")["obsoleto_unidades"] == []
      and estado.paso("guion")["obsoleto_unidades"] == ["S002"],
      str(estado.paso("voz")["obsoleto_unidades"]))

estado.marcar_obsoleto("voz", ["S001"])
ficha_estado = leer_json(proyecto.fichero_estado)
ficha_estado["pasos"]["voz"]["vale_unidades"] = ["S001"]
escribir_json(proyecto.fichero_estado, ficha_estado)
estado.marcar_obsoleto("voz", ["S001"])
check("volver a marcar RETIRA el vale (la tarjeta vuelve)",
      estado.paso("voz")["obsoleto_unidades"] == ["S001"]
      and estado.paso("voz")["vale_unidades"] == [],
      str(estado.paso("voz")))

# ------------------------------------------------ p5: comentarios -> texto

COMENTARIOS = [
    {"escena_id": "S002", "inicio_char": 0, "fin_char": 6,
     "texto_seleccionado": "texto ", "comentario": "mas directo",
     "id": "C001"},
    {"bloque_id": "S002", "comentario": "corta el final"},
    {"escena": "S001", "comentario": "otra escena"},
    {"escena_id": "", "comentario": "sin escena fuera"},
    "no soy un dict",
]
agrupados = p5_revision_audio.agrupar_comentarios(COMENTARIOS)
check("agrupar acepta bloque_id/escena y conserva el orden",
      list(agrupados) == ["S002", "S001"]
      and [c["id"] for c in agrupados["S002"]] == ["C001", "C002"]
      and agrupados["S002"][1]["comentario"] == "corta el final",
      str(agrupados))

TEXTO = "el transistor nacio de un trozo de silicio sucio"
check("localizar se fia de los offsets si el texto coincide",
      p5_revision_audio.localizar(TEXTO, {"inicio_char": 3, "fin_char": 13,
                                          "texto_seleccionado":
                                          "transistor"}) == (3, 13))
check("localizar con offsets que ya no cuadran busca el fragmento",
      p5_revision_audio.localizar(TEXTO, {"inicio_char": 0, "fin_char": 2,
                                          "texto_seleccionado":
                                          "silicio"}) == (35, 42))
check("localizar sin fragmento cae en la escena entera",
      p5_revision_audio.localizar(TEXTO, {"inicio_char": 0, "fin_char": 2,
                                          "texto_seleccionado":
                                          "no esta"}) == (None, None))

notas = p5_revision_audio.redactar_notas(TEXTO, [
    {"inicio_char": 0, "fin_char": 13, "texto_seleccionado":
     "el transistor", "comentario": "nombra el invento antes"},
    {"comentario": "menos adverbios"},
])
check("redactar_notas cita el fragmento y distingue la escena entera",
      '1. Sobre el fragmento "el transistor"' in notas
      and "2. Sobre toda la escena" in notas, notas)

check("_limpiar_respuesta quita vallas, preambulos y comillas",
      p5_revision_audio._limpiar_respuesta(
          '```text\nAquí tienes la escena reescrita:\n"nuevo texto"\n```')
      == "nuevo texto")

ESCENA = {"id": "S002", "narracion": TEXTO}
nuevo, aviso = p5_revision_audio.reescribir_bloque(ESCENA, [])
check("sin comentarios no hay llamada ni aviso",
      nuevo == TEXTO and aviso == "")

RESPUESTA_TEXTO = "REVIENTA"
nuevo, aviso = p5_revision_audio.reescribir_bloque(ESCENA, [
    {"comentario": "mas directo"}])
check("motor caido: texto ORIGINAL y aviso (perder la escena seria peor)",
      nuevo == TEXTO and "playa" in aviso, aviso)

RESPUESTA_TEXTO = "   "
nuevo, aviso = p5_revision_audio.reescribir_bloque(ESCENA, [
    {"comentario": "mas directo"}])
check("respuesta vacia: original y aviso",
      nuevo == TEXTO and "vacia" in aviso, aviso)

RESPUESTA_TEXTO = "palabra"
nuevo, aviso = p5_revision_audio.reescribir_bloque(ESCENA, [
    {"comentario": "resume"}])
check("longitud implausible (x0.25..x4 sobre lo HABLADO): original y aviso",
      nuevo == TEXTO and "implausible" in aviso, aviso)

RESPUESTA_TEXTO = ("<emphasis>fuerte</emphasis> el transistor nacio de un "
                   "trozo de silicio limpio<break time=\"5000ms\"/> y barato")
nuevo, aviso = p5_revision_audio.reescribir_bloque(ESCENA, [
    {"comentario": "cambia sucio por limpio"}])
check("reescritura buena: sin aviso, etiqueta inventada BORRADA y break "
      "recortado a lo que el motor admite",
      aviso == "" and "emphasis" not in nuevo
      and '<break time="2500ms"/>' in nuevo and "limpio" in nuevo, nuevo)

# --------------------------- la cadena: comentario -> texto -> voz (un gesto)

REGRABADAS: list[str] = []


def regrabar_doble(proyecto, escena_id, params):
    REGRABADAS.append(escena_id)
    voz = leer_json(proyecto.carpeta_paso("voz") / "datos.json") \
        if (proyecto.carpeta_paso("voz") / "datos.json").is_file() \
        else {"escenas": []}
    for fila in voz.get("escenas", []):
        if fila.get("id") == escena_id:
            fila["duracion"] = 4.2
    escribir_json(proyecto.carpeta_paso("voz") / "datos.json", voz)
    return {"id": escena_id, "duracion": 4.2}


_regrabar_real = p4_voz.regrabar_escena
p4_voz.regrabar_escena = regrabar_doble
try:
    # versions de partida (una pasada entera limpia las marcas de los
    # experimentos de arriba, incluida la de revision_audio)
    estado.completar("guion", {}, leer_json(
        proyecto.carpeta_paso("guion") / "datos.json"), unidades=3)
    estado.completar("voz", {}, leer_json(
        proyecto.carpeta_paso("voz") / "datos.json"), unidades=3)
    estado.completar("revision_audio", {}, {"comentarios": []}, unidades=3)

    def reescritura_mala(trabajo):
        return None, "la reescritura no cambio el texto"

    REGRABADAS.clear()
    salida = rutas_proyectos._correr_cadena(
        proyecto, "S002", reescritura_mala, {}, {})(TrabajoMudo())
    check("reescritura que no cambia nada: NO se regraba (una copia "
          "no se paga) y el aviso sube",
          salida == {"escena": "S002", "reescrito": False,
                     "regrabado": False,
                     "aviso": "la reescritura no cambio el texto"}
          and REGRABADAS == [], str(salida))

    def reescritura_buena(trabajo):
        ficha = {"id": "S002", "titulo": "dos",
                 "narracion": "texto DOS rehecho a mano"}
        return ficha, ""

    _v_voz = estado.paso("voz")["version"]
    REGRABADAS.clear()
    salida = rutas_proyectos._correr_cadena(
        proyecto, "S002", reescritura_buena, {}, {})(TrabajoMudo())
    guion = leer_json(proyecto.carpeta_paso("guion") / "datos.json")
    orden = [e["id"] for e in guion["escenas"]]
    voz = leer_json(proyecto.carpeta_paso("voz") / "datos.json")
    check("la cadena buena: reescrito y regrabado en el mismo trabajo",
          salida["reescrito"] and salida["regrabado"]
          and salida["version_voz"] == _v_voz + 1
          and REGRABADAS == ["S002"],
          str(salida))
    check("la escena nueva entra EN SU SITIO (no al final)",
          orden == ["S001", "S002", "S003"]
          and guion["escenas"][1]["narracion"] == "texto DOS rehecho "
          "a mano", str(orden))
    check("la voz subio version con hechas=[escena] y quedo limpia",
          next(f for f in voz["escenas"]
               if f["id"] == "S002")["duracion"] == 4.2
          and estado.paso("voz")["obsoleto_unidades"] == [],
          str(estado.paso("voz").get("obsoleto_unidades")))
    check("la marca baja a revision_audio para ESA escena",
          estado.paso("revision_audio")["obsoleto_unidades"]
          == ["S002"],
          str(estado.paso("revision_audio").get("obsoleto_unidades")))
finally:
    p4_voz.regrabar_escena = _regrabar_real

print()
if fallos:
    print(f"enrutar en ROJO: {len(fallos)} fallo(s)")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)
print("enrutar en verde")
