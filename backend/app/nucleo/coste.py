"""Medidor de coste: cada motor apunta lo que consumio, al consumirlo.

Dos niveles, como el original:
- Por proyecto:  <proyecto>/coste.jsonl   (una linea por operacion)
- Global:        datos/coste_global.jsonl

Tarifas por millon de tokens / por imagen / por caracter de voz. Los precios
cambian; el fichero tarifas.json del volumen manda sobre estos defectos.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

try:
    from .proyecto import ahora, anadir_jsonl, leer_jsonl
except ImportError:
    from proyecto import ahora, anadir_jsonl, leer_jsonl  # type: ignore

_CERROJO = threading.Lock()

#: Tarifas por defecto (USD). Llave: "proveedor/operacion".
TARIFAS_DEFECTO = {
    # LLM: dolares por millon de tokens (entrada/salida)
    "glm/tokens": [0.60, 2.20],           # glm-4.6 aprox
    "openai/tokens": [1.25, 10.00],       # gpt-5-mini aprox
    "anthropic/tokens": [3.00, 15.00],    # sonnet-4.5 aprox
    # Imagenes: dolares por imagen gpt-image-1 segun calidad
    "openai/imagen": {"low": 0.011, "medium": 0.042, "high": 0.167},
    # Voz: dolar por 1000 caracteres (aprox once_multilingual)
    "elevenlabs/voz": 0.15,
    "elevenlabs/voz_flash": 0.05,
}


def tarifas(datos_dir: Path) -> dict:
    """Tarifas activas: fichero del volumen si existe, defecto si no."""
    fichero = Path(datos_dir) / "tarifas.json"
    try:
        if fichero.is_file():
            leidas = json.loads(fichero.read_text(encoding="utf-8"))
            if isinstance(leidas, dict) and leidas:
                mezcladas = dict(TARIFAS_DEFECTO)
                mezcladas.update(leidas)
                return mezcladas
    except (OSError, ValueError):
        pass
    return dict(TARIFAS_DEFECTO)


def _coste_llm(tarifas_: dict, proveedor: str, modelo: str,
               entrada: int, salida: int) -> float:
    clave = f"{proveedor}/tokens"
    precios = tarifas_.get(clave)
    if not precios:
        return 0.0
    return (entrada / 1e6) * precios[0] + (salida / 1e6) * precios[1]


def _coste_operacion(tarifas_: dict, entrada: dict) -> float:
    operacion = entrada.get("operacion")
    proveedor = entrada.get("proveedor", "")
    if operacion == "llm":
        return _coste_llm(tarifas_, proveedor, entrada.get("modelo", ""),
                          int(entrada.get("entrada", 0)),
                          int(entrada.get("salida", 0)))
    if operacion == "imagen":
        tabla = tarifas_.get(f"{proveedor}/imagen", {})
        return float(tabla.get(entrada.get("calidad", "low"), 0.0))
    if operacion == "voz":
        precio = tarifas_.get(f"{proveedor}/voz", 0.0)
        return (int(entrada.get("caracteres", 0)) / 1000.0) * precio
    return 0.0


def anotar_operacion(datos_dir: Path | None = None, proyecto: str = "",
                     operacion: str = "", proveedor: str = "", modelo: str = "",
                     entrada: int = 0, salida: int = 0, caracteres: int = 0,
                     calidad: str = "", contexto: str = "", coste: float | None = None,
                     proyecto_dir: Path | None = None) -> dict:
    """Registra una operacion en el coste del proyecto y en el global.

    Firma pensada para llamarse desde los motores con lo que ya tienen en la
    mano; el coste se calcula de las tarifas si no viene dado.
    """
    registro = {
        "t": ahora(), "operacion": operacion, "proveedor": proveedor,
        "modelo": modelo, "entrada": entrada, "salida": salida,
        "caracteres": caracteres, "calidad": calidad, "contexto": contexto,
        "proyecto": proyecto,
    }
    with _CERROJO:
        base = Path(datos_dir) if datos_dir else Path("datos")
        tarifas_ = tarifas(base)
        registro["coste"] = (round(coste, 6) if coste is not None
                             else round(_coste_operacion(tarifas_, registro), 6))
        anadir_jsonl(base / "coste_global.jsonl", registro)
        if proyecto_dir is not None:
            anadir_jsonl(Path(proyecto_dir) / "coste.jsonl", registro)
    return registro


def total_de(entradas: list[dict]) -> dict:
    """Suma una lista de registros de coste."""
    total = {"operaciones": 0, "coste": 0.0,
             "por_operacion": {}, "por_proveedor": {}}
    for entrada in entradas:
        coste = float(entrada.get("coste", 0))
        operacion = entrada.get("operacion", "?")
        proveedor = entrada.get("proveedor", "?")
        total["operaciones"] += 1
        total["coste"] += coste
        total["por_operacion"][operacion] = round(
            total["por_operacion"].get(operacion, 0.0) + coste, 6)
        total["por_proveedor"][proveedor] = round(
            total["por_proveedor"].get(proveedor, 0.0) + coste, 6)
    total["coste"] = round(total["coste"], 6)
    return total


def global_(datos_dir: Path) -> dict:
    return total_de(leer_jsonl(Path(datos_dir) / "coste_global.jsonl"))


def de_proyecto(proyecto_dir: Path) -> dict:
    return total_de(leer_jsonl(Path(proyecto_dir) / "coste.jsonl"))


def eventos_de(proyecto_dir: Path) -> list[dict]:
    """Detalle de cada consumo, del mas antiguo al mas reciente."""
    return leer_jsonl(Path(proyecto_dir) / "coste.jsonl")


def por_paso(entradas: list[dict]) -> dict:
    """Reparte los consumos por paso leyendo el contexto «paso[:unidad]»."""
    salida: dict[str, dict] = {}
    for entrada in entradas:
        paso = str(entrada.get("contexto", "")).split(":", 1)[0] or "?"
        ficha = salida.setdefault(paso, {"operaciones": 0, "coste": 0.0})
        ficha["operaciones"] += 1
        ficha["coste"] = round(ficha["coste"] + float(entrada.get("coste", 0)), 6)
    return dict(sorted(salida.items(), key=lambda kv: -kv[1]["coste"]))
