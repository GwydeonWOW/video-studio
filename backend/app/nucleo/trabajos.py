"""Trabajos en segundo plano: cola por proyecto, eventos y cancelacion.

Modelo (simplificado del original):
- Un TRABAJO ejecuta un paso de un proyecto (o una unidad concreta de el).
- Un trabajador por proyecto: dentro de un proyecto nada corre en paralelo
  (las tandas de imagenes ya van de una en una por coste, y el estado se
  escribe con cerrojo).
- Los trabajos exponen eventos (lineas de progreso) que la pantalla lee por
  SSE; y se pueden CANCELAR por peticion (bandera que el paso consulta).
- Todo trabajo tiene tope de tiempo: nada queda 'ejecutando' para siempre.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field

try:
    from .proyecto import ahora
except ImportError:
    from proyecto import ahora  # type: ignore


class TrabajoCancelado(RuntimeError):
    """El usuario cancelo el trabajo."""


@dataclass
class Trabajo:
    id: str
    proyecto: str
    paso: str
    funcion: object = None            # callable(avance) -> resultado
    estado: str = "en_cola"           # en_cola|ejecutando|hecho|fallo|cancelado
    creado: float = field(default_factory=time.time)
    empezado: float | None = None
    terminado: float | None = None
    eventos: list = field(default_factory=list)
    resultado: object = None
    error: str = ""
    cancelado: bool = False
    unidades: list = field(default_factory=list)

    # Callbacks de progreso que el paso usa durante la ejecucion
    def avance(self, mensaje: str) -> None:
        self.eventos.append({"t": ahora(), "mensaje": str(mensaje)[:500]})
        if len(self.eventos) > 400:
            del self.eventos[:200]

    def comprobar_cancelacion(self) -> None:
        if self.cancelado:
            raise TrabajoCancelado("cancelado por el usuario")


class GestorTrabajos:
    """Cola de trabajos con un trabajador por proyecto."""

    def __init__(self, tope_s: int = 25200):
        self._cerrojo = threading.Lock()
        self._trabajos: dict[str, Trabajo] = {}
        self._colas: dict[str, list[str]] = {}
        self._hilos: dict[str, threading.Thread] = {}
        self._tope_s = tope_s
        self._contador = 0

    # ------------------------------------------------------------- alta
    def lanzar(self, proyecto: str, paso: str, funcion, unidades: list | None = None) -> Trabajo:
        """Encola un trabajo y asegura el trabajador del proyecto."""
        with self._cerrojo:
            self._contador += 1
            tid = f"t{self._contador:06d}"
            trabajo = Trabajo(id=tid, proyecto=proyecto, paso=paso,
                              funcion=funcion, unidades=list(unidades or []))
            self._trabajos[tid] = trabajo
            self._colas.setdefault(proyecto, []).append(tid)
            self._asegurar_trabajador(proyecto)
            return trabajo

    def _asegurar_trabajador(self, proyecto: str) -> None:
        hilo = self._hilos.get(proyecto)
        if hilo is not None and hilo.is_alive():
            return
        hilo = threading.Thread(target=self._trabajador, args=(proyecto,),
                                name=f"trabajo-{proyecto}", daemon=True)
        self._hilos[proyecto] = hilo
        hilo.start()

    def _trabajador(self, proyecto: str) -> None:
        while True:
            with self._cerrojo:
                cola = self._colas.get(proyecto, [])
                tid = cola.pop(0) if cola else None
            if tid is None:
                return  # no hay mas trabajo: el hilo muere y se recrea luego
            trabajo = self._trabajos[tid]
            self._ejecutar(trabajo)

    def _ejecutar(self, trabajo: Trabajo) -> None:
        trabajo.estado = "ejecutando"
        trabajo.empezado = time.time()
        try:
            trabajo.resultado = trabajo.funcion(trabajo)
        except TrabajoCancelado:
            trabajo.estado = "cancelado"
        except Exception as fallo:                     # noqa: BLE001
            trabajo.estado = "fallo"
            trabajo.error = f"{fallo}"
            trabajo.eventos.append({"t": ahora(),
                                    "mensaje": f"ERROR: {fallo}"})
            traceback.print_exc()
        else:
            trabajo.estado = "hecho"
        finally:
            trabajo.terminado = time.time()
            # limpieza: trabajos terminados de hace mas de una hora
            self._limpiar()

    # ------------------------------------------------------------ lectura
    def estado(self, tid: str) -> dict:
        trabajo = self._trabajos.get(tid)
        if trabajo is None:
            raise KeyError(tid)
        return self._ficha(trabajo)

    def listar(self, proyecto: str | None = None) -> list[dict]:
        with self._cerrojo:
            lista = [self._ficha(t) for t in self._trabajos.values()
                     if proyecto is None or t.proyecto == proyecto]
        return lista

    def eventos_desde(self, tid: str, indice: int) -> tuple[int, list]:
        trabajo = self._trabajos.get(tid)
        if trabajo is None:
            raise KeyError(tid)
        nuevos = trabajo.eventos[indice:]
        return len(trabajo.eventos), list(nuevos)

    def activo_de(self, proyecto: str) -> dict | None:
        """Trabajo en curso o en cola del proyecto, si lo hay."""
        with self._cerrojo:
            for trabajo in self._trabajos.values():
                if trabajo.proyecto == proyecto and \
                        trabajo.estado in ("en_cola", "ejecutando"):
                    return self._ficha(trabajo)
        return None

    # ---------------------------------------------------------- cancelar
    def cancelar(self, tid: str) -> dict:
        trabajo = self._trabajos.get(tid)
        if trabajo is None:
            raise KeyError(tid)
        if trabajo.estado in ("en_cola", "ejecutando"):
            trabajo.cancelado = True
            trabajo.eventos.append({"t": ahora(), "mensaje": "cancelando..."})
        return self._ficha(trabajo)

    # ------------------------------------------------------------- limpiar
    def _limpiar(self) -> None:
        limite = time.time() - 3600
        with self._cerrojo:
            caducados = [tid for tid, t in self._trabajos.items()
                         if t.terminado and t.terminado < limite]
            for tid in caducados:
                self._trabajos.pop(tid, None)

    @staticmethod
    def _ficha(t: Trabajo) -> dict:
        return {"id": t.id, "proyecto": t.proyecto, "paso": t.paso,
                "estado": t.estado, "unidades": t.unidades,
                "creado": t.creado, "empezado": t.empezado,
                "terminado": t.terminado, "error": t.error,
                "eventos": len(t.eventos)}
