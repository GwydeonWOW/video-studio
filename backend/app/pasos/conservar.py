"""Qué se puede MANTENER cuando cambia algo de una etapa anterior.

Réplica del original (`pasos/conservar.py`): el grafo deriva la
obsolescencia de las firmas, y eso deja la cascada entera obsoleta
cuando lo que cambió fue una frase. Aquí se ANALIZA qué se conserva, se
conserva todo lo que se pueda y se marca sólo lo imposible.

Tres criterios, en este orden:
  1. Lo que no ha cambiado, no se toca.
  2. Lo que ha cambiado poco se pregunta UNA vez y en una sola llamada:
     «esta frase ha cambiado; la imagen que ya hay, ¿sigue valiendo?».
  3. Sólo lo que ha cambiado de verdad se marca para rehacer.

Diferencias honestas con el original: allí el «antes» es el
`guion_locutado.json` que escribió el paso de voz; aquí es la
narración que guarda el propio datos.json de VOZ (la escena con su
audio ya pagado), que es exactamente el texto que corresponde al audio
y a las imágenes que hay en disco. Y el «ahora» es el guion activo.
Como en esta réplica cada escena es un plano, el reparto es directo
por id de escena: no hace falta resolver rangos de bloques.

MARCAR Y GENERAR SIGUEN SIENDO DOS GESTOS: aplicar escribe el reparto
en el estado (unidades sucias); quien decide regenerar —y pagar— es la
persona, con el coste delante.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from ..nucleo.estado import Estado
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

PASO = "conservacion"

#: Cuánto se parecen dos textos para considerar que es el mismo bloque
#: retocado (candidato a conservar) y no uno que dice otra cosa. BAJO a
#: propósito: reescribir una frase cambiándole el tono la aleja mucho
#: carácter a carácter y nada en lo que hay que dibujar.
PARECIDO_RETOQUE = 0.55

#: Segunda oportunidad: que las dos frases hablen de las mismas cosas,
#: medida sobre las palabras largas (las que nombran algo).
SOLAPE_RETOQUE = 0.45
LARGO_CONTENIDO = 4

#: Cambios que NO cambian lo que se ve ni lo que se oye.
PARECIDO_COSMETICO = 0.995

SISTEMA = """Un vídeo de animación narrada ya generado tiene que absorber un
cambio en su guion. Cada plano tiene una imagen ya dibujada y ya pagada.
Tu trabajo es decidir, plano a plano, si esa imagen SIGUE VALIENDO con
la frase nueva o si hay que volver a dibujarla.

COMO SE DECIDE
Vale si lo que se ve seguiría siendo verdad: los mismos personajes, el
mismo sitio, la misma acción. Cambiar el tono de una frase, apretar su
redacción, corregir una cifra que no se ve en pantalla o cambiar una
palabra por un sinónimo NO cambia lo que hay que dibujar.

No vale si la frase nueva describe otra cosa: otro sitio, otra persona,
otro momento, otra acción, o algo concreto que la imagen tendría que
enseñar y no enseña.

Ante la duda, di que NO vale. Una imagen conservada de más se ve en el
vídeo final; una rehecha de más cuesta unos céntimos.

LO QUE HAY QUE JUZGAR
Cada plano trae lo que narraba ANTES, lo que narra AHORA y cómo se
describió la imagen que ya existe.
<<<
{planos}
>>>

