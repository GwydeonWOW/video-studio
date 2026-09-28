"""El asistente: un chat que contesta con el LLM del estudio.

QUÉ ES
------
La burbuja de abajo a la derecha. Quien la abre pregunta en castellano
--«me ha dado este error», «por qué assets está en naranja», «dónde pongo
la clave de ElevenLabs», «la tanda lleva parada diez minutos»-- y contesta
el MISMO LLM multi-proveedor con el que el estudio escribe los guiones
(rol "asistente", configurable en Configuración -> modelos). No hay ninguna
clave nueva que pedir.

CÓMO CONTESTA
-------------
Tres capas, de más fija a más viva:

1. **El manual del producto**, entero y en el primer mensaje de cada charla:
   qué pasos hay, qué params manda cada uno, cómo se mide el coste.
2. **Una foto del estado AHORA**, delante de CADA pregunta: qué claves hay
   (puestas, nunca el valor), qué proyecto está abierto, en qué estado está
   cada paso, qué trabajos corren o han fallado, los últimos eventos y los
   errores que la pantalla tiene a la vista. La hace la ruta
   (rutas_asistente.foto) y se manda siempre: lo que pasaba hace tres
   preguntas ya no está pasando.
3. **Herramientas**, a demanda: como aquí no hay un CLI con Read/Grep, el
   LLM puede PEDIR que el servidor mire por él -- probar_claves,
   estado_estudio, trabajos, ficha_paso, bitacora, cancelar_trabajo -- con
   el bucle de tool-calling de motores/llm. Van pre-autorizadas: la persona
   espera que el asistente PRUEBE las cosas, no que diga que no puede.

UNA CHARLA ES UNA CONVERSACIÓN RE-ENVIADA
-----------------------------------------
El original reanudaba la sesión del CLI (`--resume`); las llamadas HTTPS no
tienen sesión, así que cada turno viaja con SU historia: el mensaje de
arranque (manual) primero y los turnos posteriores pegados detrás. Si la
historia crece demasiado se recorta por el centro, pero el manual se manda
una sola vez por charla.

Un turno corre en un HILO y la pantalla lo sigue preguntando: la respuesta
puede tardar un minuto, y detrás de un proxy una petición de un minuto se
corta a los sesenta segundos sin decir por qué. Cada charla admite UN turno
a la vez.

SEGURIDAD
---------
En la foto y en las herramientas NUNCA viaja una clave: solo si está puesta
o no, y `cancelar_trabajo` es lo único que cambia algo.

Con ESTUDIO_SIMULAR=1 no se llama a nadie: contesta un doble que repite lo
que recibió, que es lo que dejan comprobar las pruebas de la API.
"""
from __future__ import annotations

import threading
import time
import uuid

from ..motores import llm

#: Rol con el que contesta (Configuración -> modelos). Un chat pide
#: segundos, no minutos: por defecto el modelo rápido del catálogo.
ROL = "asistente"

#: Cuántas charlas se recuerdan y cuánto vive una sin que nadie le hable.
#: Viven en memoria a propósito: recargar la página tiene que reencontrar
#: la charla, reiniciar el servicio no.
MAX_CHARLAS = 30
CADUCIDAD_CHARLA_S = 24 * 3600

#: Tope de una pregunta: un pegado de 200 KB de log no es una pregunta.
MAX_PREGUNTA = 20000

#: Vueltas de herramientas por turno: ocho preguntas de "mira esto" ya son
#: una investigación, no una duda.
MAX_LLAMADAS_HERRAMIENTA = 8

#: Cuántos turnos de historia se re-envían como mucho.
TURNOS_DE_HISTORIA = 24

_LOCK = threading.RLock()
_CHARLAS: dict[str, "Charla"] = {}


class ErrorAsistente(ValueError):
    """Algo que la pantalla puede ENSEÑAR tal cual."""


class Ocupada(ErrorAsistente):
    """La charla ya está contestando: es un 409, no un 400."""


