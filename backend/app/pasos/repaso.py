"""EL REPASO: lo que se escribe MIRANDO el vídeo, y cómo se convierte en cambios.

QUÉ ES
------
El último paso del sistema y el primero que existe para una persona. Con el
vídeo delante se pausa, se escribe una frase —y si hace falta se arrastra una
imagen de referencia— y esa nota se queda anclada AL SEGUNDO en el que se
escribió. Después, un botón: aplicar y volver a generar.

LAS TRES DECISIONES QUE LO GOBIERNAN (heredadas del original):

1 · UNA NOTA ES UN REGISTRO, NO UNA ENTRADA DEL PASO.
    Vive en `<proyecto>/repaso.json` y NO en los params. Escribir «la música
    está alta en 0:45» no puede dejar el render obsoleto: el vídeo no cambia
    porque alguien lo comente. Lo que SÍ toca las firmas es APLICAR, y eso
    es un gesto aparte y con su coste delante.

2 · EL SEGUNDO ES EL ANCLA, Y DE AHÍ SALE TODO LO DEMÁS.
    Del instante se deducen el plano que estaba en pantalla, su narración,
    su cartela si la lleva y lo que se lee. Una nota no dice «el plano
    S031»: dice «aquí», y «aquí» se resuelve contra los cortes con los que
    se montó ESE vídeo, no contra el plan de ahora — que puede haber
    cambiado. Ver `reanclar`.

3 · APLICAR AHORRA, Y ESO NO ES UNA OPTIMIZACIÓN: ES EL DISEÑO.
    Cada nota se enruta a un ÁMBITO, y cada ámbito sabe exactamente qué hay
    que rehacer. Cambiar el texto de una cartela es redibujar una capa;
    tocar la IMAGEN de un plano cuesta una imagen; reescribir lo que se
    DICE cuesta la locución de esa escena. Un sistema que ante cualquier
    nota regenerara el vídeo entero convertiría el repaso en algo que
    nadie usa dos veces.

EL VOCABULARIO CERRADO DE CAMBIOS
---------------------------------
El enrutador es un LLM, así que no escribe params libres: elige entre los
cambios de `CAMBIOS`, que son datos validados por este módulo. Un cambio
que no está en la tabla no se aplica — se queda como nota y se dice.

Y cada cajón donde escribe LO LEE ALGUIEN (regla del original: media pieza
escrita no da error, deja el vídeo igual y la nota marcada como aplicada):

    feedback_plano    p6_assets.prompt_de        (unidades.escena:*.feedback)
    cartela_texto     p6_assets.es_cartela       (unidades.escena:*.cartela)
    subtitulo_texto   p7_callouts.ejecutar       (unidades.escena:*.subtitulo_texto)
    subtitulo_tam     p7_callouts + p8_render    (params.subtitulo_tam)
    grafismo          p7_callouts + p8_render    (params.diseno)
    escena_texto      p3_guion.ejecutar          (unidades.escena:*.texto)
    velocidad         p4_voz.ejecutar            (params.velocidad)
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

from ..nucleo import grafismo
from ..nucleo.proyecto import Proyecto, escribir_json
from . import comun
from ..motores import llm

PASO = "repaso"

FICHERO = "repaso.json"
CARPETA_IMAGENES = "repaso"

#: Cuántas imágenes de referencia caben en una nota. Más de cuatro y deja
#: de ser «mira esto» para ser un moodboard, que es otra cosa.
MAX_IMAGENES = 4

#: Lo que puede ocupar una nota: una nota de mil palabras es un brief, y
#: un brief se escribe en el encargo.
MAX_TEXTO = 1200


# ===========================================================================
# LOS ÁMBITOS
#
# Un ámbito es «de qué parte del vídeo habla esta nota», y lo que lo hace
# útil es la TERCERA columna: qué hay que rehacer. Ahí vive el ahorro.
# ===========================================================================

DONDE_SE_ARREGLA = {
    "imagen": "El dibujo de un plano se cambia en Imágenes, plano a plano.",
    "guion": "Lo que se DICE se reescribe en Guion, en su escena.",
    "voz": "Como se dice -- ritmo, pausas, entonación -- se cambia en Guion.",
}

AMBITOS = {
    "imagen": {
        "que_es": "lo que se ve dibujado en el plano: qué hay, quién sale, "
                  "qué hace, dónde ocurre",
        "cuesta": "una imagen por plano tocado",
    },
    "cartela": {
        "que_es": "el texto del plano que es cartela (la cabecera, la cifra, "
                  "el cierre)",
        "cuesta": "nada: se redibuja la capa",
    },
    "subtitulo": {
        "que_es": "el rótulo de la escena: qué dice, de qué tamaño, con qué "
                  "set se dibuja",
        "cuesta": "nada: se recalcula",
    },
    "guion": {
        "que_es": "lo que se dice: el texto de una escena de la narración",
        "cuesta": "la locución de esa escena, y todo lo que cuelga de ella",
    },
    "voz": {
        "que_es": "cómo se dice: el ritmo, las pausas, la entonación",
        "cuesta": "la locución de todo el vídeo",
    },
    "nota": {
        "que_es": "algo que no se puede aplicar solo y hay que decidir a mano",
        "cuesta": "nada: se queda escrito",
    },
    "transicion": {
        "que_es": "con qué efectos de transición se unen los planos, y "
                  "cuánto duran",
        "cuesta": "nada: se re-monta el vídeo",
    },
    "musica": {
        "que_es": "la música que suena debajo de la voz, y a qué nivel",
        "cuesta": "nada: se re-monta el vídeo",
    },
    "efectos": {
        "que_es": "los efectos de sonido (aires de transición, golpes), "
                  "y a qué nivel",
        "cuesta": "nada: se re-monta el vídeo",
    },
}


# ===========================================================================
# EL VOCABULARIO DE CAMBIOS
#
#   ambito     de qué habla
#   rehacer    qué pasos de la receta quedan sucios. ES LA COLUMNA QUE AHORRA.
#   campos     cómo se valida lo que llegue
# ===========================================================================

def _num(valor, minimo, maximo):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if minimo <= numero <= maximo else None


def _texto(valor, tope=600):
    limpio = " ".join(str(valor or "").split())
    return limpio[:tope] or None


def _plano(valor):
    limpio = str(valor or "").strip().upper()
    return limpio if re.fullmatch(r"S\d{3,4}", limpio) else None


#: LOS DOS ALCANCES DE UNA CORRECCIÓN DE IMAGEN:
#:
#:   retoque     «cámbiale la mano por un guante»: lo demás del plano se
#:               queda. (El motor de imagen de esta réplica no adjunta la
#:               rechazada, pero la etiqueta viaja en el historial y se
#:               añade al encargo como "cambio localizado".)
#:   sustituye   «esto tenía que ser un móvil»: lo que hay que dibujar es
#:               OTRA COSA.
ALCANCES = ("retoque", "sustituye")


def _alcance(valor):
    limpio = str(valor or "").strip().lower()
    return limpio if limpio in ALCANCES else "sustituye"


def _tamano_subtitulo(valor):
    nombre = str(valor or "").strip().lower()
    return nombre if nombre in grafismo.SUB_TAMANOS else None


def _set_de_diseno(valor):
    nombre = str(valor or "").strip().lower()
    return nombre if nombre in grafismo.SETS_DISENO else None


#: `campos_cartela` se valida AL APLICAR contra la plantilla del plano
#: (aquí solo que es un diccionario con algo dentro).
CAMBIOS = {
    # ---------------------------------------------------------------- imagen
    "feedback_plano": {
        "ambito": "imagen",
        "que_es": "vuelve a dibujar ESE plano con la nota delante. `texto` va "
                  "EN INGLÉS (derecho al modelo de imagen): di qué QUITAR y "
                  "qué PONER, en una o dos frases. `alcance` es «retoque» si "
                  "el cambio es LOCALIZADO o «sustituye» si lo que hay que "
                  "dibujar es otra cosa",
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano, "texto": lambda v: _texto(v, 600),
                   "alcance": _alcance},
    },
    # --------------------------------------------------------------- cartela
    "cartela_texto": {
        "ambito": "cartela",
        "que_es": "cambia lo que dice la cartela de ese plano (que ya ES "
                  "cartela): un diccionario con los campos nuevos",
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano,
                   "campos_cartela": lambda v: v if isinstance(v, dict) and v
                   else None},
    },
    "quitar_cartela": {
        "ambito": "cartela",
        "que_es": "ese plano deja de ser cartela y se paga su imagen",
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano},
    },
    # ------------------------------------------------------------- subtitulo
    "subtitulo_tam": {
        "ambito": "subtitulo",
        "que_es": "el tamaño del rótulo: " + ", ".join(grafismo.SUB_TAMANOS),
        "rehacer": ["callouts", "render"],
        "campos": {"valor": _tamano_subtitulo},
    },
    "grafismo": {
        "ambito": "subtitulo",
        "que_es": "el set de estilo con el que se dibuja el texto encima del "
                  "vídeo: " + ", ".join(grafismo.SETS_DISENO),
        "rehacer": ["callouts", "render"],
        "campos": {"valor": _set_de_diseno},
    },
    "subtitulo_texto": {
        "ambito": "subtitulo",
        "que_es": "corrige lo que DICE el rótulo de ese plano, sin tocar la "
                  "voz: se escribe el texto entero del rótulo, ya corregido",
        "rehacer": ["callouts", "render"],
        "campos": {"plano": _plano, "texto": lambda v: _texto(v, 80)},
    },
    # ----------------------------------------------------------------- guion
    "escena_texto": {
        "ambito": "guion",
        "que_es": "reescribe lo que se dice en esa escena: el texto nuevo "
                  "ENTERo, en el idioma del vídeo",
        "rehacer": ["voz", "revision_audio", "assets", "callouts", "render"],
        "campos": {"plano": _plano, "texto": lambda v: _texto(v, 900)},
    },
    # ------------------------------------------------------------------ voz
    "velocidad": {
        "ambito": "voz",
        "que_es": "cómo de rápido habla el locutor (0.7 a 1.2)",
        "rehacer": ["voz", "revision_audio", "assets", "callouts", "render"],
        "campos": {"valor": lambda v: _num(v, 0.7, 1.2)},
    },
    # ------------------------------------------------------------------ nota
    "anotar": {
        "ambito": "nota",
        "que_es": "no se puede aplicar solo: se deja escrito para decidirlo",
        "rehacer": [],
        "campos": {"texto": lambda v: _texto(v, 600)},
    },
    # ---------------------------------------------------------- transicion
    "transicion_duracion": {
        "ambito": "transicion",
        "que_es": "cuánto dura cada transición (0,1 a 1,5 s)",
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, 0.1, 1.5)},
    },
    "transiciones": {
        "ambito": "transicion",
        "que_es": "qué efectos de transición entran en este vídeo: una "
                  "lista con sus nombres del catálogo",
        "rehacer": ["render"],
        "campos": {"lista": lambda v: [str(x) for x in v] if isinstance(v, list)
                   else None},
    },
    # ---------------------------------------------------------------- musica
    "musica_db": {
        "ambito": "musica",
        "que_es": "cuánta música hay debajo de la voz, en dB (-24 a +24; "
                  "0 es el punto calibrado)",
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, -24.0, 24.0)},
    },
    "sin_musica": {
        "ambito": "musica",
        "que_es": "quita la música (el vídeo sale con voz y efectos)",
        "rehacer": ["render"],
        "campos": {},
    },
    "otra_musica": {
        "ambito": "musica",
        "que_es": "deja el hueco de música vacío: se elige otro tema en la "
                  "pestaña de Sonido",
        "rehacer": ["render"],
        "campos": {},
    },
    # --------------------------------------------------------------- efectos
    "efectos_db": {
        "ambito": "efectos",
        "que_es": "cuántos efectos hay, en dB (-24 a +24 sobre la pista ya "
                  "montada)",
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, -24.0, 24.0)},
    },
    "sin_efectos": {
        "ambito": "efectos",
        "que_es": "quita los efectos (el vídeo sale con voz y música)",
        "rehacer": ["render"],
        "campos": {},
    },
    "otros_efectos": {
        "ambito": "efectos",
        "que_es": "vuelve a surtir los efectos del banco (otros sonidos, "
                  "los mismos papeles)",
        "rehacer": ["efectos", "render"],
        "campos": {},
    },
}

#: DÓNDE ESCRIBE CADA CAMBIO (paso, cajón) — todos cajones que ALGUIEN lee.
DESTINOS = {
    "feedback_plano": ("assets", "unidades.escena:*.feedback"),
    "cartela_texto": ("assets", "unidades.escena:*.cartela"),
    "quitar_cartela": ("assets", "unidades.escena:*.cartela"),
    "subtitulo_tam": ("callouts", "subtitulo_tam"),
    "grafismo": ("callouts", "diseno"),
    "subtitulo_texto": ("callouts", "unidades.escena:*.subtitulo_texto"),
    "escena_texto": ("guion", "unidades.escena:*.texto"),
    "velocidad": ("voz", "velocidad"),
    "anotar": ("", ""),
    "transicion_duracion": ("render", "duracion_transicion"),
    "transiciones": ("render", "transiciones"),
    "musica_db": ("render", "musica_db"),
    "sin_musica": ("render", "musica"),
    "otra_musica": ("render", "musica"),
    "efectos_db": ("render", "efectos_db"),
    "sin_efectos": ("render", "efectos"),
    "otros_efectos": ("render", "efectos"),
}


def catalogo() -> dict:
    """Los ámbitos y los cambios, para la pantalla y para la instrucción."""
    return {
        "ambitos": {k: dict(v) for k, v in AMBITOS.items()},
        "cambios": {k: {"ambito": v["ambito"], "que_es": v["que_es"],
                        "rehacer": list(v["rehacer"]),
                        "campos": sorted(v["campos"]),
                        "destino": list(DESTINOS.get(k) or ("", ""))}
                    for k, v in CAMBIOS.items()},
    }


def validar_cambio(crudo) -> tuple[dict | None, str]:
    """Un cambio propuesto, validado. -> (cambio, motivo del descarte)"""
    if not isinstance(crudo, dict):
        return None, "no es un objeto"
    tipo = str(crudo.get("tipo") or "").strip()
    ficha = CAMBIOS.get(tipo)
    if not ficha:
        return None, f"«{tipo}» no está en el vocabulario de cambios"
    limpio = {"tipo": tipo, "ambito": ficha["ambito"]}
    for campo, valida in ficha["campos"].items():
        valor = valida(crudo.get(campo))
        if valor is None:
            return None, f"«{tipo}» necesita un {campo} válido"
        limpio[campo] = valor
    limpio["rehacer"] = list(ficha["rehacer"])
    return limpio, ""


# ===========================================================================
# LAS NOTAS
# ===========================================================================

def ruta_fichero(proyecto: Proyecto):
    return proyecto.ruta(FICHERO)


def carpeta_imagenes(proyecto: Proyecto, crear=False):
    ruta = proyecto.ruta(CARPETA_IMAGENES)
    if crear:
        os.makedirs(ruta, exist_ok=True)
    return ruta


def leer(proyecto: Proyecto) -> dict:
    """Las notas del repaso, en orden de vídeo. Nunca levanta."""
    try:
        with open(ruta_fichero(proyecto), "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        datos = {}
    notas = [n for n in (datos.get("notas") or []) if isinstance(n, dict)]
    notas.sort(key=lambda n: float(n.get("t") or 0.0))
    return {"notas": notas, "aplicado": datos.get("aplicado") or [],
            "version_video": datos.get("version_video")}


def guardar(proyecto: Proyecto, ficha: dict) -> dict:
    escribir_json(ruta_fichero(proyecto), ficha)
    return ficha


def _siguiente_id(notas) -> str:
    numeros = []
    for nota in notas:
        encaje = re.fullmatch(r"R(\d+)", str(nota.get("id") or ""))
        if encaje:
            numeros.append(int(encaje.group(1)))
    return f"R{(max(numeros) + 1) if numeros else 1:03d}"


def anadir(proyecto: Proyecto, texto, t, plano="", imagenes=(),
           version_video=None, ancla="") -> dict:
    """Una nota nueva, anclada a su segundo. El texto es OBLIGATORIO.

    La imagen es opcional y el texto no, y no es una asimetría caprichosa:
    una referencia visual sin una frase no dice qué hay que hacer con ella
    — ¿es el estilo?, ¿la composición?, ¿el objeto? —, y adivinarlo es
    exactamente como se acaba regenerando lo que no había que tocar.
    """
    limpio = " ".join(str(texto or "").split())[:MAX_TEXTO]
    if not limpio:
        raise ValueError("una nota del repaso necesita texto: una imagen "
                         "sola no dice qué hay que hacer con ella")
    ficha = leer(proyecto)
    nota = {
        "id": _siguiente_id(ficha["notas"]),
        "t": round(max(0.0, float(t or 0.0)), 3),
        "plano": str(plano or ""),
        "texto": limpio,
        "imagenes": [str(i) for i in (imagenes or [])][:MAX_IMAGENES],
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "estado": "pendiente",
        # LO QUE SE ESTABA NARRANDO cuando se escribió: el seguro contra
        # que los planos se renumeren. Ver `reanclar`.
        "ancla": " ".join(str(ancla or "").split())[:MAX_TEXTO],
    }
    ficha["notas"].append(nota)
    if version_video is not None:
        ficha["version_video"] = version_video
    guardar(proyecto, ficha)
    return nota


def editar(proyecto: Proyecto, nid, texto=None, t=None, imagenes=None,
           regenerado=None) -> dict:
    ficha = leer(proyecto)
    for nota in ficha["notas"]:
        if nota.get("id") != nid:
            continue
        if texto is not None:
            limpio = " ".join(str(texto).split())[:MAX_TEXTO]
            if not limpio:
                raise ValueError("una nota del repaso necesita texto")
            nota["texto"] = limpio
        if t is not None:
            nota["t"] = round(max(0.0, float(t)), 3)
        if imagenes is not None:
            nota["imagenes"] = [str(i) for i in imagenes][:MAX_IMAGENES]
        # CONTRA QUÉ TEXTO SE REHIZO: si fuera un sí o un no, cambiar la
        # nota dejaría el «regenerada ✓» puesto sobre una petición que
        # nadie ha atendido todavía.
        if regenerado is not None:
            nota["regenerado"] = " ".join(str(regenerado).split())[:MAX_TEXTO]
        nota["estado"] = ("aplicado"
                          if nota.get("regenerado")
                          and nota.get("regenerado") == nota.get("texto")
                          else "pendiente")
        guardar(proyecto, ficha)
        return nota
    raise KeyError(nid)


def marcar_aplicadas(proyecto: Proyecto, ids) -> list[str]:
    """Anota qué notas ya se aplicaron (quedan fuera de «Aplicar N»)."""
    pedidas = {str(i) for i in (ids or [])}
    ficha = leer(proyecto)
    tocadas = []
    for nota in ficha["notas"]:
        if nota.get("id") in pedidas and nota.get("estado") != "aplicado":
            nota["estado"] = "aplicado"
            nota["aplicada"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            tocadas.append(nota["id"])
    guardar(proyecto, ficha)
    return tocadas


def borrar(proyecto: Proyecto, nid) -> int:
    ficha = leer(proyecto)
    antes = len(ficha["notas"])
    ficha["notas"] = [n for n in ficha["notas"] if n.get("id") != nid]
    if len(ficha["notas"]) == antes:
        raise KeyError(nid)
    guardar(proyecto, ficha)
    return len(ficha["notas"])


def pendientes(proyecto: Proyecto) -> list[dict]:
    """Las notas sin aplicar."""
    return [n for n in leer(proyecto)["notas"] if n.get("estado") != "aplicado"]


# ===========================================================================
# RE-ANCLAR: el segundo es el ancla, y los planos se renumeran
# ===========================================================================

def _palabras(texto):
    """El texto reducido a palabras comparables: sin tildes ni puntuación."""
    limpio = unicodedata.normalize("NFD", str(texto or "").lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    return [p for p in re.sub(r"[^a-z0-9 ]", " ", limpio).split() if p]


def _parecido(a, b) -> float:
    """Cuánto de `a` aparece en `b`, de 0 a 1."""
    if not a:
        return 0.0
    otras = set(b)
    return sum(1 for p in a if p in otras) / len(a)


#: Alto a propósito: re-anclar mal es peor que no re-anclar — una nota que
#: apunta al plano equivocado hace rehacer el que estaba bien.
PARECIDO_MINIMO = 0.7


def _mismo_dicho(unas, otras) -> bool:
    """Si dos listas de palabras son lo mismo dicho, aunque el corte las moviera.

    Tres varas, de la más dura a la más blanda: las mismas palabras; unas
    DENTRO de las otras (un plano que se parte en dos sigue diciendo las
    mismas palabras, solo que menos de ellas); y si no, cuánto se parecen.
    """
    if unas == otras:
        return True
    if not unas or not otras:
        return False
    una, otra = " ".join(unas), " ".join(otras)
    if una in otra or otra in una:
        return True
    return _parecido(unas, otras) >= PARECIDO_MINIMO


def reanclar(notas, cortes) -> list[dict]:
    """Devuelve las notas con su plano puesto al día. -> [notas]

    POR QUÉ EXISTE. Una nota se ancla al plano que estabas mirando, y el
    número de un plano NO es estable: al regrabar la voz cambian los
    tiempos, lo que era S005 pasa a ser S004, y aplicarla habría rehecho
    el plano que estaba bien.

    CÓMO. Cada nota guarda el TEXTO que se narraba en ese plano (`ancla`).
    Si el plano que dice sigue diciendo eso, no se toca. Si no, se busca
    el que lo diga; y si ninguno se le parece lo bastante, se marca
    `descolgada` en vez de dejarla apuntando a cualquier sitio.

    Las notas viejas sin `ancla` se quedan como están: sin saber contra
    qué se escribieron, moverlas sería adivinar.
    """
    por_id = {e.get("id"): e for e in (cortes or []) if e.get("id")}
    palabras = {sid: _palabras(e.get("narracion")) for sid, e in por_id.items()}
    salida = []
    for nota in (notas or []):
        ficha = dict(nota)
        ancla = _palabras(ficha.get("ancla"))
        sid = ficha.get("plano") or ""
        if not ancla or not por_id:
            salida.append(ficha)
            continue
        if sid in palabras and _mismo_dicho(ancla, palabras[sid]):
            salida.append(ficha)
            continue
        # EL MEJOR DE LOS QUE VALEN, no el mejor a secas: se puntúa entre
        # los que ya pasan la vara.
        mejor, punto = "", 0.0
        for otro, pal in palabras.items():
            if not _mismo_dicho(ancla, pal):
                continue
            p = _parecido(ancla, pal)
            if p > punto:
                mejor, punto = otro, p
        if mejor:
            ficha["plano"] = mejor
            ficha["t"] = round(float(por_id[mejor].get("t_in") or 0.0), 3)
            ficha["reanclada"] = sid or True
        else:
            ficha["descolgada"] = True
        salida.append(ficha)
    return salida


# ===========================================================================
# DEL SEGUNDO AL CONTEXTO
# ===========================================================================

def plano_en(cortes, segundo) -> str:
    """Qué plano estaba en pantalla en ese instante. -> id o ""

    `cortes` es [{"id", "t_in", "t_out"}] con los tiempos del vídeo que se
    está viendo. Se busca por intervalo y no por índice: los planos no
    duran lo mismo.
    """
    segundo = float(segundo or 0.0)
    for corte in (cortes or []):
        try:
            if float(corte.get("t_in") or 0) <= segundo < float(corte.get("t_out") or 0):
                return str(corte.get("id") or "")
        except (TypeError, ValueError):
            continue
    return str((cortes or [{}])[-1].get("id") or "") if cortes else ""


def contexto_de_nota(nota, cortes, planos_por_id) -> dict:
    """Todo lo que rodea a un instante: el plano, su narración, sus vecinos.

    Es lo que se le da al enrutador para que no tenga que adivinar de qué
    habla «aquí». `planos_por_id` es el plan de assets ({id: plano}), de
    donde salen la cartela y el rótulo.
    """
    sid = str(nota.get("plano") or "")
    orden = [c.get("id") for c in (cortes or []) if c.get("id")]
    corte = next((c for c in (cortes or []) if c.get("id") == sid), {})
    plano = planos_por_id.get(sid) or {}
    indice = orden.index(sid) if sid in orden else -1
    return {
        "plano": sid,
        "narracion": str(corte.get("narracion") or ""),
        "rotulo": str(plano.get("texto_rotulo") or ""),
        "cartela": (plano.get("cartela") or {}).get("plantilla") or ""
                   if isinstance(plano.get("cartela"), dict) else "",
        "anterior": orden[indice - 1] if indice > 0 else "",
        "siguiente": orden[indice + 1]
                     if 0 <= indice < len(orden) - 1 else "",
        "t_in": corte.get("t_in"),
    }


# ===========================================================================
# EL ENRUTADOR
# ===========================================================================

SISTEMA = """Repartes el repaso de un vídeo ya montado en cambios concretos.
Eliges el cambio MÁS BARATO que resuelve cada nota, no el más completo:
cada cambio arrastra un trabajo distinto (redibujar una capa es gratis;
una imagen se paga; reescribir lo que se dice cuesta la locución).
Cuando una nota no se pueda arreglar con ningún cambio de la tabla, usa
«anotar»: se queda escrito para decidirlo a mano, y es una salida
legítima. Responde exclusivamente con el objeto JSON pedido, sin texto
alrededor."""

INSTRUCCION = """Vídeo: «{titulo}» ({duracion})
Estado del pipeline: {estado}

