/** Vista de un proyecto: pipeline de 8 pasos + seguimiento de trabajos. */
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { ArrowLeft, BookOpen, Camera, ChevronLeft, ChevronRight, ClipboardCopy, ClipboardList, Eye, Loader2, MessageSquareHeart, Palette, Pause, Play, Settings2, Wallet, Zap } from "lucide-react"
import { api } from "../lib/api"
import { apuntarPantalla } from "../lib/pantalla"
import { dolares, segundos } from "../lib/utils"
import {
  NOMBRES_PASOS,
  ORDEN_PASOS,
  type CostePorPaso,
  type CosteProyecto,
  type EntradaBitacora,
  type EventoCoste,
  type FichaPaso,
  type FichaPasos,
  type FichaProyecto,
  type FichaReceta,
  type IdPaso,
  type Previsualizacion,
  type RespuestaFeedback,
  type TrabajoFicha,
} from "../lib/tipos"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import { AreaTexto } from "../components/ui/textarea"
import {
  Dialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
} from "../components/ui/dialogo"
import { BarraTrabajo } from "../components/barra_trabajo"
import { DialogoCaptura } from "./proyecto/repaso"
import { EditorParams, Estimacion, PildoraEstado, ZonaVersiones } from "./proyecto/piezas"
import {
  PanelAssets,
  PanelBrief,
  PanelCallouts,
  PanelGuion,
  PanelIngesta,
  PanelRender,
  PanelRevision,
  PanelVoz,
  type PropsPanel,
} from "./proyecto/paneles"
import { PanelRepaso } from "./proyecto/repaso"
import { PanelEncargo } from "./proyecto/encargo"

/** el pipeline + el encargo + la pantalla de repaso (sobre el montado) */
type IdPantalla = IdPaso | "encargo" | "repaso"
/** las que se recorren una a una en la columna de pasos */
const PANTALLAS: IdPantalla[] = [...ORDEN_PASOS, "repaso"]

// NOMBRES_PASOS es Record<string,string>: el spread no aporta teclas
// estáticas, así que se escriben una a una para que el compilador
// eche en falta cualquier pantalla nueva sin nombre.
const NOMBRE_PANTALLA: Record<IdPantalla, string> = {
  ingesta: "Material",
  brief: "Brief",
  guion: "Guion",
  voz: "Voz",
  revision_audio: "Revisión de audio",
  assets: "Imágenes",
  callouts: "Rótulos",
  render: "Vídeo",
  repaso: "Repaso",
  encargo: "Encargo",
}

const PANELES: Record<Exclude<IdPantalla, "encargo">,
  (p: PropsPanel) => JSX.Element> = {
  ingesta: PanelIngesta,
  brief: PanelBrief,
  guion: PanelGuion,
  voz: PanelVoz,
  revision_audio: PanelRevision,
  assets: PanelAssets,
  callouts: PanelCallouts,
  render: PanelRender,
  repaso: PanelRepaso,
}

/** Las cinco paradas: el pipeline contado para móvil. Cada una cubre
 * varias pantallas; la que no se puede pisar se APAGA con su motivo,
 * no se esconde. */
const PARADAS: {
  id: string
  nombre: string
  cubre: IdPantalla[]
  destino: IdPantalla
}[] = [
  { id: "encargo", nombre: "Encargo", cubre: ["encargo", "ingesta", "brief"],
    destino: "encargo" },
  { id: "guion", nombre: "Guion",
    cubre: ["guion", "voz", "revision_audio"], destino: "guion" },
  { id: "imagenes", nombre: "Imágenes", cubre: ["assets", "callouts"],
    destino: "assets" },
  { id: "video", nombre: "Vídeo", cubre: ["render"], destino: "render" },
  { id: "repaso", nombre: "Repaso", cubre: ["repaso"], destino: "repaso" },
]

