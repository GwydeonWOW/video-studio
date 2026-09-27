/** Piezas compartidas por los paneles de paso. */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { History, Loader2, RotateCcw, Save } from "lucide-react"
import { api } from "../../lib/api"
import type { EstadoPaso, VersionPaso } from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { Insignia } from "../../components/ui/badge"
import { Entrada } from "../../components/ui/input"
import { Etiqueta } from "../../components/ui/etiqueta"
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

export function PildoraEstado({ estado }: { estado: EstadoPaso }) {
  if (estado === "ok") return <Insignia variante="exito">al día</Insignia>
  if (estado === "obsoleto") return <Insignia variante="aviso">obsoleto</Insignia>
  return <Insignia variante="secundario">vacío</Insignia>
}

export function Vacio({
  titulo,
  detalle,
}: {
  titulo: string
  detalle?: string
}) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed py-14 text-center">
      <p className="font-medium">{titulo}</p>
      {detalle && (
        <p className="max-w-md text-sm text-muted-foreground">{detalle}</p>
      )}
    </div>
  )
}

/* ----------------------------------------------------------- estimación */

interface EstimacionPaso {
  llamadas_llm: number | string
  imagenes: number | string
  caracteres_voz: number | string
  coste: number | null
}

export function Estimacion({ pid, paso }: { pid: string; paso: string }) {
  const [est, setEst] = useState<EstimacionPaso | null>(null)
  useEffect(() => {
    api
      .get<EstimacionPaso>(`/api/proyectos/${pid}/pasos/${paso}/estimacion`)
      .then(setEst)
      .catch(() => setEst(null))
  }, [pid, paso])
  if (!est) return null
  return (
    <p className="text-xs text-muted-foreground">
      ≈ {est.llamadas_llm} llamadas LLM · {est.imagenes} imágenes ·{" "}
      {est.caracteres_voz} caracteres de voz
    </p>
  )
}

/* -------------------------------------------------------- params editor */

interface DescriptorCampo {
  clave: string
  etiqueta: string
  tipo: "numero" | "texto" | "selector"
  opciones?: string[]
  paso?: number
  min?: number
  max?: number
  ayuda?: string
}

const CAMPOS: Record<string, DescriptorCampo[]> = {
  brief: [],
  guion: [
    { clave: "escenas", etiqueta: "Escenas", tipo: "numero", min: 1, max: 30 },
  ],
  voz: [
    { clave: "voz", etiqueta: "Voz (id ElevenLabs)", tipo: "texto" },
    {
      clave: "modelo",
      etiqueta: "Modelo",
      tipo: "selector",
      opciones: ["multilingual", "turbo", "flash"],
    },
    {
      clave: "estabilidad",
      etiqueta: "Estabilidad",
      tipo: "numero",
      paso: 0.05,
      min: 0,
      max: 1,
    },
    {
      clave: "similitud",
      etiqueta: "Similitud",
      tipo: "numero",
      paso: 0.05,
      min: 0,
      max: 1,
    },
    {
      clave: "velocidad",
      etiqueta: "Velocidad",
      tipo: "numero",
      paso: 0.05,
      min: 0.7,
      max: 1.2,
    },
  ],
  revision_audio: [
    {
      clave: "tope_desviacion",
      etiqueta: "Tope de desvío (s)",
      tipo: "numero",
      paso: 0.05,
      min: 0,
    },
    {
      clave: "pico_minimo_db",
      etiqueta: "Pico mínimo (dB)",
      tipo: "numero",
      min: -60,
      max: 0,
    },
  ],
  assets: [
    {
      clave: "calidad",
      etiqueta: "Calidad",
      tipo: "selector",
      opciones: ["low", "medium", "high"],
    },
    { clave: "estilo", etiqueta: "Estilo (sufijo de prompt)", tipo: "texto" },
  ],
  callouts: [
    {
      clave: "duracion_max",
      etiqueta: "Duración máxima (s)",
      tipo: "numero",
      paso: 0.5,
      min: 0.5,
    },
  ],
  render: [
    {
      clave: "calidad",
      etiqueta: "Calidad",
      tipo: "selector",
      opciones: ["borrador", "estandar", "detalle"],
    },
    {
      clave: "resolucion",
      etiqueta: "Resolución",
      tipo: "selector",
      opciones: ["1920x1080"],
    },
    { clave: "fps", etiqueta: "FPS", tipo: "numero", min: 10, max: 60 },
  ],
}

