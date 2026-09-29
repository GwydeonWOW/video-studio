"""Presets: de locución, de canal y el MODO LIGHT que los genera de una tirada.

Tres cosas que viven juntas porque son la misma decisión a tres alturas:

- `GET /api/presets` — el catálogo estático de tonos de locución
  (`pasos/presets_voz`): un desplegable en la pantalla de voz.
- `/api/presets-canal` — los presets que guarda quien usa el modo editor:
  lo que se decide UNA vez por canal y se repite en cada vídeo
  (`pasos/presets_canal`). CRUD, papelera propia y aplicar a un proyecto.
- `/api/presets-light` — el modo light: cuatro campos y sale el canal
  entero, generado en un proyecto TALLER oculto de la lista y congelado
  al acabar en un preset de tipo canal (`pasos/presets_light`).

Regla heredada del original en todo lo que toca params: aplicar COPIA
valores, nunca escribe «por defecto» al abrir, y quien decide regenerar
—y pagar— sigue siendo la persona.
"""
from __future__ import annotations

import secrets
import shutil
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import seguridad
from ..config import AJUSTES
from ..motores import llm, voz_elevenlabs
from ..nucleo import grafismo
from ..nucleo.estado import Estado
from ..nucleo.proyecto import Proyecto, ahora, escribir_json, ruta_contenida
from ..pasos import (comun, guia_estilo, moodboard, p4_voz, presets_canal,
                     presets_light, presets_voz, registro)
from .rutas_trabajos import GESTOR

router = APIRouter(prefix="/api", tags=["presets"])

_SESION = Depends(seguridad.exigir_sesion)
_MUTAR = [Depends(seguridad.exigir_sesion), Depends(seguridad.exigir_origen)]

#: pasos cuyos params puede tocar un preset de canal
_PASOS_PRESET = ("brief", "guion", "assets", "voz", "callouts")


def _a_400(fallo: Exception) -> HTTPException:
    """Los errores de dominio se cuentan tal cual: son para leerlos."""
    return HTTPException(400, str(fallo))


# ----------------------------------------------------------- tonos de locución

@router.get("/presets", dependencies=[_SESION])
def listar_presets_voz() -> list[dict]:
    """El catálogo de tonos de locución para el desplegable de la voz."""
    return presets_voz.listar()


@router.get("/presets/{identificador}", dependencies=[_SESION])
def leer_preset_voz(identificador: str) -> dict:
    try:
        return presets_voz.preset(identificador)
    except ValueError as fallo:
        raise _a_400(fallo)


# ------------------------------------------------------------------ de canal

@router.get("/presets-canal", dependencies=[_SESION])
def listar_presets_canal() -> dict:
    """Todo lo guardado, agrupado por tipo, más la papelera de presets."""
    return presets_canal.listar()


@router.post("/presets-canal", status_code=201, dependencies=_MUTAR)
def guardar_preset_canal(cuerpo: dict) -> dict:
    """Guarda un preset nuevo (o actualiza uno con `pid`)."""
    datos = cuerpo if isinstance(cuerpo, dict) else {}
    try:
        return presets_canal.guardar(
            datos.get("tipo"), datos.get("nombre"), datos.get("datos") or {},
            nota=datos.get("nota", ""), miniatura=datos.get("miniatura", ""),
            pid=datos.get("pid") or None)
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)


@router.get("/presets-canal/{prid}", dependencies=[_SESION])
def leer_preset_canal(prid: str) -> dict:
    try:
        return presets_canal.publicar(presets_canal.leer(prid))
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))


@router.put("/presets-canal/{prid}", dependencies=_MUTAR)
def editar_preset_canal(prid: str, cuerpo: dict) -> dict:
    """Cambia nombre/nota, o sustituye el contenido entero con `datos`."""
    datos = cuerpo if isinstance(cuerpo, dict) else {}
    try:
        if datos.get("datos") is not None:
            ficha = presets_canal.leer(prid)
            return presets_canal.guardar(
                ficha.get("tipo"), datos.get("nombre") or ficha.get("nombre"),
                datos.get("datos") or {}, nota=datos.get("nota", ""),
                miniatura=datos.get("miniatura", ""), pid=prid)
        return presets_canal.renombrar(prid, nombre=datos.get("nombre"),
                                       nota=datos.get("nota"))
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)


