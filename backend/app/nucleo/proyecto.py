"""Proyectos: el arbol en disco, JSON seguro y cerrojos de escritura.

Patrones tomados del original (y comprobados alli durante meses):
- `ruta_contenida`: TODO nombre que venga de un modelo o del usuario se une
  bajo la raiz del proyecto y se verifica con realpath — un ".." o una ruta
  absoluta no es hipotetico (docs/AUDITORIA.md H8).
- `leer_json`/`escribir_json`: escritura atomica (tmp + replace) para que un
  proceso caido a medias no deje un JSON roto.
- `lock_de`: cerrojo por proyecto para serializar escrituras de estado.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

#: ids de proyecto y de paso: minusculas, numeros y guion. Lo demas, fuera.
PATRON_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Cerraduras de proceso (un escritor de estado por proyecto a la vez).
#: RLock porque las rutas a veces anidan lock_de(pid) sobre llamadas que
#: ya toman el cerrojo del mismo proyecto (guardar_params): un Lock
#: plano se autobloquearia en el mismo hilo.
_CERROJOS: dict[str, threading.RLock] = {}
_CERROJOS_GUARDIA = threading.Lock()


def ahora() -> str:
    """Marca de tiempo ISO-8601 en UTC con segundos."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def id_valido(texto: object) -> bool:
    return isinstance(texto, str) and bool(PATRON_ID.fullmatch(texto))


def nuevo_id(prefijo: str = "p") -> str:
    import secrets
    return f"{prefijo}_{secrets.token_hex(4)}"


@contextmanager
def lock_de(clave: str):
    """Cerrojo por clave (id de proyecto): escrituras serializadas."""
    with _CERROJOS_GUARDIA:
        cerrojo = _CERROJOS.setdefault(clave, threading.RLock())
    with cerrojo:
        yield


def ruta_contenida(raiz: Path | str, *partes: object) -> Path:
    """Une partes bajo raiz y falla si el resultado se sale de raiz.

    Los nombres que llegan aqui vienen de JSON generado por modelos y de
    parametros que edita el usuario: un '..' o una ruta absoluta no es
    hipotetico. (Patrón del original, nucleo/proyecto.py:343.)
    """
    base = Path(os.path.abspath(raiz))
    trozos = []
    for parte in partes:
        texto = str(parte)
        if "\x00" in texto:
            raise ValueError("ruta invalida: contiene un byte nulo")
        trozos.append(texto)
    destino = Path(os.path.abspath(os.path.join(base, *trozos))) if trozos else base
    entero = os.path.normcase(os.path.realpath(destino))
    dentro = os.path.normcase(os.path.realpath(base))
    if entero != dentro and not entero.startswith(dentro + os.sep):
        raise ValueError(f"ruta fuera del proyecto: {os.path.join(*trozos)!r}")
    return destino


def leer_json(ruta: Path | str, por_defecto=None):
    """Lee JSON; si no existe, `por_defecto` (copia nueva si es dict/list)."""
    try:
        with open(ruta, "r", encoding="utf-8") as fichero:
            return json.load(fichero)
    except FileNotFoundError:
        if por_defecto is not None and isinstance(por_defecto, (dict, list)):
            import copy
            return copy.deepcopy(por_defecto)
        return por_defecto
    except (OSError, ValueError) as fallo:
        raise RuntimeError(f"no se puede leer {ruta}: {fallo}") from fallo


def leer_jsonl(ruta: Path | str) -> list:
    """Lee un JSONL (una entrada por linea), tolerando lineas vacias."""
    entradas = []
    try:
        with open(ruta, "r", encoding="utf-8") as fichero:
            for linea in fichero:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entradas.append(json.loads(linea))
                except ValueError:
                    continue  # una linea cortada a medias no tumba la lectura
    except FileNotFoundError:
        pass
    return entradas


def escribir_json(ruta: Path | str, datos) -> None:
    """Escritura atomica: tmp en el mismo directorio + os.replace."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(
        dir=str(ruta.parent), prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
            json.dump(datos, fichero, ensure_ascii=False, separators=(",", ":"))
            fichero.flush()
            os.fsync(fichero.fileno())
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def anadir_jsonl(ruta: Path | str, entrada: dict) -> None:
    """Anade una linea a un JSONL (bitacora, coste)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as fichero:
        fichero.write(json.dumps(entrada, ensure_ascii=False) + "\n")


class Proyecto:
    """Vista tipada de un proyecto en disco.

    Arbol (los ids de paso NO cambian, igual que el original):

        datos/proyectos/<pid>/
        ├── proyecto.json          # titulo, canal, creado, config
        ├── estado.json            # versiones y firmas por paso
        ├── pasos/<paso>/          # salida del paso
        │   ├── datos.json         # contenido actual
        │   └── _versiones/vN.json  # manifiesto de la version N
        ├── bitacora.jsonl         # eventos
        └── coste.jsonl            # consumo (euros/dolares por operacion)
    """

    def __init__(self, raiz: Path | str):
        self.raiz = Path(raiz)
        self.id = self.raiz.name

    # ------------------------------------------------------------ rutas
    def ruta(self, *partes: object) -> Path:
        return ruta_contenida(self.raiz, *partes)

    @property
    def fichero_proyecto(self) -> Path:
        return self.raiz / "proyecto.json"

    @property
    def fichero_estado(self) -> Path:
        return self.raiz / "estado.json"

    @property
    def fichero_bitacora(self) -> Path:
        return self.raiz / "bitacora.jsonl"

    @property
    def fichero_coste(self) -> Path:
        return self.raiz / "coste.jsonl"

    def carpeta_paso(self, paso: str) -> Path:
        if not id_valido(paso):
            raise ValueError(f"id de paso invalido: {paso!r}")
        return self.ruta("pasos", paso)

    # ------------------------------------------------------------ datos
    def leer(self) -> dict:
        datos = leer_json(self.fichero_proyecto, {})
        if not datos:
            raise FileNotFoundError(f"proyecto inexistente: {self.id}")
        return datos

    def escribir(self, datos: dict) -> None:
        escribir_json(self.fichero_proyecto, datos)

    def existe(self) -> bool:
        return self.fichero_proyecto.is_file()

    def bitacora(self, evento: str, detalle: dict | None = None) -> None:
        anadir_jsonl(self.fichero_bitacora,
                     {"t": ahora(), "evento": evento, **(detalle or {})})

    # ------------------------------------------------------------ listado
    @staticmethod
    def listar(carpeta_raiz: Path | str) -> list["Proyecto"]:
        raiz = Path(carpeta_raiz)
        if not raiz.is_dir():
            return []
        lista = []
        for entrada in sorted(raiz.iterdir()):
            if entrada.is_dir() and not entrada.name.startswith(("_", ".")):
                proyecto = Proyecto(entrada)
                if proyecto.existe():
                    lista.append(proyecto)
        return lista
