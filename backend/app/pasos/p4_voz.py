"""Paso 4 — voz: UNA toma continua para todo el vídeo (ElevenLabs).

Sintetizar escena a escena suena a robot leyendo una lista: cada frase
arranca en frío, sin memoria de la anterior, y en el montaje se oyen los
empalmes. Con una toma única la entonación fluye de una escena a la
siguiente, y los cortes se deducen después de las marcas de palabra, que
son exactas. El aire entre escenas se consigue ensanchando el silencio de
la pista ya grabada con RUIDO DE SALA de la propia pausa
(voz_elevenlabs.espaciar), nunca troceando la síntesis.

Después la toma se corta por escenas (por la mitad del hueco entre la
última palabra de una y la primera de la siguiente): cada escena conserva
su ficha de siempre —audio propio + marcas en su reloj— así que repaso,
planos, subtítulos y render no se enteran de que debajo hay una sola toma.

Las anotaciones de voz del guion (`<break .../>`, ver marcas_tts) viajan
en el texto y ElevenLabs las convierte en silencio de verdad: aportan la
prosodia que un silencio pegado después no puede aportar.

`modo: "por_escena"` mantiene el comportamiento antiguo (una llamada por
escena), y las regrabaciones del repaso siempre van por escena: regrabar
el vídeo entero para cambiar una escena es pagar el doble.

Coste: caracteres consumidos, apuntados al generar (medidor).
"""
from __future__ import annotations

import json

from ..config import AJUSTES
from ..motores import llm
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import comun, marcas_tts, p2_brief
from ..motores import voz_elevenlabs


def params_defecto() -> dict:
    # voz por defecto de Eleven Labs (Rachel); la pantalla lista las demas.
    # hueco_minimo: aire garantizado ENTRE escenas en la toma continua.
    return {"voz": "21m00Tcm4TlvDq8ikWAM", "modelo": "multilingual",
            "estabilidad": 0.5, "similitud": 0.75, "velocidad": 1.0,
            "modo": "continua", "hueco_minimo": 1.0}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": "?",
            "coste": None}


def formato_de_salida(proyecto: Proyecto) -> str:
    """El porte del vídeo («horizontal» | «vertical»), del único sitio
    donde vive la decisión: el brief. Primero sus datos (ya ejecutado,
    `formato_salida` es lo que dejó correr el paso) y, si no ha corrido,
    sus params guardados. Un proyecto anterior al mando —o sin él— es
    horizontal, que es lo que hubo siempre.

    Todos los pasos que necesitan el cuadro (p6 pide las imágenes al
    tamaño justo, p8 monta el MP4) pasan por aquí: la decisión no se
    recalcula en ninguno otro sitio.
    """
    brief = p2_brief.proyecto_leer_datos(proyecto, "brief")
    if brief.get("formato_salida"):
        return comun.normalizar_formato(brief["formato_salida"])
    from ..nucleo.estado import Estado
    params = (Estado(proyecto).paso("brief") or {}).get("params") or {}
    return comun.normalizar_formato(params.get("formato"))


