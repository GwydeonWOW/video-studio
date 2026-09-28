"""Catálogo visual del vídeo: quién sale, dónde ocurre y con qué tono.

Réplica del original (`pasos/catalogo_visual.py`), adaptada con honradez
a esta réplica: aquí el guion ya está cortado en ESCENAS (S001, S002...)
y cada escena es un plano, así que el catálogo se pide sobre las
escenas del guion y los beats cubren rangos de ids de escena. No hay
motor de mapas ni archivo de Commons: los componentes (mapas) y los
«reales» (fotos de Wikimedia) del original no se pintan de existir.

POR QUÉ VIVE EN ASSETS Y NO EN EL GUION (regla del original): el paso
donde se guarda una decisión es aquel cuya salida cambia. Cambiar cómo
es un personaje cambia las IMÁGENES, no el texto ni la voz. Si el
catálogo fuera del guion, retocar el pelo de alguien obligaría a
reescribir el guion y a REGRABAR la voz, y eso se paga. Se aprueba aquí
y se guarda en `params.catalogo` de assets.

PROPONER NO ES APROBAR: esto devuelve una propuesta. Lo que entra en
los params es lo que una persona aprueba (PUT /catalogo).
"""
from __future__ import annotations

import re
import unicodedata

from ..nucleo.proyecto import Proyecto
from . import comun, p2_brief
from ..motores import llm

PASO = "catalogo_visual"

#: Tope de planos seguidos en el mismo sitio (original: bajado de 3 a 2).
#: Encadenar muchos en el mismo set es lo que hace que la escena se
#: repita con un cambio pequeño.
PLANOS_POR_SET = 2

SISTEMA = """Eres el director de arte de un vídeo de animación narrada.
Lees el guion ENTERO y devuelves su catálogo visual: quién sale, dónde
ocurre cada tramo y con qué tono. Es el andamiaje con el que después se
arma el prompt de cada plano, y sin él cada plano se inventa el sitio y
la cara por su cuenta.

REPARTO — lo más importante
Cada persona que aparezca MÁS DE UNA VEZ va en el reparto con un
identificador estable y una descripción física cerrada: es lo único que
impide que la misma persona cambie de cara, de pelo y de ropa entre un
plano y el siguiente.
- El identificador, en minúsculas y sin acentos: 'udai', 'saddam'.
- UNA ENTRADA POR ACTOR DEL RELATO: si el guion llama a la misma gente
  de dos formas —primero «los atacantes», luego por su nombre—, eso es
  UNA entrada, no dos. Dos entradas son dos caras.
- La descripción es FÍSICA y permanente: edad aparente, complexión,
  pelo, vello facial, ropa habitual. Nada de estados de ánimo ni de
  DÓNDE está: con esa frase se dibuja la hoja sobre un fondo vacío.
- SI EL GUION NO LO DESCRIBE, INVÉNTALO: casi ningún guion documental
  describe a nadie, y un reparto vacío no significa que no salga nadie,
  significa que CADA plano se inventa la cara. Inventa lo justo y
  coherente con lo que SÍ dice el guion, y dilo en 'avisos'.
- El mismo personaje en dos edades muy distintas son DOS entradas.
- 'palabras' son las formas con las que el guion se refiere a él, para
  reconocerlo en cada frase.
- Los grupos anónimos (invitados, guardias, multitud) también valen,
  con grupo=true, descritos miembro a miembro para que salgan
  distinguibles entre sí.

SETS — dónde ocurre
Un set es un LUGAR, no un plano. Cambia de sitio cuando el relato
cambia de sitio.
- Apunta a tramos de {planos_por_set} planos como mucho por sitio
  seguido; si dudas entre arrastrar el sitio anterior o abrir uno
  nuevo, ABRE UNO NUEVO: un sitio de más no cuesta nada; uno de menos
  son cuatro planos que se parecen entre sí.
- CADA VEZ QUE EL GUION SITÚA, ESO ES UN SITIO: «Madrid, mayo de
  2024», «la sede del banco» piden su propio plano de establecimiento.
- Cada set que declares tiene que usarlo algún tramo, y cada tramo
  tiene que decir en qué sitio ocurre: cruza las dos listas antes de
  contestar.
- 'luz' fija hora del día y fuente de luz; 'descripcion' dice cómo es
  el lugar (no qué pasa en él): entra literal en el prompt de todos
  los planos rodados ahí.

BEATS — el guion en su contexto
Un beat es un TRAMO de escenas consecutivas que comparten sitio,
reparto y tono. Cubre el guion ENTERO, sin huecos ni solapes.
- 'tono' importa: alegre, neutro, tenso, triste o solemne.
- 'accion' es lo que se VE en ese tramo, en una línea, y es una idea
  visual PROPIA: dos tramos seguidos no pueden compartirla. Cuando la
  narración se pone abstracta —una cifra, una comparación—, escenifica
  algo concreto que la CUENTE.
- 'personajes' es quien está FÍSICAMENTE ahí, no de quién se habla: la
  descripción viaja al generador, así que a quien pongas en un beat,
  sale DIBUJADO en sus planos. Dos bandos no comparten beat.

LUGARES — el rótulo que sitúa
Sitios que la narración nombra y conviene rotular en pantalla cuando
se mencionan ('manzanillo' -> 'PUERTO DE MANZANILLO'). Sólo nombres
propios de sitio que importen.

CAPÍTULOS — dónde el vídeo cambia de asunto
Si el guion tiene partes claras, marca la escena donde arranca cada
una con su título. Tres o cuatro como mucho; si es un relato continuo,
ninguno.

Devuelve SOLO JSON con esta forma exacta:
{{
  "reparto": {{"<id>": {{"nombre": "...", "papel": "...",
                        "descripcion": "<física, en inglés>",
                        "palabras": ["..."], "grupo": false}}}},
  "sets": {{"<id>": {{"rotulo": "<cabecera al entrar, o vacío>",
                      "descripcion": "<en inglés>",
                      "palabras": ["..."],
                      "luz": "<hora y fuente, en inglés>"}}}},
  "beats": [{{"desde": "<id de escena>", "hasta": "<id de escena>",
              "set": "<id de set>", "personajes": ["<id de reparto>"],
              "tono": "alegre|neutro|tenso|triste|solemne",
              "accion": "<qué se ve, una línea>"}}],
  "lugares": {{"<palabra del guion>": "<RÓTULO EN PANTALLA>"}},
  "capitulos": {{"<id de escena>": {{"titulo": "...", "subtitulo": ""}}}},
  "avisos": ["..."]
}}"""


