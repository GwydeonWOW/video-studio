"""Configuración del Estudio de Vídeo.

Todo viene de variables de entorno (Coolify las inyecta) con valores por
defecto sanos para desarrollo local. Nada de secretos en el código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent


def _bool(valor: str | None, defecto: bool = False) -> bool:
    if valor is None or valor == "":
        return defecto
    return valor.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Ajustes:
    """Ajustes inmutables del servicio, leídos una vez al arrancar."""

    #: Carpeta de datos persistente (volumen en Coolify): proyectos, claves,
    #: sesiones de coste. TODO lo que sobrevive a un reinicio vive aqui.
    datos: Path = field(
        default_factory=lambda: Path(os.environ.get("ESTUDIO_DATOS", RAIZ / "datos")))

    #: Directorio con la interfaz ya construida (la sirve el propio backend).
    web: Path = field(
        default_factory=lambda: Path(os.environ.get("ESTUDIO_WEB", RAIZ / "frontend" / "dist")))

    host: str = os.environ.get("ESTUDIO_HOST", "0.0.0.0")
    puerto: int = int(os.environ.get("ESTUDIO_PUERTO", "8000"))

    #: Login integrado (ver seguridad.py). El hash scrypt va en el entorno en
    #: Coolify; si no hay, se usa el fichero de credenciales del volumen y si
    #: tampoco existe se arranca el flujo de primera instalación por la UI.
    usuario: str = os.environ.get("ESTUDIO_USUARIO", "estudio")
    hash_entorno: str = os.environ.get("ESTUDIO_HASH", "")
    #: URL publica canonica (para el chequeo de Origin cuando hay proxy).
    origen_publico: str = os.environ.get("ESTUDIO_ORIGEN", "")
    #: Origienes extra permitidos para mutaciones, separados por coma.
    origenes_extra: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.environ.get("ESTUDIO_ORIGENES", "").split(",") if o.strip()))

    #: Pruebas y desarrollo: desactiva el login (NUNCA en produccion).
    sin_login: bool = field(default_factory=lambda: _bool(os.environ.get("ESTUDIO_SIN_LOGIN")))

    #: Binarios nativos: dentro del contenedor estan en PATH; en dev pueden
    #: apuntar a rutas locales.
    ffmpeg: str = os.environ.get("ESTUDIO_FFMPEG", "ffmpeg")
    ffprobe: str = os.environ.get("ESTUDIO_FFPROBE", "ffprobe")
    #: Chromium headless para rasterizar planos. Puede ser "chromium",
    #: "chromium-browser" o "google-chrome" segun la imagen.
    chromium: str = os.environ.get("ESTUDIO_CHROMIUM", "chromium")

    #: Cuantos procesos de render en paralelo (el original midio que 8 es el
    #: techo en 8 vCPU; por defecto, la mitad de las CPUs).
    lotes: int = field(default_factory=lambda: int(
        os.environ.get("ESTUDIO_LOTES", str(max(1, (os.cpu_count() or 2) // 2)))))

    #: Duracion maxima de un trabajo completo, en segundos (7 horas).
    tope_trabajo_s: int = int(os.environ.get("ESTUDIO_TOPE_TRABAJO", "25200"))

    #: Calidad de imagen por defecto para proyectos NUEVOS
    #: (low/medium/high de glm-image).
    calidad_imagen: str = os.environ.get("ESTUDIO_CALIDAD_IMAGEN", "low")

    @property
    def carpeta_proyectos(self) -> Path:
        return self.datos / "proyectos"

    @property
    def carpeta_claves(self) -> Path:
        return self.datos / "secretos"

    @property
    def fichero_credenciales(self) -> Path:
        return self.datos / "credenciales.json"

    def origenes_permitidos(self) -> list[str]:
        """Origenes validos para el chequeo CSRF de mutaciones."""
        lista = [self.origen_publico, *self.origenes_extra]
        return [o for o in lista if o]


AJUSTES = Ajustes()


def preparar_carpetas() -> None:
    """Crea el arbol de datos con los permisos mas cerrados posibles."""
    for carpeta in (AJUSTES.datos, AJUSTES.carpeta_proyectos, AJUSTES.carpeta_claves):
        carpeta.mkdir(parents=True, exist_ok=True)
        try:
            # 0o700 en POSIX es un no-op en Windows; el contenedor es Linux.
            carpeta.chmod(0o700)
        except OSError:
            pass
