"""Qué hay que rehacer cuando alguien corrige el estilo gráfico con una frase.

POR QUÉ EXISTE
--------------
Corregir el estilo gráfico corría SIEMPRE las tareas de la parte —la guía,
las láminas, el grafismo y las muestras— pasara lo que pasara en la frase.
Y la frase que lo destapó fue:

    «quería retocar SOLO la opacidad del rectángulo de fondo de los
     subtítulos»

Eso son dos números en un fichero de params. Lo que hizo el Estudio fue
reescribir la guía entera y dibujar seis imágenes de cero para acabar
poniendo el mismo subtítulo encima.

Aquí se lee la frase ANTES de correr nada y se decide con qué basta.

EL MOLDE ES `repaso.py`, y a propósito
--------------------------------------
El repaso ya hace esto mismo con las notas escritas mirando el vídeo
montado: un vocabulario CERRADO de cambios, cada uno con lo que hay que
rehacer, y una salida legítima para «esto no lo sé tocar». Se le copia la
forma entera, incluida la parte que más cuesta acertar: al modelo se le
dice la CONSECUENCIA de inventarse un destino, no solo la prohibición.

LAS TRES REGLAS
---------------
1. **Cada retoque escribe en un cajón que alguien LEE.** El vocabulario de
   aquí abajo lleva escrito, por cada entrada, quién lee lo que escribe.
   Una entrada cuyo lector no se pueda nombrar no entra aquí: los tres
   SETS_DISENO podrían declarar una clave `opacidad` que no lee nadie, y
   un enrutador ingenuo enrutará ahí la frase de arriba, correría tres
   segundos, y el vídeo saldría idéntico con la corrección marcada como
   aplicada. Ese es el fallo mudo.

2. **Ante la duda SE AMPLÍA, y se dice.** No es simétrico: las tareas
   baratas son deterministas, así que quedarse corto no da un arreglo a
   medias, da CERO cambio con cara de éxito — y quien lo pidió reescribe
   la misma frase y vuelve a no pasar nada. Pasarse da lo de hoy: caro,
   pero coherente y visible. El respaldo es `todo`, que es exactamente
   el comportamiento anterior: si el enrutador no sabe, no se pierde nada
   respecto a antes.

3. **Pasarse tampoco es gratis, así que se avisa.** Rehacer la guía es
   una llamada no determinista que puede devolver otro trazo; las seis
   láminas se redibujan, se auto-aprueban sin que nadie las mire, y como
   el banco de moodboards se indexa por el CONTENIDO de los fotogramas,
   le cambia el estilo a cualquier otro preset construido sobre el mismo
   vídeo.

UNA LÁMINA NO ES EL ESTILO
--------------------------
La segunda frase que destapó algo fue esta, escrita mirando las seis
muestras:

    «que de las 6 referencias en UNA haya monos variados vestidos de
     formas distintas... pero SOLO para una referencia, el resto
     manténlas»

Aquí no había nada que ahorrar: es un cambio de dibujo y hay que dibujar.
Lo que fallaba era el destino. El único retoque que tocaba lo dibujado
era `dibujo`, que reescribe la guía y redibuja LAS SEIS — o sea que la
única forma de arreglar la lámina que no gustaba era tirar las cinco que
sí, y además por una llamada no determinista que devuelve otro trazo.

Y no hacía falta motor nuevo: `moodboard.generar` sabe rehacer un eje
suelto con una petición escrita desde el primer día — se escribió justo
para esto, porque en la práctica derivan unos ejes y otros salen clavados
— y `aprobar` copia eje a eje. Lo que faltaba era la palabra en el
vocabulario y el camino desde la frase hasta ese argumento.

De ahí salen las dos cosas que este módulo tiene que acertar, y son
distintas:

  QUÉ es una sola     lo dice la frase, casi siempre con todas las letras
                      («solo en una», «el resto déjalas como están»)
  CUÁL es esa una     no lo dice: hay que sacarlo de lo que se VE en cada
                      lámina. Por eso el vocabulario le enseña al modelo
                      la descripción en crudo con la que se dibujó cada
                      eje (`_ejes_legibles`), y el estado le enseña las
                      que este estilo tiene hoy, numeradas en el orden en
                      que se ven — que no es el mismo en los dos caminos
                      — para que «la segunda» tampoco sea una adivinanza.

El error caro aquí es el simétrico del de la regla 2, y por eso se avisa
aparte: mandar a UNA lámina un cambio que valía para las seis no deja las
cosas como estaban, deja cinco láminas con un estilo y una con otro.
Ampliar sigue siendo lo seguro; acotar solo se hace cuando la frase acota.

LO QUE NO HACE
--------------
No aplica nada. Devuelve QUÉ tareas y QUÉ params, y quien lo llamó los
escribe. Repartir y aplicar son dos cosas, y juntarlas hace imposible
enseñar lo que va a pasar antes de que pase.
"""
from __future__ import annotations