EL VOCABULARIO DE CAMBIOS (no hay ninguno más; uno inventado se descarta):
{cambios}

LAS NOTAS ({cuantas}), cada una con lo que había en pantalla:
{notas}

Devuelve SOLO este objeto JSON, con UNA entrada por nota y en el mismo
orden:

{{"notas": [
  {{"id": "R001",
    "entendido": "qué pide esta nota, en una línea y con tus palabras",
    "ambito": "subtitulo",
    "cambios": [{{"tipo": "subtitulo_texto", "plano": "S003",
                  "texto": "..."}}]}}
]}}

Reglas:
  · `cambios` puede llevar más de uno si la nota pide dos cosas, y vacío
    si no pide ninguna acción (una felicitación, una duda).
  · Los tipos y los campos son EXACTAMENTE los de la tabla.
  · `feedback_plano` lleva su `texto` EN INGLÉS: va derecho al modelo de
    imagen. Di qué QUITAR y qué PONER, en una o dos frases.
  · `subtitulo_texto` es el cambio BARATO: corrige lo que se LEE sin
    tocar lo que se oye. Escribe el rótulo entero ya corregido (te doy
    el actual en «rótulo actual»).
  · `escena_texto` es lo que se DICE: reescribe la narración de esa
    escena y cuesta volver a grabarla. Con las cifras en letra.
  · Si una nota se repite en todo el vídeo (tamaño del rótulo, set de
    grafismo, velocidad), usa el cambio GLOBAL una sola vez.
