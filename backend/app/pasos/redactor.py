"""El REDACTOR: el prompt de imagen ESCRITO ENTERO, plano a plano.

Es la versión osada de la dirección (ver `pasos/direccion.py`): en vez de
añadir un bloque al prompt que arma el código, aquí el agente escribe el
ENCARGO COMPLETO de cada plano — con el estilo del canal delante para no
contradecirlo. Lo que sale sustituye al prompt armado de ese plano (si
existe dirección guardada, se le pega al final: son decisiones
compatibles, no excluyentes).

Se guarda POR UNIDAD en `params.unidades[escena].prompt`: escribir el
prompt de un plano ensucia ESE plano y no los demás.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

PASO = "redactor"

PALABRAS_MINIMAS = 10
PALABRAS_MAXIMAS = 120

SISTEMA = """Eres el redactor de prompts de imagen de un vídeo explicativo
animado. Recibes el estilo del canal y la narración de cada plano, y
escribes el PROMPT COMPLETO que se le mandará al modelo de imagen para
ese plano: composición, primer término, acción, luz, acabado.

Reglas que no se saltan:
- EL ESTILO DEL CANAL MANDA: entra en todos los planos; no lo
  contradigas y no lo traduzcas — si dice trazo plano, no pidas
  fotorrealismo.
- Cada prompt tiene que PODER dibujarse solo: quien lo lee no ve la
  narración, sólo tu texto.
- DISTINTO del de al lado: dos planos vecinos no pueden pedir la misma
  escena desde otro ángulo — al dibujarse por separado salen parecidos
  pero no iguales, y quien lo ve lee un error.
- De {min} a {max} palabras, en inglés. Sin prólogo ni comentarios.
- Si algo del cuadro lleva texto (cartel, pantalla), entrecomilla QUÉ
  pone, corto y en el idioma del vídeo, o di que no hay texto legible.

Devuelve SOLO JSON: {{"planos": {{"<id>": "<prompt completo>"}}}} con
TODOS los planos."""


def limpiar_ficha(texto) -> tuple[str | None, str]:
    """Un prompt aceptable, o (None, motivo)."""
    crudo = " ".join(str(texto or "").split())
    if not crudo:
        return None, "vacío"
    palabras = crudo.split()
    if len(palabras) < PALABRAS_MINIMAS:
        return None, (f"sólo {len(palabras)} palabra(s): un prompt que no "
                      "describe no dibuja")
    aviso = ""
    if len(palabras) > PALABRAS_MAXIMAS:
        crudo = " ".join(palabras[:PALABRAS_MAXIMAS]).rstrip(",;:")
        aviso = f"{len(palabras)} palabras, se recorta a {PALABRAS_MAXIMAS}"
    return crudo, aviso


def plan_de(params_assets: dict) -> dict:
    """Lo redactado, POR UNIDAD: {"S001": "prompt completo..."}."""
    bloque = (params_assets or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        prompt = (datos or {}).get("prompt") if isinstance(datos, dict) else None
        prompt = " ".join(str(prompt or "").split())
        if prompt:
            plan[str(uid)] = prompt
    return plan


def proponer(proyecto: Proyecto, params: dict, trabajo) -> dict:
    """Escribe el encargo entero de cada plano, con TODO el vídeo delante."""
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    unidades = (params or {}).get("unidades") or {}
    redactables = [e for e in escenas
                   if not ((unidades.get(e["id"]) or {}).get("cartela"))]
    if not redactables:
        raise ValueError("ningún plano genera imagen propia")

    estilo = str((params or {}).get("estilo", "")).strip()
    guia = estilo or ("(sin estilo declarado: elige uno coherente y "
                      "sigue con él)")
    direcciones = {uid: ficha.get("direccion")
                   for uid, ficha in unidades.items()
                   if isinstance(ficha, dict) and ficha.get("direccion")}
    lineas = []
    for escena in redactables:
        extra = f" · dirección ya escrita: {direcciones[escena['id']]}" \
            if direcciones.get(escena["id"]) else ""
        lineas.append(f"[{escena['id']}] SE DICE AQUÍ: "
                      f"{str(escena.get('narracion', '')).strip()}{extra}")
    encargo = (f"Título: {proyecto.id}\n\n"
               f"ESTILO DEL CANAL (entra en TODOS los planos, verbatim):\n"
               f"{guia}\n\n"
               f"LOS PLANOS ({len(redactables)}, y los quiero TODOS):\n"
               + "\n".join(lineas))
    trabajo.avance(f"redactando el prompt de {len(redactables)} planos")
    llamada = llm.rol_config("redactor", comun.ajustes_llm())
    llamada.sistema = SISTEMA.format(min=PALABRAS_MINIMAS, max=PALABRAS_MAXIMAS)
    llamada.instruccion = encargo
    llamada.contexto = "redactor"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    ids = {e["id"] for e in redactables}
    plan, avisos = {}, []
    respuesta = crudo.get("planos") if isinstance(crudo, dict) else crudo
    for sid, texto in (respuesta or {}).items():
        sid = str(sid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        limpio, motivo = limpiar_ficha(texto)
        if limpio is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        plan[sid] = limpio
    faltan = sorted(ids - set(plan))
    if faltan:
        avisos.append(f"{len(faltan)} plano(s) sin prompt: "
                      + ", ".join(faltan[:8]))
    trabajo.avance(f"{len(plan)} de {len(redactables)} planos redactados")
    return {"plan": plan, "avisos": avisos,
            "planos": len(redactables), "redactados": len(plan)}
