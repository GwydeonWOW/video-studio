"""La voz que el canal fija UNA vez en Configuración.

Un canal graba sus vídeos con una voz: quien la tiene clara no debería
re-elegirla en cada vídeo ni depender de la que viene de fábrica
(Rachel). Aquí vive esa preferencia —motor de síntesis y voice_id— en
`datos/ajustes.json` (clave "voz"), junto al resto de ajustes del
servicio.

JERARQUÍA (la respeta `p4_voz`): lo elegido EN el vídeo manda (su
pestaña de Voz, un preset, el estilo del canal al crearlo — todo eso
vive en sus params); la voz de aquí solo se lleva los vídeos que
siguen con los valores de FÁBRICA, que son los que nadie eligió. Por
eso la resolución es EN CADA CORRIDA y no al sembrar los params:
cambiarla en Configuración es vivo y no pisa a quien ya eligió.
"""
from __future__ import annotations

from pathlib import Path

from .proyecto import escribir_json, leer_json

#: El motor de fábrica: el que usa todo vídeo que no dijo otra cosa.
MOTOR_DEFECTO = "multilingual"

#: Motores con nombre para humanos. Los IDs son las claves de
#: `voz_elevenlabs.MODELOS` (ahí está el identificador real de la API).
MOTORES = {
    "multilingual": "Eleven Multilingual v2 — natural, para narración",
    "flash": "Eleven Flash v2.5 — rápido y barato",
    "v3": "Eleven v3 — el más expresivo",
}

#: La voz de fábrica de ElevenLabs (Rachel): la que lleva todo vídeo
#: recién creado. Es el centinela de «nadie eligió voz para este vídeo».
VOZ_FABRICA = "21m00Tcm4TlvDq8ikWAM"


def _fichero(datos_dir: Path | str) -> Path:
    return Path(datos_dir) / "ajustes.json"


def leer(datos_dir: Path | str) -> dict:
    """La preferencia del canal saneada: {"motor": ..., "voz": ...}."""
    ajustes = leer_json(_fichero(datos_dir), {}) or {}
    voz = ajustes.get("voz") if isinstance(ajustes.get("voz"), dict) else {}
    motor = str(voz.get("motor") or MOTOR_DEFECTO)
    return {"motor": motor if motor in MOTORES else MOTOR_DEFECTO,
            "voz": str(voz.get("voz") or "").strip()[:64]}


def guardar(datos_dir: Path | str, motor: str, voz: str) -> dict:
    """Fija (o cambia) la preferencia y la devuelve saneada.

    `voz` vacía deja el canal sin preferencia (cada vídeo manda). Un
    motor desconocido se rechaza: la pantalla ofrece una lista cerrada
    y llegar aquí otro nombre es un bug o alguien con curl.
    """
    motor = str(motor or "").strip()
    if motor not in MOTORES:
        raise ValueError("motor desconocido; motores: "
                         + ", ".join(MOTORES))
    preferencia = {"motor": motor,
                   "voz": str(voz or "").strip()[:64]}
    ajustes = leer_json(_fichero(datos_dir), {}) or {}
    ajustes["voz"] = preferencia
    escribir_json(_fichero(datos_dir), ajustes)
    return preferencia
