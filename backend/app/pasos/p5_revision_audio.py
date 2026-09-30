"""Paso 5 — revisión de audio: comentarios, reescritura y chequeos.

Dos piezas que se tocaban por separado en el original:

1. COMENTARIOS al estilo Google Docs sobre la narración: la persona
   selecciona un trozo de una escena y deja una nota. La reescritura
   (reescribir_bloque) aplica las notas a la escena y devuelve el texto
   nuevo — o el ORIGINAL con un aviso: perder la escena entera por una
   reescritura fallida sería peor que ignorar la nota. Los offsets del
   navegador solo se aceptan si el texto que hay ahí es el que la
   persona dice haber seleccionado (el guion pudo reeditarse después de
   comentar); si no, se busca el fragmento y, en último caso, la nota se
   aplica a la escena entera.

2. CHEQUEOS deterministas sin coste: duración real vs estimada del
   guion, silencios al principio/fin (la voz arranca cortada o se traga
   el final) y volumen bajo (pico por debajo de -20 dBFS).

La regrabación de la escena reescrita la encadena la API (comentario →
reescribir texto → regrabar audio de ESA escena en un gesto), que es
donde vive el grafo. No hay reintento de reescritura: una nota que no
se pudo aplicar se ve como aviso, no como silencio.
"""
from __future__ import annotations

import re
import subprocess

from ..motores import llm
from ..nucleo.proyecto import Proyecto
from . import comun, marcas_tts, p2_brief


def params_defecto() -> dict:
    return {"tope_desviacion": 0.35, "pico_minimo_db": -20}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


# ------------------------------------------------------------ comentarios

#: Preambulos que el modelo pone delante del bloque («aquí tienes:»).
#: Quitarlos aqui evita que la reescritura llegue con basura que el TTS
#: locutaria literalmente.
_PREAMBULOS = re.compile(
    r"^(aqu[ií] tienes|aqu[ií] va|texto reescrito|bloque reescrito|"
    r"escena reescrita|versi[oó]n reescrita|reescritura|resultado)"
    r"\b[^\n]*:\s*$", re.IGNORECASE)

INSTRUCCION = """\
Eres el guionista de un documental narrado en off, en espanol.

Reescribe UNA escena del guion aplicando las notas del revisor.

ESCENA ORIGINAL (id {escena_id}):
<<<
{texto}
>>>

NOTAS DEL REVISOR:
{notas}

Reglas:
- Responde SOLO con el texto reescrito de la narracion. Sin comillas, sin
  markdown, sin encabezados, sin explicar lo que has cambiado.
- Es texto para leer en voz alta: nada de acotaciones, parentesis tecnicos,
  nombres de plano ni marcas de escena.
- Con la ORTOGRAFIA COMPLETA del castellano: todas las tildes, las dieresis
  y las enes. Lo lee un sintetizador de voz, asi que sin tilde dice
  «publico» donde pone «publico» con tilde. Da igual como este escrita esta
  instruccion.
- TODO CON LETRAS: ni un digito ni un simbolo. Esto se locuta, y una cifra
  la pronuncia el sintetizador como el decida. Anos, numeros, fechas,
  porcentajes, dinero y horas, escritos como se dicen en el idioma de la
  escena. Las siglas que se deletrean, marcadas: <spell>MFA</spell>.
- Manten el idioma, el registro y una longitud parecida, salvo que la nota
  pida expresamente acortar o alargar.
- Cambia solo lo que piden las notas; el resto de la escena se queda como
  esta.
- Si una nota no se puede aplicar, aplica las demas y no lo comentes.
- Si la narracion trae anotaciones de voz (<break time="700ms"/>), NO son
  texto: le dicen al sintetizador donde parar. Se conservan y se recolocan
  si la frase que las rodeaba ha cambiado. Es la unica que existe: no te
  inventes ninguna, porque una etiqueta que el sintetizador no reconoce la
  LEE EN VOZ ALTA.
"""