def ejecutar(proyecto: Proyecto, params: dict, trabajo,
             solo_escenas: list | None = None) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    if solo_escenas:
        # regrabar UNA escena (repaso) no vuelve a pagar las demás
        escenas = [e for e in escenas if e["id"] in solo_escenas]
        if not escenas:
            raise ValueError("ninguna de esas escenas está en el guion")
    claves = comun.claves_actuales()
    if not voz_elevenlabs.clave(claves):
        raise voz_elevenlabs.ErrorVoz(
            "falta la clave de ElevenLabs (Configuracion -> claves)")
    carpeta = proyecto.carpeta_paso("voz") / "audio"
    carpeta.mkdir(parents=True, exist_ok=True)
    if (str(params.get("modo") or "continua") == "continua"
            and not solo_escenas and len(escenas) > 1):
        return _voz_continua(proyecto, params, escenas, claves, carpeta,
                             trabajo)
    salida, total = [], 0.0
    for indice, escena in enumerate(escenas, start=1):
        trabajo.comprobar_cancelacion()
        # las anotaciones del guion viajan con el texto; el motor las calla
        narracion = marcas_tts.para_tts(marcas_tts.sanear(escena["narracion"]))
        trabajo.avance(f"voz {indice}/{len(escenas)}: {escena['id']}")
        destino = carpeta / f"{escena['id']}.mp3"
        marca = voz_elevenlabs.hablar_con_marcas(
            narracion, params.get("voz", params_defecto()["voz"]), destino,
            claves=claves, modelo=params.get("modelo", "multilingual"),
            estabilidad=float(params.get("estabilidad", 0.5)),
            similitud=float(params.get("similitud", 0.75)),
            velocidad=float(params.get("velocidad", 1.0)))
        # duracion real (ffprobe manda si esta; si no, la de las marcas)
        duracion = comun.duracion_de(destino) or marca["duracion"]
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="voz",
            proveedor="elevenlabs", modelo=params.get("modelo", "multilingual"),
            caracteres=len(narracion), contexto=f"voz:{escena['id']}",
            proyecto_dir=proyecto.raiz)
        salida.append({"id": escena["id"], "audio": f"pasos/voz/audio/{escena['id']}.mp3",
                       "duracion": duracion, "palabras": marca["palabras"]})
        total += duracion
    trabajo.avance(f"voz completa: {len(salida)} escenas, {round(total)} s")
    return {"escenas": salida, "duracion": round(total, 3)}


# ------------------------------------------------------------- toma continua

