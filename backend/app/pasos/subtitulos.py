"""Los SUBTÍTULOS: la narración escrita, trozo a trozo, cuando se dice.

Puerto de `pasos/subtitulos.py` del original. Un subtítulo no flota:
vive abajo, centrado, igual en todo el vídeo. Lo único que hay que
calcular es QUÉ DICE y CUÁNDO — aritmética de texto y de tiempo, sin un
píxel, sin cv2 y sin numpy. Se prueba sin generar nada, lo puede leer
la previsualización, y p7 lo importa a él — nunca al revés.

AQUÍ NO HAY QUE EMPAREJAR NADA, Y ESO ES LO QUE LO HACE FIABLE
--------------------------------------------------------------
Una CARTELA destila la narración; un subtítulo NO destila: **es** la
narración. Cada plano trae una marca `[inicio, fin]` por palabra de su
`narracion`.split() (p7 las rebana de las marcas de palabra de la voz),
así que emparejar es la identidad.

Y por eso `tramos` devuelve RANGOS DE ÍNDICES y no cadenas: el tiempo
sale de `marcas[a]` y `marcas[b-1]` y es exacto por construcción — no
hay conteo intermedio que pueda desviarse. El motor del que sale este
troceo devolvía texto y volvía a partirlo para contar palabras; su
propio comentario avisaba de que si un trozo perdía una palabra, TODOS
los subtítulos siguientes se desplazaban.

QUÉ PASA SI NO CUADRA
---------------------
`de_escena` devuelve `[]`. Sin subtítulo antes que con uno descuadrado:
un subtítulo que va medio segundo por detrás de la voz se lee peor que
no tenerlo, y además miente sobre lo único que promete (la misma
disciplina que `cartelas.alinear`).
"""
from __future__ import annotations

import difflib
import re

#: Caracteres por línea, medidos para cuerpo 52 en una banda de 1.400 px
#: de un cuadro de 1080p (recalibrado en el original al sacar la capa
#: del zoom: el cuerpo pasó de px de lienzo a px de salida). En dos
#: líneas cabe cualquier trozo y ninguno roza el borde.
CAP_LINEA = 38

#: UN SUBTITULO SON DOS LINEAS COMO MUCHO. Tres tapan el plano, y a
#: partir de ahí deja de ser un subtítulo para ser un párrafo.
CAP_TROZO = CAP_LINEA * 2

#: Si hay una cláusula donde partir, se parte ya aunque quepa más. Leer
#: dos trozos cortos va con el habla; leer uno largo obliga a volver atrás.
CAP_BLANDO = 62

#: Por debajo de esto un trozo es un HUÉRFANO («En California,» solo) y
#: se funde con el vecino que lo admita. Un subtítulo de tres palabras
#: que parpadea medio segundo se lee peor que no estar.
MIN_TROZO = 16

#: UN HUECO CORTO NO SE VE. Entre dos trozos seguidos la voz respira
#: unas décimas, y quitar el subtítulo para volver a ponerlo es un
#: parpadeo: el trozo anterior se queda puesto HASTA que entra el
#: siguiente. Sólo se queda la pantalla sin subtítulo cuando el silencio
#: es de verdad.
HUECO_SIN_SUBTITULO = 0.4

#: Los tokens que cierran cláusula. El guion suelto va aparte porque es
#: una pausa de dictado, no puntuación pegada a la palabra.
_CIERRA = re.compile(r"[,;:]$")
_GUION = re.compile(r"^[—–-]$")


def _cierra_clausula(token) -> bool:
    token = str(token or "")
    return bool(_CIERRA.search(token) or _GUION.match(token))


