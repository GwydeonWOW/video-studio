/** Foto de lo que la persona tiene delante, para el asistente.

 * La vista de Proyecto la apunta al cambiar de pestaña; el asistente la
 * lee al preguntar. Vive fuera de React porque el cajón está montado en
 * la shell y la pestaña abierta vive en la vista.
 */
export interface FotoPantalla {
  pestana: string
  url: string
  errores: Record<string, string>
}

let foto: FotoPantalla = { pestana: "", url: "", errores: {} }

/** La vista apunta qué tiene delante ahora (pestana, url, errores). */
export function apuntarPantalla(parcial: Partial<FotoPantalla>) {
  foto = { ...foto, ...parcial }
}

/** Lo que se manda con cada pregunta al asistente. */
export function fotoDePantalla(): FotoPantalla {
  return { ...foto, url: foto.url || window.location.pathname }
}
