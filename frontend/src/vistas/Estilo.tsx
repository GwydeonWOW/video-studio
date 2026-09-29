/** Estilo del canal: lo que se decide UNA vez y hereda cada vídeo nuevo. */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Loader2, Palette, Save } from "lucide-react"
import { api } from "../lib/api"
import type { EstiloCanal, Voz } from "../lib/tipos"
import { KitVisual, subir_imagenes } from "../components/kit_visual"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import { AreaTexto } from "../components/ui/textarea"
import { Tarjeta, ContenidoTarjeta } from "../components/ui/tarjeta"
import {
  Selector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
  ValorSelector,
} from "../components/ui/selector"

const VACIO: EstiloCanal = {
  definido: false,
  nombre: "",
  idioma: "es",
  estilo_grafico: "",
  tono: "",
  ritmo_min: 20,
  ritmo_max: 40,
  voz: "",
  velocidad: 1.0,
  actualizado: "",
  kit: [],
}

const TOPE_KIT = 24

export default function Estilo() {
  const [estilo, setEstilo] = useState<EstiloCanal | null>(null)
  const [voces, setVoces] = useState<Voz[]>([])
  const [guardando, setGuardando] = useState(false)
  const [subiendoKit, setSubiendoKit] = useState(false)

  useEffect(() => {
    api
      .get<EstiloCanal>("/api/estilo")
      .then(setEstilo)
      .catch(() => {
        toast.error("no se pudo leer el estilo del canal")
        setEstilo(VACIO)
      })
    api
      .get<Voz[]>("/api/voces")
      .then(setVoces)
      .catch(() => setVoces([]))
  }, [])

  const poner = (campo: keyof EstiloCanal, valor: string | number) =>
    setEstilo((prev) => (prev ? { ...prev, [campo]: valor } : prev))

  /* el kit visual: sube al CANON del canal (persiste, no es buzón) y
     cada vídeo nuevo lo hereda sembrado */
  const al_elegir_kit = async (ficheros: FileList | File[]) => {
    if (!estilo) return
    setSubiendoKit(true)
    try {
      const r = await subir_imagenes(
        "/api/estilo/imagenes",
        ficheros,
        estilo.kit.length,
        TOPE_KIT,
      )
      if (r.imagenes.length) toast.success("imágenes añadidas al kit del canal")
      r.avisos.forEach((a) => toast.warning(a))
      const nuevo = await api.get<EstiloCanal>("/api/estilo")
      setEstilo(nuevo)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setSubiendoKit(false)
    }
  }

  const quitar_del_kit = async (nombre: string) => {
    try {
      await api.borrar(`/api/estilo/imagenes/${nombre}`)
    } catch {
      /* si ya no está, fuera igualmente */
    }
    setEstilo((prev) =>
      prev ? { ...prev, kit: prev.kit.filter((n) => n !== nombre) } : prev,
    )
  }

  const guardar = async () => {
    if (!estilo) return
    setGuardando(true)
    try {
      const nuevo = await api.put<EstiloCanal>("/api/estilo", estilo)
      setEstilo(nuevo)
      toast.success("estilo del canal guardado: los vídeos NUEVOS lo heredan")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  if (!estilo)
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight">
          Estilo del canal
        </h1>
        {estilo.definido ? (
          <Insignia variante="exito">definido</Insignia>
        ) : (
          <Insignia variante="destructivo">sin definir</Insignia>
        )}
      </div>

      {!estilo.definido && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
          Esto es lo PRIMERO: todos los vídeos del canal siguen esta línea.
          Defínela antes de crear proyectos — cada vídeo nuevo arranca con
          estos valores ya sembrados.
        </div>
      )}

      <Tarjeta>
        <ContenidoTarjeta className="space-y-5 p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Etiqueta>Nombre del canal</Etiqueta>
              <Entrada
                valor={estilo.nombre}
                alCambiar={(e) => poner("nombre", e.target.value)}
                placeholder="p. ej. Historias de la ciencia"
              />
            </div>
            <div className="space-y-2">
              <Etiqueta>Idioma de la narración</Etiqueta>
              <Selector
                valor={estilo.idioma}
                alCambiar={(v) => poner("idioma", v)}
              >
                <DisparadorSelector>
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  <Opcion valor="es">Español</Opcion>
                  <Opcion valor="en">Inglés</Opcion>
                </ContenidoSelector>
              </Selector>
            </div>
          </div>

          <div className="space-y-2">
            <Etiqueta>Tono del guion</Etiqueta>
            <AreaTexto
              filas={3}
              valor={estilo.tono}
              alCambiar={(e) => poner("tono", e.target.value)}
              placeholder="Cómo se narra: registro, humor, muletillas fuera… (se lo dice al brief y al guion)"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Etiqueta>Ritmo: segundos por escena (mín)</Etiqueta>
              <Entrada
                tipo="number"
                min="5"
                max="120"
                valor={String(estilo.ritmo_min)}
                alCambiar={(e) => poner("ritmo_min", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Etiqueta>Segundos por escena (máx)</Etiqueta>
              <Entrada
                tipo="number"
                min="5"
                max="180"
                valor={String(estilo.ritmo_max)}
                alCambiar={(e) => poner("ritmo_max", e.target.value)}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            La cadencia de los cortes: cuánto dura de media una escena. Llega
            al brief como duración objetivo por escena.
          </p>

          <div className="space-y-2">
            <Etiqueta>
              <Palette className="mr-1 inline h-3 w-3" />
              Estilo gráfico
            </Etiqueta>
            <AreaTexto
              filas={4}
              valor={estilo.estilo_grafico}
              alCambiar={(e) => poner("estilo_grafico", e.target.value)}
              placeholder="Cómo se dibuja: paleta, técnica, encuadres, luz… (entra en cada prompt de imagen)"
            />
          </div>

          <div className="space-y-2">
            <Etiqueta>
              <Palette className="mr-1 inline h-3 w-3" />
              Kit visual del canal
            </Etiqueta>
            <KitVisual
              imagenes={estilo.kit.map((nombre) => ({ nombre }))}
              url={(n) => `/api/estilo/imagenes/${n}`}
              tope={TOPE_KIT}
              subiendo={subiendoKit}
              alElegir={al_elegir_kit}
              alQuitar={quitar_del_kit}
            />
            <p className="text-xs text-muted-foreground">
              Tus imágenes de referencia. La guía de estilo de cada vídeo
              nuevo se escribe MIRÁNDOLO: esto es el material, y lo escrito
              arriba son indicaciones que mandan sobre lo que se vea.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Etiqueta>Voz del canal</Etiqueta>
              <Selector
                valor={estilo.voz}
                alCambiar={(v) => poner("voz", v)}
              >
                <DisparadorSelector>
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  <Opcion valor="">La del paso Voz (defecto)</Opcion>
                  {voces.map((v) => (
                    <Opcion key={v.voice_id} valor={v.voice_id}>
                      {v.nombre}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
            <div className="space-y-2">
              <Etiqueta>Velocidad de la voz</Etiqueta>
              <Entrada
                tipo="number"
                paso="0.05"
                min="0.7"
                max="1.2"
                valor={String(estilo.velocidad)}
                alCambiar={(e) => poner("velocidad", e.target.value)}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Boton onClick={guardar} deshabilitado={guardando}>
              {guardando ? <Loader2 className="animate-spin" /> : <Save />}
              Guardar estilo
            </Boton>
            {estilo.actualizado && (
              <span className="text-xs text-muted-foreground">
                actualizado {estilo.actualizado.slice(0, 16).replace("T", " ")}
              </span>
            )}
          </div>
        </ContenidoTarjeta>
      </Tarjeta>

      <p className="text-sm text-muted-foreground">
        Guardar aquí NO toca los proyectos que ya existen: los vídeos nuevos
        arrancan con estos valores sembrados, y a un proyecto en marcha se le
        reaplica a mano desde su cabecera («Aplicar estilo del canal»).
      </p>
    </div>
  )
}