def _voz_continua(proyecto: Proyecto, params: dict, escenas: list,
                  claves: dict, carpeta, trabajo) -> dict:
    """TODO el vídeo en una toma, cortado después por escenas.

    La toma se graba entera (prosodia continua), se ensancha el aire entre
    escenas con ruido de sala (`espaciar`, sin re-sintetizar) y se corta
    por la mitad de cada hueco: cada escena sale con su audio propio y sus
    marcas en SU reloj, que es el contrato que ya consumen el repaso, los
    planos, los subtítulos y el render.
    """
    sr2 = voz_elevenlabs.SR * 2
    textos = [t for t in (marcas_tts.para_tts(
        marcas_tts.sanear(e.get("narracion"))) for e in escenas) if t]
    transcript = " ".join(textos)
    if not transcript:
        raise ValueError("el guion no tiene narracion que locutar")
    trabajo.avance(f"toma única: {len(escenas)} escenas, "
                   f"{len(transcript)} caracteres")
    destino = carpeta / "_toma.mp3"
    marca = voz_elevenlabs.hablar_con_marcas(
        transcript, params.get("voz", params_defecto()["voz"]), destino,
        claves=claves, modelo=params.get("modelo", "multilingual"),
        estabilidad=float(params.get("estabilidad", 0.5)),
        similitud=float(params.get("similitud", 0.75)),
        velocidad=float(params.get("velocidad", 1.0)))
    # defensa: si alguna marca llegara con restos de etiqueta, no es una
    # palabra y el reparto la estaría esperando en vano
    palabras = [p for p in marca["palabras"]
                if not marcas_tts.es_token_de_etiqueta(p["palabra"])]
    # el reparto empareja lo que el guion DICE (limpio) con lo que el motor
    # devolvió, con tolerancia por si parte o une tokens
    limpias = [{"id": e["id"],
                "narracion": marcas_tts.limpiar(e.get("narracion"))}
               for e in escenas]
    reparto = voz_elevenlabs.repartir_palabras(limpias, palabras)
    pcm = voz_elevenlabs.pcm_de_mp3(destino.read_bytes())

    hueco = max(0.0, float(params.get("hueco_minimo", 1.0)))
    if hueco > 0 and len(escenas) > 1:
        pcm, desplazamientos = voz_elevenlabs.espaciar(pcm, reparto, hueco)
        if desplazamientos:
            for tramo in reparto.values():
                for p in tramo:
                    p["inicio"] = voz_elevenlabs.aplicar_desplazamiento(
                        p["inicio"], desplazamientos)
                    p["fin"] = voz_elevenlabs.aplicar_desplazamiento(
                        p["fin"], desplazamientos)
            trabajo.avance(
                f"aire entre escenas: {len(desplazamientos)} corte(s), "
                f"+{desplazamientos[-1]['retardo']:.2f} s de ruido de sala")

    total = len(pcm) / sr2
    ids = [e["id"] for e in escenas]
    starts, ends = {ids[0]: 0.0}, {ids[-1]: total}
    con_voz = [sid for sid in ids if reparto.get(sid)]
    for anterior, siguiente in zip(con_voz, con_voz[1:]):
        fin = reparto[anterior][-1]["fin"]
        arranque = reparto[siguiente][0]["inicio"]
        corte = fin + (arranque - fin) / 2
        ends[anterior] = corte
        starts[siguiente] = corte
    # una escena sin reparto propio hereda el corte del vecino
    for k in range(len(ids) - 1, -1, -1):
        if ids[k] not in ends:
            posterior = next((starts[ids[j]] for j in range(k + 1, len(ids))
                              if ids[j] in starts), total)
            ends[ids[k]] = posterior
    for k, sid in enumerate(ids):
        if sid not in starts:
            previo = next((ends[ids[j]] for j in range(k - 1, -1, -1)
                           if ids[j] in ends), 0.0)
            starts[sid] = previo

    salida, total_fichas = [], 0.0
    for escena in escenas:
        trabajo.comprobar_cancelacion()
        sid = escena["id"]
        t0 = starts[sid]
        t1 = min(total, max(ends[sid], t0 + 0.05))
        trozo = pcm[int(t0 * sr2) & ~1:int(t1 * sr2) & ~1]
        fichero = carpeta / f"{sid}.wav"
        fichero.write_bytes(voz_elevenlabs.wav_de_pcm(trozo))
        duracion = round(len(trozo) / sr2, 3)
        propias = [{"palabra": p["palabra"],
                    "inicio": round(max(0.0, p["inicio"] - t0), 3),
                    "fin": round(max(0.0, p["fin"] - t0), 3)}
                   for p in reparto.get(sid, [])]
        salida.append({"id": sid, "audio": f"pasos/voz/audio/{sid}.wav",
                       "duracion": duracion, "palabras": propias})
        total_fichas += duracion
        trabajo.avance(f"{sid}: {duracion:g} s de la toma")
    anotar_operacion(
        datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="voz",
        proveedor="elevenlabs", modelo=params.get("modelo", "multilingual"),
        caracteres=len(transcript), contexto="voz:toma_continua",
        proyecto_dir=proyecto.raiz)
    trabajo.avance(f"toma completa: {len(salida)} escenas, "
                   f"{round(total_fichas)} s")
    return {"escenas": salida, "duracion": round(total_fichas, 3),
            "modo": "continua"}


