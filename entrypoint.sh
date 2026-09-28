#!/bin/sh
# Coolify (y otros orquestadores) montan el almacenamiento persistente
# con propietario root: ese montaje tapa el chown hecho en build.
# Arrancamos como root solo lo justo para ceder /datos a la app y
# bajamos privilegios antes de lanzar el servicio.
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /datos
  chown -R estudio:estudio /datos
  exec gosu estudio:estudio "$@"
fi

exec "$@"
