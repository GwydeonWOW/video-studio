/** El grafismo por plano: dirección, redactor, cartelas y diseño.

Un diálogo con cuatro pestañas, la unidad sigue siendo el PLANO. Las
decisiones se guardan por unidad (ensucian sólo el plano tocado), el
diseño de rótulos en los params de callouts (no cuesta imágenes).
*/
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Compass, Eraser, FileText, Layers, Loader2, Palette, Sparkles } from "lucide-react"
import { api } from "../../lib/api"
import { usarTrabajo } from "../../lib/trabajos"
import type {
  FichaCartela,
  FichaCartelas,
  FichaDiseno,
  PlantillaCartela,
  PlanoGrafismo,
  RespuestaPlan,
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
  ValorSelector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
} from "../../components/ui/selector"

export type PestanaGrafismo = "direccion" | "redactor" | "cartelas" | "diseno"

interface Props {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  pestana: PestanaGrafismo
  alPestana: (pestana: PestanaGrafismo) => void
  recargar: () => void
}

export function DialogoGrafismo({ pid, abierto, alCambiar, pestana, alPestana, recargar }: Props) {
  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-h-[88vh] max-w-4xl overflow-y-auto">
        <CabeceraDialogo>
          <TituloDialogo className="flex items-center gap-2">
            <Palette className="size-4" /> Grafismo por plano
          </TituloDialogo>
          <DescripcionDialogo>
            Qué se ve en cada plano y cómo se escribe. Las decisiones son por
            plano: ensucian sólo el tocado, y quien regenera es la persona con
            el coste delante.
          </DescripcionDialogo>
        </CabeceraDialogo>
        <Pestanas valor={pestana} alCambiar={(v) => alPestana(v as PestanaGrafismo)}>
          <ListaPestanas className="w-full">
            <DisparadorPestanas valor="direccion">
              <Compass className="mr-1 inline size-3.5" /> Dirección
            </DisparadorPestanas>
            <DisparadorPestanas valor="redactor">
              <FileText className="mr-1 inline size-3.5" /> Redactor
            </DisparadorPestanas>
            <DisparadorPestanas valor="cartelas">
              <Layers className="mr-1 inline size-3.5" /> Cartelas
            </DisparadorPestanas>
            <DisparadorPestanas valor="diseno">
              <Palette className="mr-1 inline size-3.5" /> Diseño
            </DisparadorPestanas>
          </ListaPestanas>
          <ContenidoPestanas valor="direccion" className="mt-4">
            <PestanaPlan
              pid={pid}
              tipo="direccion"
              titulo="Qué se ve en cada plano"
              detalle="La capa que distingue a un plano de su vecino: se añade al prompt armado. Vacío = sin dirección."
              placeholder="primer plano de la caja abriéndose, luz cálida lateral"
              filas={4}
              recargar={recargar}
            />
          </ContenidoPestanas>
          <ContenidoPestanas valor="redactor" className="mt-4">
            <PestanaPlan
              pid={pid}
              tipo="redactor"
              titulo="El prompt escrito entero"
              detalle="Lo que redacte SUSTITUYE al prompt armado del plano (la dirección se le pega al final)."
              placeholder="Flat vector illustration: wide shot of..."
              filas={5}
              recargar={recargar}
            />
          </ContenidoPestanas>
          <ContenidoPestanas valor="cartelas" className="mt-4">
            <PestanaCartelas pid={pid} recargar={recargar} />
          </ContenidoPestanas>
          <ContenidoPestanas valor="diseno" className="mt-4">
            <PestanaDiseno pid={pid} recargar={recargar} />
          </ContenidoPestanas>
        </Pestanas>
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* ------------------------------------------------ plan por plano (texto) */

function PestanaPlan({
  pid,
  tipo,
  titulo,
  detalle,
  placeholder,
  filas,
  recargar,
}: {
  pid: string
  tipo: "direccion" | "redactor"
  titulo: string
  detalle: string
  placeholder: string
  filas: number
  recargar: () => void
}) {
  const [planos, setPlanos] = useState<PlanoGrafismo[]>([])
  const [guardado, setGuardado] = useState<Record<string, string>>({})
  const [borrador, setBorrador] = useState<Record<string, string>>({})
  const [cargando, setCargando] = useState(true)
  const [tid, setTid] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const r = await api.get<RespuestaPlan<string>>(`/api/proyectos/${pid}/${tipo}`)
      setPlanos(r.planos ?? [])
      setGuardado(r.plan ?? {})
      setBorrador((previo) => {
        const mezcla: Record<string, string> = {}
        for (const plano of r.planos ?? []) mezcla[plano.id] = previo[plano.id] ?? r.plan?.[plano.id] ?? ""
        return mezcla
      })
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setCargando(false)
    }
  }, [pid, tipo])

  useEffect(() => {
    if (!tid) cargar()
  }, [cargar, tid])

  const alTerminar = (ficha: TrabajoFicha) => {
    setTid(null)
    if (ficha.estado === "hecho" && ficha.resultado) {
      const propuesta = ficha.resultado as RespuestaPlan<string>
      const nuevo = { ...guardado }
      for (const [id, texto] of Object.entries(propuesta.plan ?? {})) nuevo[id] = texto
      setGuardado(nuevo)
      setBorrador({ ...borrador, ...Object.fromEntries(Object.entries(propuesta.plan ?? {})) })
      const avisos = propuesta.avisos ?? []
      toast.success(`${Object.keys(propuesta.plan ?? {}).length} plano(s) propuesto(s)`, {
        description: avisos.length ? avisos.slice(0, 3).join(" · ") : "repásalos y guarda",
      })
    } else if (ficha.estado === "fallo") {
      toast.error(ficha.error ?? "la propuesta falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })
  const cambios = planos.filter((p) => (borrador[p.id] ?? "") !== (guardado[p.id] ?? ""))

  const guardar = async () => {
    const plan: Record<string, string> = {}
    for (const plano of cambios) plan[plano.id] = borrador[plano.id] ?? ""
    try {
      const r = await api.put<RespuestaPlan<string>>(`/api/proyectos/${pid}/${tipo}`, { plan })
      setGuardado(r.plan ?? {})
      setBorrador((previo) => ({ ...previo, ...Object.fromEntries(Object.entries(r.plan ?? {})) }))
      toast.success(
        `${r.tocados?.length ?? 0} plano(s) guardado(s)${r.avisos?.length ? " — " + r.avisos.join(" · ") : ""}`,
      )
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  if (cargando) return <Cargando />
  if (planos.length === 0) return <SinGuion />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">{detalle}</p>
        <div className="ml-auto flex gap-2">
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={!!trabajo && trabajo.estado === "ejecutando"}
            onClick={async () => {
              try {
                const trabajo = await api.post<{ id: string }>(`/api/proyectos/${pid}/${tipo}/proponer`)
                setTid(trabajo.id)
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
            {titulo.includes("entero") ? "Redactar con IA" : "Proponer con IA"}
          </Boton>
          <Boton tamano="pequeno" deshabilitado={cambios.length === 0} onClick={guardar}>
            Guardar {cambios.length > 0 ? `(${cambios.length})` : ""}
          </Boton>
        </div>
      </div>
      {trabajo?.estado === "ejecutando" && (
        <p className="text-xs text-muted-foreground">
          <Loader2 className="mr-1 inline size-3 animate-spin" />
          {trabajo.eventos ?? 0} evento(s): el agente está con todos los planos delante…
        </p>
      )}
      <div className="space-y-2">
        {planos.map((plano) => (
          <div key={plano.id} className="rounded-md border bg-card p-2">
            <div className="mb-1 flex items-center gap-2">
              <Insignia variante="secundario">{plano.id}</Insignia>
              <span className="truncate text-xs text-muted-foreground" title={plano.narracion}>
                {plano.narracion}
              </span>
              {(borrador[plano.id] ?? "") !== (guardado[plano.id] ?? "") && (
                <Insignia variante="contorno" className="ml-auto shrink-0">editado</Insignia>
              )}
            </div>
            <AreaTexto
              valor={borrador[plano.id] ?? ""}
              alCambiar={(e) => setBorrador({ ...borrador, [plano.id]: e.target.value })}
              filas={filas}
              placeholder={placeholder}
              className="text-xs"
            />
            {(guardado[plano.id] ?? "") !== "" && (borrador[plano.id] ?? "") === (guardado[plano.id] ?? "") && (
              <Boton
                variante="fantasma"
                tamano="pequeno"
                className="mt-1"
                onClick={() => setBorrador({ ...borrador, [plano.id]: "" })}
              >
                <Eraser className="mr-1 size-3" /> Quitar
              </Boton>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- cartelas */

/** El icono del selector cuando la cartela no lleva: radix no admite "".
 * Un icono inventado no se dibuja, así que el catálogo es cerrado. */
const SIN_ICONO = "__sin__"

/** El texto de un dato que puede venir en lista (el agente propone arrays). */
const como_texto = (v: string | string[] | undefined) =>
  Array.isArray(v) ? v.join(" ") : (v ?? "")

/** Los datos en blanco de una plantilla. El primer campo obligatorio se
 * siembra con el título del plano, que es lo que más veces acierta. */
function datos_en_blanco(
  plantilla: PlantillaCartela,
  semilla: string,
): Record<string, string | string[]> {
  const datos: Record<string, string | string[]> = {}
  let primera = true
  for (const [campo, info] of Object.entries(plantilla.campos)) {
    if (plantilla.lista && plantilla.lista[0] === campo) {
      datos[campo] = Array.from({ length: plantilla.lista[1] }, () => "")
    } else if (campo === "icono") {
      continue
    } else {
      datos[campo] = primera && info.obligatorio ? semilla : ""
      primera = false
    }
  }
  return datos
}

function PestanaCartelas({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaCartelas | null>(null)
  const [borrador, setBorrador] = useState<Record<string, FichaCartela | null>>({})
  const [permitidas, setPermitidas] = useState<string[]>([])
  const [cargando, setCargando] = useState(true)
  const [tid, setTid] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const r = await api.get<FichaCartelas>(`/api/proyectos/${pid}/cartelas`)
      setFicha(r)
      setBorrador({ ...r.plan })
      setPermitidas(r.plantillas_activas ?? [])
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
      const propuesta = trabajo.resultado as { plan: Record<string, FichaCartela>; avisos: string[] }
      setBorrador((previo) => ({ ...previo, ...propuesta.plan }))
      toast.success(`${Object.keys(propuesta.plan ?? {}).length} cartela(s) propuesta(s)`, {
        description: (propuesta.avisos ?? []).slice(0, 3).join(" · ") || "repásalas y guarda",
      })
    } else if (trabajo.estado === "fallo") {
      toast.error(trabajo.error ?? "el plan de cartelas falló")
    }
  }

  const { ficha: trabajo } = usarTrabajo({ tid, alTerminar })
  if (cargando) return <Cargando />
  if (!ficha) return null
  if ((ficha.planos ?? []).length === 0) return <SinGuion />
  const guardadas = ficha.plan ?? {}
  const cambios = Object.keys(borrador).filter((id) => JSON.stringify(borrador[id] ?? null) !== JSON.stringify(guardadas[id] ?? null))
  const cartelas_activas = Object.values(borrador).filter(Boolean).length
  const plantillas = ficha.plantillas ?? []
  const plantilla_de: Record<string, PlantillaCartela> = {}
  for (const p of plantillas) plantilla_de[p.id] = p
  const defecto = plantilla_de[ficha.defecto] ? ficha.defecto : plantillas[0]?.id ?? ""

  const permitidas_cambiadas =
    JSON.stringify([...permitidas].sort()) !==
    JSON.stringify([...(ficha.plantillas_activas ?? [])].sort())

  const guardar = async () => {
    const cuerpo: { plan?: Record<string, FichaCartela | null>; plantillas?: string[] } = {}
    if (cambios.length > 0) {
      const plan: Record<string, FichaCartela | null> = {}
      for (const id of cambios) plan[id] = borrador[id] ?? null
      cuerpo.plan = plan
    }
    if (permitidas_cambiadas) cuerpo.plantillas = permitidas
    try {
      const r = await api.put<{ plan: Record<string, FichaCartela>; tocados?: string[]; avisos?: string[]; obsoletos?: string[]; plantillas_activas?: string[] }>(
        `/api/proyectos/${pid}/cartelas`,
        cuerpo,
      )
      setFicha({ ...ficha, plan: r.plan, obsoletos: r.obsoletos ?? [],
                 plantillas_activas: r.plantillas_activas ?? permitidas })
      toast.success(
        `${r.tocados?.length ?? 0} plano(s) tocado(s)${r.avisos?.length ? " — " + r.avisos.join(" · ") : ""}`,
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
          Un plano de <b>texto escrito</b> palabra a palabra sobre la imagen del plano.{" "}
          {cartelas_activas}/{ficha.max_cartelas} de {ficha.planos.length} escenas.
        </p>
        <div className="ml-auto flex gap-2">
          <Boton
            variante="secundario"
            tamano="pequeno"
            deshabilitado={trabajo?.estado === "ejecutando"}
            onClick={async () => {
              try {
                const trabajo = await api.post<{ id: string }>(`/api/proyectos/${pid}/cartelas/plan`)
                setTid(trabajo.id)
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
            Planear con IA
          </Boton>
          <Boton
            tamano="pequeno"
            deshabilitado={cambios.length === 0 && !permitidas_cambiadas}
            onClick={guardar}
          >
            Guardar {cambios.length > 0 ? `(${cambios.length})` : ""}
          </Boton>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground">
          Plantillas que el agente puede proponer:
        </span>
        {plantillas.map((p) => {
          const todas = permitidas.length === 0
          const on = todas || permitidas.includes(p.id)
          return (
            <Boton
              key={p.id}
              variante={on ? "secundario" : "fantasma"}
              tamano="pequeno"
              title={p.cuando}
              onClick={() => {
                if (todas) {
                  // partir de "todas" y excluir esta
                  setPermitidas(plantillas.map((q) => q.id).filter((x) => x !== p.id))
                } else if (permitidas.includes(p.id)) {
                  const resto = permitidas.filter((x) => x !== p.id)
                  // vacío vuelve a significar "todas"
                  setPermitidas(resto.length === 0 ? [] : resto)
                } else {
                  const suma = [...permitidas, p.id]
                  setPermitidas(suma.length === plantillas.length ? [] : suma)
                }
              }}
            >
              {p.nombre}
            </Boton>
          )
        })}
        <span className="text-xs text-muted-foreground">
          {permitidas.length === 0
            ? "(todas)"
            : `(${permitidas.length}/${plantillas.length})`}
        </span>
      </div>
      <div className="space-y-2">
        {ficha.planos.map((plano) => {
          const ficha_cartela = borrador[plano.id] ?? null
          const plantilla_id = ficha_cartela?.plantilla ?? ""
          const plantilla = plantilla_id ? plantilla_de[plantilla_id] : undefined
          const campo_lista = plantilla?.lista?.[0]
          const poner_dato = (campo: string, valor: string | string[]) => {
            if (!ficha_cartela) return
            setBorrador({
              ...borrador,
              [plano.id]: { ...ficha_cartela, datos: { ...ficha_cartela.datos, [campo]: valor } },
            })
          }
          return (
            <div key={plano.id} className="rounded-md border bg-card p-2">
              <div className="flex flex-wrap items-center gap-2">
                <Insignia variante="secundario">{plano.id}</Insignia>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={plano.narracion}>
                  {plano.narracion}
                </span>
                <Boton
                  variante={ficha_cartela ? "secundario" : "fantasma"}
                  tamano="pequeno"
                  onClick={() =>
                    setBorrador({
                      ...borrador,
                      [plano.id]: ficha_cartela
                        ? null
                        : {
                            plantilla: defecto,
                            datos: datos_en_blanco(plantilla_de[defecto], plano.titulo || ""),
                          },
                    })
                  }
                >
                  {ficha_cartela ? "Quitar cartela" : "Hacer cartela"}
                </Boton>
              </div>
              {ficha_cartela && plantilla && (
                <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_260px]">
                  <div className="space-y-2">
                    <div className="grid grid-cols-3 gap-1 sm:grid-cols-5">
                      {plantillas.map((p) => (
                        <Boton
                          key={p.id}
                          variante={p.id === plantilla_id ? "defecto" : "fantasma"}
                          tamano="pequeno"
                          className="h-auto flex-col gap-1 p-1"
                          title={p.cuando}
                          onClick={() =>
                            setBorrador({
                              ...borrador,
                              [plano.id]: {
                                plantilla: p.id,
                                datos: datos_en_blanco(p, plano.titulo || ""),
                              },
                            })
                          }
                        >
                          {/* la muestra la dibuja el MISMO código que la
                              cartela de verdad: lo que se ve es lo que sale */}
                          <div
                            className="h-10 w-full overflow-hidden rounded-sm bg-muted [&_svg]:h-full [&_svg]:w-full"
                            dangerouslySetInnerHTML={{ __html: p.svg }}
                          />
                          <span className="w-full truncate text-[10px]">{p.nombre}</span>
                        </Boton>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground">{plantilla.cuando}</p>
                    {Object.entries(plantilla.campos).map(([campo, info]) => {
                      if (campo === campo_lista && plantilla.lista) {
                        const [, minimo, maximo] = plantilla.lista
                        const lineas = Array.isArray(ficha_cartela.datos?.[campo])
                          ? (ficha_cartela.datos[campo] as string[])
                          : Array.from({ length: minimo }, () => "")
                        return (
                          <div key={campo} className="space-y-1">
                            <div className="flex items-center gap-2">
                              <Etiqueta className="text-xs">
                                {campo}
                                {info.obligatorio ? " *" : ""}
                              </Etiqueta>
                              {lineas.length < maximo && (
                                <Boton
                                  variante="fantasma"
                                  tamano="pequeno"
                                  className="h-5 px-1.5 text-[10px]"
                                  onClick={() => poner_dato(campo, [...lineas, ""])}
                                >
                                  + línea
                                </Boton>
                              )}
                            </div>
                            {lineas.map((linea, i) => (
                              <div key={i} className="flex items-center gap-1">
                                <span className="w-4 text-[11px] text-muted-foreground">{i + 1}</span>
                                <Entrada
                                  valor={linea}
                                  maxLength={info.tope}
                                  className="text-xs"
                                  alCambiar={(e) =>
                                    poner_dato(
                                      campo,
                                      lineas.map((l, j) => (j === i ? e.target.value : l)),
                                    )
                                  }
                                />
                                {lineas.length > minimo && (
                                  <Boton
                                    variante="fantasma"
                                    tamano="pequeno"
                                    className="h-6 px-1.5"
                                    onClick={() => poner_dato(campo, lineas.filter((_, j) => j !== i))}
                                  >
                                    ×
                                  </Boton>
                                )}
                              </div>
                            ))}
                          </div>
                        )
                      }
                      if (campo === "icono") {
                        const valor = como_texto(ficha_cartela.datos?.[campo])
                        return (
                          <div key={campo} className="grid grid-cols-[90px_1fr] items-center gap-2">
                            <Etiqueta className="text-xs">icono</Etiqueta>
                            <Selector
                              valor={valor || SIN_ICONO}
                              alCambiar={(v) => poner_dato(campo, v === SIN_ICONO ? "" : v)}
                            >
                              <DisparadorSelector className="h-7 text-xs">
                                <ValorSelector />
                              </DisparadorSelector>
                              <ContenidoSelector>
                                <Opcion valor={SIN_ICONO}>(sin icono)</Opcion>
                                {(ficha.iconos ?? []).map((ic) => (
                                  <Opcion key={ic} valor={ic}>
                                    {ic.replace(/_/g, " ")}
                                  </Opcion>
                                ))}
                              </ContenidoSelector>
                            </Selector>
                          </div>
                        )
                      }
                      return (
                        <div key={campo} className="grid grid-cols-[90px_1fr] items-center gap-2">
                          <Etiqueta className="text-xs">
                            {campo}
                            {info.obligatorio ? " *" : ""}
                          </Etiqueta>
                          <Entrada
                            valor={como_texto(ficha_cartela.datos?.[campo])}
                            maxLength={info.tope}
                            alCambiar={(e) => poner_dato(campo, e.target.value)}
                            className="text-xs"
                          />
                        </div>
                      )
                    })}
                  </div>
                  <div className="overflow-hidden rounded border bg-muted">
                    {guardadas[plano.id] ? (
                      <img
                        src={`/api/proyectos/${pid}/cartelas/vista?plano=${plano.id}`}
                        alt={`cartela ${plano.id}`}
                        className="w-full"
                      />
                    ) : (
                      <p className="p-2 text-[11px] text-muted-foreground">
                        La vista se dibuja al guardar (así se enseña lo que se manda).
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- diseño */

const PAPELES: { clave: keyof FichaDiseno["paleta"]; nombre: string }[] = [
  { clave: "acento", nombre: "Acento" },
  { clave: "texto", nombre: "Texto" },
  { clave: "fondo", nombre: "Fondo" },
  { clave: "velo", nombre: "Velo" },
]

function PestanaDiseno({ pid, recargar }: { pid: string; recargar: () => void }) {
  const [ficha, setFicha] = useState<FichaDiseno | null>(null)
  const [cargando, setCargando] = useState(true)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      setFicha(await api.get<FichaDiseno>(`/api/proyectos/${pid}/callouts/diseno`))
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
  const diseno = ficha.elegido
  const tam = ficha.subtitulo_tam
  const url_vista = `/api/proyectos/${pid}/callouts/vista?plano=muestra&texto=${encodeURIComponent(
    "Un vídeo explica mejor que mil palabras",
  )}&diseno=${encodeURIComponent(diseno)}&tam=${encodeURIComponent(tam)}`

  const guardar = async (cambios: Record<string, unknown>) => {
    try {
      const nueva = await api.put<FichaDiseno>(`/api/proyectos/${pid}/callouts/plan`, cambios)
      setFicha(nueva)
      toast.success("grafismo guardado: rehacer rótulos es gratis (no paga imágenes)")
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        UN grafismo para el vídeo: el mismo set envuelve los rótulos y escribe las cartelas. Cambiarlo no cuesta
        imágenes — rehacer rótulos y montar es lo único que toca.
      </p>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(ficha.sets).map(([id, set]) => (
              <button
                key={id}
                onClick={() => guardar({ diseno: id })}
                className={`rounded-md border p-2 text-left text-xs transition-colors hover:bg-accent/10 ${
                  id === diseno ? "border-primary ring-1 ring-primary" : ""
                }`}
              >
                <span className="font-medium">{set.nombre}</span>
                {id === ficha.sugerido && <Insignia variante="contorno" className="ml-1">sugerido</Insignia>}
                <p className="mt-0.5 text-muted-foreground">{set.descripcion}</p>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Etiqueta className="text-xs">Tamaño del texto</Etiqueta>
            {Object.keys(ficha.tamanos).map((t) => (
              <Boton
                key={t}
                variante={t === tam ? "defecto" : "fantasma"}
                tamano="pequeno"
                onClick={() => guardar({ subtitulo_tam: t })}
              >
                {t}
              </Boton>
            ))}
          </div>
          <div className="space-y-1.5">
            <Etiqueta className="text-xs">Fijar colores a mano (vacío = deriva del estilo)</Etiqueta>
            {PAPELES.map(({ clave, nombre }) => (
              <div key={clave} className="flex items-center gap-2">
                <span className="w-16 text-xs text-muted-foreground">{nombre}</span>
                <span
                  className="size-4 rounded border"
                  style={{ background: (ficha.fijados as Record<string, string>)[clave] ?? ficha.paleta[clave] }}
                />
                <Entrada
                  valor={(ficha.fijados as Record<string, string>)[clave] ?? ""}
                  alCambiar={(e) => setFicha({ ...ficha, fijados: { ...ficha.fijados, [clave]: e.target.value } })}
                  placeholder={ficha.paleta[clave]}
                  className="h-7 w-40 font-mono text-xs"
                />
                {(ficha.fijados as Record<string, string>)[clave] && (
                  <Boton
                    variante="fantasma"
                    tamano="pequeno"
                    onClick={() => guardar({ paleta: { fijados: { [clave]: "" } } })}
                  >
                    <Eraser className="size-3" />
                  </Boton>
                )}
              </div>
            ))}
            <Boton
              variante="secundario"
              tamano="pequeno"
              deshabilitado={Object.values(ficha.fijados).every((v) => !v)}
              onClick={() => guardar({ paleta: { fijados: Object.fromEntries(PAPELES.map((p) => [p.clave, (ficha.fijados as Record<string, string>)[p.clave] ?? ""])) } })}
            >
              Guardar colores
            </Boton>
          </div>
        </div>
        <div className="space-y-2">
          <div className="overflow-hidden rounded border bg-muted">
            <img src={url_vista} alt="vista del rótulo" className="w-full" />
          </div>
          <p className="text-[11px] text-muted-foreground">
            La vista con el set «{ficha.sets[diseno]?.nombre}» y tamaño «{tam}».
            {ficha.obsoleto && " · los rótulos guardados son de otro diseño: rehaz el paso."}
          </p>
        </div>
      </div>
    </div>
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
