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

Y LAS CARTELAS: si una escena lleva una decidida
(`params.unidades[escena].cartela`), el tramo de planos en el que se
dicen sus palabras se FUNDE en uno solo y la cartela se escribe encima
de su imagen (`_marcar_cartelas`) — hoy van SIEMPRE sobre imagen, así
que pagan como cualquier otro plano; el texto lo dibuja el render al
ritmo de la voz (`pasos/cartelas.py`).
"""
from __future__ import annotations

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import (cartelas as cartelas_motor, catalogo_visual, comun,
               encuadres, guia_estilo, marcas_tts, p2_brief)
from ..motores import imagen_glm, reglas
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
        # Las reglas de reparto nacieron para la hoja de personaje del
        # original; aquí no hay hoja —el reparto entra como texto en cada
        # plano— así que viajan PEGADAS a la capa que describen: es el
        # sitio donde el generador dibuja a la gente.
        bloque_reparto = reglas.bloque_prompt("reparto")
        if bloque_reparto:
            lineas.append(bloque_reparto)
    tono = " ".join(str(beat.get("tono") or "").split())
    if tono:
        lineas.append(f"Mood: {tono}")
    accion = " ".join(str(beat.get("accion") or "").split())
    if accion:
        lineas.append(f"Action: {accion}")
    return lineas


def prompt_de(escena: dict, unidades: dict, params: dict,
              carta: dict | None = None, frase: str | None = None,
              idioma: str = "") -> str:
    """El encargo de imagen de un plano, armado por capas.

    La misma cuenta usa la pantalla para ENSEÑAR el prompt antes de
    pagar: lo que se ve es lo que se manda.

    `frase` es la narración del PLANO (su momento de la escena): sin
    ella, todos los planos de una escena pedirían la misma imagen.

    `idioma` solo añade una línea de dato («The language of this film
    is Spanish.») pegada a la regla de la casa que la interpreta.
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
    # LAS REGLAS DE LA CASA VAN CON LAS DEMÁS LEYES GENERALES, PEGADAS A
    # LA GUÍA — y no al final del prompt, que es donde parecían naturales:
    # ahí pesan más que el plano concreto y lo último que lee el generador
    # acaba siendo la lista de leyes y no lo que se le encarga (fallo que
    # cerró el original por esta vía). Adelantadas valen igual: son leyes.
    bloque_reglas = reglas.bloque_prompt("prompt_imagen")
    if bloque_reglas:
        piezas.append(bloque_reglas)
    # Y EN QUÉ IDIOMA. La POLÍTICA —lo que la producción escribe va en el
    # idioma del vídeo, y los nombres propios no se traducen— la trae la
    # regla `texto-dibujado-en-el-idioma-del-video` del bloque de arriba;
    # aquí solo va el DATO, que es lo único que la regla no puede saber.
    nombre = p2_brief.nombre_idioma_en(idioma)
    if nombre:
        piezas.append(f"The language of this film is {nombre}.")
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


# ------------------------------------------------------------ las cartelas

def _realternar_zoom(planos: list) -> None:
    """Realterna el zoom de los planos que quedan tras una fusión.

    El zoom alterna acercar/alejar plano a plano a propósito: dos
    seguidos en la misma dirección se leen como un único movimiento
    largo y el corte desaparece. Fundir una cartela BORRA planos, y sin
    esto la alteración quedaba rota a partir del hueco.
    """
    anterior = None
    for plano in planos:
        zoom = plano.get("zoom")
        if not isinstance(zoom, dict) or "de" not in zoom:
            continue
        if anterior is not None and zoom.get("tipo") == anterior:
            zoom["tipo"] = "out" if zoom.get("tipo") == "in" else "in"
            zoom["de"], zoom["a"] = zoom["a"], zoom["de"]
        anterior = zoom.get("tipo")


