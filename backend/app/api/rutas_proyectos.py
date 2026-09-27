"""Proyectos y pasos: CRUD, params, ejecución, versiones y unidades.

Reglas heredadas del original (su CLAUDE.md):
- Nunca se escriben params "por defecto" al abrir una pantalla: solo se
  guarda lo que la persona toca (mover la firma mueve el coste).
- La invalidación MARCA en cascada; GENERAR la acciona una persona con el
  coste delante. Este módulo jamás encadena regeneraciones.
- Las unidades (escenas/planos) se corrigen sueltas: reescribir una escena
  del guion no invalida las imágenes de las demás.
"""
from __future__ import annotations

import re
import shutil
import unicodedata

from fastapi import APIRouter, Depends, HTTPException

from .. import seguridad
from ..config import AJUSTES
from ..nucleo.coste import de_proyecto
from ..nucleo.estado import GRAFO, Estado, descendientes_de
from ..nucleo.proyecto import (Proyecto, ahora, id_valido, leer_jsonl,
                               lock_de)
from ..pasos import p3_guion, p4_voz, p6_assets, registro
from .rutas_trabajos import GESTOR

router = APIRouter(prefix="/api/proyectos", tags=["proyectos"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]

#: campos de datos.json que son listas de unidades, y su clave
_CAMPOS_UNIDADES = {"planos": "escena", "escenas": "id"}


# ------------------------------------------------------------------ auxiliares

def _proyecto_o_404(pid: str) -> Proyecto:
    if not id_valido(pid):
        raise HTTPException(404, "proyecto desconocido")
    proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
    if not proyecto.existe():
        raise HTTPException(404, "proyecto desconocido")
    return proyecto


def _paso_o_404(paso: str) -> str:
    if paso not in GRAFO:
        raise HTTPException(404, "paso desconocido")
    return paso


def _slug(nombre: str) -> str:
    """id legible a partir del nombre: minusculas, sin acentos, guiones."""
    texto = unicodedata.normalize("NFKD", nombre or "")
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:48]
    return texto or "proyecto"


def _id_libre(base: str) -> str:
    """El slug, con sufijo _2, _3... si ya existe (patron del original)."""
    if not (AJUSTES.carpeta_proyectos / base).exists():
        return base
    indice = 2
    while (AJUSTES.carpeta_proyectos / f"{base}_{indice}").exists():
        indice += 1
    return f"{base}_{indice}"


def _contar_unidades(datos) -> int:
    if not isinstance(datos, dict):
        return 0
    for campo in _CAMPOS_UNIDADES:
        if isinstance(datos.get(campo), list):
            return len(datos[campo])
    return 0


def _fusionar_unidades(previo: dict, nuevo: dict, unidades: list[str]) -> dict:
    """Sustituye SOLO las unidades regeneradas dentro de los datos previos.

    `ejecutar(solo_escenas=...)` devuelve una salida parcial; la versión
    nueva del paso debe contener todo el material, no solo lo rehecho.
    """
    mezcla = dict(previo or {})
    cambios = set(str(u) for u in unidades)
    for campo, clave in _CAMPOS_UNIDADES.items():
        viejos = mezcla.get(campo)
        recientes = nuevo.get(campo)
        if not (isinstance(viejos, list) and isinstance(recientes, list)):
            continue
        traidos = {str(u.get(clave, "")): u for u in recientes
                   if isinstance(u, dict)}
        lista = []
        for unidad in viejos:
            llave = str(unidad.get(clave, "")) if isinstance(unidad, dict) else ""
            lista.append(traidos.pop(llave, unidad) if llave in cambios else unidad)
        lista.extend(traidos.values())  # unidades nuevas que no existian
        mezcla[campo] = lista
    # campos escalares frescos (calidad, estado...) mandan
    for clave, valor in nuevo.items():
        if clave not in _CAMPOS_UNIDADES:
            mezcla[clave] = valor
    return mezcla


