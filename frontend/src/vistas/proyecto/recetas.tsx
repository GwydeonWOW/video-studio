/**
 * «De una tirada»: la receta de cada pestaña — qué corre y en qué
 * orden — y las recetas guardadas del canal que la recortan. Cada paso
 * sigue teniendo su botón, su ficha y su revisión: la receta no
 * esconde nada, adelanta trabajo. La voz no se graba sin el guion
 * aprobado.
 *
 * La receta elegida es la BASE y los interruptores mandan sobre ella
 * —igual que en el servidor (`resolver`)—, así la pantalla y la tanda
 * dicen lo mismo. Lo no opcional no lleva interruptor: la columna
 * vertebral de un vídeo no se apaga desde aquí.
 */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Loader2, Save, Star, Trash2 } from "lucide-react"
import { api } from "../../lib/api"
import type {
  CatalogoRecetas,
  FichaReceta,
  RecetaGuardada,
  TrabajoFicha,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { Insignia } from "../../components/ui/badge"
import { Entrada } from "../../components/ui/input"
import { Etiqueta } from "../../components/ui/etiqueta"
import { AreaTexto } from "../../components/ui/textarea"
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

/** La elección de una pestaña: la receta base y lo que se ha tocado. */
interface EleccionReceta {
  rid: string
  tareas: Record<string, boolean>
}

const VACIA: EleccionReceta = { rid: "", tareas: {} }

/** Qué corre de verdad: lo tocado aquí > la receta base > todo.
 * Espejo de `recetas.puestas_de` del servidor. */
function puestas_de(
  cat: CatalogoRecetas,
  pestana: string,
  eleccion: EleccionReceta,
): Record<string, boolean> {
  const base = cat.recetas.find(
    (r) => r.id === eleccion.rid && r.pestana === pestana,
  )
  const salida: Record<string, boolean> = {}
  for (const t of cat.tareas) {
    if (t.pestana !== pestana) continue
    if (t.id in eleccion.tareas) salida[t.id] = eleccion.tareas[t.id]
    else if (base && t.id in base.tareas) salida[t.id] = base.tareas[t.id]
    else salida[t.id] = t.de_fabrica
  }
  return salida
}

export function DialogoRecetas({
  pid,
  abierto,
  alCerrar,
  ocupado,
  alSeguir,
}: {
  pid: string
  abierto: boolean
  alCerrar: () => void
  ocupado: boolean
  alSeguir: (tid: string) => void
}) {
  const [ficha, setFicha] = useState<FichaReceta | null>(null)
  const [cat, setCat] = useState<CatalogoRecetas | null>(null)
  const [eleccion, setEleccion] = useState<Record<string, EleccionReceta>>({})
  const [lanzando, setLanzando] = useState<string | null>(null)

  const [guardar_abierto, setGuardarAbierto] = useState(false)
  const [guardar_pestana, setGuardarPestana] = useState("")
  const [nombre, setNombre] = useState("")
  const [nota, setNota] = useState("")
  const [por_defecto, setPorDefecto] = useState(false)
  const [enviando, setEnviando] = useState(false)

  const recargar_catalogo = () =>
    api
      .get<CatalogoRecetas>("/api/recetas")
      .then(setCat)
      .catch(() => setCat(null))

  useEffect(() => {
    if (!abierto) return
    setFicha(null)
    setCat(null)
    api
      .get<FichaReceta>(`/api/proyectos/${pid}/receta`)
      .then((f) => {
        setFicha(f)
        // la elección nace de lo que correría AHORA: la puesta por
        // defecto de cada pestaña ("" si juega con la de fábrica)
        const inicial: Record<string, EleccionReceta> = {}
        for (const [clave, p] of Object.entries(f.pestañas))
          inicial[clave] = { rid: p.receta?.id ?? "", tareas: {} }
        setEleccion(inicial)
      })
      .catch(() => setFicha(null))
    recargar_catalogo()
  }, [abierto, pid])

  const tocar = (pestana: string, tid: string, valor: boolean) =>
    setEleccion((prev) => {
      const e = prev[pestana] ?? VACIA
      return {
        ...prev,
        [pestana]: { rid: e.rid, tareas: { ...e.tareas, [tid]: valor } },
      }
    })

  const elegir = (pestana: string, rid: string) =>
    setEleccion((prev) => ({
      ...prev,
      [pestana]: { rid, tareas: {} },
    }))

  const lanzar = async (pestana: string, modo: "pendiente" | "todo") => {
    const e = eleccion[pestana] ?? VACIA
    const cuerpo: Record<string, unknown> = {
      modo,
      tareas: cat ? puestas_de(cat, pestana, e) : {},
    }
    if (e.rid) cuerpo.receta = e.rid
    setLanzando(pestana)
    try {
      const t = await api.post<TrabajoFicha>(
        `/api/proyectos/${pid}/receta/${pestana}`,
        cuerpo,
      )
      toast.success(`receta en marcha (${modo})`)
      alCerrar()
      alSeguir(t.id)
    } catch (err) {
      toast.error(String((err as Error).message ?? err))
    } finally {
      setLanzando(null)
    }
  }

  const abrir_guardar = (pestana: string) => {
    setGuardarPestana(pestana)
    setNombre("")
    setNota("")
    setPorDefecto(false)
    setGuardarAbierto(true)
  }

  const guardar = async () => {
    if (!cat) return
    const e = eleccion[guardar_pestana] ?? VACIA
    setEnviando(true)
    try {
      const r = await api.post<RecetaGuardada>("/api/recetas", {
        pestana: guardar_pestana,
        nombre,
        nota,
        por_defecto,
        tareas: puestas_de(cat, guardar_pestana, e),
      })
      toast.success(`receta «${r.nombre}» guardada`)
      setGuardarAbierto(false)
      await recargar_catalogo()
      elegir(guardar_pestana, r.id)
    } catch (err) {
      toast.error(String((err as Error).message ?? err))
    } finally {
      setEnviando(false)
    }
  }

  const fijar_defecto = async (pestana: string, rid: string) => {
    const receta = cat?.recetas.find((r) => r.id === rid)
    if (!receta) return
    try {
      await api.post("/api/recetas", {
        id: rid,
        pestana,
        nombre: receta.nombre,
        nota: receta.nota,
        tareas: receta.tareas,
        por_defecto: true,
      })
      toast.success(`«${receta.nombre}» queda como receta por defecto`)
      recargar_catalogo()
    } catch (err) {
      toast.error(String((err as Error).message ?? err))
    }
  }

  const borrar = async (pestana: string, rid: string) => {
    try {
      await api.borrar(`/api/recetas/${rid}`)
      toast.success("receta borrada")
      await recargar_catalogo()
      elegir(pestana, "")
    } catch (err) {
      toast.error(String((err as Error).message ?? err))
    }
  }

  return (
    <>
      <Dialogo abierto={abierto} alCambiar={(a) => (a ? null : alCerrar())}>
        <ContenidoDialogo className="max-w-2xl">
          <CabeceraDialogo>
            <TituloDialogo>De una tirada</TituloDialogo>
            <DescripcionDialogo>
              Lo que en pantallas son muchos botones en el orden correcto,
              aquí es una lista. Cada paso sigue teniendo su botón, su
              ficha y su revisión: la receta no esconde nada, adelanta
              trabajo. La voz no se graba sin el guion aprobado.
            </DescripcionDialogo>
          </CabeceraDialogo>
          {!ficha || !cat ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(ficha.pestañas).map(([clave, pestana]) => {
                const e = eleccion[clave] ?? VACIA
                const puestas = puestas_de(cat, clave, e)
                const guardadas = cat.recetas.filter(
                  (r) => r.pestana === clave,
                )
                const defecto = cat.por_defecto[clave]
                const pendientes = pestana.tareas.filter(
                  (t) => t.estado !== "ok" && puestas[t.id] !== false,
                ).length
                return (
                  <div key={clave} className="rounded-md border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold">{pestana.nombre}</p>
                      {pendientes > 0 ? (
                        <Insignia variante="aviso">
                          {pendientes} pendiente{pendientes > 1 ? "s" : ""}
                        </Insignia>
                      ) : (
                        <Insignia variante="exito">al día</Insignia>
                      )}
                      <div className="ml-auto flex gap-2">
                        <Boton
                          tamano="pequeno"
                          deshabilitado={ocupado || lanzando !== null
                            || pendientes === 0}
                          title="Corre lo que falta y se salta lo que ya está al día"
                          onClick={() => lanzar(clave, "pendiente")}
                        >
                          {lanzando === clave ? (
                            <Loader2 className="animate-spin" />
                          ) : null}
                          Generar lo pendiente
                        </Boton>
                        <Boton
                          tamano="pequeno"
                          variante="contorno"
                          deshabilitado={ocupado || lanzando !== null}
                          title="Lo corre todo, aunque esté al día (paga otra vez)"
                          onClick={() => lanzar(clave, "todo")}
                        >
                          Generar todo
                        </Boton>
                      </div>
                    </div>

                    {/* la receta: base de esta pestaña */}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Selector
                        valor={e.rid || ""}
                        alCambiar={(v) => elegir(clave, v === "todo" ? "" : v)}
                      >
                        <DisparadorSelector className="h-8 w-52 text-xs">
                          <ValorSelector />
                        </DisparadorSelector>
                        <ContenidoSelector>
                          <Opcion valor="todo">
                            Todo (de fábrica)
                          </Opcion>
                          {guardadas.map((r) => (
                            <Opcion key={r.id} valor={r.id}>
                              {r.nombre}
                              {defecto === r.id ? " ★" : ""}
                            </Opcion>
                          ))}
                        </ContenidoSelector>
                      </Selector>
                      <Boton
                        variante="fantasma"
                        tamano="pequeno"
                        title="Guardar esta combinación con nombre, para la próxima"
                        onClick={() => abrir_guardar(clave)}
                      >
                        <Save /> Guardar como…
                      </Boton>
                      {e.rid && (
                        <>
                          <Boton
                            variante="fantasma"
                            tamano="pequeno"
                            deshabilitado={defecto === e.rid}
                            title={
                              defecto === e.rid
                                ? "Ya es la receta por defecto de esta pestaña"
                                : "Que esta pestaña use esta receta sin elegirla"
                            }
                            onClick={() => fijar_defecto(clave, e.rid)}
                          >
                            <Star /> Por defecto
                          </Boton>
                          <Boton
                            variante="fantasma"
                            tamano="pequeno"
                            title="Borrar la receta guardada (los vídeos no se tocan)"
                            onClick={() => borrar(clave, e.rid)}
                          >
                            <Trash2 /> Borrar
                          </Boton>
                        </>
                      )}
                    </div>

                    <ul className="mt-2 space-y-1.5">
                      {pestana.tareas.map((t) => (
                        <li
                          key={t.id}
                          className={
                            "flex flex-wrap items-center gap-2 text-xs " +
                            (puestas[t.id] === false ? "opacity-40" : "")
                          }
                        >
                          <span
                            className={`h-2 w-2 shrink-0 rounded-full ${
                              t.estado === "ok"
                                ? "bg-emerald-500"
                                : t.estado === "obsoleto"
                                  ? "bg-amber-500"
                                  : "bg-muted-foreground/25"
                            }`}
                          />
                          <span className="font-medium">{t.nombre}</span>
                          {t.cuesta && (
                            <span
                              title="gasta dinero al correr"
                              className="text-amber-600"
                            >
                              ¢
                            </span>
                          )}
                          {t.estado === "obsoleto" && (
                            <Insignia variante="aviso">obsoleto</Insignia>
                          )}
                          {t.aprobado && (
                            <Insignia variante="exito">✓</Insignia>
                          )}
                          {puestas[t.id] === false && (
                            <Insignia variante="secundario">apagada</Insignia>
                          )}
                          <span className="min-w-0 flex-1 truncate text-muted-foreground">
                            {t.porque}
                          </span>
                          {t.opcional && (
                            <label
                              className="inline-flex cursor-pointer items-center gap-1.5"
                              title="Una receta puede apagarla; lo que sostiene el vídeo no se apaga"
                            >
                              <input
                                type="checkbox"
                                className="h-3.5 w-3.5 accent-primary"
                                checked={puestas[t.id] !== false}
                                onChange={(ev) =>
                                  tocar(clave, t.id, ev.target.checked)
                                }
                              />
                              <span className="text-muted-foreground">
                                corre
                              </span>
                            </label>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })}
            </div>
          )}
        </ContenidoDialogo>
      </Dialogo>

      {/* guardar como receta */}
      <Dialogo abierto={guardar_abierto} alCambiar={setGuardarAbierto}>
        <ContenidoDialogo>
          <CabeceraDialogo>
            <TituloDialogo>Guardar como receta</TituloDialogo>
            <DescripcionDialogo>
              Se guarda lo que hay en pantalla ahora mismo —lo puesto y lo
              apagado— con el nombre que le des. Es del canal, no de este
              vídeo.
            </DescripcionDialogo>
          </CabeceraDialogo>
          <div className="space-y-4">
            <div className="space-y-2">
              <Etiqueta htmlFor="receta-nombre">Nombre</Etiqueta>
              <Entrada
                id="receta-nombre"
                valor={nombre}
                alCambiar={(ev) => setNombre(ev.target.value)}
                placeholder="Sólo imágenes, sin revisar audio…"
              />
            </div>
            <div className="space-y-2">
              <Etiqueta htmlFor="receta-nota">Nota (opcional)</Etiqueta>
              <AreaTexto
                id="receta-nota"
                filas={2}
                valor={nota}
                alCambiar={(ev) => setNota(ev.target.value)}
                placeholder="para qué sirve, cuándo usarla…"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={por_defecto}
                onChange={(ev) => setPorDefecto(ev.target.checked)}
              />
              que sea la receta por defecto de esta pestaña
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Boton
              variante="contorno"
              onClick={() => setGuardarAbierto(false)}
            >
              Cancelar
            </Boton>
            <Boton
              onClick={guardar}
              deshabilitado={enviando || nombre.trim() === ""}
            >
              {enviando ? <Loader2 className="animate-spin" /> : <Save />}
              Guardar
            </Boton>
          </div>
        </ContenidoDialogo>
      </Dialogo>
    </>
  )
}
