"""Fábrica de la aplicación: API + interfaz en un solo servicio.

Arranque:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Todo lo que sobrevive a un reinicio vive en ESTUDIO_DATOS (volumen en
Coolify); la interfaz construida la sirve este proceso desde ESTUDIO_WEB.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import seguridad
from .api import (archivos, rutas_auth, rutas_config, rutas_proyectos,
                  rutas_trabajos)
from .config import AJUSTES, preparar_carpetas


def crear_app() -> FastAPI:
    preparar_carpetas()
    aplicacion = FastAPI(title="Estudio de Vídeo", version="1.0.0",
                         docs_url=None, redoc_url=None, openapi_url=None)

    aplicacion.include_router(rutas_auth.router)
    aplicacion.include_router(rutas_config.router)
    aplicacion.include_router(rutas_trabajos.router)
    aplicacion.include_router(rutas_proyectos.router)
    aplicacion.include_router(archivos.router)

    @aplicacion.exception_handler(StarletteHTTPException)
    async def errores_http(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @aplicacion.exception_handler(RequestValidationError)
    async def errores_validacion(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "cuerpo inválido"}, status_code=400)

    @aplicacion.exception_handler(ValueError)
    async def errores_valor(request: Request, exc: ValueError):
        # rutas_contenida y amigos lanzan ValueError con mensaje accionable
        return JSONResponse({"error": str(exc)}, status_code=400)

    @aplicacion.exception_handler(Exception)
    async def errores_graves(request: Request, exc: Exception):
        return JSONResponse({"error": f"error interno: {exc}"}, status_code=500)

    _montar_interfaz(aplicacion)
    return aplicacion


def _montar_interfaz(aplicacion: FastAPI) -> None:
    """Sirve la web construida (SPA) con su index como respaldo 404.

    Sin dependencias raras: si no hay build, solo queda la API.
    """
    web = Path(AJUSTES.web)
    if not web.is_dir():
        return

    @aplicacion.get("/{ruta:path}", include_in_schema=False)
    async def spa(ruta: str):
        # /api y /a son de la API: un 404 de verdad, nunca el HTML de la
        # SPA (un <video src> caido no deberia recibir index.html con 200)
        if ruta == "api" or ruta == "a" or ruta.startswith(("api/", "a/")):
            return JSONResponse({"error": "no existe"}, status_code=404)
        destino = web / ruta
        # ni subida de directorio ni ficheros fuera del build
        try:
            destino.resolve().relative_to(web.resolve())
        except ValueError:
            destino = web / "index.html"
        if ruta and destino.is_file():
            return FileResponse(destino)
        indice = web / "index.html"
        if indice.is_file():
            return FileResponse(indice)
        return JSONResponse({"error": "no hay interfaz construida"},
                            status_code=404)


app = crear_app()
