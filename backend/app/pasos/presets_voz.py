"""Presets de locución: un tono con nombre para el paso de voz.

Adaptado del original (pasos/presets_voz.py, que usaba Cartesia) a los
mandos de ElevenLabs que maneja este estudio. Un preset fija de golpe lo
que de verdad cambia cómo suena una narración: voz, modelo, estabilidad,
similitud y velocidad. La persona elige «true crime tenso» y no tiene
que saber que eso son dos deslizadores y un voice_id.

Los mandos, para quien los lea dentro de dos años:

- `estabilidad` (0..1): baja = más emotiva e inestable; alta = monótona
  y firme. Es EL mando del tono: un tono neutro se consigue con 0.6+,
  uno emocional con 0.2-0.35.
- `similitud` (0..1): cuánto clona el timbre de la voz original.
- `velocidad` (0.7..1.2): 0.8 lento, 1.0 normal, 1.1 apremiante.
- `hueco_minimo` no es un mando del paso voz de este estudio: se guarda
  igual en el preset porque la GUIA de estilo lo lee para decidir el
  aire entre planos (cuánto respira el vídeo).

Las voces sugeridas son del catálogo PÚBLICO de ElevenLabs (las que
viene de serie en toda cuenta), así que un preset se aplica aunque no
se haya añadido ninguna voz propia. La primera de la lista es la
recomendada. Si una voz dejara de existir, `p4_voz` cae a la suya por
defecto al grabar y la pantalla sigue viva.
"""
from __future__ import annotations

import copy

# voice_ids del catálogo público de ElevenLabs (los "premade voices").
VOZ_RACHEL = "21m00Tcm4TlvDq8ikWAM"      # Rachel — calm, neutral
VOZ_ADAM = "pNInz6obpgDQGcFmaJgB"        # Adam — deep, documentary
VOZ_ANTONI = "ErXwobaYiN019PkySvjV"      # Antoni — warm, well-rounded
VOZ_ARNOLD = "VR6AewLTigWG4xSOukaG"      # Arnold — deep, craggy
VOZ_DOMI = "AZnzlk1XvdvUeBnXmlld"        # Domi — strong, confident
VOZ_ELLI = "MF3mGyEYCl7XYWbV9V6O"        # Elli — young, emotional
VOZ_JOSH = "TxGEqnHWrfWFTfGW9XjX"        # Josh — deep, soft
VOZ_SARAH = "EXAVITQu4vr4xnSDxMaL"       # Sarah — soft, news-read
VOZ_LIAM = "TX3LSXxCLLxHy1sSnLYh"        # Liam — youthful
VOZ_DAVE = "CYw3kZ02Hs0563khs1Fj"        # Dave — conversational
VOZ_FIN = "D38z5RcWu1voky8WS1ja"         # Fin — technical, sharp
VOZ_PAUL = "5Q0t7uMcjvnagumLfvZi"        # Paul — serious, formal

#: Nombre de cada voz para pintarlo junto al desplegable sin pagar una
#: descarga del catálogo (la clave basta para aplicar; el nombre es para
#: leerlo). Es un dict plano y no un campo del preset para que el resumen
#: de un preset guardado no dependa de esta tabla.
NOMBRES_VOCES = {
    VOZ_RACHEL: "Rachel", VOZ_ADAM: "Adam", VOZ_ANTONI: "Antoni",
    VOZ_ARNOLD: "Arnold", VOZ_DOMI: "Domi", VOZ_ELLI: "Elli",
    VOZ_JOSH: "Josh", VOZ_SARAH: "Sarah", VOZ_LIAM: "Liam",
    VOZ_DAVE: "Dave", VOZ_FIN: "Fin", VOZ_PAUL: "Paul",
}