def _identificador(crudo) -> str:
    """'Udai Hussein' -> 'udai_hussein'. Sin acentos: acaba siendo nombre
    de fichero y carpeta."""
    plano = unicodedata.normalize("NFKD", str(crudo or ""))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9_]+", "_", plano.strip().lower()).strip("_")


def _lista_de_palabras(crudo, por_defecto) -> list[str]:
    palabras = [str(p).strip() for p in (crudo or []) if str(p).strip()]
    return palabras or [str(por_defecto).replace("_", " ")]


def _limpiar_lugares(crudos, avisos) -> dict:
    """{palabra del guion: RÓTULO}. Se rotula cuando se NOMBRA el sitio."""
    limpios = {}
    for crudo, rotulo in (crudos or {}).items():
        clave = " ".join(str(crudo or "").split()).lower()
        texto = " ".join(str(rotulo or "").split())
        if not clave or not texto:
            continue
        if len(clave) < 3:
            avisos.append(f"lugar '{clave}' descartado: la palabra es "
                          "demasiado corta y saltaría en cualquier frase")
            continue
        limpios[clave] = texto.upper()
    return limpios


def _limpiar(datos: dict, ids_escena: list[str]) -> dict:
    """Valida la propuesta y la deja en la forma que espera p6.

    Lo que no cuadra se DESCARTA y se dice en 'avisos': un beat que
    apunta a una escena o un set que no existe no se puede aplicar, y
    dejarlo pasar lo convertiría en un plano sin sitio a mitad del
    vídeo, que es justo el fallo que este módulo viene a arreglar.
    """
    avisos = [str(a) for a in (datos.get("avisos") or []) if str(a).strip()]
    orden = {sid: i for i, sid in enumerate(ids_escena)}

    reparto = {}
    for crudo, ficha in (datos.get("reparto") or {}).items():
        nombre = _identificador(crudo)
        if not nombre or not isinstance(ficha, dict):
            continue
        reparto[nombre] = {
            # 'nombre' es como se ROTULA en pantalla y 'descripcion'
            # como se DIBUJA: dos cosas distintas, por eso van separadas.
            "nombre": str(ficha.get("nombre") or "").strip()
                      or nombre.replace("_", " ").title(),
            "papel": str(ficha.get("papel") or "").strip(),
            "descripcion": str(ficha.get("descripcion") or nombre).strip(),
            "palabras": _lista_de_palabras(ficha.get("palabras"), nombre),
            "grupo": bool(ficha.get("grupo")),
        }

    sets = {}
    for crudo, ficha in (datos.get("sets") or {}).items():
        nombre = _identificador(crudo)
        if not nombre or not isinstance(ficha, dict):
            continue
        sets[nombre] = {
            "rotulo": str(ficha.get("rotulo") or "").strip(),
            "descripcion": str(ficha.get("descripcion") or nombre).strip(),
            "palabras": _lista_de_palabras(ficha.get("palabras"), nombre),
            "luz": str(ficha.get("luz") or "").strip(),
        }

    capitulos = {}
    for escena, ficha in (datos.get("capitulos") or {}).items():
        sid = str(escena or "").strip().upper()
        if sid not in orden or not isinstance(ficha, dict):
            if sid:
                avisos.append(f"capítulo descartado: la escena {sid} no existe")
            continue
        titulo = str(ficha.get("titulo") or "").strip()
        if titulo:
            capitulos[sid] = {"titulo": titulo,
                              "subtitulo": str(ficha.get("subtitulo") or "").strip()}

    beats = []
    for ficha in (datos.get("beats") or []):
        if not isinstance(ficha, dict):
            continue
        desde = str(ficha.get("desde") or "").strip().upper()
        hasta = str(ficha.get("hasta") or desde).strip().upper()
        if desde not in orden:
            avisos.append(f"beat descartado: la escena {desde or '(vacía)'} "
                          "no existe")
            continue
        if hasta not in orden:
            hasta = desde
        if orden[hasta] < orden[desde]:
            desde, hasta = hasta, desde
        set_nombre = _identificador(ficha.get("set")) or None
        if set_nombre and set_nombre not in sets:
            avisos.append(f"beat {desde}-{hasta}: el set '{set_nombre}' no "
                          "estaba declarado, se ignora el sitio")
            set_nombre = None
        personajes = []
        for crudo in (ficha.get("personajes") or []):
            nombre = _identificador(crudo)
            if nombre in reparto:
                personajes.append(nombre)
            elif nombre:
                avisos.append(f"beat {desde}-{hasta}: '{nombre}' no está en "
                              "el reparto")
        beats.append({"desde": desde, "hasta": hasta, "set": set_nombre,
                      "personajes": personajes,
                      "tono": str(ficha.get("tono") or "neutro").strip().lower(),
                      "accion": str(ficha.get("accion") or "").strip()})
    beats.sort(key=lambda b: orden[b["desde"]])

    # huecos y solapes: los huecos son planos sin sitio ni reparto; los
    # solapes se DICEN y no se rechazan (el original los reparte entre
    # los planos del tramo: aquí cada escena es un plano, así que se
    # avisa de que sobra alguno de verdad)
    cuantos = {}
    for beat in beats:
        for sid in ids_escena[orden[beat["desde"]]:orden[beat["hasta"]] + 1]:
            cuantos[sid] = cuantos.get(sid, 0) + 1
    cubiertos = set(cuantos)
    huecos = [s for s in ids_escena if s not in cubiertos]
    if huecos:
        avisos.append(f"{len(huecos)} escena(s) sin beat: "
                      f"{', '.join(huecos[:8])}"
                      + ("…" if len(huecos) > 8 else "")
                      + ". Esos planos se resolverán sin sitio ni reparto.")
    compartidos = [s for s in ids_escena if cuantos.get(s, 0) > 1]
    if compartidos:
        avisos.append(f"{len(compartidos)} escena(s) con más de un beat: "
                      f"{', '.join(compartidos[:8])}. En esta réplica cada "
                      "escena es UN plano, así que sobra alguno de verdad.")

    # los sitios que ningún tramo puede usar se quitan sin volver a
    # preguntar (regla del original): reintentar es pagar otra tirada
    sin_sitio = [b for b in beats if not b.get("set")]
    if not sin_sitio and not huecos:
        sobran = sorted(set(sets) - {b["set"] for b in beats if b.get("set")})
        for nombre in sobran:
            sets.pop(nombre, None)
        if sobran:
            avisos.append(f"se han quitado {len(sobran)} sitio(s) que ningún "
                          f"tramo usaba ({', '.join(sobran[:8])}"
                          + ("…" if len(sobran) > 8 else "")
                          + "): si querías alguno, dale un tramo en la tabla.")

    return {"reparto": reparto, "sets": sets, "beats": beats,
            "capitulos": capitulos,
            "lugares": _limpiar_lugares(datos.get("lugares"), avisos),
            "avisos": avisos,
            "cobertura": round(len(cubiertos) / max(1, len(ids_escena)), 3)}


