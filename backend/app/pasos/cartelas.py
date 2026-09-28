"""Las CARTELAS: un plano de TEXTO en vez de una imagen pagada.

Vive con ASSETS y no con los rótulos aunque sea grafismo, y el motivo es
el dinero (regla heredada del original): una cartela cambia el PLAN —ese
plano deja de generar imagen—, así que tiene que estar decidida ANTES de
generar. Decidirla después sería pagar una imagen para tirarla.

El plan se guarda POR UNIDAD (`params.unidades[escena].cartela`) porque
todo lo que no es ese bloque entra en la firma global del paso: convertir
S003 en cartela ensucia S003 y nada más.
"""
from __future__ import annotations

from ..nucleo import grafismo
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

#: Ninguna cartela a menos de estos segundos de la anterior: un vídeo
#: que es todo rótulo no necesita dibujos, y uno que los amontona no se lee.
SEPARACION_MINIMA = 2.0

#: Una cartela no puede quedarse más del 15 % del vídeo: si no cabe, ese
#: tramo se cuenta con dibujo.
FRACCION_MAXIMA = 0.15

#: Palabras por segundo que se leen de una cartela en pantalla.
PALABRAS_POR_SEGUNDO = 2.5

SISTEMA = """Decides qué tramos de un vídeo explicativo se cuentan mejor
con una CARTELA —un plano de texto sobre fondo propio— que con un dibujo.

Cuándo una cartela GANA: un dato que hay que leer despacio (una cifra, un
porcentaje), un cambio de capítulo, una cita textual, el cierre. Cuándo
PIERDE: cualquier cosa que se pueda enseñar (una acción, un lugar, una
cara) — eso va dibujado, no escrito.

Reglas:
- Pocas: {max_cartelas} como mucho en un vídeo de {planos} planos. Una
  cartela cada dos planos es un PowerPoint.
- Nunca dos seguidas.
- El texto es CORTO (se lee de un vistazo) y va en el idioma del vídeo.
- Elige plantilla entre: {plantillas}.
- Si un plano no gana con cartela, no lo incluyas.

Devuelve SOLO JSON: {{"cartelas": {{"<id de plano>": {{"plantilla": str,
"datos": {{...}}, "por_que": str}}}}}} — `datos` según la plantilla."""


def params_defecto() -> dict:
    return {}


def palabras_que_caben(duracion) -> int:
    """Cuántas palabras caben en un plano de esa duración, con la MISMA
    cuenta que decide si la cartela cabe."""
    try:
        return max(2, int(float(duracion or 0) * PALABRAS_POR_SEGUNDO))
    except (TypeError, ValueError):
        return 6


def validar(plantilla: str, datos) -> tuple[dict | None, list[str]]:
    """Una ficha de cartela aceptable, o (None, avisos)."""
    if plantilla not in grafismo.PLANTILLAS_CARTELA:
        return None, [f"plantilla desconocida: {plantilla}. Las que hay: "
                      + ", ".join(grafismo.PLANTILLAS_CARTELA)]
    ficha = grafismo.PLANTILLAS_CARTELA[plantilla]
    datos = datos if isinstance(datos, dict) else {}
    limpio, avisos = {}, []
    for campo in ficha["campos"]:
        valor = " ".join(str(datos.get(campo, "")).split())
        if not valor and campo == ficha["campos"][0]:
            return None, [f"falta '{campo}': una cartela sin texto no "
                          "dice nada"]
        limpio[campo] = valor
    return limpio, avisos


def plan_de(params_assets: dict) -> dict:
    """Las cartelas guardadas, POR UNIDAD: {"S003": {plantilla, datos...}}."""
    bloque = (params_assets or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        ficha = (datos or {}).get("cartela") if isinstance(datos, dict) else None
        if isinstance(ficha, dict) and ficha.get("plantilla"):
            plan[str(uid)] = ficha
    return plan


def proponer(proyecto: Proyecto, params: dict, trabajo) -> dict:
    """Lee el guion y decide qué tramos se cuentan mejor con texto.

    Proponer no es aprobar: lo que devuelve se repasa y se guarda con PUT
    /cartelas (o se aplica desde la receta con aplicar=True).
    """
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    duraciones = {v.get("id"): v.get("duracion")
                  for v in (voz or {}).get("escenas", [])}
    # EL IDIOMA VA EXPLÍCITO (regla del original): sin decirselo, el
    # agente escribe las cartelas en el idioma de su propio ejemplo.
    idioma = {"es": "español", "en": "inglés"}.get(
        str(proyecto.leer().get("idioma", "es")).lower(), "español")
    max_cartelas = max(1, round(len(escenas) * FRACCION_MAXIMA))
    lista = "\n".join(
        f"[{e['id']}] ({round(float(duraciones.get(e['id'], 0) or 0), 1)} s) "
        f"{str(e.get('narracion', '')).strip()}"
        for e in escenas)
    catalogo = "; ".join(
        f"{pid} ({ficha['nombre']}: campos {', '.join(ficha['campos'])})"
        for pid, ficha in grafismo.PLANTILLAS_CARTELA.items())
    trabajo.avance("decidiendo qué tramos van mejor como cartela")
    llamada = llm.rol_config("cartelas", comun.ajustes_llm())
    llamada.sistema = SISTEMA.format(max_cartelas=max_cartelas,
                                     planos=len(escenas),
                                     plantillas=catalogo)
    llamada.instruccion = (f"Vídeo: {proyecto.id} (idioma: {idioma})\n\n"
                           f"LOS PLANOS con su duración real:\n{lista}")
    llamada.contexto = "cartelas"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    ids = {e["id"] for e in escenas}
    plan, avisos = {}, []
    respuesta = crudo.get("cartelas") if isinstance(crudo, dict) else crudo
    for sid, ficha in (respuesta or {}).items():
        sid = str(sid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        if not isinstance(ficha, dict):
            avisos.append(f"{sid}: no trae ficha, se ignora")
            continue
        valores, motivos = validar(str(ficha.get("plantilla", "")),
                                   ficha.get("datos"))
        if valores is None:
            avisos.append(f"{sid}: {'; '.join(motivos)}")
            continue
        avisos.extend(f"{sid}: {m}" for m in motivos)
        texto = " ".join(str(v) for v in valores.values())
        caben = palabras_que_caben(duraciones.get(sid))
        palabras_texto = len(texto.split())
        if palabras_texto > caben:
            segundos = round(float(duraciones.get(sid, 0) or 0), 1)
            avisos.append(f"{sid}: {palabras_texto} palabras y caben "
                          f"{caben} en {segundos} s")
        plan[sid] = {"plantilla": str(ficha.get("plantilla", "")),
                     "datos": valores,
                     "por_que": str(ficha.get("por_que", "")).strip()}
    # ninguna dos veces seguidas: la regla que el modelo más rompe
    orden = [e["id"] for e in escenas]
    seguidas = [orden[i] for i in range(1, len(orden))
                if orden[i] in plan and orden[i - 1] in plan]
    if seguidas:
        avisos.append("dos cartelas seguidas: " + ", ".join(seguidas))
    trabajo.avance(f"{len(plan)} de {len(escenas)} planos serían cartela")
    return {"plan": plan, "avisos": avisos,
            "planos": len(escenas), "cartelas": len(plan),
            "max_cartelas": max_cartelas}