def _ficha_proyecto(proyecto: Proyecto) -> dict:
    datos = proyecto.leer()
    estado = Estado(proyecto)
    return {"id": proyecto.id, "nombre": datos.get("nombre", proyecto.id),
            "canal": datos.get("canal", ""), "idioma": datos.get("idioma", "es"),
            "creado": datos.get("creado"), "actualizado": datos.get("actualizado"),
            "pasos": estado.resumen(),
            "coste": de_proyecto(proyecto.raiz).get("coste", 0.0),
            "activo": GESTOR.activo_de(proyecto.id)}


# ------------------------------------------------------------------ colección

@router.get("", dependencies=[_SESION])
def listar() -> list[dict]:
    return [_ficha_proyecto(p) for p in Proyecto.listar(AJUSTES.carpeta_proyectos)]


@router.post("", status_code=201, dependencies=_MUTAR)
def crear(cuerpo: dict) -> dict:
    nombre = str(cuerpo.get("nombre", "")).strip()
    if not nombre:
        raise HTTPException(400, "el proyecto necesita un nombre")
    pid = _id_libre(_slug(nombre))
    proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
    proyecto.escribir({"id": pid, "nombre": nombre,
                       "canal": str(cuerpo.get("canal", "")).strip(),
                       "idioma": str(cuerpo.get("idioma", "es")),
                       "creado": ahora(), "actualizado": ahora()})
    # los params base se siembran AL CREAR (nunca al abrir la pantalla):
    # la calidad de imagen entra en la firma y cambiarla despues dejaria
    # obsoleto solo lo de abajo (regla del original)
    estado = Estado(proyecto)
    for paso in GRAFO:
        estado.guardar_params(paso, registro.params_defecto_de(paso))
    proyecto.bitacora("proyecto_creado", {"nombre": nombre})
    return _ficha_proyecto(proyecto)


# ------------------------------------------------------------------ papelera
# OJO al orden: estas rutas van ANTES que /{pid} para que "papelera" no se
# trague el parametro de ruta.

@router.get("/papelera", dependencies=[_SESION])
def listar_papelera() -> list[dict]:
    papelera = AJUSTES.datos / "papelera"
    if not papelera.is_dir():
        return []
    salida = []
    for carpeta in sorted(papelera.iterdir()):
        ficha = leer_json(carpeta / "proyecto.json", None)
        if ficha:
            salida.append({"carpeta": carpeta.name,
                           "id": ficha.get("id", carpeta.name),
                           "nombre": ficha.get("nombre", carpeta.name),
                           "apartado": ficha.get("actualizado", "")})
    return salida


@router.post("/papelera/{carpeta}/restaurar", status_code=201, dependencies=_MUTAR)
def restaurar(carpeta: str) -> dict:
    origen = AJUSTES.datos / "papelera" / carpeta
    if not origen.is_dir():
        raise HTTPException(404, "no está en la papelera")
    ficha = leer_json(origen / "proyecto.json", {}) or {}
    pid = _id_libre(_slug(str(ficha.get("nombre", carpeta))) if ficha else carpeta)
    destino = AJUSTES.carpeta_proyectos / pid
    shutil.move(str(origen), str(destino))
    proyecto = Proyecto(destino)
    datos = proyecto.leer()
    datos.update({"id": pid, "actualizado": ahora()})
    proyecto.escribir(datos)
    proyecto.bitacora("proyecto_restaurado", {})
    return _ficha_proyecto(proyecto)


@router.delete("/papelera/{carpeta}", status_code=204, dependencies=_MUTAR)
def borrar_definitivo(carpeta: str):
    origen = AJUSTES.datos / "papelera" / carpeta
    if not origen.is_dir():
        raise HTTPException(404, "no está en la papelera")
    shutil.rmtree(origen)


@router.post("/{pid}/duplicar", status_code=201, dependencies=_MUTAR)
def duplicar(pid: str) -> dict:
    origen = _proyecto_o_404(pid)
    if GESTOR.activo_de(pid):
        raise HTTPException(409, "hay un trabajo en marcha en ese proyecto")
    datos = origen.leer()
    nuevo_id = _id_libre(_slug(str(datos.get("nombre", pid))))
    destino = AJUSTES.carpeta_proyectos / nuevo_id
    shutil.copytree(origen.raiz, destino)
    copia = Proyecto(destino)
    datos.update({"id": nuevo_id, "nombre": f"{datos.get('nombre', pid)} (copia)",
                  "creado": ahora(), "actualizado": ahora(), "copia_de": pid})
    copia.escribir(datos)
    copia.bitacora("proyecto_duplicado", {"de": pid})
    return _ficha_proyecto(copia)


