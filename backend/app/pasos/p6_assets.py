"""Paso 6 — assets: las imágenes del vídeo, de UNA EN UNA.

Regla heredada del original: las tandas de imágenes NO van en paralelo —
cuestan dinero, y dos a la vez tardan el doble por imagen y pierden el
registro del gasto. La calidad se fija al crear el proyecto (entra en la
firma: cambiarla dejaría obsoleto solo lo de abajo).

EL RITMO: UNA ESCENA, VARIOS PLANOS
------------------------------------
El corte no se hace a ojo: `motores/guion/segmentar.py` (puerto del
original) reparte las MARCAS DE PALABRA de la voz en planos de
`planos_min_s`–`planos_max_s` segundos cortando en las pausas reales.
Cada plano es una imagen y un trozo de pantalla con su ventana
`t_in`/`t_out` (un plano entra ADELANTO_S antes de su primera palabra y
dura hasta que entra el siguiente). Sin marcas de palabra (voz vieja o
cata sin alineación) la escena entera es UN plano, como siempre.

Regrabar la voz NO tira el corte: `heredar` vuelve a colocar las fronteras
de antes sobre los tiempos nuevos — regrabar una frase movió las marcas
ochenta milésimas y en el original eso tiraba 225 imágenes pagadas.

La UNIDAD de corrección sigue siendo la ESCENA (dirección, redactor,
cartelas, feedback viven en `params.unidades[SXXX]`); los planos son las
imágenes de dentro. Regenerar una escena regenera sus planos.

El prompt de cada plano se ARMA con capas (regla de `pasos/direccion.py`):

    redactado  el prompt escrito entero (redactor), si existe MANDA
    + estilo   la guía con números (o el texto libre si aún no hay)
    + carta    QUÉ CLASE de plano es (encuadres.py): el SHOT TYPE
    + catalogo el sitio, la luz, quién sale y el tono del tramo
    + direccion que se ve en ESTE plano (la capa que distingue vecinos)
    + frase    la narración del plano (su momento de la escena)

Y hay planos que no se pagan: si una escena lleva CARTELA decidida
(`params.unidades[escena].cartela`), no se genera imagen — el plano
entero es texto, y lo dibuja el grafismo del render.
"""
from __future__ import annotations

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import comun, marcas_tts, p2_brief, catalogo_visual, encuadres, guia_estilo
from ..motores import imagen_glm
from ..motores.guion import segmentar


def params_defecto() -> dict:
    return {"calidad": AJUSTES.calidad_imagen, "estilo": "",
            # el ritmo del montaje: la horquilla de plano que obedece
            # el corte (TOPE, no precio: ver segmentar.ESCALERA)
            "planos_min_s": 3.0, "planos_max_s": 6.0}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": "?", "caracteres_voz": 0,
            "coste": None}


def _capas_catalogo(params: dict, sid: str) -> list[str]:
    """El sitio, la luz y quién sale: el andamio del catálogo visual.

    Sin catálogo devuelve [] (no es obligatorio), y entonces el plano
    se arma como siempre: estilo + direccion + frase.
    """
    catalogo = catalogo_visual.catalogo_de(params)
    if not catalogo.get("beats"):
        return []
    beat = catalogo_visual.beat_de(catalogo, sid) or {}
    lineas = []
    sitio = (catalogo.get("sets") or {}).get(beat.get("set")) or {}
    lugar = " ".join(str(sitio.get("descripcion") or "").split())
    if lugar:
        lineas.append(f"Location: {lugar}")
    luz = " ".join(str(sitio.get("luz") or "").split())
    if luz:
        lineas.append(f"Lighting: {luz}")
    reparto = catalogo.get("reparto") or {}
    presentes = [reparto[pid] for pid in (beat.get("personajes") or [])
                 if pid in reparto]
    fisicos = [" ".join(str(p.get("descripcion") or "").split())
               for p in presentes]
    fisicos = [f for f in fisicos if f]
    if fisicos:
        lineas.append("Characters in frame, draw each one exactly as "
                      "described: " + " | ".join(fisicos))
    tono = " ".join(str(beat.get("tono") or "").split())
    if tono:
        lineas.append(f"Mood: {tono}")
    accion = " ".join(str(beat.get("accion") or "").split())
    if accion:
        lineas.append(f"Action: {accion}")
    return lineas