@router.delete("/presets-canal/{prid}", dependencies=_MUTAR)
def apartar_preset_canal(prid: str) -> dict:
    try:
        return presets_canal.apartar(prid)
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)


@router.post("/presets-canal/{prid}/restaurar", status_code=201,
             dependencies=_MUTAR)
def restaurar_preset_canal(prid: str) -> dict:
    try:
        return presets_canal.restaurar(prid)
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)


@router.get("/presets-canal/{prid}/peso", dependencies=[_SESION])
def peso_preset_canal(prid: str) -> dict:
    """Qué hay dentro de un preset apartado, para decir qué se pierde."""
    try:
        return presets_canal.peso(prid)
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))


@router.delete("/presets-canal/{prid}/papelera", dependencies=_MUTAR)
def borrar_preset_canal(prid: str, confirmar: bool = False) -> dict:
    try:
        return presets_canal.borrar(prid, confirmar=confirmar)
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)


@router.post("/presets-canal/{prid}/aplicar", dependencies=_MUTAR)
def aplicar_preset_canal(prid: str, cuerpo: dict) -> dict:
    """Copia los valores del preset en los params de un proyecto.

    No encadena nada: escribe params (que mueve firmas y MARCA en
    cascada) y devuelve qué pasos quedaron tocados. Quien decide
    regenerar —y pagar— sigue siendo la persona, con el coste delante.
    """
    pid = str((cuerpo or {}).get("proyecto") or "").strip()
    if not pid or not Proyecto(AJUSTES.carpeta_proyectos / pid).existe():
        raise HTTPException(404, "proyecto desconocido")
    try:
        ficha = presets_canal.leer(prid)
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))
    proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
    estado = Estado(proyecto)
    actuales = {paso: estado.paso(paso).get("params", {})
                for paso in _PASOS_PRESET}
    cambios = presets_canal.cambios_para(ficha, actuales)
    for paso, valores in cambios.items():
        estado.actualizar_params(paso, valores)
    devueltas = presets_canal.restaurar_moodboard(ficha)
    proyecto.bitacora("preset_aplicado", {"preset": prid, "tipo": ficha["tipo"],
                                          "pasos": sorted(cambios)})
    return {"preset": presets_canal.publicar(ficha), "cambios": cambios,
            "lamina_devueltas": devueltas,
            "obsoletos": {paso: estado.unidades_obsoletas(paso)
                          for paso in cambios}}


@router.get("/presets-canal/{prid}/miniatura", dependencies=[_SESION])
def miniatura_preset_canal(prid: str):
    """La cara del preset. Sólo sale de SU carpeta: una ruta guardada en
    otra máquina no puede sacar nada de aquí."""
    ruta = presets_canal.ruta_de_miniatura({"id": prid, "miniatura":
                                            "miniatura.png"})
    if not ruta.is_file():
        raise HTTPException(404, "sin miniatura")
    return FileResponse(ruta, media_type="image/png")


@router.get("/presets-canal/{prid}/fichero/{nombre}", dependencies=[_SESION])
def fichero_preset_canal(prid: str, nombre: str):
    """Un fichero propio del preset (las muestras sueltas del modo light).

    El nombre se resuelve DENTRO de la carpeta del preset y rechazando
    `..` y rutas absolutas: lo que viaja en la URL lo escribió el
    navegador y no se da por bueno.
    """
    try:
        ruta = ruta_contenida(presets_canal.carpeta_de(prid), nombre)
    except ValueError:
        raise HTTPException(404, "fichero desconocido")
    if not ruta.is_file() or ruta.parent != presets_canal.carpeta_de(prid):
        raise HTTPException(404, "fichero desconocido")
    return FileResponse(ruta, media_type="image/png")


# ================================================================== modo light
#
# El canal entero se genera en un proyecto TALLER: oculto de la lista
# (campo `taller` en proyecto.json), con el encargo guardado dentro para
# poder rehacer una parte sin volver a pedirlo todo. Al acabar las
# tareas se CONGELA en un preset de tipo canal; el taller se queda
# (rehacer el tono no vuelve a dibujar las láminas) y se borra con el
# preset.

