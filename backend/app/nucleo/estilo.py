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

import re
import shutil
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
    "kit": [],              # imágenes de referencia del canal (nombres en _kit_canal)
}

#: El kit visual del canal: lo que sube quien lo tiene claro. Las imágenes
#: viven en `datos/_kit_canal/` (con `_` para que ningún listado las tome
#: por proyecto) y `estilo.json` guarda los nombres EN ORDEN. No es un
#: buzón como el del modo light: este kit es CANÓNICO y persiste hasta que
#: alguien lo quita — es el look que hereda cada vídeo nuevo.
CARPETA_KIT = "_kit_canal"
EXT_KIT = (".png", ".jpg", ".jpeg", ".webp")
MAX_KIT = 24
_NOMBRE_KIT = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

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
    estilo["kit"] = _sanear_kit(estilo.get("kit"))
    return estilo


def _sanear_kit(crudo) -> list[str]:
    """Nombres LLANOS y sin repetir, en orden, con tope."""
    salida: list[str] = []
    for nombre in crudo or []:
        texto = str(nombre or "").strip()
        if _NOMBRE_KIT.match(texto) and texto not in salida:
            salida.append(texto)
        if len(salida) >= MAX_KIT:
            break
    return salida


def carpeta_kit(carpeta_datos: Path | str) -> Path:
    return Path(carpeta_datos) / CARPETA_KIT


def rutas_kit(carpeta_datos: Path | str) -> list[Path]:
    """Las imágenes del kit que existen de verdad, en orden. -> [Path]

    Las rutas viajan ADJUNTAS a la llamada que escribe la guía de estilo:
    el kit es el material humano y la guía se escribe MIRÁNDOLO.
    """
    carpeta = carpeta_kit(carpeta_datos)
    if not carpeta.is_dir():
        return []
    return [carpeta / n for n in leer(carpeta_datos)["kit"]
            if (carpeta / n).is_file()]


def guardar_nombres_kit(carpeta_datos: Path | str, nombres: list[str]) -> dict:
    """Fija la lista de nombres del kit (tras subir o quitar imágenes)."""
    estilo = leer(carpeta_datos)
    estilo["kit"] = _sanear_kit(nombres)
    escribir_json(fichero(carpeta_datos), estilo)
    return estilo


def sembrar_kit(carpeta_datos: Path | str, proyecto) -> bool:
    """Copia el kit del canal a `<proyecto>/estilo/aportadas/`. -> si sembró

    Igual que el resto del estilo, esto COPIA y no referencia: el vídeo
    guarda su propio material y los cambios posteriores del kit del canal
    no le tocan (reaplicar el estilo lo refresca a mano). El destino se
    VACÍA antes: lo que se siembra es EL kit, no una adición al viejo.
    Sin kit no se toca nada — el proyecto puede tener aportadas suyas.
    """
    rutas = rutas_kit(carpeta_datos)
    if not rutas:
        return False
    destino = proyecto.ruta("estilo", "aportadas")
    if destino.is_dir():
        shutil.rmtree(destino)
    destino.mkdir(parents=True, exist_ok=True)
    for indice, ruta in enumerate(rutas, start=1):
        shutil.copy2(str(ruta), str(destino / f"{indice:02d}_{ruta.name}"))
    return True


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
