/** El estilo visual del vídeo: catálogo, encuadres, guía y moodboard.

Dos diálogos:
- «Estilo visual» (cuatro pestañas): quién sale y dónde (catálogo, vive
  en params de ASSETS), qué clase de plano es cada uno (encuadres), la
  biblia con números (guía) y sus láminas de comprobación (moodboard).
- «Conservación»: cuando el guion cambia, qué imágenes ya pagadas
  siguen valiendo. Marcar y regenerar son dos gestos.

PROPONER NO ES APROBAR: los agentes dejan propuestas en el borrador;
lo que viaja a params es lo que una persona guarda.
*/
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import {
  BookOpen,
  Check,
  Eraser,
  Film,
  Images,
  Loader2,
  Recycle,
  Sparkles,
  Users,
} from "lucide-react"
import { api } from "../../lib/api"
import { usarTrabajo } from "../../lib/trabajos"
import type {
  CatalogoVisual,
  FichaCatalogo,
  FichaEncuadres,
  FichaGuiaPantalla,
  FichaMoodboard,
  PlanConservacion,
  PropuestaCatalogo,
  PropuestaGuia,
  ResultadoConservacion,
  TrabajoFicha,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { AreaTexto } from "../../components/ui/textarea"
import { Entrada } from "../../components/ui/input"
import { Etiqueta } from "../../components/ui/etiqueta"
import { Insignia } from "../../components/ui/badge"
import {
  Dialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
} from "../../components/ui/dialogo"
import {
  Pestanas,
  ListaPestanas,
  DisparadorPestanas,
  ContenidoPestanas,
} from "../../components/ui/pestanas"
import {
  Selector,
  DisparadorSelector,
  ValorSelector,
  ContenidoSelector,
  Opcion,
} from "../../components/ui/selector"

export type PestanaEstiloVisual = "catalogo" | "encuadres" | "guia" | "moodboard"

interface PropsEstilo {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  pestana: PestanaEstiloVisual
  alPestana: (pestana: PestanaEstiloVisual) => void
  recargar: () => void
}

export function DialogoEstiloVisual({
  pid,
  abierto,
  alCambiar,
  pestana,
  alPestana,
  recargar,
}: PropsEstilo) {
  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-h-[88vh] max-w-4xl overflow-y-auto">
        <CabeceraDialogo>
          <TituloDialogo className="flex items-center gap-2">
            <BookOpen className="size-4" /> Estilo visual
          </TituloDialogo>
          <DescripcionDialogo>
            Quién sale y dónde (catálogo), qué clase de plano es cada uno
            (encuadres), la guía con números y sus láminas de comprobación.
            El catálogo y la guía viven en los params de imágenes: cambiarlos
            las deja obsoletas, y quien regenera es la persona.
          </DescripcionDialogo>
        </CabeceraDialogo>
        <Pestanas
          valor={pestana}
          alCambiar={(v) => alPestana(v as PestanaEstiloVisual)}
        >
          <ListaPestanas className="w-full">
            <DisparadorPestanas valor="catalogo">
              <Users className="mr-1 inline size-3.5" /> Catálogo
            </DisparadorPestanas>
            <DisparadorPestanas valor="encuadres">
              <Film className="mr-1 inline size-3.5" /> Encuadres
            </DisparadorPestanas>
            <DisparadorPestanas valor="guia">
              <BookOpen className="mr-1 inline size-3.5" /> Guía
            </DisparadorPestanas>
            <DisparadorPestanas valor="moodboard">
              <Images className="mr-1 inline size-3.5" /> Moodboard
            </DisparadorPestanas>
          </ListaPestanas>
          <ContenidoPestanas valor="catalogo" className="mt-4">
            <PestanaCatalogo pid={pid} recargar={recargar} />
          </ContenidoPestanas>
          <ContenidoPestanas valor="encuadres" className="mt-4">
            <PestanaEncuadres pid={pid} recargar={recargar} />
          </ContenidoPestanas>
          <ContenidoPestanas valor="guia" className="mt-4">
            <PestanaGuia pid={pid} recargar={recargar} />
          </ContenidoPestanas>
          <ContenidoPestanas valor="moodboard" className="mt-4">
            <PestanaMoodboard pid={pid} recargar={recargar} />
          </ContenidoPestanas>
        </Pestanas>
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ------------------------------------------------------------- catálogo */

const CATALOGO_VACIO: CatalogoVisual = {
  reparto: {},
  sets: {},
  beats: [],
  capitulos: {},
  lugares: {},
  avisos: [],
}

function PestanaCatalogo({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaCatalogo | null>(null)
  const [borrador, setBorrador] = useState<CatalogoVisual>(CATALOGO_VACIO)
  const [peticion, setPeticion] = useState("")
  const [cargando, setCargando] = useState(true)
  const [tid, setTid] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const r = await api.get<FichaCatalogo>(`/api/proyectos/${pid}/catalogo`)
      setFicha(r)
      setBorrador(r.catalogo ?? CATALOGO_VACIO)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setCargando(false)
    }
  }, [pid])

  useEffect(() => {
    cargar()
  }, [cargar])

  const alTerminar = (trabajo: TrabajoFicha) => {
    setTid(null)
    if (trabajo.estado === "hecho" && trabajo.resultado) {
      const propuesta = trabajo.resultado as PropuestaCatalogo
      setBorrador(propuesta.catalogo ?? CATALOGO_VACIO)
      toast.success(
        `${propuesta.personajes} personaje(s), ${propuesta.sets} set(s), ${propuesta.beats} beat(s) propuestos`,
        {
          description:
            (propuesta.avisos ?? []).slice(0, 3).join(" · ") ||
            "repásalo y guarda lo que valga",
        },
      )
    } else if (trabajo.estado === "fallo") {
      toast.error(trabajo.error ?? "la propuesta de catálogo falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })
  if (cargando) return <Cargando />
  if (ficha && (ficha.planos ?? []).length === 0) return <SinGuion />

  const cambiar = (cambios: Partial<CatalogoVisual>) =>
    setBorrador({ ...borrador, ...cambios })
  const hay_cambios =
    JSON.stringify(borrador) !== JSON.stringify(ficha?.catalogo ?? CATALOGO_VACIO)

  const guardar = async () => {
    try {
      const r = await api.put<{ catalogo: CatalogoVisual; avisos: string[] }>(
        `/api/proyectos/${pid}/catalogo`,
        { catalogo: borrador },
      )
      setFicha((previo) => (previo ? { ...previo, catalogo: r.catalogo } : previo))
      toast.success(
        `catálogo guardado: ${Object.keys(r.catalogo.reparto ?? {}).length} personaje(s)` +
          (r.avisos?.length ? " — " + r.avisos.join(" · ") : ""),
      )
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          Quién sale y dónde: el andamio que evita que cada plano se invente
          la cara y el sitio. Vive en imágenes: retocarlo NO regraba la voz.
        </p>
        <div className="ml-auto flex gap-2">
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={trabajo?.estado === "ejecutando"}
            onClick={async () => {
              try {
                const t = await api.post<{ id: string }>(
                  `/api/proyectos/${pid}/catalogo/proponer`,
                  { peticion },
                )
                setTid(t.id)
              } catch (e) {
                toast.error(String((e as Error).message ?? e))
              }
            }}
          >
            {trabajo?.estado === "ejecutando" ? (
              <Loader2 className="mr-1 size-3.5 animate-spin" />
            ) : (
              <Sparkles className="mr-1 size-3.5" />
            )}
            Proponer con IA
          </Boton>
          <Boton tamano="pequeno" deshabilitado={!hay_cambios} onClick={guardar}>
            Guardar
          </Boton>
        </div>
      </div>
      <Entrada
        valor={peticion}
        alCambiar={(e) => setPeticion(e.target.value)}
        placeholder="corrección para la propuesta: «el narrador también sale de vez en cuando»"
        className="text-xs"
      />

      <section className="space-y-2">
        <Etiqueta className="text-xs">Reparto — la descripción física que viaja al generador</Etiqueta>
        {Object.keys(borrador.reparto ?? {}).length === 0 && (
          <p className="text-xs text-muted-foreground">Sin personajes repetidos.</p>
        )}
        {Object.entries(borrador.reparto ?? {}).map(([id, p]) => (
          <div key={id} className="rounded-md border bg-card p-2">
            <div className="mb-1 flex items-center gap-2">
              <Insignia variante="secundario">{id}</Insignia>
              <Entrada
                valor={p.nombre ?? ""}
                alCambiar={(e) =>
                  cambiar({ reparto: { ...borrador.reparto, [id]: { ...p, nombre: e.target.value } } })
                }
                className="h-7 w-32 text-xs"
                placeholder="nombre"
              />
              <Entrada
                valor={p.papel ?? ""}
                alCambiar={(e) =>
                  cambiar({ reparto: { ...borrador.reparto, [id]: { ...p, papel: e.target.value } } })
                }
                className="h-7 flex-1 text-xs"
                placeholder="papel en el vídeo"
              />
              <Boton
                variante="fantasma"
                tamano="pequeno"
                title="Quitar del reparto"
                onClick={() => {
                  const nuevo = { ...borrador.reparto }
                  delete nuevo[id]
                  cambiar({ reparto: nuevo })
                }}
              >
                <Eraser className="size-3" />
              </Boton>
            </div>
            <AreaTexto
              valor={p.descripcion ?? ""}
              alCambiar={(e) =>
                cambiar({ reparto: { ...borrador.reparto, [id]: { ...p, descripcion: e.target.value } } })
              }
              filas={2}
              placeholder="a tall woman in her fifties, short grey hair, red coat…"
              className="text-xs"
            />
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <Etiqueta className="text-xs">Sets — un LUGAR, no un plano</Etiqueta>
        {Object.keys(borrador.sets ?? {}).length === 0 && (
          <p className="text-xs text-muted-foreground">Sin sets.</p>
        )}
        {Object.entries(borrador.sets ?? {}).map(([id, s]) => (
          <div key={id} className="rounded-md border bg-card p-2">
            <div className="mb-1 flex items-center gap-2">
              <Insignia variante="secundario">{id}</Insignia>
              <Entrada
                valor={s.rotulo ?? ""}
                alCambiar={(e) => cambiar({ sets: { ...borrador.sets, [id]: { ...s, rotulo: e.target.value } } })}
                className="h-7 w-40 text-xs"
                placeholder="rótulo"
              />
              <Entrada
                valor={s.luz ?? ""}
                alCambiar={(e) => cambiar({ sets: { ...borrador.sets, [id]: { ...s, luz: e.target.value } } })}
                className="h-7 flex-1 text-xs"
                placeholder="luz del sitio"
              />
              <Boton
                variante="fantasma"
                tamano="pequeno"
                title="Quitar el set"
                onClick={() => {
                  const nuevo = { ...borrador.sets }
                  delete nuevo[id]
                  cambiar({ sets: nuevo })
                }}
              >
                <Eraser className="size-3" />
              </Boton>
            </div>
            <AreaTexto
              valor={s.descripcion ?? ""}
              alCambiar={(e) => cambiar({ sets: { ...borrador.sets, [id]: { ...s, descripcion: e.target.value } } })}
              filas={2}
              placeholder="a narrow street with laundry lines above…"
              className="text-xs"
            />
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <Etiqueta className="text-xs">Beats — tramos que comparten sitio, reparto y tono</Etiqueta>
        {(borrador.beats ?? []).map((b, i) => (
          <div key={i} className="rounded-md border bg-card p-2">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Entrada
                valor={b.desde}
                alCambiar={(e) => {
                  const beats = [...borrador.beats]
                  beats[i] = { ...b, desde: e.target.value }
                  cambiar({ beats })
                }}
                className="h-7 w-20 font-mono text-xs"
                placeholder="S001"
              />
              <span className="text-xs text-muted-foreground">→</span>
              <Entrada
                valor={b.hasta}
                alCambiar={(e) => {
                  const beats = [...borrador.beats]
                  beats[i] = { ...b, hasta: e.target.value }
                  cambiar({ beats })
                }}
                className="h-7 w-20 font-mono text-xs"
                placeholder="S004"
              />
              <Selector
                valor={b.set ?? "ninguno"}
                alCambiar={(v) => {
                  const beats = [...borrador.beats]
                  beats[i] = { ...b, set: v === "ninguno" ? null : v }
                  cambiar({ beats })
                }}
              >
                <DisparadorSelector className="h-7 w-40 text-xs">
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  <Opcion valor="ninguno">— sin set —</Opcion>
                  {Object.keys(borrador.sets ?? {}).map((sid) => (
                    <Opcion key={sid} valor={sid}>
                      {sid}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
              <Entrada
                valor={(b.personajes ?? []).join(", ")}
                alCambiar={(e) => {
                  const beats = [...borrador.beats]
                  beats[i] = {
                    ...b,
                    personajes: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  }
                  cambiar({ beats })
                }}
                className="h-7 flex-1 font-mono text-xs"
                placeholder="quién sale (ids del reparto, con comas)"
              />
              <Boton
                variante="fantasma"
                tamano="pequeno"
                title="Quitar el beat"
                onClick={() => cambiar({ beats: borrador.beats.filter((_, j) => j !== i) })}
              >
                <Eraser className="size-3" />
              </Boton>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Entrada
                valor={b.tono ?? ""}
                alCambiar={(e) => {
                  const beats = [...borrador.beats]
                  beats[i] = { ...b, tono: e.target.value }
                  cambiar({ beats })
                }}
                className="h-7 text-xs"
                placeholder="tono del tramo"
              />
              <Entrada
                valor={b.accion ?? ""}
                alCambiar={(e) => {
                  const beats = [...borrador.beats]
                  beats[i] = { ...b, accion: e.target.value }
                  cambiar({ beats })
                }}
                className="h-7 text-xs"
                placeholder="qué pasa en el tramo"
              />
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}

/* ----------------------------------------------------------- encuadres */

function PestanaEncuadres({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaEncuadres | null>(null)
  const [borrador, setBorrador] = useState<Record<string, string>>({})
  const [cargando, setCargando] = useState(true)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const r = await api.get<FichaEncuadres>(`/api/proyectos/${pid}/encuadres`)
      setFicha(r)
      const inicial: Record<string, string> = {}
      for (const plano of r.planos ?? []) inicial[plano.id] = r.forzadas?.[plano.id] ?? ""
      setBorrador(inicial)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setCargando(false)
    }
  }, [pid])

  useEffect(() => {
    cargar()
  }, [cargar])

  if (cargando) return <Cargando />
  if (!ficha) return null
  if ((ficha.planos ?? []).length === 0) return <SinGuion />

  const cambios = (ficha.planos ?? []).filter(
    (p) => (borrador[p.id] ?? "") !== (ficha.forzadas?.[p.id] ?? ""),
  )

  const guardar = async () => {
    const plan: Record<string, string> = {}
    for (const plano of cambios) plan[plano.id] = borrador[plano.id] ?? ""
    try {
      const r = await api.put<{ tocados: string[]; avisos: string[] }>(
        `/api/proyectos/${pid}/encuadres`,
        { plan },
      )
      toast.success(
        `${r.tocados?.length ?? 0} plano(s) con carta fijada` +
          (r.avisos?.length ? " — " + r.avisos.join(" · ") : ""),
      )
      cargar()
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          Qué clase de plano es cada uno: el reparto es determinista (la misma
          escena narra lo mismo en cada pasada) y nunca repite la familia del
          vecino. Fijar una carta manda sobre el reparto.
        </p>
        <Boton
          className="ml-auto"
          tamano="pequeno"
          deshabilitado={cambios.length === 0}
          onClick={guardar}
        >
          Guardar {cambios.length > 0 ? `(${cambios.length})` : ""}
        </Boton>
      </div>
      <div className="space-y-2">
        {(ficha.planos ?? []).map((plano) => {
          const actual = ficha.reparto?.[plano.id] ?? ""
          const fijada = borrador[plano.id] ?? ""
          const nombre_de = (id: string) =>
            ficha.catalogo?.find((c) => c.id === id)?.nombre ?? id
          return (
            <div
              key={plano.id}
              className="flex flex-wrap items-center gap-2 rounded-md border bg-card p-2"
            >
              <Insignia variante="secundario">{plano.id}</Insignia>
              <span
                className="min-w-0 flex-1 truncate text-xs text-muted-foreground"
                title={plano.narracion}
              >
                {plano.narracion}
              </span>
              <span className="text-xs text-muted-foreground">
                {fijada ? `escalera: ${nombre_de(actual)}` : nombre_de(actual)}
              </span>
              <Selector
                valor={fijada || "auto"}
                alCambiar={(v) => setBorrador({ ...borrador, [plano.id]: v === "auto" ? "" : v })}
              >
                <DisparadorSelector className="h-7 w-44 text-xs">
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  <Opcion valor="auto">automático (escalera)</Opcion>
                  {ficha.catalogo?.map((c) => (
                    <Opcion key={c.id} valor={c.id}>
                      {c.nombre}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- guía */

const CAMPOS_GUIA: { clave: keyof FichaGuiaPantalla["guia"]; nombre: string }[] = [
  { clave: "resumen_es", nombre: "Resumen (castellano, para reconocerla)" },
  { clave: "trazo", nombre: "Trazo" },
  { clave: "relleno", nombre: "Relleno" },
  { clave: "personajes", nombre: "Personajes" },
  { clave: "caras", nombre: "Caras" },
  { clave: "manos", nombre: "Manos" },
  { clave: "fondos", nombre: "Fondos" },
  { clave: "luz", nombre: "Luz" },
  { clave: "composicion", nombre: "Composición" },
  { clave: "acabado", nombre: "Acabado" },
]

function PestanaGuia({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaGuiaPantalla | null>(null)
  const [borrador, setBorrador] = useState<Record<string, string>>({})
  const [guardado, setGuardado] = useState<Record<string, string>>({})
  const [descripcion, setDescripcion] = useState("")
  const [peticion, setPeticion] = useState("")
  const [cargando, setCargando] = useState(true)
  const [tid, setTid] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const r = await api.get<FichaGuiaPantalla>(`/api/proyectos/${pid}/guia`)
      setFicha(r)
      const plano: Record<string, string> = {}
      for (const c of ["guia", "evitar", "paleta", ...CAMPOS_GUIA.map((c) => c.clave)] as string[])
        plano[c] = Array.isArray((r.guia as Record<string, unknown>)?.[c])
          ? ((r.guia as Record<string, unknown>)[c] as string[]).join(", ")
          : String((r.guia as Record<string, unknown>)?.[c] ?? "")
      setBorrador(plano)
      setGuardado(plano)
      setDescripcion((previo) => previo || r.estilo || "")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setCargando(false)
    }
  }, [pid])

  useEffect(() => {
    cargar()
  }, [cargar])

  const alTerminar = (trabajo: TrabajoFicha) => {
    setTid(null)
    if (trabajo.estado === "hecho" && trabajo.resultado) {
      const propuesta = trabajo.resultado as PropuestaGuia
      const g = propuesta.guia as unknown as Record<string, unknown>
      setBorrador({
        guia: String(g.guia ?? ""),
        evitar: String(g.evitar ?? ""),
        paleta: Array.isArray(g.paleta) ? (g.paleta as string[]).join(", ") : "",
        ...Object.fromEntries(CAMPOS_GUIA.map((c) => [c.clave as string, String(g[c.clave] ?? "")])),
      })
      toast.success(
        `guía propuesta: ${propuesta.palabras} palabras, ${propuesta.colores} colores`,
        { description: "repásala y guárdala: entra en el prompt de cada plano" },
      )
    } else if (trabajo.estado === "fallo") {
      toast.error(trabajo.error ?? "la propuesta de guía falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })
  if (cargando) return <Cargando />
  if (!ficha) return null

  const hay_cambios = JSON.stringify(borrador) !== JSON.stringify(guardado)

  const guardar = async () => {
    const paleta = (borrador.paleta ?? "")
      .split(/[,\s]+/)
      .map((s) => s.trim().toLowerCase())
      .filter((s) => /^#[0-9a-f]{6}$/.test(s))
      .slice(0, 16)
    const guia: Record<string, unknown> = { paleta }
    for (const [k, v] of Object.entries(borrador)) if (k !== "paleta") guia[k] = v
    try {
      await api.put(`/api/proyectos/${pid}/guia`, { guia })
      toast.success("guía guardada: las imágenes quedan obsoletas — regenerarlas es cosa tuya")
      recargar()
      cargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          La biblia con NÚMEROS: cuántos píxeles de contorno, cuántos dedos.
          Un número se puede obedecer; «estilizado» no. Entra en el prompt de
          cada plano.
        </p>
        <div className="ml-auto flex gap-2">
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={trabajo?.estado === "ejecutando"}
            onClick={async () => {
              try {
                const t = await api.post<{ id: string }>(
                  `/api/proyectos/${pid}/guia/proponer`,
                  { descripcion, peticion },
                )
                setTid(t.id)
              } catch (e) {
                toast.error(String((e as Error).message ?? e))
              }
            }}
          >
            {trabajo?.estado === "ejecutando" ? (
              <Loader2 className="mr-1 size-3.5 animate-spin" />
            ) : (
              <Sparkles className="mr-1 size-3.5" />
            )}
            Escribir con IA
          </Boton>
          <Boton tamano="pequeno" deshabilitado={!hay_cambios} onClick={guardar}>
            Guardar
          </Boton>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Entrada
          valor={descripcion}
          alCambiar={(e) => setDescripcion(e.target.value)}
          placeholder="describe el estilo («cómic europeo en blanco y negro…»)"
          className="text-xs"
        />
        <Entrada
          valor={peticion}
          alCambiar={(e) => setPeticion(e.target.value)}
          placeholder="corrección de esta pasada («más contraste, trazo más fino»)"
          className="text-xs"
        />
      </div>
      <div className="space-y-2">
        <Etiqueta className="text-xs">La guía (inglés, imperativo, con cifras)</Etiqueta>
        <AreaTexto
          valor={borrador.guia ?? ""}
          alCambiar={(e) => setBorrador({ ...borrador, guia: e.target.value })}
          filas={8}
          placeholder="2px uniform black outlines on everything…"
          className="text-xs"
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <Etiqueta className="text-xs">Paleta (10–16 hex, dominantes primero)</Etiqueta>
            <Entrada
              valor={borrador.paleta ?? ""}
              alCambiar={(e) => setBorrador({ ...borrador, paleta: e.target.value })}
              placeholder="#1a1a1a, #f5f0e6, …"
              className="font-mono text-xs"
            />
            <div className="flex flex-wrap gap-1">
              {(borrador.paleta ?? "")
                .split(/[,\s]+/)
                .filter((s) => /^#[0-9a-fA-F]{6}$/.test(s))
                .map((color, i) => (
                  <span
                    key={i}
                    className="size-5 rounded border"
                    style={{ background: color.toLowerCase() }}
                    title={color}
                  />
                ))}
            </div>
          </div>
          <div className="space-y-1">
            <Etiqueta className="text-xs">Evitar (negativo, concreto; las manos primero)</Etiqueta>
            <AreaTexto
              valor={borrador.evitar ?? ""}
              alCambiar={(e) => setBorrador({ ...borrador, evitar: e.target.value })}
              filas={3}
              placeholder="no gradients, no cast shadows, no six fingers…"
              className="text-xs"
            />
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {CAMPOS_GUIA.map(({ clave, nombre }) => (
            <div key={clave as string} className="space-y-1">
              <Etiqueta className="text-xs">{nombre}</Etiqueta>
              <Entrada
                valor={borrador[clave as string] ?? ""}
                alCambiar={(e) => setBorrador({ ...borrador, [clave as string]: e.target.value })}
                className="text-xs"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------- moodboard */

function PestanaMoodboard({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaMoodboard | null>(null)
  const [peticiones, setPeticiones] = useState<Record<string, string>>({})
  const [cargando, setCargando] = useState(true)
  const [tid, setTid] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      setFicha(await api.get<FichaMoodboard>(`/api/proyectos/${pid}/moodboard`))
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setCargando(false)
    }
  }, [pid])

  useEffect(() => {
    cargar()
  }, [cargar])

  const alTerminar = (trabajo: TrabajoFicha) => {
    setTid(null)
    if (trabajo.estado === "hecho" && trabajo.resultado) {
      const r = trabajo.resultado as { ejes: string[] }
      toast.success(`${r.ejes?.length ?? 0} lámina(s) dibujadas como propuesta`)
      cargar()
    } else if (trabajo.estado === "fallo") {
      toast.error(trabajo.error ?? "el moodboard falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })
  if (cargando) return <Cargando />
  if (!ficha) return null
  if (!ficha.posible)
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        {ficha.por_que_no ?? "falta la guía"} — pestaña «Guía».
      </p>
    )

  const pendientes = (ficha.ejes ?? []).filter((e) => e.pendiente)
  const faltan = (ficha.ejes ?? []).filter((e) => !e.hay)

  const generar = async (ejes?: string[]) => {
    try {
      const t = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/moodboard/generar`,
        {
          ejes,
          peticiones: Object.fromEntries(
            Object.entries(peticiones).filter(([, v]) => v.trim()),
          ),
        },
      )
      setTid(t.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const aprobar = async () => {
    try {
      const r = await api.post<{ ejes: string[] }>(
        `/api/proyectos/${pid}/moodboard/aprobar`,
      )
      toast.success(`moodboard aprobado: ${r.ejes?.length ?? 0} lámina(s) al banco`)
      cargar()
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          Las láminas se dibujan A PROPÓSITO desde la guía — y nunca al revés.
          Es la hoja de comprobación del estilo: nace propuesta y sólo cuenta
          como aprobado cuando alguien la mira.
          {typeof ficha.coste_usd === "number" && ficha.coste_usd > 0 && (
            <> · gastado {ficha.coste_usd.toFixed(2)} $</>
          )}
        </p>
        <div className="ml-auto flex gap-2">
          {(faltan.length > 0 || pendientes.length > 0) && (
            <Boton
              variante="secundario"
              tamano="pequeno"
              deshabilitado={trabajo?.estado === "ejecutando"}
              onClick={() => generar(faltan.length ? faltan.map((e) => e.eje) : undefined)}
            >
              {trabajo?.estado === "ejecutando" ? (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 size-3.5" />
              )}
              {faltan.length ? `Dibujar las ${faltan.length} que faltan` : "Rehacer propuesta"}
            </Boton>
          )}
          {pendientes.length > 0 && (
            <Boton tamano="pequeno" onClick={aprobar}>
              <Check className="mr-1 size-3.5" /> Aprobar ({pendientes.length})
            </Boton>
          )}
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(ficha.ejes ?? []).map((eje) => (
          <div key={eje.eje} className="overflow-hidden rounded-lg border">
            {eje.hay ? (
              <img
                src={`/api/proyectos/${pid}/moodboard/${eje.eje}/imagen?v=${eje.version}`}
                alt={eje.titulo}
                className={`aspect-square w-full bg-muted object-cover ${
                  eje.pendiente ? "ring-2 ring-amber-500" : ""
                }`}
              />
            ) : (
              <div className="flex aspect-square items-center justify-center bg-muted text-xs text-muted-foreground">
                sin dibujar
              </div>
            )}
            <div className="space-y-1 p-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{eje.titulo}</span>
                {eje.pendiente && (
                  <Insignia variante="contorno" className="ml-auto">propuesta</Insignia>
                )}
              </div>
              <div className="flex gap-1">
                <Entrada
                  valor={peticiones[eje.eje] ?? ""}
                  alCambiar={(e) =>
                    setPeticiones({ ...peticiones, [eje.eje]: e.target.value })
                  }
                  placeholder="corrección («los brazos eran más delgados»)"
                  className="h-7 text-xs"
                />
                <Boton
                  variante="fantasma"
                  tamano="pequeno"
                  deshabilitado={trabajo?.estado === "ejecutando"}
                  title="Rehacer sólo esta lámina con la corrección"
                  onClick={() => generar([eje.eje])}
                >
                  <Sparkles className="size-3" />
                </Boton>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- conservación */

export function DialogoConservacion({
  pid,
  abierto,
  alCambiar,
  recargar,
}: {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  recargar: () => void
}) {
  const [plan, setPlan] = useState<PlanConservacion | null>(null)
  const [tid, setTid] = useState<string | null>(null)

  const alTerminar = (trabajo: TrabajoFicha) => {
    setTid(null)
    if (trabajo.estado === "hecho" && trabajo.resultado) {
      const p = trabajo.resultado as PlanConservacion
      setPlan(p)
      toast.success(p.posible ? p.resumen : "nada que conservar")
    } else if (trabajo.estado === "fallo") {
      toast.error(trabajo.error ?? "el análisis de conservación falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })

  const analizar = async () => {
    setPlan(null)
    try {
      const t = await api.post<{ id: string }>(`/api/proyectos/${pid}/conservacion`)
      setTid(t.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const aplicar = async () => {
    if (!plan?.posible) return
    try {
      const r = await api.post<ResultadoConservacion>(
        `/api/proyectos/${pid}/conservacion/aplicar`,
        plan,
      )
      toast.success(
        `marcado: ${r.rehacer} plano(s) por rehacer y ${r.regrabar} escena(s) de voz — ` +
          "regenerar es cosa tuya, con el coste delante",
      )
      setPlan(null)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <CabeceraDialogo>
          <TituloDialogo className="flex items-center gap-2">
            <Recycle className="size-4" /> Conservar lo pagado
          </TituloDialogo>
          <DescripcionDialogo>
            Cuando el guion cambia: qué imágenes ya dibujadas SIGUEN valiendo
            con la frase nueva. Marcar y regenerar son dos gestos — aquí sólo
            se marca.
          </DescripcionDialogo>
        </CabeceraDialogo>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Boton variante="secundario" tamano="pequeno" onClick={analizar} deshabilitado={trabajo?.estado === "ejecutando"}>
              {trabajo?.estado === "ejecutando" ? (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 size-3.5" />
              )}
              Analizar qué se conserva
            </Boton>
            {plan?.posible && (
              <Boton tamano="pequeno" onClick={aplicar}>
                Marcar {plan.rehacer.length} para rehacer
              </Boton>
            )}
          </div>
          {trabajo?.estado === "ejecutando" && (
            <p className="text-xs text-muted-foreground">
              comparando la narración grabada con el guion activo…
            </p>
          )}
          {plan && !plan.posible && (
            <p className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
              {plan.por_que_no}
            </p>
          )}
          {plan?.posible && (
            <>
              <p className="text-sm text-muted-foreground">{plan.resumen}</p>
              {(plan.regrabar_voz ?? []).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Además, {plan.regrabar_voz.length} escena(s) de voz que regrabar:{" "}
                  <span className="font-mono">{plan.regrabar_voz.join(" ")}</span>
                </p>
              )}
              <div className="max-h-72 space-y-1 overflow-y-auto">
                {plan.rehacer.map((sid) => (
                  <div key={sid} className="rounded-md border bg-card px-3 py-2 text-sm">
                    <Insignia variante="secundario">{sid}</Insignia>{" "}
                    <span className="text-muted-foreground">
                      {plan.motivos?.[sid] ?? "la narración dice otra cosa"}
                    </span>
                  </div>
                ))}
                {plan.conservar.map((sid) => (
                  <div key={sid} className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                    <Insignia variante="contorno">{sid}</Insignia>{" "}
                    {plan.motivos?.[sid] ?? "la narración no ha cambiado"} — se conserva
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ------------------------------------------------------------- auxiliares */

function Cargando() {
  return (
    <div className="flex items-center justify-center py-10 text-muted-foreground">
      <Loader2 className="mr-2 size-4 animate-spin" /> cargando…
    </div>
  )
}

function SinGuion() {
  return (
    <p className="py-8 text-center text-sm text-muted-foreground">
      Falta el guion: genera primero el paso anterior.
    </p>
  )
}