_SISTEMA_TONO = """Eres editor de guiones de un canal de YouTube. Te dan cómo \
quiere contar el canal (su tono, en palabras de quien lo lleva) y escribes \
las INSTRUCCIONES DE TONO que se pegarán en el prompt del redactor de \
guiones.

Qué decide el tono: registro (solemne o de bar), humor (nada, guiños, \
comedia), estructura (datos primero o historia primero), cómo se dirige al \
público (tuteo, usted, nadie), muletillas permitidas y prohibidas, longitud \
de frase.

Reglas:
- Escribe las instrucciones EN EL IDIOMA DEL CANAL.
- ENTRE 80 Y 200 PALABRAS: son instrucciones, no un ensayo.
- CONCRETAS y comprobables («nunca una frase de más de 25 palabras», «cada \
escena abre con un dato») mejor que adjetivos («cercano, divertido»).
- Lo que el canal no haya dicho lo eliges tú, coherente con lo que sí \
dijo, y lo dices.

Devuelve SOLO JSON: {{"tono": "<las instrucciones>", "resumen": "<una línea \
para reconocer el tono en un desplegable>"}}"""


def _pid_libre(base: str) -> str:
    """Un id de taller libre: base legible + sello corto."""
    base = "".join(c for c in base.lower() if c.isalnum() or c == "-")[:24]
    while True:
        pid = f"{base or 'taller'}-{secrets.token_hex(3)}"
        if not (AJUSTES.carpeta_proyectos / pid).exists():
            return pid


def _taller_de(prid: str) -> Proyecto | None:
    """El proyecto taller de un preset light, si aún vive."""
    try:
        ficha = presets_canal.leer(prid)
    except presets_canal.ErrorPreset:
        return None
    tid = str(((ficha.get("datos") or {}).get("origen") or {}).get("taller")
              or "")
    if not tid:
        return None
    proyecto = Proyecto(AJUSTES.carpeta_proyectos / tid)
    return proyecto if proyecto.existe() else None


def _crear_taller(encargo: dict) -> Proyecto:
    """El proyecto oculto donde se genera el preset. -> Proyecto"""
    pid = _pid_libre("taller")
    proyecto = Proyecto(AJUSTES.carpeta_proyectos / pid)
    proyecto.escribir({"id": pid, "nombre": f"Taller · {encargo['nombre']}",
                       "canal": "", "idioma": encargo["idioma"],
                       "creado": ahora(), "actualizado": ahora(),
                       "taller": True, "encargo": encargo})
    estado = Estado(proyecto)
    for paso in ("brief", "guion", "voz", "assets", "callouts"):
        estado.guardar_params(paso, registro.params_defecto_de(paso))
    # el ritmo es lo único que se decide sin generar nada
    for paso, valores in presets_light.params_de_ritmo(encargo["ritmo"]).items():
        estado.actualizar_params(paso, valores)
    # un guion de mentira con la LOCUCCIÓN de las muestras: así «Escuchar»
    # en la tarjeta suena al texto que se ve dibujado, y no a una frase de
    # cata genérica (`p4_voz._texto_de_muestra` lee el guion del proyecto)
    locucion = presets_light.muestras_de_idioma(encargo["idioma"])["locucion"]
    (proyecto.carpeta_paso("guion") / "datos.json").parent.mkdir(
        parents=True, exist_ok=True)
    escribir_json(proyecto.carpeta_paso("guion") / "datos.json",
                  {"escenas": [{"id": "M001", "titulo": "muestra",
                                "narracion": locucion}],
                   "duracion_estimada": 30})
    proyecto.bitacora("taller_creado", {"encargo": encargo["nombre"]})
    return proyecto


def _encargo_de(taller: Proyecto) -> dict:
    return dict(taller.leer().get("encargo") or {})


def _guardar_encargo(taller: Proyecto, encargo: dict) -> None:
    datos = taller.leer()
    datos["encargo"] = encargo
    datos["actualizado"] = ahora()
    taller.escribir(datos)