def tramos(palabras, cap_linea=CAP_LINEA, cap_blando=CAP_BLANDO,
           min_trozo=MIN_TROZO, cap_trozo=None, intocables=None):
    """[(a, b), ...] rangos de índices sobre `palabras`, sin solapar y cubriendo.

    Cuatro pasos:

      1. se corta en FRONTERA DE CLÁUSULA — detrás de un token que acabe
         en `,;:` o de un guion suelto;
      2. lo que aún no cabe en dos líneas se parte por la mitad, siempre
         en frontera de palabra y eligiendo el corte más parejo, y NUNCA
         por dentro de una cifra (`intocables`, en índices de palabra);
      3. se reagrupa mientras quepa cómodo en una línea;
      4. un huérfano se funde con el vecino que lo admita.

    Devuelve índices y no texto a propósito: ver la cabecera del módulo.
    """
    palabras = list(palabras or [])
    if not palabras:
        return []
    cap_trozo = int(cap_trozo) if cap_trozo else cap_linea * 2
    cap_blando = min(cap_blando, cap_trozo)
    # CON OTRA LÍNEA, LOS OTROS DOS TOPES ESCALAN CON ELLA: con el blando
    # y el huérfano escritos para 38, una línea de 16 no dejaría entrar
    # ningún corte de cláusula y todo trozo sería huérfano. Sólo cuando
    # quien llama no los ha fijado.
    if cap_linea != CAP_LINEA:
        escala = cap_linea / float(CAP_LINEA)
        if cap_blando == CAP_BLANDO:
            cap_blando = max(cap_linea, int(round(CAP_BLANDO * escala)))
        if min_trozo == MIN_TROZO:
            min_trozo = max(6, int(round(MIN_TROZO * escala)))

    def largo(a, b):
        return len(" ".join(palabras[a:b]))

    # 1 · fronteras de cláusula
    rangos, ini = [], 0
    for i, token in enumerate(palabras):
        if i == len(palabras) - 1 or _cierra_clausula(token):
            rangos.append([ini, i + 1])
            ini = i + 1

    # 2 · lo que no cabe se parte por el sitio más parejo
    dentro = set()
    for a_, b_ in (intocables or ()):
        dentro.update(range(a_ + 1, b_))

    def partir(par):
        a, b = par
        if largo(a, b) <= cap_trozo or b - a < 2:
            return [[a, b]]
        mejor, dif = None, None
        for corte in range(a + 1, b):
            if corte in dentro:
                continue
            distancia = abs(largo(a, corte) - largo(corte, b))
            if dif is None or distancia < dif:
                dif, mejor = distancia, corte
        if mejor is None:
            # todo lo que queda es UNA cifra dicha («mil novecientos
            # noventa y seis»): se deja entera aunque pase del tope,
            # porque escrita en número es mucho más corta
            return [[a, b]]
        return partir([a, mejor]) + partir([mejor, b])

    piezas = [trozo for par in rangos for trozo in partir(par)]

    # 3 · se reagrupa mientras quepa cómodo
    salida = []
    for a, b in piezas:
        if salida:
            ultimo = salida[-1]
            junto = largo(ultimo[0], b)
            if (junto <= cap_blando
                    or (largo(ultimo[0], ultimo[1]) < min_trozo
                        and junto <= cap_trozo)):
                ultimo[1] = b
                continue
        salida.append([a, b])

    # 4 · los huérfanos se funden
    i = 0
    while i < len(salida) and len(salida) > 1:
        if largo(salida[i][0], salida[i][1]) >= min_trozo:
            i += 1
            continue
        if i > 0 and largo(salida[i - 1][0], salida[i][1]) <= cap_trozo:
            salida[i - 1][1] = salida[i][1]
            salida.pop(i)
            i = max(0, i - 1)
        elif (i < len(salida) - 1
                and largo(salida[i][0], salida[i + 1][1]) <= cap_trozo):
            salida[i + 1][0] = salida[i][0]
            salida.pop(i)
        else:
            i += 1
    return [(a, b) for a, b in salida]


# ------------------------------------------------- lo dicho con números

#: Los signos que se quedan pegados a una cifra convertida: son
#: puntuación de la frase, no de la palabra. Sustituir «sesenta y cinco.»
#: por «65» a secas se comería el punto y el subtítulo siguiente
#: arrancaría pegado.
_PEGADO_IZQUIERDA = re.compile(r"^[^0-9A-Za-zÀ-ÿ]+")
_PEGADO_DERECHA = re.compile(r"[^0-9A-Za-zÀ-ÿ]+$")

