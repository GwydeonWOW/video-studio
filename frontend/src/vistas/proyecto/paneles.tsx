/** Paneles de contenido para cada paso del pipeline. */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { AudioLines, BadgeCheck, Check, Film, Loader2, Palette, PenLine, Play, RefreshCw } from "lucide-react"
import { api } from "../../lib/api"
import { segundos } from "../../lib/utils"
import { usarTrabajo } from "../../lib/trabajos"
import type {
  DatosAssets,
  DatosBrief,
  DatosCallouts,
  DatosGuion,
  DatosIngesta,
  DatosRender,
  DatosRevision,
  DatosVoz,
  FichaPaso,
  PrevisualizacionVoz,
  PresetVoz,
  PropuestaVoz,
  TrabajoFicha,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { AreaTexto } from "../../components/ui/textarea"
import { Entrada } from "../../components/ui/input"
import { Etiqueta } from "../../components/ui/etiqueta"
import { Insignia } from "../../components/ui/badge"
import {
  Tarjeta,
  ContenidoTarjeta,
} from "../../components/ui/tarjeta"
import {
  Dialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
} from "../../components/ui/dialogo"
import {
  Selector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
  ValorSelector,
} from "../../components/ui/selector"
import { Vacio } from "./piezas"
import { ZonaPresetPaso } from "./preset_paso"
import { DialogoGrafismo, type PestanaGrafismo } from "./grafismo"
import {
  DialogoSonido,
  DialogoTransiciones,
  type PestanaSonido,
} from "./sonido"
import {
  DialogoConservacion,
  DialogoEstiloVisual,
  type PestanaEstiloVisual,
} from "./estilo_visual"

export interface PropsPanel {
  pid: string
  ficha: FichaPaso
  ocupado: boolean
  /** lanza el paso entero (o solo unas unidades) y sigue el trabajo */
  alEjecutar: (unidades?: string[]) => void
  /** sigue un trabajo concreto (operaciones unitarias) */
  seguirTrabajo: (tid: string) => void
  recargar: () => void
}

/* ------------------------------------------------------------- 1 ingesta */

export function PanelIngesta({ pid, ficha, alEjecutar, ocupado }: PropsPanel) {
  const datos = ficha.estado !== "vacio" ? (ficha.datos as DatosIngesta) : null
  const [texto, setTexto] = useState<string>(
    String(ficha.params?.texto ?? datos?.texto ?? "")
  )
  const [titulo, setTitulo] = useState<string>(
    String(ficha.params?.titulo ?? datos?.titulo ?? "")
  )
  const [guardando, setGuardando] = useState(false)

  const guardar_y_ejecutar = async () => {
    if (!texto.trim()) {
      toast.error("pega el material de origen")
      return
    }
    setGuardando(true)
    try {
      await api.put(`/api/proyectos/${pid}/pasos/ingesta/params`, {
        texto,
        titulo,
      })
      alEjecutar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Etiqueta htmlFor="titulo">Título (opcional)</Etiqueta>
        <Entrada
          id="titulo"
          valor={titulo}
          alCambiar={(e) => setTitulo(e.target.value)}
          placeholder="si queda vacío se toma del primer párrafo"
        />
      </div>
      <div className="space-y-2">
        <Etiqueta htmlFor="texto">Material de origen</Etiqueta>
        <AreaTexto
          id="texto"
          filas={16}
          valor={texto}
          alCambiar={(e) => setTexto(e.target.value)}
          placeholder="pega aquí el artículo, guion bruto o material…"
          className="font-mono text-[13px]"
        />
        <p className="text-xs text-muted-foreground">
          {texto.trim().length} caracteres
        </p>
      </div>
      <Boton
        onClick={guardar_y_ejecutar}
        deshabilitado={guardando || ocupado}
      >
        {guardando || ocupado ? <Loader2 className="animate-spin" /> : null}
        {ficha.estado === "vacio" ? "Procesar material" : "Reprocesar material"}
      </Boton>
    </div>
  )
}

/* --------------------------------------------------------------- 2 brief */

export function PanelBrief({ pid, ficha, recargar }: PropsPanel) {
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin brief"
        detalle="Ejecuta el paso para extraer los puntos clave del material con el LLM configurado."
      />
    )
  const datos = ficha.datos as DatosBrief
  return (
    <div className="space-y-4">
      <ZonaPresetPaso pid={pid} tipo="guion" recargar={recargar} />
      {datos.tono && (
        <p className="text-sm text-muted-foreground">
          Tono: <span className="text-foreground">{datos.tono}</span>
          {datos.formato && (
            <>
              {" · "}Duración: {datos.formato.min}–{datos.formato.max} min
            </>
          )}
        </p>
      )}
      <ol className="space-y-2">
        {(datos.puntos ?? []).map((p, i) => (
          <li
            key={i}
            className="flex gap-3 rounded-md border bg-card px-3 py-2 text-sm"
          >
            <span className="font-mono text-xs text-muted-foreground">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span>{p}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/* --------------------------------------------------------------- 3 guion */

export function PanelGuion({
  pid,
  ficha,
  ocupado,
  seguirTrabajo,
  recargar,
}: PropsPanel) {
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set())
  const [bloques_abierto, setBloquesAbierto] = useState(false)
  const [orden_bloques, setOrdenBloques] = useState("")
  const [enviando_bloques, setEnviandoBloques] = useState(false)

  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin guion"
        detalle="Necesitas un brief al día; luego ejecuta el paso para escribir las escenas."
      />
    )
  const datos = ficha.datos as DatosGuion
  const escenas = datos.escenas ?? []

  const cambiar_seleccion = (id: string) => {
    setSeleccion((previa) => {
      const nueva = new Set(previa)
      if (nueva.has(id)) nueva.delete(id)
      else nueva.add(id)
      return nueva
    })
  }

  const reescribir_bloques = async () => {
    if (!orden_bloques.trim() || seleccion.size === 0) return
    setEnviandoBloques(true)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/guion/bloques/reescribir`,
        { ids: [...seleccion], orden: orden_bloques }
      )
      setBloquesAbierto(false)
      setOrdenBloques("")
      setSeleccion(new Set())
      seguirTrabajo(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviandoBloques(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm">
        {ficha.aprobado ? (
          <p className="flex items-center gap-2 text-emerald-600">
            <BadgeCheck className="h-4 w-4" />
            Guion aprobado (v{ficha.version}): la locucción puede generarse.
          </p>
        ) : (
          <>
            <p className="text-muted-foreground">
              Guion en revisión: la locucción está bloqueada hasta que lo
              apruebes (así no se gastan tokens de ElevenLabs en cada cambio).
            </p>
            <BotonAprobar
              pid={pid}
              version={ficha.version}
              deshabilitado={ocupado || ficha.estado === "obsoleto"}
              recargar={recargar}
            />
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          {escenas.length} escenas ·{" "}
          {segundos(datos.duracion_estimada ?? 0)} estimados
        </p>
        {seleccion.size > 0 && (
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={ocupado}
            onClick={() => setBloquesAbierto(true)}
          >
            <PenLine /> Reescribir {seleccion.size} juntas
          </Boton>
        )}
        {seleccion.size > 1 && (
          <Boton
            variante="fantasma"
            tamano="pequeno"
            onClick={() => setSeleccion(new Set())}
          >
            limpiar selección
          </Boton>
        )}
      </div>
      {escenas.map((escena) => (
        <Tarjeta key={escena.id}>
          <ContenidoTarjeta className="space-y-2 p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-primary"
                  checked={seleccion.has(escena.id)}
                  onChange={() => cambiar_seleccion(escena.id)}
                  title="Marcar para reescribir en bloque"
                />
                <div className="min-w-0">
                  <p className="font-mono text-xs text-muted-foreground">
                    {escena.id}
                  </p>
                  <p className="font-medium">{escena.titulo}</p>
                </div>
              </div>
              <BotonReescribir
                pid={pid}
                escena={escena.id}
                ocupado={ocupado}
                seguirTrabajo={seguirTrabajo}
              />
            </div>
            <p className="whitespace-pre-wrap text-sm">{escena.narracion}</p>
            {escena.visual && (
              <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Visual:</span>{" "}
                {escena.visual}
              </p>
            )}
            <div className="flex flex-wrap gap-2 text-xs">
              {escena.texto_pantalla && (
                <Insignia variante="contorno">
                  📺 {escena.texto_pantalla}
                </Insignia>
              )}
              {escena.duracion_estimada != null && (
                <Insignia variante="secundario">
                  ~{segundos(escena.duracion_estimada)}
                </Insignia>
              )}
            </div>
          </ContenidoTarjeta>
        </Tarjeta>
      ))}

      <Dialogo abierto={bloques_abierto} alCambiar={setBloquesAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>
              Reescribir {seleccion.size} escenas juntas
            </TituloDialogo>
            <DescripcionDialogo>
              Una orden para todas las marcadas ([...{[...seleccion].join(", ")}
              ...]). El LLM reescribe cada una por separado respetando la
              orden; el audio no se toca (quedará obsoleto por escena).
            </DescripcionDialogo>
          </CabeceraDialogo>
          <AreaTexto
            filas={4}
            valor={orden_bloques}
            alCambiar={(e) => setOrdenBloques(e.target.value)}
            placeholder="cíñete a los datos, sin exageraciones, frases más cortas…"
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => setBloquesAbierto(false)}>
              Cancelar
            </Boton>
            <Boton
              onClick={reescribir_bloques}
              deshabilitado={enviando_bloques || !orden_bloques.trim()}
            >
              {enviando_bloques && <Loader2 className="animate-spin" />}
              Reescribir
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </div>
  )
}

function BotonAprobar({
  pid,
  version,
  deshabilitado,
  recargar,
}: {
  pid: string
  version: number
  deshabilitado: boolean
  recargar: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [enviando, setEnviando] = useState(false)

  const aprobar = async () => {
    setEnviando(true)
    try {
      await api.post(`/api/proyectos/${pid}/pasos/guion/aprobar`)
      toast.success("guion aprobado: la locucción ya puede generarse")
      setAbierto(false)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <Boton
        tamano="pequeno"
        className="ml-auto"
        deshabilitado={deshabilitado}
        onClick={() => setAbierto(true)}
      >
        <BadgeCheck /> Aprobar guion
      </Boton>
      <Dialogo abierto={abierto} alCambiar={setAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Aprobar el guion (v{version})</TituloDialogo>
            <DescripcionDialogo>
              Con esto se habilita el paso de voz (ElevenLabs cobra por
              carácter). Si luego editas, reescribes escenas o regeneras el
              guion, hará falta aprobar de nuevo antes de regrabar.
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => setAbierto(false)}>
              Cancelar
            </Boton>
            <Boton onClick={aprobar} deshabilitado={enviando}>
              {enviando && <Loader2 className="animate-spin" />}
              Aprobar
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}

function BotonReescribir({
  pid,
  escena,
  ocupado,
  seguirTrabajo,
}: {
  pid: string
  escena: string
  ocupado: boolean
  seguirTrabajo: (tid: string) => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [orden, setOrden] = useState("")
  const [enviando, setEnviando] = useState(false)

  const reescribir = async () => {
    if (!orden.trim()) return
    setEnviando(true)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/guion/escenas/${escena}/reescribir`,
        { orden }
      )
      setAbierto(false)
      setOrden("")
      seguirTrabajo(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <Boton
        variante="contorno"
        tamano="pequeno"
        deshabilitado={ocupado}
        onClick={() => setAbierto(true)}
      >
        <PenLine /> Reescribir
      </Boton>
      <Dialogo abierto={abierto} alCambiar={setAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Reescribir {escena}</TituloDialogo>
            <DescripcionDialogo>
              Describe el cambio en lenguaje natural; el LLM reescribe solo
              esta escena.
            </DescripcionDialogo>
          </CabeceraDialogo>
          <AreaTexto
            filas={4}
            valor={orden}
            alCambiar={(e) => setOrden(e.target.value)}
            placeholder="más corta, tono más directo, añade un dato…"
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => setAbierto(false)}>
              Cancelar
            </Boton>
            <Boton onClick={reescribir} deshabilitado={enviando || !orden.trim()}>
              {enviando && <Loader2 className="animate-spin" />}
              Reescribir
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}

/* ----------------------------------------------------------------- 4 voz */

export function PanelVoz({
  pid,
  ficha,
  ocupado,
  seguirTrabajo,
  recargar,
}: PropsPanel) {
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin locución"
        detalle="Requiere guion aprobado (paso 3). Luego ejecuta el paso para narrarlo con ElevenLabs (voz de los parámetros)."
      />
    )
  const datos = ficha.datos as DatosVoz
  return (
    <div className="space-y-3">
      <ZonaElegirVoz
        pid={pid}
        ocupado={ocupado}
        params={ficha.params ?? {}}
        recargar={recargar}
      />
      <ZonaTonosCatalogo
        pid={pid}
        ocupado={ocupado}
        params={ficha.params ?? {}}
        recargar={recargar}
      />
      <ZonaPresetPaso pid={pid} tipo="voz" recargar={recargar} />
      <p className="text-sm text-muted-foreground">
        {datos.duracion ? segundos(datos.duracion) : "—"} de locución
      </p>
      {(datos.escenas ?? []).map((escena) => (
        <div
          key={escena.id}
          className="flex flex-col gap-2 rounded-md border bg-card p-3 sm:flex-row sm:items-center"
        >
          <div className="flex items-center gap-2 text-xs text-muted-foreground sm:w-28">
            <AudioLines className="h-4 w-4" />
            <span className="font-mono">{escena.id}</span>
            {escena.duracion != null && <span>{segundos(escena.duracion)}</span>}
          </div>
          <audio
            controls
            preload="none"
            src={`/a/${pid}/${escena.audio}`}
            className="h-8 min-w-0 flex-1"
          />
          <Boton
            variante="contorno"
            tamano="pequeno"
            deshabilitado={ocupado}
            onClick={async () => {
              try {
                const trabajo = await api.post<{ id: string }>(
                  `/api/proyectos/${pid}/voz/escenas/${escena.id}/regrabar`
                )
                seguirTrabajo(trabajo.id)
              } catch (e) {
                toast.error(String((e as Error).message ?? e))
              }
            }}
          >
            <RefreshCw /> Regrabar
          </Boton>
        </div>
      ))}
    </div>
  )
}

/** Elegir voz describiéndola + cata antes de pagar la grabación entera. */
function ZonaElegirVoz({
  pid,
  ocupado,
  params,
  recargar,
}: {
  pid: string
  ocupado: boolean
  params: Record<string, unknown>
  recargar: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [encargo, setEncargo] = useState("")
  const [tid, setTid] = useState<string | null>(null)
  const [propuesta, setPropuesta] = useState<PropuestaVoz | null>(null)
  const [cata, setCata] = useState<PrevisualizacionVoz | null>(null)
  const [pid_cata, setPidCata] = useState<string | null>(null)
  const [cata_corriendo, setCataCorriendo] = useState(false)

  const al_terminar = (final: TrabajoFicha) => {
    if (final.estado === "hecho" && final.paso === "voz") {
      const r = final.resultado
      if (r && typeof r === "object" && "voz_nombre" in r) {
        setPropuesta(r as PropuestaVoz)
        toast.success(`propuesta: ${(r as PropuestaVoz).voz_nombre}`)
      } else if (r && typeof r === "object" && "url" in r) {
        setCata(r as PrevisualizacionVoz)
        setCataCorriendo(false)
      }
    } else if (final.estado === "fallo") {
      toast.error(final.error || "el trabajo falló")
      setCataCorriendo(false)
    }
  }
  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar: al_terminar })
  const trabajando =
    !!tid && (trabajo?.estado === "en_cola" || trabajo?.estado === "ejecutando")

  const proponer = async () => {
    if (!encargo.trim()) return
    setPropuesta(null)
    setCata(null)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/voz/describir`,
        { encargo }
      )
      setTid(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const mandos_de = (p: PropuestaVoz) => ({
    voz: p.voz,
    modelo: p.modelo,
    estabilidad: p.estabilidad,
    similitud: p.similitud,
    velocidad: p.velocidad,
  })

  const previsualizar = async (mandos: Record<string, unknown>) => {
    setCataCorriendo(true)
    setCata(null)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/voz/previsualizar`,
        { params: mandos, segundos: 15 }
      )
      setPidCata(trabajo.id)
      setTid(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
      setCataCorriendo(false)
    }
  }

  const aplicar = async () => {
    if (!propuesta) return
    try {
      await api.put(`/api/proyectos/${pid}/pasos/voz/params`, {
        ...params,
        ...mandos_de(propuesta),
      })
      toast.success(
        `parámetros de voz rellenados (${propuesta.voz_nombre}): el paso queda obsoleto`,
      )
      setPropuesta(null)
      setAbierto(false)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <button
        className="flex w-full items-center gap-2 text-left text-sm font-medium"
        onClick={() => setAbierto((v) => !v)}
      >
        <AudioLines className="h-4 w-4" />
        Elegir voz describiéndola
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {abierto ? "ocultar" : "cata antes de pagar la grabación"}
        </span>
      </button>
      {abierto && (
        <div className="mt-3 space-y-3">
          <AreaTexto
            filas={3}
            valor={encargo}
            alCambiar={(e) => setEncargo(e.target.value)}
            placeholder="una voz cálida y cercana, hombre joven, ritmo tranquilo, estilo documental…"
          />
          <div className="flex flex-wrap gap-2">
            <Boton
              tamano="pequeno"
              deshabilitado={ocupado || trabajando || !encargo.trim()}
              onClick={proponer}
            >
              {trabajando ? (
                <Loader2 className="animate-spin" />
              ) : (
                <AudioLines />
              )}
              Proponer voz
            </Boton>
            <Boton
              variante="contorno"
              tamano="pequeno"
              deshabilitado={ocupado || cata_corriendo}
              title="Sintetiza ~15 s con los parámetros guardados (cuesta esos caracteres)"
              onClick={() => previsualizar(params)}
            >
              {cata_corriendo ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Play />
              )}
              Cata con los parámetros actuales
            </Boton>
          </div>

          {propuesta && (
            <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
              <p className="font-medium">
                {propuesta.voz_nombre}{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  ({propuesta.voz})
                </span>
              </p>
              {Object.keys(propuesta.voz_etiquetas ?? {}).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {Object.entries(propuesta.voz_etiquetas ?? {})
                    .filter(([, v]) => v)
                    .map(([k, v]) => `${k}: ${String(v)}`)
                    .join(" · ")}
                </p>
              )}
              {propuesta.motivo && (
                <p className="text-xs italic text-muted-foreground">
                  «{propuesta.motivo}»
                </p>
              )}
              <p className="font-mono text-xs text-muted-foreground">
                modelo {propuesta.modelo} · estabilidad{" "}
                {propuesta.estabilidad} · similitud {propuesta.similitud} ·
                velocidad {propuesta.velocidad}
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                <Boton tamano="pequeno" onClick={aplicar}>
                  Usar esta voz
                </Boton>
                <Boton
                  variante="contorno"
                  tamano="pequeno"
                  deshabilitado={cata_corriendo}
                  onClick={() => previsualizar(mandos_de(propuesta))}
                >
                  {pid_cata && cata_corriendo ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Play />
                  )}
                  Escuchar cata
                </Boton>
              </div>
            </div>
          )}

          {cata && (
            <div className="space-y-1 rounded-md border p-3">
              <p className="text-xs text-muted-foreground">
                cata de {cata.segundos} s · {cata.caracteres} caracteres ·
                suena con las primeras frases del guion
              </p>
              <audio
                controls
                preload="none"
                src={cata.url}
                className="h-8 w-full"
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** El catálogo de tonos: un desplegable que rellena los mandos. */
function ZonaTonosCatalogo({
  pid,
  ocupado,
  params,
  recargar,
}: {
  pid: string
  ocupado: boolean
  params: Record<string, unknown>
  recargar: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [tonos, setTonos] = useState<PresetVoz[] | null>(null)
  const [eleccion, setEleccion] = useState("")

  useEffect(() => {
    if (abierto && !tonos)
      api
        .get<PresetVoz[]>("/api/presets")
        .then(setTonos)
        .catch((e) => {
          toast.error(String(e.message ?? e))
          setTonos([])
        })
  }, [abierto, tonos])

  const ficha = tonos?.find((t) => t.id === eleccion)

  const aplicar = async () => {
    if (!ficha) return
    try {
      await api.put(`/api/proyectos/${pid}/pasos/voz/params`, {
        ...params,
        voz: ficha.voces_sugeridas?.[0],
        modelo: ficha.modelo,
        estabilidad: ficha.estabilidad,
        similitud: ficha.similitud,
        velocidad: ficha.velocidad,
      })
      toast.success(
        `tono «${ficha.nombre}» aplicado: regraba la locución para oírlo`,
      )
      setEleccion("")
      setAbierto(false)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <button
        className="flex w-full items-center gap-2 text-left text-sm font-medium"
        onClick={() => setAbierto((v) => !v)}
      >
        <AudioLines className="h-4 w-4" />
        Elegir un tono del catálogo
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {abierto ? "ocultar" : `${tonos?.length ?? 8} tonos con sus mandos`}
        </span>
      </button>
      {abierto && (
        <div className="mt-3 space-y-3">
          <Selector valor={eleccion} alCambiar={setEleccion}>
            <DisparadorSelector>
              <ValorSelector placeholder="un tono de locución…" />
            </DisparadorSelector>
            <ContenidoSelector>
              {(tonos ?? []).map((t) => (
                <Opcion key={t.id} valor={t.id}>
                  {t.nombre}
                  <span className="text-xs text-muted-foreground">
                    {" "}
                    · {t.voces_nombres?.[0] ?? ""}
                  </span>
                </Opcion>
              ))}
            </ContenidoSelector>
          </Selector>
          {ficha && (
            <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
              <p className="font-medium">{ficha.nombre}</p>
              {ficha.descripcion && (
                <p className="text-xs italic text-muted-foreground">
                  {ficha.descripcion}
                </p>
              )}
              <p className="font-mono text-xs text-muted-foreground">
                estabilidad {ficha.estabilidad} · similitud{" "}
                {ficha.similitud} · velocidad {ficha.velocidad}
              </p>
              <Boton
                tamano="pequeno"
                deshabilitado={ocupado}
                onClick={aplicar}
              >
                Aplicar tono
              </Boton>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ----------------------------------------------------- 5 revisión de voz */

export function PanelRevision({ ficha }: PropsPanel) {
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin revisión"
        detalle="Ejecuta el paso para medir duraciones, silencios y picos de cada audio."
      />
    )
  const datos = ficha.datos as DatosRevision
  return (
    <div className="space-y-3">
      {datos.estado === "ok" ? (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm">
          Todos los {datos.revisadas} audios pasan los umbrales.
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {datos.avisos?.length ?? 0} de {datos.revisadas} audios con avisos
            (ajusta los umbrales en Parámetros y vuelve a ejecutar).
          </p>
          <div className="space-y-2">
            {(datos.avisos ?? []).map((aviso) => (
              <div key={aviso.id} className="rounded-md border p-3 text-sm">
                <p className="font-mono text-xs text-muted-foreground">
                  {aviso.id}
                </p>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {aviso.problemas.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- 6 assets */

export function PanelAssets({
  pid,
  ficha,
  ocupado,
  seguirTrabajo,
  alEjecutar,
  recargar,
}: PropsPanel) {
  const [grafismo_abierto, setGrafismoAbierto] = useState(false)
  const [pestana_grafismo, setPestanaGrafismo] = useState<PestanaGrafismo>("direccion")
  const [estilo_abierto, setEstiloAbierto] = useState(false)
  const [pestana_estilo, setPestanaEstilo] = useState<PestanaEstiloVisual>("catalogo")
  const [conservar_abierto, setConservarAbierto] = useState(false)
  if (ficha.estado === "vacio")
    return (
      <div className="space-y-4">
        <Vacio
          titulo="Sin imágenes"
          detalle="Ejecuta el paso para generar un plano por escena del guion."
        />
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-muted-foreground">
            Antes de pagar la tanda: guía con números y moodboard aprobado.
          </p>
          <Boton
            variante="secundario"
            tamano="pequeno"
            onClick={() => setEstiloAbierto(true)}
            title="Catálogo visual, encuadres, guía de estilo y moodboard"
          >
            Estilo
          </Boton>
        </div>
        <ZonaPresetPaso pid={pid} tipo="estilo" recargar={recargar} />
        <DialogoEstiloVisual
          pid={pid}
          abierto={estilo_abierto}
          alCambiar={setEstiloAbierto}
          pestana={pestana_estilo}
          alPestana={setPestanaEstilo}
          recargar={recargar}
        />
      </div>
    )
  const datos = ficha.datos as DatosAssets
  const obsoletas = ficha.unidades_obsoletas ?? []
  const hay_obsoletas = obsoletas.length > 0
  const cartelas = (datos.planos ?? []).filter((p) => p.cartela).length

  return (
    <div className="space-y-4">
      <ZonaPresetPaso pid={pid} tipo="estilo" recargar={recargar} />
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          {datos.planos?.length ?? 0} planos · calidad {datos.calidad}
          {cartelas > 0 && ` · ${cartelas} cartela(s) de texto`}
        </p>
        <Boton
          variante="secundario"
          tamano="pequeno"
          onClick={() => setGrafismoAbierto(true)}
          title="Dirección, redactor, cartelas y diseño: qué se ve en cada plano"
        >
          <Palette /> Grafismo
        </Boton>
        <Boton
          variante="secundario"
          tamano="pequeno"
          onClick={() => setEstiloAbierto(true)}
          title="Catálogo visual, encuadres, guía de estilo y moodboard: el estilo del vídeo"
        >
          Estilo
        </Boton>
        <Boton
          variante="secundario"
          tamano="pequeno"
          onClick={() => setConservarAbierto(true)}
          title="Cuando el guion cambia: qué imágenes ya pagadas siguen valiendo"
        >
          Conservar
        </Boton>
        {hay_obsoletas && (
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={ocupado}
            onClick={() => alEjecutar(obsoletas)}
          >
            Regenerar solo {obsoletas.length} obsoleta(s)
          </Boton>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(datos.planos ?? []).map((plano) => {
          const obsoleto = obsoletas.includes(plano.escena)
          return (
            <div
              key={plano.escena}
              className={`overflow-hidden rounded-lg border ${
                obsoleto ? "ring-2 ring-amber-500" : ""
              }`}
            >
              {plano.cartela ? (
                <img
                  src={`/api/proyectos/${pid}/cartelas/vista?plano=${plano.escena}`}
                  alt={`cartela ${plano.escena}`}
                  title={`cartela ${plano.cartela.plantilla}`}
                  className="aspect-video w-full bg-muted object-cover"
                  onError={(e) =>
                    (e.currentTarget.style.visibility = "hidden")
                  }
                />
              ) : (
                <img
                  src={`/a/${pid}/${plano.imagen}`}
                  alt={plano.escena}
                  title={plano.prompt}
                  className="aspect-video w-full bg-muted object-cover"
                  onError={(e) =>
                    (e.currentTarget.style.visibility = "hidden")
                  }
                />
              )}
              <div className="flex items-center justify-between gap-2 p-2">
                <span className="font-mono text-xs text-muted-foreground">
                  {plano.escena}
                  {plano.cartela && " · cartela"}
                </span>
                <div className="flex items-center gap-1">
                  {obsoleto && (
                    <Boton
                      variante="fantasma"
                      tamano="pequeno"
                      deshabilitado={ocupado}
                      title="Este dibujo me vale para lo que dice ahora: retira la tarjeta (vuelve si cambia el texto)"
                      onClick={async () => {
                        try {
                          const r = await api.post<{ quedan: number }>(
                            `/api/proyectos/${pid}/escenas/${plano.escena}/vale`
                          )
                          toast.success(
                            r.quedan > 0
                              ? `quedan ${r.quedan} por revisar`
                              : "todas las imágenes revisadas",
                          )
                          recargar()
                        } catch (e) {
                          toast.error(String((e as Error).message ?? e))
                        }
                      }}
                    >
                      <Check /> Me vale
                    </Boton>
                  )}
                  <Boton
                    variante="fantasma"
                    tamano="pequeno"
                    deshabilitado={ocupado}
                    title="Regenerar (cuesta una imagen)"
                    onClick={async () => {
                      try {
                        const trabajo = await api.post<{ id: string }>(
                          `/api/proyectos/${pid}/assets/planos/${plano.escena}/regenerar`
                        )
                        seguirTrabajo(trabajo.id)
                      } catch (e) {
                        toast.error(String((e as Error).message ?? e))
                      }
                    }}
                  >
                    <RefreshCw /> Regenerar
                  </Boton>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <DialogoGrafismo
        pid={pid}
        abierto={grafismo_abierto}
        alCambiar={setGrafismoAbierto}
        pestana={pestana_grafismo}
        alPestana={setPestanaGrafismo}
        recargar={recargar}
      />
      <DialogoEstiloVisual
        pid={pid}
        abierto={estilo_abierto}
        alCambiar={setEstiloAbierto}
        pestana={pestana_estilo}
        alPestana={setPestanaEstilo}
        recargar={recargar}
      />
      <DialogoConservacion
        pid={pid}
        abierto={conservar_abierto}
        alCambiar={setConservarAbierto}
        recargar={recargar}
      />
    </div>
  )
}

/* ------------------------------------------------------------- 7 callouts */

export function PanelCallouts({ pid, ficha, recargar }: PropsPanel) {
  const [grafismo_abierto, setGrafismoAbierto] = useState(false)
  const [pestana_grafismo, setPestanaGrafismo] = useState<PestanaGrafismo>("diseno")
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin rótulos"
        detalle="Ejecuta el paso para decidir los textos en pantalla y su ritmo."
      />
    )
  const datos = ficha.datos as DatosCallouts
  return (
    <div className="space-y-2">
      <ZonaPresetPaso pid={pid} tipo="rotulos" recargar={recargar} />
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          {(datos.rotulos ?? []).length} rótulo(s)
          {datos.diseno && ` · diseño «${datos.diseno}»`}
        </p>
        <Boton
          variante="secundario"
          tamano="pequeno"
          onClick={() => setGrafismoAbierto(true)}
          title="Sets de diseño, paleta y tamaño: un grafismo para todo el vídeo"
        >
          <Palette /> Diseño
        </Boton>
      </div>
      {(datos.rotulos ?? []).length === 0 && (
        <p className="text-sm text-muted-foreground">
          El paso decidió no poner rótulos.
        </p>
      )}
      {(datos.rotulos ?? []).map((r) => (
        <div
          key={r.id}
          className="flex items-center gap-3 rounded-md border bg-card px-3 py-2 text-sm"
        >
          <Insignia variante="secundario">{r.id}</Insignia>
          <span className="font-medium">«{r.texto}»</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {r.aparece.toFixed(1)}s → +{r.dura.toFixed(1)}s
          </span>
          <img
            src={`/api/proyectos/${pid}/callouts/vista?plano=${r.id}`}
            alt={`rótulo ${r.id}`}
            className="h-8 rounded bg-muted"
            title="cómo se dibuja este rótulo"
            onError={(e) => (e.currentTarget.style.display = "none")}
          />
        </div>
      ))}
      <DialogoGrafismo
        pid={pid}
        abierto={grafismo_abierto}
        alCambiar={setGrafismoAbierto}
        pestana={pestana_grafismo}
        alPestana={setPestanaGrafismo}
        recargar={recargar}
      />
    </div>
  )
}

/* --------------------------------------------------------------- 8 render */

export function PanelRender({ pid, ficha, recargar }: PropsPanel) {
  const [sonido_abierto, setSonidoAbierto] = useState(false)
  const [pestana_sonido, setPestanaSonido] = useState<PestanaSonido>("musica")
  const [transiciones_abierto, setTransicionesAbierto] = useState(false)

  const botones = (
    <>
      <Boton
        variante="secundario"
        tamano="pequeno"
        onClick={() => setSonidoAbierto(true)}
        title="Música por tono, banda por tramos, efectos por papel y sus niveles"
      >
        <AudioLines /> Sonido
      </Boton>
      <Boton
        variante="secundario"
        tamano="pequeno"
        onClick={() => setTransicionesAbierto(true)}
        title="Catálogo de transiciones con el efecto que correrá el render"
      >
        <Film /> Transiciones
      </Boton>
    </>
  )
  const dialogos = (
    <>
      <DialogoSonido
        pid={pid}
        abierto={sonido_abierto}
        alCambiar={setSonidoAbierto}
        pestana={pestana_sonido}
        alPestana={setPestanaSonido}
        recargar={recargar}
      />
      <DialogoTransiciones
        pid={pid}
        abierto={transiciones_abierto}
        alCambiar={setTransicionesAbierto}
        recargar={recargar}
      />
    </>
  )

  if (ficha.estado === "vacio")
    return (
      <div className="space-y-4">
        <Vacio
          titulo="Sin vídeo"
          detalle="Necesitas audio revisado, imágenes y rótulos; luego ejecuta el montaje."
        />
        <div className="flex flex-wrap items-center gap-2">{botones}</div>
        {dialogos}
      </div>
    )
  const datos = ficha.datos as DatosRender
  const url = `/a/${pid}/${datos.video}`
  return (
    <div className="space-y-4">
      <video
        controls
        preload="metadata"
        src={url}
        className="w-full rounded-lg border bg-black"
      />
      <div className="flex flex-wrap gap-2 text-xs">
        <Insignia variante="secundario">{segundos(datos.duracion)}</Insignia>
        <Insignia variante="secundario">{datos.resolucion}</Insignia>
        <Insignia variante="secundario">{datos.fps} fps</Insignia>
        <Insignia variante="secundario">{datos.escenas} escenas</Insignia>
        {datos.masterizado && <Insignia variante="exito">masterizado</Insignia>}
        {datos.sonido && datos.sonido !== "voz" && (
          <Insignia variante="secundario">{datos.sonido}</Insignia>
        )}
        {datos.transiciones && (
          <Insignia variante="secundario">{datos.transiciones}</Insignia>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <a href={url} download>
          <Boton variante="contorno" tamano="pequeno">
            Descargar mp4
          </Boton>
        </a>
        {botones}
      </div>
      {dialogos}
    </div>
  )
}
