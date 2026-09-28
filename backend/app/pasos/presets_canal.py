"""Presets de canal: lo que se decide una vez por canal y se repite en cada vídeo.

Adaptado del original (`pasos/presets_canal.py`) a los pasos y params de
este estudio. Un canal tiene un idioma, un estilo gráfico, una cadencia
y una voz, y esas cosas son las MISMAS en todos sus vídeos. Hoy hay que
volver a tomarlas en cada proyecto; un preset guarda esa decisión con
un nombre y la vuelve a poner de un desplegable.

Los tipos son cinco y cada uno declara los pasos del grafo a los que toca:

    guion   -> brief + guion    tono, idioma, cadencia, nº de escenas
    estilo  -> assets           guía escrita, estilo libre, calidad
    rotulos -> callouts         set de diseño, colores fijados, subtítulo
    voz     -> voz              voz, modelo, estabilidad, similitud, ritmo
    canal   -> los cuatro       un paquete con lo de arriba dentro

Un preset por DECISIÓN, no por parámetro: guardar con nombre y
miniatura algo que es un desplegable de una sola opción es más
ceremonia que la decisión que ahorra.

Aplicar COPIA los valores, no guarda el nombre
----------------------------------------------
Un preset aplicado deja de existir como tal: lo que queda en el
proyecto son sus valores dentro de los params del paso. Es a propósito:
si se guardara el nombre, borrar un preset rompería un vídeo terminado.
Copiando los valores, la lista de presets es de quien la mantiene y lo
que ya está hecho no depende de ella.

Las LÁMINAS se COPIAN al banco
------------------------------
En el original eran los fotogramas de referencia; aquí son las láminas
del moodboard, que cuestan seis imágenes y se dibujan UNA vez por
estilo. Viven en `banco/presets/<id>/moodboard/`, fuera del banco
global, para que limpiar el banco (o mudar de máquina) no deje el
preset apuntando a nada; al aplicar, `restaurar_moodboard` las devuelve
al banco si allí ya no están. Encontrarlo no depende de eso: la clave
del moodboard sale del CONTENIDO de la guía, así que la copia da la
misma clave que el original.

La papelera es aparte de la de proyectos
----------------------------------------
Un preset borrado va a una papelera propia con su etiqueta. No se
mezcla con la de proyectos porque lo que se pierde al vaciarla no se
parece en nada: un proyecto son gigas de imágenes pagadas, un preset
son unas láminas y un párrafo.
"""
from __future__ import annotations

import copy
import shutil
import time
from pathlib import Path

from ..config import AJUSTES
from ..nucleo.proyecto import ahora, escribir_json, leer_json, lock_de


class ErrorPreset(Exception):
    """Fallo de un preset con mensaje pensado para que lo lea una persona."""


# --------------------------------------------------------------------- tipos

# Cada tipo declara QUÉ claves lleva y a qué paso del grafo van. La lista
# de claves es cerrada a propósito: una clave que no esté aquí no se
# guarda y se dice en voz alta, porque un preset que arrastra basura la
# aplicaría en silencio sobre los params de un proyecto y ahí ya no hay
# quien la encuentre.
TIPOS = {
    # Lo que de verdad se repite entre vídeos de un canal es el GUION
    # entero: en qué idioma, con qué tono y a qué cadencia.
    "guion": {
        "nombre": "Guion",
        "que_fija": ("el tono, el idioma, la cadencia de escenas y cuántas "
                     "escenas pide el vídeo"),
        "claves": ("tono", "idioma", "ritmo_min", "ritmo_max", "escenas"),
        "pasos": ("brief", "guion"),
    },
    "estilo": {
        "nombre": "Estilo gráfico",
        "que_fija": ("la guía de estilo escrita, el estilo libre, las "
                     "referencias dibujadas (moodboard) y la calidad de "
                     "imagen"),
        # 'moodboard' NO lo manda la interfaz: lo pone el servidor al
        # guardar, mirando qué láminas hay APROBADAS para esa guía. Es un
        # dato derivado, y dejar que viajara desde el navegador sería
        # dejar que el preset dijera que tiene referencias dibujadas que
        # nadie ha mirado.
        "claves": ("estilo", "guia", "calidad", "moodboard"),
        "pasos": ("assets",),
    },
    # El id se queda en 'rotulos' porque es la clave con la que se
    # guardan los presets en disco; lo que cambia es lo que se LEE.
    "rotulos": {
        "nombre": "Grafismo",
        "que_fija": ("cómo se dibuja el texto en pantalla: el set de "
                     "diseño, los colores fijados a mano y el tamaño del "
                     "subtítulo"),
        "claves": ("diseno", "paleta", "subtitulo_tam"),
        "pasos": ("callouts",),
    },
    "voz": {
        "nombre": "Voz",
        "que_fija": ("voz, modelo, estabilidad, similitud y velocidad"),
        "claves": ("voz", "voz_nombre", "modelo", "estabilidad",
                   "similitud", "velocidad"),
        "pasos": ("voz",),
    },
    "canal": {
        "nombre": "Canal",
        "que_fija": "de golpe el guion, el estilo gráfico y la voz",
        # las claves de un canal son los OTROS tipos: dentro de cada una
        # va el bloque de datos de ese tipo, tal cual. Y además 'origen',
        # que no es un tipo: ver CLAVES_ORIGEN más abajo.
        "claves": ("guion", "estilo", "voz", "rotulos", "origen"),
        "pasos": ("brief", "guion", "assets", "voz", "callouts"),
    },
}