_PUNTUACION = re.compile(r"[^0-9a-záéíóúüñ]+")


def normalizar_texto(texto: str) -> str:
    """La palabra en minúsculas y sin puntuación, para RECONOCERLA."""
    return _PUNTUACION.sub(" ", str(texto or "").lower()).strip()


def _cortes_de(palabras):
    """Los índices detrás de los que el texto crudo lleva puntuación.

    Sirve para que una serie de cifras no se trague dos frases: «dos,
    tres, cuatro veces» son tres cosas y no el número 234. Se mira el
    token CRUDO porque al normalizar la coma desaparece.
    """
    cortes = set()
    for indice, palabra in enumerate(palabras):
        if re.search(r"[,;:.!?…]$", str(palabra or "")):
            cortes.add(indice)
    return cortes


_UNIDADES_ES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3,
    "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
    "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS_ES = {"treinta": 30, "cuarenta": 40, "cincuenta": 50,
               "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
_CIENTOS_ES = {"cien": 100, "ciento": 100, "doscientos": 200,
               "trescientos": 300, "cuatrocientos": 400,
               "quinientos": 500, "seiscientos": 600,
               "setecientos": 700, "ochocientos": 800,
               "novecientos": 900}
_ESCALAS_ES = {"mil": 1_000, "millon": 1_000_000, "millones": 1_000_000,
               "billon": 1_000_000_000_000, "billones": 1_000_000_000_000}


def _valor_de(palabra: str):
    """El valor numérico de una palabra suelta, o None."""
    if palabra in _UNIDADES_ES:
        return _UNIDADES_ES[palabra]
    if palabra in _DECENAS_ES:
        return _DECENAS_ES[palabra]
    if palabra in _CIENTOS_ES:
        return _CIENTOS_ES[palabra]
    if palabra in _ESCALAS_ES:
        return _ESCALAS_ES[palabra]
    if palabra.isdigit():
        return int(palabra)
    return None


def _numero_de(llanas: list[str]) -> int | None:
    """El valor de una serie de palabras numéricas seguidas (español).

    La gramática que cubre es la del guion: unidades, decenas (con su
    «y»), centenas, `mil`, `millones` y `billones`. «mil novecientos
    noventa y seis» -> 1996.
    """
    total, corriente = 0, 0
    for palabra in llanas:
        if palabra in ("y",):
            continue
        if palabra in _ESCALAS_ES:
            escala = _ESCALAS_ES[palabra]
            base = corriente if corriente else 1
            if escala >= 1_000_000:
                # «dos millones tres mil cuatro»: lo acumulado entero
                # multiplica a la escala y arranca grupo nuevo
                total += base * escala
                corriente = 0
            else:
                # «mil» se multiplica por lo que lleva y SIGUE el grupo:
                # «dos mil trescientos» es un solo número
                corriente = base * escala
            continue
        valor = _valor_de(palabra)
        if valor is None:
            return None
        if valor >= 100:
            corriente += valor if corriente else valor
        elif valor >= 30:
            corriente += valor
        else:
            # «treinta y cinco»: la unidad se pega a la decena; «cien
            # cinco» no existe, así que pegar es seguro
            corriente += valor
    return total + corriente if (total or corriente) else None


def cifras_en(dichas, idioma=None, cortes=None):
    """Los tramos que son UNA cifra dicha. -> [(a, cuantas, cifra)]

    La versión compacta en español de `medios.cifras_en` del original
    (allí vive con las tablas del alineador; aquí basta la gramática del
    guion). Respeta `cortes`: una coma entre dos cifras dichas las
    separa, porque «dos, tres, cuatro» son tres cosas.
    """
    dichas = list(dichas or [])
    cortes = cortes or set()
    salida = []
    i = 0
    while i < len(dichas):
        llana = normalizar_texto(dichas[i])
        if _valor_de(llana) is None and llana not in ("y",):
            i += 1
            continue
        # crece mientras sigan siendo palabras numéricas Y no haya un
        # corte de puntuación detrás
        j, numero = i + 1, [llana]
        while j < len(dichas):
            siguiente = normalizar_texto(dichas[j])
            if (j - 1) in cortes:
                break
            if (_valor_de(siguiente) is not None
                    or siguiente in ("y",) and normalizar_texto(dichas[j - 1]) in _DECENAS_ES):
                numero.append(siguiente)
                j += 1
            else:
                break
        valor = _numero_de(numero)
        if valor is not None and (j - i) > (2 if valor < 10 else 0):
            # una palabra suelta que vale menos de 10 es un artículo con
            # pinta de número («un trozo»): no es una cifra dicha
            cifrado = (f"{valor:,}".replace(",", ".")
                       if abs(valor) >= 10000 else str(valor))
            salida.append((i, j - i, cifrado))
        i = j
    return salida


