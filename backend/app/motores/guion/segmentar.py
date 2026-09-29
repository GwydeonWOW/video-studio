"""Corta una narración en planos de duración objetivo, cortando en las pausas.

PUERTO DEL ORIGINAL (`_original/motores/guion/segmentar.py`), adaptado a
las marcas de palabra de este repo: aquí las palabras llegan como
{"palabra", "inicio", "fin"} (la alineación de ElevenLabs) y no como
{"w", "s", "e"} (la de Cartesia). Todo lo demás es el original: la
programación dinámica, las DOS PROHIBICIONES y la escalera de concesiones
van palabra por palabra como estaban, porque cada una nació de un fallo
real medido.

El ritmo de estos vídeos no sale de trocear el texto a ojo: sale de que
la voz ya trae pausas donde hay comas y puntos, y de cortar ahí. Con las
marcas de palabra de la síntesis se sabe el instante exacto de cada
pausa, así que el problema deja de ser editorial y pasa a ser de
optimización.

Se resuelve por programación dinámica en lugar de por avance voraz: un
corte voraz encaja bien los primeros planos y arrastra el error al final,
dejando colas de un segundo. La versión por DP minimiza el coste total,
así que reparte el desajuste en vez de acumularlo.

Coste de un segmento:
    - fuera del rango [minimo, maximo]: prohibido (ver ESCALERA)
    - dentro del rango: penalización suave por alejarse del ideal
    - más la penalización del punto de corte (un punto corta mejor que
      una coma)

Y DOS COSAS QUE NO SON PRECIO SINO PROHIBICIÓN
----------------------------------------------
El coste solo no basta, y el fallo que lo demostró es este: "The seller
had not touched a single one of the bank's own systems. Spain, May of
twenty twenty-four." salió en UN plano. La aritmética: junto costaba
2.8401, partido 3.2853, o sea que partir perdía por 0.4452 — que es
exactamente lo que paga el trozo SANO por no durar el ideal. Añadir un
segmento solo puede SUMAR términos, nunca quitarlos, así que el
optimizador tiene un sesgo estructural a no partir, y con dos frases de
duración parecida el sesgo gana siempre.

Un precio no arregla eso: se calibra para un vídeo y se esquiva en el
siguiente. Así que hay dos reglas duras, sin constante que ajustar:

  1. Un plano NO puede tragarse un punto interior si partir ahí es
     legal, y legal es que las dos mitades caigan en [SUELO_S, TECHO_S] y
     al menos una llegue al mínimo. Esa segunda mitad es la que impide
     romper un plano bueno para fabricar dos malos: dos frases de 2.2 y
     2.5 s siguen siendo un plano.
  2. Un plano no puede cerrar a mitad de frase si dentro lleva un punto
     cuya cabeza se sostiene sola. Es la vieja regla de la huérfana,
     generalizada de "una o dos palabras sueltas" a "lo que sea".

Y SE MIDE LO QUE SE VE, NO LO QUE SE HABLA
------------------------------------------
Las duraciones que se puntúan son las de PANTALLA: un plano entra un poco
antes de su primera palabra y dura hasta que entra el siguiente, así que
los silencios entre frases son suyos (ver `entradas_de`). Puntuando el
habla, el optimizador optimizaba una magnitud que no ve nadie.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Cuánto "cuesta" cortar en cada signo. Un punto es una frontera natural;
# una coma sirve, pero deja la frase partida; cortar donde no hay nada es
# lo peor.
COSTE_CORTE = {
    "fuerte": 0.0,     # . ! ? … y fin de intervención
    "medio": 0.8,      # ; :
    "debil": 1.6,      # ,
    "ninguno": 12.0,   # a mitad de sintagma
}

FUERTE = ".!?…"
MEDIO = ";:"
DEBIL = ","

# La horquilla que se pide es un TOPE, no un precio: un segmento fuera de
# [minimo, maximo] no se considera, y cuando la narración no admite ningún
# reparto así hay tres pasadas de menos a más permisiva (ver ESCALERA) y
# el informe dice por cuál se salió. Nunca se devuelve nada.
#
# Estos dos números son la horquilla POR DEFECTO de quien llame sin decir
# nada: por debajo de dos segundos un plano no da tiempo ni a leerse, y
# por encima de ocho se para el vídeo.
SUELO_S = 2.0
TECHO_S = 8.0

#: Con qué se ha resuelto el último corte. Lo escribe `segmentar` y lo lee
#: `informe`, para que un plan que ha tenido que salirse de la horquilla
#: lo diga en vez de aparecer y ya.
#:
#: Es el respaldo, no el sitio bueno: quien pueda debe pasararle a las dos
#: su propio dict con `reparto=`. Este módulo se carga UNA vez por
#: proceso y lo comparten todos los proyectos, así que dos planificaciones
#: a la vez se pisarían este dict.
ULTIMO_REPARTO = {"maximo_respetado": True, "minimo_respetado": True,
                  "horquilla_respetada": True, "frases_enterradas": False,
                  "minimo": None, "maximo": None, "escalon": 0}

# El plano entra en pantalla un poco ANTES de su primera palabra, y el
# último se lleva una cola. (Del original `voz_cartesia/sincronizar.py`:
# ADELANTO 0.25, COLA 0.45.)
ADELANTO_S = 0.25
COLA_S = 0.45


def tipo_de_corte(palabra) -> str:
    limpia = str(palabra or "").rstrip("\"'")
    if not limpia:
        return "ninguno"
    if limpia[-1] in FUERTE:
        return "fuerte"
    if limpia[-1] in MEDIO:
        return "medio"
    if limpia[-1] in DEBIL:
        return "debil"
    return "ninguno"


def coste_duracion(dur, minimo, maximo, ideal):
    if dur < minimo:
        return 6.0 * (minimo - dur) ** 2
    if dur > maximo:
        return 6.0 * (dur - maximo) ** 2
    return 0.35 * abs(dur - ideal)


def adelanto_de(hueco, corte, adelanto=ADELANTO_S):
    """Cuánto se adelanta un plano sobre su primera palabra.

    En una frontera fuerte el silencio se parte por la mitad entre los dos
    planos. El silencio de un punto no es de nadie, y dárselo entero al
    plano que se va deja al que entra pegado a su propia frase: una
    estampa de dos segundos y pico se quedaba por debajo del mínimo para
    llevar rótulo por culpa de un silencio que estaba ahí mismo, sin
    dueño.

    En una pausa débil no: ahí la frase sigue, y adelantarse media coma se
    lee como que la imagen va por delante de lo que se cuenta.
    """
    if corte == "fuerte":
        return max(adelanto, hueco / 2.0)
    return adelanto


def entradas_de(palabras, adelanto=ADELANTO_S, cola=COLA_S):
    """Instante en que ENTRA en pantalla el plano que empezará en cada palabra.

    Es la magnitud que hay que puntuar, y no la del habla: un plano dura
    hasta que entra el siguiente, así que los silencios entre frases son
    suyos. La lista trae un elemento de más, el final del último plano,
    para que la duración de un segmento sea siempre entradas[fin] -
    entradas[ini].
    """
    if not palabras:
        return []
    cortes = [tipo_de_corte(p["palabra"]) for p in palabras]
    entradas = [max(0.0, float(palabras[0]["inicio"]) - adelanto)]
    for i in range(1, len(palabras)):
        fin_anterior = float(palabras[i - 1]["fin"])
        hueco = float(palabras[i]["inicio"]) - fin_anterior
        # El tope inferior es el final de la palabra anterior: sin él, un
        # silencio largo contaría dos veces (una por cada lado).
        entradas.append(max(0.0, fin_anterior,
                            float(palabras[i]["inicio"])
                            - adelanto_de(hueco, cortes[i - 1], adelanto)))
    entradas.append(float(palabras[-1]["fin"]) + cola)
    return entradas


def _muros_utiles(muros, entradas, n, suelo=SUELO_S):
    """Fronteras que de verdad se pueden respetar.

    Un muro es una frontera de bloque del guion: ahí el redactor cambió de
    idea y la voz deja un silencio de un segundo, así que un plano no
    debería cruzarla. Pero un bloque más corto que el suelo no puede ser
    un plano por sí mismo, y forzarlo sería cambiar un plano con dos ideas
    por uno que no se ve: ese muro se cae, y ese bloque comparte plano con
    el siguiente.
    """
    validos = sorted({int(m) for m in (muros or []) if 0 < int(m) < n})
    utiles, previo = [], 0
    for indice, muro in enumerate(validos):
        siguiente = validos[indice + 1] if indice + 1 < len(validos) else n
        if (entradas[muro] - entradas[previo] >= suelo
                and entradas[siguiente] - entradas[muro] >= suelo):
            utiles.append(muro)
            previo = muro
    return utiles


def _entierra_frase(ini, fin, cortes, entradas, minimo, maximo):
    """True si este segmento se traga una frase que podía ser un plano.

    Las dos prohibiciones de la cabecera, juntas, porque las dos miran lo
    mismo: los puntos que quedan DENTRO del segmento.

    Se miden contra la horquilla PEDIDA. Antes se median contra [2, 8]
    fijos, y eso las volvía incoherentes con el mando: con el mínimo en 1,
    la excepción de la regla 1 se volvía inalcanzable, así que la
    protección cambiaba de comportamiento sin que nadie lo pidiera.
    """
    for k in range(ini, fin - 1):
        if cortes[k] != "fuerte":
            continue
        izq = entradas[k + 1] - entradas[ini]
        der = entradas[fin] - entradas[k + 1]
        # 1. Partir aquí es legal si las dos mitades se sostienen... salvo
        #    en el único caso en que partir empeora el plan: que las dos se
        #    queden cortas Y el plano junto caiga justo en la horquilla
        #    pedida. Dos frases de 2.2 y 2.5 s son un plano de 5 s en su
        #    sitio, y partirlas sería romper un plano bueno para fabricar
        #    dos malos.
        if minimo <= izq <= maximo and minimo <= der <= maximo:
            return True
        # 2. Y aunque la cola no se sostenga sola, cerrar a mitad de frase
        #    teniendo dentro un punto cuya cabeza aguanta es siempre peor:
        #    eso es dejar huérfano el arranque de la frase siguiente.
        if cortes[fin - 1] != "fuerte" and minimo <= izq <= maximo:
            return True
    return False


def segmentar(palabras, minimo=3.0, maximo=6.0, ideal=None,
              adelanto=ADELANTO_S, cola=COLA_S, muros=(), reparto=None):
    """palabras: [{"palabra","inicio","fin"}] en orden.

    Devuelve [(inicio, fin, [palabras])].
    """
    destino = ULTIMO_REPARTO if reparto is None else reparto
    minimo = max(0.1, float(minimo))
    maximo = max(minimo + 0.1, float(maximo))
    if not palabras:
        # también aquí se escribe: heredar el reparto del corte anterior
        # sería describir otro plan
        destino.update({"maximo_respetado": True, "minimo_respetado": True,
                        "horquilla_respetada": True, "frases_enterradas": False,
                        "minimo": minimo, "maximo": maximo, "escalon": 0})
        return []
    ideal = ideal if ideal is not None else (minimo + maximo) / 2
    n = len(palabras)

    cortes = [tipo_de_corte(p["palabra"]) for p in palabras]
    cortes[-1] = "fuerte"                       # el final siempre cierra
    entradas = entradas_de(palabras, adelanto, cola)
    tapias = set(_muros_utiles(muros, entradas, n, suelo=minimo))
    # El vano de UNA palabra más largo que hay. Se usa para que la poda
    # por duración del último escalón no llegue a podar el segmento de una
    # sola palabra: ese es el único que garantiza que siempre exista
    # solución, y si se poda, el DP se queda sin camino y la
    # reconstrucción devuelve un reparto a medias.
    vano_max = max((entradas[i + 1] - entradas[i] for i in range(n)),
                   default=0.0)

    def resolver(estricto, tope_max, tope_min):
        """Reparto óptimo. Los topes hacen de min/max una PROHIBICIÓN."""
        INF = float("inf")
        coste = [INF] * (n + 1)
        origen = [-1] * (n + 1)
        coste[0] = 0.0
        for fin in range(1, n + 1):
            for ini in range(fin - 1, -1, -1):
                dur = entradas[fin] - entradas[ini]
                # con el máximo como tope basta pasarse para dejar de
                # mirar; sin tope, la poda nunca puede llevarse el
                # segmento de una palabra
                if dur > (maximo if tope_max
                          else max(maximo * 2.2, vano_max)):
                    break
                if coste[ini] == INF:
                    continue
                if tope_min and dur < minimo:
                    continue
                if any(ini < muro < fin for muro in tapias):
                    continue
                if estricto:
                    # Un plano no se cierra a mitad de sintagma mientras
                    # haya otra forma: esto estaba ESCRITO en el original
                    # como comentario y no estaba en el código (solo era
                    # un precio). Con el máximo convertido en tope se notó
                    # de golpe.
                    if cortes[fin - 1] == "ninguno":
                        continue
                    if _entierra_frase(ini, fin, cortes, entradas,
                                       minimo, maximo):
                        continue
                c = (coste[ini]
                     + coste_duracion(dur, minimo, maximo, ideal)
                     + COSTE_CORTE[cortes[fin - 1]])
                if c < coste[fin]:
                    coste[fin] = c
                    origen[fin] = ini
        return coste, origen

    # EL MÁXIMO Y EL MÍNIMO NO VALEN LO MISMO, Y POR ESO CEDEN EN ESTE
    # ORDEN. El máximo es un TOPE de verdad y es el último en caer:
    # pediste planos de cuatro segundos y uno de siete es lo que se ve y
    # lo que molesta. El mínimo cede antes, y cede antes que romper una
    # frase por la mitad: un plano medio segundo más corto de lo pedido,
    # o un corte a mitad de sintagma — lo segundo se ve muchísimo peor.
    ESCALERA = (
        (True,  True,  True),    # 0: todo se cumple
        (True,  True,  False),   # 1: algún plano corto, antes que partir una frase
        (False, True,  True),    # 2: se entierra alguna frase, pero la horquilla entera
        (False, True,  False),   # 3: máximo respetado, y ya
        (True,  False, False),   # 4: ni el máximo cabe: se vuelve al precio de siempre
        (False, False, False),   # 5: último recurso, siempre devuelve algo
    )
    for etapa, (estricto, tope_max, tope_min) in enumerate(ESCALERA):
        coste, origen = resolver(estricto, tope_max, tope_min)
        if coste[n] != float("inf"):
            break
    else:
        coste = None
    if coste is None or coste[n] == float("inf"):
        # No debería ocurrir nunca: el último escalón no prohibe nada y la
        # poda ya no alcanza al segmento de una palabra. Si ocurre, se
        # grita: esto manda a generar imágenes, y devolver un reparto a
        # medias en silencio es el peor modo de fallo que hay aquí.
        raise RuntimeError(
            f"no hay ningún reparto posible para {n} palabras con planos "
            f"de {minimo}-{maximo} s")

    limites = []
    fin = n
    while fin > 0:
        ini = origen[fin]
        limites.append((ini, fin))
        fin = ini
    limites.reverse()

    # Se derivan de los FLAGS del escalón que ha ganado, no de índices
    # cableados: con índices, tocar la escalera los deja mintiendo en
    # silencio.
    destino.update({
        "maximo_respetado": tope_max,
        "minimo_respetado": tope_min,
        "horquilla_respetada": tope_max and tope_min,
        "frases_enterradas": not estricto,
        "minimo": minimo, "maximo": maximo, "escalon": etapa,
    })
    return [(float(palabras[i]["inicio"]), float(palabras[j - 1]["fin"]),
             palabras[i:j])
            for i, j in limites]


#: Cuánto cuadro se ve con el zoom CERRADO, en fracción del plano entero.
#: El zoom tiene que empujar el plano sin que se vea empujar.
CIERRE = 0.95

#: La escala que pide el recorte del render, que muestra 1/escala de cuadro.
ESCALA_CERRADA = round(1.0 / CIERRE, 4)


def alternar_zoom(indice, ancla=None):
    """Alterna acercar y alejar plano a plano.

    Alternar no es un capricho estético: dos zooms seguidos en la misma
    dirección se leen como un único movimiento largo y el corte entre
    ellos desaparece.
    """
    if indice % 2 == 0:
        return {"tipo": "in", "ancla": ancla, "de": 1.0, "a": ESCALA_CERRADA}
    return {"tipo": "out", "ancla": ancla, "de": ESCALA_CERRADA, "a": 1.0}


def transicion_para(indice, corte):
    """Qué RANURA de transición deja este corte. Suave como norma.

    Devuelve una de tres: 'corte', 'suave' o 'acento'. QUÉ transición
    concreta ocupa cada ranura no se decide aquí sino al renderizar
    (pasos/transiciones.py). La separación es por dinero: dónde va un
    acento pertenece al CORTE y viaja en el plan.

    Encadenar a media frase es lo que hace que un montaje parezca un pase
    de diapositivas: si la frase no ha terminado, se corta. Determinista
    por índice, como todo lo del corte. El único corte seco de un vídeo es
    el del PRIMER plano, y ese no es una transición: no hay nada de lo
    que venir (lo pone transiciones.resolver).
    """
    if corte == "fuerte" and indice % 5 == 2:
        return "acento"
    return "suave"


#: Cuánto del texto tiene que reconocerse para que herede el corte de
#: antes. Por debajo ya no es «el mismo guion con otra voz» sino otro
#: texto, y entonces se corta de cero.
RECONOCIDO_MINIMO = 0.5


def _limpia(palabra):
    """La palabra a secas, para comparar: sin puntuación, sin tildes.

    Sin esto, «mes.» y «mes» son dos palabras distintas y el corte no se
    reconoce justo donde más falta hace: en el límite de un plano, que es
    donde caen los puntos.
    """
    s = unicodedata.normalize("NFD", str(palabra or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


def heredar(palabras, previas, adelanto=ADELANTO_S, cola=COLA_S, maximo=None,
            minimo=None, reparto=None):
    """El corte de antes puesto sobre las palabras de ahora.

    POR QUÉ. El corte se decide con las MARCAS DE PALABRA, así que depende
    de los milisegundos de la voz. Y una voz sintetizada dos veces no da
    los mismos milisegundos: regrabar la misma frase mueve las marcas
    ochenta milésimas y el reparto óptimo cambia de 222 planos a 217. El
    texto era el mismo palabra por palabra. Nada de eso lo pidió nadie, y
    arrastra detrás a todas las imágenes, que se guardan por el número del
    plano.

    El optimizador no está mal: dadas OTRAS duraciones, otro reparto es
    efectivamente mejor. Lo que está mal es volver a preguntárselo. Si el
    guion no ha cambiado, el corte ya estaba decidido y esto solo lo
    vuelve a colocar sobre los tiempos nuevos, que es lo único que de
    verdad cambió.

    `previas` aquí son los PLANOS anteriores de la misma escena, cada uno
    como dict con su "narracion".
    """
    if not palabras or not previas:
        return []
    nuevas = [_limpia(p["palabra"]) for p in palabras]
    viejas, limites = [], []
    for escena in previas:
        trozo = [_limpia(w) for w in str(escena.get("narracion") or "").split()]
        if not trozo:
            continue
        viejas.extend(trozo)
        limites.append(len(viejas))
    if not viejas or len(limites) < 2:
        return []

    pares = difflib.SequenceMatcher(None, viejas, nuevas,
                                    autojunk=False).get_matching_blocks()
    mapa, reconocidas = {}, 0
    for a, b, n in pares:
        reconocidas += n
        for k in range(n):
            mapa[a + k] = b + k
    if reconocidas < RECONOCIDO_MINIMO * len(nuevas):
        return []

    fronteras = set()
    for limite in limites[:-1]:
        if limite in mapa:
            fronteras.add(mapa[limite])
            continue
        # LA SIGUIENTE QUE NO SE TOCÓ: se corta donde empieza ella.
        siguiente = next((i for i in range(limite, len(viejas))
                          if i in mapa), None)
        if siguiente is not None:
            fronteras.add(mapa[siguiente])
            continue
        # y si no queda nada por delante, justo detrás de lo último
        # reconocido
        anterior = next((i for i in range(limite - 1, -1, -1)
                         if i in mapa), None)
        if anterior is not None:
            fronteras.add(mapa[anterior] + 1)
    cortes = sorted(i for i in fronteras if 0 < i < len(nuevas))

    entradas = entradas_de(palabras, adelanto, cola)
    trozos, ini = [], 0
    for fin in cortes + [len(nuevas)]:
        if fin > ini:
            trozos.append((ini, fin))
            ini = fin

    # UN HUECO SE CORTA, NO SE TRAGA. Lo que se haya escrito de cero no se
    # reconoce y se queda pegado al plano vecino, que puede acabar durando
    # media escena. Ese plano —y solo ese— vuelve a pasar por el
    # optimizador.
    segmentos = []
    for ini, fin in trozos:
        largo = entradas[fin] - entradas[ini]
        if maximo and largo > 2.0 * float(maximo) and fin - ini > 1:
            dentro = segmentar(palabras[ini:fin], maximo / 2.0, maximo,
                               adelanto=adelanto, cola=cola, reparto={})
            for _a, _b, trozo in dentro:
                segmentos.append(trozo)
            continue
        segmentos.append(palabras[ini:fin])

    # LOS TIEMPOS, CRUDOS, igual que los devuelve `segmentar`: quien
    # recibe esto vuelve a restar el adelanto y a sumar la cola por medio
    # de `entradas_de`. Devolverlos ya sumados alargaba el vídeo y lo
    # descuadraba con el audio.
    salida, i = [], 0
    for trozo in segmentos:
        j = i + len(trozo)
        salida.append((float(trozo[0]["inicio"]),
                       float(trozo[-1]["fin"]), trozo))
        i = j

    # SE DICE LO QUE SALIÓ, MEDIDO. Un corte heredado puede perfectamente
    # salirse: hereda las FRONTERAS, y con una voz más lenta el mismo
    # trozo dura más.
    if reparto is not None:
        cortes_i, k = [0], 0
        for _ini, _fin, trozo in salida:
            k += len(trozo)
            cortes_i.append(k)
        duraciones = [entradas[b] - entradas[a]
                      for a, b in zip(cortes_i, cortes_i[1:])]
        bajo = float(minimo) if minimo else None
        alto = float(maximo) if maximo else None
        reparto.update({
            "heredado": True,
            "maximo_respetado": (not alto
                                 or all(d <= alto + 0.05 for d in duraciones)),
            "minimo_respetado": (not bajo
                                 or all(d >= bajo - 0.05 for d in duraciones)),
            "horquilla_respetada": (not (bajo and alto)
                                    or all(bajo - 0.05 <= d <= alto + 0.05
                                           for d in duraciones)),
            "frases_enterradas": False,
            "minimo": bajo, "maximo": alto, "escalon": 0,
        })
    return salida


def frases_dentro(narracion):
    """Cuántas frases se cierran DENTRO de un plano, sin contar la última."""
    palabras = str(narracion or "").split()
    return sum(1 for w in palabras[:-1] if tipo_de_corte(w) == "fuerte")


def informe(planos, minimo, maximo, reparto=None):
    """Los números del corte, MEDIDOS sobre lo que se guarda.

    Un informe que no mide lo que se guarda no sirve para vigilar nada:
    calculaba 6.69 s de plano más largo cuando el plano más largo del
    mismo fichero medía 7.34.
    """
    hecho = ULTIMO_REPARTO if reparto is None else reparto
    duraciones = [p["duracion"] for p in planos]
    fuera = [p for p in planos
             if p["duracion"] < minimo - 0.05 or p["duracion"] > maximo + 0.05]
    reparto_cortes = {}
    for p in planos:
        reparto_cortes[p["corte"]] = reparto_cortes.get(p["corte"], 0) + 1
    # Un plano con dos frases dentro y una frase repartida entre dos
    # planos son las dos formas de que el corte no case con lo que se
    # cuenta. Se cuentan y se nombran.
    con_varias = [p["id"] for p in planos
                  if frases_dentro(p.get("narracion")) > 0]
    partidas = [p["id"] for p in planos if p.get("corte") != "fuerte"]
    return {
        "planos": len(planos),
        "duracion_media": round(sum(duraciones) / len(duraciones), 2)
        if duraciones else 0,
        "duracion_min": round(min(duraciones), 2) if duraciones else 0,
        "duracion_max": round(max(duraciones), 2) if duraciones else 0,
        "fuera_de_rango": len(fuera),
        "fuera_de_rango_ids": [p["id"] for p in fuera],
        "horquilla": [minimo, maximo],
        "horquilla_respetada": bool(hecho.get("horquilla_respetada", True)),
        "maximo_respetado": bool(hecho.get("maximo_respetado", True)),
        "minimo_respetado": bool(hecho.get("minimo_respetado", True)),
        "frases_enterradas": bool(hecho.get("frases_enterradas", False)),
        "cortes_a_mitad_de_frase": reparto_cortes.get("ninguno", 0),
        "cortes_por_tipo": reparto_cortes,
        "planos_con_varias_frases": len(con_varias),
        "planos_con_varias_frases_ids": con_varias,
        "frases_partidas": len(partidas),
        "frases_partidas_ids": partidas,
    }
