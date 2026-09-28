"""QUÉ CLASE DE PLANO es cada uno: la escalera de cartas y su reparto.

Réplica del original (`pasos/encuadres.py`): una "carta" es una clase de
encuadre — una vista aérea, un detalle macro, una silueta a contraluz —,
y decidirlo ANTES de pedirle la imagen al modelo es lo que produce
ritmo: pedirle «haz un plano distinto» devuelve el mismo plano medio
con otras palabras.

Cada carta lleva su `encuadre` en inglés, que entra en el prompt del
plano como SHOT TYPE obligatorio. Los ids, familias, pesos y orden son
los MISMOS que en el original a propósito: el reparto es determinista y
la imagen de un plano se cachea por su prompt, así que cambiar la
escalera le cambiaría la carta a planos que narran lo mismo — y eso se
paga en imágenes.
"""
from __future__ import annotations

import hashlib

#: Las clases de plano que se van alternando.
#:
#: 'familia' impide que dos planos seguidos miren el mundo igual; 'peso'
#: inclina el reparto sin cerrarlo (un documental es sobre todo gente y
#: sitios); 'abstracta' marca las que no ocurren en ningún sitio físico.
ESCALERA = (
    {"id": "aereo", "familia": "lejos", "peso": 2, "nombre": "vista aérea",
     "encuadre": ("a high aerial bird's-eye shot looking steeply down on the "
                  "scene from far above, wide angle, the whole layout visible "
                  "and the people small within it")},

    {"id": "general", "familia": "lejos", "peso": 3, "nombre": "plano general",
     "encuadre": ("a wide establishing shot from far back, the figures small "
                  "inside a large space, plenty of air above and around them")},

    {"id": "contrapicado", "familia": "angulo", "peso": 2,
     "nombre": "contrapicado extremo",
     "encuadre": ("an extreme low-angle shot from near the floor tilted sharply "
                  "up, towering vertical lines, the subject looming over the "
                  "viewer")},

    {"id": "cenital", "familia": "angulo", "peso": 2, "nombre": "cenital",
     "encuadre": ("a top-down overhead shot looking straight down on the surface "
                  "below, the objects arranged flat within the frame")},

    {"id": "detalle", "familia": "cerca", "peso": 3, "nombre": "detalle macro",
     "encuadre": ("an extreme close-up of one single object filling the frame, "
                  "shallow depth, everything behind it out of focus and abstract")},

    {"id": "retrato", "familia": "cerca", "peso": 3, "nombre": "retrato cerrado",
     "encuadre": ("a tight close-up portrait of the face and shoulders, long "
                  "lens, the background simple and far behind")},

    {"id": "hombro", "familia": "medio", "peso": 2, "nombre": "sobre el hombro",
     "encuadre": ("an over-the-shoulder shot, the back and shoulder of one "
                  "figure large and dark on one side of the frame, the subject "
                  "of their attention beyond")},

    {"id": "silueta", "familia": "luz", "peso": 2,
     "nombre": "silueta a contraluz",
     "encuadre": ("a backlit silhouette shot: the figure is a dark shape against "
                  "a large bright opening behind, almost no detail on the figure "
                  "itself")},

    {"id": "entre", "familia": "luz", "peso": 2,
     "nombre": "mirando entre las cosas",
     "encuadre": ("a shot framed through a gap: something in the immediate "
                  "foreground partly blocks the view from the edges, the subject "
                  "seen through the opening between")},

    {"id": "perfil", "familia": "medio", "peso": 2, "nombre": "perfil lateral",
     "encuadre": ("a flat side-on profile shot, the subject seen exactly from "
                  "the side against a background parallel to the frame, almost "
                  "graphic")},

    {"id": "suelo", "familia": "angulo", "peso": 1, "nombre": "a ras de suelo",
     "encuadre": ("a ground-level shot with the camera resting on the floor, the "
                  "floor filling the lower half of the frame, everything seen "
                  "from below")},

    {"id": "hueco", "familia": "lejos", "peso": 1, "nombre": "el sitio vacío",
     "encuadre": ("an empty establishing shot of the place with no people in it "
                  "at all, still and quiet, the traces of what happened left "
                  "behind")},

    {"id": "diagrama", "familia": "abstracta", "peso": 2, "abstracta": True,
     "nombre": "diagrama",
     "encuadre": ("a clean explanatory diagram filling the frame: simple flat "
                  "shapes, thick arrows and short labels laid out on a plain "
                  "graphic background, the idea drawn as a chart rather than a "
                  "place, with small stick figures integrated as part of the "
                  "diagram")},

    {"id": "pantalla", "familia": "abstracta", "peso": 2, "abstracta": True,
     "nombre": "pantalla",
     "encuadre": ("a full-frame computer screen taking up the entire image: "
                  "terminal windows, scrolling code, progress bars and blinking "
                  "cursors drawn flat in the video's own style, slightly angled "
                  "as if glowing in a dark room, no visible person unless the "
                  "scene names one")},

    {"id": "eterea", "familia": "abstracta", "peso": 1, "abstracta": True,
     "nombre": "composición etérea",
     "encuadre": ("an abstract conceptual composition floating on an empty "
                  "backdrop: the subject suspended in space among drifting "
                  "symbolic elements, no floor, no walls, no horizon, a visual "
                  "metaphor of the idea rather than a scene")},
)