def agrupar_comentarios(comentarios) -> dict:
    """{escena_id: [comentarios]} conservando el orden de llegada.

    Acepta `bloque_id` (el nombre del original) y `escena` además de
    escena_id: el comentario lo escribe la pantalla, y solo viaja hasta
    aqui.
    """
    agrupados: dict[str, list] = {}
    for posicion, crudo in enumerate(comentarios or [], 1):
        if not isinstance(crudo, dict):
            continue
        escena_id = str(crudo.get("escena_id") or crudo.get("bloque_id")
                        or crudo.get("escena") or "").strip()
        texto = str(crudo.get("comentario") or "").strip()
        if not escena_id or not texto:
            continue
        ficha = {
            "id": str(crudo.get("id") or f"C{posicion:03d}"),
            "escena_id": escena_id,
            "inicio_char": crudo.get("inicio_char"),
            "fin_char": crudo.get("fin_char"),
            "texto_seleccionado": str(crudo.get("texto_seleccionado") or ""),
            "comentario": texto,
        }
        agrupados.setdefault(escena_id, []).append(ficha)
    return agrupados


def localizar(texto: str, comentario: dict):
    """Tramo (inicio, fin) de la escena al que se refiere el comentario.

    Los offsets del navegador pueden no cuadrar si el guion se reedito
    despues de comentar, asi que solo se aceptan si el texto que hay ahi
    es el que la persona dice haber seleccionado; si no, se busca el
    fragmento y, en ultimo caso, la nota se aplica a la escena entera.
    """
    seleccion = comentario.get("texto_seleccionado") or ""
    inicio, fin = comentario.get("inicio_char"), comentario.get("fin_char")
    if (isinstance(inicio, int) and isinstance(fin, int)
            and 0 <= inicio < fin <= len(texto)):
        if not seleccion or texto[inicio:fin] == seleccion:
            return inicio, fin
    if seleccion:
        encontrado = texto.find(seleccion)
        if encontrado >= 0:
            return encontrado, encontrado + len(seleccion)
    return None, None


def _fragmento(texto: str, comentario: dict) -> str:
    inicio, fin = localizar(texto, comentario)
    if inicio is None:
        return (comentario.get("texto_seleccionado") or "").strip()
    return texto[inicio:fin]


def redactar_notas(texto: str, comentarios: list) -> str:
    """Comentarios -> lista numerada legible para el modelo."""
    lineas = []
    for numero, comentario in enumerate(comentarios, 1):
        trozo = _fragmento(texto, comentario)
        if trozo:
            lineas.append(f'{numero}. Sobre el fragmento "{trozo}": '
                          f'{comentario["comentario"]}')
        else:
            lineas.append(f'{numero}. Sobre toda la escena: '
                          f'{comentario["comentario"]}')
    return "\n".join(lineas)


# ------------------------------------------------------------- reescritura

def _limpiar_respuesta(salida: str) -> str:
    """Quita fences, preambulos y comillas de la respuesta del modelo."""
    texto = (salida or "").strip()
    if not texto:
        return ""
    texto = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", texto).strip()
    lineas = [l for l in texto.splitlines()]
    while lineas and (not lineas[0].strip()
                      or _PREAMBULOS.match(lineas[0].strip())):
        lineas.pop(0)
    texto = "\n".join(lineas).strip()
    if len(texto) > 1 and texto[0] in "\"'«" and texto[-1] in "\"'»":
        texto = texto[1:-1].strip()
    return re.sub(r"[ \t]+", " ", texto).strip()


def reescribir_bloque(escena: dict, comentarios: list,
                      proyecto_id: str = "") -> tuple[str, str]:
    """Aplica las notas a UNA escena. -> (texto_nuevo, aviso)

    Si algo sale mal se devuelve el texto ORIGINAL y el aviso: perder la
    escena entera por una reescritura fallida seria peor que ignorar la
    nota, y el aviso sube hasta la respuesta para que se vea en la
    pantalla. Una reescritura que multiplica o divide la escena suele ser
    el modelo explicando en vez de reescribiendo: mejor quedarse con el
    original. Se compara sobre el texto HABLADO — una escena con anotacio-
    nes tiene mas caracteres sin decir una palabra mas, y esa holgura
    falseaba el limite.
    """
    texto = str(escena.get("narracion") or "")
    if not comentarios:
        return texto, ""
    llamada = llm.rol_config("correccion", comun.ajustes_llm())
    llamada.sistema = ("Responde exclusivamente con el texto reescrito de "
                       "la narracion, sin texto alrededor, sin comillas y "
                       "sin vallas de markdown.")
    llamada.instruccion = INSTRUCCION.format(
        escena_id=escena.get("id", "?"), texto=texto,
        notas=redactar_notas(texto, comentarios))
    llamada.contexto = f"revision_audio:{escena.get('id', '?')}"
    llamada.proyecto = proyecto_id
    try:
        crudo = llm.llamar(llamada, claves=comun.claves_actuales())
    except llm.ErrorLLM as fallo:
        return texto, str(fallo)

    nuevo = _limpiar_respuesta(crudo)
    if not nuevo:
        return texto, "la reescritura vino vacia"
    hablado_antes = marcas_tts.limpiar(texto)
    hablado_nuevo = marcas_tts.limpiar(nuevo)
    if not (0.25 * len(hablado_antes) <= len(hablado_nuevo)
            <= 4 * len(hablado_antes)):
        return texto, (f"reescritura descartada por longitud implausible "
                       f"({len(hablado_antes)} -> {len(hablado_nuevo)} "
                       f"caracteres de narracion)")
    # La escena puede volver de aqui con una etiqueta inventada, y lo que
    # el motor de voz no reconoce lo LOCUTA. Se corrige en silencio y no
    # se cuenta como aviso: el aviso de esta funcion significa «la
    # reescritura no salio», y esta si salio.
    nuevo = marcas_tts.sanear(nuevo)
    if not nuevo.strip():
        return texto, "la reescritura se quedo sin texto que locutar"
    return nuevo, ""