def prompt_de(escena: dict, unidades: dict, params: dict,
              carta: dict | None = None, frase: str | None = None) -> str:
    """El encargo de imagen de un plano, armado por capas.

    La misma cuenta usa la pantalla para ENSEÑAR el prompt antes de
    pagar: lo que se ve es lo que se manda.

    `frase` es la narración del PLANO (su momento de la escena): sin
    ella, todos los planos de una escena pedirían la misma imagen.
    """
    ficha = unidades.get(escena["id"]) or {}
    # EL HISTORIAL DE FEEDBACK MANDA SOBRE TODO: es lo que este plano ya
    # hizo mal (repaso, capturas anotadas). Sin releerlo, regenerar
    # repetiría el error y la nota quedaría «aplicada».
    correcciones = []
    for nota in (ficha.get("feedback") or []):
        if not isinstance(nota, dict):
            continue
        texto = " ".join(str(nota.get("texto") or "").split())
        if not texto:
            continue
        alcance = str(nota.get("alcance") or "")
        prefijo = ("LOCALIZED fix, keep the rest of the frame as is"
                   if alcance == "retoque" else "Replace the subject")
        correcciones.append(f"Correction: {prefijo}. {texto}")
    redactado = " ".join(str(ficha.get("prompt") or "").split())
    if redactado:
        # el redactor escribe el encargo ENTERO, pero las correcciones
        # posteriores van ENCIMA
        return "\n".join([redactado] + correcciones)
    piezas = []
    # la capa de estilo manda con la GUÍA si la hay (la biblia con
    # números); si no, el texto libre de siempre
    bloque = guia_estilo.bloque_de_estilo(params)
    if bloque:
        piezas.append(f"Style: {bloque}" if "\n" not in bloque else bloque)
    encuadre = " ".join(str((carta or {}).get("encuadre") or "").split())
    if encuadre:
        piezas.append(f"Shot type: {encuadre}")
    piezas.extend(_capas_catalogo(params, escena["id"]))
    direccion = " ".join(str(ficha.get("direccion") or "").split())
    if direccion:
        piezas.append(direccion)
    visual = str(escena.get("visual") or "").strip()
    if frase is not None and frase.strip():
        # el momento del plano manda, con el visual de la escena como
        # contexto si lo hay: es la capa que distingue vecinos
        capa = f"{visual}. {frase.strip()}".strip() if visual else frase.strip()
        piezas.append(capa)
    else:
        # limpiar: la narracion puede traer anotaciones de voz (<break>)
        # y una etiqueta en el prompt de imagen es ruido que ademas paga
        texto = visual or marcas_tts.limpiar(escena.get("narracion", ""))
        if texto:
            piezas.append(texto)
    return "\n".join(piezas + correcciones) or "abstract neutral illustration"


def es_cartela(unidades: dict, escena_id: str) -> dict | None:
    ficha = unidades.get(escena_id) or {}
    cartela = ficha.get("cartela")
    return cartela if isinstance(cartela, dict) and cartela.get("plantilla") \
        else None


# ------------------------------------------------------------- el corte

def _cortar(palabras: list, duracion: float, previos: list,
            minimo: float, maximo: float, reparto: dict) -> list:
    """[(t_in, t_out, corte, texto, trozo)] — la escena cortada en planos.

    Primero intenta HEREDAR el corte anterior (regrabar la voz no tira
    las imágenes); si el texto cambió demasiado, corta de cero.
    """
    segmentos = None
    if previos:
        heredado = {}
        segmentos = segmentar.heredar(palabras, previos, maximo=maximo,
                                      minimo=minimo, reparto=heredado)
        if segmentos:
            reparto.update(heredado)
    if not segmentos:
        fresco = {}
        segmentos = segmentar.segmentar(palabras, minimo, maximo,
                                        reparto=fresco)
        reparto.update(fresco)
    entradas = segmentar.entradas_de(palabras)
    salida, ini = [], 0
    for _s, _e, trozo in segmentos:
        a, b = ini, ini + len(trozo)
        t_in = max(0.0, entradas[a])
        if b >= len(palabras):
            # el último se lleva hasta el FIN del audio: el silencio
            # final de la escena es suyo
            t_out = max(entradas[-1], duracion)
        else:
            t_out = entradas[b]
        t_out = max(t_in + 0.1, min(t_out, duracion or t_out))
        texto = " ".join(p["palabra"] for p in trozo)
        salida.append((round(t_in, 3), round(t_out, 3),
                       segmentar.tipo_de_corte(trozo[-1]["palabra"]),
                       texto, trozo))
        ini = b
    return salida