def _grafismo_de_guia(estilo_prompt: str, guia: dict) -> dict:
    """El set de diseño y los colores fijados, sacados de la guía.

    No llama a ningún modelo: la guía ya trae la paleta CON números y
    el clima del estilo decide la envoltura del texto. La paleta se
    FIJA (y no se deriva en cada vídeo) porque en el modo light no hay
    nadie mirándola vídeo a vídeo: fijarla es lo que hace que el
    preset la repita.
    """
    texto = " ".join(str(estilo_prompt or "").split()).lower()
    if any(p in texto for p in ("neon", "neón", "cyber", "futur")):
        diseno = "pleno"
    elif any(p in texto for p in ("elegan", "serif", "editorial")):
        diseno = "sombra"
    else:
        diseno = "pastilla"

    colores = [c for c in (guia or {}).get("paleta") or []
               if isinstance(c, str) and c.startswith("#") and len(c) == 7]
    fijados: dict = {}
    if colores:
        def luz(hexa):
            return sum(int(hexa[i:i + 2], 16) for i in (1, 3, 5))
        ordenados = sorted(colores, key=luz)
        fijados["fondo"] = ordenados[0]
        fijados["texto"] = ordenados[-1]
        # el acento: el más DISTINTO del fondo y del texto (el del medio
        # de la tabla ordenada por luz, que es donde van los acentos)
        acentos = [c for c in ordenados[1:-1]] or ordenados
        fijados["acento"] = acentos[len(acentos) // 2]
        r, g, b = (int(fijados["fondo"][i:i + 2], 16) for i in (1, 3, 5))
        fijados["velo"] = f"rgba({r},{g},{b},0.78)"
    return {"diseno": diseno, "paleta": {"fijados": fijados}}


def _tarea_guia(taller, estado, encargo, trabajo) -> dict:
    params = estado.paso("assets").get("params", {})
    resultado = guia_estilo.proponer(
        taller, params, trabajo, descripcion=encargo.get("estilo_prompt", ""),
        peticion=(encargo.get("feedback") or {}).get("estilo", ""))
    estado.actualizar_params("assets", {
        "guia": resultado["guia"], "estilo": encargo.get("estilo_prompt", "")})
    return resultado


def _tarea_referencias(taller, estado, encargo, trabajo) -> dict:
    guia = guia_estilo.guia_de(estado.paso("assets").get("params", {}))
    clave = moodboard.clave_de(guia)
    resultado = moodboard.generar(clave, guia, avisar=trabajo.avance,
                                  proyecto_id=taller.id)
    # aprobar mueve la propuesta al banco; si todo estaba ya aprobado no
    # hay propuesta y no hay nada que mover (retomar a medias)
    if (moodboard.raiz_propuestas() / clave).is_dir():
        trabajo.avance("aprobando las referencias dibujadas")
        moodboard.aprobar(clave)
    return moodboard.ficha_de(clave) or resultado


def _tarea_grafismo(taller, estado, encargo, trabajo) -> dict:
    guia = guia_estilo.guia_de(estado.paso("assets").get("params", {}))
    grafismo_params = _grafismo_de_guia(encargo.get("estilo_prompt", ""), guia)
    estado.actualizar_params("callouts", grafismo_params)
    trabajo.avance(f"grafismo: set «{grafismo_params['diseno']}», "
                   f"{len(grafismo_params['paleta']['fijados'])} colores "
                   f"fijados de la guía")
    return grafismo_params


def _tarea_tono(taller, estado, encargo, trabajo) -> dict:
    llamada = llm.rol_config("tono", comun.ajustes_llm())
    llamada.sistema = _SISTEMA_TONO
    llamada.instruccion = (
        f'LO QUE HA PEDIDO EL CANAL, tal cual lo escribió:\n'
        f'"{encargo.get("tono_prompt", "")}"\n\n'
        f'Idioma del canal: {encargo.get("idioma", "es")}.')
    llamada.contexto = "taller:tono"
    llamada.proyecto = taller.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())
    tono = " ".join(str((crudo or {}).get("tono") or "").split())
    if not tono:
        raise ValueError("el modelo no ha devuelto instrucciones de tono")
    resumen = " ".join(str((crudo or {}).get("resumen") or "").split())
    estado.actualizar_params("brief", {"tono": tono})
    if resumen:
        encargo = _encargo_de(taller)
        encargo["tono_resumen"] = resumen
        _guardar_encargo(taller, encargo)
    trabajo.avance(f"tono escrito: {len(tono.split())} palabras de "
                   f"instrucciones")
    return {"tono": tono, "resumen": resumen}