def simulado() -> bool:
    """True si no hay que llamar al LLM (ESTUDIO_SIMULAR=1)."""
    import os
    return str(os.environ.get("ESTUDIO_SIMULAR", "")).strip().lower() in (
        "1", "true", "si")


# ------------------------------------------------------------------ el prompt

def sistema() -> str:
    """El prompt de sistema del asistente."""
    return (
        "Eres el asistente de AS Video Studio, un producto que convierte "
        "texto en un vídeo narrado en ocho pasos (ingesta, brief, guion, voz, "
        "revisión de audio, assets, callouts, render). Hablas con la persona "
        "que lo está usando desde la propia pantalla del estudio, y tu trabajo "
        "es resolver dudas y problemas: qué significa un estado, por qué un "
        "paso está obsoleto o parado, qué dice un error y qué hacer con él, "
        "cómo conseguir o cambiar una clave, cuánto va a costar algo. "
        "Contestas en castellano, en pocas frases, con pasos concretos y "
        "numerados cuando haya que hacer algo, y diciendo dónde está cada "
        "cosa en la pantalla (Configuración es el engranaje de arriba a la "
        "derecha; las claves y los modelos por rol se cambian ahí). Antes de "
        "cada pregunta recibes una foto del estado actual del estudio: fíate "
        "de ella para lo que está pasando ahora mismo. Tienes además "
        "herramientas para comprobar las cosas de verdad: probar_claves "
        "prueba cada clave contra su servicio, estado_estudio repite la foto "
        "fresca, trabajos y ficha_paso y bitacora miran un proyecto, y "
        "cancelar_trabajo para uno colgado. Úsalas sin pedir permiso cuando "
        "la pregunta lo pida: si te preguntan si las claves están bien, "
        "PRUÉBALAS y cuenta el resultado; si algo está parado, mira trabajos "
        "y bitácora antes de contestar. Las claves nunca se enseñan: si te "
        "las piden, di que se cambian en Configuración. Si no sabes algo, "
        "dilo y propone dónde mirar en vez de inventarlo. No repitas la "
        "pregunta ni saludes: contesta.")


def manual() -> str:
    """El manual del producto, en el primer mensaje de cada charla.

    Va en un bloque aparte (no en el prompt de sistema) porque pesa lo suyo
    y así puede recortarse la historia sin perderlo: siempre va primero.
    """
    from ..nucleo.estado import GRAFO, padres_de
    pasos = []
    for paso in GRAFO:
        padres = ", ".join(padres_de(paso)) or "ninguno"
        pasos.append(f"  - {paso} (necesita de: {padres})")
    return (
        "Esto es todo lo que hay que saber del estudio, tal como está "
        "escrito en su repositorio. Léelo entero antes de contestar; "
        "después, en cada turno, recibirás una foto del estado y una "
        "pregunta.\n"
        "\n"
        "=== EL PRODUCTO ===\n"
        "Un estudio que convierte texto en vídeo narrado. Ocho pasos en "
        "cadena: ingesta (texto o enlace), brief (tono/idioma/ritmo), guion "
        "(escenas con narración), voz (locución ElevenLabs), revisión de "
        "audio, assets (imágenes gpt-image-1 por escena), callouts (rótulos "
        "y diseño) y render (ffmpeg). Un paso queda OBSOLETO cuando cambian "
        "sus params o los de sus padres: se re-ejecuta y arrastra a sus "
        "descendientes. Cada ejecución es una tanda con trabajo, progreso y "
        "eventos; el coste se mide por operación en el medidor del "
        "proyecto.\n"
        "\n"
        "=== EL GRAFO ===\n" + "\n".join(pasos) + "\n"
        "\n"
        "=== DÓNDE ESTÁ CADA COSA ===\n"
        "  - Configuración (engranaje arriba a la derecha): claves (GLM, "
        "OpenAI, Anthropic, ElevenLabs, Jamendo, FreeSound), modelos por "
        "rol, tarifas y estadísticas.\n"
        "  - La papelera y los proyectos viven en la galería; duplicar un "
        "proyecto copia su árbol.\n"
        "  - El coste por paso y el desglose están en la vista de coste del "
        "proyecto.\n"
        "  - Sin la clave de GLM (u OpenAI/Anthropic según el rol) no hay "
        "textos; sin OpenAI no hay imágenes; sin ElevenLabs no hay voz.\n")


