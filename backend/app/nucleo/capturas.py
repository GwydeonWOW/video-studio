"""Capturas anotables de los pasos de reproductor (callouts y render).

El feedback por escena no puede expresar un problema que solo existe en
un instante: un plano puede estar bien al empezar y mal al acabar. Por
eso aquí la unidad de feedback no es la escena, es (escena, segundo
exacto).

El navegador compone el fotograma —dibujando el <video> en un canvas en
render, o el plano + su rótulo en la previsualización— y este módulo
guarda el PNG con su anotación:

    almacen = Almacen(proyecto)
    ficha = almacen.crear("render", "S003", png, trazos=[...],
                          comentario="el rótulo pisa la grúa",
                          t_video=14.62, t_escena=2.18)

Al aplicarlas, cada captura se traduce a instrucción para su escena
(comentario literal + zonas de los trazos + contexto temporal) y varias
capturas de la misma escena se agrupan en UNA sola instrucción ordenada
por instante, para no lanzar regeneraciones encadenadas de la misma
unidad.

Invalidación: una captura afecta a la unidad escena:<id> del paso que
puede corregirla; el núcleo MARCA en cascada esa misma escena aguas
abajo. Nunca el paso entero, y nunca generando: marcar y generar son
dos gestos distintos.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil

from .proyecto import (Proyecto, ahora, escribir_json, leer_json, lock_de,
                       ruta_contenida)

CARPETA = "capturas"
INDICE = "capturas.json"
#: los pasos con reproductor del que capturar: la previsualización
#: (callouts) y el MP4 montado (render)
PASOS_CON_CAPTURA = ("callouts", "render")
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
LIMITE_PNG = 24 * 1024 * 1024
ID_ESCENA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ID_CAPTURA = re.compile(r"^cap_\d{4,}$")


class ErrorCaptura(ValueError):
    """Captura mal formada. El mensaje es para que lo lea un humano."""


# --------------------------------------------------------------- validación

def validar_paso(paso) -> str:
    """Solo los pasos con reproductor tienen capturas."""
    paso = str(paso or "").strip()
    if paso not in PASOS_CON_CAPTURA:
        raise ErrorCaptura(
            f"el paso '{paso}' no tiene reproductor: la captura anotable "
            "es de " + " y ".join(PASOS_CON_CAPTURA))
    return paso


def _validar_escena(escena) -> str:
    escena = str(escena or "").strip()
    if not ID_ESCENA.match(escena):
        raise ErrorCaptura(f"id de escena inválido: {escena!r}")
    return escena


def segundos(valor, nombre="instante", obligatorio=False):
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorCaptura(f"falta '{nombre}'")
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErrorCaptura(f"'{nombre}' debe ser un número de segundos, "
                           f"llegó {valor!r}") from None
    if numero < 0 or numero != numero:
        raise ErrorCaptura(f"'{nombre}' no puede ser negativo: {valor!r}")
    return round(numero, 3)


def normalizar_trazos(crudos) -> list[dict]:
    """Trazos del canvas -> forma canónica con puntos en 0..1.

    Se normalizan (y se recortan al cuadro) porque la anotación tiene
    que seguir siendo válida a cualquier tamaño de pantalla.
    """
    if crudos in (None, ""):
        return []
    if isinstance(crudos, str):
        try:
            crudos = json.loads(crudos)
        except ValueError as fallo:
            raise ErrorCaptura(f"'trazos' no es JSON válido: {fallo}") from None
    if not isinstance(crudos, list):
        raise ErrorCaptura("'trazos' debe ser una lista")
    limpios = []
    for trazo in crudos:
        if not isinstance(trazo, dict):
            raise ErrorCaptura("cada trazo debe ser un objeto con 'puntos'")
        puntos = []
        for punto in trazo.get("puntos") or []:
            if isinstance(punto, dict):
                x, y = punto.get("x"), punto.get("y")
            elif isinstance(punto, (list, tuple)) and len(punto) >= 2:
                x, y = punto[0], punto[1]
            else:
                raise ErrorCaptura("cada punto es {'x':0..1,'y':0..1}")
            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                raise ErrorCaptura(f"punto no numérico: {punto!r}") from None
            puntos.append({"x": round(min(max(x, 0.0), 1.0), 5),
                           "y": round(min(max(y, 0.0), 1.0), 5)})
        if not puntos:
            continue
        limpios.append({"color": str(trazo.get("color") or "#d4785a"),
                        "grosor": int(trazo.get("grosor") or 4),
                        "puntos": puntos})
    return limpios


def _validar_png(imagen) -> bytes:
    if isinstance(imagen, str):
        crudo = imagen.strip()
        if crudo.startswith("data:"):
            crudo = crudo.split(",", 1)[-1]
        try:
            imagen = base64.b64decode(crudo, validate=False)
        except Exception as fallo:              # noqa: BLE001
            raise ErrorCaptura(
                f"la imagen en base64 no se puede decodificar: {fallo}")
    if not isinstance(imagen, (bytes, bytearray)):
        raise ErrorCaptura("la imagen debe llegar como PNG (multipart o base64)")
    imagen = bytes(imagen)
    if not imagen:
        raise ErrorCaptura("la imagen llegó vacía")
    if len(imagen) > LIMITE_PNG:
        raise ErrorCaptura(f"la captura pesa {len(imagen) // 1024} KB, "
                           f"el límite son {LIMITE_PNG // 1024} KB")
    if not imagen.startswith(FIRMA_PNG):
        raise ErrorCaptura("la captura tiene que ser un PNG "
                           "(el fotograma se compone en un canvas y se sube "
                           "en PNG)")
    return imagen


# ----------------------------------------------------------------- almacén

class Almacen:
    """Capturas de un proyecto: PNG en capturas/ e índice en capturas.json."""

    def __init__(self, proyecto):
        if isinstance(proyecto, str):
            proyecto = Proyecto(proyecto)
        self.proyecto = proyecto
        self.carpeta = proyecto.ruta(CARPETA)
        self.indice = self.carpeta / INDICE

    def __repr__(self) -> str:
        return f"<Capturas {self.proyecto.id}>"

    # ------------------------------------------------------------ interno

    def _leer(self) -> dict:
        datos = leer_json(self.indice, None)
        if not isinstance(datos, dict) or not isinstance(datos.get("capturas"), list):
            return {"version": 1, "capturas": []}
        return datos

    def _guardar(self, datos: dict) -> None:
        datos["actualizado"] = ahora()
        escribir_json(self.indice, datos)

    def ruta_imagen(self, ficha) -> "os.PathLike":
        """Ruta absoluta del PNG de una captura (contenida en el proyecto)."""
        relativa = ficha.get("imagen") if isinstance(ficha, dict) else str(ficha)
        return ruta_contenida(self.proyecto.raiz, str(relativa or ""))

    # ----------------------------------------------------------- escritura

    def crear(self, paso, escena, imagen, trazos=None, comentario="",
              t_video=None, t_escena=None, contexto=None) -> dict:
        """Guarda una captura con su anotación y devuelve su ficha."""
        paso = validar_paso(paso)
        escena = _validar_escena(escena)
        datos_png = _validar_png(imagen)
        trazos = normalizar_trazos(trazos)
        comentario = str(comentario or "").strip()
        if not comentario and not trazos:
            raise ErrorCaptura("una captura sin comentario y sin trazos no "
                               "dice nada: escribe la nota o pinta encima")
        t_video = segundos(t_video, "t_video")
        t_escena = segundos(t_escena, "t_escena")
        if t_video is None and t_escena is None:
            raise ErrorCaptura("hace falta 't_video' o 't_escena': una captura "
                               "sin instante no se puede situar en el plano")

        os.makedirs(self.carpeta, exist_ok=True)
        with lock_de(str(self.indice)):
            datos = self._leer()
            numero = max([_numero_de(c.get("id")) for c in datos["capturas"]]
                         or [0]) + 1
            cid = f"cap_{numero:04d}"
            nombre = f"{cid}.png"
            with open(os.path.join(self.carpeta, nombre), "wb") as fh:
                fh.write(datos_png)
            ficha = {
                "id": cid,
                "paso": paso,
                "escena": escena,
                "unidad": f"escena:{escena}",
                "t_video": t_video,
                "t_escena": t_escena,
                "imagen": f"{CARPETA}/{nombre}",
                "trazos": trazos,
                "comentario": comentario,
                "creada": ahora(),
                "aplicada": None,
                "trabajo": None,
                "bytes": len(datos_png),
            }
            if isinstance(contexto, dict) and contexto:
                ficha["contexto"] = contexto
            datos["capturas"].append(ficha)
            self._guardar(datos)
        return dict(ficha)

    def borrar(self, cid) -> dict | None:
        """Borra una captura y su PNG. -> ficha borrada (o None)."""
        cid = str(cid or "")
        if not ID_CAPTURA.match(cid):
            raise ErrorCaptura(f"id de captura inválido: {cid!r}")
        with lock_de(str(self.indice)):
            datos = self._leer()
            quedan = [c for c in datos["capturas"] if c.get("id") != cid]
            if len(quedan) == len(datos["capturas"]):
                return None
            borrada = next(c for c in datos["capturas"] if c.get("id") == cid)
            datos["capturas"] = quedan
            self._guardar(datos)
        ruta = self.ruta_imagen(borrada)
        if os.path.exists(ruta):
            os.remove(ruta)
        return borrada

    def marcar_aplicadas(self, ids, trabajo=None, instruccion=None) -> list[str]:
        """Anota qué capturas ya se aplicaron y en qué trabajo."""
        pedidos = {str(i) for i in (ids or [])}
        marca = ahora()
        with lock_de(str(self.indice)):
            datos = self._leer()
            tocadas = []
            for ficha in datos["capturas"]:
                if ficha.get("id") in pedidos:
                    ficha["aplicada"] = marca
                    ficha["trabajo"] = trabajo
                    if instruccion:
                        ficha["instruccion"] = instruccion
                    tocadas.append(ficha["id"])
            self._guardar(datos)
        return tocadas

    # ------------------------------------------------------------ lectura

    def listar(self, paso=None, escena=None, pendientes=None) -> list[dict]:
        """Capturas del proyecto, de la más antigua a la más reciente."""
        fichas = list(self._leer()["capturas"])
        if paso:
            fichas = [f for f in fichas if f.get("paso") == str(paso)]
        if escena:
            escena = str(escena)
            fichas = [f for f in fichas
                      if f.get("escena") == escena or f.get("unidad") == escena]
        if pendientes is True:
            fichas = [f for f in fichas if not f.get("aplicada")]
        elif pendientes is False:
            fichas = [f for f in fichas if f.get("aplicada")]
        fichas.sort(key=lambda f: (str(f.get("creada") or ""), str(f.get("id"))))
        return fichas

    def obtener(self, cid) -> dict | None:
        for ficha in self._leer()["capturas"]:
            if ficha.get("id") == str(cid):
                return ficha
        return None

    def obtener_varias(self, ids) -> list[dict]:
        """Fichas de varias capturas, en el orden pedido. Falla si falta alguna."""
        indice = {f["id"]: f for f in self._leer()["capturas"] if f.get("id")}
        fichas, faltan = [], []
        for cid in ids or []:
            ficha = indice.get(str(cid))
            if ficha is None:
                faltan.append(str(cid))
            else:
                fichas.append(ficha)
        if faltan:
            raise ErrorCaptura(f"capturas desconocidas: {', '.join(faltan)}")
        return fichas

    def limpiar(self) -> None:
        shutil.rmtree(self.carpeta, ignore_errors=True)


def _numero_de(cid) -> int:
    encaje = re.search(r"(\d+)", str(cid or ""))
    return int(encaje.group(1)) if encaje else 0


# ------------------------------------------------------------- instrucción

def _coma(numero, decimales=1) -> str:
    """2.18 -> '2,2'. El texto lo lee un humano y lo lee un modelo."""
    if numero is None:
        return "?"
    return f"{float(numero):.{decimales}f}".replace(".", ",")


def describir_trazos(trazos) -> str:
    """Trazos -> frase de zonas («arriba a la derecha»).

    El generador no entiende un canvas: entiende «la zona superior
    derecha». Versión propia y ligera del motor de descripción del
    original — media de los puntos y cruce de tercios.
    """
    if not trazos:
        return ""
    puntos = [p for t in trazos if isinstance(t, dict)
              for p in (t.get("puntos") or [])]
    if not puntos:
        return ""
    try:
        cx = sum(float(p.get("x", 0.5)) for p in puntos) / len(puntos)
        cy = sum(float(p.get("y", 0.5)) for p in puntos) / len(puntos)
    except (TypeError, ValueError):
        return ""
    vertical = "arriba" if cy < 0.33 else "abajo" if cy > 0.66 else "el centro"
    horizontal = ("a la izquierda" if cx < 0.33
                  else "a la derecha" if cx > 0.66 else "")
    zona = f"{vertical} {horizontal}".strip()
    return f"la anotación señala {zona} del cuadro"


def frase_temporal(captura) -> str:
    """El instante de la captura, dicho como se lo damos a quien corrige.

    Sin esto, una nota sobre algo que solo ocurre al final se interpreta
    como si valiera para todo el plano.
    """
    contexto = captura.get("contexto") if isinstance(captura, dict) else None
    contexto = contexto if isinstance(contexto, dict) else {}
    if contexto.get("frase"):
        return str(contexto["frase"])
    t_escena = captura.get("t_escena")
    if t_escena is None:
        return (f"el problema aparece a "
                f"{_coma(captura.get('t_video'))} s de vídeo")
    return f"el problema aparece a {_coma(t_escena)} s del plano"


def instruccion_de(capturas, describir=None) -> str:
    """Varias capturas de la MISMA escena -> una sola instrucción ordenada.

    Se agrupan a propósito: aplicarlas una a una lanzaría regeneraciones
    encadenadas de la misma unidad, cada una sin saber lo que pedía la
    anterior.
    """
    capturas = ordenar(capturas)
    if not capturas:
        return ""
    primera = capturas[0]
    lineas = [f"Corrección pedida sobre el plano {primera.get('escena')} "
              f"desde el reproductor de {primera.get('paso')}: "
              f"{len(capturas)} captura(s) anotada(s), en orden de instante."]
    for numero, captura in enumerate(capturas, start=1):
        lineas.append("")
        lineas.append(f"{numero}. {frase_temporal(captura)}.")
        comentario = str(captura.get("comentario") or "").strip()
        if comentario:
            lineas.append(f'   Nota del revisor: "{comentario}"')
        zonas = (describir or describir_trazos)(captura.get("trazos"))
        if zonas:
            lineas.append(f"   {zonas}")
    return "\n".join(lineas)


def ordenar(capturas) -> list[dict]:
    """Capturas por instante, que es el orden en que se ven en el vídeo."""
    def clave(captura):
        instante = captura.get("t_escena")
        if instante is None:
            instante = captura.get("t_video")
        return (float(instante or 0.0), str(captura.get("id") or ""))
    return sorted(capturas or [], key=clave)


def agrupar(capturas) -> dict:
    """{(paso, escena): [capturas]}, cada grupo ordenado por instante."""
    grupos: dict[tuple, list] = {}
    for captura in capturas or []:
        clave = (captura.get("paso"), captura.get("escena"))
        grupos.setdefault(clave, []).append(captura)
    return {clave: ordenar(fichas) for clave, fichas in grupos.items()}


# --------------------------------------------------------------- aplicación

def aplicar(estado, capturas, zonas=None, destino_de=None) -> list[dict]:
    """Traduce las capturas a feedback por unidad y MARCA lo que hay que rehacer.

    `destino_de(paso)` dice a qué paso va el feedback de una captura de
    ese reproductor: en esta réplica el montaje es determinista, así que
    la captura de render se corrige donde se puede corregir —la imagen
    del plano (assets)— y la de callouts en sus propios rótulos.

    Devuelve un grupo por (paso, escena) con la instrucción y la unidad
    tocada. No lanza nada: quien llama decide cómo se regenera.
    """
    zonas = zonas if isinstance(zonas, dict) else {}
    destino_de = destino_de or (lambda paso: "assets" if paso == "render" else paso)
    grupos = []
    for (_paso, escena), fichas in sorted(agrupar(capturas).items()):
        paso = destino_de(_paso)
        # el cajón de unidades de esta réplica se llama por el id de la
        # escena («S003»), igual que lo leen p6/p7 en `params.unidades`
        unidad = str(escena)
        instruccion = instruccion_de(fichas)
        nota = {
            "id": f"C{fichas[0]['id'][4:]}",
            "fecha": ahora(),
            "origen": "captura",
            "capturas": [f["id"] for f in fichas],
            "instantes": [{"captura": f["id"], "t_video": f.get("t_video"),
                           "t_escena": f.get("t_escena")} for f in fichas],
            "texto": instruccion,
        }
        params = estado.paso(paso).get("params") or {}
        bloque = dict((params.get("unidades") or {}).get(unidad) or {})
        historial = list(bloque.get("feedback") or [])
        historial.append(nota)
        bloque["feedback"] = historial
        estado.actualizar_params(paso, {"unidades": {unidad: bloque}})
        # el cambio de params ya deja la unidad sucia, pero invalidarla
        # además cubre el caso de la misma nota repetida, que no mueve
        # la firma
        estado.marcar_obsoleto(paso, [unidad])
        grupos.append({"paso": paso, "reproductor": _paso, "escena": escena,
                       "unidad": f"escena:{escena}",
                       "capturas": [f["id"] for f in fichas],
                       "instruccion": instruccion})
    return grupos
