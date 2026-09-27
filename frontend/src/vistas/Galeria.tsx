import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import {
  Copy,
  Loader2,
  Plus,
  Trash2,
  Undo2,
  FolderOpen,
} from "lucide-react"
import { api } from "../lib/api"
import { dolares } from "../lib/utils"
import {
  NOMBRES_PASOS,
  ORDEN_PASOS,
  type FichaProyecto,
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
                  <TituloTarjeta className="line-clamp-1">
                    {p.nombre}
                  </TituloTarjeta>
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
            Los pasos arrancan con sus parámetros por defecto.
          </DescripcionDialogo>
        </CabeceraDialogo>
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
  const restaurar = async (carpeta: string) => {
    try {
      await api.post(`/api/proyectos/papelera/${carpeta}/restaurar`)
      toast.success("proyecto restaurado")
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }
  const eliminar = async (carpeta: string) => {
    if (!confirm("¿Eliminar el proyecto para siempre?")) return
    try {
      await api.borrar(`/api/proyectos/papelera/${carpeta}`)
      toast.success("proyecto eliminado")
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
            items.map((it) => (
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
                    onClick={() => eliminar(it.carpeta)}
                  >
                    <Trash2 />
                  </Boton>
                </div>
              </div>
            ))
          )}
        </div>
      </ContenidoDialogo>
    </Dialogo>
  )
}
