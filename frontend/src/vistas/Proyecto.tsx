/** Vista de un proyecto: pipeline de 8 pasos + seguimiento de trabajos. */
import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { ArrowLeft, BookOpen, Loader2, Play, Settings2 } from "lucide-react"
import { api } from "../lib/api"
import { dolares } from "../lib/utils"
import {
  NOMBRES_PASOS,
  ORDEN_PASOS,
  type EntradaBitacora,
  type FichaPaso,
  type FichaPasos,
  type FichaProyecto,
  type IdPaso,
  type TrabajoFicha,
} from "../lib/tipos"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import {
  Dialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
} from "../components/ui/dialogo"
import { BarraTrabajo } from "../components/barra_trabajo"
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

const PANELES: Record<IdPaso, (p: PropsPanel) => JSX.Element> = {
  ingesta: PanelIngesta,
  brief: PanelBrief,
  guion: PanelGuion,
  voz: PanelVoz,
  revision_audio: PanelRevision,
  assets: PanelAssets,
  callouts: PanelCallouts,
  render: PanelRender,
}

export default function Proyecto() {
  const { pid = "" } = useParams()
  const navegar = useNavigate()
  const [proyecto, setProyecto] = useState<FichaProyecto | null>(null)
  const [pasos, setPasos] = useState<FichaPasos | null>(null)
  const [paso, setPaso] = useState<IdPaso>("ingesta")
  const [ficha, setFicha] = useState<FichaPaso | null>(null)
  const [tid, setTid] = useState<string | null>(null)
  const [estado_trabajo, setEstadoTrabajo] = useState<string | null>(null)
  const [bitacora, setBitacora] = useState<EntradaBitacora[] | null>(null)
  const [bitacora_abierta, setBitacoraAbierta] = useState(false)

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
    async (paso_id: string, base: FichaPasos | null = null) => {
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
  }, [cargar_proyecto, cargar_pasos])

  useEffect(() => {
    if (pasos) cargar_ficha(paso, pasos)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso, pasos])

  useEffect(() => {
    if (!bitacora_abierta || bitacora) return
    api
      .get<EntradaBitacora[]>(`/api/proyectos/${pid}/bitacora?limite=200`)
      .then(setBitacora)
      .catch(() => setBitacora([]))
  }, [bitacora_abierta, bitacora, pid])

  /* ---------------------------------------------------------- acciones */

  const recargar_todo = useCallback(
    async (paso_id?: string) => {
      await cargar_pasos()
      await cargar_ficha(paso_id ?? paso, null)
      cargar_proyecto()
    },
    [cargar_pasos, cargar_ficha, cargar_proyecto, paso]
  )

  const ejecutar = async (unidades?: string[]) => {
    const cuerpo: Record<string, unknown> = {}
    if (unidades && unidades.length > 0) cuerpo.unidades = unidades
    try {
      const trabajo = await api.post<TrabajoFicha>(
        `/api/proyectos/${pid}/pasos/${paso}/ejecutar`,
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
      recargar_todo(final.paso)
    },
    [recargar_todo]
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
  const Panel = PANELES[paso]
  const coste_proyecto = proyecto.coste ?? 0

  return (
    <div className="space-y-4">
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
            {dolares(coste_proyecto)} gastados
          </p>
        </div>
        <div className="ml-auto flex gap-2">
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
          {ORDEN_PASOS.map((id, i) => {
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
              {NOMBRES_PASOS[paso]}
              {ficha.version > 0 && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  v{ficha.version}
                </span>
              )}
            </h2>
            <PildoraEstado estado={ficha.estado} />
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
          </div>

          {paso !== "ingesta" && (
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
        </div>
      </div>

      {tid && <BarraTrabajo tid={tid} alTerminar={al_terminar} />}

      <DialogoBitacora
        abierto={bitacora_abierta}
        alCerrar={() => setBitacoraAbierta(false)}
        entradas={bitacora}
        alAbrir={() => setBitacora(null)}
      />
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
