"""Codex OAuth: textos con la cuenta ChatGPT, sin clave de API.

El mismo login que usa el CLI de Codex (flujo de dispositivo de
auth.openai.com): la pantalla enseña un codigo, la persona lo confirma
en el navegador y aqui queda una sesion refrescable en
`secretos/codex.json`. El token viaja SOLO al backend de Codex
(chatgpt.com/backend-api/codex — lo usa llm.py); las imagenes no
entran: esa API exige clave de plataforma y aqui ya se dibujan con
GLM-Image.

El access token caduca en horas: nadie lo renueva por nosotros, asi
que `token_actual()` refresca solo cuando queda poco margen. El
refresh token se rota en cada refresco — se guarda el nuevo en el
acto o la sesion muere con el siguiente reinicio.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests

try:
    from ..nucleo.proyecto import escribir_json, leer_json
except ImportError:  # uso suelto
    from ..nucleo.proyecto import escribir_json, leer_json  # type: ignore

AUTH = "https://auth.openai.com"

#: OpenAI jubilo el device flow clasico (`/oauth/device/code`: hoy
#: contesta 404 «Invalid URL»). El CLI de Codex lo sustituyo por el
#: mismo teatro con otros focos: se pide un `user_code` en
#: `/api/accounts/deviceauth/usercode`, la persona lo confirma en
#: `/codex/device`, y el sondeo a `/api/accounts/deviceauth/token`
#: devuelve un `authorization_code` CON su `code_verifier` (el PKCE lo
#: resuelve el servidor) que se canjea en `/oauth/token`.
URL_CODIGO = f"{AUTH}/api/accounts/deviceauth/usercode"
URL_CANJE_DISPOSITIVO = f"{AUTH}/api/accounts/deviceauth/token"
URL_CONFIRMAR = f"{AUTH}/codex/device"
REDIRECCION_DISPOSITIVO = f"{AUTH}/deviceauth/callback"

#: auth.openai.com esta detras de Cloudflare y el User-Agent por defecto
#: de requests (`python-requests/x.y`) cae en su lista de bots: contesta
#: 403 con la pagina "Just a moment..." en vez del JSON. Este flujo ES
#: el del CLI de Codex, asi que nos identificamos como el CLI (mismo
#: UA y misma cabecera `originator` que manda codex_cli_rs).
CABECERAS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "codex_cli_rs/0.42.0 (Windows 11; x86_64) video-studio",
    "originator": "codex_cli_rs",
}

#: Cliente publico del CLI de Codex (no es secreto: va impreso en el
#: binario de cualquiera). Se permite override por entorno por si OpenAI
#: lo retira y sale uno nuevo.
CLIENTE_ID = os.environ.get("ESTUDIO_CODEX_CLIENT_ID",
                            "app_EMoamEEZ73f0CkXaXp7hrann")

#: margen de refresco: si el token caduca en menos de esto, se renueva
MARGEN_S = 120

#: flujo de dispositivo en curso (en memoria: la app es de un usuario)
_pendiente: dict = {}


class ErrorCodex(RuntimeError):
    """Fallo del flujo OAuth con texto para humano."""


def fichero(carpeta: Path | str) -> Path:
    return Path(carpeta) / "codex.json"


def leer(carpeta: Path | str) -> dict:
    datos = leer_json(fichero(carpeta), {})
    return datos if isinstance(datos, dict) else {}


def _guardar(carpeta: Path | str, datos: dict) -> None:
    escribir_json(fichero(carpeta), datos)
    try:
        fichero(carpeta).chmod(0o600)
    except OSError:
        pass


def estado(carpeta: Path | str) -> dict:
    """Lo que ve la pantalla: conectado, quien y hasta cuando."""
    datos = leer(carpeta)
    conectado = bool(datos.get("access_token") or datos.get("refresh_token"))
    expira = datos.get("expira")
    return {
        "conectado": conectado,
        "correo": str(datos.get("correo") or ""),
        "expira": expira if isinstance(expira, (int, float)) else 0,
        "pendiente": bool(_pendiente),
    }


def iniciar(carpeta: Path | str) -> dict:
    """Arranca el flujo de dispositivo -> lo que se pinta en pantalla."""
    global _pendiente
    try:
        respuesta = requests.post(
            URL_CODIGO, headers=CABECERAS,
            json={"client_id": CLIENTE_ID}, timeout=30)
    except requests.RequestException as fallo:
        raise ErrorCodex(f"red: {fallo}") from fallo
    if respuesta.status_code != 200:
        raise ErrorCodex(f"auth.openai.com {respuesta.status_code}: "
                         f"{respuesta.text[:200]}")
    datos = respuesta.json()
    for campo in ("device_auth_id", "user_code"):
        if not datos.get(campo):
            raise ErrorCodex(f"respuesta sin {campo}: {datos}")
    _pendiente = {
        "device_auth_id": str(datos["device_auth_id"]),
        "user_code": str(datos["user_code"]),
        "caduca": _caducidad(str(datos.get("expires_at", ""))),
    }
    return {
        "user_code": _pendiente["user_code"],
        "verification_uri": URL_CONFIRMAR,
        "verification_uri_complete": "",
        "expira_s": max(0, int(_pendiente["caduca"] - time.time())),
        "intervalo_s": max(2, int(str(datos.get("interval", "5")) or 5)),
    }


def sondear(carpeta: Path | str) -> dict:
    """Una vuelta de polling: pendiente | conectado | rechazado | expirado."""
    global _pendiente
    if not _pendiente:
        return {"estado": "sin_flujo"}
    if time.time() > _pendiente["caduca"]:
        _pendiente = {}
        return {"estado": "expirado"}
    try:
        respuesta = requests.post(
            URL_CANJE_DISPOSITIVO, headers=CABECERAS,
            json={"device_auth_id": _pendiente["device_auth_id"],
                  "user_code": _pendiente["user_code"]},
            timeout=30)
    except requests.RequestException as fallo:
        raise ErrorCodex(f"red: {fallo}") from fallo
    # 403/404 es «aun no ha confirmado» en este endpoint (el CLI hace
    # lo mismo: sondea cada `interval` hasta un cuarto de hora)
    if respuesta.status_code in (403, 404):
        return {"estado": "pendiente"}
    if respuesta.status_code == 200:
        datos = respuesta.json()
        for campo in ("authorization_code", "code_verifier"):
            if not datos.get(campo):
                raise ErrorCodex(f"respuesta sin {campo}: {datos}")
        sesion = _canjear_codigo(str(datos["authorization_code"]),
                                 str(datos["code_verifier"]))
        _guardar(carpeta, sesion)
        _pendiente = {}
        return {"estado": "conectado", "correo": sesion.get("correo", "")}
    try:
        error = str((respuesta.json() or {}).get("error", ""))
    except ValueError:
        error = ""
    error = error or respuesta.text[:120].strip()
    _pendiente = {}
    if error == "expired_token":
        return {"estado": "expirado"}
    if error == "access_denied":
        return {"estado": "rechazado"}
    raise ErrorCodex(f"auth.openai.com {respuesta.status_code}: {error}")


def token_actual(carpeta: Path | str) -> str:
    """Access token valido (refresca si toca). Vacio si no hay sesion."""
    directo = os.environ.get("ESTUDIO_CODEX_TOKEN", "")
    if directo:
        return directo
    datos = leer(carpeta)
    if not datos.get("access_token") and not datos.get("refresh_token"):
        return ""
    expira = float(datos.get("expira") or 0)
    if datos.get("access_token") and time.time() < expira - MARGEN_S:
        return str(datos["access_token"])
    datos = refrescar(carpeta, datos)
    return str(datos.get("access_token") or "")


def cuenta_actual(carpeta: Path | str) -> str:
    """El chatgpt-account-id que pide el backend de Codex en cabeceras."""
    return os.environ.get("ESTUDIO_CODEX_CUENTA", "") or \
        str(leer(carpeta).get("cuenta_id") or "")


def refrescar(carpeta: Path | str, datos: dict) -> dict:
    """Canjea el refresh token por una sesion nueva (rotada)."""
    refresh = datos.get("refresh_token")
    if not refresh:
        raise ErrorCodex("la sesion de Codex no tiene refresh token: "
                         "conecta la cuenta de nuevo")
    try:
        respuesta = requests.post(
            f"{AUTH}/oauth/token",
            headers=CABECERAS,
            json={"grant_type": "refresh_token",
                  "client_id": CLIENTE_ID, "refresh_token": refresh},
            timeout=30)
    except requests.RequestException as fallo:
        raise ErrorCodex(f"red: {fallo}") from fallo
    if respuesta.status_code != 200:
        detalle = respuesta.text[:200]
        try:
            detalle = str((respuesta.json() or {}).get("error", detalle))
        except ValueError:
            pass
        raise ErrorCodex(f"no se pudo renovar la sesion ({detalle}): "
                         "conecta la cuenta de nuevo")
    sesion = _sesion_de(respuesta.json(), previa=datos)
    _guardar(carpeta, sesion)
    return sesion


def desconectar(carpeta: Path | str) -> dict:
    """Borra la sesion local (el refresco queda inservible sin ella)."""
    global _pendiente
    _pendiente = {}
    try:
        fichero(carpeta).unlink(missing_ok=True)
    except OSError as fallo:
        raise ErrorCodex(f"no se pudo borrar la sesion: {fallo}") from fallo
    return {"conectado": False}


# ------------------------------------------------------------------ helpers

def _caducidad(momento: str) -> float:
    """`expires_at` ISO del endpoint -> epoch; sin el, 15 minutos."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(momento).timestamp()
    except ValueError:
        return time.time() + 900