import time

from ..motores import llm
from ..nucleo import grafismo
from . import comun, moodboard

PASO = "enrutar_estilo"

SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor y sin vallas de markdown.")

# ===========================================================================
# EL VOCABULARIO
#
# Cada entrada dice QUÉ es, QUÉ tareas dispara, QUÉ params escribe y --lo que
# de verdad la hace válida-- QUIÉN LEE esos params. Una entrada cuyo lector
# no se pueda nombrar no entra aquí.
#
#   tareas    ids de `rutas_presets._TAREAS`. `muestra` va en TODAS las que
#             tocan algo visible: es lo único que rasteriza cartela y
#             subtítulo con el mismo código que el vídeo, o sea lo único
#             donde el cambio SE VE. Sin ella la tarjeta sigue enseñando lo
#             anterior y no hay forma de distinguir «no hizo nada» de «hizo
#             algo y no me lo enseña».
#   campos    lo que el modelo tiene que rellenar, y que se valida aquí
#   imágenes  cuántas paga. Es la cifra que se enseña antes de pulsar.
# ===========================================================================

RETOQUES = {
    "caja_subtitulo": {
        "que_es": "cuánto tapa el velo de detrás del subtítulo, de 0 "
                  "(sin caja) a 1 (opaco). Baja la caja, súbela o quítala.",
        "ejemplos": ["baja la opacidad del rectángulo del subtítulo",
                     "el fondo del subtítulo tapa demasiado",
                     "quita la caja de detrás de los subtítulos"],
        "tareas": ("grafismo", "muestra"),
        "campos": ("valor",),
        "imagenes": 0,
        "params": "callouts.subtitulo_caja",
        "lo_lee": "p7_callouts.opacidad_de_caja, que lo aplica al velo de "
                  "la caja al dibujar el subtítulo (p8_render)",
    },
    "tamano_subtitulo": {
        "que_es": "de qué tamaño se escribe el subtítulo: pequeno, normal "
                  "o grande.",
        "ejemplos": ["el subtítulo es muy pequeño",
                     "letra más grande abajo"],
        "tareas": ("grafismo", "muestra"),
        "campos": ("valor",),
        "imagenes": 0,
        "params": "callouts.subtitulo_tam",
        "lo_lee": "p7_callouts.cap_linea_de y grafismo.tamano_de, de ahí "
                  "el cuerpo del texto y los caracteres por línea",
    },
    "set_grafismo": {
        "que_es": "con qué familia se dibuja el texto en pantalla: pastilla "
                  "(texto claro sobre pastilla oscura redondeada), barra "
                  "(barra del color de acento a la izquierda), pleno (banda "
                  "del ancho entero al pie) o sombra (sin caja: texto con "
                  "sombra suave).",
        "ejemplos": ["los rótulos son demasiado infantiles",
                     "quiero las cartelas más sobrias",
                     "sin caja, el texto que flote sobre la imagen"],
        "tareas": ("grafismo", "muestra"),
        "campos": ("valor",),
        "imagenes": 0,
        "params": "callouts.diseno",
        "lo_lee": "p7_callouts (diseno -> grafismo.SETS_DISENO), y de ahí "
                  "todo el envoltorio del texto",
    },
    "una_referencia": {
        "que_es": "UNA sola de las seis referencias dibujadas. Se redibuja ESA "
                  "y las otras cinco se quedan exactamente como están, con la "
                  "guía sin tocar. Hay que decir CUÁL (`eje`) y QUÉ cambiarle "
                  "(`peticion`).",
        "ejemplos": ["en la de los tres cuerpos, que vayan vestidos de formas "
                     "distintas y no todos con traje",
                     "solo en una quiero gente más variada, el resto déjalas",
                     "la del despacho tiene demasiados muebles",
                     "el objeto de cerca sale cortado"],
        "tareas": ("referencias", "muestra"),
        "campos": ("eje", "peticion"),
        "imagenes": 1,
        "params": "— viaja en el encargo de ESTA pasada, no en los params",
        "lo_lee": "moodboard.generar, por sus argumentos `ejes` y "
                  "`peticiones`: la petición entra en el prompt de esa "
                  "lámina y en ninguna otra",
    },
    "dibujo": {
        "que_es": "cómo se DIBUJA el vídeo: el trazo, el color, los "
                  "personajes, los fondos, la luz. Esto reescribe la guía de "
                  "estilo y vuelve a dibujar las seis láminas.",
        "ejemplos": ["el trazo es demasiado fino",
                     "los personajes tienen la cara rara",
                     "quiero los fondos con menos detalle"],
        "ojo": "redibuja LAS SEIS. Las cinco que ya gustaban no vuelven.",
        "tareas": ("guia", "referencias", "grafismo", "muestra"),
        "campos": (),
        "imagenes": 6,
        "params": "assets (guia de estilo: lo escribe la tarea, no este "
                  "enrutador)",
        "lo_lee": "guia_estilo.bloque_de_estilo, en el prompt de cada plano",
    },
    "todo": {
        "que_es": "no está claro qué toca, o la frase pide varias cosas a la "
                  "vez. Se rehace el estilo gráfico entero. **Es una salida "
                  "legítima**: es lo que se hacía siempre antes de existir "
                  "este reparto, así que elegirla no empeora nada.",
        "ejemplos": ["que se parezca más al vídeo de referencia",
                     "no me convence, dale otra vuelta"],
        "tareas": ("guia", "referencias", "grafismo", "muestra"),
        "campos": (),
        "imagenes": 6,
        "params": "—",
        "lo_lee": "—",
    },
    "sin_mando": {
        "que_es": "lo que se pide no se puede tocar desde aquí: no hay ningún "
                  "mando para eso. **Es una salida legítima y mejor que "
                  "forzar un cambio que no toca**: se dice y no se gasta nada.",
        "ejemplos": ["pon el subtítulo arriba del todo",
                     "que el logo salga en la esquina"],
        "tareas": (),
        "campos": ("porque",),
        "imagenes": 0,
        "params": "—",
        "lo_lee": "—",
    },
}