#: DE DÓNDE SALIÓ EL PRESET, y no es documentación: es lo que permite
#: REHACER una de sus tres partes sin volver a pedirlo todo. El modo
#: light crea un canal entero a partir de cuatro campos; cuando después
#: se pide «que los subtítulos sean más claros», lo que hay que rehacer
#: es el estilo gráfico CON SU ENTRADA ORIGINAL más esa corrección.
#:
#: `taller` es el id del proyecto oculto donde se generó.
CLAVES_ORIGEN = ("estilo_prompt", "tono_prompt", "voz_prompt", "voz_id",
                 "idioma", "ritmo", "taller", "feedback",
                 # Descripciones cortas de lo que salió, para poder
                 # ENSEÑAR el estilo sin abrirlo entero. No son params.
                 "tono_resumen", "estilo_resumen", "muestras")

# Orden en el que se enseñan y en el que se aplican. El guion va
# primero porque el resto se lee en él: la voz hereda el idioma.
ORDEN = ("guion", "estilo", "voz", "rotulos")


def tipos() -> list[dict]:
    """Catálogo de tipos para pintar la interfaz, en orden."""
    fichas = []
    for clave in list(ORDEN) + ["canal"]:
        ficha = dict(TIPOS[clave])
        ficha["id"] = clave
        ficha["claves"] = list(ficha["claves"])
        ficha["pasos"] = list(ficha["pasos"])
        fichas.append(ficha)
    return fichas


def _validar_tipo(tipo) -> str:
    clave = str(tipo or "").strip()
    if clave not in TIPOS:
        raise ErrorPreset(f"tipo de preset desconocido: {tipo!r}. "
                          f"Los tipos son: {', '.join(TIPOS)}")
    return clave


def _limpiar_datos(tipo, datos) -> dict:
    """Deja solo las claves declaradas del tipo, y protesta por las demás."""
    if not isinstance(datos, dict):
        raise ErrorPreset(f"los datos de un preset de {tipo} tienen que ser "
                          f"un objeto, ha llegado {type(datos).__name__}")
    permitidas = TIPOS[tipo]["claves"]
    sobran = [c for c in datos if c not in permitidas]
    if sobran:
        raise ErrorPreset(
            f"un preset de {tipo} no sabe guardar {', '.join(sorted(sobran))}. "
            f"Lo que guarda es: {', '.join(permitidas)}")
    limpios = {c: copy.deepcopy(v) for c, v in datos.items()
               if v is not None and v != ""}
    if tipo == "canal":
        # un canal es un paquete de los otros tipos: cada bloque se valida
        # con las reglas de SU tipo, o el paquete se convierte en el
        # agujero por donde entra lo que los demás rechazan
        for sub, bloque in list(limpios.items()):
            if sub == "origen":
                # 'origen' NO es un tipo de preset: es de dónde salió.
                if not isinstance(bloque, dict):
                    raise ErrorPreset("el origen de un preset de canal tiene "
                                      "que ser un objeto")
                sobran = [c for c in bloque if c not in CLAVES_ORIGEN]
                if sobran:
                    raise ErrorPreset(
                        f"el origen de un canal no sabe guardar "
                        f"{', '.join(sorted(sobran))}. Lo que guarda es: "
                        + ", ".join(CLAVES_ORIGEN))
                limpios[sub] = {c: copy.deepcopy(v) for c, v in bloque.items()
                                if v is not None and v != ""}
                continue
            limpios[sub] = _limpiar_datos(sub, bloque)
    if not limpios:
        raise ErrorPreset(f"un preset de {tipo} vacío no fija nada: "
                          f"pon algún valor antes de guardarlo")
    return limpios


# ------------------------------------------------------------------ el fichero

def fichero() -> Path:
    return Path(AJUSTES.datos) / "presets.json"


def raiz_banco() -> Path:
    return Path(AJUSTES.datos) / "banco" / "presets"


def _vacio() -> dict:
    return {"presets": [], "papelera": []}


def _leer() -> dict:
    datos = leer_json(fichero(), None)
    if not isinstance(datos, dict):
        return _vacio()
    salida = _vacio()
    for grupo in salida:
        salida[grupo] = [f for f in (datos.get(grupo) or [])
                         if isinstance(f, dict) and f.get("id")]
    return salida