def _medir(ruta) -> dict:
    """Silencio inicial/final y pico con ffmpeg (una pasada, sin coste)."""
    try:
        proceso = subprocess.run(
            [comun.ffmpeg(), "-hide_banner", "-i", str(ruta),
             "-af", "silencedetect=noise=-45dB:d=0.25,"
                    "astats=metadata=1:reset=0",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120)
        informe = proceso.stderr or ""
    except subprocess.SubprocessError:
        return {"silencio_inicio": 0.0, "silencio_fin": 0.0, "pico_db": -6.0}
    inicio = fin = None
    for linea in informe.splitlines():
        if "silence_start" in linea and inicio is None:
            try:
                inicio = float(linea.split("silence_start:")[1].split()[0])
            except (ValueError, IndexError):
                pass
        elif "silence_end" in linea and fin is None:
            try:
                par = linea.split("silence_end:")[1].split("|")
                fin = float(par[0])  # marca el final del ultimo silencio
            except (ValueError, IndexError):
                pass
    pico = -6.0
    for linea in informe.splitlines():
        if "Peak level dB" in linea:
            try:
                pico = float(linea.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
    duracion = comun.duracion_de(ruta)
    silencio_final = max(0.0, duracion - (fin or 0.0)) if fin else 0.0
    return {"silencio_inicio": round(inicio or 0.0, 3),
            "silencio_fin": round(silencio_final, 3),
            "pico_db": round(pico, 1)}


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    if not voz.get("escenas"):
        raise ValueError("falta la voz: genera primero el paso anterior")
    tope = float(params.get("tope_desviacion", 0.35))
    pico_minimo = float(params.get("pico_minimo_db", -20))
    estimadas = {e["id"]: e.get("duracion_estimada", 0)
                 for e in guion.get("escenas", [])}
    avisos, ok = [], True
    for ficha in voz["escenas"]:
        trabajo.comprobar_cancelacion()
        escena_id = ficha["id"]
        trabajo.avance(f"revisando {escena_id}")
        ruta = proyecto.ruta(ficha["audio"])
        medidas = _medir(ruta)
        problemas = []
        estimada = estimadas.get(escena_id, ficha["duracion"])
        desviacion = abs(ficha["duracion"] - estimada) / max(estimada, 0.1)
        if desviacion > tope:
            problemas.append(f"duracion {ficha['duracion']}s frente a "
                             f"{round(estimada)}s previsto (desvio "
                             f"{round(desviacion * 100)}%)")
        if medidas["silencio_inicio"] > 0.4:
            problemas.append(f"arranca con {medidas['silencio_inicio']}s "
                             "de silencio")
        if medidas["silencio_fin"] > 0.8:
            problemas.append(f"acaba con {medidas['silencio_fin']}s de "
                             "silencio")
        if medidas["pico_db"] < pico_minimo:
            problemas.append(f"volumen bajo (pico {medidas['pico_db']} dB)")
        if problemas:
            ok = False
            avisos.append({"id": escena_id, "problemas": problemas})
    estado_texto = "ok" if ok else "avisos"
    trabajo.avance(f"revision de audio: {estado_texto} "
                   f"({len(avisos)} escenas con avisos)")
    return {"estado": estado_texto, "avisos": avisos,
            "revisadas": len(voz["escenas"])}