#: Lo que puede valer cada retoque que lleva `valor`. Se valida contra esto y
#: no contra el texto libre: un valor inventado es un param que nadie lee.
VALORES = {
    "tamano_subtitulo": tuple(grafismo.SUB_TAMANOS),
    "set_grafismo": tuple(grafismo.SETS_DISENO),
}

#: El respaldo cuando algo no cuadra. Es el comportamiento de SIEMPRE, así
#: que caer aquí no es una regresión: es no haber mejorado esta vez.
RESPALDO = "todo"

#: EL RETOQUE QUE TOCA UNA LÁMINA Y NO LAS SEIS, nombrado una vez porque son
#: TRES los sitios que tienen que estar de acuerdo -- `_limpiar` lo valida,
#: `laminas_de` lo recoge y `resumen_de` lo cuenta --. Escrito a mano en cada
#: uno, el día que cambie el nombre `laminas_de` devuelve un cajón vacío, la
#: tarea corre igual y redibuja las seis: el fallo mudo, otra vez.
UNA_LAMINA = "una_referencia"

#: Los ejes que existen. Se leen de `moodboard` y no se copian aquí: un eje
#: inventado sería una corrección escrita para una lámina que no existe -- la
#: tarea correría, no fallaría, y no cambiaría nada.
EJES = moodboard.EJES


