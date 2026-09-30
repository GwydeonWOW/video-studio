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

LAS CADENAS, Y LA REGLA DE LA TANDA
-----------------------------------
La regla del original sigue en pie: una TANDA (un trabajo del botón
Generar) cada vez — dos jobs a la vez tardan el doble por imagen y
pierden el registro del gasto. Pero DENTRO de una tanda los planos de
SITIOS distintos son independientes: entre dos sets hay un corte de
todas formas. Así que se agrupan por set y los grupos corren a la vez
(`cadenas`, con el tope MAX_CADENAS): con seis sitios, el camino crítico
pasa de 35 llamadas en fila a las del sitio más largo.

EL GUARDIÁN DE PLANOS REPETIDOS
-------------------------------
Al terminar, `_planos_repetidos` comprueba que no haya dos planos con el
mismo encargo o el mismo fichero byte a byte: es un fallo que en la
rejilla se ve como «repetimos mucho» y callarlo hasta que alguien lo
note a ojo sale más caro que abortar aquí. Tiene dos excepciones
documentadas (la cartela y la continuación de un plano largo) y NO se
añade ninguna a la ligera: un guardián calibrado sobre un fallo aprende
a dar por bueno ese fallo.
"""
from __future__ import annotations

import threading

from concurrent.futures import ThreadPoolExecutor

from ..config import AJUSTES
from ..nucleo.coste import anotar_operacion
from ..nucleo.proyecto import Proyecto
from . import (cartelas as cartelas_motor, catalogo_visual, comun,
               corrector, encuadres, guia_estilo, marcas_tts, p2_brief)
from ..motores import imagen_glm, reglas
from ..motores.guion import segmentar

#: Tope de cadenas de generación a la vez (una por sitio, hasta cuatro).
#: El grafo no pide más: los sitios son independientes entre sí.
MAX_CADENAS = 4


def params_defecto() -> dict:
    return {"calidad": AJUSTES.calidad_imagen, "estilo": "",
            # el ritmo del montaje: la horquilla de plano que obedece
            # el corte (TOPE, no precio: ver segmentar.ESCALERA)
            "planos_min_s": 3.0, "planos_max_s": 6.0,
            # LA SEMILLA del reparto de encuadres: un proyecto nuevo
            # nace con 7 (regla del original) y las lectas caen a 0
            "semilla": 7,
            # Cadenas de generación a la vez: 0 = automático (una por
            # sitio, tope MAX_CADENAS), 1 = en fila, N = tope de N
            "cadenas": 0}


def estimar(params: dict) -> dict:
    return {"llamadas_llm": 0, "imagenes": "?", "caracteres_voz": 0,
            "coste": None}


def _capas_catalogo(params: dict, sid: str,
                    personajes: list | None = None) -> list[str]:
    """El sitio, la luz y quién sale: el andamio del catálogo visual.

    Sin catálogo devuelve [] (no es obligatorio), y entonces el plano
    se arma como siempre: estilo + direccion + frase. `personajes`
    overridea a los del beat: es lo que trae el CORRECTOR («quién sale
    en el plano NUEVO»), que manda sobre el plan para ESTA pasada.
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
    quienes = (personajes if personajes is not None
               else (beat.get("personajes") or []))
    presentes = [reparto[pid] for pid in quienes
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


def _frase_de_referencia(ref: dict) -> str:
    """Lo que el generador oye de una referencia, según su clase.

    La misma frase para todos los planos (regla del original): la clase
    decide el trato por defecto y el detalle del corrector decide el
    resto.
    """
    clase = str(ref.get("clase") or "adjunta")
    if clase == "rechazada":
        return ("It is this very shot as it was drawn: keep everything "
                "and change only what the note asks.")
    if clase == "continuidad":
        extra = ", same set" if ref.get("mismo_set") else ""
        return (f"It is a neighbouring shot: same palette, same light"
                f"{extra}; do not copy its framing or poses.")
    if clase == "reparto":
        nombre = " ".join(str(ref.get("nombre") or "").split())
        return (f"It is how {nombre or 'that character'} looks: copy "
                f"the face, hair, body and clothes; nothing else.")
    return "Use it ONLY for what the note asks of it."


def _referencias_textuales(corregido: dict) -> list[str]:
    """Las referencias del corrector como líneas del prompt.

    El motor de aquí no adjunta imágenes (ver corrector.py): cada
    referencia viaja como su FRASE DE CLASE —la misma que oiría un plano
    nuevo— con el detalle del agente encima, que es lo que SOLO se sabe
    mirando la imagen.
    """
    lineas = []
    for ref in (corregido.get("referencias") or []):
        if not isinstance(ref, dict):
            continue
        detalle = " ".join(str(ref.get("detalle") or "").split())
        frase = _frase_de_referencia(ref)
        if detalle:
            frase = f"{frase.rstrip('.')}. {detalle}"
        lineas.append(f"Reference: {frase}")
    return lineas


def prompt_de(escena: dict, unidades: dict, params: dict,
              carta: dict | None = None, frase: str | None = None,
              idioma: str = "", correccion: dict | None = None) -> str:
    """El encargo de imagen de un plano, armado por capas.

    La misma cuenta usa la pantalla para ENSEÑAR el prompt antes de
    pagar: lo que se ve es lo que se manda.

    `frase` es la narración del PLANO (su momento de la escena): sin
    ella, todos los planos de una escena pedirían la misma imagen.

    `idioma` solo añade una línea de dato («The language of this film
    is Spanish.») pegada a la regla de la casa que la interpreta.

    `correccion` es lo que devolvió el CORRECTOR para la nota de esta
    unidad (ver pasos/corrector.py): su descripción sustituye a la capa
    visual, sus personajes a los del beat, sus referencias entran como
    líneas y su alcance manda sobre la última nota. Con {"error"} o
    None se vuelve al camino de siempre: la nota pegada al final.
    """
    ficha = unidades.get(escena["id"]) or {}
    corregido = (correccion if isinstance(correccion, dict)
                 and not correccion.get("error") else None)
    # EL HISTORIAL DE FEEDBACK MANDA SOBRE TODO: es lo que este plano ya
    # hizo mal (repaso, capturas anotadas). Sin releerlo, regenerar
    # repetiría el error y la nota quedaría «aplicada».
    correcciones = []
    notas = [n for n in (ficha.get("feedback") or [])
             if isinstance(n, dict)]
    for numero, nota in enumerate(notas):
        texto = " ".join(str(nota.get("texto") or "").split())
        if not texto:
            continue
        alcance = str(nota.get("alcance") or "")
        if corregido and numero == len(notas) - 1:
            # la última nota es la que el corrector ha leído: SU alcance
            # (el que miró la imagen para decidir) manda sobre el que
            # trajera la propia nota
            alcance = corregido["alcance"]
        prefijo = ("LOCALIZED fix, keep the rest of the frame as is"
                   if alcance == "retoque" else "Replace the subject")
        correcciones.append(f"Correction: {prefijo}. {texto}")
    referencias = _referencias_textuales(corregido) if corregido else []
    redactado = " ".join(str(ficha.get("prompt") or "").split())
    if redactado:
        # el redactor escribe el encargo ENTERO, pero las correcciones
        # posteriores van ENCIMA
        return "\n".join([redactado] + referencias + correcciones)
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
    piezas.extend(_capas_catalogo(params, escena["id"],
                                  personajes=(corregido["personajes"]
                                              if corregido else None)))
    direccion = " ".join(str(ficha.get("direccion") or "").split())
    if direccion:
        piezas.append(direccion)
    # las referencias del corrector van ANTES de la descripción, como
    # iban las adjuntas del original: sostienen lo que viene detrás
    piezas.extend(referencias)
    if corregido:
        # la descripción del corrector SUSTITUYE a la composición visual
        # (ya incorpora la nota y conserva lo que la nota no toca), pero
        # el MOMENTO del plano se queda ENCIMA: es la capa que distingue
        # vecinos — sin ella, todos los planos de la escena corregida
        # pedirían la misma imagen y el guardián los tumbaría
        momento = " ".join(str(frase or "").split())
        piezas.append(" ".join(x for x in (corregido["escena"], momento)
                               if x))
    else:
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


# ---------------------------------------------------- la nota y el corrector

def _texto_feedback(valor) -> str:
    """El feedback de una unidad como UN texto para el corrector.

    El que escribe la pantalla es una cadena; el historial que dejan
    las correcciones es una lista de fichas con 'texto'. Los dos tienen
    que acabar DENTRO del encargo: el feedback movia la firma (se pagaba
    una imagen nueva) pero el encargo era identico, asi que salia una
    variacion de lo mismo y la nota del revisor se ignoraba entera.
    """
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, list):
        trozos = [str(v.get("texto") or "").strip() for v in valor
                  if isinstance(v, dict)]
        return " | ".join(t for t in trozos if t)
    return ""