def _canjear_codigo(codigo: str, verificador: str) -> dict:
    """authorization_code del device flow -> sesion (form, como el CLI)."""
    try:
        respuesta = requests.post(
            f"{AUTH}/oauth/token",
            headers=CABECERAS,
            data={"grant_type": "authorization_code",
                  "client_id": CLIENTE_ID,
                  "code": codigo,
                  "redirect_uri": REDIRECCION_DISPOSITIVO,
                  "code_verifier": verificador},
            timeout=30)
    except requests.RequestException as fallo:
        raise ErrorCodex(f"red: {fallo}") from fallo
    if respuesta.status_code != 200:
        raise ErrorCodex(f"auth.openai.com {respuesta.status_code}: "
                         f"{respuesta.text[:200]}")
    return _sesion_de(respuesta.json())


def _sesion_de(tokens: dict, previa: dict | None = None) -> dict:
    """Normaliza la respuesta del token endpoint a nuestro fichero."""
    access = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token")
                  or (previa or {}).get("refresh_token") or "")
    if not access:
        raise ErrorCodex("la respuesta no trae access_token")
    expira_en = float(tokens.get("expires_in") or 3600)
    sesion = {
        "access_token": access,
        "refresh_token": refresh,
        "expira": time.time() + expira_en,
    }
    id_token = str(tokens.get("id_token") or "")
    if id_token:
        for campo, valor in _reclamos(id_token).items():
            sesion[campo] = valor
    return sesion


def _reclamos(id_token: str) -> dict:
    """Cuenta y correo del id_token (JWT SIN verificar firma: el token
    acaba de llegar del endpoint oficial por HTTPS, no de un tercero)."""
    try:
        carga = id_token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        cuerpo = json.loads(base64.urlsafe_b64decode(carga))
    except (IndexError, ValueError, TypeError) as fallo:
        raise ErrorCodex(f"id_token ilegible: {fallo}") from fallo
    auth = cuerpo.get("https://api.openai.com/auth") or {}
    if not isinstance(auth, dict):
        auth = {}
    return {
        "cuenta_id": str(auth.get("chatgpt_account_id") or ""),
        "correo": str(cuerpo.get("email") or ""),
    }
