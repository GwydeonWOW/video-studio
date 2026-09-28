"""QUÉ SE VE EN ESTE PLANO, y no en el de al lado.

Adaptado del original (`pasos/direccion.py`): el prompt de imagen de dos
planos vecinos saleía casi idéntico porque se armaba con piezas que son
del TRAMO (estilo, frase). Falta la capa que dice qué hay en el cuadro
AHORA: qué manda el primer término, qué hace cada uno, qué está
mostrando esa pantalla.

Diferencias con el original, honestas con esta réplica: aquí no hay
catálogo de sitios ni reparto (eso vive en otra fase), así que el agente
recibe el estilo del canal, la narración de cada plano y la dirección de
los vecinos — el trabajo de DISTINGUIR un plano del de al lado es el
mismo, la continuidad de sitio se apoya sólo en lo escrito.

Se guarda POR UNIDAD (params.unidades de assets): escribir la dirección
de un plano ensucia ESE plano y no los demás — ver `estado.firma_de`,
que ignora el bloque `unidades`.
"""
from __future__ import annotations

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

PASO = "direccion"

#: El tope existe para que el bloque no acabe describiendo el sitio otra
#: vez con otras palabras (que es como se contradice). Se recorta por
#: PALABRAS enteras, nunca a media.
PALABRAS_MAXIMAS = 60
PALABRAS_MINIMAS = 5

SISTEMA = """Eres el director de fotografía de un vídeo explicativo animado.
El vídeo ya está cortado en planos con su frase de narración decidida; lo
que falta —y es lo único que escribes tú— es QUÉ SE VE EN CADA PLANO.

Reglas que no se saltan:
- Lo que escribes entra en el prompt de la imagen junto al estilo del
  canal y la frase narrada: NO los repitas y no los contradigas.
- DISTINTO DEL DE AL LADO, que es para lo que existe esto: ves todos los
  planos a la vez precisamente para no repetirte. Dos planos vecinos
  tienen que cambiar de verdad: otro primer término, otro objeto
  mandando, otro momento.
- NO REPITAS LA NARRACIÓN: esa frase ya viaja al modelo. Tú dices lo que
  se VE mientras se oye.
- Ni una letra que no hayas pedido: si algo del cuadro podría llevar
  texto (pantalla, cartel, portada), di QUÉ pone entre comillas —corto,
  grande, en el idioma del vídeo— o di que no pone nada legible.
- Si sale gente, acaba la línea con su tono entre paréntesis, uno de
  estos: (TONO: alegre) (TONO: neutro) (TONO: tenso) (TONO: triste)
  (TONO: solemne). Siempre que salga alguien, sin excepción.

Devuelve SOLO JSON: {"planos": {"<id>": "<qué pasa en ese plano, en
inglés>"}} con TODOS los planos, ninguno de más ni de menos."""


def limpiar_linea(texto) -> tuple[str | None, str]:
    """Una dirección aceptable, o (None, motivo). Recorta por palabras."""
    crudo = " ".join(str(texto or "").split())
    if not crudo:
        return None, "vacía"
    palabras = crudo.split()
    if len(palabras) < PALABRAS_MINIMAS:
        return None, (f"sólo {len(palabras)} palabra(s): no dice nada "
                      "que dibujar")
    aviso = ""
    if len(palabras) > PALABRAS_MAXIMAS:
        crudo = " ".join(palabras[:PALABRAS_MAXIMAS]).rstrip(",;:")
        aviso = (f"{len(palabras)} palabras, se recorta a "
                 f"{PALABRAS_MAXIMAS}")
    return crudo, aviso


def _normalizar(texto: str) -> str:
    return " ".join(str(texto or "").lower().split())


def repetidas(plan: dict, escenas: list[dict]) -> list[list[str]]:
    """Direcciones IGUALES entre planos: el fallo que esto viene a quitar."""
    por_texto: dict[str, list[str]] = {}
    for escena in escenas or []:
        linea = (plan or {}).get(escena.get("id"))
        if linea:
            por_texto.setdefault(_normalizar(linea), []).append(escena["id"])
    return sorted(ids for ids in por_texto.values() if len(ids) > 1)


