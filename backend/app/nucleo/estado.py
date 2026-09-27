"""Estado por pasos: firmas, versiones e invalidacion en cascada.

El grafo (los ids NO se tocan, igual que en el original):

    ingesta -> brief -> guion -> voz -> revision_audio -> assets -> callouts -> render

Ideas heredadas del original:
- Cada paso guarda una FIRMA = hash de (params + salidas del paso padre).
  Cambiar un param o regenerar un padre cambia la firma: el paso queda
  "obsoleto" y quien decide regenerar es la persona, con el coste delante.
- Cada generacion escribe una VERSION nueva (v1, v2...); revertir vuelve a
  una anterior sin regenerar. El manifiesto de cada version vive FUERA de
  estado.json (lecciones del original documentadas en su CLAUDE.md).
- La invalidacion MARCA en cascada aguas abajo; nunca dispara por si misma.

Simplificaciones honestas respecto al original: alli la firma baja a la
unidad (escena/plano concreto); aqui la firma es por paso + unidades
afectadas cuando el paso lo permite (guion por escena, assets por plano).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

try:
    from .proyecto import (Proyecto, ahora, escribir_json, leer_json, lock_de)
except ImportError:  # ejecutado suelto
    from proyecto import (Proyecto, ahora, escribir_json, leer_json,  # type: ignore
                          lock_de)

#: El grafo, en orden. Los ids son permanentes.
GRAFO = ["ingesta", "brief", "guion", "voz", "revision_audio",
         "assets", "callouts", "render"]

_PADRES = {
    "ingesta": [],
    "brief": ["ingesta"],
    "guion": ["brief"],
    "voz": ["guion"],
    "revision_audio": ["voz"],
    "assets": ["guion"],
    "callouts": ["assets"],
    "render": ["revision_audio", "callouts"],
}


def descendientes_de(paso: str) -> list[str]:
    """Hijos directos y lejanos en el grafo, en orden topologico."""
    salida, cola = [], [paso]
    while cola:
        actual = cola.pop(0)
        for candidato, padres in _PADRES.items():
            if actual in padres and candidato not in salida:
                salida.append(candidato)
                cola.append(candidato)
    return [p for p in GRAFO if p in salida]


def padres_de(paso: str) -> list[str]:
    return list(_PADRES.get(paso, []))


def _huella(valor) -> str:
    """Hash corto y estable de cualquier estructura JSON-able."""
    texto = json.dumps(valor, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def firma_de(paso: str, params: dict, salidas_padres: dict) -> str:
    """Firma del paso: params propios + sellos de salida de los padres."""
    return _huella({"paso": paso, "params": params, "padres": salidas_padres})


class Estado:
    """Lee y escribe el estado de un proyecto con cerrojo.

    Formato de estado.json (plano y auditable):

        {
          "pasos": {
            "guion": {
              "version": 3,            # version activa
              "firma": "ab12...",      # firma con la que se genero
              "firma_calculada": "cd34...",  # la que toca por los params
              "params": {...},         # lo ultimo GUARDADO por la pantalla
              "sello_salida": "ef56..."  # hash del contenido producido
            }, ...
          }
        }

    `firma != firma_calculada` => obsoleto: params o padres cambiaron.
    """

    def __init__(self, proyecto: Proyecto):
        self.proyecto = proyecto

    # ------------------------------------------------------------- lectura
    def todo(self) -> dict:
        return leer_json(self.proyecto.fichero_estado,
                         por_defecto={"pasos": {}})

    def paso(self, nombre: str) -> dict:
        return self.todo().get("pasos", {}).get(nombre, {})

    def datos_de(self, paso: str) -> dict | list | None:
        """El contenido actual de un paso (datos.json), o None."""
        fichero = self.proyecto.carpeta_paso(paso) / "datos.json"
        from .proyecto import leer_json as _leer
        try:
            return _leer(fichero, None)
        except RuntimeError:
            return None

    def versiones_de(self, paso: str) -> list[dict]:
        """Manifiestos de todas las versiones, en orden."""
        carpeta = self.proyecto.carpeta_paso(paso) / "_versiones"
        if not carpeta.is_dir():
            return []
        lista = []
        for fichero in sorted(carpeta.glob("v*.json")):
            manifiesto = leer_json(fichero, {})
            if manifiesto:
                lista.append(manifiesto)
        return lista

    def manifiesto_version(self, paso: str, version: int) -> dict:
        fichero = (self.proyecto.carpeta_paso(paso) /
                   "_versiones" / f"v{version}.json")
        datos = leer_json(fichero, None)
        if datos is None:
            raise RuntimeError(f"falta el manifiesto de {paso} v{version}")
        return datos

    # ------------------------------------------------------------ informe
    def estado_de(self, paso: str, params_nuevos: dict | None = None) -> str:
        """'vacio' | 'ok' | 'obsoleto' para un paso.

        `params_nuevos`: params que la pantalla esta editando AHORA (sin
        guardar); con ellos la pantalla puede ensenar lo que PASARIA.
        """
        ficha = self.paso(paso)
        version = ficha.get("version", 0)
        if not version or self.datos_de(paso) is None:
            return "vacio"
        params = params_nuevos if params_nuevos is not None else ficha.get("params", {})
        salidas = {p: self.sello_de(p) for p in padres_de(paso)}
        calculada = firma_de(paso, params, salidas)
        return "ok" if calculada == ficha.get("firma") else "obsoleto"

    def sello_de(self, paso: str) -> str:
        """Sello de salida de un paso (0 si no hay contenido)."""
        ficha = self.paso(paso)
        return str(ficha.get("sello_salida", "0"))

    def resumen(self) -> dict:
        """Estado de todos los pasos para la pantalla."""
        return {paso: {
            "estado": self.estado_de(paso),
            "version": self.paso(paso).get("version", 0),
            "params": self.paso(paso).get("params", {}),
            "aprobado": self.esta_aprobado(paso),
        } for paso in GRAFO}

    def unidades_obsoletas(self, paso: str) -> list:
        """Ids de unidad (escenas/planos) obsoletos de un paso.

        Un paso queda obsoleto POR UNIDADES cuando su padre directo cambio
        solo en parte: p.ej. corregir una escena del guion no invalida las
        imagenes de las demas. La unidad se define por paso:
        guion/voz -> escenas; assets/callouts -> planos.
        """
        ficha = self.paso(paso)
        marcadas = ficha.get("obsoleto_unidades", [])
        return list(marcadas)

    # -------------------------------------------------------- aprobacion
    def esta_aprobado(self, paso: str) -> bool:
        """True si el paso tiene un acta de aprobacion VIGENTE.

        El acta se otorga sobre (version, firma) concretas: regenerar,
        corregir una unidad o revertir dejan el acta sin efecto — una
        version nueva no esta aprobada por defecto. Es la puerta del paso
        de voz: generar audio de un guion en revision es dinero tirado
        (tokens de ElevenLabs por caracter).
        """
        ficha = self.paso(paso)
        acta = ficha.get("aprobacion")
        if not acta or self.estado_de(paso) != "ok":
            return False
        return (acta.get("version") == ficha.get("version")
                and acta.get("firma") == ficha.get("firma"))

    def aprobar(self, paso: str) -> dict:
        """Aprueba la version ACTUAL del paso. -> acta escrita."""
        with lock_de(self.proyecto.id):
            estado = self.todo()
            ficha = estado["pasos"].setdefault(paso, {})
            if not ficha.get("version") or self.datos_de(paso) is None:
                raise RuntimeError(
                    "no hay contenido que aprobar: genera el paso primero")
            acta = {"version": ficha["version"],
                    "firma": ficha.get("firma", ""), "fecha": ahora()}
            ficha["aprobacion"] = acta
            escribir_json(self.proyecto.fichero_estado, estado)
            return acta

    # ------------------------------------------------------------ escritura
    def guardar_params(self, paso: str, params: dict) -> dict:
        """La pantalla guardo params: se escriben y se recalcula la firma."""
        with lock_de(self.proyecto.id):
            estado = self.todo()
            ficha = estado["pasos"].setdefault(paso, {})
            ficha["params"] = params
            salidas = {p: self.sello_de(p) for p in padres_de(paso)}
            ficha["firma_calculada"] = firma_de(paso, params, salidas)
            escribir_json(self.proyecto.fichero_estado, estado)
        return ficha

    def completar(self, paso: str, params: dict, datos, unidades: int = 0) -> int:
        """Un paso termino: escribe datos + manifiesto + estado.

        Orden (leido del original, nucleo/estado.py): PRIMERO el manifiesto
        de la version, DESPUES datos.json, AL FINAL estado.json. Un fallo a
        medias deja la version anterior como activa y valida.
        """
        with lock_de(self.proyecto.id):
            estado = self.todo()
            ficha = estado["pasos"].setdefault(paso, {})
            version = int(ficha.get("version", 0)) + 1
            carpeta = self.proyecto.carpeta_paso(paso)
            manifiesto = {
                "version": version, "fecha": ahora(),
                "firma": firma_de(paso, params,
                                  {p: self.sello_de(p) for p in padres_de(paso)}),
                "params": params,
                "unidades": unidades,
                "resumen": _resumen_de(datos),
            }
            # 1) manifiesto de la version (fuera de estado.json)
            escribir_json(carpeta / "_versiones" / f"v{version}.json", manifiesto)
            # 2) contenido + snapshot de la version (para Revertir)
            escribir_json(carpeta / "datos.json", datos)
            escribir_json(carpeta / "_versiones" / f"datos_v{version}.json", datos)
            # 3) estado
            ficha.update({"version": version, "params": params,
                          "firma": manifiesto["firma"],
                          "firma_calculada": manifiesto["firma"],
                          "sello_salida": _huella({"v": version,
                                                   "datos": _resumen_de(datos)}),
                          "obsoleto_unidades": []})
            # una version nueva no hereda la aprobacion (puerta de voz)
            ficha.pop("aprobacion", None)
            escribir_json(self.proyecto.fichero_estado, estado)
            return version

    def marcar_obsoleto(self, paso: str, unidades: list | None = None) -> None:
        """Marca el paso (y la cascada aguas abajo) como obsoleto.

        Con `unidades`: solo esas unidades. MARCA, no genera: la pantalla
        acciona con el coste delante (regla del original).
        """
        with lock_de(self.proyecto.id):
            estado = self.todo()
            tocados = []
            if unidades is None:
                # el paso entero y todo lo que cuelga
                tocados = [paso] + descendientes_de(paso)
            else:
                ficha = estado["pasos"].setdefault(paso, {})
                marcadas = set(ficha.get("obsoleto_unidades", []))
                marcadas.update(str(u) for u in unidades)
                ficha["obsoleto_unidades"] = sorted(marcadas)
                tocados = descendientes_de(paso)
            for nombre in tocados:
                if nombre == paso and unidades is not None:
                    continue  # ya quedo marcado por unidades
                ficha = estado["pasos"].setdefault(nombre, {})
                ficha["firma_calculada"] = "obsoleto"
            escribir_json(self.proyecto.fichero_estado, estado)

    def revertir(self, paso: str, version: int) -> dict:
        """Vuelve a una version anterior SIN regenerar.

        El manifiesto de esa version debe existir (mismo contrato que el
        original: revertir a una version sin manifiesto es un error).
        """
        manifiesto = self.manifiesto_version(paso, version)
        with lock_de(self.proyecto.id):
            estado = self.todo()
            ficha = estado["pasos"].setdefault(paso, {})
            # el contenido de esa version se recupera del snapshot
            snapshot = self.proyecto.carpeta_paso(paso) / "_versiones" / f"datos_v{version}.json"
            datos = leer_json(snapshot, None) if snapshot.is_file() else None
            if datos is not None:
                from .proyecto import escribir_json as _e
                _e(self.proyecto.carpeta_paso(paso) / "datos.json", datos)
            # el sello se recalcula para la version restaurada: sin esto,
            # revertir dejaria a los hijos "obsoletos" contra un sello que
            # ya no esta activo
            sello = _huella({"v": version,
                             "datos": _resumen_de(datos if datos is not None
                                                  else self.datos_de(paso) or {})})
            ficha.update({"version": version, "params": manifiesto.get("params", {}),
                          "firma": manifiesto.get("firma", ""),
                          "firma_calculada": manifiesto.get("firma", ""),
                          "sello_salida": sello,
                          "obsoleto_unidades": []})
            # revertir tampoco conserva la aprobacion: es otra version
            ficha.pop("aprobacion", None)
            escribir_json(self.proyecto.fichero_estado, estado)
        return manifiesto


def _resumen_de(datos) -> str:
    """Sello de contenido: hash del JSON completo."""
    return _huella(datos)