def catalogo():
    """Lo que la pantalla necesita saber de esto, sin abrir el módulo."""
    return {rid: {"que_es": ficha["que_es"], "imagenes": ficha["imagenes"],
                  "tareas": list(ficha["tareas"])}
            for rid, ficha in RETOQUES.items()}


def _imagenes(cuantas):
    """«imagen» o «imágenes». Una lámina suelta cuesta UNA, y decir «1
    imágenes» en la frase que enseña el precio antes de pulsar canta
    demasiado."""
    return "imagen" if cuantas == 1 else "imágenes"


def _ejes_legibles():
    """Las seis láminas y QUÉ HAY DIBUJADO EN CADA UNA. -> str

    Con la descripción en crudo que se le pasó al generador, no solo el
    título: es lo único que permite que «la que salen tres monos» caiga en
    `cuerpos` sin que nadie mire la imagen. «Varias personas de cuerpo
    entero» dice qué es el eje; «three ordinary people standing side by
    side» dice qué se ve.

    SIN NUMERAR, y a propósito: el orden en el que se ven depende del
    estilo — el moodboard va por orden alfabético de eje y las láminas de
    un estilo descrito van en el orden de `EJES` — así que un número
    escrito aquí sería un número inventado para la mitad de los casos, y
    «la tercera» acabaría cayendo en la lámina de al lado. La numeración
    de verdad la trae el bloque de estado, que es el único que la sabe.
    """
    return "\n".join(
        f"      {eje}: {ficha['titulo']} — {ficha['prompt']}"
        for eje, ficha in EJES.items())


def _legible():
    """El vocabulario tal y como se le enseña al modelo."""
    lineas = []
    for rid, ficha in RETOQUES.items():
        coste = ("no cuesta ninguna imagen" if not ficha["imagenes"]
                 else f"cuesta {ficha['imagenes']} {_imagenes(ficha['imagenes'])}")
        lineas.append(f"- {rid}: {ficha['que_es']} ({coste})")
        if ficha.get("ojo"):
            lineas.append(f"    OJO: {ficha['ojo']}")
        if rid == UNA_LAMINA:
            lineas.append("    `eje` es una de estas seis, y no hay más:")
            lineas.append(_ejes_legibles())
        if ficha["campos"]:
            lineas.append(f"    campos: {', '.join(ficha['campos'])}")
        if rid in VALORES:
            lineas.append(f"    valor tiene que ser uno de: "
                          f"{', '.join(VALORES[rid])}")
        for ejemplo in ficha["ejemplos"]:
            lineas.append(f"    ej. «{ejemplo}»")
    return "\n".join(lineas)


