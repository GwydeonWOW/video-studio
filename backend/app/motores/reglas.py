"""Base de reglas transversales aprendidas del feedback humano.

Cada vez que una revisión detecta un fallo, el fallo se destila en una
regla abierta y se guarda aquí. Las reglas NO pertenecen al vídeo en el
que se descubrieron: se aplican a todos los proyectos futuros.

Uso desde un paso:

    from ..motores import reglas
    lineas = reglas.para("prompt_imagen")   # texto listo para inyectar
    reglas.anadir(id="...", ambito="...", regla="...",
                  por_que="...", origen={...})

Uso desde consola (desde backend/):

    python -m app.motores.reglas listar [--ambito prompt_imagen]

`reglas.json` es un fichero VIVO del repositorio: se escribe en el mismo
sitio del que se lee, porque lo que guarda no es configuración sino lo
aprendido. Su contenido ES funcionalidad — llega verbatim del original.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglas.json")

AMBITOS = ("prompt_imagen", "referencias", "reparto", "blockout",
           "plan_escenas", "storyboard", "montaje", "voz")


def cargar():
    with open(RUTA, "r", encoding="utf-8") as fh:
        return json.load(fh)


def guardar(datos):
    with open(RUTA, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)


def para(ambito, como_texto=True):
    """Reglas de un ámbito, ordenadas por prioridad."""
    datos = cargar()
    filtradas = [r for r in datos["reglas"] if r["ambito"] == ambito]
    filtradas.sort(key=lambda r: r.get("prioridad", 9))
    if not como_texto:
        return filtradas
    return [r["regla"] for r in filtradas]


def bloque_prompt(ambito="prompt_imagen"):
    """Devuelve las reglas como un párrafo listo para concatenar a un prompt."""
    lineas = para(ambito)
    if not lineas:
        return ""
    return " ".join(lineas)


def anadir(*, id, ambito, regla, por_que="", origen=None, prioridad=1):
    if ambito not in AMBITOS:
        raise ValueError(f"ámbito desconocido: {ambito} (válidos: {AMBITOS})")
    datos = cargar()
    existentes = {r["id"] for r in datos["reglas"]}
    if id in existentes:
        # Se actualiza en lugar de duplicar: la misma lección puede reaparecer
        # en varios proyectos y lo útil es acumular orígenes, no repetir reglas.
        for r in datos["reglas"]:
            if r["id"] == id:
                r["regla"] = regla
                r.setdefault("origenes_extra", []).append(origen or {})
                break
    else:
        datos["reglas"].append({
            "id": id, "ambito": ambito, "prioridad": prioridad,
            "regla": regla, "por_que": por_que,
            "origen": origen or {}, "fecha": date.today().isoformat(),
        })
    guardar(datos)
    return id


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_listar = sub.add_parser("listar")
    p_listar.add_argument("--ambito", default=None, choices=AMBITOS)

    args = parser.parse_args()

    if args.cmd == "listar":
        datos = cargar()
        reglas = datos["reglas"]
        if args.ambito:
            reglas = [r for r in reglas if r["ambito"] == args.ambito]
        reglas.sort(key=lambda r: (r["ambito"], r.get("prioridad", 9)))
        ambito_actual = None
        for r in reglas:
            if r["ambito"] != ambito_actual:
                ambito_actual = r["ambito"]
                print(f"\n=== {ambito_actual} ===")
            print(f"  [{r['id']}]  {r['regla']}")
            if r.get("origen", {}).get("feedback"):
                print(f"      nació de: \"{r['origen']['feedback']}\"")
        print(f"\n{len(reglas)} reglas")


if __name__ == "__main__":
    main()
