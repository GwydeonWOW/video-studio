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

import json
import re
import shutil
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import seguridad
from ..config import AJUSTES
from ..nucleo import capturas
from ..nucleo import estilo
from ..nucleo import coste as nucleo_coste
from ..nucleo import grafismo
from ..nucleo.coste import de_proyecto
from ..nucleo.estado import GRAFO, Estado, descendientes_de
from ..nucleo import recetas
from ..nucleo.proyecto import (Proyecto, ahora, escribir_json, id_valido,
                               leer_json, leer_jsonl, lock_de,
                               ruta_contenida)
from ..nucleo.trabajos import TrabajoCancelado
from ..pasos import (cartelas, catalogo_visual, comun, conservar, cta,
                     direccion, encuadres, guia_estilo, marcas_tts, moodboard,
                     p2_brief, p3_guion, p4_voz, p5_revision_audio, p6_assets,
                     redactor, registro, repaso, sonido, transiciones)
from .rutas_trabajos import CABECERAS_SSE, GESTOR, _sse

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
    """Cuenta UNIDADES, no filas: una escena cortada en planos son
    varias filas de `planos` pero UNA unidad de corrección (su escena)."""
    if not isinstance(datos, dict):
        return 0
    for campo, clave in _CAMPOS_UNIDADES.items():
        if isinstance(datos.get(campo), list):
            return len({str(u.get(clave, "")) for u in datos[campo]
                        if isinstance(u, dict)})
    return 0


def _sustituir_unidad(datos: dict, unidad: str, ficha) -> None:
    """Cambia las filas de UNA unidad por lo que trajo la corrección.

    `ficha` es un dict (una escena del guion, una voz...) o la LISTA de
    planos de una escena (p6): el bloque entra donde estaba la PRIMERA
    fila vieja, para no desordenar el montaje.
    """
    for campo, clave in _CAMPOS_UNIDADES.items():
        viejos = datos.get(campo)
        if not isinstance(viejos, list):
            continue
        nuevas = ficha if isinstance(ficha, list) else [ficha]
        posicion = next((i for i, u in enumerate(viejos)
                         if isinstance(u, dict)
                         and str(u.get(clave, "")) == unidad), None)
        resto = [u for u in viejos
                 if not (isinstance(u, dict)
                         and str(u.get(clave, "")) == unidad)]
        if posicion is None:
            resto.extend(nuevas)        # unidad nueva: al final
        else:
            resto[posicion:posicion] = nuevas
        datos[campo] = resto


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
        # una unidad puede traer VARIAS filas (una escena, varios
        # planos): agrupar por unidad y meter cada bloque donde estaba
        # su primera fila vieja
        traidos: dict[str, list] = {}
        for u in recientes:
            if isinstance(u, dict):
                traidos.setdefault(str(u.get(clave, "")), []).append(u)
        lista = []
        gastadas: set[str] = set()
        for unidad in viejos:
            llave = str(unidad.get(clave, "")) if isinstance(unidad, dict) else ""
            if llave in cambios:
                if llave in gastadas:
                    continue        # fila hermana: su bloque ya entró antes
                gastadas.add(llave)
                lista.extend(traidos.pop(llave, [unidad]))
            else:
                lista.append(unidad)
        for bloque in traidos.values():  # unidades nuevas que no existian
            lista.extend(bloque)
        mezcla[campo] = lista
    # campos escalares frescos (calidad, estado...) mandan
    for clave, valor in nuevo.items():
        if clave not in _CAMPOS_UNIDADES:
            mezcla[clave] = valor
    # PERO la duración total de una lista de escenas no es un escalar
    # cualquiera: una corrida parcial (regrabar UNA escena) trae la suma
    # de sólo las suyas, y dejarla pasar acortaría el vídeo
    if isinstance(mezcla.get("escenas"), list):
        con_duracion = [u for u in mezcla["escenas"]
                        if isinstance(u, dict) and "duracion" in u]
        if con_duracion:
            mezcla["duracion"] = round(
                sum(float(u.get("duracion") or 0.0) for u in con_duracion), 3)
    return mezcla


def _ficha_proyecto(proyecto: Proyecto) -> dict:
    datos = proyecto.leer()
    estado = Estado(proyecto)
    return {"id": proyecto.id, "nombre": datos.get("nombre", proyecto.id),
            "canal": datos.get("canal", ""), "idioma": datos.get("idioma", "es"),
            "creado": datos.get("creado"), "actualizado": datos.get("actualizado"),
            "pasos": estado.resumen(),
            "coste": de_proyecto(proyecto.raiz).get("coste", 0.0),
            "presupuesto": datos.get("presupuesto"),
            "activo": GESTOR.activo_de(proyecto.id)}


# ------------------------------------------------------------------ colección

@router.get("", dependencies=[_SESION])
def listar() -> list[dict]:
    # los TALLERES (proyectos donde el modo light genera un preset de
    # canal) no son trabajo de nadie: son la trastienda. Se ocultan aquí
    # y no en Proyecto.listar porque la papelera y las estadísticas SÍ
    # tienen que verlo todo.
    return [_ficha_proyecto(p)
            for p in Proyecto.listar(AJUSTES.carpeta_proyectos)
            if not p.leer().get("taller")]


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
    params_por_paso = {paso: registro.params_defecto_de(paso)
                       for paso in GRAFO}
    # el estilo del canal (si ya está definido) se siembra aquí también:
    # COPIA de valores sobre los defectos, nunca una referencia
    estilo_canal = estilo.leer(AJUSTES.datos)
    if estilo_canal["definido"]:
        estilo.aplicar_a_params(params_por_paso, estilo_canal)
        # y el kit visual con él: el look del canal, copiado a lo suyo
        estilo.sembrar_kit(AJUSTES.datos, proyecto)
    # EL PORTE del vídeo (horizontal | vertical) se decide al crear,
    # junto al idioma: entra en la firma de las imágenes y del render.
    # Solo si quien crea lo trae — un proyecto que no lo trajo (los de
    # antes del mando) sigue sin la tecla y cae en horizontal solo.
    if cuerpo.get("formato"):
        params_por_paso["brief"]["formato"] = comun.normalizar_formato(
            cuerpo.get("formato"))
    for paso in GRAFO:
        estado.guardar_params(paso, params_por_paso[paso])
    proyecto.bitacora("proyecto_creado", {"nombre": nombre})
    return _ficha_proyecto(proyecto)


# ------------------------------------------------------------------ papelera
# OJO al orden: estas rutas van ANTES que /{pid} para que "papelera" no se
# trague el parametro de ruta.

def _camino_papelera(carpeta: str):
    """Resuelve una carpeta de la papelera RECHAZANDO nombres que salgan
    de ella (`..`, rutas absolutas...): un borrado definitivo jamás puede
    tocar nada que no esté dentro de la papelera."""
    papelera = (AJUSTES.datos / "papelera").resolve()
    origen = (papelera / carpeta).resolve()
    if origen.parent != papelera:
        raise HTTPException(400, "nombre de carpeta no válido")
    return origen


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
    origen = _camino_papelera(carpeta)
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
    origen = _camino_papelera(carpeta)
    if not origen.is_dir():
        raise HTTPException(404, "no está en la papelera")
    shutil.rmtree(origen)


@router.delete("/papelera", status_code=204, dependencies=_MUTAR)
def vaciar_papelera():
    """Vacia la papelera entera. Tampoco tiene vuelta atras."""
    papelera = AJUSTES.datos / "papelera"
    if not papelera.is_dir():
        return
    for carpeta in list(papelera.iterdir()):
        if carpeta.is_dir():
            shutil.rmtree(carpeta)


@router.get("/papelera/{carpeta}", dependencies=[_SESION])
def dentro_de_papelera(carpeta: str) -> dict:
    """Qué hay dentro de un proyecto apartado, para poder decir qué se pierde."""
    origen = _camino_papelera(carpeta)
    if not origen.is_dir():
        raise HTTPException(404, "no está en la papelera")
    ficha = leer_json(origen / "proyecto.json", {}) or {}
    peso = 0
    ficheros = 0
    por_carpeta: dict[str, dict] = {}
    videos: list[dict] = []
    for ruta in origen.rglob("*"):
        if not ruta.is_file():
            continue
        ficheros += 1
        tam = ruta.stat().st_size
        peso += tam
        relativa = ruta.relative_to(origen)
        grupo = (relativa.parts[0] if len(relativa.parts) > 1 else ".")
        g = por_carpeta.setdefault(grupo, {"ficheros": 0, "peso": 0,
                                           "nombres": []})
        g["ficheros"] += 1
        g["peso"] += tam
        if len(g["nombres"]) < 100:
            g["nombres"].append(relativa.name)
        if ruta.suffix.lower() == ".mp4":
            videos.append({"nombre": str(relativa), "peso": tam})
    return {"carpeta": carpeta, "id": ficha.get("id", carpeta),
            "nombre": ficha.get("nombre", carpeta),
            "ficheros": ficheros, "peso": peso,
            "por_carpeta": por_carpeta, "videos": videos}


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


@router.post("/{pid}/aplicar-estilo", dependencies=_MUTAR)
def aplicar_estilo(pid: str) -> dict:
    """Reaplica el estilo del canal a los params de un proyecto existente.

    Copia los VALORES sobre los params guardados (regla del original: sin
    referencias, para que cambiar el estilo no rompa vídeos terminados).
    Los pasos tocados quedan obsoletos a la vista; quien decide
    regenerar —y pagar— sigue siendo la persona.
    """
    proyecto = _proyecto_o_404(pid)
    if GESTOR.activo_de(pid):
        raise HTTPException(409, "hay un trabajo en marcha en ese proyecto")
    estilo_canal = estilo.leer(AJUSTES.datos)
    if not estilo_canal["definido"]:
        raise HTTPException(400, "define primero el estilo del canal "
                                 "(pestaña Estilo)")
    estado = Estado(proyecto)
    tocados: list[str] = []
    with lock_de(pid):
        params_por_paso = {paso: dict(estado.paso(paso).get("params") or {})
                           for paso in estilo.PASOS_ESTILADOS}
        estilo.aplicar_a_params(params_por_paso, estilo_canal)
        for paso, params in params_por_paso.items():
            if params != (estado.paso(paso).get("params") or {}):
                estado.guardar_params(paso, params)
                tocados.append(paso)
        sembro_kit = estilo.sembrar_kit(AJUSTES.datos, proyecto)
        ficha = proyecto.leer()
        ficha["actualizado"] = ahora()
        proyecto.escribir(ficha)
    proyecto.bitacora("estilo_aplicado", {"pasos": tocados,
                                          "kit": sembro_kit})
    # la cascada que VERIA la persona al regenerar: pasos tocados con
    # material e hijos con material (igual que guardar_params)
    afectados = set(tocados)
    for paso in tocados:
        afectados.update(descendientes_de(paso))
    obsoletos = sorted(p for p in afectados if estado.estado_de(p) != "vacio")
    return {"pasos": tocados, "obsoletos_al_regenerar": obsoletos,
            "estilo": estilo_canal}


# ------------------------------------------------------------------ recetas
# La tubería de una tirada: lo que en pantallas son muchos botones en el
# orden correcto, aquí es una lista de tareas con sus dependencias. La
# TABLA vive en nucleo/recetas.py; aquí vive el código, que reutiliza el
# MISMO camino que el botón de cada paso (`_correr`): versión nueva,
# bitácora y firma. Una receta no esconde nada: adelanta trabajo.

@router.get("/recetas", dependencies=[_SESION])
def tablero_recetas() -> dict:
    """La tabla de tareas (para pintar la pantalla sin cargar nada más)."""
    return {"pestañas": recetas.PESTANAS, "tareas": recetas.TAREAS}


def _correr_receta(proyecto: Proyecto, tareas: list[str], modo: str,
                   trabajo) -> dict:
    """Corre una lista de tareas de una tirada. -> {hechos, saltados, paro}

    En modo 'pendiente' se salta lo que ya está hecho y al día. La receta
    se PARA (sin fallo) ante la puerta del guion: grabar la voz sin
    aprobación es gastar ElevenLabs en un guion que sigue en revisión.
    """
    hechos, saltados, paro = [], [], None
    for tid in tareas:
        tarea = recetas.TAREAS_POR_ID[tid]
        paso = tarea["paso"]
        estado = Estado(proyecto)
        trabajo.comprobar_cancelacion()
        if modo == "pendiente" and estado.estado_de(paso) == "ok":
            trabajo.avance(f"{paso}: ya está al día, se salta")
            saltados.append(paso)
            continue
        if paso == "voz" and not estado.esta_aprobado("guion"):
            trabajo.avance("parada: aprueba el guion antes de grabar la voz")
            paro = "guion_sin_aprobar"
            break
        trabajo.avance(f"— {tarea['nombre']}")
        params = estado.paso(paso).get("params") or \
            registro.params_defecto_de(paso)
        _correr(proyecto, paso, params, [])(trabajo)
        hechos.append(paso)
    return {"tareas": tareas, "modo": modo, "hechos": hechos,
            "saltados": saltados, "paro": paro}