def _bloque(titulo: str, cuerpo) -> str:
    return f"=== {titulo} ===\n{str(cuerpo or '').strip()}\n"


def mensaje_de_arranque(foto: str, pregunta: str) -> str:
    """El primer mensaje de una charla: manual + foto + pregunta."""
    return "\n".join([
        manual(),
        _bloque("ESTADO DEL ESTUDIO AHORA MISMO (lo hace el servidor, no "
                "la persona)", foto),
        _bloque("PREGUNTA", pregunta),
    ])


def mensaje_de_turno(foto: str, pregunta: str) -> str:
    """Lo que va en cada turno que continúa: la foto de ahora y la pregunta."""
    return (_bloque("ESTADO DEL ESTUDIO AHORA MISMO (lo hace el servidor, "
                    "no la persona)", foto)
            + "\n" + _bloque("PREGUNTA", pregunta))


# ------------------------------------------------------------- herramientas

def _herramientas_def() -> list[dict]:
    """Catálogo normalizado: [{nombre, descripcion, parametros}]."""
    return [
        {"nombre": "probar_claves",
         "descripcion": "Prueba de verdad cada clave de API contra su "
                        "servicio y devuelve si va o no (sin enseñar ningún "
                        "valor).",
         "parametros": {"type": "object", "properties": {}}},
        {"nombre": "estado_estudio",
         "descripcion": "La foto del estado del estudio ahora mismo: claves "
                        "puestas, proyecto abierto y sus pasos, trabajos y "
                        "últimos eventos.",
         "parametros": {"type": "object", "properties": {
             "proyecto": {"type": "string",
                          "description": "id del proyecto; vacío = solo lo "
                                         "global"}}}},
        {"nombre": "trabajos",
         "descripcion": "Los trabajos (tandas) de un proyecto: estado, "
                        "progreso y error del último si falló.",
         "parametros": {"type": "object", "properties": {
             "proyecto": {"type": "string"}}}},
        {"nombre": "ficha_paso",
         "descripcion": "El estado de UN paso de un proyecto: versión, "
                        "params y unidades obsoletas.",
         "parametros": {"type": "object", "properties": {
             "proyecto": {"type": "string"},
             "paso": {"type": "string",
                      "description": "ingesta|brief|guion|voz|revision_audio"
                                     "|assets|callouts|render"}},
             "required": ["proyecto", "paso"]}},
        {"nombre": "bitacora",
         "descripcion": "Los últimos eventos de la bitácora de un proyecto.",
         "parametros": {"type": "object", "properties": {
             "proyecto": {"type": "string"},
             "limite": {"type": "integer",
                        "description": "cuántos eventos, por defecto 20"}}}},
        {"nombre": "cancelar_trabajo",
         "descripcion": "Cancela un trabajo colgado de un proyecto. Es lo "
                        "único que cambia algo: úsalo solo si la persona lo "
                        "pide o el trabajo lleva horas parado.",
         "parametros": {"type": "object", "properties": {
             "trabajo": {"type": "string",
                         "description": "id del trabajo (t000123)"}},
             "required": ["trabajo"]}},
    ]