export function EditorParams({
  pid,
  paso,
  params,
  alGuardar,
}: {
  pid: string
  paso: string
  params: Record<string, unknown>
  alGuardar: () => void
}) {
  const campos = CAMPOS[paso] ?? []
  const [valores, setValores] = useState<Record<string, string>>({})
  const [abierto, setAbierto] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const clave = `${paso}:${JSON.stringify(params)}`

  // sincroniza el estado local cuando cambian los params del servidor
  useEffect(() => {
    const iniciales: Record<string, string> = {}
    for (const c of campos) {
      iniciales[c.clave] = String(params[c.clave] ?? "")
    }
    setValores(iniciales)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave])

  if (campos.length === 0) return null

  const guardar = async () => {
    setEnviando(true)
    try {
      const cuerpo: Record<string, unknown> = { ...params }
      for (const c of campos) {
        const bruto = (valores[c.clave] ?? "").trim()
        if (bruto === "") continue
        cuerpo[c.clave] =
          c.tipo === "numero" ? Number(bruto.replace(",", ".")) : bruto
      }
      const r = await api.put<{ obsoletos_al_regenerar: string[] }>(
        `/api/proyectos/${pid}/pasos/${paso}/params`,
        cuerpo
      )
      if (r.obsoletos_al_regenerar.length > 0) {
        toast.warning(
          `guardado; al regenerar quedarán obsoletos: ${r.obsoletos_al_regenerar.join(", ")}`
        )
      } else {
        toast.success("parámetros guardados")
      }
      setAbierto(false)
      alGuardar()
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
        onClick={() => setAbierto(true)}
      >
        Parámetros
      </Boton>
      <Dialogo abierto={abierto} alCambiar={setAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Parámetros · {paso}</TituloDialogo>
            <DescripcionDialogo>
              Cambiar parámetros marca este paso como obsoleto (no lo de abajo).
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="grid gap-4 sm:grid-cols-2">
            {campos.map((c) => (
              <div key={c.clave} className="space-y-2">
                <Etiqueta>{c.etiqueta}</Etiqueta>
                {c.tipo === "selector" ? (
                  <Selector
                    valor={valores[c.clave]}
                    alCambiar={(v) =>
                      setValores((prev) => ({ ...prev, [c.clave]: v }))
                    }
                  >
                    <DisparadorSelector>
                      <ValorSelector />
                    </DisparadorSelector>
                    <ContenidoSelector>
                      {c.opciones!.map((o) => (
                        <Opcion key={o} valor={o}>
                          {o}
                        </Opcion>
                      ))}
                    </ContenidoSelector>
                  </Selector>
                ) : (
                  <Entrada
                    tipo={c.tipo === "numero" ? "number" : "text"}
                    paso={c.paso}
                    min={c.min}
                    max={c.max}
                    valor={valores[c.clave] ?? ""}
                    alCambiar={(e) =>
                      setValores((prev) => ({
                        ...prev,
                        [c.clave]: e.target.value,
                      }))
                    }
                  />
                )}
                {c.ayuda && (
                  <p className="text-xs text-muted-foreground">{c.ayuda}</p>
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => setAbierto(false)}>
              Cancelar
            </Boton>
            <Boton onClick={guardar} deshabilitado={enviando}>
              {enviando ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Save />
              )}
              Guardar
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}

/* ------------------------------------------------------------- versiones */

export function ZonaVersiones({
  pid,
  paso,
  version,
  alRevertir,
}: {
  pid: string
  paso: string
  version: number
  alRevertir: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [lista, setLista] = useState<VersionPaso[] | null>(null)
  const [revertida, setRevertida] = useState<number | null>(null)

  useEffect(() => {
    if (!abierto) return
    api
      .get<VersionPaso[]>(`/api/proyectos/${pid}/pasos/${paso}/versiones`)
      .then((v) => setLista([...v].reverse()))
      .catch(() => setLista([]))
  }, [pid, paso, abierto])

  const revertir = async (v: number) => {
    setRevertida(v)
    try {
      await api.post(`/api/proyectos/${pid}/pasos/${paso}/revertir`, {
        version: v,
      })
      toast.success(`revertido a la v${v}`)
      setAbierto(false)
      alRevertir()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setRevertida(null)
    }
  }

  return (
    <>
      <Boton
        variante="fantasma"
        tamano="pequeno"
        onClick={() => setAbierto(true)}
      >
        <History /> Versiones
      </Boton>
      <Dialogo abierto={abierto} alCambiar={setAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Versiones · {paso}</TituloDialogo>
            <DescripcionDialogo>
              Revertir restaura los datos y los parámetros de esa versión.
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="max-h-96 space-y-2 overflow-y-auto">
            {!lista ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : lista.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                sin versiones todavía
              </p>
            ) : (
              lista.map((v) => (
                <div
                  key={v.version}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      v{v.version}
                      {v.version === version && (
                        <Insignia variante="secundario" className="ml-2">
                          actual
                        </Insignia>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {v.fecha} · {v.resumen}
                    </p>
                  </div>
                  <Boton
                    variante="contorno"
                    tamano="pequeno"
                    deshabilitado={v.version === version || revertida !== null}
                    onClick={() => revertir(v.version)}
                  >
                    {revertida === v.version ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <RotateCcw />
                    )}
                    Revertir
                  </Boton>
                </div>
              ))
            )}
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}