# ------------------------------------------------------------------ elemento

@router.get("/{pid}", dependencies=[_SESION])
def detalle(pid: str) -> dict:
    return _ficha_proyecto(_proyecto_o_404(pid))


@router.put("/{pid}", dependencies=_MUTAR)
def renombrar(pid: str, cuerpo: dict) -> dict:
    proyecto = _proyecto_o_404(pid)
    datos = proyecto.leer()
    for campo in ("nombre", "canal", "idioma"):
        if campo in cuerpo:
            valor = str(cuerpo[campo]).strip()
            if campo == "nombre" and not valor:
                raise HTTPException(400, "el nombre no puede quedar vacío")
            datos[campo] = valor
    datos["actualizado"] = ahora()
    proyecto.escribir(datos)
    return _ficha_proyecto(proyecto)


@router.delete("/{pid}", status_code=204, dependencies=_MUTAR)
def apartar(pid: str):
    proyecto = _proyecto_o_404(pid)
    if GESTOR.activo_de(pid):
        raise HTTPException(409, "hay un trabajo en marcha en ese proyecto")
    papelera = AJUSTES.datos / "papelera"
    papelera.mkdir(parents=True, exist_ok=True)
    destino = papelera / pid
    indice = 2
    while destino.exists():
        destino = papelera / f"{pid}_{indice}"
        indice += 1
    shutil.move(str(proyecto.raiz), str(destino))
    proyecto.bitacora("proyecto_apartado", {})


# -------------------------------------------------------------------- pasos

@router.get("/{pid}/pasos", dependencies=[_SESION])
def pasos_de(pid: str) -> dict:
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    salida = {}
    for paso in GRAFO:
        ficha = estado.paso(paso)
        salida[paso] = {
            "estado": estado.estado_de(paso),
            "version": ficha.get("version", 0),
            "params": ficha.get("params", {}),
            "unidades_obsoletas": estado.unidades_obsoletas(paso),
            "aprobado": estado.esta_aprobado(paso),
        }
    return {"grafo": registro.todos(), "pasos": salida}


@router.get("/{pid}/pasos/{paso}", dependencies=[_SESION])
def ficha_paso(pid: str, paso: str) -> dict:
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    estado = Estado(proyecto)
    datos = estado.datos_de(paso)
    if datos is None:
        raise HTTPException(404, "ese paso aún no se ha generado")
    return {"paso": paso,
            "estado": estado.estado_de(paso),
            "version": estado.paso(paso).get("version", 0),
            "params": estado.paso(paso).get("params", {}),
            "unidades_obsoletas": estado.unidades_obsoletas(paso),
            "aprobado": estado.esta_aprobado(paso),
            "datos": datos}


@router.put("/{pid}/pasos/{paso}/params", dependencies=_MUTAR)
def guardar_params(pid: str, paso: str, cuerpo: dict) -> dict:
    """Guarda los params editados. Respuesta con la cascada VISIBLE:
    qué quedará obsoleto cuando el paso se regenere (nunca se regenera
    solo)."""
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    estado = Estado(proyecto)
    if not isinstance(cuerpo, dict) or not cuerpo:
        raise HTTPException(400, "se esperaba un objeto de params")
    with lock_de(pid):
        estado.guardar_params(paso, cuerpo)
        datos = proyecto.leer()
        datos["actualizado"] = ahora()
        proyecto.escribir(datos)
    # la cascada que VERIA la persona al regenerar: hijos con material
    obsoletos = [h for h in descendientes_de(paso)
                 if estado.estado_de(h) != "vacio"]
    return {"paso": paso, "estado": estado.estado_de(paso),
            "obsoletos_al_regenerar": obsoletos}


@router.get("/{pid}/pasos/{paso}/estimacion", dependencies=[_SESION])
def estimacion(pid: str, paso: str) -> dict:
    """Coste previsto del paso con los params guardados (pantalla)."""
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    params = Estado(proyecto).paso(paso).get("params", {})
    modulo = registro.modulo_de(paso)
    return modulo.estimar(params)


