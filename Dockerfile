# ---------------------------------------------------------- etapa 1: web
# Construye la interfaz (React + Vite) con Node.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# -------------------------------------------------------- etapa 2: servicio
# Imagen final: Python + ffmpeg + fuentes, sin herramientas de build.
FROM python:3.12-slim

# ffmpeg para audio/vídeo, DejaVu para los rótulos (drawtext/PIL) y
# ca-certificates para las llamadas HTTPS a los proveedores.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: la API nunca necesita root.
RUN useradd --system --create-home --shell /usr/sbin/nologin estudio

WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=web /web/dist ./web

# Todo el estado vive en /datos (montar un volumen) y la web ya está
# construida dentro de la imagen.
ENV ESTUDIO_DATOS=/datos \
    ESTUDIO_WEB=/srv/web \
    ESTUDIO_HOST=0.0.0.0 \
    ESTUDIO_PUERTO=8000 \
    ESTUDIO_FFMPEG=ffmpeg \
    ESTUDIO_FFPROBE=ffprobe \
    PYTHONUNBUFFERED=1

RUN mkdir -p /datos && chown -R estudio:estudio /srv /datos
USER estudio

EXPOSE 8000

# /api/salud es público y no toca servicios de pago (lo monitoriza Coolify).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request as u,sys; sys.exit(0 if u.urlopen(f'http://127.0.0.1:{os.environ.get(\"ESTUDIO_PUERTO\",\"8000\")}/api/salud', timeout=4).status==200 else 1)"

# Un solo proceso: los trabajos viven en hilos dentro de la app.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
