"""Capa LLM multi-proveedor: GLM (z.ai), OpenAI GPT y Claude (Anthropic).

Sustituye al CLI de claude del original por llamadas HTTPS directas, con un
enrutador por roles: cada papel del producto (guion, correccion, titulos...)
elige proveedor y modelo desde la configuracion, sin tocar codigo.

Esquemas soportados:
- "openai":     /chat/completions con {messages, ...}      (OpenAI y z.ai GLM)
- "anthropic":  /v1/messages  con {system, messages, ...}  (Claude API)

Seguridad: las instrucciones viajan como JSON por HTTPS (nunca por linea de
comandos — ver docs/AUDITORIA.md H2); los prompts son datos, no ejecutables.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

import requests

try:
    from ..nucleo.coste import anotar_operacion
except ImportError:  # uso suelto
    anotar_operacion = None  # type: ignore

TIEMPO_FUERA_S = 600
INTENTOS = 3

#: Proveedores conocidos. La clave puede vivir en ESTUDIO_GL_KEY,
#: ESTUDIO_OPENAI_KEY o ESTUDIO_ANTHROPIC_KEY, o en secretos/claves.json
#: (campo "llm": {"glm": "...", "openai": "...", "anthropic": "..."}).
PROVEEDORES = {
    "glm": {
        "nombre": "GLM (z.ai)",
        "esquema": "openai",
        "base": "https://api.z.ai/api/paas/v4",
        "modelos": ["glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-4.6"],
        "defecto": "glm-5.3",
        "variable": "ESTUDIO_GL_KEY",
    },
    "openai": {
        "nombre": "OpenAI GPT",
        "esquema": "openai",
        "base": "https://api.openai.com/v1",
        "modelos": ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5-mini"],
        "defecto": "gpt-6-sol",
        "variable": "ESTUDIO_OPENAI_KEY",
    },
    "anthropic": {
        "nombre": "Claude (Anthropic)",
        "esquema": "anthropic",
        "base": "https://api.anthropic.com/v1",
        "modelos": ["claude-sonnet-5", "claude-opus-5-5", "claude-haiku-4-5"],
        "defecto": "claude-sonnet-5",
        "variable": "ESTUDIO_ANTHROPIC_KEY",
    },
}

#: Papeles del producto y a que proveedor/modelo van por defecto. Se
#: sobreescribe desde la configuracion (api/ajustes) sin tocar esto.
ROLES_DEFECTO = {
    "guion": {"proveedor": "glm", "modelo": "glm-5.3"},
    "correccion": {"proveedor": "glm", "modelo": "glm-5.3"},
    "titulos": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "descripcion": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "direccion": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "redactor": {"proveedor": "glm", "modelo": "glm-5.3"},
    "cartelas": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "repaso": {"proveedor": "glm", "modelo": "glm-5.3"},
    "catalogo": {"proveedor": "glm", "modelo": "glm-5.3"},
    "conservacion": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "guia_estilo": {"proveedor": "glm", "modelo": "glm-5.3"},
}


class ErrorLLM(RuntimeError):
    """Fallo de la llamada al LLM, con texto para humano."""


@dataclass
class Llamada:
    """Parametros de una llamada (rol resuelto a proveedor+modelo)."""
    proveedor: str
    modelo: str
    sistema: str = ""
    instruccion: str = ""
    max_tokens: int = 8192
    temperatura: float = 0.7
    json: bool = False
    contexto: str = ""          # para la bitacora de coste (paso/escena)
    proyecto: str = ""


def clave_de(proveedor: str, claves: dict | None = None) -> str:
    """API key del proveedor: argumento, entorno o fichero de claves."""
    if claves and claves.get(proveedor):
        return str(claves[proveedor])
    variable = PROVEEDORES[proveedor]["variable"]
    return os.environ.get(variable, "")


def _esquema_de(proveedor: str) -> str:
    return PROVEEDORES[proveedor]["esquema"]


def _base_de(proveedor: str, ajustes_proveedor: dict | None = None) -> str:
    if ajustes_proveedor and ajustes_proveedor.get("base"):
        return str(ajustes_proveedor["base"]).rstrip("/")
    return PROVEEDORES[proveedor]["base"]


def llamar(llamada: Llamada, claves: dict | None = None,
           ajustes_proveedor: dict | None = None) -> str:
    """Llama al LLM y devuelve el texto de la respuesta.

    Reintenta con espera creciente los fallos transitorios (429/5xx/red);
    los 4xx de autenticacion fallan rapido — reintentar una clave mala no la
    arregla.
    """
    clave = clave_de(llamada.proveedor, claves)
    if not clave:
        raise ErrorLLM(f"falta la clave del proveedor '{llamada.proveedor}' "
                       f"({PROVEEDORES[llamada.proveedor]['variable']})")
    esquema = _esquema_de(llamada.proveedor)
    base = _base_de(llamada.proveedor, ajustes_proveedor)
    url = (f"{base}/chat/completions" if esquema == "openai"
           else f"{base}/messages")
    cabeceras = {"Content-Type": "application/json"}
    cuerpo: dict = {}

    if esquema == "openai":
        cabeceras["Authorization"] = f"Bearer {clave}"
        mensajes = []
        if llamada.sistema:
            mensajes.append({"role": "system", "content": llamada.sistema})
        mensajes.append({"role": "user", "content": llamada.instruccion})
        cuerpo = {"model": llamada.modelo, "messages": mensajes,
                  "max_tokens": llamada.max_tokens,
                  "temperature": llamada.temperatura}
    else:
        cabeceras["x-api-key"] = clave
        cabeceras["anthropic-version"] = "2023-06-01"
        cuerpo = {"model": llamada.modelo,
                  "max_tokens": llamada.max_tokens,
                  "temperature": llamada.temperatura,
                  "messages": [{"role": "user", "content": llamada.instruccion}]}
        if llamada.sistema:
            cuerpo["system"] = llamada.sistema

    ultimo_error = ""
    for intento in range(1, INTENTOS + 1):
        try:
            respuesta = requests.post(url, headers=cabeceras,
                                      json=cuerpo, timeout=TIEMPO_FUERA_S)
        except requests.RequestException as fallo:
            ultimo_error = f"red: {fallo}"
        else:
            if respuesta.status_code == 200:
                texto, uso = _extraer(respuesta.json(), esquema)
                _apuntar(llamada, uso)
                return texto
            if respuesta.status_code in (401, 403, 404):
                raise ErrorLLM(
                    f"{llamada.proveedor} rechazo la llamada "
                    f"({respuesta.status_code}): {respuesta.text[:300]}")
            if respuesta.status_code == 400 and esquema == "openai":
                # los modelos de razonamiento nuevos rechazan parametros
                # clasicos: se quitan y se reintenta en el acto
                detalle = respuesta.text[:500].lower()
                cambiado = False
                if "temperature" in detalle and "temperature" in cuerpo:
                    cuerpo.pop("temperature", None)
                    cambiado = True
                if "max_tokens" in detalle and "max_tokens" in cuerpo:
                    cuerpo["max_completion_tokens"] = cuerpo.pop("max_tokens")
                    cambiado = True
                if cambiado:
                    continue
            ultimo_error = (f"{respuesta.status_code}: {respuesta.text[:300]}")
        if intento < INTENTOS:
            time.sleep(2 ** intento)
    raise ErrorLLM(f"{llamada.proveedor} fallo tras {INTENTOS} intentos: "
                   f"{ultimo_error}")


def _extraer(cuerpo: dict, esquema: str) -> tuple[str, dict]:
    """Texto de la respuesta + uso de tokens (para el medidor de coste)."""
    try:
        if esquema == "openai":
            texto = (cuerpo["choices"][0]["message"]["content"] or "").strip()
            uso = cuerpo.get("usage", {}) or {}
        else:
            bloques = cuerpo.get("content", [])
            texto = "".join(b.get("text", "") for b in bloques
                            if b.get("type") == "text").strip()
            uso = cuerpo.get("usage", {}) or {}
    except (KeyError, IndexError, TypeError) as fallo:
        raise ErrorLLM(f"respuesta inesperada del LLM: {fallo}") from fallo
    if not texto:
        raise ErrorLLM("el LLM devolvio una respuesta vacia")
    return texto, {"entrada": uso.get("input_tokens",
                                      uso.get("prompt_tokens", 0)),
                   "salida": uso.get("output_tokens",
                                     uso.get("completion_tokens", 0))}


def _apuntar(llamada: Llamada, uso: dict) -> None:
    """Deja constancia del consumo (si el medidor esta disponible)."""
    if anotar_operacion is None:
        return
    try:
        anotar_operacion(
            operacion="llm", proveedor=llamada.proveedor, modelo=llamada.modelo,
            entrada=uso.get("entrada", 0), salida=uso.get("salida", 0),
            contexto=llamada.contexto, proyecto=llamada.proyecto)
    except Exception:                                  # noqa: BLE001
        pass  # el medidor nunca tumba la llamada


def llamar_json(llamada: Llamada, claves: dict | None = None,
                ajustes_proveedor: dict | None = None) -> dict | list:
    """Llama pidiendo JSON y lo parsea con rescate.

    El rescate (extraer el primer objeto/array balanceado) existe porque los
    modelos envuelven el JSON en prosa de vez en cuando; fallar ahi es perder
    una llamada cara por un par de palabras.
    """
    if llamada.sistema:
        llamada.sistema += "\n\nResponde SOLO con JSON valido, sin prosa."
    else:
        llamada.sistema = "Responde SOLO con JSON valido, sin prosa."
    texto = llamar(llamada, claves, ajustes_proveedor)
    return json.loads(texto) if _es_json(texto) else rescatar_json(texto)


def _es_json(texto: str) -> bool:
    try:
        json.loads(texto)
        return True
    except ValueError:
        return False


def rescatar_json(texto: str) -> dict | list:
    """Extrae el primer valor JSON balanceado de un texto con ruido."""
    for abridor, cerrador in (("{", "}"), ("[", "]")):
        inicio = texto.find(abridor)
        while inicio >= 0:
            profundidad, en_cadena, escape = 0, False, False
            for indice in range(inicio, len(texto)):
                caracter = texto[indice]
                if en_cadena:
                    if escape:
                        escape = False
                    elif caracter == "\\":
                        escape = True
                    elif caracter == '"':
                        en_cadena = False
                    continue
                if caracter == '"':
                    en_cadena = True
                elif caracter == abridor:
                    profundidad += 1
                elif caracter == cerrador:
                    profundidad -= 1
                    if profundidad == 0:
                        try:
                            return json.loads(texto[inicio:indice + 1])
                        except ValueError:
                            break
            inicio = texto.find(abridor, inicio + 1)
    raise ErrorLLM("la respuesta del LLM no contiene JSON: "
                   f"{texto[:200]}")


def probar(proveedor: str, claves: dict | None = None) -> dict:
    """Prueba de vida barata: lista modelos o pregunta de una palabra."""
    clave = clave_de(proveedor, claves)
    if not clave:
        return {"ok": False, "detalle": "sin clave"}
    try:
        if _esquema_de(proveedor) == "openai":
            url = f"{_base_de(proveedor)}/models"
            respuesta = requests.get(url, headers={"Authorization": f"Bearer {clave}"},
                                     timeout=30)
        else:
            url = f"{_base_de(proveedor)}/models"
            respuesta = requests.get(
                url, headers={"x-api-key": clave,
                              "anthropic-version": "2023-06-01"},
                timeout=30)
        if respuesta.status_code == 200:
            return {"ok": True, "detalle": "clave valida"}
        return {"ok": False,
                "detalle": f"{respuesta.status_code}: {respuesta.text[:200]}"}
    except requests.RequestException as fallo:
        return {"ok": False, "detalle": f"red: {fallo}"}


def rol_config(rol: str, ajustes_llm: dict | None = None) -> Llamada:
    """Construye la llamada base de un rol segun configuracion o defectos."""
    conf = (ajustes_llm or {}).get(rol) or ROLES_DEFECTO.get(rol) or {}
    proveedor = conf.get("proveedor", "glm")
    if proveedor not in PROVEEDORES:
        proveedor = "glm"
    modelo = conf.get("modelo") or PROVEEDORES[proveedor]["defecto"]
    return Llamada(proveedor=proveedor, modelo=modelo)