def regrabar_escena(proyecto: Proyecto, escena_id: str, params: dict) -> dict:
    """Regraba UNA escena (boton de la pantalla de repaso). -> ficha nueva"""
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escena = next((e for e in guion.get("escenas", [])
                   if e["id"] == escena_id), None)
    if escena is None:
        raise ValueError(f"escena inexistente: {escena_id}")
    claves = comun.claves_actuales()
    destino = proyecto.carpeta_paso("voz") / "audio" / f"{escena_id}.mp3"
    narracion = marcas_tts.para_tts(marcas_tts.sanear(escena["narracion"]))
    marca = voz_elevenlabs.hablar_con_marcas(
        narracion, params.get("voz", params_defecto()["voz"]),
        destino, claves=claves, modelo=params.get("modelo", "multilingual"),
        estabilidad=float(params.get("estabilidad", 0.5)),
        similitud=float(params.get("similitud", 0.75)),
        velocidad=float(params.get("velocidad", 1.0)))
    duracion = comun.duracion_de(destino) or marca["duracion"]
    anotar_operacion(
        datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="voz",
        proveedor="elevenlabs", modelo=params.get("modelo", "multilingual"),
        caracteres=len(narracion), contexto=f"voz:{escena_id}",
        proyecto_dir=proyecto.raiz)
    ficha = {"id": escena_id, "audio": f"pasos/voz/audio/{escena_id}.mp3",
             "duracion": duracion, "palabras": marca["palabras"]}
    # actualizar datos.json del paso (solo esa escena)
    from ..nucleo.proyecto import leer_json, escribir_json
    fichero = proyecto.carpeta_paso("voz") / "datos.json"
    datos = leer_json(fichero, {"escenas": [], "duracion": 0})
    escenas = [f if f["id"] != escena_id else ficha
               for f in datos.get("escenas", [])]
    if not any(f["id"] == escena_id for f in escenas):
        escenas.append(ficha)
    escenas.sort(key=lambda f: f["id"])
    datos["escenas"] = escenas
    datos["duracion"] = round(sum(f["duracion"] for f in escenas), 3)
    escribir_json(fichero, datos)
    return ficha


# ------------------------------------------------------------- previsualizar

FRASES_MUESTRA = {
    "es": "Esta es una prueba de voz del estudio. La escuchas tal y como "
          "sonará en el vídeo: mismo tono, mismo ritmo y misma velocidad "
          "que la narración final.",
    "en": "This is a studio voice test. You hear it exactly as it will "
          "sound in the video: same tone, same pace and same speed as the "
          "final narration.",
}


def _texto_de_muestra(proyecto: Proyecto, idioma: str, segundos: float) -> str:
    """Frases INICIALES del guion hasta llenar los segundos pedidos.

    Se prefiere el propio guion: así la previsualización suena al vídeo de
    verdad y no a una frase de cata.
    """
    tope_palabras = max(10, int(segundos * comun.RITMO_PALABRAS_S))
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    trozos: list[str] = []
    palabras = 0
    for escena in (guion or {}).get("escenas", []):
        for frase in comun.partir_en_frases(str(escena.get("narracion", "")),
                                            max_caracteres=200):
            trozos.append(frase)
            palabras += comun.palabras(frase)
            if palabras >= tope_palabras:
                return " ".join(trozos)
    if trozos:
        return " ".join(trozos)
    return FRASES_MUESTRA.get(idioma[:2], FRASES_MUESTRA["es"])


def previsualizar(proyecto: Proyecto, params: dict, segundos: float = 20.0) -> dict:
    """Sintetiza unos segundos con estos mandos de voz, para escucharlos.

    Va FUERA del versionado (previsualizacion.mp3): es una cata, no una
    toma. Cuesta los caracteres que suena — se anota al medidor.
    """
    idioma = str(proyecto.leer().get("idioma", "es"))
    texto = _texto_de_muestra(proyecto, idioma, segundos)
    # si la muestra sale del guion puede traer anotaciones: se locutan
    texto = marcas_tts.para_tts(marcas_tts.sanear(texto))
    destino = proyecto.carpeta_paso("voz") / "previsualizacion.mp3"
    voz_elevenlabs.hablar(
        texto, params.get("voz", params_defecto()["voz"]), destino,
        claves=comun.claves_actuales(),
        modelo=params.get("modelo", "multilingual"),
        estabilidad=float(params.get("estabilidad", 0.5)),
        similitud=float(params.get("similitud", 0.75)),
        velocidad=float(params.get("velocidad", 1.0)))
    anotar_operacion(
        datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="voz",
        proveedor="elevenlabs", modelo=params.get("modelo", "multilingual"),
        caracteres=len(texto), contexto="voz:previsualizar",
        proyecto_dir=proyecto.raiz)
    return {"archivo": "pasos/voz/previsualizacion.mp3",
            "url": f"/a/{proyecto.id}/pasos/voz/previsualizacion.mp3",
            "segundos": segundos, "caracteres": len(texto),
            "duracion": comun.duracion_de(destino)}