def _tarea_voz(taller, estado, encargo, trabajo) -> dict:
    voz_id = str(encargo.get("voz_id") or "").strip()
    if voz_id:
        # la voz la eligió quien hizo el encargo (lo normal: la clonada
        # del canal): no se elige, sólo se ajustan los mandos al ritmo
        ficha = presets_light.ritmo_de(encargo.get("ritmo"))
        estado.actualizar_params("voz", {
            "voz": voz_id, "modelo": "multilingual",
            "estabilidad": 0.5, "similitud": 0.75,
            "velocidad": ficha["velocidad"]})
        trabajo.avance("voz fijada a mano, mandos ajustados al ritmo")
        return {"voz": voz_id, "voz_nombre": ""}
    encargo_texto = ". ".join(x for x in (
        encargo.get("voz_prompt", ""),
        presets_light.contexto_de_ritmo(encargo.get("ritmo"))) if x)
    propuesta = p4_voz.proponer_voz(taller, encargo_texto,
                                    encargo.get("idioma", "es"), trabajo)
    estado.actualizar_params("voz", {
        k: propuesta[k] for k in ("voz", "modelo", "estabilidad",
                                  "similitud", "velocidad")})
    datos = _encargo_de(taller)
    datos["voz_nombre"] = propuesta.get("voz_nombre", "")
    _guardar_encargo(taller, datos)
    trabajo.avance(f"voz elegida: {propuesta.get('voz_nombre') or 'una voz del catálogo'}")
    return propuesta


def _tarea_muestra(taller, estado, encargo, trabajo) -> dict:
    params_assets = estado.paso("assets").get("params", {})
    params_callouts = estado.paso("callouts").get("params", {})
    guia = guia_estilo.guia_de(params_assets)
    clave = moodboard.clave_de(guia)
    ficha = moodboard.ficha_de(clave)
    laminas = [ruta for eje in ficha.get("ejes", [])
               if (ruta := moodboard.ruta_lamina(clave, eje))]
    destino = taller.ruta("muestras", "miniatura.png")
    resultado = presets_light.componer(
        laminas, destino,
        {"diseno": params_callouts.get("diseno", "pastilla"),
         "paleta": grafismo.paleta_de(
             params_assets.get("estilo", ""),
             (params_callouts.get("paleta") or {}).get("fijados")),
         "subtitulo_tam": params_callouts.get("subtitulo_tam", "normal"),
         "idioma": encargo.get("idioma", "es")},
        semilla=clave)
    trabajo.avance(f"{len(resultado['celdas'])} muestras compuestas")
    return resultado


_TAREAS = {"guia": _tarea_guia, "referencias": _tarea_referencias,
           "grafismo": _tarea_grafismo, "tono": _tarea_tono,
           "voz": _tarea_voz, "muestra": _tarea_muestra}


def _hecha(tid: str, taller, estado, encargo) -> bool:
    """Si la tarea ya tiene su resultado en disco: rehacerla sería pagar
    dos veces lo mismo. Es lo que hace que REANUDAR un taller cortado a
    medias no vuelva a empezar."""
    params = {paso: estado.paso(paso).get("params", {})
              for paso in _PASOS_PRESET}
    if tid == "guia":
        return bool(guia_estilo.guia_de(params["assets"]).get("guia"))
    if tid == "referencias":
        clave = moodboard.clave_de(guia_estilo.guia_de(params["assets"]))
        ficha = moodboard.ficha_de(clave)
        return bool(ficha.get("ejes")) and not ficha.get("pendientes")
    if tid == "grafismo":
        return bool((params["callouts"].get("paleta") or {}).get("fijados"))
    if tid == "tono":
        return bool(params["brief"].get("tono"))
    if tid == "voz":
        defecto = p4_voz.params_defecto()["voz"]
        return (params["voz"].get("voz") not in (None, "", defecto)
                or bool(encargo.get("voz_id")))
    if tid == "muestra":
        return (taller.ruta("muestras", "miniatura.png")).is_file()
    return False