def _ejecutar_herramienta(nombre: str, args: dict) -> str:
    """Corre una herramienta contra el nucleo y devuelve su texto."""
    import json

    from ..config import AJUSTES
    from ..nucleo.claves import probar_claves
    from ..nucleo.proyecto import Proyecto

    if nombre == "probar_claves":
        return json.dumps(probar_claves(AJUSTES.carpeta_claves),
                          ensure_ascii=False)
    if nombre == "estado_estudio":
        return foto_del_estadio_si_existe(str(args.get("proyecto") or ""))
    if nombre == "trabajos":
        from ..api.rutas_trabajos import GESTOR
        return json.dumps(GESTOR.listar(str(args.get("proyecto") or "") or None),
                          ensure_ascii=False, default=str)
    if nombre == "ficha_paso":
        proyecto = Proyecto(AJUSTES.carpeta_proyectos /
                            str(args.get("proyecto") or ""))
        if not proyecto.existe():
            return "ese proyecto no existe"
        from ..nucleo.estado import Estado
        estado = Estado(proyecto)
        paso = str(args.get("paso") or "")
        ficha = estado.paso(paso)
        return json.dumps({
            "paso": paso,
            "estado": estado.estado_de(paso),
            "version": ficha.get("version", 0),
            "params": ficha.get("params", {}),
            "unidades_obsoletas": estado.unidades_obsoletas(paso),
            "aprobado": estado.esta_aprobado(paso),
        }, ensure_ascii=False, default=str)
    if nombre == "bitacora":
        proyecto = Proyecto(AJUSTES.carpeta_proyectos /
                            str(args.get("proyecto") or ""))
        if not proyecto.existe():
            return "ese proyecto no existe"
        from ..nucleo.proyecto import leer_jsonl
        limite = int(args.get("limite") or 20)
        eventos = leer_jsonl(proyecto.fichero_bitacora)[-limite:]
        return json.dumps(eventos, ensure_ascii=False, default=str)
    if nombre == "cancelar_trabajo":
        from ..api.rutas_trabajos import GESTOR
        try:
            return json.dumps(GESTOR.cancelar(str(args.get("trabajo") or "")),
                              ensure_ascii=False, default=str)
        except KeyError:
            return "no hay ningún trabajo con ese id"
    return f"herramienta desconocida: {nombre}"


def foto_del_estadio_si_existe(pid: str) -> str:
    """Wrapper tolerante: la foto vive en la ruta, y aquí puede faltar."""
    try:
        from ..api.rutas_asistente import foto_del_estudio
        return foto_del_estudio(pid)
    except Exception as fallo:                          # noqa: BLE001
        return f"(no se ha podido hacer la foto del estado: {fallo})"


# ------------------------------------------------------------- la ejecución

def _contestar_de_verdad(charla: "Charla", pregunta: str, foto: str) -> tuple[str, dict]:
    """El turno de verdad: historia + foto + bucle de herramientas.

    -> (texto, sobre) donde sobre trae el uso de tokens acumulado.
    """
    from . import comun
    llamada = llm.rol_config(ROL, comun.ajustes_llm())
    llamada.sistema = sistema()
    llamada.max_tokens = 4096
    llamada.temperatura = 0.4
    llamada.contexto = "asistente"
    llamada.proyecto = charla.pid

    mensajes: list[dict] = list(charla.historia())
    arranque = (len(mensajes) == 0)
    mensajes.append({"rol": "user", "texto":
                     mensaje_de_arranque(foto, pregunta) if arranque
                     else mensaje_de_turno(foto, pregunta)})

    herramientas = _herramientas_def()
    uso_total = {"entrada": 0, "salida": 0}
    vueltas = 0
    while True:
        if charla.cancelado:
            raise ErrorAsistente("cancelado")
        resultado = llm.llamar_conversacion(
            llamada, mensajes, herramientas=herramientas,
            claves=comun.claves_actuales())
        uso = resultado.get("uso") or {}
        uso_total["entrada"] += int(uso.get("entrada") or 0)
        uso_total["salida"] += int(uso.get("salida") or 0)
        llamadas = resultado.get("llamadas") or []
        if not llamadas or vueltas >= MAX_LLAMADAS_HERRAMIENTA:
            return resultado.get("texto") or "", uso_total
        # el mensaje del asistente pidiendo herramientas + sus resultados
        mensajes.append({"rol": "asistente", "texto":
                         resultado.get("texto") or "", "llamadas": llamadas})
        for llamada_h in llamadas:
            vueltas += 1
            try:
                texto_h = _ejecutar_herramienta(
                    llamada_h["nombre"], llamada_h.get("argumentos") or {})
            except Exception as fallo:                  # noqa: BLE001
                texto_h = f"error de la herramienta: {fallo}"
            mensajes.append({"rol": "user", "resultados": [
                {"id": llamada_h["id"], "texto": str(texto_h)[:20000]}]})


