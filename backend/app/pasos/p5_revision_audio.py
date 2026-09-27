"""Paso 5 — revisión de audio: chequeos deterministas, sin coste.

Compara cada escena con lo previsto:
- duracion real vs estimada del guion (desviacion grande = narracion rara)
- silencios al principio/fin (la voz arranca cortada o se traga el final)
- volumen bajo (pico por debajo de -20 dBFS)

No llama a ningun modelo: es la parada humana para REGRABAR escenas sueltas
(que actualizan voz por unidades) antes de pagar imagenes.
"""
from __future__ import annotations

import subprocess

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief


def params_defecto() -> dict:
    return {"tope_desviacion": 0.35, "pico_minimo_db": -20}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


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
