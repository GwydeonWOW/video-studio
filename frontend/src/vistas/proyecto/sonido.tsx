/** El sonido del vídeo y las transiciones entre planos (Fase G).

Dos diálogos:
- «Sonido» (tres pestañas): la música (buscar por tono, escuchar y
  poner; o banda por tramos según el arco del vídeo), y los efectos de
  sonido por papel (surtir, oír la muestra del banco, vetar).
- «Transiciones»: el catálogo con el efecto xfade que correrá de
  verdad en el render, la duración y el reparto que ha resuelto el
  motor.

BUSCAR SALE A LA RED CON UNA PERSONA DELANTE (escuchando); RENDERIZAR
no sale a la red: lee el banco. Vetar muerde en las dos.
*/
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import {
  AudioLines,
  Ban,
  Check,
  Film,
  Loader2,
  Music,
  RefreshCw,
  X,
  Zap,
} from "lucide-react"
import { api } from "../../lib/api"
import { usarTrabajo } from "../../lib/trabajos"
import { segundos } from "../../lib/utils"
import type {
  ArcoSonido,
  EfectoSurtido,
  FichaSonido,
  FichaTransiciones,
  TemaMusica,
  TrabajoFicha,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
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

export type PestanaSonido = "musica" | "banda" | "efectos"

interface PropsSonido {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  pestana: PestanaSonido
  alPestana: (pestana: PestanaSonido) => void
  recargar: () => void
}

export function DialogoSonido({
  pid,
  abierto,
  alCambiar,
  pestana,
  alPestana,
  recargar,
}: PropsSonido) {
  const [ficha, setFicha] = useState<FichaSonido | null>(null)

  const cargar = useCallback(async () => {
    try {
      setFicha(await api.get<FichaSonido>(`/api/proyectos/${pid}/sonido`))
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }, [pid])

  useEffect(() => {
    if (abierto) cargar()
  }, [abierto, cargar])

  const refrescar = () => {
    cargar()
    recargar()
  }

  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <CabeceraDialogo>
          <TituloDialogo className="flex items-center gap-2">
            <AudioLines className="size-4" /> Sonido
          </TituloDialogo>
          <DescripcionDialogo>
            Música por tono, banda por tramos y efectos por papel. Buscar
            sale a la red y se hace escuchando; el render sólo lee el banco.
            Vetar un efecto muerde en los dos.
          </DescripcionDialogo>
        </CabeceraDialogo>
        {ficha ? (
          <Pestanas
            valor={pestana}
            alCambiar={(v) => alPestana(v as PestanaSonido)}
          >
            <ListaPestanas className="w-full">
              <DisparadorPestanas valor="musica">
                <Music className="mr-1 inline size-3.5" /> Música
              </DisparadorPestanas>
              <DisparadorPestanas valor="banda">
                <AudioLines className="mr-1 inline size-3.5" /> Banda
              </DisparadorPestanas>
              <DisparadorPestanas valor="efectos">
                <Zap className="mr-1 inline size-3.5" /> Efectos
              </DisparadorPestanas>
            </ListaPestanas>
            <ContenidoPestanas valor="musica" className="mt-4">
              <PestanaMusica pid={pid} ficha={ficha} recargar={refrescar} />
            </ContenidoPestanas>
            <ContenidoPestanas valor="banda" className="mt-4">
              <PestanaBanda pid={pid} ficha={ficha} recargar={refrescar} />
            </ContenidoPestanas>
            <ContenidoPestanas valor="efectos" className="mt-4">
              <PestanaEfectos pid={pid} ficha={ficha} recargar={refrescar} />
            </ContenidoPestanas>
          </Pestanas>
        ) : (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> cargando el sonido…
          </div>
        )}
      </ContenidoDialogo>
    </Dialogo>
  )
}

/* --------------------------------------------------------------- música */

function PestanaMusica({
  pid,
  ficha,
  recargar,
}: {
  pid: string
  ficha: FichaSonido
  recargar: () => void
}) {
  const claves = Object.keys(ficha.animos)
  const [animo, setAnimo] = useState(claves[0] ?? "")
  const [temas, setTemas] = useState<TemaMusica[]>([])
  const [buscando, setBuscando] = useState(false)
  const [poniendo, setPoniendo] = useState<string | null>(null)
  const [lufs, setLufs] = useState(ficha.lufs)
  const [musica_db, setMusicaDb] = useState(ficha.musica_db)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    setLufs(ficha.lufs)
    setMusicaDb(ficha.musica_db)
  }, [ficha.lufs, ficha.musica_db])

  async function buscar() {
    setBuscando(true)
    try {
      const r = await api.post<{ temas: TemaMusica[] }>(
        `/api/proyectos/${pid}/sonido/musica`,
        { animo },
      )
      setTemas(r.temas ?? [])
      if (!r.temas?.length) toast.info("Jamendo no devolvió nada con ese tono")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setBuscando(false)
    }
  }

  async function poner(tema: TemaMusica) {
    setPoniendo(tema.id)
    try {
      await api.put(`/api/proyectos/${pid}/sonido`, { musica: tema })
      toast.success(`puesto «${tema.titulo}»`)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setPoniendo(null)
    }
  }

  async function quitar() {
    try {
      await api.put(`/api/proyectos/${pid}/sonido`, { musica: {} })
      toast.success("sin música")
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  async function alternar() {
    try {
      await api.put(`/api/proyectos/${pid}/sonido`, { activo: !ficha.activo })
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  async function guardarNiveles() {
    setGuardando(true)
    try {
      await api.put(`/api/proyectos/${pid}/sonido`, { lufs, musica_db })
      toast.success("niveles guardados")
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const musica = ficha.musica ?? {}
  const puesto = musica.id || musica.tramos?.length

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Boton
          variante={ficha.activo ? "secundario" : "contorno"}
          tamano="pequeno"
          onClick={alternar}
          title="El interruptor general del sonido del vídeo"
        >
          {ficha.activo ? "Sonido activo" : "Silenciado"}
        </Boton>
        {!ficha.hay_jamendo && (
          <Insignia variante="secundario">
            falta la clave de Jamendo (Configuración)
          </Insignia>
        )}
      </div>

      {puesto ? (
        <div className="rounded-lg border p-3 text-sm">
          {musica.id ? (
            <>
              <p className="font-medium">
                «{musica.titulo}» — {musica.artista}
              </p>
              <p className="text-xs text-muted-foreground">
                {musica.licencia} · tema único
              </p>
            </>
          ) : (
            <>
              <p className="font-medium">
                Banda por tramos ({musica.tramos?.length} tramo(s), cruce{" "}
                {musica.cruce_s ?? 6} s)
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {musica.tramos?.map((t, i) => (
                  <li key={i}>
                    tramo {i + 1} · {t.animo} · «{t.titulo}» — {t.artista}
                  </li>
                ))}
              </ul>
            </>
          )}
          <Boton
            variante="contorno"
            tamano="pequeno"
            className="mt-2"
            onClick={quitar}
          >
            Quitar la música
          </Boton>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Sin música puesta: el vídeo saldrá con voz (y efectos) solamente.
        </p>
      )}

      <div className="rounded-lg border p-3">
        <p className="mb-2 text-sm font-medium">Buscar por tono</p>
        <div className="flex flex-wrap items-center gap-2">
          <Selector valor={animo} alCambiar={setAnimo}>
            <DisparadorSelector className="h-8 w-52">
              <ValorSelector />
            </DisparadorSelector>
            <ContenidoSelector>
              {claves.map((k) => (
                <Opcion key={k} valor={k}>
                  {ficha.animos[k]}
                </Opcion>
              ))}
            </ContenidoSelector>
          </Selector>
          <Boton
            tamano="pequeno"
            deshabilitado={buscando || !ficha.hay_jamendo}
            onClick={buscar}
          >
            {buscando ? (
              <Loader2 className="mr-1 size-3.5 animate-spin" />
            ) : (
              <Music className="mr-1 size-3.5" />
            )}
            Buscar en Jamendo
          </Boton>
        </div>
        {temas.length > 0 && (
          <ul className="mt-3 space-y-2">
            {temas.map((tema) => (
              <li key={tema.id} className="rounded border p-2 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      «{tema.titulo}» — {tema.artista}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {segundos(tema.duracion)} ·{" "}
                      {tema.vocal === "instrumental"
                        ? "instrumental"
                        : tema.vocal || "—"}
                      {tema.velocidad && ` · ${tema.velocidad}`}
                    </p>
                  </div>
                  <Boton
                    variante="secundario"
                    tamano="pequeno"
                    deshabilitado={poniendo === tema.id}
                    onClick={() => poner(tema)}
                  >
                    {poniendo === tema.id ? (
                      <Loader2 className="mr-1 size-3.5 animate-spin" />
                    ) : (
                      <Check className="mr-1 size-3.5" />
                    )}
                    Poner
                  </Boton>
                </div>
                <audio
                  controls
                  preload="none"
                  src={tema.escucha}
                  className="mt-1 h-8 w-full"
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border p-3">
        <p className="mb-2 text-sm font-medium">Nivel de la música</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">
            mezcla a {lufs.toFixed(0)} LUFS
            <input
              type="range"
              min={-40}
              max={-10}
              step={1}
              value={lufs}
              onChange={(e) => setLufs(Number(e.target.value))}
              className="mt-1 w-full accent-current"
            />
          </label>
          <label className="text-xs text-muted-foreground">
            ajuste fino {musica_db > 0 ? "+" : ""}
            {musica_db.toFixed(1)} dB
            <input
              type="range"
              min={-24}
              max={24}
              step={0.5}
              value={musica_db}
              onChange={(e) => setMusicaDb(Number(e.target.value))}
              className="mt-1 w-full accent-current"
            />
          </label>
        </div>
        <Boton
          variante="secundario"
          tamano="pequeno"
          className="mt-2"
          deshabilitado={guardando}
          onClick={guardarNiveles}
        >
          {guardando ? (
            <Loader2 className="mr-1 size-3.5 animate-spin" />
          ) : (
            <Check className="mr-1 size-3.5" />
          )}
          Guardar niveles
        </Boton>
      </div>

      {ficha.creditos.length > 0 && (
        <div className="rounded-lg border p-3 text-xs text-muted-foreground">
          <p className="mb-1 text-sm font-medium text-foreground">Créditos</p>
          <ul className="space-y-0.5">
            {ficha.creditos.map((c, i) => (
              <li key={i}>
                «{c.titulo}» — {c.artista} ({c.fuente}, {c.licencia})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- banda */

function PestanaBanda({
  pid,
  ficha,
  recargar,
}: {
  pid: string
  ficha: FichaSonido
  recargar: () => void
}) {
  const [arco, setArco] = useState<ArcoSonido | null>(null)
  const [sin_voz, setSinVoz] = useState(false)
  const [tid, setTid] = useState<string | null>(null)

  const cargarArco = useCallback(async () => {
    setSinVoz(false)
    try {
      setArco(await api.get<ArcoSonido>(`/api/proyectos/${pid}/sonido/arco`))
    } catch (e) {
      if ((e as { estado?: number }).estado === 400) setSinVoz(true)
    }
  }, [pid])

  useEffect(() => {
    cargarArco()
  }, [cargarArco])

  usarTrabajo({
    tid,
    alTerminar: (trabajo: TrabajoFicha) => {
      if (trabajo.estado === "hecho")
        toast.success("banda montada: revisa los tramos y renderiza")
      else toast.error(trabajo.error || "montar la banda falló")
      setTid(null)
      recargar()
    },
  })

  async function montar() {
    try {
      const r = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/sonido/banda`,
      )
      setTid(r.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        La banda sonora se monta por tramos según el arco del vídeo: un tema
        por cada tramo, cruzados. El trabajo busca, baja y nivela cada tramo.
      </p>
      {sin_voz ? (
        <p className="text-sm text-muted-foreground">
          Hace falta audio revisado para leer el ritmo del montaje.
        </p>
      ) : arco ? (
        <div className="rounded-lg border p-3">
          <p className="mb-2 text-sm font-medium">
            Arco del vídeo ({arco.tramos.length} tramo(s),{" "}
            {segundos(arco.duracion)})
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {arco.tramos.map((t) => (
              <li key={t.i}>
                tramo {t.i + 1} · {segundos(t.desde)}–{segundos(t.hasta)}{" "}
                · {ficha.animos[t.animo] ?? t.animo}
                {t.velocidad && ` · ritmo ${t.velocidad}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Boton tamano="pequeno" deshabilitado={!!tid || !ficha.hay_jamendo} onClick={montar}>
        {tid ? (
          <Loader2 className="mr-1 size-3.5 animate-spin" />
        ) : (
          <AudioLines className="mr-1 size-3.5" />
        )}
        Montar la banda por tramos
      </Boton>
    </div>
  )
}

/* --------------------------------------------------------------- efectos */

function PestanaEfectos({
  pid,
  ficha,
  recargar,
}: {
  pid: string
  ficha: FichaSonido
  recargar: () => void
}) {
  const [tid, setTid] = useState<string | null>(null)
  const [efectos_db, setEfectosDb] = useState(ficha.efectos_db)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    setEfectosDb(ficha.efectos_db)
  }, [ficha.efectos_db])

  usarTrabajo({
    tid,
    alTerminar: (trabajo: TrabajoFicha) => {
      if (trabajo.estado === "hecho") toast.success("efectos surtidos")
      else toast.error(trabajo.error || "surtir los efectos falló")
      setTid(null)
      recargar()
    },
  })

  async function surtir() {
    try {
      const r = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/sonido/efectos`,
      )
      setTid(r.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  async function vetar(efecto: EfectoSurtido) {
    try {
      await api.post(`/api/proyectos/${pid}/sonido/vetados`, {
        efecto,
        papel: efecto.papel,
      })
      toast.success(`«${efecto.titulo}» vetado: no volverá a salir`)
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  async function desvetar(clave: string) {
    try {
      await api.post(`/api/proyectos/${pid}/sonido/vetados`, {
        quitar: true,
        efecto: { fuente: "freesound", id: clave.split("_")[1] },
      })
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  async function guardarNivel() {
    setGuardando(true)
    try {
      await api.put(`/api/proyectos/${pid}/sonido`, { efectos_db })
      toast.success("nivel guardado")
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const por_papel = new Map<string, EfectoSurtido[]>()
  for (const efecto of ficha.efectos) {
    const lista = por_papel.get(efecto.papel) ?? []
    lista.push(efecto)
    por_papel.set(efecto.papel, lista)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Boton
          tamano="pequeno"
          deshabilitado={!!tid || !ficha.hay_freesound}
          onClick={surtir}
        >
          {tid ? (
            <Loader2 className="mr-1 size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 size-3.5" />
          )}
          Surtir efectos
        </Boton>
        {!ficha.hay_freesound && (
          <Insignia variante="secundario">
            falta la clave de FreeSound (Configuración)
          </Insignia>
        )}
      </div>

      {ficha.efectos.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nada surtido todavía. Cada papel (aire suave, golpe de acento,
          entrada de cartela) trae sus propios sonidos, medidos e igualados.
        </p>
      ) : (
        [...por_papel.entries()].map(([papel, lista]) => (
          <div key={papel} className="rounded-lg border p-3">
            <p className="mb-2 text-sm font-medium">
              {ficha.papeles[papel]?.nombre ?? papel}{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {lista.length}/{ficha.papeles[papel]?.cuantos ?? lista.length}
              </span>
            </p>
            <ul className="space-y-2">
              {lista.map((efecto) => (
                <li key={efecto.clave} className="rounded border p-2 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {efecto.titulo || efecto.id}
                        {efecto.vetado && (
                          <Insignia variante="secundario" className="ml-2">
                            vetado
                          </Insignia>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {efecto.autor} · {efecto.duracion.toFixed(1)} s ·{" "}
                        {efecto.licencia}
                        {typeof efecto.agudo === "number" && (
                          <>
                            {" "}
                            ·{" "}
                            {efecto.agudo > 0.6
                              ? "agudo"
                              : efecto.agudo < 0.4
                                ? "grave"
                                : "medio"}
                          </>
                        )}
                        {efecto.error && ` · ${efecto.error}`}
                      </p>
                    </div>
                    <Boton
                      variante="contorno"
                      tamano="pequeno"
                      deshabilitado={efecto.vetado}
                      title="Vetar: ni este vídeo ni los siguientes lo usarán"
                      onClick={() => vetar(efecto)}
                    >
                      <Ban className="mr-1 size-3.5" /> Vetar
                    </Boton>
                  </div>
                  {efecto.en_banco ? (
                    <audio
                      controls
                      preload="none"
                      src={efecto.muestra}
                      className="mt-1 h-8 w-full"
                    />
                  ) : (
                    <p className="mt-1 text-xs text-muted-foreground">
                      aún no está en el banco
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}

      <div className="rounded-lg border p-3">
        <p className="mb-2 text-sm font-medium">Nivel de los efectos</p>
        <label className="text-xs text-muted-foreground">
          ajuste fino {efectos_db > 0 ? "+" : ""}
          {efectos_db.toFixed(1)} dB
          <input
            type="range"
            min={-24}
            max={24}
            step={0.5}
            value={efectos_db}
            onChange={(e) => setEfectosDb(Number(e.target.value))}
            className="mt-1 w-full accent-current"
          />
        </label>
        <Boton
          variante="secundario"
          tamano="pequeno"
          className="mt-2"
          deshabilitado={guardando}
          onClick={guardarNivel}
        >
          Guardar nivel
        </Boton>
      </div>

      {ficha.vetados.length > 0 && (
        <div className="rounded-lg border p-3">
          <p className="mb-2 text-sm font-medium">
            Vetados del canal ({ficha.vetados.length})
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {ficha.vetados.map((v) => (
              <li key={v.clave} className="flex items-center justify-between gap-2">
                <span className="truncate">
                  {v.titulo || v.clave} — {v.autor}
                </span>
                <Boton
                  variante="contorno"
                  tamano="pequeno"
                  onClick={() => desvetar(v.clave)}
                  title="Quitar el veto"
                >
                  <X className="size-3.5" />
                </Boton>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/* --------------------------------------------------------- transiciones */

interface PropsTransiciones {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  recargar: () => void
}

export function DialogoTransiciones({
  pid,
  abierto,
  alCambiar,
  recargar,
}: PropsTransiciones) {
  const [ficha, setFicha] = useState<FichaTransiciones | null>(null)
  const [puestas, setPuestas] = useState<Set<string>>(new Set())
  const [duracion, setDuracion] = useState(0.4)
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const r = await api.get<FichaTransiciones>(
        `/api/proyectos/${pid}/transiciones`,
      )
      setFicha(r)
      setPuestas(
        new Set(r.transiciones.filter((t) => t.puesta).map((t) => t.id)),
      )
      setDuracion(r.duracion)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }, [pid])

  useEffect(() => {
    if (abierto) cargar()
  }, [abierto, cargar])

  async function guardar() {
    setGuardando(true)
    try {
      await api.put(`/api/proyectos/${pid}/transiciones`, {
        transiciones: [...puestas],
        duracion,
      })
      toast.success("transiciones guardadas: re-monta el vídeo para verlas")
      await cargar()
      recargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const rgb = (v: number[] | undefined) =>
    `rgb(${(v ?? []).map((c) => Math.round(c * 255)).join(",")})`

  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <CabeceraDialogo>
          <TituloDialogo className="flex items-center gap-2">
            <Film className="size-4" /> Transiciones
          </TituloDialogo>
          <DescripcionDialogo>
            Cada carta muestra el efecto xfade que correrá de verdad en el
            corte al renderizar — la muestra no miente. Un acento cada{" "}
            {ficha?.acento_cada ?? 5} planos, suave en el resto.
          </DescripcionDialogo>
        </CabeceraDialogo>
        {ficha ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Insignia variante="secundario">{ficha.resumen}</Insignia>
              <span
                className="inline-block size-3 rounded-full border"
                style={{ background: rgb(ficha.acento.acento) }}
                title="acento (de la paleta del vídeo)"
              />
              <span
                className="inline-block size-3 rounded-full border"
                style={{ background: rgb(ficha.acento.oscuro) }}
              />
              <span
                className="inline-block size-3 rounded-full border"
                style={{ background: rgb(ficha.acento.claro) }}
              />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {ficha.transiciones.map((t) => {
                const activa = puestas.has(t.id)
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() =>
                      setPuestas((previas) => {
                        const nuevas = new Set(previas)
                        if (activa) nuevas.delete(t.id)
                        else nuevas.add(t.id)
                        return nuevas
                      })
                    }
                    className={`rounded-lg border p-2 text-left transition-colors ${
                      activa ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">{t.nombre}</p>
                      <span
                        className={`grid size-4 shrink-0 place-items-center rounded border ${
                          activa
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-muted-foreground/30"
                        }`}
                      >
                        {activa && <Check className="size-3" />}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {t.descripcion}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Insignia variante="secundario">xfade: {t.xfade}</Insignia>
                      <Insignia variante="secundario">{t.familia}</Insignia>
                      <Insignia variante="secundario">
                        fuerza {t.fuerza}
                      </Insignia>
                      {t.defecto && (
                        <Insignia variante="exito">de fábrica</Insignia>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
            <label className="block rounded-lg border p-3 text-xs text-muted-foreground">
              duración base {duracion.toFixed(1)} s (cada efecto la multiplica)
              <input
                type="range"
                min={0.1}
                max={1.5}
                step={0.1}
                value={duracion}
                onChange={(e) => setDuracion(Number(e.target.value))}
                className="mt-1 w-full accent-current"
              />
            </label>
            <Boton deshabilitado={guardando} onClick={guardar}>
              {guardando ? (
                <Loader2 className="mr-1 size-4 animate-spin" />
              ) : (
                <Check className="mr-1 size-4" />
              )}
              Guardar{puestas.size === 0 && " (las de fábrica)"}
            </Boton>

            {ficha.reparto.length > 0 && (
              <div className="rounded-lg border p-3">
                <p className="mb-2 text-sm font-medium">
                  Reparto resuelto por el motor
                </p>
                <div className="flex flex-wrap gap-1 text-xs">
                  {ficha.reparto.map((r) => (
                    <Insignia
                      key={r.id}
                      variante={r.ranura === "acento" ? "exito" : "secundario"}
                      title={`en ${segundos(r.t_in)}`}
                    >
                      {r.id}: {r.tipo}
                      {r.duracion > 0 && ` (${r.duracion.toFixed(1)} s)`}
                    </Insignia>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> cargando el catálogo…
          </div>
        )}
      </ContenidoDialogo>
    </Dialogo>
  )
}