@router.get("/{pid}/receta", dependencies=[_SESION])
def ficha_receta(pid: str) -> dict:
    """El tablero de la receta: cada tarea con su estado real.

    Cada pestaña trae también la receta con la que correría AHORA
    mismo (la puesta por defecto o la de fábrica) y qué tareas de esa
    receta van puestas: es lo que la pantalla enseña al abrir el
    diálogo, antes de elegir nada.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    pestañas = {}
    for clave, titulo in recetas.PESTANAS.items():
        receta = recetas.resolver(clave)
        tareas = []
        for t in recetas.TAREAS:
            if t["pestana"] != clave:
                continue
            ficha = estado.paso(t["paso"])
            tareas.append({**t, "estado": estado.estado_de(t["paso"]),
                           "version": ficha.get("version", 0),
                           "aprobado": bool(ficha.get("aprobado")),
                           "puesta": bool(receta["tareas"].get(t["id"],
                                                               True))})
        pestañas[clave] = {"nombre": titulo, "tareas": tareas,
                           "receta": {"id": str(receta["id"]),
                                      "nombre": receta["nombre"]}}
    return {"pestañas": pestañas, "activo": GESTOR.activo_de(pid)}


@router.post("/{pid}/receta/{pestana}", status_code=202, dependencies=_MUTAR)
def correr_receta(pid: str, pestana: str, cuerpo: dict | None = None) -> dict:
    """Lanza la receta de UNA pestaña como trabajo en segundo plano.

    El cuerpo puede recortarla: `receta` (una guardada del canal),
    `tareas` ({id: true|false}) y `modo`. Quien lanza manda sobre la
    guardada, la guardada sobre la puesta por defecto — y lo no
    opcional va siempre (todo eso lo decide `resolver`). Pantalla y
    servidor dicen lo mismo porque ambos preguntan a `puestas_de`.
    """
    proyecto = _proyecto_o_404(pid)
    if pestana not in recetas.PESTANAS:
        raise HTTPException(404, f"no hay pestaña {pestana}")
    cuerpo = cuerpo or {}
    try:
        modo = recetas.validar_modo(cuerpo.get("modo"))
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    tareas_pedidas = cuerpo.get("tareas")
    if tareas_pedidas is not None and not isinstance(tareas_pedidas, dict):
        raise HTTPException(400, "las tareas van como {id_de_tarea: true|false}")
    try:
        receta = recetas.resolver(pestana, cuerpo.get("receta"),
                                  tareas_pedidas)
    except recetas.ErrorReceta as fallo:
        raise HTTPException(400, str(fallo)) from None
    if pestana in ("voz", "montaje") and GESTOR.activo_de(pid):
        raise HTTPException(409, "ya hay un trabajo en marcha en este proyecto")
    tareas = recetas.puestas_de(pestana, receta)
    lanzado = GESTOR.lanzar(pid, "receta",
                            lambda t: _correr_receta(proyecto, tareas,
                                                     modo, t))
    proyecto.bitacora("receta_lanzada", {"pestaña": pestana, "modo": modo,
                                         "receta": receta["nombre"],
                                         "trabajo": lanzado.id})
    return GESTOR.estado(lanzado.id)


@router.post("/tanda", status_code=202, dependencies=_MUTAR)
def lanzar_tanda(cuerpo: dict | None = None) -> dict:
    """Receta COMPLETA sobre VARIOS vídeos de una vez (la galería).

    Un solo trabajo que los recorre en orden. El que falla no tumba la
    tanda: se anota y se sigue con el siguiente.
    """
    cuerpo = cuerpo or {}
    ids = [str(i) for i in cuerpo.get("ids") or []]
    if not ids:
        raise HTTPException(400, "la tanda necesita ids de proyectos")
    try:
        modo = recetas.validar_modo(cuerpo.get("modo"))
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    proyectos = {pid: _proyecto_o_404(pid) for pid in ids}
    ocupados = [pid for pid in ids if GESTOR.activo_de(pid)]
    if ocupados:
        raise HTTPException(409, "hay trabajos en marcha en: "
                                 + ", ".join(ocupados))

    def funcion(trabajo):
        resultados = []
        for pid, proyecto in proyectos.items():
            trabajo.comprobar_cancelacion()
            trabajo.avance(f"=== {proyecto.leer().get('nombre', pid)} ===")
            try:
                ficha = _correr_receta(proyecto, recetas.COMPLETA, modo,
                                       trabajo)
            except TrabajoCancelado:
                raise
            except Exception as fallo:                  # noqa: BLE001
                trabajo.avance(f"{pid} falló: {fallo} — se sigue")
                resultados.append({"proyecto": pid, "error": str(fallo)})
            else:
                resultados.append({"proyecto": pid, **ficha})
        return {"modo": modo, "proyectos": resultados}

    lanzado = GESTOR.lanzar("__tanda", "tanda", funcion)
    return GESTOR.estado(lanzado.id)


# ------------------------------------------------- generar: plan y cadena
#
# El porte de /api/proyectos/{pid}/generar del original: UN botón que
# recorre varias pestañas en UN trabajo (la cadena), con el plan delante
# — lo que se va a hacer, qué se salta y cuánto cuesta, dichos ANTES de
# pulsar. Una cifra en la pantalla y otra durante la generación son dos
# mentiras, y la segunda tarda diez minutos en descubrirse.

def _pestanas_pedidas(datos: dict) -> list[str]:
    """Las pestañas que pide el cuerpo, en el orden del pipeline.

    Acepta una `tanda` (las tandas del botón generar, `recetas.TANDAS`)
    o `pestanas` sueltas; la tanda manda. Levanta 400 con el catálogo si
    se pide algo que no existe — un nombre mal escrito no puede caer al
    vacío y pintar un botón que no hace nada.
    """
    tanda = str(datos.get("tanda") or "").strip()
    if tanda:
        ficha = recetas.TANDAS.get(tanda)
        if not ficha:
            raise HTTPException(400, "tanda desconocida: "
                                      + ", ".join(recetas.TANDAS))
        return list(ficha["pestanas"])
    crudo = datos.get("pestanas")
    if isinstance(crudo, str):
        pedidas = [p for p in crudo.split(",") if p.strip()]
    else:
        pedidas = [str(p) for p in (crudo or []) if str(p).strip()]
    desconocidas = [p for p in pedidas if p not in recetas.PESTANAS]
    if desconocidas:
        raise HTTPException(400, "pestañas desconocidas: "
                                 + ", ".join(desconocidas))
    # el ORDEN lo pone el pipeline, no quien llama: es la única manera
    # de que la cadena siempre llegue al render con todo lo de arriba
    return [p for p in recetas.PESTANAS if p in pedidas]


def _sin_de_la_tanda(datos: dict) -> set[str]:
    """Ids de tarea que la tanda deja fuera (mirar sin montar)."""
    tanda = str(datos.get("tanda") or "").strip()
    if not tanda:
        return set()
    ficha = recetas.TANDAS.get(tanda)
    return set(ficha["sin"]) if ficha else set()


def _con_origen(estado: Estado, pestanas: list[str]) -> list[str]:
    """La pestaña Origen delante si su paso no está hecho y la cadena
    pasa de ahí: sin material no hay guion, y el plan tiene que decirlo
    ANTES de que la cadena reviente en el brief."""
    if not pestanas or "origen" in pestanas:
        return pestanas
    if pestanas[0] in ("guion", "voz", "montaje") \
            and estado.estado_de("ingesta") != "ok":
        return ["origen"] + pestanas
    return pestanas


def _plan_de_generacion(proyecto: Proyecto, pestanas: list[str],
                        modo: str, sin: set[str] = ()) -> dict:
    """Qué se va a hacer, qué se salta y cuánto cuesta. NO lanza nada.

    Es lo que se lee al lado del botón antes de pulsarlo. El coste sale
    de los `estimar` de cada paso — los mismos números que dará el
    trabajo — y donde el paso no puede saberlo todavía (las imágenes
    antes del guion, los caracteres de voz), lo DICE en vez de
    inventarlo: una cifra inventada aquí es la primera de las dos
    mentiras. Aquí no hay segundos estimados porque el gestor no pinta
    barras por tiempo (sus barras son de texto); las estadísticas
    medidas son otro capítulo.
    """
    estado = Estado(proyecto)
    calidad = str((estado.paso("assets").get("params") or {}).get("calidad")
                  or "low")
    fases, pendientes = [], 0
    llamadas, imagenes, caracteres = 0, 0, 0
    sin_saber: list[str] = []
    for pestana in pestanas:
        filas = []
        for tarea in recetas.TAREAS:
            if tarea["pestana"] != pestana or tarea["id"] in sin:
                continue
            paso = tarea["paso"]
            al_dia = estado.estado_de(paso) == "ok"
            se_hace = (modo == "todo" or not al_dia)
            params = estado.paso(paso).get("params") \
                or registro.params_defecto_de(paso)
            previsto = registro.modulo_de(paso).estimar(params)
            filas.append({**tarea, "estado": estado.estado_de(paso),
                          "al_dia": al_dia, "se_hace": se_hace,
                          "previsto": previsto})
            if se_hace:
                pendientes += 1
                # los "?" no se suman ni se callan: se dicen en
                # coste.sin_saber («depende del guion que aún no existe»)
                for clave in ("llamadas_llm", "imagenes", "caracteres_voz"):
                    valor = previsto.get(clave)
                    if isinstance(valor, (int, float)) \
                            and not isinstance(valor, bool):
                        valor = int(valor)
                        if clave == "llamadas_llm":
                            llamadas += valor
                        elif clave == "imagenes":
                            imagenes += valor
                        else:
                            caracteres += valor
                    elif valor == "?":
                        sin_saber.append(paso)
        fases.append({"pestana": pestana, "nombre": recetas.PESTANAS[pestana],
                      "tareas": filas})
    # la puerta del guion, DICHA ANTES: la cadena para (sin fallo) antes
    # de grabar una locución que nadie ha aprobado — gastar ElevenLabs
    # en un guion en revisión. En el plan se ve; dentro del trabajo la
    # para `paro = guion_sin_aprobar`.
    impedimentos = []
    for fase in fases:
        for tarea in fase["tareas"]:
            if tarea["paso"] == "voz" and tarea["se_hace"] \
                    and not estado.esta_aprobado("guion"):
                impedimentos.append({
                    "tarea": "voz",
                    "que": "aprueba el guion (paso 3) antes de grabar "
                           "la locución: la cadena parará ahí"})
    usd_llm = round(llamadas * comun.COSTE_LLAMADA_LLAM["glm"], 4)
    usd_imagenes = round(
        imagenes * comun.COSTE_IMAGEN.get(calidad, comun.COSTE_IMAGEN["low"]), 4)
    usd_voz = round(caracteres / comun.CARACTERES_POR_DOLAR, 4) \
        if caracteres else 0.0
    return {
        "pestanas": pestanas, "modo": modo, "fases": fases,
        "pendientes": pendientes, "impedimentos": impedimentos,
        "coste": {"llamadas_llm": llamadas, "imagenes": imagenes,
                  "caracteres_voz": caracteres, "calidad": calidad,
                  "usd_llm": usd_llm, "usd_imagenes": usd_imagenes,
                  "usd_voz": usd_voz,
                  "usd_total": round(usd_llm + usd_imagenes + usd_voz, 4),
                  "sin_saber": sorted(set(sin_saber))},
        "tandas": recetas.TANDAS,
        "trabajo": GESTOR.activo_de(proyecto.id) or {},
    }


@router.get("/{pid}/generar", dependencies=[_SESION])
def plan_de_generar(pid: str, tanda: str = "", pestanas: str = "",
                    modo: str = "pendiente") -> dict:
    """Lo que va a hacer, qué se salta y cuánto cuesta. NO lanza nada."""
    proyecto = _proyecto_o_404(pid)
    try:
        modo = recetas.validar_modo(modo)
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    datos = {"tanda": tanda,
             "pestanas": [p for p in pestanas.split(",") if p.strip()]}
    if not datos["tanda"] and not datos["pestanas"]:
        # sin pedir nada: el plan de la cadena COMPLETA
        datos["pestanas"] = list(recetas.PESTANAS)
    elegidas = _con_origen(Estado(proyecto), _pestanas_pedidas(datos))
    return _plan_de_generacion(proyecto, elegidas, modo,
                               _sin_de_la_tanda(datos))


@router.post("/{pid}/generar", status_code=202, dependencies=_MUTAR)
def generar_video(pid: str, cuerpo: dict | None = None) -> dict:
    """Lanza la cadena: varias pestañas en UN solo trabajo.

    Los `params` que vengan se guardan ANTES de lanzar (el trabajo lee
    los guardados). El modo `pendiente` ES el retomar: se salta lo que
    ya está al día, que es la doctrina del original — el estado del
    proyecto es el estado del arranque, y cancelar corta sin perder lo
    pagado. Los impedimentos del plan NO bloquean el lanzamiento (la
    puerta del guion para el trabajo sin fallo, igual que la receta de
    una pestaña); lo que sí bloquea es no tener nada que hacer.
    """
    cuerpo = cuerpo or {}
    proyecto = _proyecto_o_404(pid)
    try:
        modo = recetas.validar_modo(cuerpo.get("modo"))
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    elegidas = _con_origen(Estado(proyecto), _pestanas_pedidas(cuerpo))
    sin = _sin_de_la_tanda(cuerpo)
    # PARAMS primero, dentro del cerrojo del proyecto: nadie lanza sobre
    # unos params que aún no están escritos
    params = cuerpo.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(400, "params tiene que ser {paso: {clave: valor}}")
    with lock_de(pid):
        estado = Estado(proyecto)
        for paso, valores in params.items():
            paso = _paso_o_404(paso)
            if not isinstance(valores, dict) or not valores:
                raise HTTPException(400, f"params de {paso} vacíos o malformados")
            if paso == "guion" and "cta" in valores:
                try:
                    cta.normalizar(valores["cta"], estricto=True)
                except ValueError as fallo:
                    raise HTTPException(400, str(fallo)) from None
            estado.guardar_params(paso, valores)
        if GESTOR.activo_de(pid):
            raise HTTPException(409, "hay un trabajo en marcha en ese proyecto")
        plan = _plan_de_generacion(proyecto, elegidas, modo, sin)
        if not plan["pendientes"]:
            raise HTTPException(400, "nada pendiente: todo lo pedido está "
                                     "al día (lanza con modo 'todo' para "
                                     "rehacerlo)")
        # la CADENA son todas las tareas pedidas, también las al día: el
        # trabajo las salta con su línea de avance, y quien mira el
        # registro ve la misma historia que contaba el plan
        cadena = [t["id"] for fase in plan["fases"] for t in fase["tareas"]]
        lanzado = GESTOR.lanzar(pid, "generar",
                                lambda t: _correr_receta(proyecto, cadena,
                                                         modo, t))
        proyecto.bitacora("generacion_lanzada",
                          {"pestañas": elegidas, "modo": modo, "tanda":
                           cuerpo.get("tanda") or "", "trabajo": lanzado.id})
    return {"trabajo": GESTOR.estado(lanzado.id), "pestanas": elegidas,
            "modo": modo, "plan": plan}


@router.get("/{pid}/previsualizacion", dependencies=[_SESION])
def leer_previsualizacion(pid: str) -> dict:
    """Las piezas para ver el vídeo sin montarlo. -> {escenas, ...}

    ESTE ENDPOINT NO MONTA NADA, y ahí está la gracia: devuelve las
    piezas sueltas —la imagen de cada escena, su audio y su rótulo con
    su ventana temporal— y quien las junta es el navegador, que además
    las junta mejor que el render para esto (el rótulo es texto de
    verdad y cambiar de escena es mover el currentTime de un <audio>).

    Escena a escena se oye la VOZ y nada más: lo que se juzga ahí es si
    la imagen cuadra con lo que se dice, y una cama de música es justo
    lo que tapa esa pregunta.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    voz = estado.datos_de("voz") or {}
    if not voz.get("escenas"):
        raise HTTPException(409, "todavía no hay locución: genera la voz "
                                 "antes de poder mirar el vídeo")
    assets = estado.datos_de("assets") or {}
    callouts = estado.datos_de("callouts") or {}
    guion = estado.datos_de("guion") or {}
    titulo_de = {e.get("id"): e.get("titulo", "")
                 for e in guion.get("escenas", [])}
    narracion_de = {e.get("id"): e.get("narracion", "")
                    for e in guion.get("escenas", [])}
    # los planos agrupados por escena, en ORDEN: una escena son ahora
    # VARIAS imágenes (el corte de `segmentar`), y quien mira tiene que
    # ver el ritmo de verdad — no una imagen hasta que acabe el audio
    planos_de: dict[str, list] = {}
    for p in assets.get("planos", []):
        if isinstance(p, dict) and p.get("escena"):
            planos_de.setdefault(str(p["escena"]), []).append(p)
    # los TROZOS de subtítulo van por plano y en reloj de plano (los dejó
    # p7): aquí no hay nada que recolocar
    subs_de = {str(f.get("id")): f.get("trozos") or []
               for f in callouts.get("subtitulos", [])
               if isinstance(f, dict)}
    escenas = []
    for escena in voz["escenas"]:
        sid = str(escena.get("id") or "")
        duracion_voz = float(escena.get("duracion") or 0.0)
        del_escena = planos_de.get(sid) or [{}]
        for plano in del_escena:
            # la ventana del plano DENTRO del audio de la escena; los
            # planos viejos (una imagen por escena) no la traen
            t_in = max(0.0, float(plano.get("t_in") or 0.0))
            t_out = (float(plano.get("t_out") or 0.0)
                     or (t_in + duracion_voz))
            imagen = plano.get("imagen")
            if not imagen or not proyecto.ruta(str(imagen)).exists():
                imagen = None
            palabras = [w for w in (escena.get("palabras") or [])
                        if isinstance(w, dict)
                        and float(w.get("fin") or 0) > t_in
                        and float(w.get("inicio") or 0) < t_out]
            escenas.append({
                "id": str(plano.get("id") or sid),
                "escena": sid,
                "titulo": titulo_de.get(sid, ""),
                "narracion": str(plano.get("narracion")
                                  or narracion_de.get(sid, "")),
                "imagen": imagen,
                "cartela": (plano.get("cartela") or {}).get("plantilla")
                if isinstance(plano.get("cartela"), dict) else None,
                "audio": escena.get("audio"),
                "t_in": round(t_in, 3),
                "t_out": round(min(t_out, duracion_voz or t_out), 3),
                "duracion": round(max(0.1, min(t_out, duracion_voz or t_out)
                                       - t_in), 3),
                "palabras": palabras,
                "trozos": subs_de.get(str(plano.get("id") or sid)) or [],
            })
    # el cuadro de la previsualización es el mismo del render: el porte
    # con el que se pidieron las imágenes, no el param cosmético
    ficha_formato = comun.ficha_formato(assets.get("formato")
                                        or p4_voz.formato_de_salida(proyecto))
    return {
        "escenas": escenas,
        "duracion": round(sum(e["duracion"] for e in escenas), 2),
        "resolucion": "x".join(str(n) for n in ficha_formato["salida"]),
        "con_subtitulos": bool(callouts.get("subtitulos")),
        "montado": proyecto.ruta("pasos/render/final.mp4").exists(),
        "idioma": str(proyecto.leer().get("idioma", "es")),
    }


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
    # la caja de las llamadas a la acción es anidada y tiene sus propias
    # reglas (qué momentos existen, cuánto puede ocupar lo que se pide):
    # se valida aquí porque un params.cta malforme guardado en silencio
    # es un guion que no sale y un aviso que no llega a nadie
    if paso == "guion" and "cta" in cuerpo:
        try:
            cta.normalizar(cuerpo["cta"], estricto=True)
        except ValueError as e:
            raise HTTPException(400, str(e))
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
        kwargs = ({"solo_escenas": unidades}
                  if paso in ("assets", "voz") and unidades else {})
        datos = modulo.ejecutar(proyecto, params, trabajo, **kwargs)
        if unidades:
            datos = _fusionar_unidades(estado.datos_de(paso) or {}, datos, unidades)
        version = estado.completar(paso, params, datos,
                                   unidades=_contar_unidades(datos),
                                   hechas=unidades or None)
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
        _sustituir_unidad(datos, unidad, ficha)
        version = estado.completar(paso, paso_params, datos,
                                   unidades=_contar_unidades(datos),
                                   hechas=[unidad])
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


