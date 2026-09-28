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
from fastapi.responses import Response, StreamingResponse

from .. import seguridad
from ..config import AJUSTES
from ..nucleo import estilo
from ..nucleo import coste as nucleo_coste
from ..nucleo import grafismo
from ..nucleo.coste import de_proyecto
from ..nucleo.estado import GRAFO, Estado, descendientes_de
from ..nucleo import recetas
from ..nucleo.proyecto import (Proyecto, ahora, id_valido, leer_json,
                               leer_jsonl, lock_de)
from ..nucleo.trabajos import TrabajoCancelado
from ..pasos import (cartelas, direccion, p2_brief, p3_guion, p4_voz,
                     p6_assets, redactor, registro)
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
            "presupuesto": datos.get("presupuesto"),
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
    params_por_paso = {paso: registro.params_defecto_de(paso)
                       for paso in GRAFO}
    # el estilo del canal (si ya está definido) se siembra aquí también:
    # COPIA de valores sobre los defectos, nunca una referencia
    estilo_canal = estilo.leer(AJUSTES.datos)
    if estilo_canal["definido"]:
        estilo.aplicar_a_params(params_por_paso, estilo_canal)
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
        ficha = proyecto.leer()
        ficha["actualizado"] = ahora()
        proyecto.escribir(ficha)
    proyecto.bitacora("estilo_aplicado", {"pasos": tocados})
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
    """El tablero de la receta: cada tarea con su estado real."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    pestañas = {}
    for clave, titulo in recetas.PESTANAS.items():
        tareas = []
        for t in recetas.TAREAS:
            if t["pestana"] != clave:
                continue
            ficha = estado.paso(t["paso"])
            tareas.append({**t, "estado": estado.estado_de(t["paso"]),
                           "version": ficha.get("version", 0),
                           "aprobado": bool(ficha.get("aprobado"))})
        pestañas[clave] = {"nombre": titulo, "tareas": tareas}
    return {"pestañas": pestañas, "activo": GESTOR.activo_de(pid)}


@router.post("/{pid}/receta/{pestana}", status_code=202, dependencies=_MUTAR)
def correr_receta(pid: str, pestana: str, cuerpo: dict | None = None) -> dict:
    """Lanza la receta de UNA pestaña como trabajo en segundo plano."""
    proyecto = _proyecto_o_404(pid)
    if pestana not in recetas.PESTANAS:
        raise HTTPException(404, f"no hay pestaña {pestana}")
    try:
        modo = recetas.validar_modo((cuerpo or {}).get("modo"))
    except ValueError as fallo:
        raise HTTPException(400, str(fallo)) from None
    if pestana in ("voz", "montaje") and GESTOR.activo_de(pid):
        raise HTTPException(409, "ya hay un trabajo en marcha en este proyecto")
    tareas = recetas.tareas_de(pestana)
    lanzado = GESTOR.lanzar(pid, "receta",
                            lambda t: _correr_receta(proyecto, tareas,
                                                     modo, t))
    proyecto.bitacora("receta_lanzada", {"pestaña": pestana, "modo": modo,
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
    planos_de = {p.get("escena"): p for p in assets.get("planos", [])}
    rotulos_de = {r.get("id"): r for r in callouts.get("rotulos", [])}
    titulo_de = {e.get("id"): e.get("titulo", "")
                 for e in guion.get("escenas", [])}
    narracion_de = {e.get("id"): e.get("narracion", "")
                    for e in guion.get("escenas", [])}
    escenas = []
    for escena in voz["escenas"]:
        sid = str(escena.get("id") or "")
        plano = planos_de.get(sid) or {}
        imagen = plano.get("imagen")
        if not imagen or not proyecto.ruta(str(imagen)).exists():
            imagen = None
        rotulo = rotulos_de.get(sid)
        escenas.append({
            "id": sid,
            "titulo": titulo_de.get(sid, ""),
            "narracion": narracion_de.get(sid, ""),
            "imagen": imagen,
            "audio": escena.get("audio"),
            "duracion": round(float(escena.get("duracion") or 0.0), 3),
            "palabras": escena.get("palabras") or [],
            "rotulo": ({"texto": str(rotulo.get("texto", "")),
                        "aparece": round(float(rotulo.get("aparece", 0.0)), 2),
                        "dura": round(float(rotulo.get("dura", 4.0)), 2)}
                       if rotulo else None),
        })
    render_params = estado.paso("render").get("params") or {}
    return {
        "escenas": escenas,
        "duracion": round(sum(e["duracion"] for e in escenas), 2),
        "resolucion": str(render_params.get("resolucion", "1920x1080")),
        "con_rotulos": bool(callouts.get("rotulos")),
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
        for campo, clave in _CAMPOS_UNIDADES.items():
            if isinstance(datos.get(campo), list):
                datos[campo] = [ficha if (isinstance(u, dict)
                                          and str(u.get(clave, "")) == unidad)
                                else u for u in datos[campo]]
        version = estado.completar(paso, params, datos,
                                   unidades=_contar_unidades(datos))
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
                                   unidades=_contar_unidades(datos))
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
    return {"plan": cartelas.plan_de(params),
            "plantillas": grafismo.PLANTILLAS_CARTELA,
            "planos": planos,
            "max_cartelas": max(1, round(len(planos)
                                         * cartelas.FRACCION_MAXIMA)),
            "obsoletos": estado.unidades_obsoletas("assets")}


@router.get("/{pid}/cartelas/vista", dependencies=[_SESION])
def vista_cartela(pid: str, plano: str) -> Response:
    """La cartela de un plano como SVG: lo que dibuja el render."""
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    params = estado.paso("assets").get("params", {})
    ficha = cartelas.plan_de(params).get(str(plano).strip().upper())
    if not ficha:
        raise HTTPException(404, f"el plano {plano} no lleva cartela")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz") or {}
    duracion = next((float(v.get("duracion", 0) or 0)
                     for v in voz.get("escenas", [])
                     if v.get("id") == str(plano).strip().upper()), 4.0)
    svg = grafismo.svg_cartela(ficha.get("plantilla", "titulo"),
                               ficha.get("datos"), _paleta_actual(estado),
                               duracion or 4.0)
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/{pid}/cartelas/plan", status_code=202, dependencies=_MUTAR)
def proponer_cartelas(pid: str) -> dict:
    """El agente decide qué tramos van mejor como cartela (trabajo de cola)."""
    proyecto = _proyecto_o_404(pid)
    params = Estado(proyecto).paso("assets").get("params", {})

    def funcion(trabajo):
        return cartelas.proponer(proyecto, params, trabajo)

    trabajo = GESTOR.lanzar(pid, "cartelas", funcion, unidades=[])
    return GESTOR.estado(trabajo.id)


@router.put("/{pid}/cartelas", dependencies=_MUTAR)
def guardar_cartelas(pid: str, cuerpo: dict) -> dict:
    """Fija (o quita) la cartela de planos concretos.

    Decidirla antes de generar AHORRA la imagen de ese plano: por eso
    vive con assets y por eso se ensucia el plano tocado.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    ids = _ids_de_planos(proyecto)
    plan = (cuerpo or {}).get("plan")
    if not isinstance(plan, dict) or not plan:
        raise HTTPException(400, "se esperaba {plan: {plano: ficha|null}}")
    unidades, tocados, avisos = {}, [], []
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
        valores, motivos = cartelas.validar(str(ficha.get("plantilla", "")),
                                            ficha.get("datos"))
        if valores is None:
            avisos.append(f"{sid}: {'; '.join(motivos)}")
            continue
        avisos.extend(f"{sid}: {m}" for m in motivos)
        unidades[sid] = {"cartela": {
            "plantilla": str(ficha.get("plantilla", "")),
            "datos": valores,
            "por_que": str(ficha.get("por_que", "")).strip()}}
        tocados.append(sid)
    if not tocados:
        raise HTTPException(400, "; ".join(avisos) or "nada que guardar")
    estado.actualizar_params("assets", {"unidades": unidades})
    estado.marcar_obsoleto("assets", tocados)
    proyecto.bitacora("cartelas_guardadas", {"planos": tocados})
    params = estado.paso("assets").get("params", {})
    return {"plan": cartelas.plan_de(params), "tocados": tocados,
            "avisos": avisos,
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
    """El rótulo de un plano como SVG: lo que dibuja el render.

    Los query params opcionales son la VISTA PREVIA de lo que la pantalla
    está editando (aún sin guardar): sin ellos se enseña lo guardado.
    """
    proyecto = _proyecto_o_404(pid)
    estado = Estado(proyecto)
    datos = estado.datos_de("callouts") or {}
    params = estado.paso("callouts").get("params", {})
    sid = str(plano).strip().upper()
    rotulo = next((r for r in datos.get("rotulos", [])
                   if str(r.get("id", "")).upper() == sid), None)
    if not rotulo and texto is None:
        raise HTTPException(404, f"el plano {plano} no lleva rótulo")
    svg = grafismo.svg_rotulo(
        texto if texto is not None else rotulo.get("texto", ""),
        diseno or datos.get("diseno") or params.get("diseno", "pastilla"),
        _paleta_actual(estado),
        tam or datos.get("subtitulo_tam")
        or params.get("subtitulo_tam", "normal"))
    return Response(content=svg, media_type="image/svg+xml")