def ejecutar(proyecto: Proyecto, params: dict, trabajo,
             solo_escenas: list | None = None) -> dict:
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    todas = guion.get("escenas", [])
    if not todas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    voz = p2_brief.proyecto_leer_datos(proyecto, "voz")
    voz_de = {v["id"]: v for v in (voz.get("escenas") or [])
              if isinstance(v, dict)}
    # el corte de ANTES, para heredar: regrabar la voz no debe tirar
    # imágenes ya pagadas
    anteriores = p2_brief.proyecto_leer_datos(proyecto, "assets")
    previos_de: dict[str, list] = {}
    for p in (anteriores.get("planos") or []):
        if isinstance(p, dict) and p.get("escena") and p.get("narracion"):
            previos_de.setdefault(str(p["escena"]), []).append(p)
    unidades = params.get("unidades") or {}
    # el reparto de cartas se calcula sobre el guion ENTERO: depende del
    # ORDEN (cada plano mira los que tiene delante), así que
    # regenerar uno solo no puede cambiarle la carta a los demás. La
    # carta que haya pedido una persona (unidades[sid].carta) manda
    # sobre el reparto.
    forzadas = {sid: str((ficha or {}).get("carta") or "")
                for sid, ficha in unidades.items()
                if isinstance(ficha, dict)}
    cartas = encuadres.repartir(todas, semilla=proyecto.id,
                                forzadas=forzadas)
    escenas = ([e for e in todas if e["id"] in solo_escenas]
               if solo_escenas else todas)
    minimo = max(0.5, float(params.get("planos_min_s") or 3.0))
    maximo = max(minimo + 0.5, float(params.get("planos_max_s") or 6.0))
    claves = comun.claves_actuales()
    calidad = params.get("calidad", "low")
    carpeta = proyecto.carpeta_paso("assets") / "imagenes"

    # FASE 1 — el corte (gratis): decidir los planos antes de pagar nada
    trabajo.avance(f"cortando el ritmo: planos de {minimo:g}-{maximo:g} s "
                   "sobre las pausas de la voz")
    planos, cortados, reparto = [], [], {}
    indice = 0
    for escena in escenas:
        trabajo.comprobar_cancelacion()
        sid = escena["id"]
        cartela = es_cartela(unidades, sid)
        ficha_voz = voz_de.get(sid) or {}
        duracion = float(ficha_voz.get("duracion") or 0.0)
        palabras = [p for p in (ficha_voz.get("palabras") or [])
                    if isinstance(p, dict)]
        zoom = segmentar.alternar_zoom(indice)
        ranura = segmentar.transicion_para(indice, "fuerte")
        if cartela or not palabras or duracion <= 0:
            # cartela, o voz SIN marcas (cata/vieja): la escena entera
            # es UN plano — el comportamiento de siempre
            planos.append({"id": sid, "escena": sid,
                           "t_in": 0.0, "t_out": round(duracion, 3),
                           "duracion": round(duracion, 3), "corte": "fuerte",
                           "zoom": zoom, "transicion": ranura,
                           **({"cartela": cartela, "imagen": None,
                               "prompt": "(cartela)"} if cartela else {}),
                           "narracion": marcas_tts.limpiar(
                               escena.get("narracion", ""))})
            indice += 1
            continue
        trozos = _cortar(palabras, duracion, previos_de.get(sid) or [],
                         minimo, maximo, reparto)
        for k, (t_in, t_out, corte, texto, _palabras) in enumerate(trozos,
                                                                   start=1):
            pid = f"{sid}-{k}" if len(trozos) > 1 else sid
            planos.append({"id": pid, "escena": sid, "t_in": t_in,
                           "t_out": t_out,
                           "duracion": round(t_out - t_in, 3),
                           "corte": corte,
                           "zoom": segmentar.alternar_zoom(indice),
                           "transicion": segmentar.transicion_para(
                               indice, corte),
                           "narracion": texto})
            cortados.append(planos[-1])
            indice += 1

    # FASE 2 — las imágenes, una a una (cuestan dinero)
    a_pagar = [p for p in planos if not p.get("cartela")]
    cartelas = [p for p in planos if p.get("cartela")]
    if a_pagar and not imagen_glm.clave(claves):
        raise imagen_glm.ErrorImagen(
            "falta la clave de GLM para imagenes (Configuracion -> claves)")
    pagadas = 0
    for plano in planos:
        trabajo.comprobar_cancelacion()
        if plano.get("cartela"):
            trabajo.avance(f"cartela {plano['id']} "
                           "(plano de texto: no se paga imagen)")
            continue
        sid = plano["escena"]
        escena = next(e for e in escenas if e["id"] == sid)
        pagadas += 1
        trabajo.avance(f"imagen {pagadas}/{len(a_pagar)}: {plano['id']} "
                       "(una a una, cuesta dinero)")
        destino = carpeta / f"{plano['id']}.png"
        encargo = prompt_de(escena, unidades, params,
                            carta=cartas.get(sid), frase=plano["narracion"])
        imagen_glm.generar(
            encargo, destino, calidad=calidad, claves=claves, estilo="")
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="imagen",
            proveedor="glm", modelo="glm-image", calidad=calidad,
            contexto=f"assets:{plano['id']}", proyecto_dir=proyecto.raiz)
        plano["imagen"] = f"pasos/assets/imagenes/{plano['id']}.png"
        plano["prompt"] = encargo[:300]

    informe = (segmentar.informe(cortados, minimo, maximo, reparto=reparto)
               if cortados else None)
    total = len(planos)
    trabajo.avance(f"{total} planos: {len(a_pagar)} imagen(es) + "
                   f"{len(cartelas)} cartela(s) de texto"
                   + (f" · media {informe['duracion_media']} s por plano"
                      if informe else ""))
    return {"planos": planos, "calidad": calidad,
            "cartelas": len(cartelas),
            **({"informe": informe} if informe else {}),
            "ritmo": {"minimo": minimo, "maximo": maximo}}


def regenerar_plano(proyecto: Proyecto, escena_id: str, params: dict) -> list:
    """Regenera los planos de UNA escena bajo demanda (botón de imagen)."""
    resultado = ejecutar(proyecto, params, _TrabajoMudo(),
                         solo_escenas=[escena_id])
    return resultado["planos"]


class _TrabajoMudo:
    """Avance que no va a ninguna parte (llamadas suelas fuera de cola)."""

    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass
