/** Paneles de contenido para cada paso del pipeline. */
import { useState } from "react"
import { toast } from "sonner"
import { AudioLines, BadgeCheck, Loader2, PenLine, RefreshCw } from "lucide-react"
import { api } from "../../lib/api"
import { segundos } from "../../lib/utils"
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
import { Vacio } from "./piezas"

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

export function PanelBrief({ ficha }: PropsPanel) {
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
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin guion"
        detalle="Necesitas un brief al día; luego ejecuta el paso para escribir las escenas."
      />
    )
  const datos = ficha.datos as DatosGuion
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
      <p className="text-sm text-muted-foreground">
        {datos.escenas?.length ?? 0} escenas ·{" "}
        {segundos(datos.duracion_estimada ?? 0)} estimados
      </p>
      {(datos.escenas ?? []).map((escena) => (
        <Tarjeta key={escena.id}>
          <ContenidoTarjeta className="space-y-2 p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-mono text-xs text-muted-foreground">
                  {escena.id}
                </p>
                <p className="font-medium">{escena.titulo}</p>
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

export function PanelVoz({ pid, ficha, ocupado, seguirTrabajo }: PropsPanel) {
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
}: PropsPanel) {
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin imágenes"
        detalle="Ejecuta el paso para generar un plano por escena del guion."
      />
    )
  const datos = ficha.datos as DatosAssets
  const obsoletas = ficha.unidades_obsoletas ?? []
  const hay_obsoletas = obsoletas.length > 0

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          {datos.planos?.length ?? 0} planos · calidad {datos.calidad}
        </p>
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
              <img
                src={`/a/${pid}/${plano.imagen}`}
                alt={plano.escena}
                title={plano.prompt}
                className="aspect-video w-full bg-muted object-cover"
                onError={(e) =>
                  (e.currentTarget.style.visibility = "hidden")
                }
              />
              <div className="flex items-center justify-between gap-2 p-2">
                <span className="font-mono text-xs text-muted-foreground">
                  {plano.escena}
                </span>
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
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- 7 callouts */

export function PanelCallouts({ ficha }: PropsPanel) {
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
        </div>
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- 8 render */

export function PanelRender({ pid, ficha }: PropsPanel) {
  if (ficha.estado === "vacio")
    return (
      <Vacio
        titulo="Sin vídeo"
        detalle="Necesitas audio revisado, imágenes y rótulos; luego ejecuta el montaje."
      />
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
      </div>
      <a href={url} download>
        <Boton variante="contorno" tamano="pequeno">
          Descargar mp4
        </Boton>
      </a>
    </div>
  )
}
