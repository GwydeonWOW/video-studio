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

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

try:
    from ..nucleo.coste import anotar_operacion
except ImportError:  # uso suelto
    anotar_operacion = None  # type: ignore

try:
    from ..nucleo import salud_llm
except ImportError:  # uso suelto
    salud_llm = None  # type: ignore

TIEMPO_FUERA_S = 600
INTENTOS = 3

#: Proveedores conocidos. La clave puede vivir en ESTUDIO_GL_KEY,
#: ESTUDIO_OPENAI_KEY o ESTUDIO_ANTHROPIC_KEY, o en secretos/claves.json
#: (campo "llm": {"glm": "...", "openai": "...", "anthropic": "..."}).
PROVEEDORES = {
    "glm": {
        "nombre": "GLM (z.ai)",
        "esquema": "openai",
        #: z.ai tiene DOS APIs con la misma clave: el Coding Plan
        #: (suscripcion, sin tokens comprados) vive en /api/coding/paas/v4
        #: y el pago por token, en /api/paas/v4. Mismo esquema OpenAI en
        #: ambas; se salta de una a otra con ESTUDIO_GL_BASE.
        "base": os.environ.get("ESTUDIO_GL_BASE",
                               "https://api.z.ai/api/coding/paas/v4"),
        "modelos": ["glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-4.6",
                    "glm-5.3v"],
        "defecto": "glm-5.3",
        "variable": "ESTUDIO_GL_KEY",
        # modelo que lee imagenes: si una llamada viaja con imagenes y el
        # rol esta configurado con otro modelo, se cambia a este (los
        # insignia de openai/anthropic/codex ya ven, no declaran «vision»)
        "vision": "glm-5.3v",
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
    "codex": {
        "nombre": "Codex (cuenta ChatGPT)",
        "esquema": "codex",
        "base": "https://chatgpt.com/backend-api/codex",
        "modelos": ["gpt-5.2-codex", "gpt-5.2-codex-mini",
                    "gpt-5.1-codex-max", "gpt-5.1-codex"],
        "defecto": "gpt-5.2-codex",
        # sin clave: la sesion OAuth vive en secretos/codex.json (ver
        # codex_oauth.py); la variable solo inyecta un token en dev
        "variable": "ESTUDIO_CODEX_TOKEN",
    },
}

#: Los modelos de codex salen mas rapido que las releases de esto: se
#: estiran por entorno (ESTUDIO_CODEX_MODELOS, separados por coma).
PROVEEDORES["codex"]["modelos"] = [
    m.strip() for m in os.environ.get("ESTUDIO_CODEX_MODELOS", "").split(",")
    if m.strip()] + PROVEEDORES["codex"]["modelos"]

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
    # el corrector de UN plano (pasos/corrector.py): lee la nota y mira
    # la imagen rechazada — merece el modelo grande, y con imagen puesta
    # se resuelve a vision (glm-5.3v) solo
    "corrector": {"proveedor": "glm", "modelo": "glm-5.3"},
    "conservacion": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    "guia_estilo": {"proveedor": "glm", "modelo": "glm-5.3"},
    "asistente": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
    # decide QUE se rehace al corregir el estilo con una frase
    # (pasos/enrutar_estilo.py): clasificar barato, no crear
    "enrutador": {"proveedor": "glm", "modelo": "glm-5.3-flash"},
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
    #: rutas de imagenes que acompañan a la instruccion (el modelo las
    #: ve; se usan para escribir la guia de estilo desde el material)
    imagenes: list[str] = field(default_factory=list)


def clave_de(proveedor: str, claves: dict | None = None) -> str:
    """Credencial del proveedor: argumento, entorno o fichero de claves.

    «codex» no tiene clave: su token OAuth se refresca al pedirlo.
    """
    if proveedor == "codex":
        if claves and claves.get("codex"):
            return str(claves["codex"])
        return _token_codex()
    if claves and claves.get(proveedor):
        return str(claves[proveedor])
    variable = PROVEEDORES[proveedor]["variable"]
    return os.environ.get(variable, "")


def _token_codex() -> str:
    """Token de codex fresco (refresca si caduca pronto)."""
    from ..config import AJUSTES
    from . import codex_oauth
    try:
        return codex_oauth.token_actual(AJUSTES.carpeta_claves)
    except codex_oauth.ErrorCodex as fallo:
        raise ErrorLLM(f"codex: {fallo}") from fallo


def _cabeceras_codex(clave: str) -> dict:
    """Cabeceras que el backend de Codex espera de un cliente CLI."""
    from ..config import AJUSTES
    from . import codex_oauth
    cabeceras = {
        "Authorization": f"Bearer {clave}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
    }
    cuenta = codex_oauth.cuenta_actual(AJUSTES.carpeta_claves)
    if cuenta:
        cabeceras["chatgpt-account-id"] = cuenta
    return cabeceras


def _esquema_de(proveedor: str) -> str:
    return PROVEEDORES[proveedor]["esquema"]


def _base_de(proveedor: str, ajustes_proveedor: dict | None = None) -> str:
    if ajustes_proveedor and ajustes_proveedor.get("base"):
        return str(ajustes_proveedor["base"]).rstrip("/")
    return PROVEEDORES[proveedor]["base"]


def _aliviar_400(cuerpo: dict, detalle: str) -> bool:
    """Un 400 de esquema openai suele ser un parametro que el modelo no
    admite (temperature en los de razonamiento, thinking donde no llego).
    Se quita el señalado por el mensaje y se reintenta en el acto.
    Devuelve True si el cuerpo cambio."""
    cambiado = False
    if "temperature" in detalle and "temperature" in cuerpo:
        cuerpo.pop("temperature", None)
        cambiado = True
    if "thinking" in detalle and "thinking" in cuerpo:
        cuerpo.pop("thinking", None)
        cambiado = True
    if "max_tokens" in detalle and "max_tokens" in cuerpo:
        cuerpo["max_completion_tokens"] = cuerpo.pop("max_tokens")
        cambiado = True
    return cambiado


def llamar(llamada: Llamada, claves: dict | None = None,
           ajustes_proveedor: dict | None = None) -> str:
    """Llama al LLM y devuelve el texto de la respuesta.

    Reintenta con espera creciente los fallos transitorios (429/5xx/red);
    los 4xx de autenticacion fallan rapido — reintentar una clave mala no la
    arregla.
    """
    if llamada.imagenes:
        _resolver_vision(llamada)
    clave = clave_de(llamada.proveedor, claves)
    if not clave:
        if llamada.proveedor == "codex":
            raise ErrorLLM("falta la sesion de Codex: conecta la cuenta "
                           "ChatGPT en Configuracion -> Claves")
        raise ErrorLLM(f"falta la clave del proveedor '{llamada.proveedor}' "
                       f"({PROVEEDORES[llamada.proveedor]['variable']})")
    esquema = _esquema_de(llamada.proveedor)
    base = _base_de(llamada.proveedor, ajustes_proveedor)
    url = f"{base}" + {"openai": "/chat/completions",
                       "anthropic": "/messages",
                       "codex": "/responses"}[esquema]
    cabeceras = {"Content-Type": "application/json"}
    cuerpo: dict = {}

    if esquema == "codex":
        # Responses API del backend de Codex. Sin temperature ni
        # max_tokens: ese backend rechaza los parametros clasicos y el
        # tamaño lo gobierna el propio modelo.
        cabeceras = _cabeceras_codex(clave)
        cuerpo = {
            "model": llamada.modelo,
            "instructions": llamada.sistema or "",
            "input": [{"role": "user",
                       "content": _contenido_user(llamada, esquema)}],
            "stream": True,
            "store": False,
        }
    elif esquema == "openai":
        cabeceras["Authorization"] = f"Bearer {clave}"
        mensajes = []
        if llamada.sistema:
            mensajes.append({"role": "system", "content": llamada.sistema})
        mensajes.append({"role": "user",
                         "content": _contenido_user(llamada, esquema)})
        cuerpo = {"model": llamada.modelo, "messages": mensajes,
                  "max_tokens": llamada.max_tokens,
                  "temperature": llamada.temperatura}
        if llamada.proveedor == "glm":
            # glm-5.x razona antes de contestar y el razonamiento sale del
            # MISMO presupuesto de max_tokens: con un guion largo se lo come
            # entero y la respuesta llega con content VACIO (finish length,
            # tres minutos perdidos). Sin pensamiento: directo y con texto.
            cuerpo["thinking"] = {"type": "disabled"}
    else:
        cabeceras["x-api-key"] = clave
        cabeceras["anthropic-version"] = "2023-06-01"
        cuerpo = {"model": llamada.modelo,
                  "max_tokens": llamada.max_tokens,
                  "temperature": llamada.temperatura,
                  "messages": [{"role": "user",
                                "content": _contenido_user(llamada, esquema)}]}
        if llamada.sistema:
            cuerpo["system"] = llamada.sistema

    ultimo_error = ""
    for intento in range(1, INTENTOS + 1):
        try:
            respuesta = requests.post(url, headers=cabeceras, json=cuerpo,
                                      timeout=TIEMPO_FUERA_S,
                                      stream=(esquema == "codex"))
        except requests.RequestException as fallo:
            ultimo_error = f"red: {fallo}"
        else:
            if respuesta.status_code == 200:
                texto, uso = _extraer(_cuerpo_de(respuesta, esquema), esquema)
                _apuntar(llamada, uso)
                _anotar_salud(llamada.proveedor, "ok", para=llamada.modelo)
                return texto
            if respuesta.status_code in (401, 403, 404):
                _anotar_salud(
                    llamada.proveedor, "sesion",
                    f"{respuesta.status_code}: {respuesta.text[:200]}",
                    para=llamada.modelo)
                raise ErrorLLM(
                    f"{llamada.proveedor} rechazo la llamada "
                    f"({respuesta.status_code}): {respuesta.text[:300]}")
            if respuesta.status_code == 400 and esquema == "openai":
                # los modelos de razonamiento nuevos rechazan parametros
                # clasicos: se quitan y se reintenta en el acto
                if _aliviar_400(cuerpo, respuesta.text[:500].lower()):
                    continue
            ultimo_error = (f"{respuesta.status_code}: {respuesta.text[:300]}")
        if intento < INTENTOS:
            time.sleep(2 ** intento)
    _anotar_salud(llamada.proveedor, _estado_salud(ultimo_error),
                  ultimo_error, para=llamada.modelo)
    raise ErrorLLM(f"{llamada.proveedor} fallo tras {INTENTOS} intentos: "
                   f"{ultimo_error}")


def _resolver_vision(llamada: Llamada) -> None:
    """Una llamada con imagenes necesita un modelo que las vea.

    Solo actua si el proveedor declara «vision» (glm: el de texto no lee
    imagenes). openai/anthropic/codex no lo declaran: sus insignia ya son
    multimodales y se quedan con el modelo configurado en el rol.
    """
    vision = PROVEEDORES.get(llamada.proveedor, {}).get("vision")
    if vision and llamada.modelo != vision:
        llamada.modelo = vision


_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp"}


def _leer_imagen(ruta: str) -> tuple[str, str]:
    """Lee una imagen de disco -> (mime, base64). Con nombre de fallo claro."""
    fichero = Path(ruta)
    mime = _MIMES.get(fichero.suffix.lower())
    if not mime:
        raise ErrorLLM(f"imagen con formato no soportado: {fichero.name}")
    datos = base64.b64encode(fichero.read_bytes()).decode("ascii")
    return mime, datos


def _contenido_user(llamada: Llamada, esquema: str):
    """Contenido del mensaje de usuario: texto plano, o texto + imagenes.

    Sin imagenes devuelve la instruccion tal cual (los cuerpos quedan
    identicos a los de siempre). Con imagenes, cada esquema tiene su
    bloque: codex «input_image», openai «image_url» con data-URL y
    anthropic «image» en base64.
    """
    if not llamada.imagenes:
        return llamada.instruccion
    bloques = []
    if llamada.instruccion:
        if esquema == "codex":
            bloques.append({"type": "input_text",
                            "text": llamada.instruccion})
        else:
            bloques.append({"type": "text", "text": llamada.instruccion})
    for ruta in llamada.imagenes:
        mime, datos = _leer_imagen(ruta)
        data_url = f"data:{mime};base64,{datos}"
        if esquema == "codex":
            bloques.append({"type": "input_image", "image_url": data_url})
        elif esquema == "anthropic":
            bloques.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": mime, "data": datos}})
        else:  # openai y compatibles (z.ai GLM)
            bloques.append({"type": "image_url",
                            "image_url": {"url": data_url}})
    return bloques


def _cuerpo_de(respuesta, esquema: str) -> dict:
    """El JSON final de la respuesta. El SSE de codex se drena hasta
    response.completed (lo unico que hace falta: el texto ya completo)."""
    if esquema != "codex":
        return respuesta.json()
    if not (respuesta.headers.get("content-type") or
            "").startswith("text/event-stream"):
        return respuesta.json()
    for linea in respuesta.iter_lines(decode_unicode=True):
        if not linea or not linea.startswith("data:"):
            continue
        bruto = linea[len("data:"):].strip()
        if bruto == "[DONE]":
            break
        try:
            evento = json.loads(bruto)
        except ValueError:
            continue
        if evento.get("type") == "response.completed":
            return evento.get("response") or {}
    raise ErrorLLM("codex cerro el flujo sin respuesta completa")


def _extraer(cuerpo: dict, esquema: str) -> tuple[str, dict]:
    """Texto de la respuesta + uso de tokens (para el medidor de coste)."""
    try:
        if esquema == "codex":
            # Responses API: la salida es una lista de piezas; el texto
            # vive en los bloques output_text de los mensajes
            textos = []
            for pieza in cuerpo.get("output") or []:
                if pieza.get("type") != "message":
                    continue
                for bloque in pieza.get("content") or []:
                    if bloque.get("type") in ("output_text", "text"):
                        textos.append(str(bloque.get("text") or ""))
            texto = "".join(textos).strip()
            uso = cuerpo.get("usage", {}) or {}
        elif esquema == "openai":
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
        # el finish dice POR QUE vino vacia: "length" = se quedo sin
        # presupuesto (el razonamiento se lo comio en glm-5.x)
        if esquema == "anthropic":
            fin = cuerpo.get("stop_reason")
        else:
            eleccion = (cuerpo.get("choices") or [{}])[0] or {}
            fin = eleccion.get("finish_reason")
        raise ErrorLLM("el LLM devolvio una respuesta vacia "
                       f"(finish: {fin or '?'})")
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


def _anotar_salud(proveedor: str, estado: str, mensaje: str = "",
                  para: str = "") -> None:
    """Deja constancia de cómo fue la última charla con el proveedor.

    Como `_apuntar`: diagnóstico puro — si no se puede escribir, la
    llamada ya salió bien o mal por sus propios medios y no hay que
    tumbarla por un apunte. No se anota nada cuando NI SE HA LLAMADO
    (falta de clave): la salud cuenta lo que pasó al hablar, no lo que
    no se hizo.
    """
    if salud_llm is None:
        return
    try:
        salud_llm.anotar(proveedor, estado, mensaje, para)
    except Exception:                                  # noqa: BLE001
        pass


def _estado_salud(texto: str) -> str:
    """El estado que corresponde a un texto de fallo (defecto: error)."""
    return salud_llm.clasificar(texto) if salud_llm is not None else "error"


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
    """Prueba de vida barata: lista modelos o pregunta de una palabra.

    Sin clave no se anota salud (no se ha hablado con nadie); el resto
    de desenlaces sí — esta prueba es la otra mitad del estado que
    Configuración pinta al lado de cada clave.
    """
    clave = clave_de(proveedor, claves)
    if not clave:
        return {"ok": False, "detalle": "sin clave"}
    try:
        if proveedor == "codex":
            # el backend de codex no lista modelos: se preguntan dos
            # palabras (gasta unos tokens de la suscripcion, nada mas)
            texto = llamar(Llamada(
                proveedor="codex", modelo=PROVEEDORES["codex"]["defecto"],
                sistema="Contesta con una sola palabra.", instruccion="Di: ok",
            ), claves)
            _anotar_salud(proveedor, "ok", texto.strip()[:40])
            return {"ok": True, "detalle": texto.strip()[:40] or "sesion valida"}
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
            _anotar_salud(proveedor, "ok", "clave valida")
            return {"ok": True, "detalle": "clave valida"}
        detalle = f"{respuesta.status_code}: {respuesta.text[:200]}"
        _anotar_salud(proveedor, _estado_salud(detalle), detalle)
        return {"ok": False, "detalle": detalle}
    except ErrorLLM as fallo:
        _anotar_salud(proveedor, _estado_salud(str(fallo)), str(fallo)[:200])
        return {"ok": False, "detalle": str(fallo)[:200]}
    except requests.RequestException as fallo:
        detalle = f"red: {fallo}"
        _anotar_salud(proveedor, _estado_salud(detalle), detalle[:200])
        return {"ok": False, "detalle": detalle}


def rol_config(rol: str, ajustes_llm: dict | None = None) -> Llamada:
    """Construye la llamada base de un rol segun configuracion o defectos."""
    conf = (ajustes_llm or {}).get(rol) or ROLES_DEFECTO.get(rol) or {}
    proveedor = conf.get("proveedor", "glm")
    if proveedor not in PROVEEDORES:
        proveedor = "glm"
    modelo = conf.get("modelo") or PROVEEDORES[proveedor]["defecto"]
    return Llamada(proveedor=proveedor, modelo=modelo)


# ------------------------------------------------------- conversación + tools

def llamar_conversacion(llamada: Llamada, mensajes: list[dict],
                        herramientas: list[dict] | None = None,
                        claves: dict | None = None,
                        ajustes_proveedor: dict | None = None) -> dict:
    """UNA vuelta de una conversación multi-turno, con herramientas opcionales.

    `mensajes` va en el formato NORMALIZADO del estudio (independiente del
    proveedor):

        [{"rol": "user",      "texto": str},
         {"rol": "asistente", "texto": str},
         {"rol": "asistente", "texto": str, "llamadas":
             [{"id", "nombre", "argumentos": dict}]},
         {"rol": "user", "resultados":
             [{"id", "texto": str}]}]

    `herramientas`: [{"nombre", "descripcion", "parametros": esquema-json}].

    -> {"texto": str,                la parte hablada (puede venir vacía
                                      si solo pidió herramientas)
        "llamadas": [{id, nombre, argumentos}],   lo que pidió ejecutar
        "uso": {"entrada": n, "salida": n}}

    El bucle (pedir -> ejecutar -> volver a pedir) lo lleva quien llama:
    aquí solo UNA ida y vuelta, para que el asistente pueda cancelar entre
    vueltas.
    """
    clave = clave_de(llamada.proveedor, claves)
    if not clave:
        if llamada.proveedor == "codex":
            raise ErrorLLM("falta la sesion de Codex: conecta la cuenta "
                           "ChatGPT en Configuracion -> Claves")
        raise ErrorLLM(f"falta la clave del proveedor '{llamada.proveedor}' "
                       f"({PROVEEDORES[llamada.proveedor]['variable']})")
    esquema = _esquema_de(llamada.proveedor)
    base = _base_de(llamada.proveedor, ajustes_proveedor)
    url = f"{base}" + {"openai": "/chat/completions",
                       "anthropic": "/messages",
                       "codex": "/responses"}[esquema]
    cabeceras = {"Content-Type": "application/json"}

    if esquema == "codex":
        cabeceras = _cabeceras_codex(clave)
        cuerpo: dict = {
            "model": llamada.modelo,
            "instructions": llamada.sistema or "",
            "input": _abrir_mensajes(mensajes, "", esquema),
            "stream": True,
            "store": False,
        }
        if herramientas:
            # responses: la funcion va PLANA (no anidada como en chat)
            cuerpo["tools"] = [
                {"type": "function", "name": h["nombre"],
                 "description": h.get("descripcion", ""),
                 "parameters": h.get("parametros",
                                     {"type": "object", "properties": {}})}
                for h in herramientas]
    elif esquema == "openai":
        cabeceras["Authorization"] = f"Bearer {clave}"
        cuerpo: dict = {"model": llamada.modelo,
                        "messages": _abrir_mensajes(mensajes,
                                                    llamada.sistema, esquema),
                        "max_tokens": llamada.max_tokens}
        if llamada.proveedor == "glm":
            # mismo motivo que en llamar(): sin pensamiento no se come el
            # presupuesto ni deja al asistente esperando un vacio
            cuerpo["thinking"] = {"type": "disabled"}
        if llamada.temperatura:
            cuerpo["temperature"] = llamada.temperatura
        if herramientas:
            cuerpo["tools"] = [
                {"type": "function",
                 "function": {"name": h["nombre"],
                              "description": h.get("descripcion", ""),
                              "parameters": h.get(
                                  "parametros",
                                  {"type": "object", "properties": {}})}}
                for h in herramientas]
    else:
        cabeceras["x-api-key"] = clave
        cabeceras["anthropic-version"] = "2023-06-01"
        cuerpo = {"model": llamada.modelo,
                  "max_tokens": llamada.max_tokens,
                  "messages": _abrir_mensajes(mensajes, "", esquema)}
        if llamada.temperatura:
            cuerpo["temperature"] = llamada.temperatura
        if llamada.sistema:
            cuerpo["system"] = llamada.sistema
        if herramientas:
            cuerpo["tools"] = [
                {"name": h["nombre"],
                 "description": h.get("descripcion", ""),
                 "input_schema": h.get("parametros",
                                       {"type": "object", "properties": {}})}
                for h in herramientas]

    ultimo_error = ""
    for intento in range(1, INTENTOS + 1):
        try:
            respuesta = requests.post(url, headers=cabeceras, json=cuerpo,
                                      timeout=TIEMPO_FUERA_S,
                                      stream=(esquema == "codex"))
        except requests.RequestException as fallo:
            ultimo_error = f"red: {fallo}"
        else:
            if respuesta.status_code == 200:
                crudo = _cuerpo_de(respuesta, esquema)
                texto, llamadas, uso = _extraer_conversacion(crudo, esquema)
                _apuntar(llamada, uso)
                _anotar_salud(llamada.proveedor, "ok", para=llamada.modelo)
                return {"texto": texto, "llamadas": llamadas, "uso": uso}
            if respuesta.status_code in (401, 403, 404):
                _anotar_salud(
                    llamada.proveedor, "sesion",
                    f"{respuesta.status_code}: {respuesta.text[:200]}",
                    para=llamada.modelo)
                raise ErrorLLM(
                    f"{llamada.proveedor} rechazo la llamada "
                    f"({respuesta.status_code}): {respuesta.text[:300]}")
            if respuesta.status_code == 400 and esquema == "openai":
                if _aliviar_400(cuerpo, respuesta.text[:500].lower()):
                    continue
            ultimo_error = f"{respuesta.status_code}: {respuesta.text[:300]}"
        if intento < INTENTOS:
            time.sleep(2 ** intento)
    _anotar_salud(llamada.proveedor, _estado_salud(ultimo_error),
                  ultimo_error, para=llamada.modelo)
    raise ErrorLLM(f"{llamada.proveedor} fallo tras {INTENTOS} intentos: "
                   f"{ultimo_error}")


def _abrir_mensajes(mensajes: list[dict], sistema: str, esquema: str) -> list:
    """Traduce el formato normalizado al del proveedor (sin el system)."""
    salida = []
    for mensaje in mensajes:
        rol = mensaje.get("rol")
        texto = str(mensaje.get("texto") or "")
        llamadas = mensaje.get("llamadas") or []
        resultados = mensaje.get("resultados") or []
        if esquema == "openai":
            if rol == "user" and resultados:
                for resultado in resultados:
                    salida.append({"role": "tool",
                                   "tool_call_id": resultado.get("id"),
                                   "content": resultado.get("texto", "")})
                continue
            m: dict = {"role": "user" if rol == "user" else "assistant",
                       "content": texto or None}
            if llamadas:
                m["tool_calls"] = [
                    {"id": h.get("id"), "type": "function",
                     "function": {"name": h.get("nombre"),
                                  "arguments": json.dumps(
                                      h.get("argumentos") or {},
                                      ensure_ascii=False)}}
                    for h in llamadas]
            salida.append(m)
        elif esquema == "codex":
            if rol == "user" and resultados:
                for resultado in resultados:
                    salida.append({"type": "function_call_output",
                                   "call_id": resultado.get("id"),
                                   "output": resultado.get("texto", "")})
                continue
            if texto:
                salida.append({
                    "role": "user" if rol == "user" else "assistant",
                    "content": [{"type": "input_text" if rol == "user"
                                 else "output_text", "text": texto}]})
            salida.extend({"type": "function_call",
                           "call_id": h.get("id"), "name": h.get("nombre"),
                           "arguments": json.dumps(h.get("argumentos") or {},
                                                   ensure_ascii=False)}
                          for h in llamadas)
        else:  # anthropic
            if rol == "user" and resultados:
                salida.append({"role": "user", "content": [
                    {"type": "tool_result",
                     "tool_use_id": resultado.get("id"),
                     "content": resultado.get("texto", "")}
                    for resultado in resultados]})
                continue
            bloques = []
            if texto:
                bloques.append({"type": "text", "text": texto})
            bloques.extend({"type": "tool_use", "id": h.get("id"),
                            "name": h.get("nombre"),
                            "input": h.get("argumentos") or {}}
                           for h in llamadas)
            salida.append({"role": "user" if rol == "user" else "assistant",
                           "content": bloques or [{"type": "text",
                                                   "text": ""}]})
    return salida


def _extraer_conversacion(crudo: dict, esquema: str) -> tuple[str, list, dict]:
    """Texto + llamadas de herramienta + uso, del cuerpo del proveedor."""
    try:
        if esquema == "openai":
            mensaje = crudo["choices"][0]["message"]
            texto = str(mensaje.get("content") or "")
            llamadas = []
            for pedido in mensaje.get("tool_calls") or []:
                funcion = pedido.get("function") or {}
                argumentos: dict = {}
                bruto = funcion.get("arguments") or "{}"
                try:
                    argumentos = json.loads(bruto)
                except ValueError:
                    argumentos = {"_bruto": bruto[:2000]}
                llamadas.append({"id": pedido.get("id"),
                                 "nombre": funcion.get("name"),
                                 "argumentos": argumentos})
            uso = crudo.get("usage", {}) or {}
        elif esquema == "codex":
            texto = ""
            llamadas = []
            for item in crudo.get("output", []) or []:
                if item.get("type") == "message":
                    for bloque in item.get("content") or []:
                        if bloque.get("type") in ("output_text", "text"):
                            texto += str(bloque.get("text") or "")
                elif item.get("type") == "function_call":
                    bruto = item.get("arguments") or "{}"
                    try:
                        argumentos = json.loads(bruto)
                    except ValueError:
                        argumentos = {"_bruto": bruto[:2000]}
                    llamadas.append({"id": item.get("call_id"),
                                     "nombre": item.get("name"),
                                     "argumentos": argumentos})
            uso = crudo.get("usage", {}) or {}
        else:  # anthropic
            bloques = crudo.get("content", []) or []
            texto = "".join(b.get("text", "") for b in bloques
                            if b.get("type") == "text")
            llamadas = [{"id": b.get("id"), "nombre": b.get("name"),
                         "argumentos": b.get("input") or {}}
                        for b in bloques if b.get("type") == "tool_use"]
            uso = crudo.get("usage", {}) or {}
    except (KeyError, IndexError, TypeError) as fallo:
        raise ErrorLLM(f"respuesta inesperada del LLM: {fallo}") from fallo
    return (texto.strip(), llamadas,
            {"entrada": uso.get("input_tokens", uso.get("prompt_tokens", 0)),
             "salida": uso.get("output_tokens",
                               uso.get("completion_tokens", 0))})