# ------------------------------------------------------------ voz descrita

def proponer_voz(proyecto: Proyecto, encargo: str, idioma: str,
                 trabajo=None) -> dict:
    """Elige voz y mandos a partir de una DESCRIPCIÓN en palabras.

    Devuelve una PROPUESTA: no toca los params. La voz se paga cada vez
    que se graba, así que aplicar a ciegas son dos tomas en vez de una —
    quien mira la propuesta y decide es la persona.
    """
    claves = comun.claves_actuales()
    catalogo = voz_elevenlabs.voces(claves)
    if not catalogo:
        raise voz_elevenlabs.ErrorVoz(
            "sin catálogo de voces: falta la clave de ElevenLabs "
            "(Configuración → claves)")
    if trabajo:
        trabajo.avance(f"{len(catalogo)} voces en la cuenta")
    # catalogo compacto para el prompt (etiquetas dicen mas que el nombre)
    fichas = []
    for voz in catalogo[:120]:
        etiquetas = voz.get("etiquetas") or {}
        fichas.append({"id": voz["voice_id"], "nombre": voz.get("nombre", ""),
                       "etiquetas": " · ".join(
                           f"{k}:{v}" for k, v in etiquetas.items() if v)})
    llamada = llm.rol_config("descripcion", comun.ajustes_llm())
    llamada.contexto = "voz:describir"
    llamada.proyecto = proyecto.id
    llamada.sistema = (
        "Eliges voz de locución para un vídeo de YouTube. Te dan cómo "
        "quiere que suene (encargo), el idioma y el catálogo de voces de "
        "ElevenLabs con sus etiquetas. Devuelve la MEJOR voz y los mandos "
        "de síntesis (estabilidad 0..1: baja = más emotiva e inestable; "
        "similitud 0..1: cuánto clona el timbre; velocidad 0.7..1.2). "
        "Modelo: 'multilingual' para narración normal, 'flash' si el "
        "encargo pide rapidez y poco costo.")
    llamada.instruccion = json.dumps({
        "encargo": encargo, "idioma": idioma or "es", "voces": fichas},
        ensure_ascii=False)
    propuesta = llm.llamar_json(llamada, claves=comun.claves_actuales())
    if not isinstance(propuesta, dict):
        raise llm.ErrorLLM("la propuesta de voz no es un objeto")
    # la voz DEBE existir en el catalogo: una alucinada no se puede grabar
    por_id = {v["voice_id"]: v for v in catalogo}
    elegida = por_id.get(str(propuesta.get("voz", "")))
    if elegida is None:
        elegida = por_id.get(params_defecto()["voz"]) or catalogo[0]
    def _flotante(clave, defecto, bajo, alto):
        try:
            valor = float(propuesta.get(clave, defecto))
        except (TypeError, ValueError):
            return defecto
        return round(min(max(valor, bajo), alto), 3)
    return {
        "voz": elegida["voice_id"],
        "voz_nombre": elegida.get("nombre", ""),
        "voz_etiquetas": elegida.get("etiquetas") or {},
        "modelo": (str(propuesta.get("modelo", "multilingual"))
                   if str(propuesta.get("modelo", "")) in voz_elevenlabs.MODELOS
                   else "multilingual"),
        "estabilidad": _flotante("estabilidad", 0.5, 0.0, 1.0),
        "similitud": _flotante("similitud", 0.75, 0.0, 1.0),
        "velocidad": _flotante("velocidad", 1.0, 0.7, 1.2),
        "motivo": str(propuesta.get("motivo", ""))[:600],
        "catalogo": len(catalogo),
    }