INSTRUCCION = """Eres quien recoge una corrección sobre el ESTILO GRÁFICO de un
canal de vídeo y decide QUÉ hay que rehacer para aplicarla.

No aplicas nada: repartes. Lo que devuelvas decide cuánto se gasta.

=====================================================================
LO QUE HA ESCRITO
=====================================================================
"{frase}"

=====================================================================
CÓMO ESTÁ EL CANAL AHORA
=====================================================================
{estado}

=====================================================================
LOS RETOQUES QUE EXISTEN, Y NO HAY MÁS
=====================================================================
{retoques}

=====================================================================
CÓMO ELEGIR
=====================================================================

1. LO MÁS BARATO QUE RESUELVE DE VERDAD LO QUE PIDE. Si con cambiar un mando
   del texto en pantalla se arregla, ese es el retoque: rehacer el dibujo
   entero cuesta seis imágenes y no lo arreglaría mejor.

2. PERO SOLO SI DE VERDAD LO RESUELVE. Quedarse corto es peor que pasarse, y
   por un motivo concreto: los retoques baratos son deterministas, así que si
   eliges mal no sale un arreglo a medias — sale EXACTAMENTE lo mismo que
   había, con el cambio marcado como aplicado. Quien lo pidió lo mira, ve que
   no ha pasado nada, y vuelve a escribir la misma frase.

3. SI LA FRASE HABLA DE CÓMO SE DIBUJA —el trazo, el color, las caras, los
   fondos, la luz, los personajes— es `dibujo`. Eso no se arregla con ningún
   mando de texto.

4. PERO SI SEÑALA UNA SOLA DE LAS SEIS REFERENCIAS, ES `una_referencia` Y NO
   `dibujo`. Las seis láminas no son el estilo: son seis dibujos distintos que
   enseñan el mismo estilo, y se pueden tocar de una en una.

   La señal de que es una sola está casi siempre escrita, y en estas formas:
     · lo dice con todas las letras — «solo en una», «solo para una
       referencia», «el resto déjalas como están», «las demás están bien»;
     · la nombra por lo que se ve en ella — «la de los tres cuerpos», «la del
       despacho», «la de la calle», «la de la cara», «la del diagrama»;
     · o la nombra por su sitio — «la segunda», «la tercera». En ese caso el
       orden es el del bloque CÓMO ESTÁ EL CANAL AHORA, que las lista
       numeradas; si ahí no hay lista, no adivines el número: `todo`.

   Cuál es cuál se decide comparando lo que dice la frase con lo que hay
   DIBUJADO en cada eje, que está escrito en el vocabulario. Tres personas de
   pie es `cuerpos`; una habitación con muebles es `interior`; una calle es
   `exterior`; una cara de cerca es `cara`; un objeto sobre una superficie es
   `objeto`; tres cajas con flechas es `diagrama`.

   En `peticion` va lo que hay que cambiarle a ESA lámina, con las palabras de
   quien lo pidió y sin lo que sobra: de «que en una haya gente variada, rica,
   pobre, joven, vieja, y no todos con traje, pero solo en una» la petición es
   «gente variada — rica, pobre, joven, vieja — y no todos con traje», no la
   parte de «solo en una», que ya la dice el retoque.

   Cuesta UNA imagen en vez de seis, pero eso es lo de menos: es lo único que
   respeta un «el resto déjalas como están». `dibujo` las redibuja las seis, y
   las cinco que ya gustaban no vuelven.

5. Y AL REVÉS, QUE ES EL ERROR CARO: si el cambio vale para TODAS —el trazo,
   la paleta, la luz, cómo se resuelven las caras— y lo mandas a una sola,
   salen cinco láminas con un estilo y una con otro. Eso no es quedarse corto:
   es un estilo incoherente, marcado como aplicado, y el vídeo lo hereda. Un
   cambio de dibujo solo es `una_referencia` si la frase acota a una lámina;
   si no acota, es `dibujo`.

6. SI NO ESTÁS SEGURO, `todo`. Es una salida legítima: es lo que se hacía
   siempre antes de que existiera este reparto, así que elegirla no empeora
   nada. Adivinar sí.

7. SI LO QUE PIDE NO TIENE MANDO, `sin_mando`, y escribe en `porque` qué es lo
   que no se puede tocar. También es una salida legítima, y es mejor que
   forzar un retoque que no toca: así se dice en vez de gastar cuatro minutos
   para nada.

8. UN RETOQUE QUE NO ESTÉ EN LA LISTA DE ARRIBA NO EXISTE. Si devuelves uno
   inventado, se descarta entero y se rehace el estilo completo — o sea que
   inventarlo cuesta seis imágenes y no aplica lo que pediste. Lo mismo con un
   `valor` que no esté entre los permitidos, con un `eje` que no sea uno de
   los seis, y con un `una_referencia` sin `peticion`: una lámina redibujada
   sin decirle qué cambiar sale otra vez igual de genérica.

9. LA FRASE PUEDE PEDIR VARIAS COSAS. Si son varias y todas son mandos
   baratos, devuélvelas todas. Si nombra dos láminas distintas, devuelve dos
   `una_referencia`, cada una con su `eje` y su `peticion`. Si alguna es del
   dibujo entero, con `dibujo` basta: ya rehace el grafismo y las muestras
   detrás, y también las seis láminas — así que no lo mezcles con
   `una_referencia`, que quedaría de adorno.

=====================================================================
DEVUELVE SOLO ESTE JSON
=====================================================================
{{"retoques": [
   {{"retoque": "uno de los ids de arriba",
     "valor": "solo si ese retoque lleva `valor`; para caja_subtitulo es un
               número de 0 a 1",
     "eje": "solo para una_referencia: cuál de las seis láminas",
     "peticion": "solo para una_referencia: qué cambiarle a ESA lámina",
     "porque": "una frase corta: por qué ESTE y no otro. Para sin_mando, qué
                es lo que no se puede tocar."}}
 ]}}
"""


