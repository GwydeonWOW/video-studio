/**
 * La zona de presets de canal de cada pantalla del editor.
 *
 * Guardar los params del paso como preset (guion, estilo, rotulos o voz)
 * y aplicar los guardados al proyecto. Es la misma tabla de claves que
 * usa el backend en `cambios_para`: lo que aquí se guarda es exactamente
 * lo que aplicar escribe.
 */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { BookmarkPlus, FolderDown, Loader2 } from "lucide-react"
import { api } from "../../lib/api"
import {
  type FichaPasos,
  type PresetCanal,
  type ResultadoAplicar,
  type TipoPreset,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { Entrada } from "../../components/ui/input"
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

/** Qué claves mira cada tipo y en qué paso viven (espejo de cambios_para). */
const TABLA: Record<
  Exclude<TipoPreset, "canal">,
  {
    nombre: string
    ayuda: string
    pasos: string[]
    claves: Record<string, string[]>
  }
> = {
  guion: {
    nombre: "guión",
    ayuda: "tono, idioma y cadencia de las escenas",
    pasos: ["brief", "guion"],
    claves: {
      brief: ["tono", "idioma", "ritmo_min", "ritmo_max"],
      guion: ["tono", "idioma", "escenas"],
    },
  },
  estilo: {
    nombre: "estilo visual",
    ayuda: "estilo, guía y calidad de las imágenes",
    pasos: ["assets"],
    claves: { assets: ["estilo", "guia", "calidad", "moodboard"] },
  },
  rotulos: {
    nombre: "rótulos",
    ayuda: "diseño, subtítulos y paleta fijada",
    pasos: ["callouts"],
    claves: { callouts: ["diseno", "paleta", "subtitulo_tam"] },
  },
  voz: {
    nombre: "voz",
    ayuda: "voz, modelo y mandos de locución",
    pasos: ["voz"],
    claves: {
      voz: ["voz", "voz_nombre", "modelo", "estabilidad", "similitud",
        "velocidad"],
    },
  },
}

function datos_de(pasos: FichaPasos, tipo: Exclude<TipoPreset, "canal">) {
  const datos: Record<string, unknown> = {}
  for (const [paso, claves] of Object.entries(TABLA[tipo].claves)) {
    const params = pasos.pasos[paso]?.params ?? {}
    for (const clave of claves)
      if (params[clave] !== undefined && params[clave] !== "")
        datos[clave] = params[clave]
  }
  return datos
}

export function ZonaPresetPaso({
  pid,
  tipo,
  recargar,
}: {
  pid: string
  tipo: Exclude<TipoPreset, "canal">
  recargar: () => void
}) {
  const info = TABLA[tipo]
  const [abierto, setAbierto] = useState(false)
  const [presets, setPresets] = useState<PresetCanal[] | null>(null)
  const [eleccion, setEleccion] = useState("")
  const [guardar_abierto, setGuardarAbierto] = useState(false)
  const [nombre, setNombre] = useState("")
  const [nota, setNota] = useState("")
  const [datos, setDatos] = useState<Record<string, unknown>>({})
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    if (!abierto || presets) return
    api
      .get<{ presets: Record<string, PresetCanal[]> }>("/api/presets-canal")
      .then((f) => setPresets(f.presets[tipo] ?? []))
      .catch((e) => {
        toast.error(String(e.message ?? e))
        setPresets([])
      })
  }, [abierto, presets, tipo])

  useEffect(() => {
    if (!guardar_abierto) return
    api
      .get<FichaPasos>(`/api/proyectos/${pid}/pasos`)
      .then((f) => setDatos(datos_de(f, tipo)))
      .catch((e) => toast.error(String(e.message ?? e)))
  }, [guardar_abierto, pid, tipo])

  const elegido = presets?.find((p) => p.id === eleccion)

  const aplicar = async () => {
    if (!elegido) return
    setOcupado(true)
    try {
      const r = await api.post<ResultadoAplicar>(
        `/api/presets-canal/${elegido.id}/aplicar`,
        { proyecto: pid },
      )
      toast.success(
        `preset aplicado a ${Object.keys(r.cambios || {}).join(", ") || "nada"}: los pasos quedan obsoletos`,
      )
      setEleccion("")
      setAbierto(false)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setOcupado(false)
    }
  }

  const guardar = async () => {
    const limpio = nombre.trim()
    if (!limpio) return
    setOcupado(true)
    try {
      await api.post("/api/presets-canal", {
        tipo,
        nombre: limpio,
        nota: nota.trim(),
        datos,
      })
      toast.success(`preset de ${info.nombre} guardado`)
      setGuardarAbierto(false)
      setNombre("")
      setNota("")
      setPresets(null)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setOcupado(false)
    }
  }

  const claves_guardadas = Object.keys(datos)

  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <button
        className="flex w-full items-center gap-2 text-left text-sm font-medium"
        onClick={() => setAbierto((v) => !v)}
      >
        <BookmarkPlus className="h-4 w-4" />
        Presets de {info.nombre} del canal
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {abierto ? "ocultar" : info.ayuda}
        </span>
      </button>
      {abierto && (
        <div className="mt-3 space-y-3">
          <Selector valor={eleccion} alCambiar={setEleccion}>
            <DisparadorSelector>
              <ValorSelector placeholder="un preset guardado…" />
            </DisparadorSelector>
            <ContenidoSelector>
              {(presets ?? []).map((p) => (
                <Opcion key={p.id} valor={p.id}>
                  {p.nombre}
                  {p.resumen && (
                    <span className="text-xs text-muted-foreground">
                      {" "}
                      · {p.resumen.slice(0, 60)}
                    </span>
                  )}
                </Opcion>
              ))}
            </ContenidoSelector>
          </Selector>
          {elegido && (
            <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
              <p className="font-medium">{elegido.nombre}</p>
              {elegido.nota && (
                <p className="text-xs italic text-muted-foreground">
                  {elegido.nota}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {elegido.vinetas?.map((v) => `${v.icono} ${v.texto}`).join(" · ")}
              </p>
              <Boton
                tamano="pequeno"
                deshabilitado={ocupado}
                onClick={aplicar}
              >
                <FolderDown /> Aplicar al proyecto
              </Boton>
            </div>
          )}
          <Boton
            variante="contorno"
            tamano="pequeno"
            onClick={() => setGuardarAbierto(true)}
          >
            <BookmarkPlus /> Guardar esto como preset
          </Boton>
        </div>
      )}

      <Dialogo abierto={guardar_abierto} alCambiar={setGuardarAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Guardar preset de {info.nombre}</TituloDialogo>
            <DescripcionDialogo>
              {claves_guardadas.length > 0
                ? `Guarda: ${claves_guardadas.join(", ")}.`
                : `No hay nada que guardar aún en este paso.`}
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="space-y-3">
            <Entrada
              valor={nombre}
              alCambiar={(e) => setNombre(e.target.value)}
              placeholder="nombre del preset"
            />
            <Entrada
              valor={nota}
              alCambiar={(e) => setNota(e.target.value)}
              placeholder="nota (opcional): para qué es"
            />
            <div className="flex justify-end gap-2">
              <Boton
                variante="fantasma"
                onClick={() => setGuardarAbierto(false)}
              >
                Cancelar
              </Boton>
              <Boton
                deshabilitado={
                  ocupado || !nombre.trim() || claves_guardadas.length === 0
                }
                onClick={guardar}
              >
                {ocupado ? <Loader2 className="animate-spin" /> : null}
                Guardar
              </Boton>
            </div>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </div>
  )
}
