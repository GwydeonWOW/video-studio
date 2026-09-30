"""El GRAFISMO del vídeo: sets de diseño, paleta y cartelas dibujadas.

UN vídeo tiene UN grafismo. El mismo set decide cómo se envuelve un rótulo
sobre la imagen y cómo se escribe una cartela, y la misma paleta tiñe los
dos. Vive en los params de CALLOUTS porque cambiarlo no cuesta imágenes:
rehace capas y render, nada más (la regla del original).

Aquí viven sólo los DATOS y el dibujo (SVG/PNG de andar por casa, sin
dependencias): qué sets hay, qué plantillas de cartela existen, cómo se
deriva la paleta del estilo del canal y cómo se pinta cada pieza. Las
rutas y los pasos llaman a esto; nada de esto llama afuera.
"""
from __future__ import annotations

ANCHO, ALTO = 1920, 1080

#: Tamaños del rótulo/subtítulo: lo único que queda por elegir a mano.
SUB_TAMANOS = {"pequeno": 0.8, "normal": 1.0, "grande": 1.3}

#: Sets de diseño del rótulo. `caja` decide la envoltura; los colores
#: vienen de la paleta (derivada del estilo o fijada a mano).
SETS_DISENO = {
    "pastilla": {
        "nombre": "Pastilla",
        "descripcion": "texto claro sobre pastilla oscura redondeada",
        "caja": "pastilla",
    },
    "barra": {
        "nombre": "Barra de acento",
        "descripcion": "barra del color de acento a la izquierda del texto",
        "caja": "barra",
    },
    "pleno": {
        "nombre": "Banda plena",
        "descripcion": "banda del ancho entero al pie del cuadro",
        "caja": "pleno",
    },
    "sombra": {
        "nombre": "Aire",
        "descripcion": "sin caja: texto claro con sombra suave",
        "caja": "sombra",
    },
}

#: Las plantillas de CARTELA ya no viven aquí: son un motor propio
#: (`pasos/cartelas.py`) con sus cuentas de anclaje con la voz. Lo que
#: queda en grafismo es el rótulo — el texto que va ENCIMA de una
#: imagen, que no necesita buscarle hueco a nada.

#: Paleta por defecto: la de una pantalla oscura de vídeo explicativo.
PALETA_DEFECTO = {"acento": "#eab308", "texto": "#f8fafc",
                  "fondo": "#0b0e13", "velo": "rgba(10,12,16,0.78)"}

#: Palabras del estilo gráfico que mueven el acento. Es una derivación
#: humilde (no una decisión de diseño): si el canal dice neón, el acento
#: no puede ser ámbar de documento serio.
_ACENTOS_POR_CLIMA = [
    (("neon", "neón", "cyber", "futur"), "#22d3ee"),
    (("natural", "acua", "agua", "acuarela", "orgánic", "organic"), "#34d399"),
    (("elegan", "serif", "clásic", "clasic", "editorial"), "#c084fc"),
    (("cálid", "calid", "vintage", "retro", "añadid", "analog"), "#fb923c"),
    (("serio", "técnic", "tecnic", "corporativ", "finanz"), "#60a5fa"),
]


def paleta_de(estilo_grafico: str, fijados: dict | None = None) -> dict:
    """La paleta del vídeo: derivada del estilo, con lo manual MANDANDO.

    Lo que alguien fijó a mano va aparte y se aplica al final: volver a
    derivar (porque el estilo cambió) nunca se lleva por delante una
    decisión de persona.
    """
    paleta = dict(PALETA_DEFECTO)
    texto = str(estilo_grafico or "").lower()
    for pistas, acento in _ACENTOS_POR_CLIMA:
        if any(pista in texto for pista in pistas):
            paleta["acento"] = acento
            break
    for papel, color in (fijados or {}).items():
        if papel in paleta and str(color or "").strip():
            paleta[papel] = str(color).strip()
    return paleta


def tamano_de(subtitulo_tam: str) -> float:
    return SUB_TAMANOS.get(str(subtitulo_tam or "normal").lower(), 1.0)


def con_opacidad(paleta: dict, valor) -> dict:
    """La paleta con el VELO a otra alfa (0..1): cuánto tapa la caja.

    `valor` puede ser numero (0.6) o la palabra "auto" (o cualquiera
    rara): se devuelve la paleta TAL CUAL, que es la alfa que trae el
    velo derivado del estilo. Es el mando `subtitulo_caja` de callouts.
    """
    paleta = dict(paleta or PALETA_DEFECTO)
    try:
        alfa = min(1.0, max(0.0, float(valor)))
    except (TypeError, ValueError):
        return paleta
    velo = str(paleta.get("velo", "")).strip()
    if velo.lower().startswith("rgba") and ")" in velo:
        rgb = velo[velo.find("(") + 1:velo.rfind(")")].rsplit(",", 1)[0].strip()
    else:
        rgb = "10,12,16"
    paleta["velo"] = f"rgba({rgb},{round(alfa, 3)})"
    return paleta


# ----------------------------------------------------------------- dibujo