def _corrector_activo(params: dict) -> bool:
    """Si este proyecto usa el corrector. Se apaga con `corrector: "no"`."""
    return str((params or {}).get("corrector") or "").lower() != "no"


def _inventario_para_nota(plano: dict, planos: list, params: dict,
                          carpeta) -> list[dict]:
    """Las referencias que el corrector puede citar, como fichas.

    Cada ficha es {"clave", "que", "clase"} (+ los atributos que su
    frase necesite, como `mismo_set` o `nombre`). En el original el
    inventario era de RUTAS que el agente abría con Read y adjuntaba
    luego el generador; aquí el generador solo lee texto (ver
    corrector.py), así que la clave es un identificador corto y la
    ficha viaja al prompt como línea.

    ENTRAN: la imagen actual del plano (la rechazada), los VECINOS de
    alrededor (con su sitio y lo que dicen, que es lo que decide si son
    del mismo sitio) y el reparto entero. NO entran los sets ni las
    láminas del estilo: ya viajan en el encargo como capas, y una
    referencia que repite una capa no añade nada que el generador no
    haya oído ya.
    """
    pid = str(plano.get("id") or "")
    fichas: list[dict] = []
    catalogo = catalogo_visual.catalogo_de(params)
    beat = catalogo_visual.beat_de(catalogo, str(plano.get("escena"))) or {}

    def meter(clave, que, clase, **extra):
        if not any(f["clave"] == clave for f in fichas):
            fichas.append(dict(extra, clave=str(clave), que=que,
                               clase=clase))

    if plano.get("imagen"):
        ruta = carpeta / f"{pid}.png"
        if ruta.is_file():
            meter("rechazada",
                  f"LA IMAGEN ACTUAL del plano {pid}, la que el revisor "
                  "ha rechazado (viaja adjunta a tu mensaje)",
                  "rechazada")
    orden = [str(p.get("id") or "") for p in planos]
    if pid in orden:
        centro = orden.index(pid)
        for indice in range(max(0, centro - corrector.VECINOS),
                            min(len(planos), centro + corrector.VECINOS + 1)):
            if indice == centro:
                continue
            vecino = planos[indice]
            if not isinstance(vecino, dict) or not vecino.get("imagen"):
                continue
            su_beat = (catalogo_visual.beat_de(
                catalogo, str(vecino.get("escena"))) or {})
            donde = "ANTERIOR" if indice < centro else "SIGUIENTE"
            dice = " ".join(str(vecino.get("narracion") or "").split())
            meter(vecino["id"],
                  f"el plano {vecino['id']}, {abs(indice - centro)} a este "
                  f"({donde}); sitio '{su_beat.get('set') or '-'}'; dice: "
                  f"{dice[:160]}",
                  "continuidad",
                  mismo_set=bool(su_beat.get("set")
                                 and su_beat.get("set") == beat.get("set")))
    for ident, ficha in ((catalogo.get("reparto") or {}).items()):
        if isinstance(ficha, dict):
            como = " ".join(str(ficha.get("descripcion") or "").split())
            meter(f"reparto:{ident}",
                  f"como es '{ident}': {como[:200]}", "reparto",
                  nombre=str(ident))
    return fichas