def _escribir(datos: dict) -> None:
    escribir_json(fichero(), datos)


def _nuevo_id(ocupados=()) -> str:
    """Un id que no esté cogido. El reloj SOLO no basta.

    Era `pr{milisegundos:x}` a secas, y dos presets guardados en el mismo
    milisegundo salían con el MISMO id. Y eso no daba error: `guardar`
    ve un id que ya existe, lo toma por una actualización y SUSTITUYE el
    preset anterior. Guardar dos presets seguidos se llevaba uno por
    delante, en silencio. Con la lista de ocupados delante, el segundo
    del mismo milisegundo coge el siguiente hueco.
    """
    ocupados = set(ocupados)
    marca = int(time.time() * 1000)
    while f"pr{marca:x}" in ocupados:
        marca += 1
    return f"pr{marca:x}"


def carpeta_de(pid) -> Path:
    """Donde viven los ficheros propios de un preset (láminas, miniatura)."""
    return raiz_banco() / str(pid)


def ruta_de_miniatura(ficha: dict) -> Path:
    """La miniatura de un preset, resuelta contra ESTA máquina.

    De lo guardado solo vale el NOMBRE: una ficha escrita en otra
    máquina, o con otro volumen de datos, trae una ruta que aquí no
    existe y la tarjeta se quedaría sin cara sin decir por qué. Quedarse
    con el nombre NO afloja lo que protege al endpoint que la sirve: el
    nombre se pega a la carpeta del preset, así que no puede apuntar
    fuera.
    """
    cruda = str((ficha or {}).get("miniatura") or "").strip()
    if not cruda:
        return Path()
    # se parte por las DOS barras: la ruta pudo escribirla Windows o Linux
    nombre = Path(cruda.replace("\\", "/")).name
    if not nombre or nombre in (".", ".."):
        return Path()
    return carpeta_de((ficha or {}).get("id") or "") / nombre


def carpeta_moodboard_de(pid) -> Path:
    """Donde guarda un preset de estilo sus referencias dibujadas."""
    return carpeta_de(pid) / "moodboard"


def _moodboard():
    """El módulo de moodboards, importado tarde: un preset de guion o de
    voz no tiene por qué arrastrar la cadena de imagen al guardarse."""
    from . import moodboard                             # noqa: PLC0415
    return moodboard


# -------------------------------------------------------------------- resumen

def resumen_de(ficha: dict) -> str:
    """Una línea que dice lo que hay dentro sin tener que abrirlo.

    Un desplegable de presets donde solo se lee el nombre obliga a
    aplicar uno para saber qué hace. Va CON tildes porque se pinta en
    la interfaz, no en una consola.
    """
    tipo = ficha.get("tipo")
    datos = ficha.get("datos") or {}
    if tipo == "guion":
        trozos = [NOMBRES_IDIOMA.get(datos.get("idioma"),
                                     datos.get("idioma") or "sin idioma")]
        if datos.get("ritmo_min") and datos.get("ritmo_max"):
            trozos.append(f"escenas de {datos['ritmo_min']:g}-"
                          f"{datos['ritmo_max']:g} s")
        if datos.get("escenas"):
            trozos.append(f"{datos['escenas']} escenas")
        if datos.get("tono"):
            trozos.append("con tono propio")
        return " · ".join(trozos)
    if tipo == "estilo":
        guia = datos.get("guia") or {}
        trozos = [f"guía de {len(str(guia.get('guia') or '').split()) or '?'} "
                  f"palabras" if guia else "sin guía escrita"]
        colores = len(guia.get("paleta") or [])
        if colores:
            trozos.append(f"{colores} colores")
        dibujadas = len((datos.get("moodboard") or {}).get("ejes") or [])
        if dibujadas:
            trozos.append(f"{dibujadas} referencias dibujadas")
        if datos.get("calidad"):
            trozos.append(f"calidad {datos['calidad']}")
        return " · ".join(trozos)
    if tipo == "voz":
        return " · ".join(x for x in [
            datos.get("voz_nombre") or str(datos.get("voz") or "")[:8],
            datos.get("modelo"),
            f"velocidad {datos['velocidad']:g}" if datos.get("velocidad") else "",
            "estabilidad alta" if float(datos.get("estabilidad") or 0) >= 0.55
            else "voz viva",
        ] if x)
    if tipo == "rotulos":
        fijados = len((datos.get("paleta") or {}).get("fijados") or {})
        return " · ".join(x for x in [
            datos.get("diseno") or "diseño por defecto",
            f"subtítulo {datos['subtitulo_tam']}" if datos.get("subtitulo_tam") else "",
            f"{fijados} color(es) a mano" if fijados else "",
        ] if x)
    if tipo == "canal":
        # Un canal del modo light se lee por VIÑETAS (ver `vinetas_de`).
        vinetas = vinetas_de(ficha)
        if vinetas:
            return " · ".join(v["texto"] for v in vinetas)
        dentro = [TIPOS[s]["nombre"].lower() for s in ORDEN if datos.get(s)]
        return ("lleva " + ", ".join(dentro)) if dentro else "vacío"
    return ""


