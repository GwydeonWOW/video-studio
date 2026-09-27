"""Paso 4 — voz: narración con ElevenLabs, escena a escena.

Por escena: TTS con marcas de tiempo (alineación por palabra) -> mp3 +
duración real. La duración real sustituye a la estimada del guion: el
vídeo se mide con lo que se oyó, no con lo que se pensó.

Coste: caracteres consumidos, apuntados al generar (medidor).
"""
from __future__ import annotations

from pathlib import Path

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import voz_elevenlabs


def params_defecto() -> dict:
    # voz por defecto de Eleven Labs (Rachel); la pantalla lista las demas.
    return {"voz": "21m00Tcm4TlvDq8ikWAM", "modelo": "multilingual",
            "estabilidad": 0.5, "similitud": 0.75, "velocidad": 1.0}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": "?",
            "coste": None}


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    claves = comun.claves_actuales()
    if not voz_elevenlabs.clave(claves):
        raise voz_elevenlabs.ErrorVoz(
            "falta la clave de ElevenLabs (Configuracion -> claves)")
    carpeta = proyecto.carpeta_paso("voz") / "audio"
    carpeta.mkdir(parents=True, exist_ok=True)
    salida, total = [], 0.0
    for indice, escena in enumerate(escenas, start=1):
        trabajo.comprobar_cancelacion()
        narracion = escena["narracion"]
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


def regrabar_escena(proyecto: Proyecto, escena_id: str, params: dict) -> dict:
    """Regraba UNA escena (boton de la pantalla de repaso). -> ficha nueva"""
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escena = next((e for e in guion.get("escenas", [])
                   if e["id"] == escena_id), None)
    if escena is None:
        raise ValueError(f"escena inexistente: {escena_id}")
    claves = comun.claves_actuales()
    destino = proyecto.carpeta_paso("voz") / "audio" / f"{escena_id}.mp3"
    marca = voz_elevenlabs.hablar_con_marcas(
        escena["narracion"], params.get("voz", params_defecto()["voz"]),
        destino, claves=claves, modelo=params.get("modelo", "multilingual"),
        estabilidad=float(params.get("estabilidad", 0.5)),
        similitud=float(params.get("similitud", 0.75)),
        velocidad=float(params.get("velocidad", 1.0)))
    duracion = comun.duracion_de(destino) or marca["duracion"]
    anotar_operacion(
        datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="voz",
        proveedor="elevenlabs", modelo=params.get("modelo", "multilingual"),
        caracteres=len(escena["narracion"]), contexto=f"voz:{escena_id}",
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