def _correr_tanda(taller, estado, encargo, tanda, trabajo) -> dict:
    """Corre las tareas de una tanda; lo que ya está hecho se salta."""
    resultados, pendientes = {}, []
    for tarea in tanda:
        if _hecha(tarea["id"], taller, estado, encargo):
            trabajo.avance(f"{tarea['nombre']}: ya estaba hecho, no se "
                           f"vuelve a pagar")
            continue
        pendientes.append(tarea)
    if not pendientes:
        return resultados
    if len(pendientes) == 1:
        tarea = pendientes[0]
        trabajo.avance(tarea.get("publico") or tarea["nombre"])
        resultados[tarea["id"]] = _TAREAS[tarea["id"]](
            taller, estado, encargo, trabajo)
        trabajo.comprobar_cancelacion()
        return resultados
    # una tanda corre a la vez, pero cada hilo avanza el MISMO trabajo:
    # los eventos de un Trabajo son una lista con cerrojo del gestor
    with ThreadPoolExecutor(max_workers=len(pendientes)) as pool:
        futuros = {}
        for tarea in pendientes:
            trabajo.avance(tarea.get("publico") or tarea["nombre"])
            futuros[pool.submit(_TAREAS[tarea["id"]], taller, estado,
                                encargo, trabajo)] = tarea
        for futuro in futuros:
            resultados[futuros[futuro]["id"]] = futuro.result()
    trabajo.comprobar_cancelacion()
    return resultados


def _congelar(taller: Proyecto, prid: str | None, encargo: dict) -> dict:
    """El taller se convierte en preset de canal (tipo 'canal')."""
    estado = Estado(taller)
    params_por_paso = {paso: estado.paso(paso).get("params", {})
                       for paso in _PASOS_PRESET}
    # voz_nombre viaja en el encargo del taller (no es un param del paso:
    # meterlo cambiaría la firma sin cambiar lo que suena)
    if encargo.get("voz_nombre"):
        params_por_paso["voz"] = dict(params_por_paso["voz"],
                                      voz_nombre=encargo["voz_nombre"])
    datos = presets_canal.datos_de_params(params_por_paso)
    guia = (datos.get("estilo") or {}).get("guia") or {}
    datos["origen"] = {
        "estilo_prompt": encargo.get("estilo_prompt", ""),
        "tono_prompt": encargo.get("tono_prompt", ""),
        "voz_prompt": encargo.get("voz_prompt", ""),
        "voz_id": encargo.get("voz_id", ""),
        "idioma": encargo.get("idioma", "es"),
        "ritmo": encargo.get("ritmo", presets_light.RITMO_POR_DEFECTO),
        "taller": taller.id,
        "feedback": dict(encargo.get("feedback") or {}),
        "tono_resumen": encargo.get("tono_resumen", ""),
        "estilo_resumen": guia.get("resumen_es", ""),
        "muestras": [nombre for nombre in presets_light.nombres_de_muestra()
                     if (taller.ruta("muestras", nombre)).is_file()],
    }
    return presets_canal.guardar(
        "canal", encargo.get("nombre") or "canal", datos,
        nota=encargo.get("nota", ""),
        miniatura=str(taller.ruta("muestras", "miniatura.png")), pid=prid)


def _correr_taller(taller: Proyecto, prid: str | None, solo=None) -> dict:
    """La función del trabajo: tanda a tanda, congelando al final."""
    def funcion(trabajo):
        encargo = _encargo_de(taller)
        tandas = presets_light.tandas_de(encargo, solo=solo)
        for tanda in tandas:
            trabajo.comprobar_cancelacion()
            _correr_tanda(taller, Estado(taller), encargo, tanda, trabajo)
        ficha = _congelar(taller, prid, encargo)
        trabajo.avance(f"preset guardado: {ficha['nombre']}")
        return {"preset": ficha}
    return funcion


# ------------------------------------------------------------ las rutas light

@router.get("/presets-light", dependencies=[_SESION])
def ficha_light() -> dict:
    """Lo que necesita la pantalla: ritmos, idiomas, plan y la galería."""
    claves = comun.claves_actuales()
    return {
        "ritmos": [presets_light.ficha_de_ritmo(r["id"]) for r in
                   presets_light.RITMOS],
        "ritmo_defecto": presets_light.RITMO_POR_DEFECTO,
        "idiomas": [{"id": i, "nombre": n} for i, n in
                    presets_canal.NOMBRES_IDIOMA.items()],
        "plan": presets_light.plan_de({}),
        "presets": presets_canal.listar()["presets"]["canal"],
        "papelera": presets_canal.listar()["papelera"],
        "hay_glm": bool(claves.get("glm")),
        "hay_elevenlabs": bool(voz_elevenlabs.clave(claves)),
    }