def _cifras_de(palabras, idioma=None):
    """Los tramos de palabras que son UNA cifra dicha. -> [(a, b)]

    La misma cuenta que `limpiar_texto`, para que lo que no se parte sea
    exactamente lo que luego se convierte.
    """
    try:
        return [(a, a + n) for a, n, _ in
                cifras_en(palabras, idioma, _cortes_de(palabras))]
    except Exception:                                          # noqa: BLE001
        return []


def limpiar_texto(palabras, idioma=None):
    """El texto que se DIBUJA a partir de las palabras que se DICEN.

    LO QUE SE DICE CON PALABRAS SE ESCRIBE CON NÚMEROS. El guion va con
    todo en letra porque lo locuta un sintetizador, pero eso es una
    regla de la VOZ: en pantalla, «mil novecientos noventa y seis» se
    lee peor que «1996».

    SE HACE SOBRE EL TROZO YA ELEGIDO, nunca antes: los tiempos salen de
    los ÍNDICES de palabra, así que cambiar el número de palabras antes
    de trocear desplazaría todo lo que viene detrás. Aquí el texto puede
    encoger sin que nada se mueva, porque el trozo ya tiene su `desde` y
    su `hasta`.
    """
    palabras = list(palabras or [])
    if not palabras:
        return ""
    tramos_cifra = cifras_en(palabras, idioma, _cortes_de(palabras))
    por_indice = {t[0]: t for t in tramos_cifra}
    salida, i = [], 0
    while i < len(palabras):
        tramo = por_indice.get(i)
        if not tramo:
            salida.append(palabras[i])
            i += 1
            continue
        _, cuantas, cifra = tramo
        primero, ultimo = str(palabras[i]), str(palabras[i + cuantas - 1])
        izquierda = _PEGADO_IZQUIERDA.search(primero)
        derecha = _PEGADO_DERECHA.search(ultimo)
        salida.append((izquierda.group(0) if izquierda else "") + cifra
                      + (derecha.group(0) if derecha else ""))
        i += cuantas
    return " ".join(salida)


def repartir_escrito(dibujados, texto):
    """El texto corregido a mano, repartido entre los trozos que ya tienen hora.

    LOS TIEMPOS NO SE TOCAN, y por eso esto reparte en vez de volver a
    trocear: el `desde` y el `hasta` de cada trozo salen del ÍNDICE de la
    marca de la palabra hablada, no de contar el texto dibujado. Volver
    a trocear el texto escrito daría otro número de trozos y habría que
    repartir los tiempos a ojo, que es exactamente lo que este módulo
    existe para no hacer.

    Se reparte ALINEANDO, no por proporción: el caso real es corregir
    una palabra («un uno por 100» -> «1%»), así que casi todo el texto
    es idéntico y un alineado deja cada palabra en el trozo donde ya
    estaba. Lo que cambia se queda en el trozo de la palabra que
    sustituye.
    """
    dibujados = [str(t or "") for t in (dibujados or [])]
    texto = " ".join(str(texto or "").split())
    if not dibujados:
        return []
    if not texto:
        return dibujados
    if len(dibujados) == 1:
        return [texto]
    viejas, de_trozo = [], []
    for indice, trozo in enumerate(dibujados):
        for palabra in trozo.split():
            viejas.append(palabra)
            de_trozo.append(indice)
    nuevas = texto.split()
    reparto = [[] for _ in dibujados]
    casador = difflib.SequenceMatcher(
        None, [p.lower() for p in viejas], [p.lower() for p in nuevas],
        autojunk=False)
    for etiqueta, i1, i2, j1, j2 in casador.get_opcodes():
        if etiqueta == "delete":
            continue
        if etiqueta == "equal":
            for salto in range(j2 - j1):
                reparto[de_trozo[i1 + salto]].append(nuevas[j1 + salto])
            continue
        # lo que cambia o lo que se añade va entero al trozo donde
        # EMPEZABA lo que sustituye; si se añade detrás del final, al último
        donde = de_trozo[i1] if i1 < len(de_trozo) else len(dibujados) - 1
        reparto[donde].extend(nuevas[j1:j2])
    return [" ".join(p) for p in reparto]


