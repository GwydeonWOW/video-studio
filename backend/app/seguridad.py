"""Autenticación integrada del Estudio (cookie de sesión + scrypt).

A diferencia del original, que delegaba el login en un proxy Node aparte,
aqui la sesion vive en el propio servicio: desplegar en Coolify sin mas
frontal que el del propio Coolify es seguro.

- Contraseñas: scrypt con los MISMOS parametros que el login del original
  (N=32768, r=8, p=1 -> 32 MiB por intento) y comparacion en tiempo constante.
- Sesion: cookie httpOnly + SameSite=Lax, token de 32 bytes aleatorio,
  caducidad deslizante.
- CSRF: SameSite=Lax cubre los casos normales; ademas toda mutacion
  (POST/PUT/DELETE) exige cabecera Origin (o Referer de respaldo) que case
  con el propio host o con ESTUDIO_ORIGENES.
- Fuerza bruta: maximo 8 intentos por ventana de 15 minutos por IP sobre
  /api/auth/login.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import unicodedata
from pathlib import Path

from fastapi import HTTPException, Request

try:
    from .config import AJUSTES
except ImportError:  # ejecutado como modulo suelto
    from config import AJUSTES  # type: ignore

#: scrypt: 128 * N * r = 32 MiB por hash (identico al original).
N, R, P, LONGITUD = 32768, 8, 1, 64

#: Tiempo de vida de la sesion (7 dias) y deslizamiento (renueva a mitad).
VIDA_SESION_S = 7 * 24 * 3600
RENUEVA_A_PARTIR_DE = VIDA_SESION_S // 2

MIN_CONTRASENA = 12

#: Intentos de login por IP y ventana.
INTENTOS_MAX = 8
VENTANA_INTENTOS_S = 15 * 60


# ------------------------------------------------------------------ scrypt

def hash_contrasena(contrasena: str) -> str:
    """Devuelve el hash almacenable: scrypt$N$r$p$salt$hash (hex)."""
    if not isinstance(contrasena, str) or len(contrasena) < MIN_CONTRASENA:
        raise ValueError(f"la contrasena debe tener al menos {MIN_CONTRASENA} caracteres")
    sal = secrets.token_bytes(16)
    normalizada = unicodedata.normalize("NFKC", contrasena)
    derivada = hashlib.scrypt(normalizada.encode("utf-8"),
                              salt=sal, n=N, r=R, p=P, dklen=LONGITUD,
                              maxmem=128 * N * R * 2)
    return f"scrypt${N}${R}${P}${sal.hex()}${derivada.hex()}"


def verificar_contrasena(contrasena: str, guardado: str) -> bool:
    """Comparacion en tiempo constante contra el hash almacenado."""
    try:
        esquema, n, r, p, sal_hex, hash_hex = guardado.split("$")
        if esquema != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        esperado = bytes.fromhex(hash_hex)
        normalizada = unicodedata.normalize("NFKC", contrasena)
        derivada = hashlib.scrypt(normalizada.encode("utf-8"),
                                  salt=bytes.fromhex(sal_hex),
                                  n=n, r=r, p=p, dklen=len(esperado),
                                  maxmem=128 * N * R * 2)
        return hmac.compare_digest(derivada, esperado)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------- credenciales

def hash_actual() -> str:
    """El hash de la contrasena del usuario: del entorno o del volumen."""
    if AJUSTES.hash_entorno:
        return AJUSTES.hash_entorno
    fichero: Path = AJUSTES.fichero_credenciales
    if fichero.is_file():
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
            return str(datos.get("hash", ""))
        except (OSError, ValueError):
            return ""
    return ""


def guardar_credenciales(hash_: str) -> None:
    """Escribe la contrasena del primer arranque (flujo de instalacion)."""
    fichero: Path = AJUSTES.fichero_credenciales
    fichero.parent.mkdir(parents=True, exist_ok=True)
    fichero.write_text(
        json.dumps({"usuario": AJUSTES.usuario, "hash": hash_}, ensure_ascii=False),
        encoding="utf-8")
    try:
        fichero.chmod(0o600)
    except OSError:
        pass


def necesita_instalacion() -> bool:
    """True si no hay contrasena ni en el entorno ni en el volumen."""
    return not hash_actual()


# ------------------------------------------------------------------ sesiones

#: Sesiones en memoria: {token: {"expira": epoch, "ultima": epoch}}.
#: Reiniciar el servicio cierra sesiones; es aceptable para un equipo pequeno
#: y evita una base de datos. El original hacia igual con las charlas del
#: asistente.
_SESIONES: dict[str, dict[str, float]] = {}

NOMBRE_COOKIE = "estudio_sesion"


def crear_sesion() -> str:
    token = secrets.token_urlsafe(32)
    ahora = time.time()
    _SESIONES[token] = {"expira": ahora + VIDA_SESION_S, "ultima": ahora}
    # limpieza oportunista de sesiones caducadas
    for t in [t for t, s in _SESIONES.items() if s["expira"] < ahora]:
        _SESIONES.pop(t, None)
    return token


def cerrar_sesion(token: str) -> None:
    _SESIONES.pop(token, None)


def sesion_valida(token: str | None) -> bool:
    if not token or token not in _SESIONES:
        return False
    ses = _SESIONES[token]
    ahora = time.time()
    if ses["expira"] < ahora:
        _SESIONES.pop(token, None)
        return False
    # caducidad deslizante: a partir de la mitad de vida, cada peticion renueva
    if ahora - ses["ultima"] > RENUEVA_A_PARTIR_DE:
        ses["expira"] = ahora + VIDA_SESION_S
        ses["ultima"] = ahora
    else:
        ses["ultima"] = ahora
    return True


def token_de(peticion: Request) -> str | None:
    return peticion.cookies.get(NOMBRE_COOKIE)


# ------------------------------------------------------------------- CSRF

def _origenes_validos(peticion: Request) -> list[str]:
    """Hosts que cuentan como 'el mismo sitio' para el chequeo de Origin."""
    propios: list[str] = []
    host = peticion.headers.get("host", "")
    if host:
        propios.append(host)
        esquema = "https" if peticion.url.scheme == "https" or peticion.headers.get(
            "x-forwarded-proto") == "https" else "http"
        propios.append(f"{esquema}://{host}")
    for origen in AJUSTES.origenes_permitidos():
        propios.append(origen)
        try:
            from urllib.parse import urlparse
            anfitrion = urlparse(origen).netloc
            if anfitrion:
                propios.append(anfitrion)
        except ValueError:
            continue
    return propios


def origen_de_confianza(peticion: Request) -> bool:
    """True si la peticion viene de un origen permitido (o no declara ninguno).

    Los clientes no-navegador (curl con la cookie) pueden no mandar Origin:
    se les deja pasar — quien tiene la cookie ya esta dentro. Un navegador
    SIEMPRE manda Origin en mutaciones cross-site, y es a quien esto para.
    """
    declarado = peticion.headers.get("origin") or peticion.headers.get("referer")
    if not declarado:
        return True
    validos = _origenes_validos(peticion)
    for valido in validos:
        if declarado == valido or declarado.startswith(valido + "/"):
            return True
        # Referer con ruta: https://host/ruta casa con https://host
        if declarado.rstrip("/") == valido.rstrip("/"):
            return True
    return False


# -------------------------------------------------------------- rate limit

#: {ip: [marcas de tiempo de intentos dentro de la ventana]}
_INTENTOS: dict[str, list[float]] = {}


def intentos_de(ip: str) -> list[float]:
    ahora = time.time()
    lista = [t for t in _INTENTOS.get(ip, []) if ahora - t < VENTANA_INTENTOS_S]
    _INTENTOS[ip] = lista
    return lista


def anotar_intento(ip: str) -> None:
    intentos_de(ip)
    _INTENTOS.setdefault(ip, []).append(time.time())


def ip_de(peticion: Request) -> str:
    """IP de cliente, respetando el X-Forwarded-For del proxy de Coolify."""
    reenviada = peticion.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return peticion.client.host if peticion.client else "?"


# ------------------------------------------------------------ dependencias

def exigir_sesion(peticion: Request) -> None:
    """Dependencia FastAPI: 401 si no hay sesion valida.

    Instalacion pendiente y /api/auth/* siempre pasan; el resto no.
    """
    if AJUSTES.sin_login or necesita_instalacion():
        return
    if sesion_valida(token_de(peticion)):
        return
    raise HTTPException(status_code=401, detail="sesion requerida",
                        headers={"WWW-Authenticate": "Cookie"})


def exigir_origen(peticion: Request) -> None:
    """Dependencia FastAPI: 403 si la mutacion viene de un origen ajeno."""
    if not origen_de_confianza(peticion):
        raise HTTPException(status_code=403, detail="origen no permitido")