@router.post("/presets-light/plan", dependencies=[_SESION])
def plan_light(cuerpo: dict) -> dict:
    """El plan de un encargo (la barra antes de pulsar)."""
    return presets_light.plan_de((cuerpo or {}).get("encargo") or {})


@router.post("/presets-light", status_code=202, dependencies=_MUTAR)
def crear_light(cuerpo: dict) -> dict:
    """Crea el taller y lanza la generación del canal entero."""
    try:
        encargo = presets_light.validar_encargo((cuerpo or {}).get("encargo"))
    except presets_light.ErrorEncargo as fallo:
        raise _a_400(fallo)
    taller = _crear_taller(encargo)
    funcion = _correr_taller(taller, None)
    trabajo = GESTOR.lanzar(taller.id, "taller", funcion)
    return {"taller": taller.id, "trabajo": GESTOR.estado(trabajo.id)}


@router.get("/presets-light/{prid}", dependencies=[_SESION])
def leer_light(prid: str) -> dict:
    """La ficha de un preset light: encargo, muestras y taller vivo."""
    try:
        ficha = presets_canal.publicar(presets_canal.leer(prid))
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))
    origen = (ficha.get("datos") or {}).get("origen") or {}
    taller = _taller_de(prid)
    muestras = [n for n in (origen.get("muestras") or [])
                if (presets_canal.carpeta_de(prid) / n).is_file()]
    return {"preset": ficha,
            "encargo": {k: origen.get(k, "") for k in
                        ("estilo_prompt", "tono_prompt", "voz_prompt",
                         "voz_id", "idioma", "ritmo", "feedback",
                         "tono_resumen", "estilo_resumen")},
            "muestras": muestras,
            "taller": taller.id if taller else "",
            "activo": GESTOR.activo_de(taller.id) if taller else None}


@router.post("/presets-light/{prid}/regenerar", status_code=202,
             dependencies=_MUTAR)
def regenerar_light(prid: str, cuerpo: dict) -> dict:
    """Rehace UNA de las tres partes (estilo, tono, voz) con feedback."""
    datos = cuerpo if isinstance(cuerpo, dict) else {}
    parte = str(datos.get("parte") or "").strip()
    if parte not in presets_light.PARTES:
        raise _a_400(ValueError(
            "parte desconocida: "
            + ", ".join(presets_light.PARTES)))
    taller = _taller_de(prid)
    if taller is None:
        raise HTTPException(404, "el taller de este preset ya no está: "
                                 "duplica el preset para volver a generarlo")
    encargo = _encargo_de(taller)
    feedback = " ".join(str(datos.get("feedback") or "").split())
    if feedback:
        encargo.setdefault("feedback", {})[parte] = feedback
        _guardar_encargo(taller, encargo)
    trabajo = GESTOR.lanzar(taller.id, "taller",
                            _correr_taller(taller, prid,
                                           solo=presets_light.PARTES[parte]
                                           ["tareas"]))
    return {"trabajo": GESTOR.estado(trabajo.id), "parte": parte}


@router.put("/presets-light/{prid}", dependencies=_MUTAR)
def editar_light(prid: str, cuerpo: dict) -> dict:
    """Ediciones que no son feedback: nombre, idioma, ritmo y voz."""
    datos = cuerpo if isinstance(cuerpo, dict) else {}
    taller = _taller_de(prid)
    if taller is None:
        raise HTTPException(404, "el taller de este preset ya no está")
    try:
        ficha = presets_canal.leer(prid)
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))
    encargo = _encargo_de(taller)
    respuesta: dict = {}

    if datos.get("nombre"):
        presets_canal.renombrar(prid, nombre=datos["nombre"])
        encargo["nombre"] = str(datos["nombre"]).strip()
        _guardar_encargo(taller, encargo)

    nuevo_idioma = str(datos.get("idioma") or "").strip().lower()
    if nuevo_idioma and nuevo_idioma != encargo.get("idioma"):
        anterior = encargo.get("idioma", "es")
        encargo["idioma"] = nuevo_idioma
        _guardar_encargo(taller, encargo)
        datos_proyecto = taller.leer()
        datos_proyecto["idioma"] = nuevo_idioma
        taller.escribir(datos_proyecto)
        respuesta["aviso_idioma"] = presets_light.aviso_de_idioma(
            anterior, nuevo_idioma)
        trabajo = GESTOR.lanzar(
            taller.id, "taller",
            _correr_taller(taller, prid, solo=presets_light.TAREAS_DE_IDIOMA))
        respuesta["trabajo"] = GESTOR.estado(trabajo.id)
        return respuesta

    nuevo_ritmo = str(datos.get("ritmo") or "").strip().lower()
    if nuevo_ritmo and nuevo_ritmo != encargo.get("ritmo"):
        encargo["ritmo"] = presets_light.ritmo_de(nuevo_ritmo)["id"]
        _guardar_encargo(taller, encargo)
        estado = Estado(taller)
        for paso, valores in presets_light.params_de_ritmo(
                encargo["ritmo"]).items():
            estado.actualizar_params(paso, valores)
        respuesta["preset"] = _congelar(taller, prid, encargo)
        return respuesta

    nueva_voz = " ".join(str(datos.get("voz_id") or "").split())
    if nueva_voz and nueva_voz != encargo.get("voz_id"):
        encargo["voz_id"] = nueva_voz
        _guardar_encargo(taller, encargo)
        respuesta["preset"] = _congelar(taller, prid, encargo)
        return respuesta

    if "preset" not in respuesta:
        respuesta["preset"] = presets_canal.publicar(ficha)
    return respuesta


