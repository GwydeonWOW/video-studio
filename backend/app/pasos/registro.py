"""Registro de pasos: une el grafo con sus modulos.

Cada paso expone:
- params_defecto() -> dict          (valores al crear el proyecto)
- ejecutar(proyecto, params, trabajo) -> datos
- estimar(params) -> dict           (coste previsto para la pantalla)

Los ids son los del grafo y no cambian (regla del original).
"""
from __future__ import annotations

from importlib import import_module

from ..nucleo.estado import GRAFO

_MODULOS = {
    "ingesta": "p1_ingesta",
    "brief": "p2_brief",
    "guion": "p3_guion",
    "voz": "p4_voz",
    "revision_audio": "p5_revision_audio",
    "assets": "p6_assets",
    "callouts": "p7_callouts",
    "render": "p8_render",
}

_CACHE: dict[str, object] = {}


def modulo_de(paso: str):
    """Modulo de un paso (importado una vez)."""
    if paso not in _MODULOS:
        raise ValueError(f"paso desconocido: {paso!r}")
    if paso not in _CACHE:
        _CACHE[paso] = import_module(f".{_MODULOS[paso]}", __package__)
    return _CACHE[paso]


def params_defecto_de(paso: str) -> dict:
    return dict(modulo_de(paso).params_defecto())


def todos() -> list[dict]:
    """Catalogo de pasos para la pantalla."""
    from ..nucleo.estado import padres_de
    salida = []
    for paso in GRAFO:
        salida.append({"id": paso, "padres": padres_de(paso),
                       "params": params_defecto_de(paso)})
    return salida