def _escapar(texto: str) -> str:
    return (str(texto or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def svg_rotulo(texto: str, diseno: str = "pastilla", paleta: dict | None = None,
               tam: float = 1.0, ancho: int = 1600) -> str:
    """El rótulo como SVG: la MISMA pieza que dibuja el render, en vector.

    La pantalla la pide en vez de leer un PNG para que enseñe exactamente
    lo que va a salir — cambiar un color y no verlo sería una pantalla que
    miente.
    """
    paleta = paleta or dict(PALETA_DEFECTO)
    caja = SETS_DISENO.get(diseno, SETS_DISENO["pastilla"])["caja"]
    fuente = 46 * tamano_de(tam)
    etiqueta = _escapar(texto)
    ancho_texto = min(ancho - 160, 26 * len(etiqueta) * tamano_de(tam) * 0.62)
    alto = fuente + 56
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" '
              f'height="{alto}" viewBox="0 0 {ancho} {alto}">']
    x0 = (ancho - ancho_texto) / 2
    y_texto = alto / 2 + fuente * 0.35
    if caja == "pastilla":
        partes.append(
            f'<rect x="{x0 - 28}" y="8" width="{ancho_texto + 56}" '
            f'height="{alto - 16}" rx="18" fill="{paleta["velo"]}"/>')
    elif caja == "barra":
        partes.append(
            f'<rect x="{x0 - 28}" y="8" width="8" height="{alto - 16}" '
            f'fill="{paleta["acento"]}"/>')
    elif caja == "pleno":
        partes.append(
            f'<rect x="0" y="0" width="{ancho}" height="{alto}" '
            f'fill="{paleta["velo"]}"/>'
            f'<rect x="0" y="0" width="14" height="{alto}" '
            f'fill="{paleta["acento"]}"/>')
    else:  # sombra
        partes.append(
            f'<filter id="s"><feDropShadow dx="0" dy="2" stdDeviation="4" '
            f'flood-opacity="0.7"/></filter>')
    filtro = ' filter="url(#s)"' if caja == "sombra" else ""
    partes.append(
        f'<text x="{ancho / 2}" y="{y_texto}" text-anchor="middle"'
        f'{filtro} font-family="Arial, Helvetica, sans-serif" '
        f'font-weight="700" font-size="{fuente:.0f}" fill="{paleta["texto"]}">'
        f"{etiqueta}</text></svg>")
    return "".join(partes)


def svg_subtitulo(texto: str, diseno: str = "pastilla",
                  paleta: dict | None = None, tam: float = 1.0,
                  ancho: int = 1600, cap_linea: int = 38) -> str:
    """Un TROZO de subtítulo como SVG: lo MISMO que dibuja el render.

    La caja es UNA por trozo (dos cajas de anchos distintos apiladas
    dibujan un escalón) y las líneas salen PAREJAS, como
    `pasos.subtitulos.dos_lineas` — aquí aproximado por caracteres,
    que el vector no sabe medir con la fuente del render.
    """
    paleta = paleta or dict(PALETA_DEFECTO)
    caja = SETS_DISENO.get(diseno, SETS_DISENO["pastilla"])["caja"]
    escala = tamano_de(tam)
    fuente = 52 * escala
    cap = max(10, round(cap_linea))
    texto = " ".join(str(texto or "").split())
    lineas = [texto]
    if len(texto) > cap and " " in texto:
        palabras = texto.split()
        mejor, dif = None, None
        for corte in range(1, len(palabras)):
            arriba = len(" ".join(palabras[:corte]))
            abajo = len(" ".join(palabras[corte:]))
            distancia = abs(arriba - abajo) \
                + 4 * (max(0, arriba - cap) + max(0, abajo - cap))
            if dif is None or distancia < dif:
                dif, mejor = distancia, corte
        lineas = [" ".join(palabras[:mejor]), " ".join(palabras[mejor:])]
    salto = int(fuente * 1.28)
    aire_x, aire_y = int(fuente * 0.62), int(fuente * 0.24)
    ancho_texto = min(ancho - 2 * aire_x - 40,
                      int(0.56 * fuente * max(len(l) for l in lineas)))
    alto = 2 * aire_y + salto * (len(lineas) - 1) + int(fuente * 1.25)
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" '
              f'height="{alto}" viewBox="0 0 {ancho} {alto}">']
    if caja == "sombra":
        partes.append('<filter id="s"><feDropShadow dx="0" dy="2" '
                      'stdDeviation="4" flood-opacity="0.7"/></filter>')
    elif caja == "pleno":
        partes.append(f'<rect x="0" y="0" width="{ancho}" height="{alto}" '
                      f'fill="{paleta["velo"]}"/>'
                      f'<rect x="0" y="0" width="14" height="{alto}" '
                      f'fill="{paleta["acento"]}"/>')
    else:
        x0 = (ancho - ancho_texto) / 2
        partes.append(
            f'<rect x="{x0 - aire_x}" y="0" width="{ancho_texto + 2 * aire_x}" '
            f'height="{alto}" rx="{18 if caja == "pastilla" else 4}" '
            f'fill="{paleta["velo"]}"/>')
        if caja == "barra":
            partes.append(f'<rect x="{x0 - aire_x + aire_x // 4}" '
                          f'y="{alto // 4}" width="8" height="{alto // 2}" '
                          f'fill="{paleta["acento"]}"/>')
    filtro = ' filter="url(#s)"' if caja == "sombra" else ""
    y = aire_y + fuente
    for linea in lineas:
        partes.append(
            f'<text x="{ancho / 2}" y="{y}" text-anchor="middle"'
            f'{filtro} font-family="Arial, Helvetica, sans-serif" '
            f'font-weight="600" font-size="{fuente:.0f}" '
            f'fill="{paleta["texto"]}">{_escapar(linea)}</text>')
        y += salto
    partes.append("</svg>")
    return "".join(partes)