#: Los idiomas por nombre, para la tarjeta. Llevan tildes porque se
#: leen en la interfaz.
NOMBRES_IDIOMA = {"es": "Español", "en": "Inglés"}


def idioma_de(ficha: dict) -> str:
    """El idioma del canal. Sale del guion, que es quien lo decide.

    No se guarda como clave propia a propósito: ya vive en el bloque
    `guion`, y una tercera copia sería una tercera cosa que puede
    contradecir a las otras dos.
    """
    datos = (ficha.get("datos") or {})
    if ficha.get("tipo") == "canal":
        return str((datos.get("guion") or {}).get("idioma") or "").strip().lower()
    return str((datos.get("idioma")) or "").strip().lower()


def vinetas_de(ficha: dict) -> list[dict]:
    """Las líneas cortas que dicen QUÉ es este preset. -> [{icono, texto}]

    Es lo que se lee debajo de la miniatura en la galería del modo
    light. Cortas a propósito: la tarjeta se mira, no se estudia.

    EL ICONO LO PONE AQUÍ Y NO LA PANTALLA: la pantalla recibe una
    lista de líneas y no sabe cuál es el idioma y cuál la voz; ponerlo
    alli obligaría a deducirlo por el orden, que es justo lo que se
    rompe el día que una línea no salga.
    """
    if ficha.get("tipo") != "canal":
        return []
    datos = ficha.get("datos") or {}
    origen = datos.get("origen") or {}
    estilo = datos.get("estilo") or {}
    lineas: list[dict] = []

    def poner(icono, texto):
        texto = " ".join(str(texto or "").split())
        if texto:
            lineas.append({"icono": icono, "texto": texto})

    idioma = idioma_de(ficha)
    poner("🌐", NOMBRES_IDIOMA.get(idioma, idioma) if idioma else "")

    guia = estilo.get("guia") if isinstance(estilo.get("guia"), dict) else {}
    resumen_estilo = " ".join(str((guia or {}).get("resumen_es")
                                  or estilo.get("estilo") or "").split())
    if resumen_estilo:
        poner("🎨", _recortar(resumen_estilo, 70))

    tono = " ".join(str((datos.get("guion") or {}).get("tono") or "").split())
    poner("🗣️", _recortar(str(origen.get("tono_prompt") or tono), 70))

    voz = datos.get("voz") or {}
    if voz:
        nombre = (voz.get("voz_nombre") or str(voz.get("voz") or "")[:8])
        poner("🎙️", " · ".join(x for x in [
            nombre,
            f"velocidad {voz['velocidad']:g}" if voz.get("velocidad") else "",
        ] if x))

    # La cadencia se lee de los VALORES y no del `origen`: es lo que de
    # verdad tiene puesto el preset.
    guion = datos.get("guion") or {}
    if guion.get("ritmo_min") is not None:
        poner("⏱️", f"escenas de {float(guion['ritmo_min']):g}-"
                    f"{float(guion.get('ritmo_max') or 0):g} s")

    return lineas[:5]


def _recortar(texto, tope) -> str:
    texto = str(texto or "").strip()
    if len(texto) <= tope:
        return texto
    return texto[:tope - 1].rstrip(" ,.;:") + "…"


def _publicar(ficha: dict) -> dict:
    """Copia de la ficha con lo calculado que necesita la interfaz."""
    salida = copy.deepcopy(ficha)
    salida["resumen"] = resumen_de(ficha)
    salida["tipo_nombre"] = TIPOS.get(ficha.get("tipo"), {}).get("nombre", "")
    # Las viñetas y el idioma son de la tarjeta del modo light: se
    # calculan aquí porque quien sabe dónde vive el idioma de un canal
    # es la tabla de tipos, igual que con `cambios_para`.
    salida["vinetas"] = vinetas_de(ficha)
    salida["idioma"] = idioma_de(ficha)
    # El ritmo con el que se creó, para que el deslizador de la pantalla
    # sepa dónde ponerse. Vive en `origen` porque es la ENTRADA que se
    # dio; lo que el preset fija de verdad es ritmo_min/max.
    salida["origen_ritmo"] = str(
        ((ficha.get("datos") or {}).get("origen") or {}).get("ritmo") or "")
    # que la miniatura esté en el disco no se da por hecho: el banco es
    # una carpeta que alguien puede limpiar a mano
    salida["hay_miniatura"] = ruta_de_miniatura(ficha).is_file()
    return salida


def publicar(ficha: dict) -> dict:
    """La ficha tal y como la ve la interfaz: con resumen y sin sorpresas."""
    return _publicar(ficha)