def _corregir_con_agente(plano: dict, escena: dict, planos: list,
                         unidades: dict, params: dict, carpeta, proyecto,
                         carta: dict | None, previo: dict, avisar) -> dict:
    """Pasa la nota de esta unidad por el corrector. -> dict (o {"error"}).

    Nunca rompe la corrección: si el agente no contesta, quien llama
    sigue con `prompt_de` sin corrección — la nota pegada al final, el
    camino de siempre.
    """
    catalogo = catalogo_visual.catalogo_de(params)
    beat = catalogo_visual.beat_de(catalogo, str(plano.get("escena"))) or {}
    fichas = _inventario_para_nota(plano, planos, params, carpeta)
    # la imagen rechazada es la SEMBRADA de la pasada anterior (ver el
    # comedero de previos en `ejecutar`): este plano aún no se ha dibujado
    ruta_actual = str(carpeta / f"{plano['id']}.png") \
        if plano.get("imagen") and (carpeta / f"{plano['id']}.png").is_file() \
        else ""
    estilo = guia_estilo.bloque_de_estilo(params)
    return corrector.preparar(
        _texto_feedback((unidades.get(str(plano.get("escena"))) or {})
                        .get("feedback")),
        {"id": plano.get("id"),
         "narracion": plano.get("narracion"),
         "set": beat.get("set"),
         "personajes": beat.get("personajes") or [],
         # el encargo CON el que se dibujó lo que hay en disco: está en
         # los datos de la pasada anterior, no en este plan recién cortado
         "prompt": previo.get("prompt") if isinstance(previo, dict) else "",
         "encuadre": (carta or {}).get("encuadre")},
        catalogo, estilo, fichas,
        titulo=str((proyecto.leer() or {}).get("nombre") or ""),
        imagen_actual=ruta_actual,
        proyecto_id=proyecto.id, avisar=avisar)


