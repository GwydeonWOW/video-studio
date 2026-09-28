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
  presupuesto?: number | null
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
  cartela?: { plantilla: string; datos: Record<string, string>; por_que?: string } | null
}

export interface DatosAssets {
  planos: Plano[]
  calidad: string
  cartelas?: number
}

export interface Rotulo {
  id: string
  texto: string
  aparece: number
  dura: number
}

export interface DatosCallouts {
  rotulos: Rotulo[]
  diseno?: string
  paleta?: Paleta
  subtitulo_tam?: string
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

/** Ficha de coste de un proyecto (GET /{pid}/coste), con presupuesto. */
export interface CosteProyecto extends CosteTotal {
  presupuesto: number | null
  aviso: boolean
}

/** Reparto de consumos por paso (GET /{pid}/coste/por-paso). */
export interface CostePorPaso {
  [paso: string]: { operaciones: number; coste: number }
}

/** Un consumo anotado (GET /{pid}/coste/eventos). */
export interface EventoCoste {
  t: string
  operacion: string
  proveedor: string
  modelo: string
  coste: number
  contexto: string
  paso?: string
  unidad?: string
  [detalle: string]: unknown
}

/** Inventario de un proyecto apartado (GET /papelera/{carpeta}). */
export interface InventarioPapelera {
  carpeta: string
  id: string
  nombre: string
  ficheros: number
  peso: number
  por_carpeta: Record<string, { ficheros: number; peso: number; nombres: string[] }>
  videos: { nombre: string; peso: number }[]
}

/** Tiempos reales por paso entre todos los proyectos (GET /api/estadisticas). */
export interface Estadisticas {
  proyectos: number
  corridas: number
  por_paso: Record<string, { n: number; media_s: number; mediana_s: number; max_s: number }>
}

/* ---------- recetas y previsualización (Fase C) ---------- */

/** Tarea del tablero de receta (GET /{pid}/receta). */
export interface RecetaTarea {
  id: string
  nombre: string
  pestana: string
  paso: string
  necesita: string[]
  cuesta: boolean
  porque: string
  estado: EstadoPaso
  version: number
  aprobado?: boolean
}

/** Tablero de la receta de un proyecto (qué falta, en qué pestaña). */
export interface FichaReceta {
  pestañas: Record<string, { nombre: string; tareas: RecetaTarea[] }>
  activo: TrabajoFicha | null
}

/** Una escena de la previsualización (GET /{pid}/previsualizacion). */
export interface EscenaPrevia {
  id: string
  titulo: string
  narracion: string
  imagen: string | null
  audio: string | null
  duracion: number
  palabras: { palabra: string; inicio: number; fin: number }[]
  rotulo: { texto: string; aparece: number; dura: number } | null
}

/** Las piezas para ver el vídeo sin montarlo (quien las junta es el navegador). */
export interface Previsualizacion {
  escenas: EscenaPrevia[]
  duracion: number
  resolucion: string
  con_rotulos: boolean
  montado: boolean
  idioma: string
}

/* ---------- voz descrita y feedback (Fase B) ---------- */

/** Propuesta de voz a partir de una descripción (POST /{pid}/voz/describir). */
export interface PropuestaVoz {
  voz: string
  voz_nombre: string
  voz_etiquetas?: Record<string, unknown>
  modelo: string
  estabilidad: number
  similitud: number
  velocidad: number
  motivo: string
  catalogo?: number
}

/** Resultado de la cata de voz (POST /{pid}/voz/previsualizar). */
export interface PrevisualizacionVoz {
  archivo: string
  url: string
  segundos: number
  caracteres: number
  duracion: number
}

/** Respuesta de POST /{pid}/feedback. */
export interface RespuestaFeedback {
  paso: string
  unidad: string | null
  nota: { id: string; fecha: string; texto: string }
  afectadas: string[]
  aguas_abajo: Record<string, string[]>
  estado: EstadoPaso
  trabajo?: TrabajoFicha
}

/* ---------- grafismo por plano (Fase E) ---------- */

/** Un plano resumido para los diálogos de grafismo (GET /{pid}/direccion). */
export interface PlanoGrafismo {
  id: string
  titulo: string
  narracion: string
}

export interface RespuestaPlan<T> {
  plan: Record<string, T>
  planos?: PlanoGrafismo[]
  obsoletos?: string[]
  tocados?: string[]
  avisos?: string[]
}

/** Propuesta del agente de dirección (POST /{pid}/direccion/proponer). */
export interface PropuestaDireccion extends RespuestaPlan<string> {
  dirigidos: number
}

/** Propuesta del redactor de prompts (POST /{pid}/redactor/proponer). */
export interface PropuestaRedactor extends RespuestaPlan<string> {
  redactados: number
}

/** Una cartela decidida: plantilla + sus campos. */
export interface FichaCartela {
  plantilla: string
  datos: Record<string, string>
  por_que?: string
}

export interface PropuestaCartelas {
  plan: Record<string, FichaCartela>
  avisos: string[]
  planos: number
  cartelas: number
  max_cartelas: number
}

/** Ficha de plantilla de cartela (campos y ejemplo). */
export interface PlantillaCartela {
  nombre: string
  descripcion: string
  campos: string[]
  muestra: Record<string, string>
}

/** Respuesta de GET /{pid}/cartelas. */
export interface FichaCartelas {
  plan: Record<string, FichaCartela>
  plantillas: Record<string, PlantillaCartela>
  planos: PlanoGrafismo[]
  max_cartelas: number
  obsoletos: string[]
}

export interface Paleta {
  acento: string
  texto: string
  fondo: string
  velo: string
}

/** Set de diseño de rótulo. */
export interface SetDiseno {
  nombre: string
  descripcion: string
  caja: string
}

/** Respuesta de GET /{pid}/callouts/diseno. */
export interface FichaDiseno {
  sets: Record<string, SetDiseno>
  elegido: string
  sugerido: string
  paleta: Paleta
  fijados: Partial<Paleta>
  tamanos: Record<string, number>
  subtitulo_tam: string
  obsoleto: boolean
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
  receta: "Receta",
  tanda: "Tanda",
  direccion: "Dirección",
  redactor: "Redactor",
  cartelas: "Cartelas",
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