Devuelve SOLO JSON:
{{"planos": [{{"id": "<id del plano>", "vale": true,
              "porque": "<en una línea>"}}]}}"""


# ---------------------------------------------------- comparar dos guiones

def _normal(texto: str) -> str:
    """Texto comparable: sin acentos, sin puntuación, sin dobles espacios."""
    plano = unicodedata.normalize("NFKD", str(texto or "").lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", plano).split())


def _parecido(antes: str, despues: str) -> float:
    if antes == despues:
        return 1.0
    return difflib.SequenceMatcher(None, antes, despues).ratio()


def _contenido(texto: str) -> set[str]:
    return {p for p in texto.split() if len(p) >= LARGO_CONTENIDO}


def _solape(antes: str, despues: str) -> float:
    a, d = _contenido(antes), _contenido(despues)
    if not a or not d:
        return 0.0
    return len(a & d) / float(len(a | d))


def comparar_escenas(antes, despues) -> dict:
    """Qué le ha pasado a cada escena. Sin llamar a nadie.

    'antes' y 'despues' son listas de {"id", "narracion"}. Devuelve un
    dict por id con su estado:

        igual/cosmetico  no se toca nada
        retocado         la misma idea con otras palabras -> hay que mirarlo
        reescrito        dice otra cosa -> se rehace
        nuevo/borrado    no estaba / ya no está
    """
    mapa_antes = {str(e.get("id") or "").upper(): str(e.get("narracion") or "")
                  for e in (antes or []) if e.get("id")}
    mapa_despues = {str(e.get("id") or "").upper(): str(e.get("narracion") or "")
                    for e in (despues or []) if e.get("id")}
    fichas = {}
    for sid in sorted(set(mapa_antes) | set(mapa_despues)):
        viejo, nuevo = mapa_antes.get(sid), mapa_despues.get(sid)
        if viejo is None:
            fichas[sid] = {"estado": "nuevo", "parecido": 0.0, "solape": 0.0,
                           "antes": "", "despues": nuevo}
            continue
        if nuevo is None:
            fichas[sid] = {"estado": "borrado", "parecido": 0.0, "solape": 0.0,
                           "antes": viejo, "despues": ""}
            continue
        a, d = _normal(viejo), _normal(nuevo)
        parecido, solape = _parecido(a, d), _solape(a, d)
        if viejo == nuevo:
            estado = "igual"
        elif a == d or parecido >= PARECIDO_COSMETICO:
            estado = "cosmetico"
        elif parecido >= PARECIDO_RETOQUE or solape >= SOLAPE_RETOQUE:
            estado = "retocado"
        else:
            estado = "reescrito"
        fichas[sid] = {"estado": estado, "parecido": round(parecido, 3),
                       "solape": round(solape, 3),
                       "antes": viejo, "despues": nuevo}
    return fichas


def resumen(fichas: dict) -> dict:
    cuenta: dict[str, int] = {}
    for ficha in (fichas or {}).values():
        cuenta[ficha["estado"]] = cuenta.get(ficha["estado"], 0) + 1
    return cuenta


# ------------------------------------------------------------- análisis

def _prompts_de_assets(proyecto: Proyecto) -> dict:
    """{escena: prompt con el que se pagó la imagen que hay}."""
    datos = p2_brief.proyecto_leer_datos(proyecto, "assets") or {}
    return {str(p.get("escena") or ""): str(p.get("prompt") or "")
            for p in (datos.get("planos") or []) if isinstance(p, dict)}


def analizar(antes, despues) -> dict:
    """El reparto SIN llamar a nadie: conservar / rehacer / dudosos."""
    fichas = comparar_escenas(antes, despues)
    conservar, rehacer, dudosos = [], [], []
    for sid, ficha in sorted(fichas.items()):
        if ficha["estado"] in ("igual", "cosmetico"):
            conservar.append(sid)
        elif ficha["estado"] in ("borrado", "reescrito", "nuevo"):
            rehacer.append(sid)
        else:                                   # retocado: hay que mirarlo
            dudosos.append({"id": sid, "antes": ficha["antes"],
                            "despues": ficha["despues"]})
    return {"escenas": fichas, "resumen": resumen(fichas),
            "conservar": conservar, "rehacer": rehacer, "dudosos": dudosos}


def _tabla_de_dudosos(dudosos, prompts, maximo=60) -> str:
    lineas = []
    for ficha in dudosos[:maximo]:
        lineas.append(f"[{ficha['id']}]")
        lineas.append(f"  ANTES : {' '.join(str(ficha['antes']).split())}")
        lineas.append(f"  AHORA : {' '.join(str(ficha['despues']).split())}")
        imagen = " ".join((prompts or {}).get(ficha["id"], "").split())
        if imagen:
            lineas.append(f"  IMAGEN: {imagen[:320]}")
    return "\n".join(lineas)


def juzgar_dudosos(dudosos, prompts, proyecto_id="") -> dict:
    """Pregunta por TODOS los dudosos de una vez, en UNA llamada.

    Si algo falla, todos los dudosos se van a rehacer — que es lo que
    pasaba antes de que existiera esto, o sea que el fallo nunca deja
    el vídeo peor de lo que estaba.
    """
    if not dudosos:
        return {"porque": {}, "llamada": False}
    llamada = llm.rol_config("conservacion", comun.ajustes_llm())
    llamada.sistema = SISTEMA.format(
        planos=_tabla_de_dudosos(dudosos, prompts))
    llamada.contexto = "conservacion"
    llamada.proyecto = proyecto_id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    conocidos = {d["id"] for d in dudosos}
    porque = {}
    vale = set()
    for ficha in (crudo.get("planos") or []) if isinstance(crudo, dict) else []:
        if not isinstance(ficha, dict):
            continue
        pid = str(ficha.get("id") or "").strip().upper()
        if pid not in conocidos:
            continue
        if bool(ficha.get("vale")):
            vale.add(pid)
        porque[pid] = str(ficha.get("porque") or "").strip()
    # un plano del que no contestó NO se conserva: no contestar es no
    # haberlo mirado, y darlo por bueno sería inventarse un sí
    for ficha in dudosos:
        porque.setdefault(ficha["id"],
                          "el análisis no dijo nada de este plano, "
                          "así que se rehace")
    return {"vale": vale, "porque": porque, "llamada": True}


def plan(proyecto: Proyecto, avisar=None, preguntar: bool = True) -> dict:
    """El plan de conservación de ESTE proyecto, con sus ficheros en disco.

    El «antes» es lo que grabó la voz (datos.json de voz: la narración
    que corresponde al audio y a las imágenes pagadas); el «ahora» es
    el guion activo. Además del reparto por planos traduce el resultado
    a los pasos del grafo: la voz se regraba por escena y las unidades
    de assets/callouts son los planos.
    """
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz") or {}
    antes = [e for e in (voz.get("escenas") or []) if e.get("id")]
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion") or {}
    despues = [e for e in (guion.get("escenas") or []) if e.get("id")]
    if not antes:
        return {"posible": False, "conservar": [], "rehacer": [], "escenas": {},
                "por_que_no": "no hay voz grabada: sin ella no se sabe con "
                              "qué texto se pagaron las imágenes, así que se "
                              "rehace todo, que es lo que se hacía antes."}
    if not despues:
        return {"posible": False, "conservar": [], "rehacer": [], "escenas": {},
                "por_que_no": "no hay guion que comparar: ejecuta el paso "
                              "de guion"}

    analisis = analizar(antes, despues)
    motivos = {sid: "la narración no ha cambiado" for sid in analisis["conservar"]}
    for sid in analisis["rehacer"]:
        estado = analisis["escenas"][sid]["estado"]
        motivos[sid] = {"borrado": "la escena ya no está en el guion",
                        "nuevo": "escena nueva: no tiene imagen",
                        "reescrito": "la narración dice otra cosa"}.get(
                            estado, "la narración dice otra cosa")

    juicio = {"vale": set(), "porque": {}, "llamada": False}
    if analisis["dudosos"] and preguntar:
        try:
            if avisar:
                avisar(f"preguntando por {len(analisis['dudosos'])} plano(s) "
                       "dudoso(s)")
            juicio = juzgar_dudosos(analisis["dudosos"],
                                    _prompts_de_assets(proyecto), proyecto.id)
        except Exception as fallo:                      # noqa: BLE001
            juicio = {"vale": set(), "porque": {}, "llamada": False,
                      "error": f"{type(fallo).__name__}: {fallo}"}

    conservar = list(analisis["conservar"])
    rehacer = list(analisis["rehacer"])
    for ficha in analisis["dudosos"]:
        sid = ficha["id"]
        if sid in juicio["vale"]:
            conservar.append(sid)
            motivos[sid] = (juicio["porque"].get(sid)
                            or "la frase cambia, pero lo que se ve no")
        else:
            rehacer.append(sid)
            motivos[sid] = (juicio["porque"].get(sid)
                            or "la frase ha cambiado y no se ha podido "
                               "comprobar si la imagen sigue valiendo")
    conservar = sorted(set(conservar) - set(rehacer))
    rehacer = sorted(set(rehacer))

    regrabar = sorted(
        sid for sid, f in analisis["escenas"].items()
        if f["estado"] in ("retocado", "reescrito", "nuevo"))
    return {**analisis, "posible": True, "conservar": conservar,
            "rehacer": rehacer,
            "motivos": {sid: motivos.get(sid, "") for sid in conservar + rehacer},
            "juicio": {k: v for k, v in juicio.items() if k != "vale"},
            "regrabar_voz": regrabar,
            "resumen": (f"{len(conservar)} plano(s) se conservan, "
                        f"{len(rehacer)} hay que rehacer, "
                        f"{len(regrabar)} escena(s) de voz que regrabar")}


def aplicar(estado: Estado, ficha: dict, proyecto: Proyecto) -> dict:
    """Escribe el plan en el grafo: MARCA lo que hay que rehacer.

    Conservar no se escribe en ningún sitio: es lo que ya está en disco
    y no se toca (las imágenes se regeneran por unidades, así que lo no
    marcado se conserva solo). La voz se marca por escena para que la
    pantalla ofrezca regrabar sólo lo cambiado.
    """
    if not ficha.get("posible"):
        raise ValueError(ficha.get("por_que_no") or "nada que conservar")
    rehacer = [str(s) for s in (ficha.get("rehacer") or [])]
    regrabar = [str(s) for s in (ficha.get("regrabar_voz") or [])]
    tocados = {}
    if rehacer:
        # assets y callouts comparten el id de plano; la cascada de
        # marcar_obsoleto deja avisados los de abajo
        estado.marcar_obsoleto("assets", rehacer)
        tocados["assets"] = rehacer
    if regrabar:
        estado.marcar_obsoleto("voz", regrabar)
        tocados["voz"] = regrabar
    proyecto.bitacora("conservacion_aplicada",
                      {"rehacer": rehacer, "regrabar": regrabar,
                       "resumen": ficha.get("resumen", "")})
    return {"tocados": tocados,
            "conservados": len(ficha.get("conservar") or []),
            "rehacer": len(rehacer), "regrabar": len(regrabar)}