# ------------------------------------------------------------------ operaciones

def listar() -> dict:
    """Todo lo guardado, agrupado por tipo, más la papelera de presets."""
    datos = _leer()
    por_tipo = {clave: [] for clave in TIPOS}
    for ficha in datos["presets"]:
        tipo = ficha.get("tipo")
        if tipo in por_tipo:
            por_tipo[tipo].append(_publicar(ficha))
    for lista in por_tipo.values():
        lista.sort(key=lambda f: str(f.get("nombre") or "").lower())
    return {
        "presets": por_tipo,
        "papelera": [_publicar(f) for f in datos["papelera"]],
        "tipos": tipos(),
        "total": sum(len(v) for v in por_tipo.values()),
    }


def leer(pid) -> dict:
    """Una ficha por id, mire donde mire (activos o papelera)."""
    datos = _leer()
    for grupo in ("presets", "papelera"):
        for ficha in datos[grupo]:
            if ficha.get("id") == str(pid):
                return copy.deepcopy(ficha)
    raise ErrorPreset(f"no hay ningún preset con id {pid!r}")


def es_propio_de_canal(nombre: str) -> bool:
    """Ficheros que un canal tiene en propiedad y NO salen de sus láminas.

    Son la miniatura 2x2 y las muestras sueltas: se dibujaron a propósito
    para ese preset —con sus cartelas y su subtítulo encima— y no están
    en ningún otro sitio de donde recuperarlas.
    """
    return (nombre == "miniatura.png"
            or (nombre.startswith("muestra") and nombre.endswith(".png")))


def guardar(tipo, nombre, datos, nota="", miniatura="", pid=None) -> dict:
    """Guarda un preset nuevo, o sustituye el contenido de uno que ya existe.

    `miniatura` es opcional y solo tiene sentido en estilo (la lámina que
    se ve) y en canal (la 2x2 compuesta del modo light). Si no se dice,
    se coge la primera lámina: un preset sin cara en el desplegable
    obliga a leer el nombre para saber cuál es cuál, y el nombre lo
    escribió alguien con prisa.
    """
    tipo = _validar_tipo(tipo)
    nombre = str(nombre or "").strip()
    if not nombre:
        raise ErrorPreset("un preset necesita un nombre: es lo único que se "
                          "ve en el desplegable")
    limpios = _limpiar_datos(tipo, datos)

    with lock_de(str(fichero())):
        guardado = _leer()
        anterior = None
        if pid:
            anterior = next((f for f in guardado["presets"]
                             if f.get("id") == pid), None)
            if anterior is None:
                raise ErrorPreset(f"no hay ningún preset con id {pid!r} que "
                                  f"actualizar")
            if anterior.get("tipo") != tipo:
                raise ErrorPreset(
                    f"el preset {pid} es de tipo {anterior.get('tipo')}, no "
                    f"de {tipo}: cambiarle el tipo lo convertiría en otra "
                    f"cosa con el mismo nombre")
        # con los ya guardados delante: sin eso, dos presets del mismo
        # milisegundo comparten id y el segundo SUSTITUYE al primero
        identificador = pid or _nuevo_id(f.get("id") for f in guardado["presets"])

        limpios, ruta_miniatura = _sembrar_ficheros(tipo, identificador,
                                                    limpios, miniatura)

        ficha = {
            "id": identificador,
            "tipo": tipo,
            "nombre": nombre,
            "nota": str(nota or "").strip(),
            "fecha": (anterior or {}).get("fecha") or ahora(),
            "modificado": ahora(),
            "miniatura": ruta_miniatura,
            "datos": limpios,
        }
        if anterior is not None:
            guardado["presets"] = [ficha if f.get("id") == identificador else f
                                   for f in guardado["presets"]]
        else:
            guardado["presets"].append(ficha)
        _escribir(guardado)
    return _publicar(ficha)