# ----------------------------------------------- cadenas y el guardián

def _cuantas_cadenas(params: dict, planos: list) -> int:
    """Cuántas cadenas correr a la vez: por defecto, una por sitio, con tope.

    0 (por defecto) = automático, 1 = en fila, N = tope de N. El
    automático mira las dos restricciones y se queda con la más
    estrecha: el paralelismo que admite el montaje son los SITIOS —
    entre dos sets hay un corte de todas formas —, y el que admite la
    casa es MAX_CADENAS.
    """
    try:
        pedidas = int((params or {}).get("cadenas") or 0)
    except (TypeError, ValueError):
        pedidas = 0
    if pedidas > 0:
        return pedidas
    catalogo = catalogo_visual.catalogo_de(params)
    sitios = {(catalogo_visual.beat_de(catalogo, str(p.get("escena")))
               or {}).get("set") or "\x00sin-set"
              for p in planos if isinstance(p, dict)}
    return max(1, min(len(sitios), MAX_CADENAS))


def _cadenas_por_set(planos: list, params: dict) -> list[list[dict]]:
    """Los planos agrupados por sitio, la cadena más larga primero.

    Dentro de cada grupo se conserva el ORDEN del vídeo: es lo que hace
    que el resultado sea el mismo vaya en fila o en cadenas.
    """
    catalogo = catalogo_visual.catalogo_de(params)
    grupos: dict[str, list[dict]] = {}
    for plano in planos:
        if not isinstance(plano, dict):
            continue
        beat = (catalogo_visual.beat_de(catalogo, str(plano.get("escena")))
                or {})
        clave = beat.get("set") or "\x00sin-set"
        grupos.setdefault(clave, []).append(plano)
    return sorted(grupos.values(), key=len, reverse=True)


