"""Estilo del canal: lo que se decide UNA vez y se repite en cada vídeo.

El original (pasos/presets_canal.py) lo resume: un canal tiene un idioma, un
estilo gráfico, una cadencia y una voz, y esas cosas son las MISMAS en todos
sus vídeos. Aquí viven en datos/estilo.json y se APLICAN a los proyectos:

- Al CREAR un proyecto, sus params arrancan sembrados con el estilo (canal).
- A un proyecto existente se le puede reaplicar (botón "aplicar estilo"):
  quien decide regenerar — y pagar — sigue siendo la persona.

APLICAR COPIA LOS VALORES, no guarda una referencia (decisión del original):
si el estilo del canal cambia o se borra, un vídeo ya terminado no se rompe.
La firma de cada paso hashea los params guardados, así que la copia también
es lo que mantiene coherente la invalidación en cascada.
"""
from __future__ import annotations

from pathlib import Path

try:
    from .proyecto import ahora, escribir_json, leer_json
except ImportError:  # ejecutado suelto
    from proyecto import ahora, escribir_json, leer_json  # type: ignore

#: Campos del estilo y valores razonables de arranque. "definido" lo marca
#: la primera vez que alguien guarda: hasta entonces la pantalla insiste en
#: que lo PRIMERO es definir el estilo del canal.
ESTILO_DEFECTO: dict = {
    "definido": False,
    "nombre": "",
    "idioma": "es",
    "estilo_grafico": "",   # cómo se dibuja: paleta, técnica, encuadres, luz
    "tono": "",             # cómo se narra: registro, humor, muletillas fuera
    "ritmo_min": 20,        # segundos objetivo por escena: la cadencia
    "ritmo_max": 40,
    "voz": "",              # voice_id de ElevenLabs; "" -> defecto del paso
    "velocidad": 1.0,
    "actualizado": "",
}

_LIMITES = {"ritmo_min": (5, 120), "ritmo_max": (5, 180),
            "velocidad": (0.7, 1.2)}

#: pasos cuyos params siembra el estilo
PASOS_ESTILADOS = ("brief", "guion", "voz", "assets")


def fichero(carpeta_datos: Path | str) -> Path:
    return Path(carpeta_datos) / "estilo.json"


def leer(carpeta_datos: Path | str) -> dict:
    """El estilo guardado (mezclado con los defectos)."""
    guardado = leer_json(fichero(carpeta_datos), {}) or {}
    estilo = dict(ESTILO_DEFECTO)
    if isinstance(guardado, dict):
        estilo.update({k: v for k, v in guardado.items() if k in estilo})
    return _sanear(estilo)


def guardar(carpeta_datos: Path | str, cambios: dict) -> dict:
    """Escribe el estilo saneado y lo devuelve."""
    estilo = leer(carpeta_datos)
    estilo.update({k: v for k, v in cambios.items() if k in ESTILO_DEFECTO})
    estilo["definido"] = True
    estilo["actualizado"] = ahora()
    estilo = _sanear(estilo)
    escribir_json(fichero(carpeta_datos), estilo)
    return estilo


def _sanear(estilo: dict) -> dict:
    estilo["definido"] = bool(estilo.get("definido"))
    estilo["nombre"] = str(estilo.get("nombre", ""))[:120]
    estilo["idioma"] = estilo["idioma"] if estilo.get("idioma") in ("es", "en") else "es"
    for campo in ("estilo_grafico", "tono"):
        estilo[campo] = str(estilo.get(campo, ""))[:4000]
    for campo, (bajo, alto) in _LIMITES.items():
        try:
            valor = float(estilo.get(campo) or 0)
        except (TypeError, ValueError):
            valor = ESTILO_DEFECTO[campo]
        estilo[campo] = int(min(max(valor, bajo), alto)) if campo.startswith("ritmo") \
            else round(min(max(valor, bajo), alto), 2)
    if estilo["ritmo_max"] < estilo["ritmo_min"]:
        estilo["ritmo_max"] = estilo["ritmo_min"]
    estilo["voz"] = str(estilo.get("voz", ""))[:64]
    estilo["actualizado"] = str(estilo.get("actualizado", ""))
    return estilo


def aplicar_a_params(params_por_paso: dict, estilo: dict | None = None) -> dict:
    """Siembra el estilo en los params de los pasos que lo consumen.

    Devuelve el mismo diccionario con los valores COPIADOS (no referencia):
    brief (tono/ritmo/idioma), guion (tono/idioma), voz y assets (estilo
    gráfico). Al CREAR se siembra sobre los defectos; reaplicar a un
    proyecto existente PISA (lo pide una persona con el botón de la
    pantalla, y los pasos tocados quedan obsoletos a la vista).
    """
    e = estilo or {}
    semilla = {
        "brief": {"idioma": e.get("idioma", "es"),
                  "tono": e.get("tono", ""),
                  "ritmo_min": e.get("ritmo_min", ESTILO_DEFECTO["ritmo_min"]),
                  "ritmo_max": e.get("ritmo_max", ESTILO_DEFECTO["ritmo_max"])},
        "guion": {"tono": e.get("tono", ""),
                  "idioma": e.get("idioma", "es")},
        "voz": {},
        "assets": {"estilo": e.get("estilo_grafico", "")},
    }
    voz = e.get("voz", "")
    if voz:
        semilla["voz"]["voz"] = voz
    if e.get("velocidad"):
        semilla["voz"]["velocidad"] = e["velocidad"]
    for paso, valores in semilla.items():
        params_por_paso.setdefault(paso, {})
        params_por_paso[paso].update(valores)
    return params_por_paso
