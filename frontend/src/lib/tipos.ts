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
  /** presupuesto de palabras que se le pidió al guion (modo duración) */
  horquilla?: {
    objetivo: number
    min: number
    max: number
    palabras: number
  }
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
  /** sub-id del plano (S012-1); igual a `escena` si la escena sale en un solo plano */
  id?: string
  escena: string
  imagen: string
  prompt: string
  /** ventana del plano DENTRO del audio de su escena */
  t_in?: number
  t_out?: number
  duracion?: number
  /** texto que narra este plano (el trozo de la escena) */
  narracion?: string
  zoom?: { de: number; a: number }
  transicion?: string
  cartela?: { plantilla: string; datos: Record<string, string>; por_que?: string } | null
}

export interface DatosAssets {
  planos: Plano[]
  calidad: string
  cartelas?: number
  /** informe del ritmo de montaje (horquilla, cortes, heredados...) */
  informe?: Record<string, unknown>
  /** horquilla de plano con la que se cortó ({minimo, maximo} en s) */
  ritmo?: { minimo: number; maximo: number }
}

/** Un trozo de subtítulo: lo que se dice entre dos marcas de palabra. */
export interface Trozo {
  texto: string
  /** segundos, en el reloj del plano */
  desde: number
  hasta: number
}

/** Los subtítulos de UN plano (la fila de p7, por id de plano). */
export interface FilaSubtitulo {
  id: string
  escena: string
  trozos: Trozo[]
}

export interface DatosCallouts {
  subtitulos: FilaSubtitulo[]
  diseno?: string
  paleta?: Paleta
  subtitulo_tam?: string
  /** caracteres por línea con los que se troceó (según el tamaño) */
  cap_linea?: number
}