@router.post("/{pid}/pasos/{paso}/ejecutar", status_code=202, dependencies=_MUTAR)
def ejecutar(pid: str, paso: str, cuerpo: dict | None = None) -> dict:
    """Lanza el paso como trabajo en segundo plano (cola por proyecto)."""
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    cuerpo = cuerpo or {}
    unidades = [str(u) for u in cuerpo.get("unidades") or []]
    estado = Estado(proyecto)
    # la locucion cuesta por caracter: solo con el guion aprobado, para no
    # grabar (y pagar) audio de un guion que sigue en revision
    if paso == "voz" and not estado.esta_aprobado("guion"):
        raise HTTPException(409, "aprueba el guion (paso 3) antes de generar "
                                 "la locución: así no se gastan tokens de "
                                 "ElevenLabs en un guion en revisión")
    params = estado.paso(paso).get("params") or registro.params_defecto_de(paso)
    trabajo = GESTOR.lanzar(pid, paso, _correr(proyecto, paso, params, unidades),
                            unidades=unidades)
    proyecto.bitacora("paso_lanzado", {"paso": paso, "trabajo": trabajo.id,
                                       "unidades": unidades})
    return GESTOR.estado(trabajo.id)


def _correr(proyecto: Proyecto, paso: str, params: dict, unidades: list[str]):
    """Cierre que ejecuta un paso y lo deja como versión nueva."""
    estado = Estado(proyecto)

    def funcion(trabajo):
        modulo = registro.modulo_de(paso)
        trabajo.avance(f"ejecutando {paso}")
        kwargs = {"solo_escenas": unidades} if paso == "assets" and unidades else {}
        datos = modulo.ejecutar(proyecto, params, trabajo, **kwargs)
        if unidades:
            datos = _fusionar_unidades(estado.datos_de(paso) or {}, datos, unidades)
        version = estado.completar(paso, params, datos,
                                   unidades=_contar_unidades(datos))
        proyecto.bitacora("paso_completado",
                          {"paso": paso, "version": version})
        with lock_de(proyecto.id):
            ficha = proyecto.leer()
            ficha["actualizado"] = ahora()
            proyecto.escribir(ficha)
        return {"paso": paso, "version": version,
                "unidades": _contar_unidades(datos)}

    return funcion


@router.get("/{pid}/pasos/{paso}/versiones", dependencies=[_SESION])
def versiones(pid: str, paso: str) -> list[dict]:
    estado = Estado(_proyecto_o_404(pid))
    paso = _paso_o_404(paso)
    return estado.versiones_de(paso)


