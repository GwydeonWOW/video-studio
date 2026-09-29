"""Prueba de humo de la Fase K, sin tocar servicios de pago.

Codex OAuth (flujo de dispositivo, sesion y borrado), el proveedor
«codex» del enrutador LLM (SSE de la Responses API) y GLM-Image (la
misma clave GLM dibuja los planos). Todo con HTTP falseado. Ejecutar:

    python pruebas/humo_fasek.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_fasek_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ.pop("ESTUDIO_HASH", None)
os.environ.pop("ESTUDIO_CODEX_TOKEN", None)
os.environ.pop("ESTUDIO_CODEX_CUENTA", None)
sys.path.insert(0, str(_raiz))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.motores import codex_oauth, imagen_glm, llm  # noqa: E402

cliente = TestClient(app)
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


# ------------------------------------------------- HTTP falseado (por módulo)

class _Respuesta:
    def __init__(self, codigo: int = 200, cuerpo: dict | None = None,
                 texto: str = "", contenido: bytes = b"",
                 cabeceras: dict | None = None, lineas: list[str] | None = None):
        self.status_code = codigo
        self._json = cuerpo
        self.text = texto or (json.dumps(cuerpo) if cuerpo is not None else "")
        self.content = contenido
        self.headers = cabeceras or {}
        self._lineas = lineas or []

    def json(self) -> dict:
        if self._json is None:
            raise ValueError("sin json")
        return self._json

    def iter_lines(self, decode_unicode: bool = False) -> list[str]:
        return list(self._lineas)


class _HTTP:
    """Cola de respuestas por método; recuerda la última petición."""

    def __init__(self) -> None:
        self.cola_post: list[_Respuesta] = []
        self.cola_get: list[_Respuesta] = []
        self.peticiones: list[dict] = []

    def post(self, url: str, **kwargs) -> _Respuesta:
        self.peticiones.append({"metodo": "POST", "url": url, **kwargs})
        return self.cola_post.pop(0)

    def get(self, url: str, **kwargs) -> _Respuesta:
        self.peticiones.append({"metodo": "GET", "url": url, **kwargs})
        return self.cola_get.pop(0)


def _jwt(carga: dict) -> str:
    """Un id_token de mentira (aqui no hace falta firma: acababa de
    llegar del endpoint oficial)."""
    def b64(parte: dict) -> str:
        crudo = base64.urlsafe_b64encode(json.dumps(parte).encode())
        return crudo.decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64(carga)}."


_red_codex = _HTTP()
_red_llm = _HTTP()
_red_imagen = _HTTP()
codex_oauth.requests = _red_codex      # type: ignore[assignment]
llm.requests = _red_llm                # type: ignore[assignment]
imagen_glm.requests = _red_imagen      # type: ignore[assignment]

# --------------------------------------------- instalación (deja la cookie)

cliente.post("/api/auth/instalar", json={"contrasena": "una-clave-larga"})

# --------------------------------------------- codex: flujo de dispositivo

ID_TOKEN = _jwt({
    "email": "prueba@ejemplo.com",
    "https://api.openai.com/auth": {"chatgpt_account_id": "cuenta-1"},
})

from datetime import datetime, timedelta, timezone  # noqa: E402

_red_codex.cola_post.append(_Respuesta(cuerpo={
    "device_auth_id": "deviceauth-123", "user_code": "ABCD-EFGH",
    "interval": "5",
    "expires_at": (datetime.now(timezone.utc)
                   + timedelta(minutes=15)).isoformat(),
}))
r = cliente.post("/api/codex/conectar")
flujo = r.json()
check("POST codex/conectar: el código que se pinta",
      r.status_code == 200 and flujo.get("user_code") == "ABCD-EFGH"
      and flujo.get("verification_uri", "").endswith("/codex/device")
      and flujo.get("intervalo_s", 0) >= 2
      and flujo.get("expira_s", 0) > 800,
      str(r.text)[:120])

r = cliente.get("/api/codex")
check("GET codex: flujo pendiente, sesión aún no",
      r.status_code == 200 and r.json().get("pendiente") is True
      and r.json().get("conectado") is False)

# en el endpoint nuevo, «aún sin confirmar» es 404 (o 403)
_red_codex.cola_post.append(
    _Respuesta(codigo=404, cuerpo={"error": "not found"}))
r = cliente.post("/api/codex/sondeo")
check("sondeo antes de confirmar en el navegador: pendiente",
      r.status_code == 200 and r.json().get("estado") == "pendiente")

# confirmado: el sondeo devuelve el authorization_code con su
# code_verifier, y el canje (form) trae la sesión
_red_codex.cola_post.append(_Respuesta(cuerpo={
    "authorization_code": "authz-1", "code_challenge": "reto",
    "code_verifier": "verificador-1"}))
_red_codex.cola_post.append(_Respuesta(cuerpo={
    "access_token": "acc-1", "refresh_token": "ref-1",
    "expires_in": 3600, "id_token": ID_TOKEN}))
r = cliente.post("/api/codex/sondeo")
check("sondeo tras confirmar: conectado y quien",
      r.status_code == 200 and r.json().get("estado") == "conectado"
      and r.json().get("correo") == "prueba@ejemplo.com",
      str(r.text)[:120])
canje = next((p for p in _red_codex.peticiones
              if p["url"].endswith("/oauth/token")), None)
check("el canje del código es form contra /oauth/token",
      canje is not None
      and canje.get("data", {}).get("redirect_uri", "")
          .endswith("/deviceauth/callback")
      and canje.get("data", {}).get("code") == "authz-1"
      and canje.get("data", {}).get("code_verifier") == "verificador-1",
      str(canje)[:160])

r = cliente.get("/api/codex")
check("GET codex conectado: correo y caducidad",
      r.status_code == 200 and r.json().get("conectado") is True
      and r.json().get("correo") == "prueba@ejemplo.com"
      and r.json().get("expira", 0) > 0
      and r.json().get("pendiente") is False)

from app.config import AJUSTES  # noqa: E402
fichero_sesion = codex_oauth.fichero(AJUSTES.carpeta_claves)
sesion = json.loads(fichero_sesion.read_text(encoding="utf-8"))
check("la sesión vive en secretos/codex.json (con refresh y cuenta)",
      sesion.get("refresh_token") == "ref-1"
      and sesion.get("cuenta_id") == "cuenta-1"
      and sesion.get("correo") == "prueba@ejemplo.com")

r = cliente.get("/api/claves")
fila = next((c for c in r.json() if c["clave"] == "codex"), None)
check("GET claves: fila de codex detrás de GLM (correo, no máscara)",
      fila is not None and fila["presente"] is True
      and fila["mascara"] == "prueba@ejemplo.com"
      and fila["variable"] == "/api/codex")

# -------------------------------- codex: el LLM (Responses API con SSE)

os.environ["ESTUDIO_CODEX_TOKEN"] = "token-entorno"
os.environ["ESTUDIO_CODEX_CUENTA"] = "cuenta-entorno"
_red_llm.cola_post.append(_Respuesta(
    cabeceras={"content-type": "text/event-stream"},
    lineas=[
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"hol"}',
        '',
        'data: {"type":"response.completed","response":{"output":['
        '{"type":"message","content":[{"type":"output_text",'
        '"text":"hola desde codex"}]}],'
        '"usage":{"input_tokens":11,"output_tokens":7}}}',
    ]))
texto = llm.llamar(llm.Llamada(proveedor="codex", modelo="gpt-5.2-codex",
                               instruccion="di hola"))
check("llamar(codex) drena el SSE hasta response.completed",
      texto == "hola desde codex", texto[:80])
cabeceras = _red_llm.peticiones[-1]["headers"]
url = _red_llm.peticiones[-1]["url"]
check("la llamada va al backend de Codex con sus cabeceras",
      url.endswith("/responses")
      and cabeceras.get("Authorization") == "Bearer token-entorno"
      and cabeceras.get("chatgpt-account-id") == "cuenta-entorno"
      and cabeceras.get("originator") == "codex_cli_rs",
      url)
os.environ.pop("ESTUDIO_CODEX_TOKEN")
os.environ.pop("ESTUDIO_CODEX_CUENTA")

# glm (Coding Plan): misma clave, endpoint propio de la suscripcion
_red_llm.cola_post.append(_Respuesta(cuerpo={
    "choices": [{"message": {"content": "hola glm"}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2}}))
texto = llm.llamar(llm.Llamada(proveedor="glm", modelo="glm-5.3",
                               instruccion="di hola"),
                   claves={"glm": "clave-glm"})
check("llamar(glm) ataca el endpoint del Coding Plan",
      texto == "hola glm" and _red_llm.peticiones[-1]["url"]
      == "https://api.z.ai/api/coding/paas/v4/chat/completions",
      _red_llm.peticiones[-1]["url"])

# -------------------------------- codex: caducidad y desconexión

_red_codex.cola_post.append(_Respuesta(cuerpo={
    "device_auth_id": "deviceauth-456", "user_code": "ZZZZ-ZZZZ",
    "interval": "5", "expires_at": ""}))
r = cliente.post("/api/codex/conectar")
check("segunda conexión para probar la caducidad",
      r.status_code == 200 and r.json().get("user_code") == "ZZZZ-ZZZZ")
codex_oauth._pendiente["caduca"] = 0.0            # envejece el flujo
r = cliente.post("/api/codex/sondeo")
check("flujo caducado: expirado sin tocar la red",
      r.status_code == 200 and r.json().get("estado") == "expirado")

r = cliente.delete("/api/codex")
check("DELETE codex: sesión borrada",
      r.status_code == 200 and r.json().get("conectado") is False
      and not fichero_sesion.exists())

r = cliente.get("/api/codex")
check("GET codex tras borrar: desconectado",
      r.json().get("conectado") is False and r.json().get("correo") == "")

# codex NO es una clave pegable: PUT /api/claves no puede fijarla
r = cliente.put("/api/claves", json={"codex": "intruso"})
fila = next((c for c in r.json() if c["clave"] == "codex"), None)
check("PUT claves no admite codex (no es del catálogo)",
      r.status_code == 200 and fila is not None
      and fila["presente"] is False and fila["mascara"] == "",
      str(r.text)[:120])

# ------------------------------------------- GLM-Image (misma clave GLM)

carpeta_img = Path(_dir_datos) / "imagenes"

_red_imagen.cola_post.append(_Respuesta(cuerpo={
    "data": [{"url": "https://cdn.ejemplo.com/plano.png"}]}))
_red_imagen.cola_get.append(_Respuesta(contenido=b"png-descargado"))
destino = imagen_glm.generar("un plano del puerto al amanecer",
                             carpeta_img / "p1.png",
                             calidad="high", claves={"glm": "clave-glm"})
check("GLM-Image por URL: descarga y escribe el png",
      destino == carpeta_img / "p1.png"
      and destino.read_bytes() == b"png-descargado")
cuerpo_enviado = _red_imagen.peticiones[0]["json"]
check("el cuerpo pide glm-image con el tamaño de la calidad",
      cuerpo_enviado["model"] == "glm-image"
      and cuerpo_enviado["size"] == "1728x960")

_red_imagen.cola_post.append(_Respuesta(cuerpo={
    "data": [{"b64_json": base64.b64encode(b"png-embebido").decode()}]}))
destino = imagen_glm.generar("plano vertical", carpeta_img / "p2.png",
                             claves={"glm": "clave-glm"}, vertical=True)
check("GLM-Image con b64 embebido también cae en el fichero",
      destino.read_bytes() == b"png-embebido"
      and _red_imagen.peticiones[-1]["json"]["size"] == "768x1344")

_red_imagen.cola_get.append(_Respuesta(codigo=200))
check("probar la clave de GLM-Image lista modelos (gratis)",
      imagen_glm.probar({"glm": "clave-glm"})["ok"] is True)

# -------------------------------------------------------------------- cierre

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    for f in fallos:
        print(" -", f)
    sys.exit(1)
print("fase K en verde")