export interface DatosRender {
  video: string
  duracion: number
  fps: number
  resolucion: string
  escenas: number
  masterizado: boolean
  sonido?: string
  transiciones?: string
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

/** Un plano de la previsualización (GET /{pid}/previsualizacion) — una
 * escena son ahora varios planos, cada uno con su ventana de audio. */
export interface EscenaPrevia {
  id: string
  /** la escena de la que sale el plano (y cuyo audio suena) */
  escena: string
  titulo: string
  narracion: string
  imagen: string | null
  cartela: string | null
  audio: string | null
  /** la ventana del plano DENTRO del audio de su escena */
  t_in: number
  t_out: number
  duracion: number
  palabras: { palabra: string; inicio: number; fin: number }[]
  /** los trozos de subtítulo de ESTE plano, en su reloj (t_in restado) */
  trozos: Trozo[] | null
}

/** Las piezas para ver el vídeo sin montarlo (quien las junta es el navegador). */
export interface Previsualizacion {
  escenas: EscenaPrevia[]
  duracion: number
  resolucion: string
  con_subtitulos: boolean
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

/** Una voz del catálogo ElevenLabs de la cuenta (GET /api/voces). */
export interface VozCatalogo {
  voice_id: string
  nombre: string
  etiquetas: Record<string, unknown>
  idiomas: string[]
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

/** Una cartela decidida: plantilla + sus campos (los de lista, en array). */
export interface FichaCartela {
  plantilla: string
  datos: Record<string, string | string[]>
  por_que?: string
}

export interface PropuestaCartelas {
  plan: Record<string, FichaCartela>
  avisos: string[]
  planos: number
  cartelas: number
  max_cartelas: number
}

/** Un hueco de la plantilla: si es obligatorio y cuántos caracteres caben. */
export interface CampoCartela {
  obligatorio: boolean
  tope: number
}

/** Ficha de plantilla de cartela, con su muestra dibujada por el servidor. */
export interface PlantillaCartela {
  id: string
  nombre: string
  descripcion: string
  /** lo que lee el agente (y la persona) para decidir si es la suya */
  cuando: string
  campos: Record<string, CampoCartela>
  /** (campo, mínimo, máximo) cuando un campo es una lista de líneas */
  lista?: [string, number, number] | null
  svg: string
}

/** Respuesta de GET /{pid}/cartelas. */
export interface FichaCartelas {
  plan: Record<string, FichaCartela>
  plantillas: PlantillaCartela[]
  /** qué plantillas puede usar el agente al proponer (vacío = todas) */
  plantillas_activas: string[]
  /** el catálogo CERRADO de iconos que puede llevar una plantilla */
  iconos: string[]
  defecto: string
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

/** Ajustes del servidor (GET /api/ajustes): modelos por rol y la marca
 * de la guía de inicio (ausente = aún sin ver). */
export interface Ajustes {
  llm?: Record<string, { proveedor: string; modelo: string }>
  onboarding_visto?: boolean
}

export interface ClaveEstado {
  clave: string
  etiqueta: string
  uso: string
  variable: string
  presente: boolean
  mascara: string
}

/** Sesión OAuth de Codex (GET /api/codex): no es una clave pegable. */
export interface CodexEstado {
  conectado: boolean
  correo: string
  expira: number
  pendiente: boolean
}

/** Flujo de dispositivo recién arrancado (POST /api/codex/conectar). */
export interface CodexFlujo {
  user_code: string
  verification_uri: string
  verification_uri_complete: string
  expira_s: number
  intervalo_s: number
}

/** Una vuelta de polling del flujo (POST /api/codex/sondeo). */
export type CodexSondeo =
  | { estado: "sin_flujo" | "pendiente" }
  | { estado: "conectado"; correo: string }
  | { estado: "expirado" | "rechazado" }

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
  /** nombres de las imágenes del kit visual, en orden */
  kit: string[]
}

/* ---------- repaso, capturas y montaje (Fase D) ---------- */

/** Una nota del repaso, anclada al segundo (GET/POST /{pid}/repaso). */
export interface NotaRepaso {
  id: string
  t: number
  plano: string
  texto: string
  imagenes: string[]
  fecha: string
  estado: "pendiente" | "aplicado"
  ancla?: string
  regenerado?: string
  reanclada?: string | boolean
  descolgada?: boolean
  aplicada?: string
}

/** Corte de escena del vídeo montado (contra lo que se anclan las notas). */
export interface CorteRepaso {
  id: string
  t_in: number
  t_out: number
  narracion: string
}

/** El vocabulario del enrutador: ámbitos y cambios con su coste. */
export interface CatalogoRepaso {
  ambitos: Record<string, { que_es: string; cuesta: string }>
  cambios: Record<
    string,
    { ambito: string; que_es: string; rehacer: string[]; campos: string[]; destino: string[] }
  >
}

/** Ficha completa del repaso (GET /{pid}/repaso). */
export interface FichaRepaso {
  notas: NotaRepaso[]
  pendientes: number
  cortes: CorteRepaso[]
  duracion: number
  montado: boolean
  video: string | null
  version_video?: number | null
  catalogo: CatalogoRepaso
  pipeline: string
  activo: TrabajoFicha | null
}

/** Nota ya repartida por el enrutador (respuesta del trabajo «repaso»). */
export interface NotaEnrutada {
  id: string
  texto: string
  entendido: string
  ambito: string
  cambios: { tipo: string; ambito: string; plano?: string; texto?: string; valor?: unknown }[]
}

/** Un cambio validado del vocabulario cerrado. */
export interface CambioRepaso {
  tipo: string
  ambito: string
  plano?: string
  texto?: string
  valor?: string | number
  alcance?: string
  campos_cartela?: Record<string, string>
  rehacer: string[]
}

/** Una captura anotada del reproductor (GET/POST /{pid}/capturas). */
export interface FichaCaptura {
  id: string
  paso: "callouts" | "render"
  escena: string
  unidad: string
  t_video: number | null
  t_escena: number | null
  imagen: string
  url?: string
  trazos: { color: string; grosor: number; puntos: { x: number; y: number }[] }[]
  comentario: string
  creada: string
  aplicada: string | null
  trabajo: string | null
  bytes: number
  contexto?: Record<string, unknown>
}

/** Notas libres del montaje (GET/PUT /{pid}/montaje/notas). */
export interface NotasMontaje {
  texto: string
  actualizado?: string
}

/* ---------- catálogo, encuadres, guía, moodboard, conservación (Fase F) ---------- */

/** Una entrada del reparto: la descripción física que viaja al generador. */
export interface PersonajeCatalogo {
  nombre: string
  papel: string
  descripcion: string
  palabras: string[]
  grupo: boolean
}

/** Un set: un LUGAR, no un plano. */
export interface SetCatalogo {
  rotulo: string
  descripcion: string
  palabras: string[]
  luz: string
}

/** Un tramo de escenas que comparten sitio, reparto y tono. */
export interface BeatCatalogo {
  desde: string
  hasta: string
  set: string | null
  personajes: string[]
  tono: string
  accion: string
}

/** El catálogo visual del vídeo (params.assets.catalogo). */
export interface CatalogoVisual {
  reparto: Record<string, PersonajeCatalogo>
  sets: Record<string, SetCatalogo>
  beats: BeatCatalogo[]
  capitulos: Record<string, { titulo: string; subtitulo: string }>
  lugares: Record<string, string>
  avisos: string[]
  cobertura?: number
}

/** Respuesta de GET /{pid}/catalogo. */
export interface FichaCatalogo {
  catalogo: CatalogoVisual
  planos: PlanoGrafismo[]
  obsoletos: string[]
}

/** Propuesta del agente de catálogo (POST /{pid}/catalogo/proponer). */
export interface PropuestaCatalogo {
  catalogo: CatalogoVisual
  personajes: number
  sets: number
  beats: number
  avisos: string[]
}

/** Una clase de plano de la escalera. */
export interface CartaEncuadre {
  id: string
  nombre: string
  familia: string
  peso: number
  abstracta: boolean
}

/** Respuesta de GET /{pid}/encuadres. */
export interface FichaEncuadres {
  catalogo: CartaEncuadre[]
  reparto: Record<string, string>
  forzadas: Record<string, string>
  planos: PlanoGrafismo[]
  obsoletos: string[]
}

/** La guía de estilo escrita, con números (params.assets.guia). */
export interface FichaGuia {
  guia: string
  paleta: string[]
  trazo: string
  relleno: string
  personajes: string
  caras: string
  manos: string
  fondos: string
  luz: string
  composicion: string
  acabado: string
  evitar: string
  resumen_es: string
  descripcion?: string
  peticion?: string
}

/** Respuesta de GET /{pid}/guia. */
export interface FichaGuiaPantalla {
  guia: Partial<FichaGuia>
  estilo: string
  moodboard: { clave: string; estado: string }
  obsoletos: string[]
  aportadas: string[]
}

/** Propuesta del agente de guía (POST /{pid}/guia/proponer). */
export interface PropuestaGuia {
  guia: FichaGuia
  palabras: number
  colores: number
}

/** Un eje del moodboard y su lámina. */
export interface EjeMoodboard {
  eje: string
  titulo: string
  hay: boolean
  pendiente: boolean
  version: number
}

/** Respuesta de GET /{pid}/moodboard. */
export interface FichaMoodboard {
  posible: boolean
  por_que_no?: string
  clave?: string
  ejes: EjeMoodboard[]
  estado?: string
  coste_usd?: number
  pendientes?: string[]
}

/** El reparto de conservación (resultado del trabajo «conservacion»). */
export interface PlanConservacion {
  posible: boolean
  por_que_no?: string
  conservar: string[]
  rehacer: string[]
  motivos: Record<string, string>
  regrabar_voz: string[]
  resumen: string
  escenas?: Record<string, { estado: string; parecido: number; solape: number }>
}

/** Respuesta de POST /{pid}/conservacion/aplicar. */
export interface ResultadoConservacion {
  tocados: Record<string, string[]>
  conservados: number
  rehacer: number
  regrabar: number
  obsoletos_assets: string[]
  obsoletos_voz: string[]
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

/* ---------- presets: locución, canal y modo light (Fase H) ---------- */

/** Un tono de locución del catálogo (GET /api/presets). */
export interface PresetVoz {
  id: string
  nombre: string
  descripcion: string
  voces_sugeridas: string[]
  voces_nombres: string[]
  modelo: string
  estabilidad: number
  similitud: number
  velocidad: number
  hueco_minimo?: number
}

export type TipoPreset = "guion" | "estilo" | "rotulos" | "voz" | "canal"

/** Un preset guardado, tal como lo publica la API (con resumen y viñetas). */
export interface PresetCanal {
  id: string
  tipo: TipoPreset
  tipo_nombre: string
  nombre: string
  nota: string
  fecha: string
  modificado?: string
  miniatura?: string
  hay_miniatura?: boolean
  resumen: string
  vinetas: { icono: string; texto: string }[]
  idioma: string
  origen_ritmo: string
  apartado?: string
  datos: Record<string, any>
}

/** Respuesta de GET /api/presets-canal. */
export interface FichaPresetsCanal {
  presets: Record<TipoPreset, PresetCanal[]>
  papelera: PresetCanal[]
  tipos: { id: TipoPreset; nombre: string }[]
  total: number
}

/** Respuesta de POST /{prid}/aplicar: lo que tocó y lo que restauró. */
export interface ResultadoAplicar {
  preset: PresetCanal
  cambios: Record<string, Record<string, unknown>>
  /** Las láminas devueltas al banco de moodboards (clave + ejes). */
  lamina_devueltas?: { clave: string; ejes: string[] }
  /** Pasos cuyas unidades quedaron obsoletas tras el cambio de params. */
  obsoletos?: Record<string, unknown>
}

/** Peso de un preset apartado (GET /{prid}/peso). */
export interface PesoPreset {
  id: string
  nombre: string
  ficheros: number
  bytes: number
  [detalle: string]: unknown
}

/** Un ritmo del modo light, con sus dos cifras y su coste. */
export interface RitmoLight {
  id: string
  nombre: string
  ritmo_min: number
  ritmo_max: number
  media_s: number
  velocidad: number
  usd_por_minuto: number
}

/** Los cuatro campos (más idioma y ritmo): TODO el formulario del modo. */
export interface EncargoLight {
  nombre: string
  estilo_prompt: string
  /** nombres de imágenes de referencia ya subidas al buzón del servidor */
  estilo_imagenes?: string[]
  tono_prompt: string
  voz_prompt: string
  idioma: string
  ritmo: string
  voz_id?: string
}

/** Una imagen de referencia aceptada por el buzón (tras subirla). */
export interface ImagenAportada {
  nombre: string
  origen?: string
  bytes?: number
}

/** Respuesta de POST /api/presets-light/imagenes. */
export interface RespuestaAportadas {
  imagenes: ImagenAportada[]
  avisos: string[]
  tope: number
}

/** Una tarea del plan (lo que hará el taller, en una línea). */
export interface TareaLight {
  id: string
  nombre: string
  descripcion?: string
  tanda?: number
  [detalle: string]: unknown
}

/** Respuesta de POST /api/presets-light/plan. */
export interface PlanLight {
  tandas: TareaLight[][]
  segundos: number
  imagenes: number
  tareas: TareaLight[]
}

/** Respuesta de GET /api/presets-light (la pantalla entera). */
export interface FichaPresetsLight {
  ritmos: RitmoLight[]
  ritmo_defecto: string
  idiomas: { id: string; nombre: string }[]
  plan: PlanLight
  max_imagenes_estilo: number
  presets: PresetCanal[]
  papelera: PresetCanal[]
  hay_glm: boolean
  hay_elevenlabs: boolean
}

/** Respuesta de GET /api/presets-light/{prid}. */
export interface FichaPresetLight {
  preset: PresetCanal
  encargo: Record<string, string>
  /** imágenes de referencia sembradas en el taller (sus nombres) */
  estilo_imagenes: string[]
  max_imagenes_estilo: number
  muestras: string[]
  taller: string
  activo: TrabajoFicha | null
}

/** Respuesta de POST /{prid}/escucha: doce segundos con la voz del canal. */
export interface EscuchaLight extends PrevisualizacionVoz {}

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
  repaso: "Repaso",
  capturas: "Capturas",
  catalogo: "Catálogo",
  guia: "Guía de estilo",
  moodboard: "Moodboard",
  conservacion: "Conservación",
  banda: "Banda sonora",
  efectos: "Efectos",
  transiciones: "Transiciones",
  taller: "Taller",
}

/* ------------------------------------------ Fase G: sonido y transiciones */

/** Un tema de Jamendo tal como llega de la búsqueda (escucha = para oírlo). */
export interface TemaMusica {
  fuente: string
  id: string
  titulo: string
  artista: string
  duracion: number
  descarga: string
  escucha: string
  licencia: string
  etiquetas?: string[]
  instrumentos?: string[]
  vocal?: string
  velocidad?: string
}

/** Un tramo del vídeo y el ánimo que le pediría a la música. */
export interface TramoArco {
  i: number
  desde: number
  hasta: number
  animo: string
  velocidad?: string
  densidad?: number
  planos?: number
  fraccion?: number
  por_que?: string
}

/** Respuesta de GET /{pid}/sonido/arco. */
export interface ArcoSonido {
  duracion: number
  tramos: TramoArco[]
}

/** La música puesta: un tema único o la banda por tramos. */
export interface MusicaPuesta {
  id?: string
  titulo?: string
  artista?: string
  licencia?: string
  duracion?: number
  modo?: string
  ganancia_db?: number
  cruce_s?: number
  tramos?: (TemaMusica & { animo?: string })[]
}

/** Un efecto surtido, con su muestra del banco para oírlo. */
export interface EfectoSurtido {
  fuente: string
  id: string
  titulo: string
  autor: string
  duracion: number
  licencia: string
  etiquetas?: string[]
  brillo?: number
  dureza?: number
  reverb?: number
  error?: string
  papel: string
  clave: string
  en_banco: boolean
  muestra: string
  vetado: boolean
  agudo?: number
}

/** Lo que suena y hay que firmar en los créditos. */
export interface CreditoMusica {
  titulo: string
  artista: string
  fuente: string
  licencia: string
}

/** Respuesta de GET /{pid}/sonido. */
export interface FichaSonido {
  activo: boolean
  musica: MusicaPuesta
  lufs: number
  musica_db: number
  efectos_db: number
  efectos: EfectoSurtido[]
  papeles: Record<string, { nombre: string; descripcion: string; cuantos: number }>
  vetados: { clave: string; titulo: string; autor: string; papel: string; fecha: string }[]
  animos: Record<string, string>
  hay_jamendo: boolean
  hay_freesound: boolean
  resumen: string
  creditos: CreditoMusica[]
}

/** Una carta del catálogo de transiciones (xfade = lo que corre el render). */
export interface CartaTransicion {
  id: string
  puesta: boolean
  nombre: string
  descripcion: string
  familia: string
  fuerza: number
  factor: number
  xfade: string
  defecto: boolean
  origen: string
}

/** Qué transición lleva cada plano, resuelta por el motor. */
export interface RepartoTransicion {
  id: string
  t_in: number
  tipo: string
  xfade: string | null
  duracion: number
  ranura: string
}

/** Respuesta de GET /{pid}/transiciones. */
export interface FichaTransiciones {
  transiciones: CartaTransicion[]
  por_defecto: string[]
  acento_cada: number
  duracion: number
  todas_de_fabrica: boolean
  acento: { acento: number[]; oscuro: number[]; claro: number[] }
  reparto: RepartoTransicion[]
  resumen: string
}

/** Turno de una charla con el asistente (tu pregunta o su respuesta). */
export interface TurnoAsistente {
  n: number
  quien: "tu" | "asistente"
  texto: string
  estado?: "pensando" | "listo" | "error" | "cancelado"
  fecha?: string
  segundos?: number
  tokens?: number
}

/** Respuesta de GET/POST /api/asistente/charlas/{cid}. */
export interface CharlaAsistente {
  id: string
  proyecto: string
  turnos: TurnoAsistente[]
  ocupada: boolean
  modelo: string
}

/** Respuesta de GET /api/asistente: si puede contestar y con qué cuenta. */
export interface EstadoAsistente {
  listo: boolean
  motivo: string
  cuenta: string
  modelo: string
  simulado: boolean
  claves: { clave: string; presente: boolean }[]
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
