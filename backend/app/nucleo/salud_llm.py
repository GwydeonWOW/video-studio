"""Cómo respondió cada proveedor de LLM la última vez que se le habló.

Puerto de la salud de las cuentas del CLI del original: «con clave» no
es «funciona». Una clave puede estar puesta y con el cupo agotado, o ser
inválida, o el proveedor colgándose — y la pantalla lo pintaba todo en
verde («clave puesta», que es lo único que sabe decir el catálogo)
hasta que alguien generaba algo y se comía un error de seiscientos
caracteres. Aquí se apunta LO ÚLTIMO QUE PASÓ con cada proveedor, y la
pantalla lo enseña al lado de la clave (Configuración).

DE DÓNDE SALE
-------------
De dos sitios:

  1. **De cada llamada de verdad.** `motores/llm.py` (`llamar` y
     `llamar_conversacion`, los únicos sitios por los que pasa toda
     llamada) anota al volver si fue bien o qué falló. Así un cupo
     agotado a mitad de una tanda se ve al momento, sin que nadie haya
     preguntado nada.
  2. **De la prueba de clave** (`llm.probar`, el botón «Probar» de
     Configuración): una llamada sin coste que falla rápido.

LOS ESTADOS, que son los que pinta la pantalla:

    ok       contestó
    cupo     429 o cuota agotada; el mensaje del proveedor suele traer
             cuándo se renueva (lo saca `renueva`)
    sesion   la clave no vale (401/403): hay que volver a ponerla
    tiempo   no contestó a tiempo (timeout de red)
    error    cualquier otra cosa, con el texto tal cual

Se guarda en `<datos>/salud_llm.json`. Un fichero y no memoria porque
el servicio se reinicia y un cupo agotado el martes sigue agotado el
miércoles. La ruta se mira EN CADA LLAMADA y no al importar: las suites
redirigen `ESTUDIO_DATOS` después de importar la app.

LO QUE NO HACE: no decide por su cuenta que un cupo se ha renovado. Un
estado malo se queda hasta que una llamada —de verdad o de prueba—
vuelve a salir bien.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

_LOCK = threading.RLock()

ESTADOS = ("ok", "cupo", "sesion", "tiempo", "error")


def fichero() -> "os.PathLike | str":
    """Dónde se guarda. Redirigible con `ESTUDIO_SALUD_LLM`."""
    desde_entorno = os.environ.get("ESTUDIO_SALUD_LLM")
    if desde_entorno:
        return desde_entorno
    from ..config import AJUSTES          # diferido: nucleo no arranca config
    return AJUSTES.datos / "salud_llm.json"


def leer() -> dict:
    """{proveedor: ficha}. Un fichero ilegible es uno vacío, no un error."""
    try:
        with open(fichero(), "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir(datos: dict) -> None:
    ruta = fichero()
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    temporal = None
    try:
        with open(os.path.join(carpeta, f".salud_llm.{os.getpid()}.tmp"),
                  "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            temporal = fh.name
        os.replace(temporal, ruta)
        temporal = None
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def anotar(proveedor: str, estado: str, mensaje: str = "",
           para: str = "") -> dict:
    """Apunta cómo respondió ese proveedor. -> la ficha escrita."""
    if estado not in ESTADOS:
        raise ValueError(f"estado desconocido: {estado!r}")
    ficha = {
        "estado": estado,
        "mensaje": " ".join(str(mensaje or "").split())[:600],
        "para": str(para or "")[:120],
        "cuando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "epoch": int(time.time()),
    }
    with _LOCK:
        datos = leer()
        datos[str(proveedor)] = ficha
        _escribir(datos)
    return dict(ficha)


def de(proveedor: str) -> dict | None:
    """La ficha de ese proveedor, o None si nunca se le ha hablado."""
    ficha = leer().get(str(proveedor))
    return dict(ficha) if isinstance(ficha, dict) else None


# ---------------------------------------------------------------- clasificar

def clasificar(texto: str) -> str:
    """El estado que pinta la pantalla a partir de lo que dijo el proveedor.

    Los códigos de HTTP van primero (son lo más fiable que llega); el
    texto solo distingue «no queda cupo» de «la clave no vale».
    """
    bajo = " ".join(str(texto).lower().split())
    if any(pista in bajo for pista in ("429", "rate limit", "rate_limit",
                                       "quota", "cuota")):
        return "cupo"
    if any(pista in bajo for pista in ("401", "403", "unauthorized",
                                       "invalid api key", "authentication",
                                       "credencial", "sin clave")):
        return "sesion"
    if any(pista in bajo for pista in ("timed out", "timeout",
                                       "read timeout", "connect timeout")):
        return "tiempo"
    return "error"


def describir(ficha: dict | None, etiqueta: str = "") -> str:
    """Una frase para la pantalla, o '' si no hay nada apuntado."""
    if not isinstance(ficha, dict):
        return ""
    quien = f"de {etiqueta} " if etiqueta else ""
    estado = ficha.get("estado")
    mensaje = ficha.get("mensaje") or ""
    if estado == "ok":
        return f"la clave {quien}contesta (comprobado {ficha.get('cuando', '?')})"
    if estado == "cupo":
        return f"la clave {quien}tiene el cupo agotado: {mensaje}"
    if estado == "sesion":
        return f"la clave {quien}no es válida: {mensaje}"
    if estado == "tiempo":
        return f"la clave {quien}no contestó a tiempo: {mensaje}"
    return f"la clave {quien}ha fallado: {mensaje}"


def renueva(ficha: dict | None) -> str:
    """El trozo del mensaje que dice cuándo se renueva el cupo, si lo dice."""
    if not isinstance(ficha, dict) or ficha.get("estado") != "cupo":
        return ""
    m = re.search(r"(resets?|renueva|se renueva|renovar[aá]?)\s*:?\s*(.+)$",
                  ficha.get("mensaje") or "", re.I)
    return m.group(2).strip() if m else ""
