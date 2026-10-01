"""Paso 7 — callouts: los subtítulos de la narración, trozo a trozo.

Puerto del original: aquí NO hay ninguna llamada de modelo. Un
subtítulo no destila la narración — LA ES — así que lo único que hay
que calcular es qué dice y cuándo, y eso sale de las MARCAS DE PALABRA
de la voz (`pasos/subtitulos.py`): el trozo entra cuando se dice lo
que escribe y se va justo antes de estorbar.

La unidad sigue siendo la ESCENA (el texto corregido a mano vive en
`params.unidades[SXXX].subtitulo_texto`), pero los TROZOS son por
PLANO: cada plano aporta su `narracion` y sus marcas rebanadas, y sus
subtítulos viven en el reloj del plano (el mismo que el zoom y los
cortes).

SIN SUBTÍTULO ANTES QUE CON UNO DESCUADRADO: un plano de cartela no
lleva (la cartela ES el texto, a tamaño de titular — dos textos
compitiendo por la misma atención), una voz sin marcas de palabra no
lleva (voz vieja o cata sin alineación), y una escena cuyas palabras
no reproducen la narración de sus planos tampoco: un subtítulo medio
segundo por detrás de la voz se lee peor que no tenerlo.
"""
from __future__ import annotations

from ..config import AJUSTES
from ..nucleo import grafismo
from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief, p4_voz, subtitulos

#: La banda del subtítulo: el pie del cuadro de salida, quieta.
SUB_MARGEN = 72
SUB_ANCHO = 1400


def params_defecto() -> dict:
    return {"diseno": "pastilla", "paleta": {"fijados": {}},
            "subtitulo_tam": "normal", "subtitulo_caja": "auto"}


def opacidad_de_caja(params: dict):
    """La alfa del velo del subtítulo (mando `subtitulo_caja`).

    "auto" (o cualquier valor sin número) es None: el velo tal como lo
    derivó el estilo. Un número 0..1 lo fija a mano — el mando barato
    del retoque `caja_subtitulo`, que rehace capas y render, nada más.
    """
    valor = (params or {}).get("subtitulo_caja", "auto")
    if valor is None:
        return None
    try:
        return min(1.0, max(0.0, float(valor)))
    except (TypeError, ValueError):
        return None


def estimar(params: dict) -> dict:
    # aritmética de texto y tiempo: ni modelo ni imágenes
    return {"llamadas_llm": 0, "imagenes": 0, "caracteres_voz": 0,
            "coste": 0.0}


def cap_linea_de(subtitulo_tam, salida=None) -> int:
    """Caracteres por línea para ESTE cuerpo y ESTA salida.

    `subtitulos.CAP_LINEA` (38) está medido para el cuerpo normal en
    una banda de 1.400 px; con el grande caben menos. Y en vertical la
    banda se estrecha a 936 y el cuerpo crece con la pantalla, así que
    caben muchas menos: trocear con el tope horizontal daba renglones
    que el render recortaba por los dos lados. Aquí salen ~19 por
    línea en vertical — trozos más cortos y más grandes, que es lo que
    se lee en un móvil.
    """
    escala = grafismo.tamano_de(subtitulo_tam) \
        * subtitulos.escala_subtitulo(salida)
    banda = subtitulos.banda_fija(*(salida or ()))["ancho"]
    return max(12, round(subtitulos.CAP_LINEA * (banda / float(SUB_ANCHO))
                         / max(0.5, escala)))


