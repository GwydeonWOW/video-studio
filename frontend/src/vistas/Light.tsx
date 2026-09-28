/**
 * El modo light: el canal de una tirada.
 *
 * «Tu estilo en cuatro campos. No hay pestañas, no hay pasos»: se
 * describe el estilo, el tono y la voz en lenguaje normal, se ve el
 * plan (tareas, segundos, láminas y coste) y al pulsar el estudio
 * monta el canal entero y lo congela como un preset de canal.
 */
import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import {
  AlertTriangle,
  Copy,
  Loader2,
  Music,
  Play,
  RefreshCw,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react"
import { api } from "../lib/api"
import { dolares, segundos } from "../lib/utils"
import { usarTrabajo } from "../lib/trabajos"
import {
  type EncargoLight,
  type FichaPresetLight,
  type FichaPresetsLight,
  type PlanLight,
  type PresetCanal,
  type TrabajoFicha,
} from "../lib/tipos"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import { AreaTexto } from "../components/ui/textarea"
import {
  Tarjeta,
  CabeceraTarjeta,
  TituloTarjeta,
  ContenidoTarjeta,
  PieTarjeta,
} from "../components/ui/tarjeta"
import {
  Dialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
} from "../components/ui/dialogo"
import {
  Selector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
  ValorSelector,
} from "../components/ui/selector"

const PARTES: { id: "estilo" | "tono" | "voz"; nombre: string; ayuda: string }[] = [
  { id: "estilo", nombre: "Estilo", ayuda: "el look de las imágenes" },
  { id: "tono", nombre: "Tono", ayuda: "cómo suena la escritura" },
  { id: "voz", nombre: "Voz", ayuda: "la voz de la locución" },
]

const encargo_vacio = (ritmo: string): EncargoLight => ({
  nombre: "",
  estilo_prompt: "",
  tono_prompt: "",
  voz_prompt: "",
  idioma: "es",
  ritmo,
})

export default function Light({ alCambiar }: { alCambiar?: () => void }) {
  const [ficha, setFicha] = useState<FichaPresetsLight | null>(null)
  const [encargo, setEncargo] = useState<EncargoLight | null>(null)
  const [plan, setPlan] = useState<PlanLight | null>(null)
  const [creando_tid, setCreandoTid] = useState<string | null>(null)
  const [detalle, setDetalle] = useState<PresetCanal | null>(null)
  const timer_plan = useRef<number | null>(null)

  const cargar = useCallback(() => {
    api
      .get<FichaPresetsLight>("/api/presets-light")
      .then((f) => {
        setFicha(f)
        setEncargo((previo) => previo ?? encargo_vacio(f.ritmo_defecto))
      })
      .catch((e) => toast.error(String(e.message ?? e)))
  }, [])

  useEffect(cargar, [cargar])

  /* el plan se recalcula al cambiar el encargo, sin martillar la API */
  useEffect(() => {
    if (!encargo) return
    if (timer_plan.current) window.clearTimeout(timer_plan.current)
    timer_plan.current = window.setTimeout(() => {
      api
        .post<PlanLight>("/api/presets-light/plan", { encargo })
        .then(setPlan)
        .catch(() => setPlan(null))
    }, 400)
    return () => {
      if (timer_plan.current) window.clearTimeout(timer_plan.current)
    }
  }, [encargo])

  const al_terminar_creacion = (final: TrabajoFicha) => {
    if (final.estado === "hecho") {
      toast.success("canal congelado: ya está en la galería de abajo")
      setCreandoTid(null)
      setEncargo((e) => (e ? { ...e, nombre: "" } : e))
      cargar()
      alCambiar?.()
    } else if (final.estado === "fallo" || final.estado === "cancelado") {
      toast.error(final.error || "la generación del canal falló")
      setCreandoTid(null)
    }
  }
  const { ficha: trabajo_creacion } = usarTrabajo({
    tid: creando_tid,
    alTerminar: al_terminar_creacion,
  })

  const crear = async () => {
    if (!encargo) return
    try {
      const r = await api.post<{ trabajo: TrabajoFicha }>("/api/presets-light", {
        encargo,
      })
      setCreandoTid(r.trabajo.id)
      toast.success("taller en marcha: el canal se monta solo")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  if (!ficha || !encargo)
    return (
      <div className="flex justify-center py-20 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  const ritmo =
    ficha.ritmos.find((r) => r.id === encargo.ritmo) ?? ficha.ritmos[0]
  const coste = plan ? (ritmo?.usd_por_minuto || 0) * (plan.segundos / 60) : 0
  const listo =
    encargo.nombre.trim().length > 0 &&
    encargo.estilo_prompt.trim().length >= 8 &&
    encargo.tono_prompt.trim().length > 0 &&
    encargo.voz_prompt.trim().length > 0

  return (
    <div className="space-y-8">
      {(!ficha.hay_openai || !ficha.hay_elevenlabs) && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p>
            Faltan claves ({!ficha.hay_openai && "OpenAI"}
            {!ficha.hay_openai && !ficha.hay_elevenlabs && " y "}
            {!ficha.hay_elevenlabs && "ElevenLabs"}): el canal no puede
            generarse.{" "}
            <Link to="/config" className="underline underline-offset-2">
              Configuración
            </Link>
          </p>
        </div>
      )}

      {/* ------------------------------------------ los cuatro campos */}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">
              Tu canal de una tirada
            </h2>
            <p className="text-sm text-muted-foreground">
              Tu estilo en cuatro campos. No hay pestañas, no hay pasos:
              describe y pulsa.
            </p>
          </div>

          <div className="space-y-2">
            <Etiqueta htmlFor="l-nombre">Nombre del canal</Etiqueta>
            <Entrada
              id="l-nombre"
              valor={encargo.nombre}
              alCambiar={(e) =>
                setEncargo({ ...encargo, nombre: e.target.value })
              }
              placeholder="Documental de archivo"
            />
          </div>

          <div className="space-y-2">
            <Etiqueta htmlFor="l-estilo">Estilo visual</Etiqueta>
            <AreaTexto
              id="l-estilo"
              filas={3}
              valor={encargo.estilo_prompt}
              alCambiar={(e) =>
                setEncargo({ ...encargo, estilo_prompt: e.target.value })
              }
              placeholder="documental sobrio de archivo, fotografía en azul, texturas de película vieja…"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Etiqueta htmlFor="l-tono">Tono de escritura</Etiqueta>
              <AreaTexto
                id="l-tono"
                filas={3}
                valor={encargo.tono_prompt}
                alCambiar={(e) =>
                  setEncargo({ ...encargo, tono_prompt: e.target.value })
                }
                placeholder="seco y periodístico, sin adjetivos…"
              />
            </div>
            <div className="space-y-2">
              <Etiqueta htmlFor="l-voz">Voz</Etiqueta>
              <AreaTexto
                id="l-voz"
                filas={3}
                valor={encargo.voz_prompt}
                alCambiar={(e) =>
                  setEncargo({ ...encargo, voz_prompt: e.target.value })
                }
                placeholder="grave, pausada, sin dramatismo…"
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Etiqueta>Idioma</Etiqueta>
              <Selector
                valor={encargo.idioma}
                alCambiar={(v) => setEncargo({ ...encargo, idioma: v })}
              >
                <DisparadorSelector>
                  <ValorSelector placeholder="idioma" />
                </DisparadorSelector>
                <ContenidoSelector>
                  {ficha.idiomas.map((i) => (
                    <Opcion key={i.id} valor={i.id}>
                      {i.nombre}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
            <div className="space-y-2">
              <Etiqueta>Ritmo</Etiqueta>
              <Selector
                valor={encargo.ritmo}
                alCambiar={(v) => setEncargo({ ...encargo, ritmo: v })}
              >
                <DisparadorSelector>
                  <ValorSelector placeholder="ritmo" />
                </DisparadorSelector>
                <ContenidoSelector>
                  {ficha.ritmos.map((r) => (
                    <Opcion key={r.id} valor={r.id}>
                      {r.nombre} · {r.ritmo_min}-{r.ritmo_max} s
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
          </div>

          {creando_tid ? (
            <div className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
              <p className="flex items-center gap-2 font-medium">
                <Loader2 className="h-4 w-4 animate-spin" />
                Montando el canal ({trabajo_creacion?.paso ?? "taller"}…)
              </p>
              {trabajo_creacion?.lineas?.length ? (
                <p className="truncate text-xs text-muted-foreground">
                  {trabajo_creacion.lineas[
                    trabajo_creacion.lineas.length - 1
                  ]?.mensaje.slice(0, 140)}
                </p>
              ) : null}
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <Boton deshabilitado={!listo} onClick={crear}>
                <Wand2 /> Crear el canal
              </Boton>
              <span className="text-xs text-muted-foreground">
                género · tono · voz · muestras, todo de una tirada
              </span>
            </div>
          )}
        </div>

        {/* ------------------------------------------------- el plan */}
        <Tarjeta className="h-fit">
          <CabeceraTarjeta>
            <TituloTarjeta className="text-base">El plan</TituloTarjeta>
            <p className="text-xs text-muted-foreground">
              lo que hará el taller al pulsar
            </p>
          </CabeceraTarjeta>
          <ContenidoTarjeta className="space-y-3">
            {plan ? (
              <>
                {plan.tandas.map((tanda, i) => (
                  <div key={i} className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">
                      tanda {i + 1}
                    </p>
                    {tanda.map((t) => (
                      <p key={String(t.id)} className="text-sm">
                        · {String(t.nombre)}
                      </p>
                    ))}
                  </div>
                ))}
                <div className="border-t pt-2 text-sm">
                  <p>
                    {segundos(plan.segundos)} de vídeo de muestra
                    <br />{plan.imagenes} láminas generadas
                  </p>
                  <p className="mt-1 font-medium">
                    ≈ {dolares(coste)} en generación
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {ritmo?.nombre}: {ritmo?.usd_por_minuto} $/min de vídeo
                    final. Pagarás más al generar vídeos, no al estilo.
                  </p>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">calculando…</p>
            )}
          </ContenidoTarjeta>
        </Tarjeta>
      </div>

      {/* --------------------------------------- la galería de canales */}
      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h3 className="text-lg font-semibold tracking-tight">
            Canales congelados
          </h3>
          <p className="text-xs text-muted-foreground">
            cada canal es un preset listo para aplicar a los vídeos
          </p>
        </div>
        {ficha.presets.length === 0 ? (
          <p className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            aún no hay canales: el primero sale de los cuatro campos de arriba
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {ficha.presets.map((p) => (
              <Tarjeta
                key={p.id}
                className="cursor-pointer transition-shadow hover:shadow-md"
                onClick={() => setDetalle(p)}
              >
                <CabeceraTarjeta>
                  <div className="flex items-start justify-between gap-2">
                    <TituloTarjeta className="line-clamp-1">
                      {p.nombre}
                    </TituloTarjeta>
                    <Insignia>{p.idioma}</Insignia>
                  </div>
                  {p.resumen && (
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {p.resumen}
                    </p>
                  )}
                </CabeceraTarjeta>
                <ContenidoTarjeta>
                  {p.hay_miniatura ? (
                    <img
                      src={`/api/presets-canal/${p.id}/miniatura`}
                      alt=""
                      className="aspect-video w-full rounded-md object-cover"
                    />
                  ) : (
                    <div className="flex aspect-video w-full items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <Sparkles className="h-6 w-6" />
                    </div>
                  )}
                </ContenidoTarjeta>
                <PieTarjeta className="justify-between">
                  <ul className="space-y-0.5 text-xs text-muted-foreground">
                    {(p.vinetas ?? []).slice(0, 2).map((v, i) => (
                      <li key={i} className="line-clamp-1">
                        · {v.icono} {v.texto}
                      </li>
                    ))}
                  </ul>
                  <Boton
                    variante="fantasma"
                    tamano="pequeno"
                    onClick={(e) => {
                      e.stopPropagation()
                      setDetalle(p)
                    }}
                  >
                    Ver
                  </Boton>
                </PieTarjeta>
              </Tarjeta>
            ))}
          </div>
        )}
      </div>

      {detalle && (
        <DialogoCanal
          preset={detalle}
          alCerrar={() => setDetalle(null)}
          alCambiar={cargar}
        />
      )}
    </div>
  )
}

/* ------------------------------------------------- la ficha de un canal */

function DialogoCanal({
  preset,
  alCerrar,
  alCambiar,
}: {
  preset: PresetCanal
  alCerrar: () => void
  alCambiar: () => void
}) {
  const [ficha, setFicha] = useState<FichaPresetLight | null>(null)
  const [escucha, setEscucha] = useState<{ url: string } | null>(null)
  const [escuchando, setEscuchando] = useState(false)
  const [feedback, setFeedback] = useState("")
  const [parte, setParte] = useState<"estilo" | "tono" | "voz" | null>(null)
  const [tid, setTid] = useState<string | null>(null)
  const [nombre, setNombre] = useState(preset.nombre)

  const cargar = useCallback(() => {
    api
      .get<FichaPresetLight>(`/api/presets-light/${preset.id}`)
      .then(setFicha)
      .catch((e) => toast.error(String(e.message ?? e)))
  }, [preset.id])

  useEffect(cargar, [cargar])

  const al_terminar = (final: TrabajoFicha) => {
    if (final.estado === "hecho") {
      toast.success("regenerado y congelado de nuevo")
      setTid(null)
      setParte(null)
      setFeedback("")
      cargar()
      alCambiar()
    } else if (final.estado === "fallo" || final.estado === "cancelado") {
      toast.error(final.error || "la regeneración falló")
      setTid(null)
    }
  }
  usarTrabajo({ tid, alTerminar: al_terminar })

  const oir = async () => {
    setEscuchando(true)
    setEscucha(null)
    try {
      setEscucha(await api.post(`/api/presets-light/${preset.id}/escucha`))
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEscuchando(false)
    }
  }

  const regenerar = async () => {
    if (!parte) return
    try {
      const r = await api.post<{ trabajo: TrabajoFicha }>(
        `/api/presets-light/${preset.id}/regenerar`,
        { parte, feedback },
      )
      setTid(r.trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const duplicar = async () => {
    try {
      await api.post(`/api/presets-light/${preset.id}/duplicar`)
      toast.success("duplicado: rehaz la copia sin tocar el original")
      alCambiar()
      alCerrar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const borrar = async () => {
    if (
      !confirm(
        `¿Borrar «${preset.nombre}»? El preset y su taller se van juntos (sin el taller no se puede rehacer el tono).`,
      )
    )
      return
    try {
      await api.borrar(`/api/presets-light/${preset.id}`)
      toast.success("canal apartado a la papelera de presets")
      alCambiar()
      alCerrar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const renombrar = async () => {
    const limpio = nombre.trim()
    if (!limpio || limpio === preset.nombre) return
    try {
      await api.put(`/api/presets-light/${preset.id}`, { nombre: limpio })
      toast.success("renombrado")
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const en_curso =
    !!tid || ficha?.activo?.estado === "en_cola" || ficha?.activo?.estado === "ejecutando"

  return (
    <Dialogo abierto alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo className="max-w-2xl">
        <CabeceraDialogo>
          <TituloDialogo className="flex w-full items-center gap-2">
            <Entrada
              valor={nombre}
              alCambiar={(e) => setNombre(e.target.value)}
              onBlur={renombrar}
              className=" flex-1"
            />
          </TituloDialogo>
          <DescripcionDialogo>
            {preset.vinetas?.map((v) => `${v.icono} ${v.texto}`).join(" · ")}
          </DescripcionDialogo>
        </CabeceraDialogo>

        <div className="space-y-4">
          {ficha === null ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <>
              {/* los cuatro campos, tal como se pidieron */}
              <div className="grid gap-3 sm:grid-cols-3">
                {(
                  [
                    ["estilo_prompt", "Estilo"],
                    ["tono_prompt", "Tono"],
                    ["voz_prompt", "Voz"],
                  ] as const
                ).map(([clave, titulo]) => (
                  <div
                    key={clave}
                    className="rounded-md border bg-muted/30 p-3 text-sm"
                  >
                    <p className="text-xs font-medium text-muted-foreground">
                      {titulo}
                    </p>
                    <p className="line-clamp-4">
                      {ficha.encargo[clave] || "—"}
                    </p>
                  </div>
                ))}
              </div>

              {/* las muestras del taller */}
              {ficha.muestras.length > 0 && (
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {ficha.muestras.map((m) => (
                    <img
                      key={m}
                      src={`/api/presets-canal/${preset.id}/fichero/${m}`}
                      alt={m}
                      className="h-24 rounded-md border object-cover"
                    />
                  ))}
                </div>
              )}

              {/* la voz del canal */}
              <div className="space-y-2 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Boton
                    variante="contorno"
                    tamano="pequeno"
                    deshabilitado={escuchando || !ficha.taller}
                    title={
                      ficha.taller
                        ? "sintetiza unos segundos con la voz del canal"
                        : "el taller ya no está: duplica el preset para oírlo"
                    }
                    onClick={oir}
                  >
                    {escuchando ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Play />
                    )}
                    Escucha
                  </Boton>
                  <span className="text-xs text-muted-foreground">
                    {ficha.taller
                      ? "unos segundos con la voz y el ritmo del canal"
                      : "taller borrado: duplica para regenerar"}
                  </span>
                </div>
                {escucha && (
                  <audio controls preload="none" src={escucha.url} className="h-8 w-full" />
                )}
              </div>

              {/* regenerar una parte con feedback */}
              <div className="space-y-2 rounded-md border p-3">
                <p className="text-sm font-medium">Rehacer una parte</p>
                <div className="flex flex-wrap gap-2">
                  {PARTES.map((p) => (
                    <Boton
                      key={p.id}
                      variante={parte === p.id ? "defecto" : "contorno"}
                      tamano="pequeno"
                      deshabilitado={!ficha.taller}
                      title={p.ayuda}
                      onClick={() => setParte(parte === p.id ? null : p.id)}
                    >
                      <RefreshCw /> {p.nombre}
                    </Boton>
                  ))}
                </div>
                {parte && (
                  <div className="space-y-2">
                    <AreaTexto
                      filas={2}
                      valor={feedback}
                      alCambiar={(e) => setFeedback(e.target.value)}
                      placeholder="qué cambia: «más claro», «menos solemne», «mujer más joven»…"
                    />
                    <Boton
                      tamano="pequeno"
                      deshabilitado={en_curso || !feedback.trim()}
                      onClick={regenerar}
                    >
                      {en_curso ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <Music />
                      )}
                      Rehacer {parte}
                    </Boton>
                  </div>
                )}
                {en_curso && (
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    el taller está trabajando…
                  </p>
                )}
              </div>

              <div className="flex justify-between gap-2">
                <Boton
                  variante="contorno"
                  tamano="pequeno"
                  onClick={duplicar}
                  title="copia el preset y su taller: rehaz sin tocar el original"
                >
                  <Copy /> Duplicar
                </Boton>
                <Boton
                  variante="destructivo"
                  tamano="pequeno"
                  onClick={borrar}
                >
                  <Trash2 /> Borrar
                </Boton>
              </div>
            </>
          )}
        </div>
      </ContenidoDialogo>
    </Dialogo>
  )
}