_TONOS = ("alegre", "neutro", "tenso", "triste", "solemne")


def sin_tono(plan: dict, escenas: list[dict]) -> list[str]:
    """Planos que mencionan gente sin declarar su tono."""
    import re
    flojos = []
    patron = re.compile(r"\(\s*TONO\s*:\s*([a-záéíóú]+)\s*\)", re.I)
    for escena in escenas or []:
        linea = str((plan or {}).get(escena.get("id")) or "")
        if not linea:
            continue
        # en esta réplica no hay reparto: se mira si la línea habla de gente
        menciona = any(p in linea.lower()
                       for p in ("man ", "woman ", "men,", "women", "people",
                                 "person", "girl", "boy", "family", "worker",
                                 "crowd", "child", "cliente", "hand"))
        if not menciona:
            continue
        casa = patron.search(linea)
        if not casa or casa.group(1).strip().lower() not in _TONOS:
            flojos.append(escena["id"])
    return flojos


def plan_de(params_assets: dict) -> dict:
    """Lo dirigido, POR UNIDAD: {"S001": "a hand covers the screen"}."""
    bloque = (params_assets or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        linea = (datos or {}).get("direccion") if isinstance(datos, dict) else None
        linea = " ".join(str(linea or "").split())
        if linea:
            plan[str(uid)] = linea
    return plan


def proponer(proyecto: Proyecto, params: dict, trabajo) -> dict:
    """Escribe qué se ve en cada plano, de una vez y con todos delante.

    NO escribe en params: propone. Lo que se guarda después es la
    DECISION (PUT /direccion), igual que en el original.
    """
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    # las cartelas no se ruedan: fuera de la lista del agente
    unidades = (params or {}).get("unidades") or {}
    dirigibles = [e for e in escenas
                  if not ((unidades.get(e["id"]) or {}).get("cartela"))]
    if not dirigibles:
        raise ValueError("ningún plano genera imagen propia: no hay nada "
                         "que dirigir")

    estilo = str((params or {}).get("estilo", "")).strip()
    lineas = []
    for escena in dirigibles:
        lineas.append(
            f"[{escena['id']}] SE DICE AQUÍ: "
            f"{str(escena.get('narracion', '')).strip()}")
    lista = "\n".join(lineas)
    encargo = (f"Título: {proyecto.id}\n\n"
               f"ESTILO DEL CANAL (no lo repitas, no lo contradigas):\n"
               f"{estilo or '(sin estilo declarado)'}\n\n"
               f"LOS PLANOS ({len(dirigibles)}, y los quiero TODOS):\n"
               f"{lista}")
    trabajo.avance(f"dirigiendo {len(dirigibles)} planos de una vez")
    llamada = llm.rol_config("direccion", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = encargo
    llamada.contexto = "direccion"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    ids = {e["id"] for e in dirigibles}
    plan, avisos = {}, []
    respuesta = crudo.get("planos") if isinstance(crudo, dict) else crudo
    for sid, texto in (respuesta or {}).items():
        sid = str(sid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este vídeo, se ignora")
            continue
        linea, motivo = limpiar_linea(texto)
        if linea is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        plan[sid] = linea
    faltan = sorted(ids - set(plan))
    if faltan:
        avisos.append(f"{len(faltan)} plano(s) sin dirección: "
                      + ", ".join(faltan[:8]))
    for grupo in repetidas(plan, dirigibles):
        avisos.append(f"{' = '.join(grupo)}: misma dirección en varios "
                      "planos, que es justo lo que esto viene a quitar")
    mudos = sin_tono(plan, dirigibles)
    if mudos:
        avisos.append(f"{len(mudos)} plano(s) con gente no declaran su tono: "
                      + ", ".join(mudos[:8]))
    trabajo.avance(f"{len(plan)} de {len(dirigibles)} planos dirigidos")
    return {"plan": plan, "avisos": avisos,
            "planos": len(dirigibles), "dirigidos": len(plan)}