def _marcar_cartelas(planos: list, unidades: dict, trabajo,
                     limitar: bool = True) -> tuple[list, list]:
    """Decide qué planos son cartela y FUNDE el tramo que ocupa cada una.

    Puerto del `_marcar_cartelas`/`_fundir_cartelas` del original,
    adaptado a la unidad de aquí: la cartela se pide por ESCENA del
    guion (`unidades[sid].cartela`) pero el tramo se decide sobre los
    PLANOS ya cortados — el candidato viaja en el PRIMER plano de su
    escena y `tramo_de` lo muda al plano donde de verdad se dicen sus
    palabras. Una cartela nunca cruza a otra escena (`bloque_de`).

    -> ([{id, escena, plantilla, planos, segundos, absorbidos}], avisos)
    """
    plan = {}
    vistos = set()
    for plano in planos:
        sid = str(plano.get("escena") or "")
        if not sid or sid in vistos:
            continue                      # solo el PRIMER plano de su escena
        vistos.add(sid)
        cartela = es_cartela(unidades, sid)
        if cartela:
            plan[str(plano["id"])] = cartela
    if not plan:
        return [], []
    trabajo.avance(f"repartiendo {len(plan)} cartela(s) sobre el corte")

    if limitar:
        # la ocupación se cuenta ANTES de repartir: una cartela que
        # quiere tres planos ya no se los puede comer a la que viene
        # detrás
        ocupacion = cartelas_motor.ocupacion_de(planos, plan)
        puestas, avisos = cartelas_motor.repartir(planos, plan,
                                                  ocupacion=ocupacion)
    else:
        # regenerar una escena sola NO vuelve a repartir: el reparto se
        # decidió sobre el guion entero y redecidirlo con una sola
        # escena delante lo cambiaría
        puestas, avisos = dict(plan), []

    def libre(otro) -> bool:
        otro = otro if isinstance(otro, dict) else {}
        return not (puestas.get(otro.get("id")) or otro.get("cartela"))

    fichas = []
    for pid, ficha in puestas.items():
        indice = next((i for i, p in enumerate(planos)
                       if str(p.get("id")) == pid), None)
        if indice is None:
            continue
        desde, hasta, escritura = cartelas_motor.tramo_de(
            ficha, planos, indice, libre)
        hogar = planos[desde]
        # LA MUDANZA: `tramo_de` devuelve el plano donde de verdad se
        # dicen sus palabras — la cartela se muda a él si no era el suyo
        hogar["cartela"] = ficha
        hogar["escritura"] = escritura
        absorbidos = []
        for chico in planos[desde + 1:hasta + 1]:
            hogar["narracion"] = " ".join(
                x for x in (hogar.get("narracion"),
                            chico.get("narracion")) if x)
            hogar["marcas"] = (hogar.get("marcas") or []) + \
                (chico.get("marcas") or [])
            hogar["corte"] = chico.get("corte") or hogar.get("corte")
            hogar["transicion"] = (chico.get("transicion")
                                   or hogar.get("transicion"))
            hogar["t_out"] = chico["t_out"]
            absorbidos.append(str(chico.get("id")))
        hogar["duracion"] = round(float(hogar["t_out"])
                                  - float(hogar["t_in"]), 3)
        del planos[desde + 1:hasta + 1]
        fichas.append({"id": str(hogar.get("id")),
                       "escena": str(hogar.get("escena")),
                       "plantilla": ficha.get("plantilla"),
                       "planos": hasta - desde + 1,
                       "segundos": hogar["duracion"],
                       "absorbidos": absorbidos})
        trabajo.avance(
            f"cartela {hogar['id']} ({ficha.get('plantilla')}): "
            + (f"funde {hasta - desde + 1} planos" if hasta > desde
               else "un plano"))
    _realternar_zoom(planos)
    return fichas, list(avisos)


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
        ficha_voz = voz_de.get(sid) or {}
        duracion = float(ficha_voz.get("duracion") or 0.0)
        palabras = [p for p in (ficha_voz.get("palabras") or [])
                    if isinstance(p, dict)]
        zoom = segmentar.alternar_zoom(indice)
        ranura = segmentar.transicion_para(indice, "fuerte")
        if not palabras or duracion <= 0:
            # voz SIN marcas (cata/vieja): la escena entera es UN plano
            # — el comportamiento de siempre
            planos.append({"id": sid, "escena": sid,
                           "t_in": 0.0, "t_out": round(duracion, 3),
                           "duracion": round(duracion, 3), "corte": "fuerte",
                           "zoom": zoom, "transicion": ranura,
                           "narracion": marcas_tts.limpiar(
                               escena.get("narracion", ""))})
            indice += 1
            continue
        trozos = _cortar(palabras, duracion, previos_de.get(sid) or [],
                         minimo, maximo, reparto)
        for k, (t_in, t_out, corte, texto, trozo) in enumerate(trozos,
                                                               start=1):
            pid = f"{sid}-{k}" if len(trozos) > 1 else sid
            planos.append({"id": pid, "escena": sid, "t_in": t_in,
                           "t_out": t_out,
                           "duracion": round(t_out - t_in, 3),
                           "corte": corte,
                           "zoom": segmentar.alternar_zoom(indice),
                           "transicion": segmentar.transicion_para(
                               indice, corte),
                           # LAS MARCAS DE PALABRA del trozo, en el reloj
                           # de la escena: con ellas las cartelas anclan
                           # cada palabra que escriben al instante en
                           # que la voz la dice
                           "marcas": [[p["inicio"], p["fin"]] for p in trozo],
                           "narracion": texto})
            cortados.append(planos[-1])
            indice += 1

    # FASE 1b — las cartelas: decididas ANTES de pagar, sobre el corte
    # ya hecho. El tramo que ocupa cada una se FUNDE en un solo plano:
    # no hay ningún corte dentro de la cartela.
    detalle_cartelas, avisos_cartelas = _marcar_cartelas(
        planos, unidades, trabajo, limitar=solo_escenas is None)

    # FASE 2 — las imágenes, una a una (cuestan dinero). Las cartelas de
    # hoy van SIEMPRE sobre la imagen del plano (`TODAS_SOBRE_IMAGEN`),
    # así que pagan como cualquier otro; solo el fondo negro (en desuso)
    # se libera.
    a_pagar = [p for p in planos if not cartelas_motor.sin_imagen(p)]
    con_cartela = [p for p in planos if p.get("cartela")]
    if a_pagar and not imagen_glm.clave(claves):
        raise imagen_glm.ErrorImagen(
            "falta la clave de GLM para imagenes (Configuracion -> claves)")
    pagadas = 0
    # el idioma del vídeo, leído UNA vez: solo sirve para la línea de
    # dato que acompaña a la regla del idioma en el prompt
    idioma = str(proyecto.leer().get("idioma", "es"))
    for plano in planos:
        trabajo.comprobar_cancelacion()
        if cartelas_motor.sin_imagen(plano):
            trabajo.avance(f"cartela {plano['id']} "
                           "(plano de texto: no se paga imagen)")
            plano["imagen"] = None
            plano["prompt"] = "(cartela)"
            continue
        sid = plano["escena"]
        escena = next(e for e in escenas if e["id"] == sid)
        pagadas += 1
        trabajo.avance(f"imagen {pagadas}/{len(a_pagar)}: {plano['id']} "
                       "(una a una, cuesta dinero)")
        destino = carpeta / f"{plano['id']}.png"
        encargo = prompt_de(escena, unidades, params,
                            carta=cartas.get(sid), frase=plano["narracion"],
                            idioma=idioma)
        imagen_glm.generar(
            encargo, destino, calidad=calidad, claves=claves, estilo="")
        anotar_operacion(
            datos_dir=AJUSTES.datos, proyecto=proyecto.id, operacion="imagen",
            proveedor="glm", modelo="glm-image", calidad=calidad,
            contexto=f"assets:{plano['id']}", proyecto_dir=proyecto.raiz)
        plano["imagen"] = f"pasos/assets/imagenes/{plano['id']}.png"
        plano["prompt"] = encargo

    informe = (segmentar.informe(cortados, minimo, maximo, reparto=reparto)
               if cortados else None)
    if detalle_cartelas or avisos_cartelas:
        informe = dict(informe or {})
        informe["cartelas"] = {"fichas": detalle_cartelas,
                               "avisos": avisos_cartelas}
    total = len(planos)
    trabajo.avance(f"{total} planos: {len(a_pagar)} imagen(es)"
                   + (f" · {len(con_cartela)} con cartela encima"
                      if con_cartela else "")
                   + (f" · media {informe['duracion_media']} s por plano"
                      if informe and "duracion_media" in informe else ""))
    return {"planos": planos, "calidad": calidad,
            "cartelas": len(con_cartela),
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