def _correr_cadena(proyecto: Proyecto, escena: str, reescritura,
                   params_guion: dict, params_voz: dict):
    """Cierre del gesto encadenado de la revisión de audio.

    Reescribe la narración de UNA escena y regraba SU audio en el mismo
    trabajo: comentario → texto nuevo → voz nueva. Es la excepción
    honrada a «este módulo jamás encadena»: aquí la persona ya escuchó
    la toma y pidió el cambio — encadenarlo a mano sería dos gestos y
    una ventana para regrabar texto viejo.

    `reescritura(trabajo)` -> (ficha_guion | None, aviso). Con None (la
    reescritura falló o dejó el texto igual) NO se regraba: grabar el
    mismo texto otra vez es pagar ElevenLabs por una copia, y el aviso
    sube a la respuesta del trabajo.
    """
    estado = Estado(proyecto)

    def funcion(trabajo):
        reescrito, aviso = False, ""
        if reescritura is not None:
            trabajo.avance(f"reescribiendo {escena}")
            ficha, aviso = reescritura(trabajo)
            if ficha is not None:
                datos = estado.datos_de("guion") or {}
                _sustituir_unidad(datos, escena, ficha)
                estado.completar("guion", params_guion, datos,
                                 unidades=_contar_unidades(datos),
                                 hechas=[escena])
                # la unidad viaja ENTERA aguas abajo: la voz la regraba
                # esta cadena, las imágenes quedan marcadas para que las
                # accione quien las paga
                for consumidor in _CONSUMIDORES["guion"]:
                    if consumidor != "voz":
                        estado.marcar_obsoleto(consumidor, [escena])
                reescrito = True
        if not reescrito:
            return {"escena": escena, "reescrito": False, "regrabado": False,
                    "aviso": aviso or "la reescritura no cambió el texto"}
        trabajo.avance(f"regrabando el audio de {escena}")
        p4_voz.regrabar_escena(proyecto, escena, params_voz)  # escribe datos
        datos_voz = estado.datos_de("voz") or {}
        version = estado.completar("voz", params_voz, datos_voz,
                                   unidades=_contar_unidades(datos_voz),
                                   hechas=[escena])
        estado.marcar_obsoleto("revision_audio", [escena])
        proyecto.bitacora("revision_encadenada",
                          {"escena": escena, "version_voz": version})
        return {"escena": escena, "reescrito": True, "regrabado": True,
                "version_voz": version, "aviso": aviso}

    return funcion


@router.post("/{pid}/voz/escenas/{escena}/regrabar",
             status_code=202, dependencies=_MUTAR)
def regrabar_escena(pid: str, escena: str, cuerpo: dict | None = None) -> dict:
    """Regraba el audio de UNA escena con los params de voz guardados.

    Con {peticion} es un MICROCAMBIO encadenado: la petición reescribe la
    narración de esa escena y el audio se graba del texto nuevo, en un
    gesto — el que sale natural mientras se escucha la toma.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    peticion = str(cuerpo.get("peticion", "")).strip()
    estado = Estado(proyecto)
    params_voz = estado.paso("voz").get("params", {})
    if peticion:
        params_guion = estado.paso("guion").get("params", {})

        def reescritura(trabajo):
            return p3_guion.reescribir_escena(proyecto, escena, peticion,
                                              trabajo), ""

        funcion = _correr_cadena(proyecto, escena, reescritura,
                                 params_guion, params_voz)
    else:
        # LO ESCRITO A MANO MANDA también aquí (regla del original: el
        # cajón lo aplica quien graba). Si la edición a mano de la
        # pantalla dejó texto para esta escena en `params.unidades` y los
        # datos del guion aún no lo tienen, la cadena lo aplica ANTES de
        # regrabar: grabar sin más sería pagar la voz para que diga lo
        # que ya no está escrito.
        params_guion = estado.paso("guion").get("params", {})
        cajon = ((params_guion.get("unidades") or {}).get(escena) or {})
        manual = " ".join(str(cajon.get("texto") or "").split())
        actual = next(
            (e for e in (estado.datos_de("guion") or {}).get("escenas", [])
             if isinstance(e, dict) and str(e.get("id")) == escena), None)
        aplicar = bool(manual) and actual is not None and \
            " ".join(marcas_tts.limpiar(
                str(actual.get("narracion", ""))).split()) != manual
        if aplicar:

            def reescritura_manual(_trabajo):
                ficha = dict(actual)
                ficha["narracion"] = manual
                return ficha, ""

            funcion = _correr_cadena(proyecto, escena, reescritura_manual,
                                     params_guion, params_voz)
        else:
            def unidad(trabajo):
                return p4_voz.regrabar_escena(proyecto, escena, params_voz)

            funcion = _correr_unidad(proyecto, "voz", escena, unidad,
                                     params_voz)
    trabajo = GESTOR.lanzar(pid, "voz", funcion, unidades=[escena])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/revision_audio/escenas/{escena}/comentarios",
             status_code=202, dependencies=_MUTAR)
def comentar_escena(pid: str, escena: str, cuerpo: dict) -> dict:
    """Notas al estilo Google Docs sobre UNA escena: la cadena completa.

    Cada nota apunta a un trozo de la narración (los offsets del
    navegador solo se aceptan si el texto que hay ahí es el seleccionado).
    El paso reescribe la escena con TODAS sus notas y regraba el audio
    del texto nuevo en el mismo trabajo. Una nota que no se pudo aplicar
    vuelve como aviso con el texto intacto.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    comentarios = [c for c in cuerpo.get("comentarios") or []
                   if isinstance(c, dict)]
    if not comentarios:
        raise HTTPException(400, "falta la lista de comentarios")
    estado = Estado(proyecto)
    guion = estado.datos_de("guion")
    if not guion:
        raise HTTPException(409, "todavía no hay guion que comentar")
    if escena not in _unidades_del_paso(estado, "guion"):
        raise HTTPException(404, f"no hay ninguna escena {escena}")
    if not estado.datos_de("voz"):
        raise HTTPException(409, "todavía no hay voz que revisar")
    params_guion = estado.paso("guion").get("params", {})
    params_voz = estado.paso("voz").get("params", {})

    def reescritura(trabajo):
        actual = next((e for e in guion.get("escenas", [])
                       if isinstance(e, dict) and str(e.get("id")) == escena),
                      None)
        nuevo, aviso = p5_revision_audio.reescribir_bloque(
            actual, p5_revision_audio.agrupar_comentarios(
                comentarios).get(escena, []), proyecto_id=pid)
        if aviso or nuevo.strip() == str(actual.get("narracion",
                                                    "")).strip():
            return None, aviso or "la reescritura no cambió el texto"
        ficha = dict(actual)
        ficha["narracion"] = nuevo
        return ficha, ""

    trabajo = GESTOR.lanzar(pid, "revision_audio",
                            _correr_cadena(proyecto, escena, reescritura,
                                           params_guion, params_voz),
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


@router.post("/{pid}/escenas/{escena}/vale", dependencies=_MUTAR)
def aceptar_unidad(pid: str, escena: str) -> dict:
    """«Este dibujo me vale para lo que dice ahora». -> {ok}

    Es el descarte de la tarjeta de obsoleto, y no toca la imagen ni el
    plan: apunta la unidad como mirada y aceptada. Si la frase vuelve a
    cambiar aguas arriba, la tarjeta vuelve — que es justo lo que se
    quiere.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    if estado.estado_de("assets") == "vacio":
        raise HTTPException(409, "todavía no hay imágenes de este vídeo")
    datos = estado.datos_de("assets") or {}
    ids = {str(p.get("escena")) for p in datos.get("planos", [])
           if isinstance(p, dict)}
    if escena not in ids:
        raise HTTPException(404, f"no hay ningún plano {escena} en este vídeo")
    if not estado.aceptar_unidad("assets", escena):
        raise HTTPException(409, f"el plano {escena} no está marcado "
                                 "como obsoleto")
    proyecto.bitacora("plano_aceptado", {"unidad": escena, "paso": "assets"})
    return {"ok": True, "id": escena,
            "quedan": estado.unidades_obsoletas("assets")}


# ------------------------------------------------------------- feedback
#
# Feedback general o sobre una unidad. La nota se guarda en los params del
# paso ( cambia la firma: la etiqueta significa algo) y se rehace SOLO lo
# que apunta: la unidad si va dirigida, lo sucio si es del paso entero.

#: pasos que saben rehacer UNA unidad suelta
_CORRECCIONES_UNIDAD = {"guion", "voz", "assets"}


def _unidades_del_paso(estado: Estado, paso: str) -> set[str]:
    datos = estado.datos_de(paso) or {}
    for campo, clave in _CAMPOS_UNIDADES.items():
        if isinstance(datos.get(campo), list):
            return {str(u.get(clave, "")) for u in datos[campo]
                    if isinstance(u, dict)}
    return set()


def _corregir_unidad(proyecto: Proyecto, paso: str, unidad: str,
                     orden: str, params: dict):
    """Cierre de corrección por unidad, dispatchado por paso."""
    estado = Estado(proyecto)

    def funcion(trabajo):
        trabajo.avance(f"aplicando feedback a {paso}/{unidad}")
        if paso == "guion":
            ficha = p3_guion.reescribir_escena(proyecto, unidad, orden, trabajo)
        elif paso == "voz":
            ficha = p4_voz.regrabar_escena(proyecto, unidad, params)
        else:
            ficha = p6_assets.regenerar_plano(proyecto, unidad, params)
        datos = estado.datos_de(paso) or {}
        _sustituir_unidad(datos, unidad, ficha)
        version = estado.completar(paso, params, datos,
                                   unidades=_contar_unidades(datos),
                                   hechas=[unidad])
        for consumidor in _CONSUMIDORES.get(paso, []):
            estado.marcar_obsoleto(consumidor, [unidad])
        proyecto.bitacora("unidad_corregida",
                          {"paso": paso, "unidad": unidad,
                           "version": version, "motivo": "feedback"})
        return {"paso": paso, "unidad": unidad, "version": version,
                "ficha": ficha}

    return funcion


@router.post("/{pid}/feedback", status_code=202, dependencies=_MUTAR)
def enviar_feedback(pid: str, cuerpo: dict) -> dict:
    """Feedback general o sobre una unidad; rehace SOLO lo que apunta.

    La nota se guarda en los params del paso (su firma cambia: la
    etiqueta significa algo). Con unidad se rehace ESA unidad y nada más;
    sin unidad el feedback es del paso entero y se relanza tal cual.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    paso = _paso_o_404(str(cuerpo.get("paso", "")))
    texto = str(cuerpo.get("texto", "")).strip()
    if not texto:
        raise HTTPException(400, "falta el texto del feedback")
    unidad = str(cuerpo.get("unidad") or "").strip() or None
    estado = Estado(proyecto)
    if unidad and unidad not in _unidades_del_paso(estado, paso):
        raise HTTPException(404, f"no hay ninguna unidad {unidad} en {paso}")
    # la nota viaja a los params: general al cajón del paso, dirigida al
    # de la unidad (mismo cajón que la corrección a mano)
    if unidad:
        previo = ((estado.paso(paso).get("params") or {})
                  .get("unidades", {}).get(unidad, {}))
        historial = list(previo.get("feedback") or [])
    else:
        historial = list((estado.paso(paso).get("params") or {})
                         .get("feedback") or [])
    nota = {"id": f"F{len(historial) + 1:03d}", "fecha": ahora(),
            "texto": texto[:2000]}
    historial.append(nota)
    cambio_final = ({"unidades": {unidad: {"feedback": historial}}}
                    if unidad else {"feedback": historial})
    with lock_de(pid):
        estado.actualizar_params(paso, cambio_final)
        ficha = proyecto.leer()
        ficha["actualizado"] = ahora()
        proyecto.escribir(ficha)
    afectadas = estado.unidades_obsoletas(paso)
    aguas_abajo = {hijo: estado.unidades_obsoletas(hijo)
                   for hijo in descendientes_de(paso)}
    proyecto.bitacora("feedback", {"paso": paso, "unidad": unidad,
                                   "texto": texto[:200], "afectadas": afectadas})
    respuesta: dict = {"paso": paso, "unidad": unidad, "nota": nota,
                       "afectadas": afectadas, "aguas_abajo": aguas_abajo,
                       "estado": estado.estado_de(paso)}
    if cuerpo.get("ejecutar") is False:
        return respuesta
    # relanzar: la unidad si el paso sabe rehacerla suelta, el paso si no
    params = estado.paso(paso).get("params") or registro.params_defecto_de(paso)
    if unidad and paso in _CORRECCIONES_UNIDAD:
        funcion = _corregir_unidad(proyecto, paso, unidad, texto, params)
        trabajo = GESTOR.lanzar(pid, paso, funcion, unidades=[unidad])
    else:
        if paso == "voz" and not estado.esta_aprobado("guion"):
            raise HTTPException(409, "aprueba el guion (paso 3) antes de "
                                     "rehacer la locución: así no se gastan "
                                     "tokens de ElevenLabs en un guion en "
                                     "revisión")
        trabajo = GESTOR.lanzar(pid, paso,
                                _correr(proyecto, paso, params, []),
                                unidades=afectadas or [])
    respuesta["trabajo"] = GESTOR.estado(trabajo.id)
    return respuesta


@router.post("/{pid}/guion/bloques/reescribir",
             status_code=202, dependencies=_MUTAR)
def reescribir_bloques(pid: str, cuerpo: dict) -> dict:
    """Reescribe VARIAS escenas del guion con una frase. Sin tocar el audio."""
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    orden = str(cuerpo.get("orden", "")).strip()
    ids = [str(i) for i in cuerpo.get("ids") or [] if str(i).strip()]
    if not orden:
        raise HTTPException(400, "falta la orden de corrección")
    if not ids:
        raise HTTPException(400, "falta qué escenas reescribir (ids)")
    estado = Estado(proyecto)
    datos = estado.datos_de("guion")
    if not datos:
        raise HTTPException(409, "todavía no hay guion que reescribir")
    existentes = _unidades_del_paso(estado, "guion")
    desconocidas = [i for i in ids if i not in existentes]
    if desconocidas:
        raise HTTPException(404, "escenas inexistentes: "
                                 + ", ".join(desconocidas))
    params = estado.paso("guion").get("params", {})

    def funcion(trabajo):
        escenas = datos.get("escenas", [])
        for indice, eid in enumerate(ids, start=1):
            trabajo.comprobar_cancelacion()
            trabajo.avance(f"reescribiendo {indice}/{len(ids)}: {eid}")
            ficha = p3_guion.reescribir_escena(proyecto, eid, orden, trabajo)
            escenas = [ficha if (isinstance(e, dict)
                                 and str(e.get("id", "")) == eid) else e
                       for e in escenas]
        datos["escenas"] = escenas
        version = estado.completar("guion", params, datos,
                                   unidades=_contar_unidades(datos),
                                   hechas=ids)
        for consumidor in _CONSUMIDORES.get("guion", []):
            estado.marcar_obsoleto(consumidor, ids)
        proyecto.bitacora("bloques_reescritos",
                          {"unidades": ids, "version": version})
        return {"paso": "guion", "unidades": ids, "version": version}

    trabajo = GESTOR.lanzar(pid, "guion", funcion, unidades=ids)
    return GESTOR.estado(trabajo.id)


# ------------------------------------------------------------------ voz

@router.post("/{pid}/voz/describir", status_code=202, dependencies=_MUTAR)
def describir_voz(pid: str, cuerpo: dict) -> dict:
    """Describe cómo quieres que suene y devuelve voz y mandos propuestos.

    Es una PROPUESTA: no toca los params, los rellena la pantalla y
    decide quien mira. La voz se paga cada vez que se graba.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    encargo = str(cuerpo.get("encargo", "")).strip()
    if not encargo:
        raise HTTPException(400, "hace falta describir cómo quieres que "
                                 "suene la voz")
    idioma = str(cuerpo.get("idioma")
                 or proyecto.leer().get("idioma", "es")).strip().lower()

    def funcion(trabajo):
        trabajo.avance("mirando el catálogo de voces")
        propuesta = p4_voz.proponer_voz(proyecto, encargo, idioma, trabajo)
        trabajo.avance(f"propuesta: {propuesta['voz_nombre']}")
        proyecto.bitacora("voz_descrita",
                          {"encargo": encargo[:200],
                           "voz": propuesta["voz_nombre"],
                           "velocidad": propuesta["velocidad"]})
        return propuesta

    trabajo = GESTOR.lanzar(pid, "voz", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/voz/previsualizar", status_code=202, dependencies=_MUTAR)
def previsualizar_voz(pid: str, cuerpo: dict) -> dict:
    """Sintetiza unos segundos con estos mandos de voz para escucharlos."""
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    params = cuerpo.get("params") if isinstance(cuerpo.get("params"), dict) \
        else {k: v for k, v in cuerpo.items() if k != "segundos"}
    if not params:
        params = Estado(proyecto).paso("voz").get("params") \
            or p4_voz.params_defecto()
    try:
        segundos = float(cuerpo.get("segundos") or 20)
    except (TypeError, ValueError):
        raise HTTPException(400, "'segundos' debe ser un número") from None
    if not 1 <= segundos <= 120:
        raise HTTPException(400, "'segundos' debe estar entre 1 y 120")

    def funcion(trabajo):
        trabajo.avance(f"sintetizando {round(segundos)} s de cata")
        resultado = p4_voz.previsualizar(proyecto, params, segundos)
        trabajo.avance("cata lista: dale al play")
        proyecto.bitacora("voz_previsualizada",
                          {"segundos": segundos,
                           "voz": str(params.get("voz", ""))})
        return resultado

    trabajo = GESTOR.lanzar(pid, "voz", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


# ------------------------------------------------------- coste y bitácora

@router.get("/{pid}/coste", dependencies=[_SESION])
def coste(pid: str) -> dict:
    proyecto = _proyecto_o_404(pid)
    ficha = de_proyecto(proyecto.raiz)
    ficha["presupuesto"] = proyecto.leer().get("presupuesto")
    ficha["aviso"] = ficha["presupuesto"] is not None and \
        ficha["coste"] >= float(ficha["presupuesto"])
    return ficha


@router.get("/{pid}/coste/por-paso", dependencies=[_SESION])
def coste_por_paso(pid: str) -> dict:
    """Qué paso se ha llevado el dinero (contexto «paso[:unidad]»)."""
    proyecto = _proyecto_o_404(pid)
    return nucleo_coste.por_paso(nucleo_coste.eventos_de(proyecto.raiz))


@router.get("/{pid}/coste/eventos", dependencies=[_SESION])
def coste_eventos(pid: str, proveedor: str | None = None,
                  paso: str | None = None, unidad: str | None = None,
                  limite: int = 200) -> list[dict]:
    """Detalle de cada consumo, filtrable (pantalla del coste)."""
    proyecto = _proyecto_o_404(pid)
    salida = []
    for entrada in nucleo_coste.eventos_de(proyecto.raiz):
        ctx_paso, _, ctx_unidad = str(
            entrada.get("contexto", "")).partition(":")
        if proveedor and entrada.get("proveedor") != proveedor:
            continue
        if paso and ctx_paso != paso:
            continue
        if unidad and ctx_unidad != unidad:
            continue
        salida.append({**entrada, "paso": ctx_paso or None,
                       "unidad": ctx_unidad or None})
    return salida[-max(1, min(limite, 1000)):]


@router.put("/{pid}/coste/presupuesto", dependencies=_MUTAR)
def poner_presupuesto(pid: str, cuerpo: dict) -> dict:
    """Fija (o quita con null) el tope de gasto del proyecto."""
    proyecto = _proyecto_o_404(pid)
    bruto = (cuerpo or {}).get("presupuesto", None)
    if bruto is None:
        valor = None
    else:
        try:
            valor = round(float(bruto), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "el presupuesto debe ser un número "
                                     "(o null para quitarlo)") from None
        if valor != valor or not (0 <= valor <= 10000):
            # `valor != valor` caza NaN (pasa cualquier comparación < >)
            raise HTTPException(400, "el presupuesto debe estar entre 0 y "
                                     "10000 dólares")
    with lock_de(pid):
        datos = proyecto.leer()
        if valor is None:
            datos.pop("presupuesto", None)
        else:
            datos["presupuesto"] = valor
        proyecto.escribir(datos)
    proyecto.bitacora("presupuesto_cambiado", {"presupuesto": valor})
    return coste(pid)


@router.get("/{pid}/coste/flujo", dependencies=[_SESION])
async def coste_flujo(pid: str) -> StreamingResponse:
    """SSE: coste acumulado en vivo, para que la cabecera se mueva."""
    proyecto = _proyecto_o_404(pid)

    async def flujo():
        import asyncio
        ultimo: tuple | None = None
        for _ in range(1800):  # tope: 30 min por conexión
            ficha = de_proyecto(proyecto.raiz)
            presupuesto = proyecto.leer().get("presupuesto")
            actual = (ficha["coste"], presupuesto)
            if actual != ultimo:
                yield _sse("coste", {
                    "coste": ficha["coste"],
                    "operaciones": ficha["operaciones"],
                    "presupuesto": presupuesto,
                    "aviso": presupuesto is not None
                    and ficha["coste"] >= float(presupuesto)})
                ultimo = actual
            else:
                yield ": latido\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers=CABECERAS_SSE)


@router.get("/{pid}/bitacora", dependencies=[_SESION])
def bitacora(pid: str, limite: int = 200) -> list[dict]:
    proyecto = _proyecto_o_404(pid)
    entradas = leer_jsonl(proyecto.fichero_bitacora)
    return entradas[-max(1, min(limite, 1000)):]


@router.get("/{pid}/bitacora/llm", dependencies=[_SESION])
def bitacora_llm(pid: str, limite: int = 200) -> dict:
    """La bitácora como texto navegable (para copiar o pelear con un LLM)."""
    proyecto = _proyecto_o_404(pid)
    entradas = leer_jsonl(proyecto.fichero_bitacora)
    entradas = entradas[-max(1, min(limite, 1000)):]
    lineas = [f"# Bitácora de {proyecto.id}", ""]
    for entrada in entradas:
        detalle = {k: v for k, v in entrada.items() if k not in ("t", "evento")}
        extra = (" — " + json.dumps(detalle, ensure_ascii=False)) if detalle else ""
        lineas.append(f"- {entrada.get('t', '')} · {entrada.get('evento', '?')}"
                      f"{extra}")
    return {"texto": "\n".join(lineas), "eventos": len(entradas)}


# ---------------------------------------------------- grafismo por plano
#
# Dirección, redactor, cartelas y diseño de rótulos: decisiones que se
# guardan POR PLANO en `params.unidades` de assets (la firma del paso no
# se mueve: se ensucia SOLO el plano tocado) o en los params de callouts
# (el grafismo no cuesta imágenes). Proponer es un trabajo de cola: la
# pantalla sigue el sondeo del trabajo y lee su `resultado`.

def _planos_del_guion(proyecto: Proyecto) -> list[dict]:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion") or {}
    return [{"id": e.get("id", ""), "titulo": e.get("titulo", ""),
             "narracion": str(e.get("narracion", ""))}
            for e in guion.get("escenas", []) if isinstance(e, dict)]


def _paleta_actual(estado: Estado) -> dict:
    """La paleta vigente: estilo del canal + lo fijado a mano en callouts."""
    fijados = ((estado.paso("callouts").get("params", {})
                .get("paleta") or {}).get("fijados"))
    try:
        estilo_grafico = estilo.leer(AJUSTES.datos).get("estilo_grafico", "")
    except Exception:                                  # noqa: BLE001
        estilo_grafico = ""
    return grafismo.paleta_de(estilo_grafico, fijados)


def _diseno_sugerido() -> str:
    """Un set honesto para el estilo del canal (sugerencia, no mandato)."""
    try:
        texto = estilo.leer(AJUSTES.datos).get("estilo_grafico", "").lower()
    except Exception:                                  # noqa: BLE001
        texto = ""
    if any(p in texto for p in ("neon", "neón", "cyber", "futur")):
        return "pleno"
    if any(p in texto for p in ("elegan", "serif", "editorial")):
        return "sombra"
    return "pastilla"


def _ids_de_planos(proyecto: Proyecto) -> set[str]:
    return {p["id"] for p in _planos_del_guion(proyecto) if p["id"]}


# ------------------------------------------------------------- dirección

@router.get("/{pid}/direccion", dependencies=[_SESION])
def leer_direccion(pid: str) -> dict:
    """El plan de dirección guardado: qué se ve en cada plano."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    return {"plan": direccion.plan_de(params),
            "planos": _planos_del_guion(proyecto),
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.put("/{pid}/direccion", dependencies=_MUTAR)
def guardar_direccion(pid: str, cuerpo: dict) -> dict:
    """Escribe la dirección de planos concretos.

    Un texto vacío QUITA la dirección de ese plano (vuelve al prompt
    armado por capas). Se ensucian sólo los planos tocados.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    ids = _ids_de_planos(proyecto)
    plan = (cuerpo or {}).get("plan")
    if not isinstance(plan, dict) or not plan:
        raise HTTPException(400, "se esperaba {plan: {plano: direccion}}")
    unidades, tocados, avisos = {}, [], []
    for uid, texto in plan.items():
        sid = str(uid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        limpio, motivo = direccion.limpiar_linea(texto)
        if limpio is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        unidades[sid] = {"direccion": limpio}
        tocados.append(sid)
    if not tocados:
        raise HTTPException(400, "; ".join(avisos) or "nada que guardar")
    estado.actualizar_params("assets", {"unidades": unidades})
    estado.marcar_obsoleto("assets", tocados)
    proyecto.bitacora("direccion_guardada", {"planos": tocados})
    params = estado.paso("assets").get("params", {})
    return {"plan": direccion.plan_de(params), "tocados": tocados,
            "avisos": avisos,
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.post("/{pid}/direccion/proponer", status_code=202, dependencies=_MUTAR)
def proponer_direccion(pid: str) -> dict:
    """El agente propone qué se ve en cada plano (trabajo de cola)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})

    def funcion(trabajo):
        return direccion.proponer(proyecto, params, trabajo)

    trabajo = GESTOR.lanzar(pid, "direccion", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


# -------------------------------------------------------------- redactor

@router.get("/{pid}/redactor", dependencies=[_SESION])
def leer_redactor(pid: str) -> dict:
    """Los prompts escritos enteros, por plano."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    return {"plan": redactor.plan_de(params),
            "planos": _planos_del_guion(proyecto),
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.put("/{pid}/redactor", dependencies=_MUTAR)
def guardar_redactor(pid: str, cuerpo: dict) -> dict:
    """Escribe el prompt completo de planos concretos (MÁNDA sobre capas).

    Un texto vacío quita el prompt redactado de ese plano.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    ids = _ids_de_planos(proyecto)
    plan = (cuerpo or {}).get("plan")
    if not isinstance(plan, dict) or not plan:
        raise HTTPException(400, "se esperaba {plan: {plano: prompt}}")
    unidades, tocados, avisos = {}, [], []
    for uid, texto in plan.items():
        sid = str(uid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        limpio, motivo = redactor.limpiar_ficha(texto)
        if limpio is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        unidades[sid] = {"prompt": limpio}
        tocados.append(sid)
    if not tocados:
        raise HTTPException(400, "; ".join(avisos) or "nada que guardar")
    estado.actualizar_params("assets", {"unidades": unidades})
    estado.marcar_obsoleto("assets", tocados)
    proyecto.bitacora("redactor_guardado", {"planos": tocados})
    params = estado.paso("assets").get("params", {})
    return {"plan": redactor.plan_de(params), "tocados": tocados,
            "avisos": avisos,
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.post("/{pid}/redactor/proponer", status_code=202, dependencies=_MUTAR)
def proponer_redactor(pid: str) -> dict:
    """El agente redacta el prompt entero de cada plano (trabajo de cola)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})

    def funcion(trabajo):
        return redactor.proponer(proyecto, params, trabajo)

    trabajo = GESTOR.lanzar(pid, "redactor", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


# -------------------------------------------------------------- cartelas

@router.get("/{pid}/cartelas", dependencies=[_SESION])
def leer_cartelas(pid: str) -> dict:
    """El plan de cartelas guardado y el catálogo de plantillas."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    planos = _planos_del_guion(proyecto)
    permitidas = ((estado.paso("callouts").get("params", {}) or {})
                  .get("plantillas_cartela")) or []
    return {"plan": cartelas.plan_de(params),
            "plantillas": cartelas.catalogo_plantillas(
                paleta=_paleta_actual(estado)),
            "plantillas_activas": permitidas,
            "iconos": sorted(cartelas.ICONOS),
            "defecto": cartelas.PLANTILLA_POR_DEFECTO,
            "planos": planos,
            "max_cartelas": max(1, round(len(planos)
                                         * cartelas.FRACCION_MAXIMA)),
            "obsoletos": estado.unidades_obsoletas("assets")}


def _imagen_debajo(ruta) -> str:
    """La imagen del plano como trozo de SVG (data URI), para debajo de
    la carta en la vista: la cartela de hoy va SOBRE la imagen, y una
    vista sin ella enseñaría un fondo que el vídeo no lleva."""
    import base64                                                # noqa: PLC0415
    try:
        crudo = base64.b64encode(Path(ruta).read_bytes()).decode("ascii")
    except OSError:
        return ""
    return (f'<image x="0" y="0" width="{cartelas.TAMANO[0]}" '
            f'height="{cartelas.TAMANO[1]}" '
            f'href="data:image/png;base64,{crudo}" '
            f'preserveAspectRatio="xMidYMid slice"/>')


@router.get("/{pid}/cartelas/vista", dependencies=[_SESION])
def vista_cartela(pid: str, plano: str) -> Response:
    """La cartela de un plano como SVG: lo que dibuja el render.

    Si el paso 6 ya cortó, viaja con los tiempos de VERDAD (los que
    escribirá el render, dejados en `escritura`) y la imagen del plano
    debajo; si no, quieta y con el ritmo de muestra.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    sid = str(plano).strip().upper()
    ficha = cartelas.plan_de(params).get(sid)
    if not ficha:
        raise HTTPException(404, f"el plano {plano} no lleva cartela")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz") or {}
    duracion = next((float(v.get("duracion", 0) or 0)
                     for v in voz.get("escenas", [])
                     if v.get("id") == sid), 4.0)
    tiempos, debajo = None, ""
    assets = p2_brief.proyecto_leer_datos(proyecto, "assets") or {}
    plano_de = next((p for p in assets.get("planos", [])
                     if isinstance(p, dict) and p.get("cartela")
                     and str(p.get("escena")) == sid), None)
    if plano_de:
        escritura = plano_de.get("escritura") if isinstance(
            plano_de.get("escritura"), dict) else {}
        tiempos = escritura.get("tiempos") or None
        duracion = float(plano_de.get("duracion") or duracion or 4.0)
        if plano_de.get("imagen"):
            debajo = _imagen_debajo(proyecto.ruta(plano_de["imagen"]))
    svg = cartelas.svg_carta(ficha, paleta=_paleta_actual(estado),
                             duracion=duracion or 4.0, debajo=debajo,
                             tiempos=tiempos, animada=True)
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/{pid}/cartelas/plan", status_code=202, dependencies=_MUTAR)
def proponer_cartelas(pid: str) -> dict:
    """El agente decide qué tramos van mejor como cartela (trabajo de cola)."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    # LA ALLOWLIST vive con el grafismo, en los params de rótulos: limita
    # lo que el agente puede elegir sin ensuciar una sola imagen (regla
    # del original, que la pasaba explícita aparte del saco de assets).
    plantillas = ((estado.paso("callouts").get("params", {}) or {})
                  .get("plantillas_cartela"))

    def funcion(trabajo):
        return cartelas.proponer(proyecto, params, trabajo,
                                 plantillas=plantillas)

    trabajo = GESTOR.lanzar(pid, "cartelas", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.put("/{pid}/cartelas", dependencies=_MUTAR)
def guardar_cartelas(pid: str, cuerpo: dict) -> dict:
    """Fija (o quita) la cartela de planos concretos y qué plantillas
    se pueden usar.

    El plan va al bloque `unidades` de assets: POR UNIDAD, convertir
    S013 en cartela ensucia S013 y nada más. Y las plantillas permitidas
    van a los params de RÓTULOS, con el resto del grafismo: solo
    limitan lo que puede elegir el agente la próxima vez, así que no
    tienen por qué ensuciar una sola imagen.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    ids = _ids_de_planos(proyecto)
    datos = cuerpo or {}
    unidades, tocados, avisos, hecho = {}, [], [], []
    plan = datos.get("plan")
    if isinstance(plan, dict) and plan:
        for uid, ficha in plan.items():
            sid = str(uid).strip().upper()
            if sid not in ids:
                avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
                continue
            if ficha is None:  # quitar la cartela: el plano vuelve a pagar imagen
                unidades[sid] = {"cartela": None}
                tocados.append(sid)
                continue
            if not isinstance(ficha, dict):
                avisos.append(f"{sid}: no trae ficha, se ignora")
                continue
            plantilla = str(ficha.get("plantilla", ""))
            if plantilla not in cartelas.PLANTILLAS:
                raise HTTPException(
                    400, f"plantilla de cartela desconocida: {plantilla}. "
                    f"Las que hay son: {', '.join(cartelas.PLANTILLAS)}")
            valores, motivos = cartelas.validar(plantilla, ficha.get("datos"))
            if valores is None:
                avisos.append(f"{sid}: {'; '.join(motivos)}")
                continue
            avisos.extend(f"{sid}: {m}" for m in motivos)
            unidades[sid] = {"cartela": {
                "plantilla": plantilla,
                "datos": valores,
                "por_que": str(ficha.get("por_que", "")).strip()}}
            tocados.append(sid)
        if not tocados:
            raise HTTPException(400, "; ".join(avisos) or "nada que guardar")
        hecho.append("plan")
    if isinstance(datos.get("plantillas"), list):
        desconocidas = [t for t in datos["plantillas"]
                        if t not in cartelas.PLANTILLAS]
        if desconocidas:
            raise HTTPException(
                400, f"plantillas desconocidas: {', '.join(desconocidas)}. "
                f"Las que hay son: {', '.join(cartelas.PLANTILLAS)}")
        estado.actualizar_params(
            "callouts", {"plantillas_cartela": list(datos["plantillas"])})
        hecho.append("plantillas")
    if not hecho:
        raise HTTPException(400, "se esperaba {plan: ...} o {plantillas: [...]}")
    if tocados:
        estado.actualizar_params("assets", {"unidades": unidades})
        estado.marcar_obsoleto("assets", tocados)
        proyecto.bitacora("cartelas_guardadas", {"planos": tocados})
    params = estado.paso("assets").get("params", {})
    return {"plan": cartelas.plan_de(params), "tocados": tocados,
            "avisos": avisos, "guardado": hecho,
            "plantillas_activas": (estado.paso("callouts")
                                   .get("params", {}) or {}
                                   ).get("plantillas_cartela") or [],
            "obsoletos": estado.unidades_obsoletas("assets")}


# ------------------------------------------------------ diseño de rótulos

@router.get("/{pid}/callouts/diseno", dependencies=[_SESION])
def leer_diseno(pid: str) -> dict:
    """Sets de diseño, paleta y tamaño: UN grafismo para todo el vídeo."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("callouts").get("params", {})
    return {"sets": grafismo.SETS_DISENO,
            "elegido": params.get("diseno", "pastilla"),
            "sugerido": _diseno_sugerido(),
            "paleta": _paleta_actual(estado),
            "fijados": (params.get("paleta") or {}).get("fijados") or {},
            "tamanos": grafismo.SUB_TAMANOS,
            "subtitulo_tam": params.get("subtitulo_tam", "normal"),
            "obsoleto": estado.estado_de("callouts") == "obsoleto"}


@router.put("/{pid}/callouts/plan", dependencies=_MUTAR)
def guardar_diseno(pid: str, cuerpo: dict) -> dict:
    """Cambia el grafismo: no cuesta imágenes, sólo rehacer capas y render."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    datos = cuerpo if isinstance(cuerpo, dict) else {}
    extra = {}
    diseno = str(datos.get("diseno", "")).strip()
    if diseno:
        if diseno not in grafismo.SETS_DISENO:
            raise HTTPException(400, "set desconocido; los que hay: "
                                     + ", ".join(grafismo.SETS_DISENO))
        extra["diseno"] = diseno
    tam = str(datos.get("subtitulo_tam", "")).strip()
    if tam:
        if tam not in grafismo.SUB_TAMANOS:
            raise HTTPException(400, "tamaño desconocido; los que hay: "
                                     + ", ".join(grafismo.SUB_TAMANOS))
        extra["subtitulo_tam"] = tam
    fijados_nuevos = ((datos.get("paleta") or {}).get("fijados"))
    if isinstance(fijados_nuevos, dict):
        actuales = ((estado.paso("callouts").get("params", {})
                     .get("paleta") or {}).get("fijados") or {})
        mezcla = dict(actuales)
        for papel, color in fijados_nuevos.items():
            limpio = str(color or "").strip()
            if papel not in grafismo.PALETA_DEFECTO:
                continue
            if limpio:
                mezcla[papel] = limpio
            else:
                mezcla.pop(papel, None)  # vacío quita el fijado manual
        extra["paleta"] = {"fijados": mezcla}
    if not extra:
        raise HTTPException(400, "nada que guardar")
    estado.actualizar_params("callouts", extra)
    proyecto.bitacora("diseno_cambiado", extra)
    return leer_diseno(pid)


@router.get("/{pid}/callouts/vista", dependencies=[_SESION])
def vista_callout(pid: str, plano: str, diseno: str | None = None,
                  tam: str | None = None, texto: str | None = None) -> Response:
    """Un trozo de subtítulo como SVG: lo que dibuja el render.

    Los query params opcionales son la VISTA PREVIA de lo que la pantalla
    está editando (aún sin guardar): sin ellos se enseña el primer trozo
    guardado del plano.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    datos = estado.datos_de("callouts") or {}
    params = estado.paso("callouts").get("params", {})
    sid = str(plano).strip().upper()
    fila = next((f for f in datos.get("subtitulos", [])
                 if str(f.get("id", "")).upper() == sid), None)
    trozo = (fila.get("trozos") or [{}])[0].get("texto", "") if fila else ""
    if not trozo and texto is None:
        raise HTTPException(404, f"el plano {plano} no lleva subtítulo")
    svg = grafismo.svg_subtitulo(
        texto if texto is not None else trozo,
        diseno or datos.get("diseno") or params.get("diseno", "pastilla"),
        _paleta_actual(estado),
        tam or datos.get("subtitulo_tam")
        or params.get("subtitulo_tam", "normal"),
        cap_linea=int(datos.get("cap_linea") or 38))
    return Response(content=svg, media_type="image/svg+xml")


# ===================================================================== #
# EL REPASO                                                             #
# ===================================================================== #
#
# Las notas se escriben MIRANDO el vídeo: ancladas al segundo, con el
# plano que estaba en pantalla deducido de los cortes con los que se
# montó ESE vídeo. Las notas viven en repaso.json (NO en params:
# comentar un vídeo no lo deja obsoleto) y se convierten en cambios —
# vocabulario cerrado, cada cambio con su coste — sólo al APLICAR.
# Ver pasos/repaso.py para las tres decisiones que lo gobiernan.

def _tiempos_de(proyecto: Proyecto) -> list[dict]:
    """Los cortes del vídeo ACTUAL: escena a escena, con sus instantes.

    Se arma con la voz (las duraciones reales) y el guion (lo que se
    dice): es contra lo que se ancla una nota y contra lo que se
    re-anclan las viejas.
    """
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion") or {}
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz") or {}
    narracion_de = {str(e.get("id")): str(e.get("narracion", ""))
                    for e in guion.get("escenas", []) if isinstance(e, dict)}
    cortes, t = [], 0.0
    for escena in voz.get("escenas", []):
        if not isinstance(escena, dict):
            continue
        sid = str(escena.get("id") or "")
        try:
            dur = float(escena.get("duracion") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        cortes.append({"id": sid, "t_in": round(t, 3),
                       "t_out": round(t + dur, 3),
                       "narracion": narracion_de.get(sid, "")})
        t += dur
    return cortes


def _planos_del_repaso(proyecto: Proyecto) -> dict:
    """{plano: {cartela, texto_rotulo}} — el contexto de cada nota.

    El texto que viaja es el de los SUBTÍTULOS (lo que de verdad se
    escribe en pantalla ahora), juntado por escena.
    """
    assets = p2_brief.proyecto_leer_datos(proyecto, "assets") or {}
    callouts = p2_brief.proyecto_leer_datos(proyecto, "callouts") or {}
    cartela_de = {str(p.get("escena")): p.get("cartela")
                  for p in assets.get("planos", []) if isinstance(p, dict)}
    texto_de: dict[str, str] = {}
    for fila in callouts.get("subtitulos", []):
        if not isinstance(fila, dict):
            continue
        trozos = " ".join(str(t.get("texto") or "")
                          for t in (fila.get("trozos") or [])
                          if isinstance(t, dict)).strip()
        if trozos:
            texto_de[str(fila.get("escena"))] = trozos
    return {sid: {"cartela": cartela_de.get(sid) or {},
                  "texto_rotulo": texto_de.get(sid, "")}
            for sid in set(cartela_de) | set(texto_de)}


def _ficha_repaso(proyecto: Proyecto) -> dict:
    """Todo lo que pinta la pantalla del repaso."""
    estado = Estado(proyecto)
    ficha = repaso.leer(proyecto)
    cortes = _tiempos_de(proyecto)
    notas = repaso.reanclar(ficha["notas"], cortes)
    montado = proyecto.ruta("pasos/render/final.mp4").exists()
    pipeline = " · ".join(f"{p}:{estado.estado_de(p)}"
                          for p in GRAFO if estado.estado_de(p) != "vacio")
    return {
        "notas": notas,
        "pendientes": sum(1 for n in notas if n.get("estado") != "aplicado"),
        "cortes": cortes,
        "duracion": round(sum(c["t_out"] - c["t_in"] for c in cortes), 2),
        "montado": montado,
        "video": (f"/a/{proyecto.id}/pasos/render/final.mp4"
                  if montado else None),
        "version_video": ficha.get("version_video"),
        "catalogo": repaso.catalogo(),
        "pipeline": pipeline or "todavía no hay nada generado",
        "activo": GESTOR.activo_de(proyecto.id),
    }


@router.get("/{pid}/repaso", dependencies=[_SESION])
def leer_repaso(pid: str) -> dict:
    return _ficha_repaso(_proyecto_o_404(pid))


@router.post("/{pid}/repaso", status_code=201, dependencies=_MUTAR)
def anadir_nota(pid: str, cuerpo: dict) -> dict:
    """Una nota nueva, anclada al segundo en que se escribió.

    El plano se deduce del instante contra los cortes del vídeo actual, y
    la nota se guarda con el ANCLA de lo que se estaba narrando: el
    seguro contra que los planos se renumeren al regenerar.
    """
    proyecto = _proyecto_o_404(pid)
    texto = str((cuerpo or {}).get("texto", "")).strip()
    if not texto:
        raise HTTPException(400, "una nota del repaso necesita texto")
    try:
        t = max(0.0, float((cuerpo or {}).get("t") or 0.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "'t' debe ser el segundo del vídeo") from None
    cortes = _tiempos_de(proyecto)
    sid = str((cuerpo or {}).get("plano") or "").strip() \
        or repaso.plano_en(cortes, t)
    ancla = next((c.get("narracion") for c in cortes if c.get("id") == sid), "")
    nota = repaso.anadir(proyecto, texto, t, plano=sid,
                         imagenes=(cuerpo or {}).get("imagenes") or (),
                         version_video=(cuerpo or {}).get("version_video"),
                         ancla=ancla)
    proyecto.bitacora("nota_anadida", {"id": nota["id"], "t": t,
                                       "plano": sid})
    return {"nota": nota, "plano": sid}


@router.put("/{pid}/repaso/{nid}", dependencies=_MUTAR)
def editar_nota(pid: str, nid: str, cuerpo: dict) -> dict:
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    try:
        nota = repaso.editar(proyecto, nid,
                             texto=cuerpo.get("texto"),
                             t=cuerpo.get("t"),
                             imagenes=cuerpo.get("imagenes"))
    except KeyError:
        raise HTTPException(404, f"no hay nota {nid}") from None
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    return {"nota": nota}


@router.delete("/{pid}/repaso/{nid}", status_code=204, dependencies=_MUTAR)
def borrar_nota(pid: str, nid: str):
    proyecto = _proyecto_o_404(pid)
    try:
        repaso.borrar(proyecto, nid)
    except KeyError:
        raise HTTPException(404, f"no hay nota {nid}") from None


@router.post("/{pid}/repaso/imagenes", status_code=201, dependencies=_MUTAR)
def subir_imagen_repaso(pid: str, cuerpo: dict) -> dict:
    """Una imagen de referencia para la nota (PNG, del portapapeles o no)."""
    proyecto = _proyecto_o_404(pid)
    try:
        datos_png = capturas._validar_png((cuerpo or {}).get("imagen"))
    except capturas.ErrorCaptura as fallo:
        raise HTTPException(400, str(fallo)) from None
    carpeta = repaso.carpeta_imagenes(proyecto, crear=True)
    numero, existentes = 1, {p.name for p in carpeta.glob("*.png")}
    while f"ref_{numero:03d}.png" in existentes:
        numero += 1
    nombre = f"ref_{numero:03d}.png"
    (carpeta / nombre).write_bytes(datos_png)
    return {"nombre": nombre, "bytes": len(datos_png),
            "url": f"/a/{proyecto.id}/repaso/{nombre}"}


@router.get("/{pid}/repaso/imagenes/{nombre}", dependencies=[_SESION])
def leer_imagen_repaso(pid: str, nombre: str) -> FileResponse:
    proyecto = _proyecto_o_404(pid)
    ruta = ruta_contenida(repaso.carpeta_imagenes(proyecto), nombre)
    if not ruta.is_file():
        raise HTTPException(404, "esa imagen no está en el repaso")
    return FileResponse(ruta, media_type="image/png")


# ------------------------------------------------------- aplicar el repaso

def _nota_feedback(texto: str, alcance: str, numero: int) -> dict:
    """La nota de feedback que viaja al cajón de la unidad (en INGLÉS al
    modelo de imagen, con la etiqueta de alcance delante)."""
    prefijo = ("LOCALIZED fix, keep the rest of the frame as is"
               if alcance == "retoque" else "Replace the subject")
    return {"id": f"C{numero:03d}", "fecha": ahora(), "origen": "repaso",
            "alcance": alcance,
            "texto": f"Correction: {prefijo}. {texto}"}


def _aplicar_cambios(proyecto: Proyecto, cambios: list[dict],
                     trabajo) -> dict:
    """Escribe cada cambio en SU cajón y MARCA lo que hay que rehacer.

    Nada de esto genera: los cajones quedan escritos, las unidades
    quedan sucias, y quien corre los pasos es `_correr_repaso` — con el
    coste ya anunciado por el resumen. Los cajones son los MISMOS que
    leen los pasos (regla del original: un cajón que nadie lee es una
    nota marcada como aplicada con el vídeo igual).
    """
    estado = Estado(proyecto)
    extras: dict[str, dict] = {}          # paso -> params que cambiarán
    unidades: dict[str, list[str]] = {}   # paso -> unidades tocadas
    escenas_reescritas: dict[str, str] = {}  # sid -> narración nueva

    def cajon_unidad(paso: str, sid: str, campo: str, valor):
        params = estado.paso(paso).get("params") or {}
        bloque = dict((params.get("unidades") or {}).get(sid) or {})
        bloque[campo] = valor
        extras.setdefault(paso, {}).setdefault("unidades", {})[sid] = bloque
        unidades.setdefault(paso, []).append(sid)

    for cambio in cambios:
        tipo = cambio.get("tipo")
        sid = str(cambio.get("plano") or "")
        if tipo == "feedback_plano":
            params = estado.paso("assets").get("params") or {}
            bloque = dict((params.get("unidades") or {}).get(sid) or {})
            historial = list(bloque.get("feedback") or [])
            historial.append(_nota_feedback(cambio["texto"],
                                            cambio.get("alcance", "sustituye"),
                                            len(historial) + 1))
            extras.setdefault("assets", {}).setdefault("unidades", {})[sid] = {
                **bloque, "feedback": historial}
            unidades.setdefault("assets", []).append(sid)
        elif tipo == "cartela_texto":
            params = estado.paso("assets").get("params") or {}
            previa = (params.get("unidades") or {}).get(sid) or {}
            cartela = dict(previa.get("cartela") or {})
            if not cartela.get("plantilla"):
                trabajo.avance(f"{sid}: no es cartela, su texto no se "
                               "puede cambiar — se ignora")
                continue
            valores, motivos = cartelas.validar(
                cartela.get("plantilla", ""),
                {**(cartela.get("datos") or {}), **cambio["campos_cartela"]})
            if valores is None:
                trabajo.avance(f"{sid}: {'; '.join(motivos)} — se ignora")
                continue
            cartela["datos"] = valores
            extras.setdefault("assets", {}).setdefault("unidades", {})[sid] = {
                **dict(previa), "cartela": cartela}
            unidades.setdefault("assets", []).append(sid)
        elif tipo == "quitar_cartela":
            cajon_unidad("assets", sid, "cartela", None)
        elif tipo == "subtitulo_tam":
            extras.setdefault("callouts", {})["subtitulo_tam"] = cambio["valor"]
        elif tipo == "grafismo":
            extras.setdefault("callouts", {})["diseno"] = cambio["valor"]
        elif tipo == "subtitulo_texto":
            cajon_unidad("callouts", sid, "subtitulo_texto", cambio["texto"])
        elif tipo == "escena_texto":
            cajon_unidad("guion", sid, "texto", cambio["texto"])
            escenas_reescritas[sid] = cambio["texto"]
            # la narración nueva arrastra SU plano (el prompt usa la frase)
            unidades.setdefault("assets", []).append(sid)
        elif tipo == "velocidad":
            extras.setdefault("voz", {})["velocidad"] = cambio["valor"]
            unidades["voz"] = None      # TODO el paso: la velocidad es global
        elif tipo == "transicion_duracion":
            extras.setdefault("render", {})["duracion_transicion"] = \
                cambio["valor"]
        elif tipo == "transiciones":
            validas = [t for t in cambio["lista"]
                       if t in transiciones.CATALOGO]
            extras.setdefault("render", {})["transiciones"] = \
                validas or list(transiciones.POR_DEFECTO)
        elif tipo == "musica_db":
            extras.setdefault("render", {})["musica_db"] = cambio["valor"]
        elif tipo == "efectos_db":
            extras.setdefault("render", {})["efectos_db"] = cambio["valor"]
        elif tipo in ("sin_musica", "otra_musica"):
            extras.setdefault("render", {})["musica"] = {}
        elif tipo == "sin_efectos":
            extras.setdefault("render", {})["efectos"] = {}
        elif tipo == "otros_efectos":
            # VUELVE A SURTIR: lo limpia y busca otros sonidos para los
            # mismos papeles. Sin claves se queda limpio y se dice.
            extras.setdefault("render", {})["efectos"] = {}
            try:
                nuevo = {papel: sonido.surtir(papel)
                         for papel in sonido.PAPELES}
                extras["render"]["efectos"] = nuevo
                trabajo.avance(f"efectos re-surtidos: "
                               f"{sum(len(v) for v in nuevo.values())}")
            except RuntimeError as fallo:
                trabajo.avance(f"no se pudieron re-surtir: {str(fallo)[:160]}")

    with lock_de(proyecto.id):
        for paso, extra in extras.items():
            estado.actualizar_params(paso, extra)
        for paso, sids in unidades.items():
            if sids is not None:
                estado.marcar_obsoleto(paso, sorted(set(sids)))
        # escena_texto REESCRIBE el guion sin LLM: el texto ya está escrito
        # (es lo que la nota pedía), y la voz lee el guion, no los params
        if escenas_reescritas:
            datos = estado.datos_de("guion") or {}
            escenas = datos.get("escenas", [])
            for indice, escena in enumerate(escenas):
                sid = str(escena.get("id") or "")
                if sid in escenas_reescritas:
                    escena["narracion"] = escenas_reescritas[sid]
                    escena["duracion_estimada"] = comun.duracion_estimada(
                        escena["narracion"])
            datos["escenas"] = escenas
            datos["duracion_estimada"] = round(
                sum(float(e.get("duracion_estimada") or 0.0)
                    for e in escenas), 2)
            params = estado.paso("guion").get("params") or \
                registro.params_defecto_de("guion")
            estado.completar("guion", params, datos,
                             unidades=_contar_unidades(datos))
            estado.aprobar("guion")   # lo aprobó quien lo corrigió a mano
            trabajo.avance(f"guion reescrito en {len(escenas_reescritas)} "
                           "escena(s), sin gastar LLM")
    return {"extras": sorted(extras),
            "unidades": {p: sorted(set(u)) for p, u in unidades.items() if u},
            "escenas_reescritas": sorted(escenas_reescritas)}


def _correr_repaso(proyecto: Proyecto, solo_notas: list[str],
                   regenerar: bool, ambitos_vetados: tuple):
    """UN trabajo: enrutar -> escribir cajones -> rehacer lo que toca."""

    def funcion(trabajo):
        estado = Estado(proyecto)
        ficha = repaso.leer(proyecto)
        pendientes = repaso.pendientes(proyecto)
        if solo_notas:
            queridas = set(solo_notas)
            pendientes = [n for n in pendientes if n.get("id") in queridas]
        if not pendientes:
            return {"notas": [], "cambios": [], "tareas": [], "hechos": [],
                    "avisos": ["no hay notas pendientes que aplicar"]}
        trabajo.avance(f"re-anclando {len(pendientes)} nota(s)")
        cortes = _tiempos_de(proyecto)
        notas = repaso.reanclar(pendientes, cortes)
        planos = _planos_del_repaso(proyecto)
        contextos = {n["id"]: repaso.contexto_de_nota(n, cortes, planos)
                     for n in notas}
        datos = proyecto.leer()
        reparto = repaso.enrutar(
            notas, contextos, titulo=str(datos.get("nombre", "")),
            duracion=sum(c["t_out"] - c["t_in"] for c in cortes),
            estado=" · ".join(f"{p}:{estado.estado_de(p)}"
                              for p in GRAFO
                              if estado.estado_de(p) != "vacio"),
            proyecto_id=proyecto.id, ambitos_vetados=ambitos_vetados,
            avisar=trabajo.avance)
        for aviso in reparto["avisos"]:
            trabajo.avance(f"aviso: {aviso}")
        cambios = reparto["cambios"]
        if not cambios:
            return {"reparto": reparto, "tareas": [], "hechos": [],
                    "aplicadas": []}
        resumen = repaso.resumen_de(reparto)
        trabajo.avance(f"{resumen['frase']} — rehace: "
                       f"{', '.join(resumen['tareas']) or 'nada'}"
                       + (" (cuesta imágenes)" if resumen["cuesta_imagenes"]
                          else ""))
        escrito = _aplicar_cambios(proyecto, cambios, trabajo)
        tareas = repaso.tareas_de(cambios)
        if not proyecto.ruta("pasos/render/final.mp4").exists() \
                and "render" in tareas:
            # sin vídeo montado no hay nada que volver a montar
            tareas = [t for t in tareas if t != "render"]
            trabajo.avance("no había vídeo montado: el render se salta")
        hechos = []
        if regenerar:
            # QUÉ unidades por paso: sólo las tocadas (una nota de escena
            # no vuelve a pagar las imágenes de las demás)
            por_paso: dict[str, list[str]] = dict(escrito["unidades"])
            if cambios and any(c["tipo"] == "velocidad" for c in cambios):
                por_paso["voz"] = []       # global: todo el audio
            for paso in tareas:
                trabajo.comprobar_cancelacion()
                unidades_p = por_paso.get(paso) or []
                params = estado.paso(paso).get("params") or \
                    registro.params_defecto_de(paso)
                trabajo.avance(f"rehaciendo {paso}"
                               + (f" ({len(unidades_p)} unidad/es)"
                                  if unidades_p else ""))
                _correr(proyecto, paso, params, unidades_p)(trabajo)
                hechos.append(paso)
        aplicadas = repaso.marcar_aplicadas(proyecto,
                                            [n["id"] for n in notas])
        proyecto.bitacora("repaso_aplicado",
                          {"notas": [n["id"] for n in notas],
                           "cambios": [c["tipo"] for c in cambios],
                           "tareas": tareas, "hechos": hechos})
        return {"reparto": reparto, "resumen": resumen, "escrito": escrito,
                "tareas": tareas, "hechos": hechos, "aplicadas": aplicadas}

    return funcion


@router.post("/{pid}/repaso/aplicar", status_code=202, dependencies=_MUTAR)
def aplicar_repaso(pid: str, cuerpo: dict | None = None) -> dict:
    """Aplica las notas pendientes: enruta, escribe y rehace lo justo.

    `notas` limita a unas ids concretas; `regenerar: false` sólo escribe
    los cajones y deja los pasos sucios (el modo «mirar el reparto
    primero»); `ambitos_vetados` son ámbitos que esta pantalla no
    arregla.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    if GESTOR.activo_de(pid):
        raise HTTPException(409, "ya hay un trabajo en marcha en este "
                                 "proyecto")
    if not repaso.pendientes(proyecto):
        raise HTTPException(409, "no hay notas pendientes que aplicar")
    solo_notas = [str(i) for i in cuerpo.get("notas") or []]
    regenerar = cuerpo.get("regenerar", True) is not False
    vetados = tuple(str(a) for a in cuerpo.get("ambitos_vetados") or ())
    trabajo = GESTOR.lanzar(pid, "repaso", _correr_repaso(
        proyecto, solo_notas, regenerar, vetados))
    proyecto.bitacora("repaso_lanzado", {"trabajo": trabajo.id,
                                         "notas": solo_notas,
                                         "regenerar": regenerar})
    return GESTOR.estado(trabajo.id)


# ------------------------------------------------------- notas de montaje

_FICHERO_MONTAJE = "notas_montaje.json"


@router.get("/{pid}/montaje/notas", dependencies=[_SESION])
def leer_notas_montaje(pid: str) -> dict:
    """El texto libre del montaje: decisiones que no viven en params."""
    proyecto = _proyecto_o_404(pid)
    ficha = leer_json(proyecto.ruta(_FICHERO_MONTAJE), {}) or {}
    return {"texto": str(ficha.get("texto", "")),
            "actualizado": ficha.get("actualizado")}


@router.put("/{pid}/montaje/notas", dependencies=_MUTAR)
def guardar_notas_montaje(pid: str, cuerpo: dict) -> dict:
    proyecto = _proyecto_o_404(pid)
    texto = str((cuerpo or {}).get("texto", ""))[:20000]
    with lock_de(pid):
        escribir_json(proyecto.ruta(_FICHERO_MONTAJE),
                      {"texto": texto, "actualizado": ahora()})
        datos = proyecto.leer()
        datos["actualizado"] = ahora()
        proyecto.escribir(datos)
    return {"texto": texto, "actualizado": ahora()}


# ===================================================================== #
# CAPTURAS ANOTADAS                                                    #
# ===================================================================== #
#
# El feedback por escena no expresa lo que pasa en UN instante; la
# captura sí. El navegador compone el fotograma (canvas), pinta encima
# y sube el PNG con los trazos normalizados. Al aplicar, cada captura
# se traduce a feedback por unidad y se rehace SOLO esa unidad.
# Ver nucleo/capturas.py.

@router.get("/{pid}/capturas", dependencies=[_SESION])
def listar_capturas(pid: str, paso: str | None = None,
                    escena: str | None = None,
                    pendientes: bool | None = None) -> list[dict]:
    return capturas.Almacen(_proyecto_o_404(pid)).listar(
        paso=paso, escena=escena, pendientes=pendientes)


@router.post("/{pid}/capturas", status_code=201, dependencies=_MUTAR)
def crear_captura(pid: str, cuerpo: dict) -> dict:
    """Guarda un fotograma anotado del reproductor de un paso."""
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    try:
        ficha = capturas.Almacen(proyecto).crear(
            cuerpo.get("paso"), cuerpo.get("escena"),
            cuerpo.get("imagen"), trazos=cuerpo.get("trazos"),
            comentario=cuerpo.get("comentario", ""),
            t_video=cuerpo.get("t_video"), t_escena=cuerpo.get("t_escena"),
            contexto=cuerpo.get("contexto"))
    except capturas.ErrorCaptura as fallo:
        raise HTTPException(400, str(fallo)) from None
    ficha["url"] = f"/a/{proyecto.id}/{ficha['imagen']}"
    proyecto.bitacora("captura_creada", {"id": ficha["id"],
                                         "paso": ficha["paso"],
                                         "escena": ficha["escena"]})
    return ficha


@router.get("/{pid}/capturas/{cid}/imagen", dependencies=[_SESION])
def leer_imagen_captura(pid: str, cid: str) -> FileResponse:
    proyecto = _proyecto_o_404(pid)
    almacen = capturas.Almacen(proyecto)
    ficha = almacen.obtener(cid)
    if not ficha:
        raise HTTPException(404, "no hay esa captura")
    ruta = almacen.ruta_imagen(ficha)
    if not ruta.is_file():
        raise HTTPException(404, "la captura perdió su PNG")
    return FileResponse(ruta, media_type="image/png")


@router.delete("/{pid}/capturas/{cid}", status_code=204, dependencies=_MUTAR)
def borrar_captura(pid: str, cid: str):
    proyecto = _proyecto_o_404(pid)
    try:
        borrada = capturas.Almacen(proyecto).borrar(cid)
    except capturas.ErrorCaptura as fallo:
        raise HTTPException(400, str(fallo)) from None
    if borrada is None:
        raise HTTPException(404, "no hay esa captura")


def _correr_capturas(proyecto: Proyecto, ids: list[str]):
    """UN trabajo: capturas -> feedback por unidad -> rehacer lo tocado."""

    def funcion(trabajo):
        estado = Estado(proyecto)
        almacen = capturas.Almacen(proyecto)
        fichas = almacen.obtener_varias(ids)
        trabajo.avance(f"traduciendo {len(fichas)} captura(s) a feedback")
        grupos = capturas.aplicar(estado, fichas)
        if not grupos:
            almacen.marcar_aplicadas([f["id"] for f in fichas],
                                     trabajo=trabajo.id)
            return {"grupos": [], "hechos": [],
                    "avisos": ["las capturas no apuntan a ninguna escena "
                               "de este vídeo"]}
        trabajo.avance("; ".join(f"{g['paso']}/{g['escena']}"
                                 for g in grupos))
        por_paso: dict[str, list[str]] = {}
        for grupo in grupos:
            por_paso.setdefault(grupo["paso"], []).append(grupo["escena"])
        hechos = []
        for paso in repaso.ORDEN:
            if paso not in por_paso:
                continue
            trabajo.comprobar_cancelacion()
            unidades = sorted(set(por_paso[paso]))
            params = estado.paso(paso).get("params") or \
                registro.params_defecto_de(paso)
            trabajo.avance(f"rehaciendo {paso}: {', '.join(unidades)}")
            _correr(proyecto, paso, params, unidades)(trabajo)
            hechos.append(paso)
        # el vídeo montado se re-monta si lo estaba
        if hechos and proyecto.ruta("pasos/render/final.mp4").exists():
            params = estado.paso("render").get("params") or \
                registro.params_defecto_de("render")
            trabajo.avance("rehaciendo render")
            _correr(proyecto, "render", params, [])(trabajo)
            hechos.append("render")
        almacen.marcar_aplicadas([f["id"] for f in fichas],
                                 trabajo=trabajo.id)
        proyecto.bitacora("capturas_aplicadas",
                          {"capturas": [f["id"] for f in fichas],
                           "hechos": hechos})
        return {"grupos": grupos, "hechos": hechos}

    return funcion


@router.post("/{pid}/capturas/aplicar", status_code=202, dependencies=_MUTAR)
def aplicar_capturas(pid: str, cuerpo: dict | None = None) -> dict:
    """Aplica capturas: feedback por unidad y regeneración de lo tocado."""
    proyecto = _proyecto_o_404(pid)
    ids = [str(i) for i in (cuerpo or {}).get("ids") or []]
    if not ids:
        raise HTTPException(400, "hace falta qué capturas aplicar (ids)")
    if GESTOR.activo_de(pid):
        raise HTTPException(409, "ya hay un trabajo en marcha en este "
                                 "proyecto")
    try:
        capturas.Almacen(proyecto).obtener_varias(ids)
    except capturas.ErrorCaptura as fallo:
        raise HTTPException(404, str(fallo)) from None
    trabajo = GESTOR.lanzar(pid, "capturas", _correr_capturas(proyecto, ids))
    proyecto.bitacora("capturas_lanzadas", {"trabajo": trabajo.id,
                                            "ids": ids})
    return GESTOR.estado(trabajo.id)


# --------------------------------------------------------- catálogo visual

@router.get("/{pid}/catalogo", dependencies=[_SESION])
def leer_catalogo(pid: str) -> dict:
    """El catálogo guardado: quién sale, dónde y con qué tono."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    catalogo = catalogo_visual.catalogo_de(params)
    return {"catalogo": catalogo,
            "planos": _planos_del_guion(proyecto),
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.put("/{pid}/catalogo", dependencies=_MUTAR)
def guardar_catalogo(pid: str, cuerpo: dict) -> dict:
    """Aprueba un catálogo: es la decisión de una persona.

    El catálogo vive en params de ASSETS (regla del original): cambiar
    cómo es un personaje cambia las imágenes, no el texto ni la voz.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    crudo = (cuerpo or {}).get("catalogo")
    if not isinstance(crudo, dict):
        raise HTTPException(400, "se esperaba {catalogo: {...}}")
    catalogo = catalogo_visual._limpiar(crudo, sorted(_ids_de_planos(proyecto)))
    estado.actualizar_params("assets", {"catalogo": catalogo})
    proyecto.bitacora("catalogo_guardado",
                      {"personajes": len(catalogo["reparto"]),
                       "sets": len(catalogo["sets"]),
                       "beats": len(catalogo["beats"])})
    return {"catalogo": catalogo, "avisos": catalogo.get("avisos", []),
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.post("/{pid}/catalogo/proponer", status_code=202, dependencies=_MUTAR)
def proponer_catalogo(pid: str, cuerpo: dict | None = None) -> dict:
    """El agente lee el guion entero y propone el catálogo (cola)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})
    peticion = str((cuerpo or {}).get("peticion") or "")

    def funcion(trabajo):
        return catalogo_visual.proponer(proyecto, params, trabajo,
                                        peticion=peticion)

    trabajo = GESTOR.lanzar(pid, "catalogo", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


# -------------------------------------------------------------- encuadres

@router.get("/{pid}/encuadres", dependencies=[_SESION])
def leer_encuadres(pid: str) -> dict:
    """La escalera de cartas y qué carta cae en cada plano hoy."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    unidades = params.get("unidades") or {}
    forzadas = {sid: str((f or {}).get("carta") or "")
                for sid, f in unidades.items() if isinstance(f, dict)}
    planos = _planos_del_guion(proyecto)
    escenas = [{"id": p["id"]} for p in planos if p["id"]]
    reparto = encuadres.repartir(escenas, semilla=proyecto.id,
                                 forzadas=forzadas)
    return {"catalogo": encuadres.catalogo(),
            "reparto": {sid: carta["id"] for sid, carta in reparto.items()},
            "forzadas": {sid: c for sid, c in forzadas.items() if c},
            "planos": planos,
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.put("/{pid}/encuadres", dependencies=_MUTAR)
def guardar_encuadres(pid: str, cuerpo: dict) -> dict:
    """Fija (o libera) la carta de planos concretos.

    La carta de una persona manda sobre el reparto. Un id vacío la
    libera (vuelve a tocarle la que diga la escalera).
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    ids = _ids_de_planos(proyecto)
    plan = (cuerpo or {}).get("plan")
    if not isinstance(plan, dict) or not plan:
        raise HTTPException(400, "se esperaba {plan: {plano: carta}}")
    unidades, tocados, avisos = {}, [], []
    for uid, crudo in plan.items():
        sid = str(uid).strip().upper()
        carta = str(crudo or "").strip()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        if carta and carta not in encuadres.POR_ID:
            avisos.append(f"{sid}: '{carta}' no está en la escalera, se "
                          "ignora")
            continue
        unidades[sid] = {"carta": carta}
        tocados.append(sid)
    if not tocados:
        raise HTTPException(400, "; ".join(avisos) or "nada que guardar")
    estado.actualizar_params("assets", {"unidades": unidades})
    estado.marcar_obsoleto("assets", tocados)
    proyecto.bitacora("encuadres_guardados", {"planos": tocados})
    return {"tocados": tocados, "avisos": avisos,
            "obsoletos": estado.unidades_obsoletas("assets")}


# ----------------------------------------------------------- guía de estilo

@router.get("/{pid}/guia", dependencies=[_SESION])
def leer_guia(pid: str) -> dict:
    """La guía de estilo escrita del proyecto (la biblia con números)."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    clave = moodboard.clave_de(guia_estilo.guia_de(params))
    ficha_moodboard = moodboard.ficha_de(clave) if clave else {}
    carpeta = proyecto.ruta("estilo", "aportadas")
    return {"guia": guia_estilo.guia_de(params),
            "estilo": params.get("estilo", ""),
            "aportadas": sorted(r.name for r in carpeta.iterdir()
                                if r.is_file()
                                and r.suffix.lower() in estilo.EXT_KIT)
            if carpeta.is_dir() else [],
            "moodboard": {"clave": clave,
                          "estado": ficha_moodboard.get("estado", "falta")},
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.put("/{pid}/guia", dependencies=_MUTAR)
def guardar_guia(pid: str, cuerpo: dict) -> dict:
    """Aprueba una guía de estilo: números que obedecer, no adjetivos."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    crudo = (cuerpo or {}).get("guia")
    if crudo is None:
        raise HTTPException(400, "se esperaba {guia: {...}}")
    if not isinstance(crudo, dict):
        crudo = {}
    ficha = {"guia": " ".join(str(crudo.get("guia") or "").split())}
    for campo in guia_estilo.CAMPOS:
        ficha[campo] = " ".join(str(crudo.get(campo) or "").split())
    paleta = []
    for color in (crudo.get("paleta") or []):
        texto = str(color).strip().lower()
        if guia_estilo._hex(texto):
            paleta.append(texto)
        if len(paleta) >= 16:
            break
    ficha["paleta"] = paleta
    estado.actualizar_params("assets", {"guia": ficha})
    proyecto.bitacora("guia_guardada",
                      {"palabras": len(ficha["guia"].split()),
                       "colores": len(paleta)})
    return {"guia": ficha,
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.post("/{pid}/guia/proponer", status_code=202, dependencies=_MUTAR)
def proponer_guia(pid: str, cuerpo: dict | None = None) -> dict:
    """El agente escribe la guía con números (cola). PROPONE, no guarda.

    Con aportadas en `estilo/` (el kit del canal heredado al crear, o
    material subido al proyecto) la guía nace de MIRARLAS: son el
    material humano y viajan adjuntas a la llamada.
    """
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})
    descripcion = str((cuerpo or {}).get("descripcion") or "")
    peticion = str((cuerpo or {}).get("peticion") or "")
    carpeta = proyecto.ruta("estilo", "aportadas")
    imagenes = sorted(str(r) for r in carpeta.iterdir()
                      if r.is_file()
                      and r.suffix.lower() in estilo.EXT_KIT) \
        if carpeta.is_dir() else []

    def funcion(trabajo):
        return guia_estilo.proponer(proyecto, params, trabajo,
                                    descripcion=descripcion,
                                    imagenes=imagenes,
                                    peticion=peticion)

    trabajo = GESTOR.lanzar(pid, "guia", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


# --------------------------------------------------------------- moodboard

@router.get("/{pid}/moodboard", dependencies=[_SESION])
def leer_moodboard(pid: str) -> dict:
    """Las láminas del estilo: propuesta, banco y qué falta."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    guia = guia_estilo.guia_de(params)
    clave = moodboard.clave_de(guia)
    if not clave:
        return {"posible": False,
                "por_que_no": "no hay guía escrita: las láminas saldrían "
                              "con el estilo por defecto del generador",
                "ejes": []}
    ficha = moodboard.ficha_de(clave)
    ejes = []
    for eje in sorted(moodboard.EJES):
        ruta = moodboard.ruta_lamina(clave, eje)
        ejes.append({"eje": eje, "titulo": moodboard.EJES[eje]["titulo"],
                     "hay": ruta is not None,
                     "pendiente": eje in (ficha.get("pendientes") or []),
                     "version": moodboard.version_de(ruta) if ruta else 0})
    return {"posible": True, "clave": clave, "ficha": ficha, "ejes": ejes,
            "estado": ficha.get("estado", "falta"),
            "coste_usd": ficha.get("coste_usd", 0.0)}


@router.post("/{pid}/moodboard/generar", status_code=202, dependencies=_MUTAR)
def generar_moodboard(pid: str, cuerpo: dict | None = None) -> dict:
    """Dibuja las láminas que falten como PROPUESTA (trabajo de cola).

    Sólo las pedidas si el cuerpo trae 'ejes': es lo que hace útil el
    feedback, porque en la práctica derivan unas láminas y otras salen
    clavadas.
    """
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})
    guia = guia_estilo.guia_de(params)
    clave = moodboard.clave_de(guia)
    if not clave:
        raise HTTPException(400, "no hay guía escrita: escribe o propone "
                                 "primero la guía de estilo")
    peticiones = (cuerpo or {}).get("peticiones") or {}
    if not isinstance(peticiones, dict):
        peticiones = {}
    calidad = str((cuerpo or {}).get("calidad") or "medium")
    if calidad not in comun.COSTE_IMAGEN:
        calidad = "medium"

    def funcion(trabajo):
        return moodboard.generar(clave, guia, ejes=(cuerpo or {}).get("ejes"),
                                 peticiones={k: str(v) for k, v
                                             in peticiones.items()},
                                 calidad=calidad, avisar=trabajo.avance,
                                 proyecto_id=proyecto.id,
                                 idioma=str(proyecto.leer()
                                            .get("idioma", "es")))

    trabajo = GESTOR.lanzar(pid, "moodboard", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/moodboard/aprobar", dependencies=_MUTAR)
def aprobar_moodboard(pid: str) -> dict:
    """Mete la propuesta en el banco global. Decisión de una persona."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})
    clave = moodboard.clave_de(guia_estilo.guia_de(params))
    try:
        resultado = moodboard.aprobar(clave)
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    proyecto.bitacora("moodboard_aprobado",
                      {"clave": clave, "ejes": resultado["ejes"]})
    return resultado


@router.get("/{pid}/moodboard/{eje}/imagen", dependencies=[_SESION])
def lamina_moodboard(pid: str, eje: str, origen: str = "") -> FileResponse:
    """Una lámina, propuesta si la hay (que es lo último dibujado)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})
    clave = moodboard.clave_de(guia_estilo.guia_de(params))
    ruta = moodboard.ruta_lamina(clave, eje, origen) if clave else None
    if not ruta:
        raise HTTPException(404, "no hay lámina de ese eje")
    return FileResponse(ruta, media_type="image/png")


# -------------------------------------------------------------- conservación

@router.post("/{pid}/conservacion", status_code=202, dependencies=_MUTAR)
def planear_conservacion(pid: str) -> dict:
    """Compara el guion con lo ya pagado y reparte (trabajo de cola).

    Devuelve el PLAN: qué imágenes siguen valiendo, cuáles hay que
    rehacer y por qué. MARCAR es otro gesto (aplicar), y regenerar
    otro (el de siempre, con el coste delante).
    """
    proyecto = _proyecto_o_404(pid)

    def funcion(trabajo):
        return conservar.plan(proyecto, avisar=trabajo.avance)

    trabajo = GESTOR.lanzar(pid, "conservacion", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/conservacion/aplicar", dependencies=_MUTAR)
def aplicar_conservacion(pid: str, cuerpo: dict) -> dict:
    """Escribe el plan en el estado: MARCA lo que hay que rehacer.

    Conservar no se escribe en ningún sitio: es lo que ya está en disco
    y la regeneración por unidades lo conserva solo.
    """
    proyecto = _proyecto_o_404(pid)
    if not isinstance(cuerpo, dict) or not cuerpo.get("posible"):
        raise HTTPException(400, (cuerpo or {}).get("por_que_no")
                            or "nada que conservar")
    estado = Estado(proyecto)
    try:
        resultado = conservar.aplicar(estado, cuerpo, proyecto)
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    return {**resultado,
            "obsoletos_assets": estado.unidades_obsoletas("assets"),
            "obsoletos_voz": estado.unidades_obsoletas("voz")}


# ============================================================== FASE G: sonido
#
# El contrato de arriba para abajo: BUSCAR sale a la red y se hace con una
# persona delante (escuchando); RENDERIZAR no sale a la red (el banco ya
# tiene los ficheros). Nada de esto genera vídeo: escribe los params del
# render y ya.

@router.get("/{pid}/sonido")
def leer_sonido(pid: str) -> dict:
    """Qué suena en este vídeo: música, efectos, interruptor y niveles."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("render").get("params") or {}
    hay_jamendo, hay_freesound = sonido.hay_claves()
    prohibidos = sonido.vetados()
    surtido = params.get("efectos") or {}
    efectos = []
    for papel, fichas in surtido.items():
        for ficha in (fichas or []):
            clave = sonido.clave_de(ficha)
            nombre = sonido._nombre_de(ficha)
            efectos.append({
                **{k: ficha.get(k) for k in
                   ("fuente", "id", "titulo", "autor", "duracion", "licencia",
                    "etiquetas", "brillo", "dureza", "reverb", "error")},
                "papel": papel, "clave": clave,
                "en_banco": sonido.banco("efectos", nombre).exists(),
                "muestra": f"/api/proyectos/efectos-banco/{nombre}",
                "vetado": clave in prohibidos,
                "agudo": sonido.agudeza(ficha),
            })
    vetados = [{"clave": v["clave"], "titulo": v.get("titulo") or "",
                "autor": v.get("autor") or "", "papel": v.get("papel") or "",
                "fecha": v.get("fecha") or ""}
               for v in prohibidos.values()]
    return {
        "activo": bool(params.get("sonido", True)),
        "musica": params.get("musica") or {},
        "lufs": float(params.get("musica_lufs") or sonido.MUSICA_LUFS),
        "musica_db": float(params.get("musica_db") or 0.0),
        "efectos_db": float(params.get("efectos_db") or 0.0),
        "efectos": efectos,
        "papeles": {papel: {"nombre": f["nombre"],
                            "descripcion": f["descripcion"],
                            "cuantos": len(surtido.get(papel) or [])}
                    for papel, f in sonido.PAPELES.items()},
        "vetados": vetados,
        "animos": sonido.ANIMOS,
        "hay_jamendo": hay_jamendo, "hay_freesound": hay_freesound,
        "resumen": sonido.describir(params),
        "creditos": _creditos_musica(params.get("musica") or {}),
    }


def _creditos_musica(musica: dict) -> list[dict]:
    """Los créditos de lo que suena: Jamendo/FreeSound lo piden y el vídeo
    los debe. Del lado del canal, junto al banco."""
    salida = []
    if musica.get("tramos"):
        for tramo in musica["tramos"]:
            salida.append({"titulo": tramo.get("titulo") or "",
                           "artista": tramo.get("artista") or "",
                           "fuente": "Jamendo",
                           "licencia": tramo.get("licencia") or ""})
    elif musica.get("id"):
        salida.append({"titulo": musica.get("titulo") or "",
                       "artista": musica.get("artista") or "",
                       "fuente": "Jamendo",
                       "licencia": musica.get("licencia") or ""})
    return salida


@router.put("/{pid}/sonido", dependencies=_MUTAR)
def guardar_sonido(pid: str, cuerpo: dict | None = None) -> dict:
    """El interruptor, el nivel y EL TEMA ÚNICO. La banda va por su ruta.

    Elegir tema es SURTIR: se descarga al banco AQUÍ (con la persona
    delante, que acaba de escucharlo), y a partir de ahí es un dato.
    """
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    extras: dict = {}
    if "activo" in cuerpo:
        extras["sonido"] = bool(cuerpo["activo"])
    if "lufs" in cuerpo:
        try:
            lufs = float(cuerpo["lufs"])
        except (TypeError, ValueError):
            raise HTTPException(400, "lufs tiene que ser un número") from None
        extras["musica_lufs"] = max(-40.0, min(-10.0, lufs))
    for campo in ("musica_db", "efectos_db"):
        if campo in cuerpo:
            try:
                extras[campo] = max(-24.0, min(24.0, float(cuerpo[campo])))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{campo} tiene que ser un número") \
                    from None
    if "musica" in cuerpo:
        musica = cuerpo["musica"]
        if musica in (None, {}, ""):
            extras["musica"] = {}
        elif isinstance(musica, dict) and musica.get("id"):
            try:
                sonido.traer(musica, "musica")
            except Exception as fallo:            # noqa: BLE001
                raise HTTPException(502, f"no se pudo bajar el tema: "
                                          f"{str(fallo)[:160]}") from None
            extras["musica"] = musica
        else:
            raise HTTPException(400, "musica tiene que ser un tema o nada")
    estado = Estado(proyecto)
    with lock_de(proyecto.id):
        if extras:
            estado.actualizar_params("render", extras)
        if "activo" in extras:
            proyecto.bitacora("sonido", {"activo": extras["activo"]})
        if extras.get("musica"):
            proyecto.bitacora("musica_puesta", {
                "titulo": extras["musica"].get("titulo"),
                "artista": extras["musica"].get("artista")})
    return leer_sonido(pid)


@router.post("/{pid}/sonido/musica")
def buscar_musica_ruta(pid: str, cuerpo: dict | None = None) -> dict:
    """Busca temas en Jamendo según el tono del vídeo. Escuchar y elegir."""
    _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    try:
        temas = sonido.buscar_musica(
            animo=str(cuerpo.get("animo") or "sobrio"),
            cuantas=int(cuerpo.get("cuantas") or 12),
            duracion_s=float(cuerpo.get("duracion_s") or 0),
            velocidad=str(cuerpo.get("velocidad") or "low"),
            instrumental=bool(cuerpo.get("instrumental", True)),
            extra=str(cuerpo.get("extra") or "")[:60])
    except RuntimeError as fallo:
        raise HTTPException(400, str(fallo)) from None
    except Exception as fallo:                    # noqa: BLE001
        raise HTTPException(502, f"Jamendo no respondió: {str(fallo)[:160]}") \
            from None
    return {"temas": temas}


@router.get("/{pid}/sonido/arco")
def arco_sonido(pid: str) -> dict:
    """En qué tramos se parte el vídeo y qué ánimo pediría para cada uno."""
    proyecto = _proyecto_o_404(pid)
    cortes = _tiempos_de(proyecto)
    if not cortes:
        raise HTTPException(400, "no hay voz grabada: el ritmo se lee del "
                                 "montaje, no del guion")
    duracion = sum(c["t_out"] - c["t_in"] for c in cortes)
    return {"duracion": round(duracion, 2),
            "tramos": sonido.arco_del_video(cortes, duracion)}


@router.post("/{pid}/sonido/banda", status_code=202, dependencies=_MUTAR)
def montar_banda_ruta(pid: str) -> dict:
    """Monta la banda sonora por tramos (trabajo de cola: sale a la red)."""
    proyecto = _proyecto_o_404(pid)
    cortes = _tiempos_de(proyecto)
    if not cortes:
        raise HTTPException(400, "no hay voz grabada: sin el ritmo del "
                                 "montaje no hay tramos")
    if not sonido.hay_claves()[0]:
        raise HTTPException(400, "falta la clave de Jamendo (Configuración)")
    duracion = sum(c["t_out"] - c["t_in"] for c in cortes)

    def funcion(trabajo):
        ficha = sonido.montar_banda(cortes, duracion, avisar=trabajo.avance)
        with lock_de(proyecto.id):
            Estado(proyecto).actualizar_params("render",
                                               {"musica": ficha})
        proyecto.bitacora("banda_montada", {"tramos": len(ficha["tramos"])})
        return ficha

    trabajo = GESTOR.lanzar(pid, "banda", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/sonido/efectos", status_code=202, dependencies=_MUTAR)
def surtir_efectos(pid: str, cuerpo: dict | None = None) -> dict:
    """Surtido de efectos por papel (trabajo de cola: sale a la red)."""
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    papeles = [p for p in (cuerpo.get("papeles") or sonido.PAPELES)
               if p in sonido.PAPELES] or list(sonido.PAPELES)
    salteado = int(cuerpo.get("salteado") or 0)
    if not sonido.hay_claves()[1]:
        raise HTTPException(400, "falta la clave de FreeSound (Configuración)")

    def funcion(trabajo):
        nuevo = {}
        for indice, papel in enumerate(papeles):
            trabajo.avance(0.1 + 0.8 * indice / len(papeles),
                           f"surtiendo {sonido.PAPELES[papel]['nombre']}")
            nuevo[papel] = sonido.surtir(papel, salteado=salteado)
        estado = Estado(proyecto)
        previo = (estado.paso("render").get("params") or {}).get("efectos") or {}
        # los papeles NO pedidos se quedan como están: re-surtir uno no
        # vacía los demás
        mezcla = {**{k: v for k, v in previo.items() if k not in papeles},
                  **nuevo}
        with lock_de(proyecto.id):
            estado.actualizar_params("render", {"efectos": mezcla})
        proyecto.bitacora("efectos_surtidos",
                          {"cuantos": sum(len(v) for v in nuevo.values())})
        return {"papeles": {k: len(v) for k, v in nuevo.items()}}

    trabajo = GESTOR.lanzar(pid, "efectos", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.post("/{pid}/sonido/vetados", dependencies=_MUTAR)
def vetar_efecto(pid: str, cuerpo: dict) -> dict:
    """Veta (o desveta) un efecto para todo el canal."""
    _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    ficha = cuerpo.get("efecto") or cuerpo
    if cuerpo.get("quitar"):
        quito = sonido.desvetar(ficha)
        return {"ok": quito, "vetados": list(sonido.vetados())}
    try:
        entrada = sonido.vetar(ficha, papel=cuerpo.get("papel"),
                               motivo=cuerpo.get("motivo") or "")
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    return {"ok": True, "veto": entrada, "vetados": list(sonido.vetados())}


@router.get("/efectos-banco/{archivo}")
def oir_efecto(archivo: str):
    """Un efecto del banco, PARA OÍRLO en la pantalla. Read-only."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", archivo) or ".." in archivo:
        raise HTTPException(404, "archivo desconocido")
    ruta = sonido.banco("efectos", archivo)
    if not ruta.is_file():
        raise HTTPException(404, "ese efecto no está en el banco")
    return FileResponse(ruta)


# ---------------------------------------------------------- transiciones

@router.get("/{pid}/transiciones")
def leer_transiciones(pid: str) -> dict:
    """Las transiciones que existen y cuáles entran en este vídeo."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("render").get("params") or {}
    elegidas = transiciones.elegidas_de(params)
    ficha = transiciones.catalogo_para_pantalla(elegidas)
    try:
        ficha["duracion"] = float(params.get("duracion_transicion") or 0.4)
    except (TypeError, ValueError):
        ficha["duracion"] = 0.4
    ficha["todas_de_fabrica"] = not [t for t in (params.get("transiciones")
                                                 or [])]
    # el acento cromático de ESTE vídeo (paleta de callouts o de la guía)
    paleta = {}
    callouts = p2_brief.proyecto_leer_datos(proyecto, "callouts") or {}
    if isinstance(callouts.get("paleta"), dict):
        paleta = callouts["paleta"]
    if not paleta.get("acento"):
        guia_params = estado.paso("assets").get("params") or {}
        colores = (guia_estilo.guia_de(guia_params).get("paleta") or [])
        if colores:
            paleta = {"acento": colores[0]}
    ficha["acento"] = transiciones.acentos(paleta)
    # QUÉ TRANSICIÓN LLEVA CADA PLANO, resuelta por el motor (determinista):
    # viaja a la pantalla para que elegir mirando sea elegir de verdad
    import hashlib                                          # noqa: PLC0415
    cortes = _tiempos_de(proyecto)
    semilla = int.from_bytes(hashlib.sha1(pid.encode()).digest()[:8], "big")
    reparto = transiciones.resolver(cortes, params, semilla=semilla)
    ficha["reparto"] = [{"id": c["id"], "t_in": c["t_in"],
                         **reparto.get(c["id"], {})}
                        for c in cortes if c["id"] in reparto]
    ficha["resumen"] = transiciones.describir(params)
    return ficha


@router.put("/{pid}/transiciones", dependencies=_MUTAR)
def guardar_transiciones(pid: str, cuerpo: dict | None = None) -> dict:
    """La paleta de transiciones y su duración. Sólo toca el render."""
    proyecto = _proyecto_o_404(pid)
    cuerpo = cuerpo or {}
    estado = Estado(proyecto)
    extras: dict = {}
    if "transiciones" in cuerpo:
        lista = cuerpo["transiciones"]
        if not isinstance(lista, list):
            raise HTTPException(400, "transiciones tiene que ser una lista")
        validas = [t for t in lista if t in transiciones.CATALOGO]
        extras["transiciones"] = validas      # vacío = las de fábrica
    if "duracion" in cuerpo:
        try:
            duracion = float(cuerpo["duracion"])
        except (TypeError, ValueError):
            raise HTTPException(400, "duracion tiene que ser un número") \
                from None
        extras["duracion_transicion"] = max(0.1, min(1.5, duracion))
    with lock_de(proyecto.id):
        estado.actualizar_params("render", extras)
        proyecto.bitacora("transiciones", extras)
    return leer_transiciones(pid)