def catalogo_de(params_assets: dict) -> dict:
    """El catálogo guardado en params (o vacío, que es un catálogo válido)."""
    datos = (params_assets or {}).get("catalogo")
    if not isinstance(datos, dict):
        return {"reparto": {}, "sets": {}, "beats": [], "capitulos": {},
                "lugares": {}, "avisos": [], "cobertura": 0.0}
    vacio = {"reparto": {}, "sets": {}, "beats": [], "capitulos": {},
             "lugares": {}, "avisos": []}
    return {**vacio, **{k: v for k, v in datos.items() if k in vacio}}


def beat_de(catalogo: dict, sid: str) -> dict | None:
    """El beat que cubre una escena (el primero, si se solapan)."""
    for beat in (catalogo or {}).get("beats") or []:
        # los ids S001... comparan bien en orden de cadena
        if str(beat.get("desde")) <= sid <= str(beat.get("hasta")):
            return beat
    return None


def _guion_legible(escenas) -> str:
    lineas = []
    for escena in escenas or []:
        sid = str(escena.get("id") or "").strip()
        titulo = str(escena.get("titulo") or "").strip()
        narracion = " ".join(str(escena.get("narracion") or "").split())
        linea = f"[{sid}]"
        if titulo:
            linea += f" ({titulo})"
        lineas.append(f"{linea} {narracion}")
    return "\n".join(lineas)