def _planos_repetidos(planos: list, carpeta, copiados=()) -> list[list[str]]:
    """Grupos de planos que han acabado con un fichero o un encargo idéntico.

    Vale la pena comprobarlo aunque el encargo ya lleve la narración:
    que dos planos compartan imagen es un fallo que en la UI se ve como
    «repetimos mucho» y que en disco es un byte a byte idéntico.
    Callarlo hasta que alguien lo note a ojo sale más caro que abortar
    aquí.

    LO QUE BUSCA ES UN FALLO CONCRETO: dos encargos que salieron
    idénticos (la capa frase no llegó a distinguirlos) o dos ficheros
    idénticos. Así que lo que comparte imagen A PROPÓSITO no cuenta, y
    son dos casos:

      la cartela        no tiene imagen ni pasa por el generador; dos
                        cartelas iguales serían dos textos iguales, que
                        se ve en la rejilla y no justifica tumbar una
                        tanda ya pagada.
      la CONTINUACIÓN   la segunda mitad de una toma que dura más es la
                        MISMA imagen copiada: mismo fichero, zoom
                        partido, sin transición en medio. Es byte a byte
                        idéntica porque tiene que serlo.

    Quién dice quién es continuación no es el disco sino el PLAN (los
    ids con `sigue_a`): el guardián se calibra sobre lo que se ENCARGA,
    no sobre lo que hay. **Un guardián calibrado sobre un fallo aprende
    a dar por bueno ese fallo.**
    """
    copiados = set(copiados or ())
    por_huella: dict[str, list[str]] = {}
    por_encargo: dict[str, list[str]] = {}
    for plano in planos:
        if not isinstance(plano, dict) or not plano.get("imagen"):
            continue                        # la cartela sin imagen no entra
        pid = str(plano.get("id") or "")
        if not pid or pid in copiados or plano.get("sigue_a"):
            continue
        huella = comun.huella_fichero(carpeta / f"{pid}.png")
        if huella:
            por_huella.setdefault(huella, []).append(pid)
        encargo = str(plano.get("prompt") or "")
        if encargo and encargo != "(cartela)":
            por_encargo.setdefault(encargo, []).append(pid)
    grupos = [sorted(ids) for ids in por_huella.values() if len(ids) > 1]
    grupos += [sorted(ids) for ids in por_encargo.values() if len(ids) > 1]
    # huella y encargo suelen caer juntos (mismo encargo, mismos bytes):
    # el mismo grupo solo se cuenta UNA vez, o el fallo se lee doble
    vistos, unicos = set(), []
    for grupo in grupos:
        clave = tuple(grupo)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(grupo)
    return unicos


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
    cartas = encuadres.repartir(
        todas, semilla=str(params.get("semilla", 0)), forzadas=forzadas)
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

    # FASE 2 — las imágenes (cuestan dinero). Las cartelas de hoy van
    # SIEMPRE sobre la imagen del plano (`TODAS_SOBRE_IMAGEN`), así que
    # pagan como cualquier otro; solo el fondo negro (en desuso) se
    # libera. Dentro de la tanda, los planos de SITIOS distintos son
    # independientes: corren en CADENAS (una por set, con tope).
    a_pagar = [p for p in planos if not cartelas_motor.sin_imagen(p)]
    con_cartela = [p for p in planos if p.get("cartela")]
    if a_pagar and not imagen_glm.clave(claves):
        raise imagen_glm.ErrorImagen(
            "falta la clave de GLM para imagenes (Configuracion -> claves)")
    pagadas = 0
    # el idioma del vídeo, leído UNA vez: solo sirve para la línea de
    # dato que acompaña a la regla del idioma en el prompt
    idioma = str(proyecto.leer().get("idioma", "es"))
    # el encargo CON el que se dibujó cada plano la vez ANTERIOR: el
    # corrector lo necesita delante para saber qué había antes de la nota
    previo_de_id = {str(p.get("id")): p
                    for p in (anteriores.get("planos") or [])
                    if isinstance(p, dict)}
    # se SIEMBRA lo pagado: un plano recién cortado aún no tiene imagen,
    # pero su id puede ser el de la pasada anterior (el corte se hereda)
    # y lo que hay en su disco ES la imagen que la persona rechazó. Sin
    # esto el corrector no vería ni la rechazada ni a los vecinos
    for plano in planos:
        previo = previo_de_id.get(str(plano.get("id")))
        if isinstance(previo, dict) and previo.get("imagen"):
            plano.setdefault("imagen", previo["imagen"])
    # el contador y el registro del gasto compiten entre cadenas: sin
    # cerrojo se pierden avances y operaciones del medidor
    cerrojo = threading.Lock()

    def dibujar(plano):
        nonlocal pagadas
        trabajo.comprobar_cancelacion()
        sid = plano["escena"]
        escena = next(e for e in escenas if e["id"] == sid)
        with cerrojo:
            pagadas += 1
            numero = pagadas
        # LA NOTA DE LA PERSONA: si esta tanda es la respuesta a un
        # rechazo con nota, el corrector la convierte en encargo antes
        # de redactar el prompt (ver pasos/corrector.py). Si el agente
        # no contesta, la nota viaja pegada al final como siempre.
        corregido = None
        nota_texto = _texto_feedback(
            (unidades.get(sid) or {}).get("feedback"))
        if (nota_texto and solo_escenas is not None
                and _corrector_activo(params)):
            corregido = _corregir_con_agente(
                plano, escena, planos, unidades, params, carpeta, proyecto,
                cartas.get(sid), previo_de_id.get(str(plano["id"])),
                avisar=trabajo.avance)
            if corregido.get("error"):
                trabajo.avance(
                    f"{plano['id']}: el corrector no ha contestado "
                    f"({corregido['error']}); la nota viaja pegada al "
                    "prompt como siempre")
                corregido = None
            else:
                trabajo.avance(
                    f"{plano['id']}: correccion '{corregido['alcance']}' "
                    f"con {len(corregido['referencias'])} referencia(s)")
        trabajo.avance(f"imagen {numero}/{len(a_pagar)}: {plano['id']} "
                       "(cuesta dinero)")
        destino = carpeta / f"{plano['id']}.png"
        encargo = prompt_de(escena, unidades, params,
                            carta=cartas.get(sid), frase=plano["narracion"],
                            idioma=idioma, correccion=corregido)
        imagen_glm.generar(
            encargo, destino, calidad=calidad, claves=claves, estilo="")
        with cerrojo:
            anotar_operacion(
                datos_dir=AJUSTES.datos, proyecto=proyecto.id,
                operacion="imagen", proveedor="glm", modelo="glm-image",
                calidad=calidad, contexto=f"assets:{plano['id']}",
                proyecto_dir=proyecto.raiz)
        plano["imagen"] = f"pasos/assets/imagenes/{plano['id']}.png"
        plano["prompt"] = encargo

    # las cartelas no pagan: se despachan antes de abrir cadenas
    for plano in planos:
        if cartelas_motor.sin_imagen(plano):
            trabajo.avance(f"cartela {plano['id']} "
                           "(plano de texto: no se paga imagen)")
            plano["imagen"] = None
            plano["prompt"] = "(cartela)"
    cadenas = _cuantas_cadenas(params, a_pagar) if len(a_pagar) > 1 else 1
    if cadenas <= 1 or len(a_pagar) <= 1:
        for plano in planos:
            if not cartelas_motor.sin_imagen(plano):
                dibujar(plano)
    else:
        trabajo.avance(f"{cadenas} cadena(s) por sitio, dentro de la tanda")

        def correr_grupo(grupo):
            for plano in grupo:
                if not cartelas_motor.sin_imagen(plano):
                    dibujar(plano)

        with ThreadPoolExecutor(max_workers=cadenas) as piscina:
            futuros = [piscina.submit(correr_grupo, grupo)
                       for grupo in _cadenas_por_set(planos, params)]
            for futuro in futuros:
                futuro.result()

    # EL GUARDIÁN DE PLANOS REPETIDOS: dos planos con la MISMA imagen o
    # el MISMO encargo son un fallo del corte, no de la generación, y
    # tumban la tanda. Las continuaciones (sigue_a) son idénticas POR
    # DISEÑO y la cartela no tiene imagen: no cuentan.
    trabajo.avance("comprobando que no haya planos repetidos")
    copiados = {str(p["id"]) for p in planos if p.get("sigue_a")}
    repetidos = _planos_repetidos(planos, carpeta, copiados=copiados)
    if repetidos:
        detalle = "; ".join(" = ".join(grupo) for grupo in repetidos)
        raise RuntimeError(
            f"dos o mas planos han acabado con la MISMA imagen o el MISMO "
            f"encargo: {detalle}. El corte deberia distinguirlos con la "
            "capa frase: si sale otra vez, es un fallo del corte y no de "
            "la generacion.")

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
            "ritmo": {"minimo": minimo, "maximo": maximo},
            # la semilla con la que se repartió: aparece en el resultado
            # para que se sepa con qué se dibujó esto
            "semilla": comun.desempatar(params.get("semilla", 0),
                                        proyecto.id)}


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
