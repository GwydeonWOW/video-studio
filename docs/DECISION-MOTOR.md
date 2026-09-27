# Decisión de stack del motor: ¿Rust?

**Decisión: NO portar el motor a Rust. El motor se mantiene en Python (FastAPI),
y las piezas pesadas siguen siendo código nativo que ya existe (ffmpeg y Chromium).**

Fecha del análisis: 2026-09-27 · Analizado sobre as-video-studio original (91 K líneas).

## Qué es "el motor" aquí

El sistema tiene cuatro clases de trabajo:

| Trabajo | Quién lo ejecuta | Naturaleza |
|---|---|---|
| Orquestación del grafo (8 fases, hashes, invalidación, trabajos) | Python | I/O + JSON |
| LLM (guion, catálogo, rótulos) | Red (API del proveedor) | Espera de 30–300 s por llamada |
| Voz (TTS) e imágenes | Red (API del proveedor) | Espera de segundos-minutos por unidad |
| Render y rasterizado | **ffmpeg (C) y Chromium (C++)** vía subprocess | CPU nativa |

El código Python es pegamento: construye prompts, parsea JSON, escribe manifiestos
y espera a procesos y HTTP. No hay bucles numéricos intensivos propios — el
movimiento de cámara del original es `numpy` vectorizado y el resto del cálculo
de fotogramas lo hace el navegador al rasterizar.

## Los cinco motivos de la decisión

1. **El cuello de botella no es la CPU del proceso.** El tiempo de un vídeo se va
   en esperar al LLM, esperar a las imágenes (por política, **de una en una**,
   porque cuestan dinero), esperar a ElevenLabs y esperar a ffmpeg/Chromium.
   Reescribir el pegamento no acelera ninguna de esas esperas.

2. **El GIL no es el límite.** Los trabajos pesados ya son procesos aparte
   (ffmpeg, Chromium) o llamadas de red. La cola de trabajos con hilos/asyncio
   cubre la concurrencia real del producto (una tanda de imágenes, un render,
   un paso de guion a la vez por proyecto).

3. **El producto itera a diario sobre prompts y reglas.** El original lleva el
   histórico a cara de pergamino (docstrings con fechas y medidas). Ese tipo de
   sintonía fina —cambiar una frase de un prompt y volver a probar— es el flujo
   de trabajo natural de Python y el peor de un compile-link-run de Rust.

4. **Riesgo de rewrite.** 91 K líneas con comportamientos calibrados y
   documentados como "no toques esto sin medir". Un port pierde todo ese
   conocimiento operativo a cambio de… nada medible en throughput.

5. **Donde Rust ayudaría, ya hay código nativo.** ¿Frame math? La hace
   Chromium/ffmpeg. ¿Hashing de ficheros? Marginal (I/O de disco). ¿Muxing?
   ffmpeg. No queda ninguna parte del sistema donde Rust aporte ganancia real.

## Cuándo sí tendría sentido Rust (y no es este caso)

- Si el render fuera software propio (compositor de fotogramas en el propio
  proceso) con cientos de hilos — aquí se delega en ffmpeg + navegador.
- Si el servicio atendiera miles de usuarios concurrentes — es una herramienta
  de un equipo pequeño con cola de trabajos.
- Si hubiera parsing binario/audio en tiempo real — no lo hay.

## Conclusión aplicada a la réplica

- Backend en **Python 3.12 + FastAPI + uvicorn**, igual que el original:
  misma clase de sistema, misma operación, mismo perfil de carga.
- HTTP saliente con `requests` en los workers (igual que el original: sin
  dependencias async extra).
- Render: ffmpeg + Chromium headless por subprocess (listas de argumentos,
  jamás `shell=True` — ver AUDITORIA.md).
- Frontend separado en React + shadcn/ui (decisión aparte, pedido del usuario),
  servido estático por el propio backend.