def _numero(valor):
    try:
        return max(0.0, min(1.0, float(str(valor).replace(",", "."))))
    except (TypeError, ValueError):
        return None


def _limpiar(datos):
    """Lo que devolvió el modelo, dejado en algo que se puede correr.

    -> (retoques, avisos)
    """
    if not isinstance(datos, dict):
        return [], ["la respuesta del motor no tenía forma de reparto: se "
                    "rehace el estilo entero"]
    salida, avisos = [], []
    for cruda in (datos.get("retoques") or []):
        if not isinstance(cruda, dict):
            continue
        rid = str(cruda.get("retoque") or "").strip()
        if rid not in RETOQUES:
            avisos.append(f"el motor propuso «{rid or 'nada'}», que no existe: "
                          f"se rehace el estilo entero")
            return [], avisos
        ficha = RETOQUES[rid]
        entrada = {"retoque": rid,
                   "porque": " ".join(str(cruda.get("porque") or "").split()),
                   "tareas": list(ficha["tareas"]),
                   "imagenes": ficha["imagenes"]}
        if "valor" in ficha["campos"]:
            crudo = cruda.get("valor")
            if rid in VALORES:
                valor = str(crudo or "").strip().lower()
                if valor not in VALORES[rid]:
                    avisos.append(
                        f"«{crudo}» no vale para {rid} (tiene que ser uno de "
                        f"{', '.join(VALORES[rid])}): se rehace el estilo "
                        f"entero")
                    return [], avisos
            else:
                valor = _numero(crudo)
                if valor is None:
                    avisos.append(f"«{crudo}» no es un número de 0 a 1: se "
                                  f"rehace el estilo entero")
                    return [], avisos
            entrada["valor"] = valor
        if "eje" in ficha["campos"]:
            eje = str(cruda.get("eje") or "").strip().lower()
            if eje not in EJES:
                avisos.append(
                    f"«{eje or 'nada'}» no es ninguna de las seis referencias "
                    f"(son {', '.join(EJES)}): se rehace el estilo entero")
                return [], avisos
            entrada["eje"] = eje
        if "peticion" in ficha["campos"]:
            # SIN CORRECCIÓN NO HAY CORRECCIÓN. Redibujar una lámina con su
            # descripción genérica y nada más sale otra vez genérica: la tarea
            # correría, se pagaría la imagen, y lo que se pidió no estaría por
            # ninguna parte -- con el cambio marcado como aplicado. Vale más
            # caer al respaldo, que es lo que se hacía antes.
            texto = " ".join(str(cruda.get("peticion") or "").split())
            if not texto:
                avisos.append(f"«{rid}» vino sin decir qué cambiarle a la "
                              f"lámina: se rehace el estilo entero")
                return [], avisos
            entrada["peticion"] = texto
        salida.append(entrada)
    return salida, avisos


