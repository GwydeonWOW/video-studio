# Auditoría de seguridad — as-video-studio (original) y medidas de la réplica

Fecha: 2026-09-27 · Analizado: repositorio NeverBlink/as-video-studio (copia en
`_original/`, solo lectura). La réplica aplica las correcciones indicadas en
cada hallazgo.

## Resumen ejecutivo

El original está **diseñado para correr detrás de un proxy de login separado**
(servicio Node en `despliegue/login/`): su API no autentica nada, a propósito.
Ese login está bien construido (scrypt con comparación en tiempo constante,
helmet, rate-limit, chequeo de Origin). Los riesgos reales aparecen cuando la
API queda expuesta sin ese frontal, y en un patrón de `shell=True` aislado.
La réplica **integra la autenticación en el propio servicio** y elimina los
patrones peligrosos.

## Hallazgos

### H1 — CRÍTICO: la API del Estudio no autentica nada (por diseño)

- **Dónde**: `app.py` (todos los endpoints `/api/...`), sin middleware de auth.
- **Dónde**: lo asume el README: *«la API no autentica nada, a propósito»*; el
  frontal es `despliegue/login/` + nginx (`despliegue/nginx-sitio.conf`).
- **Impacto**: si el puerto de uvicorn queda expuesto (misconfiguración de
  proxy, `--host 0.0.0.0` sin frontal, red interna con más gente), cualquiera
  puede: usar tus claves de API para generar imágenes y voz **con tu dinero**,
  leer material de los proyectos, borrar proyectos y leer la bitácora.
- **En la réplica**: sesión de usuario **dentro del propio servicio** (cookie
  httpOnly + SameSite=Lax, scrypt para la contraseña, rate-limit en el login,
  chequeo de Origin en las mutaciones). Exponer el puerto ya no entrega el
  estudio. Ver `backend/app/seguridad.py`.

### H2 — ALTO: inyección de comandos vía `shell=True`

- **Dónde**: `motores/revision/regenerar.py:193-202` —
  `subprocess.run([... "-p", instruccion ...], shell=True)`.
- **Qué pasa**: `instruccion` interpola `feedback` **texto libre del usuario**
  (`INSTRUCCION_AGENTE.format(feedback=...)`, línea 177-184) y viaja como
  argumento con `shell=True`. En POSIX, lista+`shell=True` ejecuta `sh -c` con
  el primer elemento; en Windows, la lista se une y pasa a `cmd /c`. Un
  feedback con metacaracteres de shell puede ejecutar comandos arbitrarios
  con los privilegios del servicio.
- **Contexto**: es el ÚNICO `shell=True` de todo el repo (el resto de llamadas
  a ffmpeg/Edge/ffprobe van con lista de argumentos, sin shell — correcto).
- **En la réplica**: ninguna llamada a subprocess usa `shell=True` (regla
  fijada en código y revisada por prueba automatizada). La instrucción al LLM
  viaja por HTTPS como campo JSON, no por línea de comandos.

### H3 — ALTO: agente de corrección con permisos de escritura

- **Dónde**: `motores/revision/regenerar.py:194-199` — el CLI se lanza con
  `--permission-mode acceptEdits` y `--add-dir MOTORES`.
- **Qué pasa**: el modelo puede **editar ficheros** del proyecto y del director
  de motores sin confirmación. El material de ingesta es texto del usuario (o
  pegado de terceros): un *prompt injection* en ese material puede dirigir
  escrituras dentro de esos directorios. El propio CLAUDE.md documenta que el
  veto de lectura de `secretos/` es una regla de permisos del CLI — es decir,
  la contención depende de la configuración del CLI, no del sistema.
- **En la réplica**: no hay agente con capacidad de escritura: los modelos se
  llaman por API y **solo devuelven texto**; quien escribe en disco es
  exclusivamente el código del backend, dentro del proyecto y tras validación.

### H4 — MEDIO: claves de API en claro en disco

- **Dónde**: `secretos/claves.json` (fuera de git, correcto), pero sin cifrado.
- **Impacto**: cualquier proceso o copia de seguridad que lea el volumen lee
  las claves. La UI enmascara bien (etiqueta + últimos 4), pero el fichero es
  plano.
- **En la réplica**: igual de pragmático (auto-hospedado, volumen dedicado
  `secretos/` con permisos restringidos y fuera del build de Docker), con una
  diferencia: el fichero se crea con `0600` y las claves NUNCA salen por la
  API (ni en los logs); `GET /api/claves` solo devuelve máscara y estado,
  y `prueba de clave` se hace desde el servidor.

### H5 — MEDIO: rasterizado de contenido no confiado con `file://`

- **Dónde**: `pasos/medios.py:1718-1728` — Edge headless abre `file:///` de un
  SVG/HTML compuesto con datos del guion (salida de LLM + texto del usuario).