POR_ID = {carta["id"]: carta for carta in ESCALERA}

#: Cuántos planos hacia atrás se mira para no repetir FAMILIA. Regla dura.
#: Dos y no uno: con uno, aereo-retrato-general pasa el filtro y el
#: espectador ve dos planos lejanos separados por uno cercano.
VENTANA_FAMILIA = 2

#: Y cuántos para no repetir la MISMA carta. Preferencia, no regla: con
#: quince cartas y vídeos de cuarenta y ocho planos, exigirlo dejaría sin
#: candidatos.
VENTANA_CARTA = 5


def catalogo() -> list[dict]:
    """La escalera para la pantalla: id, nombre, familia y peso."""
    return [{"id": c["id"], "nombre": c["nombre"], "familia": c["familia"],
             "peso": c["peso"], "abstracta": bool(c.get("abstracta"))}
            for c in ESCALERA]


def _desempatar(semilla, sid) -> int:
    """Arranque estable: el mismo plano narra lo mismo en cada pasada."""
    texto = f"{semilla}|{sid}|carta"
    return int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8], 16)


def _repartidas() -> list[dict]:
    """La escalera expandida por peso, que es sobre lo que se reparte."""
    expandida = []
    for carta in ESCALERA:
        expandida.extend([carta] * max(1, int(carta.get("peso") or 1)))
    return expandida


def carta_de(sid: str, previas=(), semilla: str = "", forzada: str = "") -> dict:
    """Qué clase de plano es este. Determinista, y nunca la familia de al lado.

    'forzada' es el id que haya pedido una persona para ESE plano (el
    select de la tarjeta), y manda sobre todo lo demás: una decisión
    tomada mirando el vídeo no se rebate sola.
    """
    if forzada and forzada in POR_ID:
        return POR_ID[forzada]
    previas = [str(p) for p in (previas or [])]
    vetadas = {(POR_ID.get(p) or {}).get("familia")
               for p in previas[-VENTANA_FAMILIA:]}
    vetadas.discard(None)
    recientes = set(previas[-VENTANA_CARTA:])
    fondo = _repartidas()
    arranque = _desempatar(semilla, sid) % len(fondo)
    orden = [fondo[(arranque + i) % len(fondo)] for i in range(len(fondo))]
    libres = [c for c in orden if c["familia"] not in vetadas]
    if not libres:
        return orden[0]
    frescas = [c for c in libres if c["id"] not in recientes]
    return (frescas or libres)[0]


def repartir(escenas, semilla: str = "", forzadas: dict | None = None) -> dict:
    """Una carta por plano, en orden y con las dos reglas puestas.

    Va aparte de `carta_de` porque el reparto depende del ORDEN — cada
    plano mira los que tiene delante —, y eso es una decisión del
    conjunto. -> {sid: carta}
    """
    forzadas = forzadas or {}
    cartas, previas = {}, []
    for escena in escenas or []:
        sid = escena.get("id")
        if not sid:
            continue
        carta = carta_de(sid, previas, semilla, str(forzadas.get(sid, "")))
        cartas[sid] = carta
        previas.append(carta["id"])
    return cartas