def params_de(retoques):
    """Los params que hay que ESCRIBIR antes de correr. -> {paso: {clave: v}}

    Solo los retoques baratos escriben params; `dibujo` y `todo` no escriben
    nada porque lo suyo lo decide la tarea que corre.
    """
    cambios = {}
    for entrada in retoques or []:
        rid = entrada.get("retoque")
        if "valor" not in entrada:
            continue
        clave = {"caja_subtitulo": "subtitulo_caja",
                 "tamano_subtitulo": "subtitulo_tam",
                 "set_grafismo": "diseno"}.get(rid)
        if clave:
            cambios.setdefault("callouts", {})[clave] = entrada["valor"]
    return cambios


def laminas_de(retoques):
    """Qué referencias hay que redibujar, y con qué corrección. -> {eje: texto}

    Es el cajón de `una_referencia`, y lo lee `moodboard.generar` por sus
    argumentos `ejes` y `peticiones`.

    VA POR INVOCACIÓN, dentro del encargo de esta pasada, y no a los params.
    Es lo que se corrige HOY -- «en esta que salgan vestidos distintos» --,
    no lo que el estilo ES. Guardado en los params se volvería a aplicar en
    la siguiente regeneración, y dos correcciones seguidas se sumarían sin
    que nadie lo pida. Misma regla que el `feedback` del encargo.

    UN DICCIONARIO VACÍO SIGNIFICA «LAS SEIS», que es el comportamiento de
    siempre. Por eso, si algo del reparto pide las seis --`dibujo`, `todo`--
    se devuelve vacío aunque también venga una lámina suelta: entregar solo
    esa dejaría cinco láminas con el estilo viejo y una con el nuevo, con la
    tarea corrida y el cambio dado por bueno.
    """
    pedidas = {}
    for entrada in retoques or []:
        rid = entrada.get("retoque")
        if rid != UNA_LAMINA:
            if "referencias" in (RETOQUES.get(rid) or {}).get("tareas", ()):
                return {}
            continue
        eje, peticion = entrada.get("eje"), entrada.get("peticion")
        if not eje or not peticion:
            continue                    # `_limpiar` no deja pasar esto
        # La misma lámina nombrada dos veces se corrige con las dos cosas, no
        # con la última: lo otro perdería media petición sin decirlo.
        pedidas[eje] = (f"{pedidas[eje]}; {peticion}" if eje in pedidas
                        else peticion)
    return pedidas


def imagenes_de(retoques):
    """Cuántas imágenes paga este reparto. -> int

    No es un `max` a secas: dos láminas sueltas son dos imágenes, y con `max`
    se anunciaría una. Y no es una suma a secas: `dibujo` ya redibuja las
    seis, así que sumarle una lámina prometería siete de seis.
    """
    if not retoques:
        return 0
    enteros = max((int(e.get("imagenes") or 0) for e in retoques
                   if e.get("retoque") != UNA_LAMINA), default=0)
    sueltas = len(laminas_de(retoques))
    return max(enteros, sueltas)


def tareas_de(retoques, respaldo=None):
    """Qué tareas hay que correr, sin repetir y sin inventar. -> tupla

    `muestra` entra siempre que entre algo: es lo único que hace VISIBLE el
    cambio en la tarjeta, y cuesta cero.
    """
    if not retoques:
        return tuple(respaldo or RETOQUES[RESPALDO]["tareas"])
    pedidas = set()
    for entrada in retoques:
        pedidas.update(RETOQUES.get(entrada.get("retoque"), {}).get("tareas", ()))
    if not pedidas:
        return ()                       # sin_mando: no se corre nada
    pedidas.add("muestra")
    # EN EL ORDEN DE SIEMPRE, que es el de las dependencias.
    orden = ("guia", "referencias", "grafismo", "muestra")
    return tuple(t for t in orden if t in pedidas)


