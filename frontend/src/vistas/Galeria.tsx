import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { toast } from "sonner"
import {
  Copy,
  Loader2,
  Plus,
  Trash2,
  Undo2,
  FolderOpen,
  AlertTriangle,
  Film,
  Zap,
} from "lucide-react"
import { api } from "../lib/api"
import { dolares } from "../lib/utils"
import {
  NOMBRES_PASOS,
  ORDEN_PASOS,
  type EstiloCanal,
  type FichaProyecto,
  type InventarioPapelera,
  type TrabajoFicha,
} from "../lib/tipos"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
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

interface ProyectoPapelera {
  carpeta: string
  id: string
  nombre: string
  apartado: string
}

const COLOR_PUNTO: Record<string, string> = {
  vacio: "bg-muted-foreground/20",
  ok: "bg-emerald-500",
  obsoleto: "bg-amber-500",
}

export default function Galeria() {
  const navegar = useNavigate()
  const [proyectos, setProyectos] = useState<FichaProyecto[] | null>(null)
  const [papelera, setPapelera] = useState<ProyectoPapelera[] | null>(null)
  const [crear_abierto, setCrearAbierto] = useState(false)
  const [papelera_abierta, setPapeleraAbierta] = useState(false)
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set())
  const [tanda_tid, setTandaTid] = useState<string | null>(null)

  const alternar_seleccion = (id: string) => {
    setSeleccion((prev) => {
      const nueva = new Set(prev)
      if (nueva.has(id)) nueva.delete(id)
      else nueva.add(id)
      return nueva
    })
  }

  const lanzar_tanda = async () => {
    const ids = [...seleccion]
    if (
      !confirm(
        `¿Correr lo pendiente en ${ids.length} vídeo(s)? Cada paso pendiente gasta lo que gasta su botón (la voz sigue esperando el guion aprobado).`,
      )
    )
      return
    try {
      const t = await api.post<TrabajoFicha>("/api/proyectos/tanda", {
        ids,
        modo: "pendiente",
      })
      toast.success(`tanda en marcha (${ids.length} vídeos)`)
      setSeleccion(new Set())
      setTandaTid(t.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const cargar = useCallback(() => {
    api.get<FichaProyecto[]>("/api/proyectos").then(setProyectos).catch((e) => {
      toast.error(String(e.message ?? e))
      setProyectos([])
    })
  }, [])

  const cargar_papelera = useCallback(() => {
    api
      .get<ProyectoPapelera[]>("/api/proyectos/papelera")
      .then(setPapelera)
      .catch(() => setPapelera([]))
  }, [])

  useEffect(() => {
    cargar()
    cargar_papelera()
  }, [cargar, cargar_papelera])

  /* la tanda no vive en ningún proyecto: la galería la sigue sondeando */
  useEffect(() => {
    if (!tanda_tid) return
    const timer = setInterval(async () => {
      try {
        const t = await api.get<TrabajoFicha>(`/api/trabajos/${tanda_tid}`)
        cargar()
        if (t.estado === "hecho" || t.estado === "fallo" || t.estado === "cancelado") {
          if (t.estado === "fallo") toast.error(`tanda falló: ${t.error}`)
          else toast.success("tanda terminada")
          setTandaTid(null)
        }
      } catch {
        setTandaTid(null)
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [tanda_tid, cargar])

  const borrar = async (p: FichaProyecto) => {
    if (!confirm(`¿Mover «${p.nombre}» a la papelera?`)) return
    try {
      await api.borrar(`/api/proyectos/${p.id}`)
      toast.success("movido a la papelera")
      cargar()
      cargar_papelera()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const duplicar = async (p: FichaProyecto) => {
    try {
      await api.post(`/api/proyectos/${p.id}/duplicar`)
      toast.success("proyecto duplicado")
      cargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Proyectos</h1>
        <div className="flex gap-2">
          {seleccion.size > 0 && (
            <Boton
              variante="contorno"
              tamano="pequeno"
              title="Receta completa sobre los seleccionados: cada vídeo corre lo que le falta"
              deshabilitado={!!tanda_tid}
              onClick={lanzar_tanda}
            >
              <Zap /> Generar pendientes ({seleccion.size})
            </Boton>
          )}
          <Boton
            variante="contorno"
            tamano="pequeno"
            onClick={() => {
              cargar_papelera()
              setPapeleraAbierta(true)
            }}
          >
            <FolderOpen /> Papelera
          </Boton>
          <Boton tamano="pequeno" onClick={() => setCrearAbierto(true)}>
            <Plus /> Nuevo proyecto
          </Boton>
        </div>
      </div>

      {tanda_tid && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Tanda en marcha: la galería se refresca sola mientras trabaja.
        </div>
      )}

      {!proyectos ? (
        <div className="flex justify-center py-20 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : proyectos.length === 0 ? (
        <Tarjeta>
          <ContenidoTarjeta className="flex flex-col items-center gap-2 py-16 text-center">
            <p className="font-medium">Todavía no hay proyectos</p>
            <p className="text-sm text-muted-foreground">
              Crea el primero y pega tu material para empezar.
            </p>
            <Boton className="mt-2" onClick={() => setCrearAbierto(true)}>
              <Plus /> Nuevo proyecto
            </Boton>
          </ContenidoTarjeta>
        </Tarjeta>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {proyectos.map((p) => (
            <Tarjeta
              key={p.id}
              className="cursor-pointer transition-shadow hover:shadow-md"
              onClick={() => navegar(`/p/${p.id}`)}
            >
              <CabeceraTarjeta>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1 shrink-0"
                      title="Marcar para la tanda"
                      checked={seleccion.has(p.id)}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => alternar_seleccion(p.id)}
                    />
                    <TituloTarjeta className="line-clamp-1">
                      {p.nombre}
                    </TituloTarjeta>
                  </div>
                  {p.activo ? (
                    <Insignia variante="aviso">
                      {NOMBRES_PASOS[p.activo.paso] ?? p.activo.paso}…
                    </Insignia>
                  ) : null}
                </div>
                <p className="text-xs text-muted-foreground">
                  {[p.canal, p.idioma].filter(Boolean).join(" · ") || "—"}
                </p>
              </CabeceraTarjeta>
              <ContenidoTarjeta>
                <div className="flex gap-1.5" title="Estado de los pasos">
                  {ORDEN_PASOS.map((paso) => (
                    <span
                      key={paso}
                      title={NOMBRES_PASOS[paso]}
                      className={`h-2.5 w-2.5 rounded-full ${
                        COLOR_PUNTO[p.pasos?.[paso]?.estado ?? "vacio"]
                      }`}
                    />
                  ))}
                </div>
              </ContenidoTarjeta>
              <PieTarjeta className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {dolares(p.coste || 0)}
                </span>
                <div
                  className="flex gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Boton
                    variante="fantasma"
                    tamano="icono"
                    title="Duplicar"
                    onClick={() => duplicar(p)}
                  >
                    <Copy />
                  </Boton>
                  <Boton
                    variante="fantasma"
                    tamano="icono"
                    title="Mover a la papelera"
                    onClick={() => borrar(p)}
                  >
                    <Trash2 />
                  </Boton>
                </div>
              </PieTarjeta>
            </Tarjeta>
          ))}
        </div>
      )}

      <DialogoCrear
        abierto={crear_abierto}
        alCerrar={() => setCrearAbierto(false)}
        alCrear={(pid) => {
          setCrearAbierto(false)
          navegar(`/p/${pid}`)
        }}
      />

      <DialogoPapelera
        abierto={papelera_abierta}
        items={papelera}
        alCerrar={() => setPapeleraAbierta(false)}
        alCambiar={() => {
          cargar_papelera()
          cargar()
        }}
      />
    </div>
  )
}

function DialogoCrear({
  abierto,
  alCerrar,
  alCrear,
}: {
  abierto: boolean
  alCerrar: () => void
  alCrear: (pid: string) => void
}) {
  const [nombre, setNombre] = useState("")
  const [canal, setCanal] = useState("")
  const [idioma, setIdioma] = useState("es")
  const [enviando, setEnviando] = useState(false)
  const [estilo, setEstilo] = useState<EstiloCanal | null>(null)

  useEffect(() => {
    if (abierto)
      api
        .get<EstiloCanal>("/api/estilo")
        .then(setEstilo)
        .catch(() => setEstilo(null))
  }, [abierto])

  const crear = async (e: React.FormEvent) => {
    e.preventDefault()
    setEnviando(true)
    try {
      const ficha = await api.post<FichaProyecto>("/api/proyectos", {
        nombre,
        canal,
        idioma,
      })
      alCrear(ficha.id)
    } catch (err) {
      toast.error(String((err as Error).message ?? err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo>
        <CabeceraDialogo>
          <TituloDialogo>Nuevo proyecto</TituloDialogo>
          <DescripcionDialogo>
            {estilo?.definido
              ? `Arranca sembrado con el estilo del canal${estilo.nombre ? ` «${estilo.nombre}»` : ""}: tono, ritmo, voz y estilo gráfico.`
              : "Los pasos arrancan con sus parámetros por defecto."}
          </DescripcionDialogo>
        </CabeceraDialogo>
        {estilo && !estilo.definido && (
          <p className="-mt-1 text-sm text-amber-600 dark:text-amber-400">
            Todavía no hay estilo del canal:{" "}
            <Link to="/estilo" className="underline underline-offset-2">
              defínelo primero
            </Link>{" "}
            para que todos los vídeos sigan la misma línea.
          </p>
        )}
        <form onSubmit={crear} className="space-y-4">
          <div className="space-y-2">
            <Etiqueta htmlFor="nombre">Nombre</Etiqueta>
            <Entrada
              id="nombre"
              autoFocus
              required
              valor={nombre}
              alCambiar={(e) => setNombre(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Etiqueta htmlFor="canal">Canal (opcional)</Etiqueta>
              <Entrada
                id="canal"
                valor={canal}
                alCambiar={(e) => setCanal(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Etiqueta>Idioma</Etiqueta>
              <Selector valor={idioma} alCambiar={setIdioma}>
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
          <div className="flex justify-end gap-2">
            <Boton tipo="button" variante="contorno" onClick={alCerrar}>
              Cancelar
            </Boton>
            <Boton tipo="submit" deshabilitado={enviando || !nombre.trim()}>
              {enviando && <Loader2 className="animate-spin" />}
              Crear
            </Boton>
          </div>
        </form>
      </ContenidoDialogo>
    </Dialogo>
  )
}

function peso_texto(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${bytes} B`
}

function DialogoPapelera({
  abierto,
  items,
  alCerrar,
  alCambiar,
}: {
  abierto: boolean
  items: ProyectoPapelera[] | null
  alCerrar: () => void
  alCambiar: () => void
}) {
  const [pendiente, setPendiente] = useState<InventarioPapelera | null>(null)

  const restaurar = async (carpeta: string) => {
    try {
      await api.post(`/api/proyectos/papelera/${carpeta}/restaurar`)
      toast.success("proyecto restaurado")
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  /** Pide el inventario ANTES de borrar: que se vea qué se pierde. */
  const pre_eliminar = async (carpeta: string) => {
    setPendiente(null)
    try {
      setPendiente(
        await api.get<InventarioPapelera>(`/api/proyectos/papelera/${carpeta}`),
      )
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const eliminar = async () => {
    if (!pendiente) return
    try {
      await api.borrar(`/api/proyectos/papelera/${pendiente.carpeta}`)
      toast.success("proyecto eliminado para siempre")
      setPendiente(null)
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const vaciar = async () => {
    if (
      !confirm(
        `¿Vaciar la papelera entera (${items?.length ?? 0} proyectos)? No tiene vuelta atrás.`,
      )
    )
      return
    try {
      await api.borrar("/api/proyectos/papelera")
      toast.success("papelera vaciada")
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
      <ContenidoDialogo>
        <CabeceraDialogo>
          <TituloDialogo>Papelera</TituloDialogo>
          <DescripcionDialogo>
            Los proyectos siguen en disco hasta que los elimines.
          </DescripcionDialogo>
        </CabeceraDialogo>

        <div className="max-h-80 space-y-2 overflow-y-auto">
          {!items ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              cargando…
            </p>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              la papelera está vacía
            </p>
          ) : (
            items.map((it) =>
              pendiente?.carpeta === it.carpeta ? (
                <div
                  key={it.carpeta}
                  className="space-y-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3"
                >
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <AlertTriangle className="h-4 w-4 text-destructive" />
                    Se pierde «{pendiente.nombre}» para siempre
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {pendiente.ficheros} ficheros ·{" "}
                    {peso_texto(pendiente.peso)}
                    {pendiente.videos.length > 0 &&
                      ` · ${pendiente.videos.length} vídeo(s)`}
                  </p>
                  <div className="max-h-32 space-y-1 overflow-y-auto text-xs">
                    {Object.entries(pendiente.por_carpeta).map(
                      ([grupo, info]) => (
                        <p key={grupo} className="text-muted-foreground">
                          <span className="font-medium text-foreground">
                            {grupo === "." ? "raíz" : grupo}
                          </span>
                          : {info.nombres.slice(0, 6).join(", ")}
                          {info.nombres.length > 6 &&
                            ` y ${info.nombres.length - 6} más`}
                        </p>
                      ),
                    )}
                  </div>
                  <div className="flex justify-end gap-2">
                    <Boton
                      variante="contorno"
                      tamano="pequeno"
                      onClick={() => setPendiente(null)}
                    >
                      Cancelar
                    </Boton>
                    <Boton
                      variante="destructivo"
                      tamano="pequeno"
                      onClick={eliminar}
                    >
                      <Trash2 /> Eliminar para siempre
                    </Boton>
                  </div>
                </div>
              ) : (
                <div
                  key={it.carpeta}
                  className="flex items-center justify-between rounded-md border px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-medium">{it.nombre}</p>
                    <p className="text-xs text-muted-foreground">
                      {it.apartado || it.id}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Boton
                      variante="fantasma"
                      tamano="icono"
                      title="Restaurar"
                      onClick={() => restaurar(it.carpeta)}
                    >
                      <Undo2 />
                    </Boton>
                    <Boton
                      variante="fantasma"
                      tamano="icono"
                      title="Eliminar para siempre"
                      onClick={() => pre_eliminar(it.carpeta)}
                    >
                      <Trash2 />
                    </Boton>
                  </div>
                </div>
              ),
            )
          )}
        </div>

        {items && items.length > 0 && (
          <div className="flex items-center justify-between pt-2">
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Film className="h-3 w-3" />
              {items.length} proyecto(s) ocupando disco
            </p>
            <Boton
              variante="destructivo"
              tamano="pequeno"
              onClick={vaciar}
              deshabilitado={!!pendiente}
            >
              <Trash2 /> Vaciar papelera
            </Boton>
          </div>
        )}
      </ContenidoDialogo>
    </Dialogo>
  )
}