def _sembrar_ficheros(tipo, pid, datos, miniatura):
    """Copia al banco lo que el preset necesita tener en propiedad.

    Solo el estilo: sus láminas viven en el banco global de moodboards y
    ese banco se puede limpiar. En el original eran los fotogramas de
    referencia; aquí, las referencias dibujadas.
    """
    if tipo == "canal":
        ruta = ""
        if datos.get("estilo"):
            # el estilo de dentro de un canal necesita lo mismo que uno
            # suelto
            dentro, ruta = _sembrar_ficheros("estilo", pid, datos["estilo"],
                                             miniatura)
            datos = dict(datos, estilo=dentro)
        # LA MINIATURA PROPIA. Un canal del modo light no se enseña con
        # una de sus láminas: se enseña con la muestra 2x2 que se generó
        # a propósito, con sus cartelas y su subtítulo puestos. Va
        # DESPUÉS de sembrar el estilo para no ser sobreescrita.
        propia = str(miniatura or "").strip()
        destino = carpeta_de(pid) / "miniatura.png"
        if propia and Path(propia).exists() and es_propio_de_canal(
                Path(propia).name):
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(propia, destino)
                ruta = destino.name
            except OSError:
                pass         # sin cara se sigue: el preset vale igual
        elif destino.is_file():
            # la 2x2 que ya estaba: la ficha vuelve a apuntar a ella en
            # vez de caer a la primera lámina
            ruta = destino.name
        return datos, ruta
    if tipo != "estilo":
        return datos, ""

    guia = datos.get("guia") if isinstance(datos.get("guia"), dict) else {}
    libre = " ".join(str(datos.get("estilo") or "").split())
    if not guia.get("guia") and len(libre) < 8:
        raise ErrorPreset(
            "un preset de estilo necesita material: la guía escrita o un "
            "estilo libre con algo más de ocho letras. Con menos se describe "
            "un capricho, no un estilo")

    # Las láminas dibujadas se guardan CON el preset. Falla en silencio
    # a propósito: no poder copiarlas no puede impedir guardar el
    # estilo, y lo que se pierde es una copia de respaldo de algo que
    # sigue en el banco global.
    datos.pop("moodboard", None)
    copiada = ""
    if guia.get("guia"):
        try:
            exportado = _exportar_moodboard(pid, guia)
        except Exception:                                     # noqa: BLE001
            exportado = None
        if exportado:
            datos["moodboard"] = {"clave": exportado["clave"],
                                  "ejes": list(exportado["ejes"])}
            if exportado["primera"]:
                copiada = exportado["primera"]

    destino = carpeta_de(pid)
    destino.mkdir(parents=True, exist_ok=True)
    elegida = destino / "miniatura.png"
    pedir = str(miniatura or "").strip()
    if pedir and Path(pedir).exists():
        try:
            shutil.copyfile(pedir, elegida)
        except OSError:
            pass
    elif copiada and not elegida.is_file():
        # la primera lámina como cara del desplegable, si no había ninguna
        try:
            shutil.copyfile(copiada, elegida)
        except OSError:
            pass
    elif not elegida.is_file():
        elegida = Path()
    # de lo guardado solo vale el nombre (lo resuelve ruta_de_miniatura
    # contra la carpeta de ESTA máquina): un Path aquí revienta el
    # escribir_json del guardar
    return datos, (elegida.name if elegida.is_file() else "")


def _exportar_moodboard(pid, guia: dict) -> dict | None:
    """Copia al preset las láminas aprobadas de esa guía. -> ficha o None."""
    mb = _moodboard()
    clave = mb.clave_de(guia)
    origen = mb.carpeta_de(clave)
    if not clave or not origen:
        return None
    ejes = [eje for eje in sorted(mb.EJES)
            if (origen / f"{eje}.png").is_file()]
    if not ejes:
        return None
    destino = carpeta_moodboard_de(pid)
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)
    for eje in ejes:
        shutil.copyfile(origen / f"{eje}.png", destino / f"{eje}.png")
    ficha = mb.ficha_de(clave)
    escribir_json(destino / "ficha.json", {
        "clave": clave, "estado": "aprobado",
        "coste_usd": ficha.get("coste_usd", 0.0),
        "peticiones": ficha.get("peticiones") or {},
    })
    return {"clave": clave, "ejes": ejes,
            "primera": destino / f"{ejes[0]}.png"}


def restaurar_moodboard(ficha: dict) -> dict:
    """Devuelve al banco las referencias dibujadas que guarda un preset.

    Se llama al APLICAR. Normalmente no hace nada —el moodboard sigue
    en el banco global y se encuentra solo por la huella de la guía—;
    sirve para la máquina nueva y para el banco que alguien ha limpiado.
    """
    tipo = str(ficha.get("tipo") or "")
    datos = ficha.get("datos") or {}
    if tipo == "canal":
        return restaurar_moodboard({"id": ficha.get("id"), "tipo": "estilo",
                                    "datos": datos.get("estilo") or {}})
    guardado = datos.get("moodboard") or {}
    if tipo != "estilo" or not guardado.get("clave"):
        return {"clave": "", "ejes": []}
    try:
        mb = _moodboard()
        clave = str(guardado["clave"])
        destino = mb.raiz_banco() / clave
        origen = carpeta_moodboard_de(ficha.get("id"))
        if not origen.is_dir():
            return {"clave": clave, "ejes": []}
        devueltos = []
        destino.mkdir(parents=True, exist_ok=True)
        for eje in guardado.get("ejes") or []:
            lamina = origen / f"{eje}.png"
            if lamina.is_file() and not (destino / f"{eje}.png").is_file():
                shutil.copyfile(lamina, destino / f"{eje}.png")
                devueltos.append(eje)
        if devueltos and not (destino / "ficha.json").is_file():
            escribir_json(destino / "ficha.json", {
                "clave": clave, "estado": "aprobado", "coste_usd": 0.0,
                "peticiones": {}})
        return {"clave": clave, "ejes": devueltos}
    except Exception:                                         # noqa: BLE001
        # lo mismo que al guardar: esto es una red de seguridad, no la
        # vía normal, y no puede impedir que se aplique el estilo
        return {"clave": guardado.get("clave") or "", "ejes": []}