def resumen_de(retoques, avisos=None):
    """Una línea para decir en pantalla qué se ha decidido. -> str"""
    if not retoques:
        return "se rehace el estilo gráfico entero"
    if len(retoques) == 1 and retoques[0]["retoque"] == "sin_mando":
        return (retoques[0].get("porque")
                or "eso no se puede tocar desde aquí")
    trozos = []
    for entrada in retoques:
        if entrada["retoque"] == UNA_LAMINA:
            titulo = ((EJES.get(entrada.get("eje")) or {}).get("titulo")
                      or entrada.get("eje"))
            trozos.append(f"solo la referencia «{titulo}»")
            continue
        nombre = entrada["retoque"].replace("_", " ")
        trozos.append(f"{nombre} = {entrada['valor']}" if "valor" in entrada
                      else nombre)
    imagenes = imagenes_de(retoques)
    return (f"se toca {', '.join(trozos)} · "
            + ("ninguna imagen" if not imagenes
               else f"{imagenes} {_imagenes(imagenes)}"))


def repartir(frase, estado="", avisar=None, proyecto_id=""):
    """De la frase a lo que hay que rehacer. -> dict

    -> {"retoques": [...], "tareas": (...), "params": {...},
        "avisos": [...], "resumen": str, "segundos": float}

    NUNCA revienta por culpa del modelo: cualquier cosa rara cae en el
    respaldo, que es rehacer el estilo entero -- o sea lo de antes.
    """
    avisar = avisar or (lambda *a, **k: None)
    frase = " ".join(str(frase or "").split())
    if not frase:
        return {"retoques": [], "tareas": tuple(RETOQUES[RESPALDO]["tareas"]),
                "params": {}, "laminas": {}, "imagenes": 0,
                "avisos": [], "segundos": 0.0,
                "resumen": "sin nada escrito: se rehace el estilo entero"}

    llamada = llm.rol_config("enrutador", comun.ajustes_llm())
    llamada.sistema = SISTEMA
    llamada.instruccion = INSTRUCCION.format(frase=frase,
                                             estado=estado or "—",
                                             retoques=_legible())
    llamada.contexto = "enrutar_estilo"
    llamada.proyecto = proyecto_id
    arranque = time.time()
    avisar("leyendo la corrección para ver qué hace falta rehacer")
    try:
        datos = llm.llamar_json(llamada, claves=comun.claves_actuales())
    except Exception as fallo:                                  # noqa: BLE001
        # SI EL REPARTO FALLA, SE HACE LO DE SIEMPRE. Un enrutador caído no
        # puede dejar sin corregir un estilo: lo único que se pierde es el
        # ahorro.
        return {"retoques": [], "tareas": tuple(RETOQUES[RESPALDO]["tareas"]),
                "params": {}, "laminas": {}, "imagenes": 0,
                "segundos": round(time.time() - arranque, 1),
                "avisos": [f"no se ha podido repartir la corrección ({fallo}); "
                           f"se rehace el estilo entero"],
                "resumen": "se rehace el estilo gráfico entero"}

    retoques, avisos = _limpiar(datos)
    return {"retoques": retoques, "tareas": tareas_de(retoques),
            "params": params_de(retoques), "laminas": laminas_de(retoques),
            "imagenes": imagenes_de(retoques), "avisos": avisos,
            "resumen": resumen_de(retoques, avisos),
            "segundos": round(time.time() - arranque, 1)}


def describir():
    rol = llm.ROLES_DEFECTO["enrutador"]
    return (f"reparto de la corrección del estilo en {len(RETOQUES)} retoques "
            f"y {len(EJES)} referencias "
            f"({rol['modelo']})")