def proponer(proyecto: Proyecto, params: dict, trabajo, peticion: str = "") -> dict:
    """Propone el catálogo visual del vídeo. NO lo guarda: eso lo hace
    una persona (PUT /catalogo)."""
    guion = p2_brief.proyecto_leer_datos(proyecto, "guion")
    escenas = guion.get("escenas", [])
    if not escenas:
        raise ValueError("falta el guion: genera primero el paso anterior")
    ids = [str(e["id"]).strip().upper() for e in escenas]

    encargo = []
    encargo.append(f"VÍDEO: {proyecto.nombre} (idioma {proyecto.idioma or 'es'})")
    estilo = str((params or {}).get("estilo", "")).strip()
    if estilo:
        encargo.append(f"ESTILO GRÁFICO DEL CANAL (contexto; no lo repitas "
                       f"en las descripciones): {estilo}")
    peticion = " ".join(str(peticion or "").split())
    if peticion:
        encargo.append(f"\nLO QUE TE PIDE EL EDITOR (va por delante del "
                       f"criterio general):\n{peticion}")
    encargo.append(f"\nGUION COMPLETO, ESCENA A ESCENA ({len(escenas)}):\n"
                   + _guion_legible(escenas))

    trabajo.avance(f"leyendo el guion entero para repartir sitios y personajes")
    llamada = llm.rol_config("catalogo", comun.ajustes_llm())
    llamada.sistema = SISTEMA.format(planos_por_set=PLANOS_POR_SET)
    llamada.instruccion = "\n".join(encargo)
    llamada.contexto = "catalogo_visual"
    llamada.proyecto = proyecto.id
    crudo = llm.llamar_json(llamada, claves=comun.claves_actuales())

    catalogo = _limpiar(crudo if isinstance(crudo, dict) else {}, ids)
    trabajo.avance(
        f"catálogo propuesto: {len(catalogo['reparto'])} personaje(s), "
        f"{len(catalogo['sets'])} sitio(s), {len(catalogo['beats'])} beat(s), "
        f"cobertura {catalogo['cobertura']}")
    return {"catalogo": catalogo,
            "personajes": len(catalogo["reparto"]),
            "sets": len(catalogo["sets"]),
            "beats": len(catalogo["beats"]),
            "avisos": catalogo["avisos"]}
