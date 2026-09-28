"""Claves de API: lectura segura, listado enmascarado y prueba.

Fuentes (en orden): variables de entorno (Coolify) y `secretos/claves.json`
en el volumen. La UI JAMAS recibe una clave: solo etiqueta, ultimos 4 y
estado (patron del original, docs/AUDITORIA.md H4).

Formato de claves.json:

    {
      "llm":        {"glm": "...", "openai": "...", "anthropic": "..."},
      "openai":     "...",        // imagenes (misma clave de OpenAI)
      "elevenlabs": "..."
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from .proyecto import escribir_json, leer_json
except ImportError:
    from proyecto import escribir_json, leer_json  # type: ignore

#: (clave interna, etiqueta humana, variable de entorno, para_que)
CATALOGO = [
    ("glm", "GLM (z.ai)", "ESTUDIO_GL_KEY", "guion y textos"),
    ("openai", "OpenAI", "ESTUDIO_OPENAI_KEY", "gpt + imagenes"),
    ("anthropic", "Anthropic", "ESTUDIO_ANTHROPIC_KEY", "claude (opcional)"),
    ("elevenlabs", "ElevenLabs", "ESTUDIO_ELEVENLABS_KEY", "voz"),
    ("jamendo", "Jamendo", "ESTUDIO_JAMENDO_ID", "musica de fondo"),
    ("freesound", "FreeSound", "ESTUDIO_FREESOUND_KEY", "efectos de sonido"),
]

#: variables de entorno -> campo en claves.json
_ENTORNO_A_JSON = {
    "ESTUDIO_GL_KEY": ("llm", "glm"),
    "ESTUDIO_OPENAI_KEY": ("openai", None),
    "ESTUDIO_ANTHROPIC_KEY": ("llm", "anthropic"),
    "ESTUDIO_ELEVENLABS_KEY": ("elevenlabs", None),
    "ESTUDIO_JAMENDO_ID": ("jamendo", None),
    "ESTUDIO_FREESOUND_KEY": ("freesound", None),
}


def fichero(carpeta: Path | str) -> Path:
    return Path(carpeta) / "claves.json"


def leer_claves(carpeta: Path | str) -> dict:
    """Todas las claves planas {glm, openai, anthropic, elevenlabs}."""
    planas: dict[str, str] = {}
    datos = leer_json(fichero(carpeta), {})
    if isinstance(datos, dict):
        llm = datos.get("llm") or {}
        planas.update({k: v for k, v in llm.items() if isinstance(v, str)})
        for campo in ("openai", "elevenlabs", "jamendo", "freesound"):
            if isinstance(datos.get(campo), str):
                planas[campo] = datos[campo]
    for variable, (seccion, campo) in _ENTORNO_A_JSON.items():
        valor = os.environ.get(variable, "")
        if valor and (campo or seccion) not in planas:
            planas[campo or seccion] = valor
    return {k: v for k, v in planas.items() if v}


def guardar_claves(carpeta: Path | str, nuevas: dict[str, str]) -> None:
    """Escribe solo los campos que llegan (los vacios no borran nada).

    Escribe con 0600. Nunca se guarda una cadena vacia: borrar una clave es
    explicito con null.
    """
    destino = fichero(carpeta)
    datos = leer_json(destino, {})
    if not isinstance(datos, dict):
        datos = {}
    limpias = {k: v for k, v in nuevas.items() if v}
    for clave, valor in limpias.items():
        if clave in ("glm", "anthropic"):
            datos.setdefault("llm", {})
            datos["llm"][clave] = valor
        elif clave in ("openai", "elevenlabs", "jamendo", "freesound"):
            datos[clave] = valor
    escribir_json(destino, datos)
    try:
        destino.chmod(0o600)
    except OSError:
        pass


def enmascaradas(carpeta: Path | str) -> list[dict]:
    """Estado de cada clave para la pantalla (sin el valor)."""
    claves = leer_claves(carpeta)
    lista = []
    for clave, etiqueta, variable, uso in CATALOGO:
        valor = claves.get(clave, "")
        lista.append({
            "clave": clave, "etiqueta": etiqueta, "uso": uso,
            "variable": variable,
            "presente": bool(valor),
            "mascara": f"...{valor[-4:]}" if len(valor) >= 8 else
                       ("****" if valor else ""),
        })
    return lista


def probar_claves(carpeta: Path | str) -> dict:
    """Prueba cada clave contra su servicio, sin coste.

    Devuelve {clave: {"ok": bool, "detalle": str}}. Cada prueba llama al
    servicio real con una operacion gratuita (listar modelos/voces).
    """
    import requests

    claves = leer_claves(carpeta)
    resultados: dict[str, dict] = {}

    if claves.get("glm"):
        try:
            r = requests.get("https://api.z.ai/api/paas/v4/models",
                             headers={"Authorization": f"Bearer {claves['glm']}"},
                             timeout=30)
            resultados["glm"] = {"ok": r.status_code == 200,
                                 "detalle": f"{r.status_code}"}
        except requests.RequestException as e:
            resultados["glm"] = {"ok": False, "detalle": f"red: {e}"}
    if claves.get("openai"):
        try:
            r = requests.get("https://api.openai.com/v1/models",
                             headers={"Authorization": f"Bearer {claves['openai']}"},
                             timeout=30)
            resultados["openai"] = {
                "ok": r.status_code == 200,
                "detalle": "valida (saldo no comprobable)" if r.status_code == 200
                else f"{r.status_code}"}
        except requests.RequestException as e:
            resultados["openai"] = {"ok": False, "detalle": f"red: {e}"}
    if claves.get("anthropic"):
        try:
            r = requests.get("https://api.anthropic.com/v1/models",
                             headers={"x-api-key": claves["anthropic"],
                                      "anthropic-version": "2023-06-01"},
                             timeout=30)
            resultados["anthropic"] = {"ok": r.status_code == 200,
                                       "detalle": f"{r.status_code}"}
        except requests.RequestException as e:
            resultados["anthropic"] = {"ok": False, "detalle": f"red: {e}"}
    if claves.get("elevenlabs"):
        try:
            r = requests.get("https://api.elevenlabs.io/v1/user",
                             headers={"xi-api-key": claves["elevenlabs"]},
                             timeout=30)
            detalle = f"{r.status_code}"
            if r.status_code == 200:
                sub = r.json().get("subscription", {})
                detalle = (f"cuota {sub.get('character_count', '?')}/"
                           f"{sub.get('character_limit', '?')}")
            resultados["elevenlabs"] = {"ok": r.status_code == 200,
                                        "detalle": detalle}
        except requests.RequestException as e:
            resultados["elevenlabs"] = {"ok": False, "detalle": f"red: {e}"}
    if claves.get("jamendo"):
        try:
            r = requests.get("https://api.jamendo.com/v3.0/tracks/",
                             params={"client_id": claves["jamendo"],
                                     "format": "json", "limit": 1},
                             timeout=30)
            ok = (r.status_code == 200
                  and (r.json().get("headers") or {}).get("status") == "success")
            resultados["jamendo"] = {"ok": ok, "detalle": f"{r.status_code}"}
        except requests.RequestException as e:
            resultados["jamendo"] = {"ok": False, "detalle": f"red: {e}"}
    if claves.get("freesound"):
        try:
            r = requests.get("https://freesound.org/apiv2/search/text/",
                             params={"query": "whoosh", "page_size": 1},
                             headers={"Authorization":
                                      "Token " + claves["freesound"]},
                             timeout=30)
            resultados["freesound"] = {"ok": r.status_code == 200,
                                       "detalle": f"{r.status_code}"}
        except requests.RequestException as e:
            resultados["freesound"] = {"ok": False, "detalle": f"red: {e}"}
    return resultados
