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

#: Plantillas de cartela: un plano de TEXTO en vez de una imagen pagada.
#: `campos` es lo que pide cada una; `muestra` son datos de ejemplo.
PLANTILLAS_CARTELA = {
    "titulo": {
        "nombre": "Título",
        "descripcion": "un titular grande y centrado",
        "campos": ["titulo"],
        "muestra": {"titulo": "El precio del pan"},
    },
    "cita": {
        "nombre": "Cita",
        "descripcion": "una frase entre comillas, con autor",
        "campos": ["texto", "autor"],
        "muestra": {"texto": "Quien no arriesga, no cruza.",
                    "autor": "Refrán"},
    },
    "dato": {
        "nombre": "Dato",
        "descripcion": "una cifra enorme con su pie",
        "campos": ["cifra", "pie"],
        "muestra": {"cifra": "71 %", "pie": "de los hogares ya lo hace"},
    },
    "capitulo": {
        "nombre": "Capítulo",
        "descripcion": "número de capítulo y su título",
        "campos": ["numero", "titulo"],
        "muestra": {"numero": "2", "titulo": "La burbuja"},
    },
    "cierre": {
        "nombre": "Cierre",
        "descripcion": "el final del vídeo, con subtítulo",
        "campos": ["titulo", "sub"],
        "muestra": {"titulo": "Gracias por ver", "sub": "Sígueme para más"},
    },
}

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


def svg_cartela(plantilla: str, datos: dict | None, paleta: dict | None = None,
                duracion: float = 4.0) -> str:
    """Una cartela completa (1920×1080): el plano que no se paga.

    Cada plantilla es una composición distinta, pero todas comparten la
    paleta del vídeo y el fondo propio: una cartela NO lleva imagen
    debajo, porque el plano entero ES el texto.
    """
    paleta = paleta or dict(PALETA_DEFECTO)
    datos = datos or {}
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ANCHO}" '
              f'height="{ALTO}" viewBox="0 0 {ANCHO} {ALTO}">',
              f'<rect width="{ANCHO}" height="{ALTO}" fill="{paleta["fondo"]}"/>']
    familia = 'font-family="Arial, Helvetica, sans-serif"'
    centro_y = ALTO / 2

    if plantilla == "cita":
        texto = _escapar(datos.get("texto", ""))
        autor = _escapar(datos.get("autor", ""))
        partes.append(
            f'<text x="{ANCHO / 2}" y="{centro_y - 40}" text-anchor="middle" '
            f'{familia} font-size="150" fill="{paleta["acento"]}">“</text>'
            f'<text x="{ANCHO / 2}" y="{centro_y + 40}" text-anchor="middle" '
            f'{familia} font-size="72" fill="{paleta["texto"]}">'
            f"{texto}</text>")
        if autor:
            partes.append(
                f'<text x="{ANCHO / 2}" y="{centro_y + 150}" '
                f'text-anchor="middle" {familia} font-size="38" '
                f'fill="{paleta["acento"]}">— {autor}</text>')
    elif plantilla == "dato":
        cifra = _escapar(datos.get("cifra", ""))
        pie = _escapar(datos.get("pie", ""))
        partes.append(
            f'<text x="{ANCHO / 2}" y="{centro_y + 40}" text-anchor="middle" '
            f'{familia} font-size="220" font-weight="800" '
            f'fill="{paleta["acento"]}">{cifra}</text>')
        if pie:
            partes.append(
                f'<text x="{ANCHO / 2}" y="{centro_y + 200}" '
                f'text-anchor="middle" {familia} font-size="52" '
                f'fill="{paleta["texto"]}">{pie}</text>')
    elif plantilla == "capitulo":
        numero = _escapar(datos.get("numero", ""))
        titulo = _escapar(datos.get("titulo", ""))
        partes.append(
            f'<text x="{ANCHO / 2}" y="{centro_y - 60}" '
            f'text-anchor="middle" {familia} font-size="44" letter-spacing="18" '
            f'fill="{paleta["acento"]}">CAPÍTULO {numero}</text>'
            f'<rect x="{ANCHO / 2 - 90}" y="{centro_y - 10}" width="180" '
            f'height="4" fill="{paleta["acento"]}"/>'
            f'<text x="{ANCHO / 2}" y="{centro_y + 130}" '
            f'text-anchor="middle" {familia} font-size="96" font-weight="800" '
            f'fill="{paleta["texto"]}">{titulo}</text>')
    elif plantilla == "cierre":
        titulo = _escapar(datos.get("titulo", ""))
        sub = _escapar(datos.get("sub", ""))
        partes.append(
            f'<text x="{ANCHO / 2}" y="{centro_y}" text-anchor="middle" '
            f'{familia} font-size="110" font-weight="800" '
            f'fill="{paleta["texto"]}">{titulo}</text>')
        if sub:
            partes.append(
                f'<text x="{ANCHO / 2}" y="{centro_y + 120}" '
                f'text-anchor="middle" {familia} font-size="48" '
                f'fill="{paleta["acento"]}">{sub}</text>')
    else:  # titulo
        titulo = _escapar(datos.get("titulo", ""))
        partes.append(
            f'<rect x="{ANCHO / 2 - 70}" y="{centro_y - 160}" width="140" '
            f'height="6" fill="{paleta["acento"]}"/>'
            f'<text x="{ANCHO / 2}" y="{centro_y}" text-anchor="middle" '
            f'{familia} font-size="130" font-weight="800" '
            f'fill="{paleta["texto"]}">{titulo}</text>')
    # el instante de lectura, para la muestra de la pantalla
    partes.append(
        f'<text x="{ANCHO - 40}" y="{ALTO - 36}" text-anchor="end" '
        f'{familia} font-size="28" fill="{paleta["acento"]}" opacity="0.65">'
        f"~{round(float(duracion or 4))} s</text></svg>")
    return "".join(partes)