@router.post("/{pid}/pasos/{paso}/revertir", dependencies=_MUTAR)
def revertir(pid: str, paso: str, cuerpo: dict) -> dict:
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    try:
        version = int(cuerpo.get("version", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "versión inválida") from None
    estado = Estado(proyecto)
    try:
        manifiesto = estado.revertir(paso, version)
    except RuntimeError as fallo:
        raise HTTPException(404, str(fallo)) from None
    proyecto.bitacora("paso_revertido", {"paso": paso, "version": version})
    return {"paso": paso, "version": version,
            "estado": estado.estado_de(paso),
            "params": manifiesto.get("params", {})}


# ------------------------------------------------------------------ aprobacion
#: pasos con puerta manual antes de gastar aguas abajo (por ahora, el guion)
_APROBABLES = {"guion"}


@router.post("/{pid}/pasos/{paso}/aprobar", dependencies=_MUTAR)
def aprobar_paso(pid: str, paso: str) -> dict:
    """Aprueba la version actual del guion: abre la puerta de la voz.

    El flujo sano es generar/retocar el guion hasta que convence, APROBAR
    y solo entonces pagar la locucion. Editar o regenerar el guion deja el
    acta sin efecto (hay que volver a aprobar); revertir tambien.
    """
    proyecto = _proyecto_o_404(pid)
    paso = _paso_o_404(paso)
    if paso not in _APROBABLES:
        raise HTTPException(400, "ese paso no se aprueba a mano")
    estado = Estado(proyecto)
    try:
        acta = estado.aprobar(paso)
    except RuntimeError as fallo:
        raise HTTPException(400, str(fallo)) from None
    proyecto.bitacora("paso_aprobado", {"paso": paso, "version": acta["version"]})
    return {"paso": paso, "aprobado": True, "version": acta["version"]}


# ------------------------------------------------------------------ unidades

#: (paso, consumidor directo de la unidad, campo de datos)
_CONSUMIDORES = {"guion": ["voz", "assets"], "voz": ["revision_audio"],
                 "assets": ["callouts"]}


def _correr_unidad(proyecto: Proyecto, paso: str, unidad: str,
                   funcion_unidad, paso_params: dict):
    """Cierre común: corrige UNA unidad, la aplica como versión y marca
    aguas abajo SOLO esa unidad (la cascada marca, la persona acciona)."""
    estado = Estado(proyecto)

    def funcion(trabajo):
        trabajo.avance(f"corrigiendo {paso}/{unidad}")
        ficha = funcion_unidad(trabajo)
        datos = estado.datos_de(paso) or {}
        for campo, clave in _CAMPOS_UNIDADES.items():
            if isinstance(datos.get(campo), list):
                datos[campo] = [ficha if (isinstance(u, dict)
                                          and str(u.get(clave, "")) == unidad)
                                else u for u in datos[campo]]
        version = estado.completar(paso, paso_params, datos,
                                   unidades=_contar_unidades(datos))
        for consumidor in _CONSUMIDORES.get(paso, []):
            estado.marcar_obsoleto(consumidor, [unidad])
        proyecto.bitacora("unidad_corregida",
                          {"paso": paso, "unidad": unidad, "version": version})
        return {"paso": paso, "unidad": unidad, "version": version, "ficha": ficha}

    return funcion


@router.post("/{pid}/guion/escenas/{escena}/reescribir",
             status_code=202, dependencies=_MUTAR)
def reescribir_escena(pid: str, escena: str, cuerpo: dict) -> dict:
    """Corrige UNA escena del guion con una orden en lenguaje natural."""
    proyecto = _proyecto_o_404(pid)
    orden = str(cuerpo.get("orden", "")).strip()
    if not orden:
        raise HTTPException(400, "falta la orden de corrección")
    params = Estado(proyecto).paso("guion").get("params", {})

    def unidad(trabajo):
        return p3_guion.reescribir_escena(proyecto, escena, orden, trabajo)

    trabajo = GESTOR.lanzar(pid, "guion",
                            _correr_unidad(proyecto, "guion", escena,
                                           unidad, params),
                            unidades=[escena])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/voz/escenas/{escena}/regrabar",
             status_code=202, dependencies=_MUTAR)
def regrabar_escena(pid: str, escena: str) -> dict:
    """Regraba el audio de UNA escena con los params de voz guardados."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("voz").get("params", {})

    def unidad(trabajo):
        return p4_voz.regrabar_escena(proyecto, escena, params)

    trabajo = GESTOR.lanzar(pid, "voz",
                            _correr_unidad(proyecto, "voz", escena,
                                           unidad, params),
                            unidades=[escena])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/assets/planos/{escena}/regenerar",
             status_code=202, dependencies=_MUTAR)
def regenerar_plano(pid: str, escena: str) -> dict:
    """Regenera la imagen de UN plano (cuesta dinero: una imagen)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})

    def unidad(trabajo):
        return p6_assets.regenerar_plano(proyecto, escena, params)

    trabajo = GESTOR.lanzar(pid, "assets",
                            _correr_unidad(proyecto, "assets", escena,
                                           unidad, params),
                            unidades=[escena])
    return GESTOR.estado(trabajo.id)


# ------------------------------------------------------- coste y bitácora

@router.get("/{pid}/coste", dependencies=[_SESION])
def coste(pid: str) -> dict:
    proyecto = _proyecto_o_404(pid)
    return de_proyecto(proyecto.raiz)


@router.get("/{pid}/bitacora", dependencies=[_SESION])
def bitacora(pid: str, limite: int = 200) -> list[dict]:
    proyecto = _proyecto_o_404(pid)
    entradas = leer_jsonl(proyecto.fichero_bitacora)
    return entradas[-max(1, min(limite, 1000)):]