def de_escena(escena, cap_linea=CAP_LINEA, idioma=None, texto="",
              cap_trozo=None):
    """[{"texto", "desde", "hasta"}] en el reloj DEL PLANO, o [] si no cuadra.

    Aquí la "escena" es el PLANO (nuestro corte de `segmentar`): trae su
    `narracion` (el trozo de la escena que le tocó), sus `marcas`
    ([[inicio, fin]] por palabra, en reloj de la escena) y su ventana
    `t_in`/`t_out`. `desde`/`hasta` salen de la primera y la última
    marca del rango, menos el `t_in` del plano.

    Con `texto` manda lo escrito a mano en vez de lo que sale de la
    narración: existe para corregir una palabra ESCRITA sin regrabar la
    voz. Entra AQUÍ y no antes de trocear, que es lo único que importa:
    después del troceo el texto puede encoger sin que nada se mueva.
    """
    escena = escena if isinstance(escena, dict) else {}
    palabras = str(escena.get("narracion") or "").split()
    marcas = escena.get("marcas") or []
    if not palabras or len(palabras) != len(marcas):
        # LA GUARDA. Sin esto un plano cuyo texto y cuyas marcas no
        # cuadran sacaría el subtítulo desplazado, y un subtítulo
        # desplazado es peor que ninguno.
        return []
    t_in = float(escena.get("t_in") or 0.0)
    rangos = list(tramos(palabras, cap_linea=cap_linea, cap_trozo=cap_trozo,
                         intocables=_cifras_de(palabras, idioma)))
    dibujados = [limpiar_texto(palabras[a:b], idioma) for a, b in rangos]
    if texto:
        dibujados = repartir_escrito(dibujados, texto)
    salida = []
    for (a, b), escrito in zip(rangos, dibujados):
        try:
            desde = float(marcas[a][0]) - t_in
            hasta = float(marcas[b - 1][1]) - t_in
        except (TypeError, ValueError, IndexError):
            return []
        if hasta < desde:
            hasta = desde
        if not escrito:
            # un trozo que se queda sin texto no se dibuja: el override
            # puede ser más corto que lo que sustituye
            continue
        salida.append({"texto": escrito,
                       "desde": round(desde, 3), "hasta": round(hasta, 3)})
    # los huecos cortos se cierran: ver HUECO_SIN_SUBTITULO
    for anterior, siguiente in zip(salida, salida[1:]):
        if 0 <= siguiente["desde"] - anterior["hasta"] < HUECO_SIN_SUBTITULO:
            anterior["hasta"] = siguiente["desde"]
    # y el último llega al final del plano si le falta poco
    try:
        fin_plano = float(escena.get("t_out")) - t_in
    except (TypeError, ValueError):
        fin_plano = None
    if (salida and fin_plano is not None
            and 0 <= fin_plano - salida[-1]["hasta"] < HUECO_SIN_SUBTITULO):
        salida[-1]["hasta"] = round(fin_plano, 3)
    return salida