"""


def _notas_legibles(notas, contextos) -> str:
    piezas = []
    for nota in notas:
        contexto = contextos.get(nota["id"]) or {}
        trozos = [f"--- {nota['id']} · minuto {_reloj(nota.get('t'))} ---",
                  f"lo que escribió: {nota.get('texto')}"]
        if contexto.get("plano"):
            trozos.append(f"plano en pantalla: {contexto['plano']}")
        if contexto.get("narracion"):
            trozos.append(f"se estaba narrando: {contexto['narracion']}")
        if contexto.get("rotulo"):
            trozos.append(f"rótulo actual: {contexto['rotulo']}")
        if contexto.get("cartela"):
            trozos.append(f"lleva cartela: {contexto['cartela']}")
        if contexto.get("anterior") or contexto.get("siguiente"):
            trozos.append(f"planos de al lado: {contexto.get('anterior') or '-'}"
                          f" → {contexto.get('siguiente') or '-'}")
        piezas.append("\n".join(trozos))
    return "\n\n".join(piezas)


def _reloj(segundos) -> str:
    try:
        total = int(float(segundos or 0))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60}:{total % 60:02d}"


def _cambios_legibles() -> str:
    lineas = []
    for tipo, ficha in CAMBIOS.items():
        campos = ", ".join(sorted(ficha["campos"])) or "sin campos"
        rehacer = ", ".join(ficha["rehacer"]) or "nada"
        lineas.append(f"  · {tipo} ({ficha['ambito']}) — {ficha['que_es']}. "
                      f"Campos: {campos}. Rehace: {rehacer}.")
    return "\n".join(lineas)


def enrutar(notas, contextos, titulo="", duracion=0.0, estado="",
            proyecto_id=None, ambitos_vetados=(), avisar=None) -> dict:
    """De las notas a los cambios, validados. -> {notas, cambios, avisos}

    `ambitos_vetados` son los ámbitos que ESTA pantalla no arregla: se
    comprueba al validar, no en el prompt — pedírselo al modelo es
    pedirlo; comprobarlo es tenerlo. Y así la nota no se pierde: se
    devuelve un aviso con su id diciendo dónde se arregla.
    """
    avisar = avisar or (lambda *_: None)
    notas = [n for n in (notas or []) if n.get("texto")]
    if not notas:
        return {"notas": [], "cambios": [],
                "avisos": ["no hay notas que aplicar"]}
    vetados = {str(a) for a in (ambitos_vetados or ())}
    llamada = llm.rol_config("repaso", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = INSTRUCCION.format(
        titulo=titulo or "sin título",
        duracion=f"{_reloj(duracion)} ({duracion:.1f} s)" if duracion else "?",
        estado=estado or "-",
        cambios=_cambios_legibles(),
        cuantas=len(notas),
        notas=_notas_legibles(notas, contextos or {}))
    llamada.contexto = "repaso"
    llamada.proyecto = proyecto_id or ""
    avisar(f"leyendo {len(notas)} nota(s) del repaso")
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())
    respuesta = crudo.get("notas") if isinstance(crudo, dict) else crudo
    salida, avisos = [], []
    por_id = {n["id"]: n for n in notas}
    for item in (respuesta or []):
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "")
        if nid not in por_id:
            continue
        cambios = []
        for propuesto in (item.get("cambios") or []):
            cambio, motivo = validar_cambio(propuesto)
            if cambio and cambio.get("ambito") in vetados:
                donde = DONDE_SE_ARREGLA.get(cambio["ambito"], "otra pantalla")
                avisos.append(f"{nid}: eso no se arregla aquí. {donde}")
                continue
            if cambio:
                cambios.append(cambio)
            elif motivo:
                avisos.append(f"{nid}: {motivo}")
        salida.append({
            "id": nid,
            "texto": por_id[nid]["texto"],
            "entendido": " ".join(str(item.get("entendido") or "").split()),
            "ambito": (str(item.get("ambito") or "").strip()
                       if str(item.get("ambito") or "").strip() in AMBITOS
                       else (cambios[0]["ambito"] if cambios else "nota")),
            "cambios": cambios,
        })
    sin_respuesta = [n["id"] for n in notas
                     if n["id"] not in {s["id"] for s in salida}]
    if sin_respuesta:
        avisos.append("estas notas no se han podido repartir y se quedan sin "
                      "aplicar: " + ", ".join(sin_respuesta))
    return {"notas": salida,
            "cambios": [c for s in salida for c in s["cambios"]],
            "avisos": avisos}


# ===========================================================================
# QUÉ HAY QUE REHACER
# ===========================================================================

#: El orden del pipeline (el del grafo, y por eso una lista y no un
#: conjunto: aplicar diez cambios rehace las cosas en el orden en que
#: dependen unas de otras).
ORDEN = ("ingesta", "brief", "guion", "voz", "revision_audio",
         "assets", "callouts", "render")


def tareas_de(cambios) -> list[str]:
    """Las pasos que hay que volver a correr, en orden de pipeline.

    ESTO ES EL AHORRO: una nota sobre el rótulo devuelve
    `['callouts', 'render']` y nada más — aplicarla no vuelve a pagar
    ninguna imagen.
    """
    pedidas = set()
    for cambio in (cambios or []):
        pedidas.update(cambio.get("rehacer") or [])
    return [t for t in ORDEN if t in pedidas]


def resumen_de(reparto: dict) -> dict:
    """Una línea por ámbito con lo que se va a hacer, para enseñarlo antes."""
    cuenta: dict[str, int] = {}
    for nota in (reparto or {}).get("notas") or []:
        cuenta[nota["ambito"]] = cuenta.get(nota["ambito"], 0) + 1
    partes = [f"{n} de {ambito}" for ambito, n in sorted(cuenta.items())]
    tareas = tareas_de((reparto or {}).get("cambios") or [])
    return {"por_ambito": cuenta,
            "frase": " · ".join(partes) or "nada que aplicar",
            "tareas": tareas,
            "cuesta_imagenes": "assets" in tareas,
            "cuesta_voz": any(t in ("voz", "guion") for t in tareas)}
