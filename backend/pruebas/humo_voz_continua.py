"""Prueba de humo de la voz continua (p4) + anotaciones + ruido de sala.

La voz se graba en UNA toma y se corta despues por escenas usando las
marcas de palabra; el aire entre escenas se ensancha con ruido de sala
sin re-sintetizar, y las anotaciones `<break>` viajan en el texto que
el motor calla. Se comprueba todo SIN pagar nada (el motor de
ElevenLabs va doblado):

- marcas_tts: limpiar/contar (la horquilla mide lo que se OYE), sanear
  (rango, fusion, etiquetas fuera de vocabulario BORRADAS, idempotente),
  para_tts (ms -> s del motor), pausa_al_final (sustituye, no suma)
- p3: _a_salida sanea y respeta abre_seccion; _palabras_de no cuenta
  etiquetas; _pausas_estructurales sopla el gancho y las secciones
- voz_elevenlabs: cabecera WAV, repartir_palabras (tolerancia y sobra),
  espaciar + aplicar_desplazamiento (el retardo acumulado)
- p4.ejecutar en modo continua: toma doblada -> fichas por escena con
  WAV propio, marcas en SU reloj, hueco garantizado y sin solapes

Ejecutar:

    python pruebas/humo_voz_continua.py

Sale 0 si todo verde.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
_dir_datos = tempfile.mkdtemp(prefix="estudio_toma_")
os.environ["ESTUDIO_DATOS"] = str(Path(_dir_datos) / "datos")
os.environ["ESTUDIO_ELEVENLABS_KEY"] = "clave-de-prueba"
os.environ.pop("ESTUDIO_HASH", None)
sys.path.insert(0, str(_raiz))

from app.nucleo.proyecto import Proyecto, escribir_json  # noqa: E402
from app.pasos import marcas_tts, p3_guion, p4_voz  # noqa: E402
from app.motores import voz_elevenlabs  # noqa: E402

fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "ok " if condicion else "FALLO"
    print(f"[{marca}] {nombre}" + (f" - {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


class TrabajoMudo:
    def avance(self, *_):
        pass

    def comprobar_cancelacion(self):
        pass


# ------------------------------------------------------------- marcas_tts

check("limpiar quita las etiquetas y los espacios dobles",
      marcas_tts.limpiar('Frase <break time="700ms"/> con  aire') ==
      "Frase con aire",
      marcas_tts.limpiar('Frase <break time="700ms"/> con  aire'))
check("limpiar se traga cualquier cosa con forma de etiqueta",
      "<musica>no</musica>" not in marcas_tts.limpiar("<musica>no</musica>")
      and marcas_tts.limpiar("<musica>no</musica>") == "no")
check("contar_palabras mide lo que se OYE, no las etiquetas",
      marcas_tts.contar_palabras('uno dos <break time="700ms"/> tres') == 3)

saneado = marcas_tts.sanear(
    'uno <break time="3000ms"/> dos <break time="40ms"/> '
    '<speed="2">tres</speed> <break time="300ms"/> '
    '<break time="500ms"/> cuatro')
check("sanear recorta al maximo, tira el minimo y borra lo desconocido",
      '<break time="2500ms"/>' in saneado
      and 'time="40ms"' not in saneado
      and "speed" not in saneado,
      saneado)
check("sanear funde dos silencios seguidos en uno",
      saneado.count("<break") == 2, saneado)
check("sanear es idempotente",
      marcas_tts.sanear(saneado) == saneado)
check("una escena que solo trae etiquetas no es una escena",
      marcas_tts.sanear('<break time="700ms"/>') == "")
check("revisar avisa de lo que ha tenido que corregir",
      any("vocabulario" in a for a in
          marcas_tts.revisar('<em>hola</em> <break time="9ms"/>')))

check("para_tts reescribe a SEGUNDOS para el motor",
      marcas_tts.para_tts('<break time="900ms"/>') ==
      '<break time="0.9s"/>'
      and marcas_tts.para_tts('<break time="250ms"/>') ==
      '<break time="0.25s"/>',
      marcas_tts.para_tts('<break time="900ms"/>'))

check("silencio_final cuenta la cola de silencio",
      marcas_tts.silencio_final('frase <break time="700ms"/> '
                                '<break time="200ms"/>') == 900.0)
con_paleta = marcas_tts.pausa_al_final("frase que remata", 900)
check("pausa_al_final pone el aire del gancho si no esta",
      con_paleta.endswith('<break time="900ms"/>'), con_paleta)
check("pausa_al_final respeta el silencio que ya hay",
      marcas_tts.pausa_al_final('frase <break time="1200ms"/>', 900) ==
      'frase <break time="1200ms"/>')
sustituida = marcas_tts.pausa_al_final('frase <break time="400ms"/>', 900)
check("pausa_al_final SUSTITUYE el silencio corto (no suma dos)",
      sustituida.count("<break") == 1
      and sustituida.endswith('<break time="900ms"/>'), sustituida)

check("texto_de_marca conserva la palabra y tira la etiqueta suelta",
      marcas_tts.texto_de_marca("palabra<break") == "palabra"
      and marcas_tts.texto_de_marca("<break") is None)
check("es_token_de_etiqueta detecta la marca sin palabra",
      marcas_tts.es_token_de_etiqueta('<break time="0.4s"/>')
      and not marcas_tts.es_token_de_etiqueta("hola"))

# ------------------------------------------------------ p3: salida y pausas

respuesta = {"escenas": [
    {"id": "S001", "titulo": "gancho",
     "narracion": 'Frase uno. <break time="3000ms"/>',
     "visual": "v", "texto_pantalla": "x", "abre_seccion": False},
    {"id": "S002", "titulo": "desarrollo",
     "narracion": "Frase dos y sigue el relato",
     "visual": "v", "texto_pantalla": "x"},
    {"id": "S003", "titulo": "capitulo nuevo",
     "narracion": "Frase tres abre capitulo",
     "visual": "v", "texto_pantalla": "x", "abre_seccion": True},
    {"id": "S004", "titulo": "cierre", "narracion": "Frase cuatro",
     "visual": "v", "texto_pantalla": "x"},
]}
salida = p3_guion._a_salida(respuesta, {
    "S002": {"texto": 'Texto a mano con <break time="700ms"/> aire.'}})
check("_a_salida sanea lo que trae el modelo",
      salida[0]["narracion"].endswith('<break time="2500ms"/>'),
      salida[0]["narracion"])
check("_a_salida respeta el texto a mano (saneado tambien)",
      salida[1]["narracion"] ==
      'Texto a mano con <break time="700ms"/> aire.',
      salida[1]["narracion"])
check("_a_salida conserva abre_seccion como estructura",
      salida[0]["abre_seccion"] is False
      and salida[2]["abre_seccion"] is True)
check("_palabras_de cuenta lo que se oye, sin etiquetas",
      p3_guion._palabras_de(salida) == 2 + 5 + 4 + 2,
      str(p3_guion._palabras_de(salida)))

p3_guion._pausas_estructurales(salida, {"pausa_gancho_ms": 900,
                                        "pausa_seccion_ms": 900})
check("pausa del gancho al final de la PRIMERA escena",
      marcas_tts.silencio_final(salida[0]["narracion"]) == 2500.0
      and salida[0]["narracion"].count("<break") == 1,
      salida[0]["narracion"])
check("pausa de seccion al final de la ANTERIOR (no en la primera)",
      salida[1]["narracion"].endswith('<break time="900ms"/>')
      and marcas_tts.silencio_final(salida[1]["narracion"]) == 900.0
      and "<break" not in salida[2]["narracion"],
      salida[1]["narracion"])
check("la duracion estimada suma el aire del silencio",
      salida[0]["duracion_estimada"] >
      p3_guion.comun.duracion_estimada("Frase uno."),
      str(salida[0]["duracion_estimada"]))

# --------------------------------------------- voz_elevenlabs: PCM y corte

pcm2s = b"\x01\x02" * voz_elevenlabs.SR      # 1 segundo de PCM s16 mono
cab = voz_elevenlabs.wav_de_pcm(pcm2s)
check("wav_de_pcm escribe cabecera RIFF PCM 44100 mono s16",
      cab[:4] == b"RIFF" and cab[8:12] == b"WAVE"
      and struct.unpack("<I", cab[24:28])[0] == voz_elevenlabs.SR
      and struct.unpack("<H", cab[22:24])[0] == 1
      and struct.unpack("<H", cab[34:36])[0] == 16
      and struct.unpack("<I", cab[40:44])[0] == len(pcm2s))

def _palabra(txt, i, f):
    return {"palabra": txt, "inicio": i, "fin": f}

reparto = voz_elevenlabs.repartir_palabras(
    [{"id": "A", "narracion": "hola mundo"},
     {"id": "B", "narracion": "adios mundo cruel"}],
    [_palabra("Hola,", 0.0, 0.2), _palabra("pues", 0.3, 0.4),
     _palabra("mundo.", 0.5, 0.7), _palabra("adios", 0.8, 1.0),
     _palabra("mundo", 1.1, 1.3), _palabra("cruel.", 1.4, 1.6),
     _palabra("sobra", 1.7, 1.8)])
check("repartir_palabras tolera puntuacion y tokens de mas",
      [p["palabra"] for p in reparto["A"]] == ["Hola,", "pues", "mundo."]
      and [p["palabra"] for p in reparto["B"]] ==
      ["adios", "mundo", "cruel.", "sobra"],
      str(reparto))

pcm_corte = b"\x00\x00" * int(2.0 * voz_elevenlabs.SR)
pcm_nuevo, desplazamientos = voz_elevenlabs.espaciar(
    pcm_corte,
    {"A": [_palabra("uno", 0.1, 0.4), _palabra("dos", 0.4, 0.5)],
     "B": [_palabra("tres", 0.9, 1.2)]},
    hueco_minimo=1.0)
check("espaciar ensancha el hueco sin tocar el resto",
      len(pcm_nuevo) == len(pcm_corte) + int(0.6 * voz_elevenlabs.SR * 2)
      and desplazamientos == [{"desde": 0.7, "retardo": 0.6}],
      str(desplazamientos))
check("aplicar_desplazamiento retrasa solo lo de despues del corte",
      voz_elevenlabs.aplicar_desplazamiento(0.5, desplazamientos) == 0.5
      and voz_elevenlabs.aplicar_desplazamiento(0.9, desplazamientos)
      == 1.5)
relleno = voz_elevenlabs._relleno_de_sala(pcm_corte, 0.5, 0.9, 0.6)
check("el relleno de sala mide lo pedido y no es cero digital",
      len(relleno) == int(0.6 * voz_elevenlabs.SR * 2) & ~1,
      str(len(relleno)))

# ----------------------------------------------- p4: la toma continua entera

# toma sintetica (en el reloj de la TOMA): 8 palabras por escena, huecos
# naturales de 0.36 s que espaciar tendra que ensanchar hasta 1.0
PALABRAS_TOMA, t = [], 0.2
ESCNAS_TEXTO = ["El transistor nacio de un trozo de silicio sucio.",
                "Amplificaba senales pequenas hasta volverlas gritos.",
                "El mundo entero escucho el rumor de aquel invento."]
for texto in ESCNAS_TEXTO:
    for palabra in texto.split():
        PALABRAS_TOMA.append(_palabra(palabra, round(t, 3),
                                      round(t + 0.10, 3)))
        t += 0.12
    t += 0.36        # el hueco natural entre escenas
DUR_TOMA = round(t + 0.16, 3)     # cola final
# una marca que solo trae la etiqueta: no es una palabra y el reparto no
# puede esperarla
PALABRAS_TOMA.append(_palabra('<break time="0.4s"/>', DUR_TOMA, DUR_TOMA))

capturado: dict = {}


def _habla_doblada(texto, voz, destino, **kwargs):
    capturado["texto"] = texto
    destino.write_bytes(b"MP3-DE-PRUEBA")
    return {"ruta": destino, "duracion": DUR_TOMA,
            "palabras": PALABRAS_TOMA}


def _pcm_doblado(mp3, **kwargs):
    return b"\x00\x00" * int(DUR_TOMA * voz_elevenlabs.SR)


voz_elevenlabs.hablar_con_marcas = _habla_doblada
voz_elevenlabs.pcm_de_mp3 = _pcm_doblado

_dir_proy = Path(os.environ["ESTUDIO_DATOS"]) / "proyectos" / "prueba_toma"
(_dir_proy / "pasos" / "guion").mkdir(parents=True)
escribir_json(_dir_proy / "proyecto.json", {"nombre": "toma"})
escribir_json(_dir_proy / "pasos" / "guion" / "datos.json", {"escenas": [
    {"id": "S001", "titulo": "uno",
     # la anotacion viaja en el guion: el motor la calla
     "narracion": ESCNAS_TEXTO[0] + ' <break time="400ms"/>'},
    {"id": "S002", "titulo": "dos", "narracion": ESCNAS_TEXTO[1]},
    {"id": "S003", "titulo": "tres", "narracion": ESCNAS_TEXTO[2]},
]})
proyecto = Proyecto(_dir_proy)

resultado = p4_voz.ejecutar(proyecto, {"modo": "continua",
                                       "hueco_minimo": 1.0}, TrabajoMudo())
fichas = resultado["escenas"]
check("la toma continua devuelve fichas por escena en modo continua",
      resultado.get("modo") == "continua" and len(fichas) == 3)
check("al motor le llega el texto en SEGUNDOS y saneado",
      'time="0.4s"' in capturado["texto"]
      and "400ms" not in capturado["texto"]
      and capturado["texto"].count("<break") == 1,
      capturado["texto"][-40:])
check("cada escena sale con su WAV propio",
      all((proyecto.raiz / "pasos" / "voz" / "audio" /
           f"{f['id']}.wav").exists() for f in fichas))
check("las marcas viajan en el reloj de CADA escena",
      all(abs(f["palabras"][0]["inicio"]) < 1.0 for f in fichas)
      and [len(f["palabras"]) for f in fichas] ==
      [len(t.split()) for t in ESCNAS_TEXTO],
      str([f["palabras"][0]["inicio"] for f in fichas]))
check("la marca de etiqueta no llega al reparto",
      all(p["palabra"] != '<break time="0.4s"/>'
          for f in fichas for p in f["palabras"]))
contiguas = abs(sum(f["duracion"] for f in fichas) - resultado["duracion"]) \
    < 0.02
check("los cortes tilean la toma sin solapes ni huecos", contiguas,
      f"{[f['duracion'] for f in fichas]} vs {resultado['duracion']}")
_aire = (fichas[0]["duracion"] - fichas[0]["palabras"][-1]["fin"]) \
    + fichas[1]["palabras"][0]["inicio"]
check("el aire entre escenas llega al hueco pedido (ruido de sala)",
      _aire >= 0.99, f"{_aire:.3f} s")
check("la duracion total crece con el aire ensanchado",
      abs(resultado["duracion"] - (DUR_TOMA + 1.24)) < 0.02,
      f"{resultado['duracion']} vs {DUR_TOMA + 1.24}")

# sin hueco pedido no se toca la toma
resultado0 = p4_voz.ejecutar(proyecto, {"modo": "continua",
                                        "hueco_minimo": 0}, TrabajoMudo())
check("hueco_minimo 0 apaga el espaciado",
      abs(resultado0["duracion"] - DUR_TOMA) < 0.02,
      f"{resultado0['duracion']} vs {DUR_TOMA}")

print()
if fallos:
    print(f"{len(fallos)} FALLO(S): " + ", ".join(fallos))
    sys.exit(1)
print("voz continua: todo verde")
