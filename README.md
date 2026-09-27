# Estudio de Vídeo

Réplica auto-hospedada de [as-video-studio](https://github.com/NeverBlink/as-video-studio):
un pipeline de 8 pasos que convierte un artículo en un vídeo narrado, con
interfaz basada en [shadcn/ui](https://ui.shadcn.com), motor **multi-modelo**
(GLM de z.ai, GPT de OpenAI, Anthropic…) y locución con **ElevenLabs**.

```
ingesta → brief → guion → voz → revisión de audio → assets → callouts → render
```

Un solo servicio (FastAPI + ffmpeg + la web estática) y una carpeta de datos:
todo lo demás se pierde sin drama al reiniciar.

## Decisiones tomadas

- **Motor en Python, no en Rust.** El cuello de botella son las APIs externas
  (LLM, imágenes, TTS) y ffmpeg, que ya es nativo; reescribir el orquestador
  aportaría complejidad sin acelerar el pipeline. Detalles y números en
  [`docs/DECISION-MOTOR.md`](docs/DECISION-MOTOR.md).
- **Auditoría del original:** hallazgos H1–H8 y cómo se mitigan aquí en
  [`docs/AUDITORIA.md`](docs/AUDITORIA.md) (inyección en shell, rutas, CSRF,
  exposición de claves…).

## Despliegue en Coolify

1. Crea una app nueva → **Dockerfile** (o **Docker Compose** con el
   `docker-compose.yml` de la raíz) apuntando a este repositorio.
2. Puerto: **8000** (Coolify le pone el dominio/HTTPS delante).
3. **Imprescindible:** volumen persistente montado en `/datos`
   (proyectos, claves cifradas, sesiones de coste). Sin él, todo se
   borra en cada despliegue.
4. Variables recomendadas:
   - `ESTUDIO_ORIGEN=https://tu-dominio` — activa el chequeo de Origin en
     las mutaciones (CSRF). Sin ella el servicio funciona, pero con la
     comprobación relajada.
   - `ESTUDIO_USUARIO`, y opcionalmente `ESTUDIO_HASH` (ver abajo).
5. Healthcheck: `GET /api/salud` (público y sin coste).
6. Al abrir la web por primera vez, el propio interfaz pide fijar la
   **contraseña** (flujo de primera instalación). Después: Configuración →
   Claves, guarda las API keys y pruébalas con un clic.

Contraseña sin pasar por la UI: genera el hash y pásalo en `ESTUDIO_HASH`:

```bash
docker run --rm -e CLAVE=tu-clave estudio-video python -c \
  "from app.seguridad import hash_contrasena; import os; \
   print(hash_contrasena(os.environ['CLAVE']))"
```

Todas las variables: [`.env.example`](.env.example).

## Desarrollo local (Windows/Laragon o Linux)

Requisitos: Python 3.12+, Node 20+, ffmpeg en PATH.

```bash
# backend (http://127.0.0.1:8000)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload

# frontend (http://127.0.0.1:5173, proxy a /api y /a)
cd frontend
npm install
npm run dev
```

Datos y claves en `datos/` (raíz). Para construir la web que sirve el
backend: `npm run build` en `frontend/` (deja `frontend/dist`).

Prueba de humo de la API completa (sin tocar servicios de pago):

```bash
cd backend && python pruebas/humo_api.py
```

## Configuración de modelos

Configuración → **Modelos por rol**: cada tarea usa el proveedor/modelo que
quieras sin tocar código:

| Rol | Uso |
|---|---|
| `guion` | brief + escenas del guion |
| `correccion` | reescritura de escenas concretas |
| `titulos` | título del vídeo y textos en pantalla |
| `descripcion` | prompts de imagen de los planos |

Las claves se guardan en el volumen (nunca vuelven al navegador; la UI solo
ve los últimos 4 caracteres) y se pueden probar con llamadas gratuitas.

## Estructura

```
backend/app
├── main.py            # fábrica: API + SPA en un servicio
├── config.py          # todo por variables de entorno
├── seguridad.py       # login con cookie httpOnly + chequeo de Origin
├── api/               # rutas: auth, config, proyectos, trabajos, archivos
├── motores/           # llm (multi-proveedor), voz_elevenlabs, imagen
├── nucleo/            # proyectos, estado/obsolescencia, trabajos, coste, claves
└── pasos/             # los 8 pasos del pipeline (p1…p8)
frontend/src
├── vistas/            # Login, Galeria, Proyecto (paneles por paso), Configuracion
├── components/ui/     # shadcn/ui vendida, props en español
└── lib/               # api, tipos espejo del backend, hook SSE de trabajos
```

Coste: cada operación queda tarificada (Configuración → Tarifas) y visible
por proyecto y global; los pasos muestran una estimación antes de ejecutar.