PRESETS = {
    "documental_sobrio": {
        "nombre": "Documental sobrio",
        "descripcion": (
            "Narrador clásico de documental: neutro, un punto por debajo "
            "del ritmo natural, firme. Deja que hablen los hechos. Es el "
            "que no se equivoca nunca."
        ),
        "modelo": "multilingual",
        "velocidad": 0.9,
        "estabilidad": 0.65,
        "similitud": 0.8,
        "hueco_minimo": 1.0,
        "voces_sugeridas": [VOZ_RACHEL, VOZ_JOSH, VOZ_ADAM],
    },
    "true_crime_tenso": {
        "nombre": "True crime tenso",
        "descripcion": (
            "Voz contenida con un punto de inestabilidad deliberada: suena "
            "a que lo que viene después es peor. Huecos largos entre "
            "bloques para que respire la amenaza."
        ),
        "modelo": "multilingual",
        "velocidad": 0.85,
        "estabilidad": 0.35,
        "similitud": 0.75,
        "hueco_minimo": 1.3,
        "voces_sugeridas": [VOZ_ARNOLD, VOZ_DOMI, VOZ_JOSH],
    },
    "divulgacion_cercana": {
        "nombre": "Divulgación cercana",
        "descripcion": (
            "Explicador de canal grande: ritmo normal, energía y vida en "
            "la voz (estabilidad baja a propósito). Encadena rápido para "
            "que no se caiga la atención."
        ),
        "modelo": "multilingual",
        "velocidad": 1.0,
        "estabilidad": 0.4,
        "similitud": 0.75,
        "hueco_minimo": 0.6,
        "voces_sugeridas": [VOZ_ANTONI, VOZ_ELLI, VOZ_RACHEL],
    },
    "urgente_noticia": {
        "nombre": "Urgente de noticia",
        "descripcion": (
            "Cabecera de informativo: rápido, con la voz suelta y viva. "
            "Huecos mínimos, sensación de directo. Cansa si dura más de "
            "un minuto; úsalo en aperturas."
        ),
        "modelo": "flash",
        "velocidad": 1.1,
        "estabilidad": 0.3,
        "similitud": 0.75,
        "hueco_minimo": 0.3,
        "voces_sugeridas": [VOZ_ADAM, VOZ_FIN, VOZ_SARAH],
    },
    "reflexivo_pausado": {
        "nombre": "Reflexivo pausado",
        "descripcion": (
            "Ensayo en voz alta: lo más lento del catálogo, voz firme y "
            "limpia, silencios largos. Para cierres, epílogos y planos "
            "contemplativos."
        ),
        "modelo": "multilingual",
        "velocidad": 0.8,
        "estabilidad": 0.55,
        "similitud": 0.8,
        "hueco_minimo": 1.6,
        "voces_sugeridas": [VOZ_SARAH, VOZ_JOSH, VOZ_RACHEL],
    },
    "testimonio_seco": {
        "nombre": "Testimonio seco",
        "descripcion": (
            "Lectura de acta: velocidad normal, estabilidad alta (cero "
            "teatralidad), huecos cortos. Suena a informe, a dato "
            "verificado. Contrasta muy bien intercalado con un preset "
            "emocional."
        ),
        "modelo": "multilingual",
        "velocidad": 1.0,
        "estabilidad": 0.75,
        "similitud": 0.75,
        "hueco_minimo": 0.8,
        "voces_sugeridas": [VOZ_ADAM, VOZ_PAUL, VOZ_ARNOLD],
    },
    "denuncia_indignada": {
        "nombre": "Denuncia indignada",
        "descripcion": (
            "Periodismo de trinchera: estabilidad baja para que la voz se "
            "le vaya de las manos, ritmo normal para que se entienda cada "
            "acusación. Para el bloque en el que el vídeo toma partido."
        ),
        "modelo": "multilingual",
        "velocidad": 1.0,
        "estabilidad": 0.25,
        "similitud": 0.7,
        "hueco_minimo": 0.7,
        "voces_sugeridas": [VOZ_DOMI, VOZ_DAVE, VOZ_ARNOLD],
    },
    "confidencia_susurrada": {
        "nombre": "Confidencia susurrada",
        "descripcion": (
            "Como si contara algo que no debería: lenta y muy viva "
            "(estabilidad por los suelos), pausas largas. Buena para "
            "revelaciones y giros a mitad de vídeo."
        ),
        "modelo": "multilingual",
        "velocidad": 0.8,
        "estabilidad": 0.2,
        "similitud": 0.75,
        "hueco_minimo": 1.2,
        "voces_sugeridas": [VOZ_SARAH, VOZ_LIAM, VOZ_ELLI],
    },
}

POR_DEFECTO = "documental_sobrio"


def listar() -> list[dict]:
    """Presets disponibles como fichas con su id, para pintar la UI."""
    fichas = []
    for identificador, datos in PRESETS.items():
        ficha = copy.deepcopy(datos)
        ficha["id"] = identificador
        ficha["voces_nombres"] = [
            NOMBRES_VOCES.get(v, "") for v in ficha["voces_sugeridas"]]
        fichas.append(ficha)
    fichas.sort(key=lambda f: f["nombre"])
    return fichas


def preset(identificador: str) -> dict:
    """Copia de un preset por id; falla claro si no existe."""
    clave = str(identificador or "").strip()
    if clave not in PRESETS:
        raise ValueError(f"preset de voz desconocido: {identificador!r}. "
                         f"Disponibles: {', '.join(sorted(PRESETS))}")
    return copy.deepcopy(PRESETS[clave])


def params_de(identificador: str) -> dict:
    """Los params del paso voz que fija un preset (sin voz_nombre).

    La voz RECOMENDADA va dentro; la pantalla puede cambiarla por otra
    del catálogo antes de guardar — el preset propone, quien decide es
    quien lo escucha.
    """
    ficha = preset(identificador)
    return {
        "voz": ficha["voces_sugeridas"][0],
        "modelo": ficha["modelo"],
        "estabilidad": ficha["estabilidad"],
        "similitud": ficha["similitud"],
        "velocidad": ficha["velocidad"],
    }
