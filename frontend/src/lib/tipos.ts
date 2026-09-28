/** Tipos que viajan por la API (espejo del backend). */

export type EstadoPaso = "vacio" | "ok" | "obsoleto"

export type IdPaso =
  | "ingesta"
  | "brief"
  | "guion"
  | "voz"
  | "revision_audio"
  | "assets"
  | "callouts"
  | "render"

export interface FichaProyecto {
  id: string
  nombre: string
  canal: string
  idioma: string
  creado: string
  actualizado: string
  pasos: Record<string, { estado: EstadoPaso; version: number }>
  coste: number
  activo: TrabajoFicha | null
}

export interface DefinicionPaso {
  id: string
  padres: string[]
  params: Record<string, unknown>
}

export interface FichaPasos {
  grafo: DefinicionPaso[]
  pasos: Record<
    string,
    {
      estado: EstadoPaso
      version: number
      params: Record<string, unknown>
      unidades_obsoletas: string[]
      aprobado?: boolean
    }
  >
}

/** Manifiesto de una versión guardada (GET /{pid}/pasos/{paso}/versiones). */
export interface VersionPaso {
  version: number
  fecha: string
  firma: string
  params: Record<string, unknown>
  unidades: string[]
  resumen: string
}

export interface FichaPaso {
  paso: string
  estado: EstadoPaso
  version: number
  params: Record<string, unknown>
  unidades_obsoletas: string[]
  aprobado?: boolean
  datos: any
}

/* ---------- datos por paso (contenido de datos.json) ---------- */

export interface DatosIngesta {
  texto: string
  titulo: string
}

export interface DatosBrief {
  puntos: string[]
  tono?: string
  formato?: { min: number; max: number }
}

export interface DatosGuion {
  escenas: Escena[]
  duracion_estimada: number
}

export interface DatosVoz {
  escenas: (Escena & { audio: string; duracion: number })[]
  duracion: number
}

export interface Aviso {
  id: string
  problemas: string[]
}

export interface DatosRevision {
  estado: "ok" | "avisos"
  avisos: Aviso[]
  revisadas: number
}

export interface Plano {
  escena: string
  imagen: string
  prompt: string
}

export interface DatosAssets {
  planos: Plano[]
  calidad: string
}

export interface Rotulo {
  id: string
  texto: string
  aparece: number
  dura: number
}

export interface DatosCallouts {
  rotulos: Rotulo[]
}

export interface DatosRender {
  video: string
  duracion: number
  fps: number
  resolucion: string
  escenas: number
  masterizado: boolean
}

/* ---------- trabajos ---------- */

export interface TrabajoEvento {
  t: string
  mensaje: string
}

/**
 * La ficha corta (listados y SSE `estado`) trae `eventos` como NÚMERO
 * (cantidad). La ficha completa (GET /api/trabajos/{tid} y SSE `fin`)
 * añade `lineas` (últimos 100 eventos) y `resultado`.
 */
export interface TrabajoFicha {
  id: string
  proyecto: string
  paso: string
  estado: "en_cola" | "ejecutando" | "hecho" | "fallo" | "cancelado"
  unidades: string[]
  creado: string
  empezado: string | null
  terminado: string | null
  error: string | null
  eventos: number
  lineas?: TrabajoEvento[]
  resultado?: unknown
}

/* ---------- coste y bitácora ---------- */

export interface CosteTotal {
  operaciones: number
  coste: number
  por_operacion: Record<string, number>
  por_proveedor: Record<string, number>
}

export interface EntradaBitacora {
  t: string
  evento: string
  [detalle: string]: unknown
}

/* ---------- auth y configuración ---------- */

export interface EstadoAuth {
  instalacion: boolean
  sin_login: boolean
  usuario: string | null
  autenticado: boolean
}

export interface ClaveEstado {
  clave: string
  etiqueta: string
  uso: string
  variable: string
  presente: boolean
  mascara: string
}

/** Voces de ElevenLabs (GET /api/voces). */
export interface Voz {
  voice_id: string
  nombre: string
  idiomas?: string[]
  etiquetas?: Record<string, unknown>
}

export interface CatalogoProveedores {
  proveedores: Record<
    string,
    { nombre: string; esquema: string; modelos: string[]; defecto: string }
  >
  roles_defecto: Record<string, { proveedor: string; modelo: string }>
}

/** Estilo del canal (GET/PUT /api/estilo): lo que se decide UNA vez. */
export interface EstiloCanal {
  definido: boolean
  nombre: string
  idioma: "es" | "en"
  estilo_grafico: string
  tono: string
  ritmo_min: number
  ritmo_max: number
  voz: string
  velocidad: number
  actualizado: string
}

export interface Escena {
  id: string
  titulo?: string
  narracion: string
  visual?: string
  texto_pantalla?: string
  duracion_estimada?: number
  audio?: string
  duracion?: number
  palabras?: { palabra: string; inicio: number; fin: number }[]
}

export const NOMBRES_PASOS: Record<string, string> = {
  ingesta: "Material",
  brief: "Brief",
  guion: "Guion",
  voz: "Voz",
  revision_audio: "Revisión de audio",
  assets: "Imágenes",
  callouts: "Rótulos",
  render: "Vídeo",
}

export const ORDEN_PASOS: IdPaso[] = [
  "ingesta",
  "brief",
  "guion",
  "voz",
  "revision_audio",
  "assets",
  "callouts",
  "render",
]