def ejecutar(proyecto: Proyecto, params: dict, trabajo) -> dict:
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    assets = p2_brief.proyecto_leer_datos(proyecto, "assets")
    if not voz.get("escenas") or not assets.get("planos"):
        raise ValueError("falta voz o assets: genera primero los pasos "
                         "previos")
    planos_de: dict[str, list] = {}
    for p in assets.get("planos", []):
        if isinstance(p, dict) and p.get("escena"):
            planos_de.setdefault(str(p["escena"]), []).append(p)
    unidades = params.get("unidades") or {}
    # el formato, por el MISMO camino que el render (`p8`): lo que dejó
    # escrito assets manda, y si no ha corrido, lo que decidió el brief
    salida = comun.ficha_formato(assets.get("formato")
                                 or p4_voz.formato_de_salida(proyecto))["salida"]
    cap_linea = cap_linea_de(params.get("subtitulo_tam", "normal"), salida)
    # EN VERTICAL, UN RENGLÓN POR TROZO: se lee de un golpe y no tapa
    # el plano (dos líneas en horizontal, como siempre). Un tope de
    # trozo a una línea deja a `dos_lineas` el margen de partir lo que
    # no quepa, midiéndolo de verdad.
    cap_trozo = cap_linea if subtitulos.es_vertical(salida) else None
    idioma = str(proyecto.leer().get("idioma", "es"))
    filas, con_texto = [], 0
    for escena in voz["escenas"]:
        sid = str(escena.get("id") or "")
        palabras = [w for w in (escena.get("palabras") or [])
                    if isinstance(w, dict) and "inicio" in w]
        del_escena = planos_de.get(sid) or []
        if not palabras or not del_escena:
            continue          # voz sin marcas: como siempre, sin subtítulo
        # las marcas de la voz, REBANADAS por plano: la narración de los
        # planos tiene que ser exactamente sus palabras (la guarda del
        # módulo — sin emparejar no hay subtítulo, no uno descuadrado)
        cursor, planos_con_marcas, cuadra = 0, [], True
        for plano in del_escena:
            texto = str(plano.get("narracion") or "")
            dichas = texto.split()
            ventana = palabras[cursor:cursor + len(dichas)]
            if (not dichas or len(ventana) != len(dichas)
                    or [subtitulos.normalizar_texto(w.get("palabra"))
                        for w in ventana]
                    != [subtitulos.normalizar_texto(t) for t in dichas]):
                cuadra = False
                break
            # las palabras del plano de cartela TAMBIÉN se consumen (el
            # emparejado es con la escena entera); solo que su plano no
            # lleva subtítulo — la cartela ES el texto de ese plano
            cursor += len(dichas)
            if plano.get("cartela"):
                continue
            planos_con_marcas.append({
                **plano,
                "marcas": [[w.get("inicio"), w.get("fin")]
                           for w in ventana],
            })
        if not cuadra or cursor != len(palabras):
            continue
        # EL TEXTO CORREGIDO A MANO MANDA, y se reparte SIN TOCAR LOS
        # TIEMPOS (`repartir_escrito`): corregir una palabra escrita no
        # puede volver a trocear, o habría que repartir los tiempos a ojo
        manual = " ".join(str((unidades.get(sid) or {})
                              .get("subtitulo_texto") or "").split())
        trozos_de_plano = [
            subtitulos.de_escena(plano, cap_linea=cap_linea,
                                 cap_trozo=cap_trozo, idioma=idioma)
            for plano in planos_con_marcas]
        if manual:
            dibujados = [t["texto"] for trozos in trozos_de_plano
                         for t in trozos]
            repartidos = iter(subtitulos.repartir_escrito(dibujados, manual))
            trozos_de_plano = [
                [{**t, "texto": texto} for t, texto in zip(trozos, repartidos)
                 if texto]
                for trozos in trozos_de_plano]
        for plano, trozos in zip(planos_con_marcas, trozos_de_plano):
            if not trozos:
                continue
            con_texto += 1
            filas.append({"id": str(plano.get("id") or sid),
                          "escena": sid, "trozos": trozos})
    trozos_total = sum(len(f["trozos"]) for f in filas)
    trabajo.avance(f"{trozos_total} trozos de subtítulo en {con_texto} "
                   f"plano(s) · hasta {cap_linea} caracteres por línea")
    # El grafismo usado queda ESCRITO en los datos: el render no relee
    # params (los suyos son de otro paso), y una vista vieja tiene que
    # poder reproducir qué diseño la dibujó.
    diseno = str(params.get("diseno", "pastilla"))
    if diseno not in grafismo.SETS_DISENO:
        diseno = "pastilla"
    opacidad = opacidad_de_caja(params)
    return {"subtitulos": filas, "diseno": diseno,
            "cap_linea": cap_linea,
            "paleta": grafismo.paleta_de(_estilo_del_canal(),
                                         (params.get("paleta") or {})
                                         .get("fijados")),
            "subtitulo_tam": str(params.get("subtitulo_tam", "normal")),
            # la alfa del velo de la CAJA DEL SUBTÍTULO, escrita aparte:
            # la paleta la comparten las cartelas y el rótulo, y este
            # mando solo quiere tocar el pie del cuadro
            "subtitulo_caja": (round(opacidad, 3) if opacidad is not None
                               else "auto")}


def _estilo_del_canal() -> str:
    """La guía del canal para derivar la paleta: la MISMA que siembra
    los pasos, leída del ajuste global (no params de otro paso)."""
    try:
        from ..nucleo import estilo as modulo_estilo
        return str(modulo_estilo.leer(AJUSTES.datos)
                   .get("estilo_grafico", ""))
    except Exception:                                  # noqa: BLE001
        return ""