def dos_lineas(texto, medir, ancho_max):
    """Una línea, o DOS lo más parejas posible. Nunca tres. -> [str, ...]

    `medir(cadena)` devuelve el ancho en píxeles.

    NO se llena la primera línea hasta el tope dejando huérfana la
    última palabra: en un bloque CENTRADO canta. Se elige el corte que
    deja los dos renglones más parejos (medido sobre un vídeo real, el
    desnivel baja de 618-927 px a 17-64).
    """
    texto = " ".join(str(texto or "").split())
    if not texto or medir(texto) <= ancho_max:
        return [texto] if texto else []
    palabras = texto.split()
    if len(palabras) < 2:
        return [texto]
    mejor, dif = 1, None
    for corte in range(1, len(palabras)):
        arriba = medir(" ".join(palabras[:corte]))
        abajo = medir(" ".join(palabras[corte:]))
        # entre dos repartos igual de parejos gana el que no se pase de ancho
        castigo = max(0.0, arriba - ancho_max) + max(0.0, abajo - ancho_max)
        distancia = abs(arriba - abajo) + castigo * 4
        if dif is None or distancia < dif:
            dif, mejor = distancia, corte
    return [" ".join(palabras[:mejor]), " ".join(palabras[mejor:])]


#: CUÁNTO CRECE EL SUBTÍTULO EN VERTICAL, como mucho. El cuerpo (52 px)
#: está pensado para 1080 de alto; en un 1080x1920 que se ve en un
#: móvil, 52 px son la mitad de alto relativo y se leen pequeños. Se
#: escala con el alto del cuadro (1920/1080 = 1,78) con este techo: a
#: 1,78 el subtítulo se comía dos renglones de un tercio de pantalla.
ESCALA_VERTICAL_MAX = 1.35

#: EN VERTICAL EL SUBTÍTULO VA A UN TERCIO DE LA PANTALLA desde abajo,
#: no al pie: en un móvil el pie lo tapan los controles y la mirada
#: está en el centro. Es la fracción del alto que queda por debajo de
#: la línea base.
ALTURA_VERTICAL = 1.0 / 3.0


def es_vertical(salida=None) -> bool:
    """¿El cuadro de salida es más alto que ancho?"""
    return bool(salida) and len(salida) >= 2 \
        and float(salida[1] or 0) > float(salida[0] or 0)


def escala_subtitulo(salida=None) -> float:
    """Por cuánto se multiplica el cuerpo del subtítulo en ESTA salida.

    En vertical el mismo «normal» es más grande, porque la pantalla es
    más alta que ancha (con techo). Quien trocea (`p7.cap_linea_de`) y
    quien dibuja (`p8._subtitulo_png`) tienen que usar ESTA misma
    cuenta: una línea de 38 caracteres calibrada para el cuerpo de
    siempre no cabe en la banda vertical con el cuerpo crecido.
    """
    if not es_vertical(salida):
        return 1.0
    return round(min(ESCALA_VERTICAL_MAX, float(salida[1]) / 1080.0), 2)


def banda_fija(ancho=1920, alto=1080, margen=72, ancho_maximo=1400):
    """Dónde va el subtítulo: EL PIE DEL CUADRO DE SALIDA — o, en
    vertical, a un tercio de la pantalla (ver `ALTURA_VERTICAL`).

    Tres números y ninguna cuenta. El subtítulo vive en el cuadro de
    salida, FUERA del zoom, y ahí no se mueve nada: la deriva es cero
    por construcción, no por cálculo. Ojo con el orden si algún día se
    deshace: esto SOLO vale con la capa fuera del zoom — dentro, el pie
    del cuadro de salida se sale de la imagen en cuanto el zoom entra.
    """
    ancho, alto = float(ancho), float(alto)
    banda = {"suelo": round(alto - float(margen), 1),
             "centro": round(ancho / 2.0, 1),
             "ancho": round(min(float(ancho_maximo), ancho - 2 * float(margen)),
                            1)}
    if es_vertical((ancho, alto)):
        # solo sube el SUELO: el margen lateral (y con él el ancho de
        # la banda) es el de siempre. Pasarle un tercio del alto como
        # margen dejaría la banda con ancho negativo y partiría cada
        # trozo en dos.
        banda["suelo"] = round(alto * (1.0 - ALTURA_VERTICAL), 1)
    return banda