- **Impacto**: el contenido puede referenciar recursos externos (`<img
  href="http://...">`): fuga de datos del proyecto hacia fuera (exfiltración
  pasiva) o peticiones a servicios internos desde el servidor (SSRF interno
  desde el navegador). El navegador corre sin sandbox extra más allá de sus
  flags.
- **En la réplica**: el HTML de los planos se genera con contenido **escapado**
  y con URLs de imagen convertidas a rutas locales (las imágenes referenciadas
  viven en el proyecto); el Chromium de rasterizado se lanza con
  `--disable-extensions --no-first-run --disable-gpu` + perfil temporal y
  **sin acceso a red** (contenido autosuficiente con recursos embebidos);
  cualquier recurso externo no se resuelve y no se pide.

### H6 — MEDIO: sin CSRF propio en la API del Estudio

- **Dónde**: la API confía en que el frontal nginx la deje en el mismo origen.
- **Impacto**: si se expone directamente, un sitio de terceros puede lanzar
  peticiones contra ella (el navegador manda cookies/credenciales del usuario
  si los hubiera; y sin cookies, las rutas GET de coste/bitácora son
  navegables por enlace).
- **En la réplica**: cookie de sesión `SameSite=Lax` + validación de
  `Origin`/`Referer` en todas las mutaciones (POST/PUT/DELETE) + login con
  rate-limit (ver `seguridad.py`).

### H7 — BAJO: herramientas MCP pre-autorizadas del asistente

- **Dónde**: `pasos/mcp_estudio.py` + `asistente.vetos_de_lectura` — el chat
  del asistente corre el CLI con herramientas del estudio (cancelar trabajos,
  probar claves, leer estado) ya autorizadas, y con Read/Grep/Glob sobre la
  carpeta del código, vetando `secretos/`.
- **Impacto**: el veto de `secretos/` es una regla de permisos del CLI; un
  cambio de formato o un bug del CLI lo dejaría sin efecto. El asistente puede
  cancelar trabajos sin confirmación (nocivo, no destructivo más allá del
  trabajo en curso).
- **En la réplica**: no se incluye asistente con acceso al sistema de
  ficheros. (Funcionalidad fuera del alcance pedido.)

### H8 — BAJO: ficheros servidos con recorrido controlado (correcto, se conserva)

- **Dónde**: `ruta_segura()` (`app.py:673`) y `ruta_contenida()`
  (`nucleo/proyecto.py:343`): unen rutas, resuelven con `realpath`, comparan
  prefijo, rechazan byte nulo. Sin hallazgos — patrón **correcto** que la
  réplica replica tal cual.
- Las llamadas a ffmpeg/ffprobe/Edge del resto del repo van con **listas de
  argumentos** (sin shell): patrón correcto, se conserva.

## Tabla resumen

| # | Severidad | Hallazgo | Réplica |
|---|---|---|---|
| H1 | CRÍTICO* | API sin autenticación (delegada en proxy) | Auth integrada: sesión + scrypt + rate-limit |
| H2 | ALTO | `shell=True` con feedback de usuario | Cero `shell=True`, prompts por HTTPS |
| H3 | ALTO | Agente con `acceptEdits` escribe ficheros | Modelos solo devuelven texto |
| H4 | MEDIO | Claves en claro (`0600` + volumen dedicado) | Igual + enmascarado total en API |
| H5 | MEDIO | `file://` sobre contenido no confiado | Escape + recursos embebidos locales |
| H6 | MEDIO | Sin CSRF propio | SameSite + chequeo de Origin |
| H7 | BAJO | MCP pre-autorizado | Fuera de alcance en la réplica |
| H8 | OK | Contención de rutas correcta | Se replica el patrón |

\* En el diseño original (con su frontal nginx+login) el riesgo es
configuración, no código. Sube a crítico en el despliegue que pide el usuario
(Coolify, contenedor expuesto) si no se añade auth — por eso la réplica la
integra.

## Prácticas del original que la réplica conserva

- scrypt (32 MiB) con `timingSafeEqual` para contraseñas — el mismo algoritmo
  y parámetros que `despliegue/login/lib/auth.js`.
- Instrucciones grandes al LLM **por stdin**, nunca en argv (evita límites y
  fuga en la lista de procesos) — en la réplica, ni siquiera hay proceso local.
- Timeouts finitos que matan el árbol de procesos (nunca un trabajo colgado).
- Claves: la UI solo ve etiqueta + últimos 4 caracteres + estado.
- Rate-limit en el login; contraseña mínima de 12 caracteres.
- `realpath` + prefijo para servir y escribir ficheros bajo el proyecto.
- Fuera de git todo lo sensible (`.gitignore`): `secretos/`, `proyectos/`.