def _contestar_simulado(charla: "Charla", pregunta: str, foto: str) -> tuple[str, dict]:
    """El doble de las pruebas: no llama a nadie y cuenta lo que recibió."""
    reanuda = bool(charla.historia())
    return (f"(simulado) He recibido una foto de {len(foto)} caracteres"
            f"{' reanudando la charla' if reanuda else ' de arranque'}. "
            f"Me preguntas: {pregunta}",
            {"entrada": (len(foto) + len(pregunta)) // 4, "salida": 40})


# ------------------------------------------------------------------ la charla

class Charla:
    """Una conversación: sus turnos visibles y la historia para el LLM.

    Estados de un turno del asistente (los pinta la pantalla):

        pensando   el LLM está en ello
        listo      contestó; `texto` es la respuesta
        error      no pudo; `texto` dice por qué
        cancelado  se le pidió parar
    """

    def __init__(self, cid: str | None = None):
        self.id = cid or uuid.uuid4().hex[:12]
        self.turnos: list[dict] = []
        self.creada = time.time()
        self.tocada = self.creada
        self.pid = ""
        self.cancelado = False
        self._historia: list[dict] = []
        self._lock = threading.RLock()
        self._hilo: threading.Thread | None = None

    # -- lo que ve la pantalla
    def ver(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "proyecto": self.pid,
                "turnos": [dict(t) for t in self.turnos],
                "ocupada": self.ocupada(),
                "modelo": self._modelo(),
            }

    def _modelo(self) -> str:
        try:
            from . import comun
            llamada = llm.rol_config(ROL, comun.ajustes_llm())
            return f"{llamada.proveedor}/{llamada.modelo}"
        except Exception:                               # noqa: BLE001
            return ROL

    def ocupada(self) -> bool:
        return bool(self.turnos) and self.turnos[-1].get("estado") == "pensando"

    def caducada(self) -> bool:
        return time.time() - self.tocada > CADUCIDAD_CHARLA_S

    def historia(self) -> list[dict]:
        """La historia para el LLM: el manual primero, recortada por el medio."""
        with self._lock:
            historia = list(self._historia)
        if len(historia) <= TURNOS_DE_HISTORIA:
            return historia
        # el primer mensaje (manual) se queda; el resto se recorta por detrás
        return [historia[0]] + historia[-(TURNOS_DE_HISTORIA - 1):]

    def _anadir(self, quien: str, texto: str, estado: str = "listo", **extra) -> dict:
        turno = {"n": len(self.turnos) + 1, "quien": quien, "texto": texto,
                 "estado": estado, "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
        turno.update(extra)
        self.turnos.append(turno)
        return turno

    def preguntar(self, pregunta: str, foto: str, pid: str = "") -> dict:
        """Arranca un turno. -> la ficha de la charla, con el turno 'pensando'.

        No espera: el turno corre en un hilo y la pantalla vuelve a preguntar.
        """
        pregunta = str(pregunta or "").strip()
        if not pregunta:
            raise ErrorAsistente("escribe algo que preguntar")
        if len(pregunta) > MAX_PREGUNTA:
            raise ErrorAsistente(
                f"la pregunta pasa de {MAX_PREGUNTA} caracteres; si es un log, "
                f"pega solo el trozo donde está el error")
        with self._lock:
            if self.ocupada():
                raise Ocupada("todavía está contestando la anterior; espera "
                              "o cancélala")
            self.tocada = time.time()
            self.pid = str(pid or "")
            self.cancelado = False
            self._anadir("tu", pregunta)
            respuesta = self._anadir("asistente", "", estado="pensando",
                                     segundos=0)
        ejecutar = _contestar_simulado if simulado() else _contestar_de_verdad
        hilo = threading.Thread(
            target=self._correr,
            args=(pregunta, foto, ejecutar, respuesta, time.time()),
            daemon=True)
        self._hilo = hilo
        hilo.start()
        return self.ver()

    def _correr(self, pregunta: str, foto: str, ejecutar, respuesta: dict,
                arranque: float) -> None:
        try:
            texto, uso = ejecutar(self, pregunta, foto)
            with self._lock:
                self._historia.append({"rol": "user", "texto": pregunta})
                self._historia.append({"rol": "asistente", "texto": texto})
                respuesta.update({
                    "texto": texto, "estado": "listo",
                    "segundos": round(time.time() - arranque, 1),
                    "tokens": {"entrada": int(uso.get("entrada") or 0),
                               "salida": int(uso.get("salida") or 0)},
                })
        except Exception as fallo:                      # noqa: BLE001 - el motivo va a la pantalla
            with self._lock:
                cancelado = self.cancelado
                respuesta.update({
                    "estado": "cancelado" if cancelado else "error",
                    "texto": ("cancelado" if cancelado
                              else f"{type(fallo).__name__}: {fallo}"),
                    "segundos": round(time.time() - arranque, 1),
                })
        finally:
            with self._lock:
                self.tocada = time.time()

    def cancelar(self) -> bool:
        """Para el turno en marcha. -> bool (había uno).

        La llamada HTTP en curso no se puede cortar a mitad: se anula la
        vuelta siguiente (entre herramientas) y el turno muere al volver.
        """
        with self._lock:
            habia = self.ocupada()
            if habia:
                self.cancelado = True
        return habia


# ------------------------------------------------------------------ registro

def _barrer() -> None:
    """Se lleva las charlas caducadas y, si sobran, las más viejas."""
    for cid, charla in list(_CHARLAS.items()):
        if charla.caducada() and not charla.ocupada():
            _CHARLAS.pop(cid, None)
    if len(_CHARLAS) > MAX_CHARLAS:
        libres = sorted((c for c in _CHARLAS.values() if not c.ocupada()),
                        key=lambda c: c.tocada)
        for charla in libres[:len(_CHARLAS) - MAX_CHARLAS]:
            _CHARLAS.pop(charla.id, None)


def nueva() -> Charla:
    with _LOCK:
        _barrer()
        charla = Charla()
        _CHARLAS[charla.id] = charla
        return charla


def obtener(cid: str) -> Charla | None:
    with _LOCK:
        _barrer()
        return _CHARLAS.get(str(cid or ""))


def olvidar(cid: str) -> bool:
    """Tira una charla, cancelando lo que tuviera en marcha. -> bool"""
    with _LOCK:
        charla = _CHARLAS.pop(str(cid or ""), None)
    if charla is None:
        return False
    charla.cancelar()
    return True


def estado() -> dict:
    """Si el asistente puede contestar: rol resuelto y clave presente."""
    from . import comun
    from ..motores.llm import clave_de, PROVEEDORES
    llamada = llm.rol_config(ROL, comun.ajustes_llm())
    claves = comun.claves_actuales()
    lista = enmascarado_simple(claves)
    listo = bool(clave_de(llamada.proveedor, claves)) or simulado()
    motivo = "" if listo else (
        f"falta la clave de {PROVEEDORES[llamada.proveedor]['nombre']} "
        f"({PROVEEDORES[llamada.proveedor]['variable']}); se pone en "
        f"Configuración -> claves")
    cuenta = f"{PROVEEDORES[llamada.proveedor]['nombre']} · {llamada.modelo}"
    return {"listo": listo, "motivo": motivo, "cuenta": cuenta,
            "claves": lista, "modelo": cuenta,
            "simulado": simulado()}


def enmascarado_simple(claves: dict) -> list[dict]:
    """Qué claves hay puestas, sin ningún valor (para la foto y el estado)."""
    from ..nucleo.claves import CATALOGO
    return [{"clave": clave, "presente": bool(claves.get(clave))}
            for clave, *_ in CATALOGO]


def describir() -> str:
    return f"asistente con el rol '{ROL}' del estudio, herramientas de " \
           f"lectura y cancelar_trabajo"
