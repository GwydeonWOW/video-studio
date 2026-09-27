/** Cliente HTTP de la API: fetch con errores tipados {error: mensaje}. */

export class ErrorApi extends Error {
  estado: number
  constructor(mensaje: string, estado: number) {
    super(mensaje)
    this.estado = estado
  }
}

async function pedir(ruta: string, opciones: RequestInit = {}): Promise<Response> {
  const respuesta = await fetch(ruta, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...opciones.headers },
    ...opciones,
  })
  if (!respuesta.ok) {
    let mensaje = `error ${respuesta.status}`
    try {
      const cuerpo = await respuesta.json()
      if (cuerpo?.error) mensaje = cuerpo.error
    } catch {
      /* cuerpo no JSON */
    }
    throw new ErrorApi(mensaje, respuesta.status)
  }
  return respuesta
}

export async function json<T>(ruta: string, opciones?: RequestInit): Promise<T> {
  const r = await pedir(ruta, opciones)
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T)
}

export const api = {
  get: <T,>(ruta: string) => json<T>(ruta),
  post: <T,>(ruta: string, cuerpo?: unknown) =>
    json<T>(ruta, { method: "POST", body: JSON.stringify(cuerpo ?? {}) }),
  put: <T,>(ruta: string, cuerpo: unknown) =>
    json<T>(ruta, { method: "PUT", body: JSON.stringify(cuerpo) }),
  borrar: (ruta: string) => json<void>(ruta, { method: "DELETE" }),
}