def renombrar(pid, nombre=None, nota=None) -> dict:
    """Cambia el nombre o la nota de un preset SIN tocar lo que guarda.

    Existe como operación aparte y no como un guardar() con los mismos
    datos porque guardar() vuelve a sembrar los ficheros del preset. Un
    argumento a None se deja como estaba.
    """
    with lock_de(str(fichero())):
        guardado = _leer()
        ficha = next((f for f in guardado["presets"]
                      if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningún preset con id {pid!r}")
        if nombre is not None:
            limpio = str(nombre).strip()
            if not limpio:
                raise ErrorPreset("un preset necesita un nombre: es lo único "
                                  "que se ve en el desplegable")
            ficha["nombre"] = limpio
        if nota is not None:
            ficha["nota"] = str(nota).strip()
        ficha["modificado"] = ahora()
        _escribir(guardado)
    return _publicar(ficha)


def apartar(pid) -> dict:
    """A la papelera. No borra nada: la ficha y su carpeta siguen enteras."""
    with lock_de(str(fichero())):
        guardado = _leer()
        ficha = next((f for f in guardado["presets"]
                      if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningún preset con id {pid!r}")
        guardado["presets"] = [f for f in guardado["presets"]
                               if f.get("id") != str(pid)]
        ficha["apartado"] = ahora()
        guardado["papelera"].insert(0, ficha)
        _escribir(guardado)
    return _publicar(ficha)


def restaurar(pid) -> dict:
    """Devuelve a la lista un preset apartado."""
    with lock_de(str(fichero())):
        guardado = _leer()
        ficha = next((f for f in guardado["papelera"]
                      if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningún preset apartado con id {pid!r}")
        guardado["papelera"] = [f for f in guardado["papelera"]
                                if f.get("id") != str(pid)]
        ficha.pop("apartado", None)
        guardado["presets"].append(ficha)
        _escribir(guardado)
    return _publicar(ficha)


def peso(pid) -> dict:
    """Qué hay dentro de un preset apartado, para poder decir qué se pierde."""
    ficha = leer(pid)
    carpeta = carpeta_de(pid)
    ficheros = bytes_totales = 0
    for ruta in carpeta.rglob("*"):
        if ruta.is_file():
            ficheros += 1
            try:
                bytes_totales += ruta.stat().st_size
            except OSError:
                pass
    return {"id": pid, "nombre": ficha.get("nombre"),
            "tipo": ficha.get("tipo"), "carpeta": str(carpeta),
            "ficheros": ficheros, "bytes": bytes_totales,
            "megas": round(bytes_totales / (1024 * 1024), 2)}


def borrar(pid, confirmar=False) -> dict:
    """Borrado definitivo. Solo alcanza a lo que YA está en la papelera.

    Un preset vivo hay que apartarlo antes, que es un paso más y
    reversible: es la misma regla que los proyectos.
    """
    if not confirmar:
        raise ErrorPreset("el borrado definitivo necesita confirmar=true")
    with lock_de(str(fichero())):
        guardado = _leer()
        ficha = next((f for f in guardado["papelera"]
                      if f.get("id") == str(pid)), None)
        if ficha is None:
            vivo = any(f.get("id") == str(pid) for f in guardado["presets"])
            if vivo:
                raise ErrorPreset(
                    f"el preset {pid} no está en la papelera: apártalo "
                    f"primero. Borrar de verdad solo se puede desde la "
                    f"papelera")
            raise ErrorPreset(f"no hay ningún preset apartado con id {pid!r}")
        guardado["papelera"] = [f for f in guardado["papelera"]
                                if f.get("id") != str(pid)]
        _escribir(guardado)
    shutil.rmtree(carpeta_de(pid), ignore_errors=True)
    return {"borrado": pid, "nombre": ficha.get("nombre"),
            "tipo": ficha.get("tipo")}


# -------------------------------------------------------------------- aplicar

def cambios_para(ficha: dict, params_actuales: dict | None = None) -> dict:
    """Qué hay que escribir en los params de cada paso para aplicar un preset.

    Devuelve {paso: {clave: valor}}, listo para `Estado.actualizar_params`.
    """
    tipo = _validar_tipo(ficha.get("tipo"))
    datos = ficha.get("datos") or {}
    actuales = params_actuales or {}
    cambios: dict = {}

    if tipo == "canal":
        for sub in ORDEN:
            if not datos.get(sub):
                continue
            parcial = cambios_para({"tipo": sub, "datos": datos[sub]},
                                   actuales)
            for paso, valores in parcial.items():
                cambios.setdefault(paso, {}).update(valores)
        return cambios

    if tipo == "guion":
        # la cadencia y el idioma van al brief (quien hace la cuenta de
        # palabras); el tono viaja en ambos porque el sembrado del estilo
        # del canal ya lo escribe así y `linea_canal` lo lee en los dos
        de_brief = {c: copy.deepcopy(datos[c])
                    for c in ("tono", "idioma", "ritmo_min", "ritmo_max")
                    if datos.get(c) not in (None, "")}
        de_guion = {c: copy.deepcopy(datos[c])
                    for c in ("tono", "idioma", "escenas")
                    if datos.get(c) not in (None, "")}
        if de_brief:
            cambios["brief"] = de_brief
        if de_guion:
            cambios["guion"] = de_guion
        return cambios

    if tipo == "estilo":
        if datos.get("estilo") is not None:
            cambios["assets"] = {"estilo": copy.deepcopy(datos["estilo"])}
        if datos.get("guia"):
            cambios.setdefault("assets", {})["guia"] = \
                copy.deepcopy(datos["guia"])
        if datos.get("calidad"):
            cambios.setdefault("assets", {})["calidad"] = datos["calidad"]
        return cambios

    if tipo == "rotulos":
        de_callouts: dict = {}
        if datos.get("diseno"):
            de_callouts["diseno"] = datos["diseno"]
        if datos.get("subtitulo_tam"):
            de_callouts["subtitulo_tam"] = datos["subtitulo_tam"]
        if datos.get("paleta"):
            # solo viajan los papeles FIJADOS a mano: el resto se deriva
            # de la guía de estilo de CADA vídeo, que es lo que hace que
            # el rótulo pertenezca a ese dibujo y no al del vídeo donde
            # se guardó
            actual = dict((actuales.get("callouts") or {}).get("paleta") or {})
            actual["fijados"] = copy.deepcopy(
                (datos["paleta"] or {}).get("fijados") or {})
            de_callouts["paleta"] = actual
        if de_callouts:
            cambios["callouts"] = de_callouts
        return cambios

    if tipo == "voz":
        # voz_nombre es solo para el resumen del desplegable: no es un
        # param del paso y meterlo cambiaría la firma sin cambiar lo
        # que suena
        cambios["voz"] = {c: copy.deepcopy(v) for c, v in datos.items()
                          if c != "voz_nombre"}
        return cambios

    raise ErrorPreset(f"no se sabe aplicar un preset de tipo {tipo}")


# ------------------------------------------------ de un proyecto a un preset
#
# EL INVERSO DE `cambios_para`, y vive pegado a él a propósito: los dos
# usan la MISMA tabla de claves, y separarlos en dos ficheros es como se
# acaba con un preset que guarda una clave que aplicar no escribe (o al
# revés), que es un fallo mudo.
#
# Lo usa el modo light: allí el canal se genera en un proyecto taller y
# después se congela en un preset.

def datos_de_params(params_por_paso: dict, incluir=ORDEN) -> dict:
    """Los datos de un preset de canal leídos de los params de un proyecto.

    `params_por_paso` es {paso: params}. Devuelve {tipo: {clave: valor}}
    con solo los bloques que de verdad tienen algo: un bloque vacío no
    se guarda porque `_limpiar_datos` lo rechaza, y con razón.
    """
    params = {k: (v or {}) for k, v in (params_por_paso or {}).items()}
    brief = params.get("brief") or {}
    guion = params.get("guion") or {}
    assets = params.get("assets") or {}
    voz = params.get("voz") or {}
    callouts = params.get("callouts") or {}
    datos: dict = {}

    if "guion" in incluir:
        bloque = {}
        for clave in ("tono", "idioma", "ritmo_min", "ritmo_max"):
            if brief.get(clave) not in (None, ""):
                bloque[clave] = copy.deepcopy(brief[clave])
        if guion.get("escenas"):
            bloque["escenas"] = copy.deepcopy(guion["escenas"])
        if bloque:
            datos["guion"] = bloque

    if "estilo" in incluir:
        bloque = {}
        for clave in ("estilo", "guia", "calidad"):
            if assets.get(clave) not in (None, ""):
                bloque[clave] = copy.deepcopy(assets[clave])
        if bloque:
            datos["estilo"] = bloque

    if "voz" in incluir:
        bloque = {c: copy.deepcopy(voz[c]) for c in TIPOS["voz"]["claves"]
                  if voz.get(c) not in (None, "")}
        if bloque:
            datos["voz"] = bloque

    if "rotulos" in incluir:
        bloque = {c: copy.deepcopy(callouts[c])
                  for c in TIPOS["rotulos"]["claves"]
                  if callouts.get(c) not in (None, "")}
        if bloque:
            datos["rotulos"] = bloque

    return datos
