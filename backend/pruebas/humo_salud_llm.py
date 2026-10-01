"""Prueba de humo de la salud del LLM: anotar, clasificar y pintar.

El defecto que vigila: la pantalla de claves solo sabía decir «puesta» —
un cupo agotado o una clave caducada solo se descubría al generar y
comerse un error de seiscientos caracteres. La salud cuenta lo ÚLTIMO
que pasó al hablar con cada proveedor, y sale de dos sitios: las
llamadas de verdad (llamar/llamar_conversacion) y el botón Probar.

Sin gastar un céntimo: los accesos a la red van falseados, así que se
comprueba el cableado entero (200 → ok, 401 → sesion sin reintentar,
429 agotado → cupo tras los intentos) sin hablar con nadie. Ejecutar:

    python pruebas/humo_salud_llm.py

Sale 0 si todo verde; imprime cada chequeo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# datos y fichero de salud aislados ANTES de importar la app
_raiz = Path(__file__).resolve().parent.parent
_dir = tempfile.mkdtemp(prefix="estudio_humo_salud_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir) / "datos")
os.environ["ESTUDIO_SALUD_LLM"] = str(Path(_dir) / "salud_llm.json")
os.environ.pop("ESTUDIO_HASH", None)
for _v in ("ESTUDIO_GL_KEY", "ESTUDIO_OPENAI_KEY", "ESTUDIO_ANTHROPIC_KEY",
           "ESTUDIO_CODEX_TOKEN"):
    os.environ.pop(_v, None)
sys.path.insert(0, str(_raiz))

import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.motores import llm as motor  # noqa: E402
from app.nucleo import salud_llm  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" — {detalle}" if detalle and not condicion else ""))
    if not condicion:
        fallos.append(nombre)


# --------------------------------------------------------------- clasificar

casos = {"429 too many": "cupo", "rate limit exceeded": "cupo",
         "quota exceeded": "cupo", "401 unauthorized": "sesion",
         "invalid api key": "sesion", "read timeout": "tiempo",
         "timed out.": "tiempo", "algo raro pasó": "error"}
mal = [f"{t}→{salud_llm.clasificar(t)} (esperaba {e})"
       for t, e in casos.items() if salud_llm.clasificar(t) != e]
check("clasificar distingue cupo/sesion/tiempo/error", not mal, "; ".join(mal))

# ------------------------------------------------------------ anotar/leer

ficha = salud_llm.anotar("glm", "cupo", "rate limit exceeded. "
                            "resets: 2026-10-02T00:00Z " + "x" * 700,
                            para="m" * 200)
leida = salud_llm.de("glm")
check("anotar escribe la ficha y leer la devuelve",
      leida == ficha and leida["estado"] == "cupo")
check("el mensaje se recorta a 600 y para a 120",
      len(leida["mensaje"]) == 600 and len(leida["para"]) == 120,
      f"{len(leida['mensaje'])}/{len(leida['para'])}")
check("la ficha trae cuándo pasó",
      leida.get("cuando") and leida.get("epoch", 0) > 0)
check("un proveedor al que nunca se habló no tiene ficha",
      salud_llm.de("anthropic") is None)

frases = {e: salud_llm.describir({"estado": e, "mensaje": "lo que sea",
                                  "cuando": "2026-10-01T10:00:00"}, "GLM")
          for e in salud_llm.ESTADOS}
check("describir arma una frase distinta por estado",
      len(set(frases.values())) == len(frases)
      and "contesta" in frases["ok"]
      and "cupo agotado" in frases["cupo"])
check("renueva saca cuándo se repone el cupo",
      salud_llm.renueva({"estado": "cupo",
                         "mensaje": "rate limit. resets: el martes"}) == "el martes"
      and salud_llm.renueva({"estado": "ok", "mensaje": "resets: x"}) == "")

# ------------------------------------------------------- el embudo (falso)

CLAVES = {"glm": "clave-de-prueba"}


class Respuesta:
    def __init__(self, codigo: int, cuerpo: dict | None = None):
        self.status_code = codigo
        self._cuerpo = cuerpo or {}
        self.text = str(self._cuerpo)

    def json(self):
        return self._cuerpo


def _montar(codigo: int, cuerpo: dict | None = None, contador: list | None = None):
    def falso(_url, **_kw):
        if contador is not None:
            contador.append(1)
        return Respuesta(codigo, cuerpo)
    return falso


_post_real, _get_real = requests.post, requests.get
_dormir_real = time.sleep
requests.post = _montar(200, {"choices": [{"message": {"content": "hola"}}],
                              "usage": {"prompt_tokens": 3,
                                        "completion_tokens": 2}})
time.sleep = lambda _s: None
try:
    texto = motor.llamar(motor.Llamada(proveedor="glm", modelo="glm-4.6",
                                       instruccion="hola"), CLAVES)
    check("llamar sigue devolviendo el texto", texto == "hola")
    check("una llamada que va bien anota ok",
          salud_llm.de("glm")["estado"] == "ok")

    usos: list = []
    requests.post = _montar(401, {"error": "unauthorized"}, contador=usos)
    try:
        motor.llamar(motor.Llamada(proveedor="glm", modelo="glm-4.6",
                                   instruccion="hola"), CLAVES)
        check("un 401 levanta ErrorLLM", False)
    except motor.ErrorLLM:
        check("un 401 levanta ErrorLLM", True)
    check("el 401 anota sesion sin gastar reintentos",
          salud_llm.de("glm")["estado"] == "sesion" and len(usos) == 1,
          f"estado={salud_llm.de('glm')['estado']}, intentos={len(usos)}")

    requests.post = _montar(429, {"error": "rate limit exceeded"})
    try:
        motor.llamar(motor.Llamada(proveedor="glm", modelo="glm-4.6",
                                   instruccion="hola"), CLAVES)
        check("el 429 agotado levanta ErrorLLM", False)
    except motor.ErrorLLM:
        check("el 429 agotado levanta ErrorLLM", True)
    check("el 429 agotado anota cupo tras los intentos",
          salud_llm.de("glm")["estado"] == "cupo")

    requests.get = _montar(200, {"data": []})
    resultado = motor.probar("glm", CLAVES)
    check("probar con clave valida anota ok",
          resultado["ok"] and salud_llm.de("glm")["estado"] == "ok")

    check("sin clave, probar no anota salud (nadie llamó)",
          motor.probar("anthropic", {})["detalle"] == "sin clave"
          and "anthropic" not in salud_llm.leer())
finally:
    requests.post, requests.get = _post_real, _get_real
    time.sleep = _dormir_real

# ---------------------------------------------------------------- por HTTP

r = cliente.get("/api/salud/llm")
datos = r.json() if r.status_code == 200 else {}
check("GET /api/salud/llm trae las fichas con su frase",
      r.status_code == 200 and datos.get("glm", {}).get("estado") == "ok"
      and "GLM" in datos.get("glm", {}).get("frase", ""),
      str(datos)[:200])

# --------------------------------------------------------------------- sale

if fallos:
    print(f"\n{len(fallos)} fallo(s): " + ", ".join(fallos))
    sys.exit(1)
print("\nOK — humo de la salud del LLM")