export default function Proyecto() {
  const { pid = "" } = useParams()
  const navegar = useNavigate()
  const [proyecto, setProyecto] = useState<FichaProyecto | null>(null)
  const [pasos, setPasos] = useState<FichaPasos | null>(null)
  const [paso, setPaso] = useState<IdPantalla>("ingesta")
  const [ficha, setFicha] = useState<FichaPaso | null>(null)
  const [tid, setTid] = useState<string | null>(null)
  const [estado_trabajo, setEstadoTrabajo] = useState<string | null>(null)
  const [bitacora, setBitacora] = useState<EntradaBitacora[] | null>(null)
  const [bitacora_abierta, setBitacoraAbierta] = useState(false)
  const [coste, setCoste] = useState<CosteProyecto | null>(null)
  const [coste_abierto, setCosteAbierto] = useState(false)
  const [receta_abierta, setRecetaAbierta] = useState(false)
  const [visor_abierto, setVisorAbierto] = useState(false)

  // la foto de pantalla que se lleva el asistente al preguntar
  useEffect(() => {
    apuntarPantalla({ pestana: paso, url: `/p/${pid}` })
  }, [paso, pid])

  /* ------------------------------------------------------------ cargas */

  const cargar_proyecto = useCallback(async () => {
    try {
      const p = await api.get<FichaProyecto>(`/api/proyectos/${pid}`)
      setProyecto(p)
      return p
    } catch {
      toast.error("proyecto no encontrado")
      navegar("/")
      return null
    }
  }, [pid, navegar])

  const cargar_pasos = useCallback(async () => {
    const r = await api.get<FichaPasos>(`/api/proyectos/${pid}/pasos`)
    setPasos(r)
    return r
  }, [pid])

  const cargar_ficha = useCallback(
    async (paso_id: IdPantalla, base: FichaPasos | null = null) => {
      const fuente = base ?? pasos
      const resumen = fuente?.pasos[paso_id]
      if (!resumen || resumen.estado === "vacio") {
        setFicha({
          paso: paso_id,
          estado: "vacio",
          version: resumen?.version ?? 0,
          params: resumen?.params ?? {},
          unidades_obsoletas: resumen?.unidades_obsoletas ?? [],
          aprobado: resumen?.aprobado ?? false,
          datos: null,
        })
        return
      }
      try {
        setFicha(
          await api.get<FichaPaso>(`/api/proyectos/${pid}/pasos/${paso_id}`)
        )
      } catch {
        setFicha(null)
      }
    },
    // pasos a propósito: la firma usa el último resumen conocido
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pid, pasos]
  )

  const cargar_coste = useCallback(() => {
    api
      .get<CosteProyecto>(`/api/proyectos/${pid}/coste`)
      .then(setCoste)
      .catch(() => {})
  }, [pid])

  useEffect(() => {
    setProyecto(null)
    setPasos(null)
    setFicha(null)
    setTid(null)
    ;(async () => {
      const p = await cargar_proyecto()
      if (!p) return
      if (p.activo?.id) {
        setTid(p.activo.id)
        setEstadoTrabajo(p.activo.estado)
      }
      await cargar_pasos()
    })()
    cargar_coste()
  }, [cargar_proyecto, cargar_pasos, cargar_coste])

  useEffect(() => {
    if (pasos) cargar_ficha(paso, pasos)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso, pasos])

  /* coste en vivo: mientras corre un trabajo, escuchar el flujo SSE */
  const trabajando =
    tid !== null &&
    (estado_trabajo === "en_cola" || estado_trabajo === "ejecutando")
  useEffect(() => {
    if (!trabajando) return
    const fuente = new EventSource(`/api/proyectos/${pid}/coste/flujo`)
    const al_coste = (e: MessageEvent) => {
      const d = JSON.parse(e.data) as Partial<CosteProyecto>
      setCoste((prev) => (prev ? { ...prev, ...d } : prev))
    }
    fuente.addEventListener("coste", al_coste as EventListener)
    return () => fuente.close()
  }, [trabajando, pid])

  useEffect(() => {
    if (!bitacora_abierta || bitacora) return
    api
      .get<EntradaBitacora[]>(`/api/proyectos/${pid}/bitacora?limite=200`)
      .then(setBitacora)
      .catch(() => setBitacora([]))
  }, [bitacora_abierta, bitacora, pid])

  /* ---------------------------------------------------------- acciones */

  const recargar_todo = useCallback(
    async (paso_id?: IdPantalla) => {
      await cargar_pasos()
      await cargar_ficha(paso_id ?? paso, null)
      cargar_proyecto()
    },
    [cargar_pasos, cargar_ficha, cargar_proyecto, paso]
  )

  const ejecutar = async (unidades?: string[], paso_id?: IdPantalla) => {
    const destino = paso_id ?? paso
    const cuerpo: Record<string, unknown> = {}
    if (unidades && unidades.length > 0) cuerpo.unidades = unidades
    try {
      const trabajo = await api.post<TrabajoFicha>(
        `/api/proyectos/${pid}/pasos/${destino}/ejecutar`,
        cuerpo
      )
      setTid(trabajo.id)
      setEstadoTrabajo(trabajo.estado)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const al_terminar = useCallback(
    (final: TrabajoFicha) => {
      setEstadoTrabajo(final.estado)
      if (final.estado === "hecho")
        toast.success(`${NOMBRES_PASOS[final.paso] ?? final.paso}: listo`)
      else if (final.estado === "fallo")
        toast.error(final.error || "el trabajo falló")
      else if (final.estado === "cancelado") toast("trabajo cancelado")
      cargar_coste()
      const destino = (PANTALLAS as string[]).includes(final.paso)
        ? (final.paso as IdPantalla)
        : paso
      recargar_todo(destino)
    },
    [recargar_todo, cargar_coste, paso]
  )

  const renombrar = async (nombre: string, canal: string, idioma: string) => {
    try {
      await api.put(`/api/proyectos/${pid}`, { nombre, canal, idioma })
      toast.success("proyecto actualizado")
      cargar_proyecto()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const aplicar_estilo = async () => {
    if (
      !confirm(
        "¿Reaplicar el estilo del canal? Los pasos afectados quedarán obsoletos: regenerarlos gasta dinero."
      )
    )
      return
    try {
      const r = await api.post<{
        pasos: string[]
        obsoletos_al_regenerar: string[]
      }>(`/api/proyectos/${pid}/aplicar-estilo`)
      if (r.pasos.length === 0) {
        toast("el proyecto ya tenía el estilo del canal")
      } else {
        const nombres = r.pasos.map((p) => NOMBRES_PASOS[p] ?? p).join(", ")
        toast.success(`estilo aplicado a: ${nombres}`)
      }
      recargar_todo()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  /* ------------------------------------------------------------ render */

  if (!proyecto || !pasos || !ficha) {
    return (
      <div className="flex justify-center py-20 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )
  }

  const ocupado =
    tid !== null &&
    (estado_trabajo === "en_cola" || estado_trabajo === "ejecutando")
  const resumen_actual = pasos.pasos[paso]
  const guion_aprobado = pasos.pasos.guion?.aprobado ?? false
  const Panel = paso === "encargo" ? null : PANELES[paso]
  const coste_proyecto = proyecto.coste ?? 0

  /** cada parada sabe si se puede pisar y, si no, por qué (se APAGA
   * con su motivo, no se esconde) */
  const puede_parada = (id: string): { puede: boolean; porque: string } => {
    switch (id) {
      case "encargo":
        return { puede: true, porque: "" }
      case "guion":
        return pasos.pasos.ingesta?.estado !== "vacio"
          ? { puede: true, porque: "" }
          : { puede: false, porque: "procesa el material primero (parada Encargo)" }
      case "imagenes":
        return guion_aprobado
          ? { puede: true, porque: "" }
          : { puede: false, porque: "aprueba el guion primero (parada Guion): cada imagen cuesta dinero" }
      case "video":
        return pasos.pasos.assets?.estado !== "vacio"
          ? { puede: true, porque: "" }
          : { puede: false, porque: "genera las imágenes primero (parada Imágenes)" }
      default:
        return pasos.pasos.render?.estado !== "vacio"
          ? { puede: true, porque: "" }
          : { puede: false, porque: "monta el vídeo primero (parada Vídeo)" }
    }
  }

  return (
    <div className="space-y-4 pb-14 lg:pb-0">
      {/* cabecera del proyecto */}
      <div className="flex flex-wrap items-center gap-3">
        <Boton
          variante="fantasma"
          tamano="icono"
          title="Volver"
          onClick={() => navegar("/")}
        >
          <ArrowLeft />
        </Boton>
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight">
            {proyecto.nombre}
          </h1>
          <p className="text-xs text-muted-foreground">
            {[proyecto.canal, proyecto.idioma].filter(Boolean).join(" · ")} ·{" "}
            <button
              className="underline decoration-dotted underline-offset-2"
              title="Ver el desglose del coste"
              onClick={() => setCosteAbierto(true)}
            >
              {dolares(coste?.coste ?? coste_proyecto)} gastados
              {coste?.presupuesto != null &&
                ` de ${dolares(coste.presupuesto)}`}
            </button>{" "}
            {coste?.aviso && (
              <Insignia variante="destructivo">presupuesto rebasado</Insignia>
            )}
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <Boton
            variante={paso === "encargo" ? "defecto" : "contorno"}
            tamano="pequeno"
            title="El vídeo en una pantalla: material, tono y largo, con autoguardado"
            onClick={() => setPaso(paso === "encargo" ? "ingesta" : "encargo")}
          >
            <ClipboardList /> Encargo
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            title="Ver el vídeo sin montarlo: la imagen y la voz de cada escena, al ritmo de quien mira"
            onClick={() => setVisorAbierto(true)}
          >
            <Eye /> Mirar
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            title="Lo que falta de una tirada: cada pestaña con su receta"
            onClick={() => setRecetaAbierta(true)}
          >
            <Zap /> De una tirada
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            title="Desglose del coste, presupuesto y consumos"
            onClick={() => setCosteAbierto(true)}
          >
            <Wallet /> Coste
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            title="Copiar el estilo del canal sobre los params de este proyecto"
            onClick={aplicar_estilo}
          >
            <Palette /> Aplicar estilo
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            onClick={() => setBitacoraAbierta(true)}
          >
            <BookOpen /> Bitácora
          </Boton>
          <DialogoRenombrar proyecto={proyecto} alGuardar={renombrar} />
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[230px_1fr]">
        {/* columna de pasos */}
        <nav className="flex gap-1 overflow-x-auto lg:sticky lg:top-20 lg:flex-col lg:overflow-visible">
          {PANTALLAS.map((id, i) => {
            const res = pasos.pasos[id]
            const obsoletas = res?.unidades_obsoletas?.length ?? 0
            const seleccionado = id === paso
            return (
              <button
                key={id}
                onClick={() => setPaso(id)}
                className={`flex min-w-[150px] items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors lg:min-w-0 ${
                  seleccionado
                    ? "border-primary/50 bg-secondary"
                    : "border-transparent hover:bg-secondary/60"
                }`}
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {NOMBRES_PASOS[id]}
                </span>
                {obsoletas > 0 ? (
                  <Insignia variante="aviso">{obsoletas}</Insignia>
                ) : (
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      res?.estado === "ok"
                        ? "bg-emerald-500"
                        : res?.estado === "obsoleto"
                          ? "bg-amber-500"
                          : "bg-muted-foreground/25"
                    }`}
                  />
                )}
              </button>
            )
          })}
        </nav>

        {/* panel del paso */}
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">
              {NOMBRE_PANTALLA[paso]}
              {paso !== "repaso" && paso !== "encargo" && ficha.version > 0 && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  v{ficha.version}
                </span>
              )}
            </h2>
            {paso !== "repaso" && paso !== "encargo" && (
              <PildoraEstado estado={ficha.estado} />
            )}
            {paso !== "repaso" && paso !== "encargo" && (
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Estimacion pid={pid} paso={paso} />
                <EditorParams
                  pid={pid}
                  paso={paso}
                  params={ficha.params ?? {}}
                  alGuardar={() => recargar_todo(paso)}
                />
                {ficha.estado !== "vacio" && (
                  <ZonaVersiones
                    pid={pid}
                    paso={paso}
                    version={ficha.version}
                    alRevertir={() => recargar_todo(paso)}
                  />
                )}
              </div>
            )}
          </div>

          {paso !== "ingesta" && paso !== "repaso" && paso !== "encargo" && (
            <div className="flex flex-wrap items-center gap-3">
              <Boton
                onClick={() => ejecutar()}
                deshabilitado={ocupado || (paso === "voz" && !guion_aprobado)}
              >
                {ocupado ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Play />
                )}
                {ficha.estado === "vacio" ? "Generar" : "Regenerar"}
              </Boton>
              {paso === "voz" && !guion_aprobado && (
                <p className="text-xs text-amber-600">
                  guion sin aprobar: aprueba el paso 3 para habilitar la
                  locución (cada generación gasta tokens de ElevenLabs)
                </p>
              )}
              {resumen_actual?.estado === "obsoleto" && (
                <p className="text-xs text-amber-600">
                  hay cambios arriba: regenera para dejarlo al día
                </p>
              )}
            </div>
          )}

          {paso === "encargo" ? (
            <PanelEncargo
              pid={pid}
              ocupado={ocupado}
              params={{
                ingesta: pasos.pasos.ingesta?.params ?? {},
                brief: pasos.pasos.brief?.params ?? {},
                guion: pasos.pasos.guion?.params ?? {},
              }}
              material_listo={pasos.pasos.ingesta?.estado !== "vacio"}
              guion_vacio={pasos.pasos.guion?.estado === "vacio"}
              alEjecutarGuion={() => ejecutar(undefined, "guion")}
              alGuardar={() => {
                cargar_pasos()
              }}
            />
          ) : Panel ? (
            <Panel
              pid={pid}
              ficha={ficha}
              ocupado={ocupado}
              alEjecutar={ejecutar}
              seguirTrabajo={(nuevo_tid) => {
                setTid(nuevo_tid)
                setEstadoTrabajo("en_cola")
              }}
              recargar={() => recargar_todo(paso)}
            />
          ) : null}

          {paso !== "repaso" && paso !== "encargo" && (
            <CajaFeedback
              pid={pid}
              paso={paso}
            ficha={ficha}
            ocupado={ocupado}
            alSeguir={(nuevo_tid) => {
              setTid(nuevo_tid)
              setEstadoTrabajo("en_cola")
            }}
            alAnotar={() => recargar_todo(paso)}
          />
          )}
        </div>
      </div>

      {tid && <BarraTrabajo tid={tid} alTerminar={al_terminar} />}

      <DialogoBitacora
        abierto={bitacora_abierta}
        alCerrar={() => setBitacoraAbierta(false)}
        entradas={bitacora}
        alAbrir={() => setBitacora(null)}
      />

      <DialogoCoste
        pid={pid}
        abierto={coste_abierto}
        alCerrar={() => setCosteAbierto(false)}
        alCambiar={cargar_coste}
      />

      <DialogoReceta
        pid={pid}
        abierto={receta_abierta}
        alCerrar={() => setRecetaAbierta(false)}
        ocupado={ocupado}
        alSeguir={(nuevo_tid) => {
          setTid(nuevo_tid)
          setEstadoTrabajo("en_cola")
        }}
      />

      <DialogoVisor
        pid={pid}
        abierto={visor_abierto}
        alCerrar={() => setVisorAbierto(false)}
      />

      {/* las cinco paradas, solo en móvil: el pipeline de bolsillo */}
      <nav
        aria-label="Paradas del vídeo"
        className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 backdrop-blur lg:hidden"
      >
        <div className="mx-auto flex max-w-7xl items-stretch">
          {PARADAS.map((parada) => {
            const { puede, porque } = puede_parada(parada.id)
            const activa = parada.cubre.includes(paso)
            return (
              <button
                key={parada.id}
                disabled={!puede}
                onClick={() => setPaso(parada.destino)}
                aria-current={activa ? "page" : undefined}
                title={puede ? parada.nombre : porque}
                className={`flex flex-1 flex-col items-center gap-0.5 px-1 py-2 text-[11px] transition-colors ${
                  activa
                    ? "font-semibold text-primary"
                    : "text-muted-foreground hover:text-foreground"
                } ${!puede ? "cursor-not-allowed opacity-40" : ""}`}
              >
                {parada.nombre}
                <span
                  className={`h-0.5 w-6 rounded-full ${
                    activa ? "bg-primary" : "bg-transparent"
                  }`}
                />
              </button>
            )
          })}
        </div>
      </nav>
    </div>
  )
}

/* -------------------------------------------------------------- feedback */

/** Unidades con nombre propio de los datos de un paso (guion/voz/assets). */
function unidades_de(ficha: FichaPaso): string[] {
  const datos = ficha.datos as Record<string, unknown> | null
  if (!datos || typeof datos !== "object") return []
  const planos = datos.planos
  if (Array.isArray(planos))
    return planos.map((p) => String((p as Record<string, unknown>).escena ?? ""))
  const escenas = datos.escenas
  if (Array.isArray(escenas))
    return escenas.map((e) => String((e as Record<string, unknown>).id ?? ""))
  return []
}

function CajaFeedback({
  pid,
  paso,
  ficha,
  ocupado,
  alSeguir,
  alAnotar,
}: {
  pid: string
  paso: IdPaso
  ficha: FichaPaso
  ocupado: boolean
  alSeguir: (tid: string) => void
  alAnotar: () => void
}) {
  const [texto, setTexto] = useState("")
  const [unidad, setUnidad] = useState("")
  const [solo_anotar, setSoloAnotar] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [abierto, setAbierto] = useState(false)
  const unidades = ficha.estado === "vacio" ? [] : unidades_de(ficha)

  const enviar = async () => {
    if (!texto.trim()) return
    setEnviando(true)
    try {
      const r = await api.post<RespuestaFeedback>(
        `/api/proyectos/${pid}/feedback`,
        {
          paso,
          texto,
          unidad: unidad || null,
          ejecutar: solo_anotar ? false : undefined,
        }
      )
      setTexto("")
      if (r.trabajo) {
        toast.success(`feedback en marcha (${r.nota.id})`)
        alSeguir(r.trabajo.id)
      } else {
        toast.success(
          `nota ${r.nota.id} guardada en los params: el paso queda obsoleto`,
        )
        alAnotar()
      }
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="rounded-md border bg-card">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium"
        onClick={() => setAbierto((v) => !v)}
      >
        <MessageSquareHeart className="h-4 w-4" />
        Feedback
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {abierto ? "ocultar" : "cuéntale al paso qué cambiar"}
        </span>
      </button>
      {abierto && (
        <div className="space-y-2 border-t px-3 py-3">
          <p className="text-xs text-muted-foreground">
            La nota se guarda en los parámetros del paso (su firma cambia:
            quedará obsoleto) y se rehace solo lo que apunta — la unidad si
            eliges una, el paso entero si no.
          </p>
          <AreaTexto
            filas={3}
            valor={texto}
            alCambiar={(e) => setTexto(e.target.value)}
            placeholder={
              unidad
                ? `qué cambiar en ${unidad}…`
                : "más corto, sin exageraciones, tono más seco…"
            }
          />
          {unidades.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Etiqueta htmlFor="fb-unidad">Unidad</Etiqueta>
              <select
                id="fb-unidad"
                value={unidad}
                onChange={(e) => setUnidad(e.target.value)}
                className="rounded-md border bg-background px-2 py-1"
              >
                <option value="">el paso entero</option>
                {unidades.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={solo_anotar}
                onChange={(e) => setSoloAnotar(e.target.checked)}
              />
              solo anotar (no relanzar ahora)
            </label>
            <Boton
              tamano="pequeno"
              className="ml-auto"
              deshabilitado={enviando || !texto.trim() || ocupado}
              onClick={enviar}
            >
              {enviando && <Loader2 className="animate-spin" />}
              Enviar feedback
            </Boton>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ renombrar */

function DialogoRenombrar({
  proyecto,
  alGuardar,
}: {
  proyecto: FichaProyecto
  alGuardar: (nombre: string, canal: string, idioma: string) => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState(proyecto.nombre)
  const [canal, setCanal] = useState(proyecto.canal)
  const [idioma, setIdioma] = useState(proyecto.idioma)

  useEffect(() => {
    if (abierto) {
      setNombre(proyecto.nombre)
      setCanal(proyecto.canal)
      setIdioma(proyecto.idioma)
    }
  }, [abierto, proyecto])

  return (
    <>
      <Boton
        variante="contorno"
        tamano="pequeno"
        onClick={() => setAbierto(true)}
      >
        <Settings2 /> Ajustes
      </Boton>
      <Dialogo abierto={abierto} alCambiar={setAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Ajustes del proyecto</TituloDialogo>
            <DescripcionDialogo>
              Nombre, canal e idioma (afecta a las instrucciones del LLM).
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="space-y-4">
            <div className="space-y-2">
              <Etiqueta htmlFor="r-nombre">Nombre</Etiqueta>
              <Entrada
                id="r-nombre"
                valor={nombre}
                alCambiar={(e) => setNombre(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Etiqueta htmlFor="r-canal">Canal</Etiqueta>
                <Entrada
                  id="r-canal"
                  valor={canal}
                  alCambiar={(e) => setCanal(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Etiqueta htmlFor="r-idioma">Idioma</Etiqueta>
                <Entrada
                  id="r-idioma"
                  valor={idioma}
                  alCambiar={(e) => setIdioma(e.target.value)}
                />
              </div>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => setAbierto(false)}>
              Cancelar
            </Boton>
            <Boton
              deshabilitado={!nombre.trim()}
              onClick={() => {
                alGuardar(nombre.trim(), canal.trim(), idioma.trim())
                setAbierto(false)
              }}
            >
              Guardar
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}

/* -------------------------------------------------------------- bitácora */

function DialogoBitacora({
  abierto,
  alCerrar,
  entradas,
  alAbrir,
}: {
  abierto: boolean
  alCerrar: () => void
  entradas: EntradaBitacora[] | null
  alAbrir: () => void
}) {
  useEffect(() => {
    if (abierto) alAbrir()
  }, [abierto, alAbrir])

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo>
        <CabeceraDialogo>
          <TituloDialogo>Bitácora</TituloDialogo>
          <DescripcionDialogo>
            Últimos 200 eventos del proyecto (generaciones, correcciones,
            reversiones…).
          </DescripcionDialogo>
        </CabeceraDialogo>
        <div className="max-h-[60vh] space-y-1.5 overflow-y-auto font-mono text-xs">
          {!entradas ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : entradas.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              sin eventos
            </p>
          ) : (
            [...entradas].reverse().map((e, i) => {
              const { t, evento, ...detalle } = e
              const extra = Object.keys(detalle).length
                ? JSON.stringify(detalle)
                : ""
              return (
                <p key={i} className="flex gap-2">
                  <span className="shrink-0 text-muted-foreground">
                    {new Date(t).toLocaleString()}
                  </span>
                  <span className="shrink-0 font-semibold">{evento}</span>
                  <span className="min-w-0 truncate text-muted-foreground">
                    {extra}
                  </span>
                </p>
              )
            })
          )}
        </div>
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ----------------------------------------------------------------- coste */

function DialogoCoste({
  pid,
  abierto,
  alCerrar,
  alCambiar,
}: {
  pid: string
  abierto: boolean
  alCerrar: () => void
  alCambiar: () => void
}) {
  const [ficha, setFicha] = useState<CosteProyecto | null>(null)
  const [por_paso, setPorPaso] = useState<CostePorPaso | null>(null)
  const [eventos, setEventos] = useState<EventoCoste[] | null>(null)
  const [presupuesto, setPresupuesto] = useState("")
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    if (!abierto) return
    setFicha(null)
    setPorPaso(null)
    setEventos(null)
    api
      .get<CosteProyecto>(`/api/proyectos/${pid}/coste`)
      .then((r) => {
        setFicha(r)
        setPresupuesto(r.presupuesto != null ? String(r.presupuesto) : "")
      })
      .catch(() => setFicha(null))
    api.get<CostePorPaso>(`/api/proyectos/${pid}/coste/por-paso`)
      .then(setPorPaso)
      .catch(() => setPorPaso({}))
    api
      .get<EventoCoste[]>(`/api/proyectos/${pid}/coste/eventos?limite=100`)
      .then(setEventos)
      .catch(() => setEventos([]))
  }, [abierto, pid])

  const guardar_presupuesto = async (valor: string | null) => {
    setGuardando(true)
    try {
      const cuerpo = valor === null ? { presupuesto: null } : { presupuesto: Number(valor.replace(",", ".")) }
      const r = await api.put<CosteProyecto>(
        `/api/proyectos/${pid}/coste/presupuesto`,
        cuerpo,
      )
      setFicha((prev) => (prev ? { ...prev, ...r } : r))
      setPresupuesto(r.presupuesto != null ? String(r.presupuesto) : "")
      toast.success(
        r.presupuesto == null
          ? "presupuesto quitado"
          : "presupuesto guardado: avisará al rebasarlo",
      )
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const copiar_bitacora = async () => {
    try {
      const r = await api.get<{ texto: string; eventos: number }>(
        `/api/proyectos/${pid}/bitacora/llm`,
      )
      await navigator.clipboard.writeText(r.texto)
      toast.success(`bitácora copiada (${r.eventos} eventos)`)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const pasos_ordenados = por_paso
    ? Object.entries(por_paso).sort((a, b) => b[1].coste - a[1].coste)
    : []

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo className="max-w-2xl">
        <CabeceraDialogo>
          <TituloDialogo>Coste del proyecto</TituloDialogo>
          <DescripcionDialogo>
            Cada consumo apuntado al gastarse. El presupuesto solo avisa: no
            corta nada.
          </DescripcionDialogo>
        </CabeceraDialogo>

        {!ficha ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-5">
            {/* resumen */}
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="rounded-md border p-3">
                <p className="text-lg font-semibold">{dolares(ficha.coste)}</p>
                <p className="text-xs text-muted-foreground">total</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-lg font-semibold">{ficha.operaciones}</p>
                <p className="text-xs text-muted-foreground">operaciones</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-lg font-semibold">
                  {ficha.presupuesto != null ? dolares(ficha.presupuesto) : "—"}
                </p>
                <p className="text-xs text-muted-foreground">presupuesto</p>
              </div>
            </div>
            {ficha.aviso && (
              <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
                El gasto ya rebasa el presupuesto fijado.
              </p>
            )}

            {/* por paso */}
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Reparto por paso</p>
              {pasos_ordenados.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  todavía no hay consumos
                </p>
              ) : (
                pasos_ordenados.map(([paso, info]) => (
                  <div key={paso} className="flex items-center gap-2 text-xs">
                    <span className="w-32 shrink-0 truncate">
                      {NOMBRES_PASOS[paso] ?? paso}
                    </span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary/70"
                        style={{
                          width: `${
                            ficha.coste > 0
                              ? Math.max(2, (info.coste / ficha.coste) * 100)
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                    <span className="w-24 shrink-0 text-right tabular-nums">
                      {dolares(info.coste)} · {info.operaciones} op.
                    </span>
                  </div>
                ))
              )}
            </div>

            {/* últimos consumos */}
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Últimos consumos</p>
              <div className="max-h-40 space-y-1 overflow-y-auto font-mono text-xs">
                {!eventos || eventos.length === 0 ? (
                  <p className="text-muted-foreground">sin consumos aún</p>
                ) : (
                  [...eventos].reverse().map((e, i) => (
                    <p key={i} className="flex gap-2">
                      <span className="shrink-0 text-muted-foreground">
                        {new Date(e.t).toLocaleTimeString()}
                      </span>
                      <span className="w-28 shrink-0 truncate" title={e.contexto}>
                        {e.paso ?? e.contexto}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-muted-foreground">
                        {[e.proveedor, e.modelo].filter(Boolean).join("/")}
                        {e.operacion === "llm"
                          ? ` · ${e.entrada}→${e.salida} tok`
                          : ""}
                      </span>
                      <span className="shrink-0 tabular-nums">
                        {dolares(e.coste)}
                      </span>
                    </p>
                  ))
                )}
              </div>
            </div>

            {/* presupuesto */}
            <div className="flex flex-wrap items-end gap-2 rounded-md border p-3">
              <div className="space-y-1">
                <Etiqueta htmlFor="presupuesto">
                  Presupuesto (USD, solo avisa)
                </Etiqueta>
                <Entrada
                  id="presupuesto"
                  tipo="number"
                  min="0"
                  paso="0.5"
                  placeholder="sin límite"
                  valor={presupuesto}
                  alCambiar={(e) => setPresupuesto(e.target.value)}
                  className="w-32"
                />
              </div>
              <Boton
                tamano="pequeno"
                deshabilitado={guardando || presupuesto.trim() === ""}
                onClick={() => guardar_presupuesto(presupuesto)}
              >
                Fijar
              </Boton>
              <Boton
                variante="contorno"
                tamano="pequeno"
                deshabilitado={guardando || ficha.presupuesto == null}
                onClick={() => guardar_presupuesto(null)}
              >
                Quitar
              </Boton>
              <Boton
                variante="fantasma"
                tamano="pequeno"
                className="ml-auto"
                title="Copiar la bitácora entera como texto para pegársela a un LLM"
                onClick={copiar_bitacora}
              >
                <ClipboardCopy /> Copiar bitácora
              </Boton>
            </div>
          </div>
        )}
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ---------------------------------------------------------------- receta */

function DialogoReceta({
  pid,
  abierto,
  alCerrar,
  ocupado,
  alSeguir,
}: {
  pid: string
  abierto: boolean
  alCerrar: () => void
  ocupado: boolean
  alSeguir: (tid: string) => void
}) {
  const [ficha, setFicha] = useState<FichaReceta | null>(null)

  useEffect(() => {
    if (!abierto) return
    setFicha(null)
    api
      .get<FichaReceta>(`/api/proyectos/${pid}/receta`)
      .then(setFicha)
      .catch(() => setFicha(null))
  }, [abierto, pid])

  const lanzar = async (pestana: string, modo: "pendiente" | "todo") => {
    try {
      const t = await api.post<TrabajoFicha>(
        `/api/proyectos/${pid}/receta/${pestana}`,
        { modo },
      )
      toast.success(`receta en marcha (${modo})`)
      alCerrar()
      alSeguir(t.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo className="max-w-2xl">
        <CabeceraDialogo>
          <TituloDialogo>De una tirada</TituloDialogo>
          <DescripcionDialogo>
            Lo que en pantallas son muchos botones en el orden correcto, aquí
            es una lista. Cada paso sigue teniendo su botón, su ficha y su
            revisión: la receta no esconde nada, adelanta trabajo. La voz no
            se graba sin el guion aprobado.
          </DescripcionDialogo>
        </CabeceraDialogo>
        {!ficha ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-3">
            {Object.entries(ficha.pestañas).map(([clave, pestana]) => {
              const pendientes = pestana.tareas.filter(
                (t) => t.estado !== "ok",
              ).length
              return (
                <div key={clave} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold">{pestana.nombre}</p>
                    {pendientes > 0 ? (
                      <Insignia variante="aviso">
                        {pendientes} pendiente{pendientes > 1 ? "s" : ""}
                      </Insignia>
                    ) : (
                      <Insignia variante="exito">al día</Insignia>
                    )}
                    <div className="ml-auto flex gap-2">
                      <Boton
                        tamano="pequeno"
                        deshabilitado={ocupado || pendientes === 0}
                        title="Corre lo que falta y se salta lo que ya está al día"
                        onClick={() => lanzar(clave, "pendiente")}
                      >
                        Generar lo pendiente
                      </Boton>
                      <Boton
                        tamano="pequeno"
                        variante="contorno"
                        deshabilitado={ocupado}
                        title="Lo corre todo, aunque esté al día (paga otra vez)"
                        onClick={() => lanzar(clave, "todo")}
                      >
                        Generar todo
                      </Boton>
                    </div>
                  </div>
                  <ul className="mt-2 space-y-1.5">
                    {pestana.tareas.map((t) => (
                      <li
                        key={t.id}
                        className="flex flex-wrap items-center gap-2 text-xs"
                      >
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${
                            t.estado === "ok"
                              ? "bg-emerald-500"
                              : t.estado === "obsoleto"
                                ? "bg-amber-500"
                                : "bg-muted-foreground/25"
                          }`}
                        />
                        <span className="font-medium">{t.nombre}</span>
                        {t.cuesta && (
                          <span
                            title="gasta dinero al correr"
                            className="text-amber-600"
                          >
                            ¢
                          </span>
                        )}
                        {t.estado === "obsoleto" && (
                          <Insignia variante="aviso">obsoleto</Insignia>
                        )}
                        {t.aprobado && <Insignia variante="exito">✓</Insignia>}
                        <span className="min-w-0 flex-1 truncate text-muted-foreground">
                          {t.porque}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        )}
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ---------------------------------------------------------- previsualizar */

function DialogoVisor({
  pid,
  abierto,
  alCerrar,
}: {
  pid: string
  abierto: boolean
  alCerrar: () => void
}) {
  const [datos, setDatos] = useState<Previsualizacion | null>(null)
  const [indice, setIndice] = useState(0)
  const [seguido, setSeguido] = useState(false)
  const [t_audio, setTAudio] = useState(0)
  const [captura_abierta, setCapturaAbierta] = useState(false)
  const audio_ref = useRef<HTMLAudioElement | null>(null)
  const img_ref = useRef<HTMLImageElement | null>(null)

  useEffect(() => {
    if (!abierto) return
    setDatos(null)
    setIndice(0)
    setSeguido(false)
    api
      .get<Previsualizacion>(`/api/proyectos/${pid}/previsualizacion`)
      .then(setDatos)
      .catch((e) => {
        toast.error(String((e as Error).message ?? e))
        alCerrar()
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto, pid])

  const escena = datos?.escenas[indice]
  const ultima = datos ? indice >= datos.escenas.length - 1 : true

  // al cambiar de plano: colocarse en su ventana dentro del audio de la
  // escena y seguir si iba seguido (el plano ENTRA en su t_in, no en 0)
  useEffect(() => {
    const audio = audio_ref.current
    const desde = escena?.t_in ?? 0
    setTAudio(desde)
    if (!audio || !escena?.audio) return
    const colocar = () => {
      audio.currentTime = desde
    }
    colocar()
    audio.addEventListener("loadedmetadata", colocar, { once: true })
    if (seguido) audio.play().catch(() => setSeguido(false))
    return () => audio.removeEventListener("loadedmetadata", colocar)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indice])

  // el plano dura hasta SU t_out: ahí cambia (seguido) o se para
  const al_mover_reloj = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    const t = e.currentTarget.currentTime
    setTAudio(t)
    const fin = escena?.t_out ?? Infinity
    if (t >= fin - 0.03) {
      if (seguido && !ultima) setIndice(indice + 1)
      else {
        e.currentTarget.pause()
        setSeguido(false)
      }
    }
  }

  const al_terminar_audio = () => {
    if (seguido && !ultima) setIndice(indice + 1)
    else setSeguido(false)
  }

  const alternar = () => {
    const audio = audio_ref.current
    if (!audio) return
    if (seguido && !audio.paused) {
      setSeguido(false)
      audio.pause()
    } else {
      setSeguido(true)
      audio.play().catch(() => {})
    }
  }

  const rotulo_visible =
    escena?.rotulo != null &&
    t_audio - escena.t_in >= escena.rotulo.aparece &&
    t_audio - escena.t_in < escena.rotulo.aparece + escena.rotulo.dura

  /** Compone el fotograma de la previsualización: imagen + rótulo tal
   * como se ven (la captura es de lo que se está MIRANDO). */
  const componer_fotograma = (): HTMLCanvasElement | null => {
    const img = img_ref.current
    if (!img || !img.naturalWidth) return null
    const lienzo = document.createElement("canvas")
    lienzo.width = 1280
    lienzo.height = 720
    const ctx = lienzo.getContext("2d")!
    ctx.fillStyle = "#000"
    ctx.fillRect(0, 0, 1280, 720)
    const escala = Math.min(1280 / img.naturalWidth, 720 / img.naturalHeight)
    const w = img.naturalWidth * escala
    const h = img.naturalHeight * escala
    ctx.drawImage(img, (1280 - w) / 2, (720 - h) / 2, w, h)
    if (rotulo_visible && escena?.rotulo) {
      const texto = escena.rotulo.texto
      ctx.font = "600 44px system-ui, sans-serif"
      const metrica = ctx.measureText(texto)
      const ancho = metrica.width + 56
      const alto = 72
      const x = (1280 - ancho) / 2
      const y = 720 - 160
      ctx.fillStyle = "rgba(0,0,0,0.75)"
      ctx.beginPath()
      ctx.roundRect(x, y, ancho, alto, 18)
      ctx.fill()
      ctx.fillStyle = "#fff"
      ctx.textBaseline = "middle"
      ctx.fillText(texto, x + 28, y + alto / 2 + 2)
    }
    ctx.fillStyle = "rgba(0,0,0,0.6)"
    ctx.fillRect(0, 0, 220, 34)
    ctx.fillStyle = "#fff"
    ctx.font = "500 20px system-ui, sans-serif"
    ctx.textBaseline = "middle"
    ctx.fillText(`${indice + 1}/${datos?.escenas.length ?? 1} · ${escena?.id ?? ""}`, 12, 18)
    return lienzo
  }

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo className="max-w-3xl">
        <CabeceraDialogo>
          <TituloDialogo>Mirar sin montar</TituloDialogo>
          <DescripcionDialogo>
            El vídeo antes de montarlo: la imagen y la voz de cada escena, al
            ritmo de quien mira. El rótulo es texto de verdad (como se verá);
            el zoom y los cortes sólo se ven en el MP4.
          </DescripcionDialogo>
        </CabeceraDialogo>
        {!datos || !escena ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-3">
            <div
              className="relative overflow-hidden rounded-md bg-black"
              style={{ aspectRatio: "16 / 9" }}
            >
              {escena.imagen ? (
                <img
                  ref={img_ref}
                  src={`/a/${pid}/${escena.imagen}`}
                  alt={escena.titulo || escena.id}
                  className="h-full w-full object-contain"
                />
              ) : escena.cartela ? (
                <div className="flex h-full items-center justify-center text-sm text-white/60">
                  cartela de texto ({escena.cartela}) — la dibuja el render
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-white/60">
                  sin imagen para este plano (genera las imágenes)
                </div>
              )}
              {rotulo_visible && escena.rotulo && (
                <div className="pointer-events-none absolute inset-x-0 bottom-10 flex justify-center px-6">
                  <span className="rounded-2xl bg-black/75 px-6 py-3 text-lg font-semibold text-white">
                    {escena.rotulo.texto}
                  </span>
                </div>
              )}
              <span className="absolute left-2 top-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">
                {indice + 1}/{datos.escenas.length} · {escena.id}
              </span>
            </div>

            <audio
              ref={audio_ref}
              src={escena.audio ? `/a/${pid}/${escena.audio}` : undefined}
              onTimeUpdate={al_mover_reloj}
              onEnded={al_terminar_audio}
              controls
              className="w-full"
            />

            <div className="flex flex-wrap items-center gap-2">
              <Boton
                variante="contorno"
                tamano="icono"
                title="Escena anterior"
                deshabilitado={indice === 0}
                onClick={() => setIndice(indice - 1)}
              >
                <ChevronLeft />
              </Boton>
              <Boton
                variante="contorno"
                tamano="icono"
                title="Escena siguiente"
                deshabilitado={ultima}
                onClick={() => setIndice(indice + 1)}
              >
                <ChevronRight />
              </Boton>
              <Boton
                tamano="pequeno"
                onClick={alternar}
                deshabilitado={!escena.audio}
              >
                {seguido ? (
                  <>
                    <Pause /> Parar
                  </>
                ) : (
                  <>
                    <Play /> Seguir seguido
                  </>
                )}
              </Boton>
              <span className="ml-auto text-xs text-muted-foreground">
                {segundos(escena.duracion)} · total {segundos(datos.duracion)}
                {datos.montado && " · MP4 listo"}
              </span>
              <Boton
                variante="contorno"
                tamano="pequeno"
                title="Congela este plano (con su rótulo tal como se ve) y pinta encima"
                onClick={() => setCapturaAbierta(true)}
              >
                <Camera /> Capturar
              </Boton>
            </div>

            <div className="flex flex-wrap gap-1">
              {datos.escenas.map((e, i) => (
                <button
                  key={e.id}
                  onClick={() => setIndice(i)}
                  className={`rounded px-2 py-0.5 font-mono text-xs ${
                    i === indice
                      ? "bg-secondary font-semibold"
                      : "text-muted-foreground hover:bg-secondary/60"
                  }`}
                >
                  {e.id}
                </button>
              ))}
            </div>

            <p className="text-sm text-muted-foreground">{escena.narracion}</p>
          </div>
        )}

        <DialogoCaptura
          pid={pid}
          abierto={captura_abierta}
          alCambiar={setCapturaAbierta}
          paso="callouts"
          escena={escena?.id ?? ""}
          componer={componer_fotograma}
          t_escena={t_audio}
        />
      </ContenidoDialogo>
    </Dialogo>
  )
}