@router.post("/presets-light/{prid}/duplicar", status_code=201,
             dependencies=_MUTAR)
def duplicar_light(prid: str) -> dict:
    """Copia el preset Y su taller: se rehace sin tocar el original."""
    try:
        original = presets_canal.leer(prid)
    except presets_canal.ErrorPreset as fallo:
        raise HTTPException(404, str(fallo))
    origen = (original.get("datos") or {}).get("origen") or {}
    encargo = presets_light.validar_encargo({
        "nombre": f"{original.get('nombre')} (copia)",
        "idioma": origen.get("idioma", "es"),
        "ritmo": origen.get("ritmo", ""),
        "estilo_prompt": origen.get("estilo_prompt", ""),
        "tono_prompt": origen.get("tono_prompt", ""),
        "voz_prompt": origen.get("voz_prompt", ""),
        "voz_id": origen.get("voz_id", ""),
    })
    taller_viejo = _taller_de(prid)
    taller = _crear_taller(encargo)
    if taller_viejo is not None:
        # el taller nuevo nace con lo hecho: copiar el árbol entero es lo
        # que hace que duplicar no vuelva a pagar ni una lámina
        shutil.rmtree(taller.raiz)
        shutil.copytree(taller_viejo.raiz, taller.raiz)
        datos = taller.leer()
        datos.update({"id": taller.id,
                      "nombre": f"Taller · {encargo['nombre']}",
                      "taller": True, "encargo": encargo})
        escribir_json(taller.fichero_proyecto, datos)
    # copiar las muestras al banco del nuevo id las hace _congelar/guardar:
    # con el taller ya hecho, todo sale de disco y no se paga nada
    ficha = _congelar(taller, None, encargo)
    return {"preset": ficha, "taller": taller.id}


@router.delete("/presets-light/{prid}", dependencies=_MUTAR)
def borrar_light(prid: str) -> dict:
    """Aparta el preset y borra su taller: se borran juntos.

    El taller es una pieza del preset (rehacer el tono sin él obligaría
    a rehacerlo todo), y no contiene trabajo que no esté ya en el banco
    de moodboards o en el propio preset.
    """
    try:
        ficha = presets_canal.apartar(prid)
    except presets_canal.ErrorPreset as fallo:
        raise _a_400(fallo)
    taller = _taller_de(prid)
    if taller is not None:
        shutil.rmtree(taller.raiz, ignore_errors=True)
    return ficha


@router.post("/presets-light/{prid}/escucha", dependencies=_MUTAR)
def escucha_light(prid: str) -> dict:
    """Sintetiza la locución de muestra con la voz del preset.

    Se graba en el TALLER con los params que allí quedaron: suena
    exactamente a lo que saldrá en los vídeos de este canal.
    """
    taller = _taller_de(prid)
    if taller is None:
        raise HTTPException(404, "el taller de este preset ya no está")
    estado = Estado(taller)
    params = estado.paso("voz").get("params", {})
    return p4_voz.previsualizar(taller, params, segundos=18)
