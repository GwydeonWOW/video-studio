/** El repaso: notas ancladas al segundo sobre el vídeo montado.
 *
 * TRES COSAS VIVEN AQUÍ (heredadas del original):
 * 1 · LAS NOTAS — se escriben mirando el vídeo, ancladas al instante; el
 *     plano se deduce de los cortes y la nota guarda el ancla de lo que
 *     se narraba (por si los planos se renumeran al regenerar).
 * 2 · LAS CAPTURAS — un fotograma con trazos encima: feedback que sólo
 *     existe en un instante. Al aplicar, se convierte en instrucción por
 *     escena y se rehace SOLO esa unidad.
 * 3 · LAS NOTAS DE MONTAJE — texto libre del montador, autoguardado.
 *
 * Aplicar es UN gesto con su coste delante: el enrutador reparte las
 * notas en cambios de un vocabulario cerrado y cada cambio sabe qué hay
 * que rehacer (el ahorro es el diseño, no una optimización).
 */
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  Camera,
  Check,
  Eraser,
  Loader2,
  MessageSquareHeart,
  Pencil,
  Play,
  StickyNote,
  Trash2,
  Undo2,
  Upload,
  X,
} from "lucide-react"
import { api } from "../../lib/api"
import type {
  FichaCaptura,
  FichaRepaso,
  NotaRepaso,
  NotasMontaje,
} from "../../lib/tipos"
import { Boton } from "../../components/ui/button"
import { AreaTexto } from "../../components/ui/textarea"
import { Etiqueta } from "../../components/ui/etiqueta"
import { Insignia } from "../../components/ui/badge"
import { Dialogo, ContenidoDialogo, CabeceraDialogo, TituloDialogo, DescripcionDialogo } from "../../components/ui/dialogo"

/** 83.7 -> "1:23" */
export function reloj(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

/* ============================================================ el panel == */

export function PanelRepaso({
  pid,
  ocupado,
  seguirTrabajo,
}: {
  pid: string
  ocupado: boolean
  seguirTrabajo: (tid: string) => void
}) {
  const [ficha, setFicha] = useState<FichaRepaso | null>(null)
  const [t_video, setTVideo] = useState(0)
  const [texto, setTexto] = useState("")
  const [imagenes, setImagenes] = useState<string[]>([])
  const [subiendo, setSubiendo] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [captura_abierta, setCapturaAbierta] = useState(false)
  const [aplicando, setAplicando] = useState(false)
  const [montaje, setMontaje] = useState("")
  const [montaje_actualizado, setMontajeActualizado] = useState<string | null>(null)
  const video_ref = useRef<HTMLVideoElement | null>(null)
  const fichero_ref = useRef<HTMLInputElement | null>(null)
  const montaje_ref = useRef("")

  const cargar = useCallback(() => {
    api
      .get<FichaRepaso>(`/api/proyectos/${pid}/repaso`)
      .then(setFicha)
      .catch(() => setFicha(null))
  }, [pid])

  useEffect(() => {
    setTexto("")
    setImagenes([])
    montaje_ref.current = ""
    setMontaje("")
    cargar()
    api
      .get<NotasMontaje>(`/api/proyectos/${pid}/montaje/notas`)
      .then((r) => {
        montaje_ref.current = r.texto
        setMontaje(r.texto)
        setMontajeActualizado(r.actualizado ?? null)
      })
      .catch(() => {})
  }, [pid, cargar])

  /* al terminar cualquier trabajo (repaso, capturas, pasos) refresca */
  useEffect(() => {
    if (!ocupado) cargar()
  }, [ocupado, cargar])

  /* notas de montaje: autoguardado con retardo */
  useEffect(() => {
    if (montaje === montaje_ref.current) return
    const timer = setTimeout(async () => {
      try {
        const r = await api.put<NotasMontaje>(
          `/api/proyectos/${pid}/montaje/notas`,
          { texto: montaje },
        )
        montaje_ref.current = montaje
        setMontajeActualizado(r.actualizado ?? null)
      } catch (e) {
        toast.error(String((e as Error).message ?? e))
      }
    }, 800)
    return () => clearTimeout(timer)
  }, [montaje, pid])

  const notas = ficha?.notas ?? []
  const pendientes = notas.filter((n) => n.estado !== "aplicado")

  const anadir_nota = async () => {
    if (!texto.trim()) return
    setEnviando(true)
    try {
      await api.post(`/api/proyectos/${pid}/repaso`, {
        texto,
        t: t_video,
        imagenes,
      })
      setTexto("")
      setImagenes([])
      cargar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviando(false)
    }
  }

  const subir_imagen = async (fichero: File) => {
    setSubiendo(true)
    try {
      const data_url = await new Promise<string>((ok, no) => {
        const lector = new FileReader()
        lector.onload = () => ok(String(lector.result))
        lector.onerror = () => no(new Error("no se pudo leer la imagen"))
        lector.readAsDataURL(fichero)
      })
      const r = await api.post<{ nombre: string }>(
        `/api/proyectos/${pid}/repaso/imagenes`,
        { imagen: data_url },
      )
      setImagenes((prev) => [...prev, r.nombre].slice(0, 4))
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setSubiendo(false)
    }
  }

  const aplicar = async () => {
    if (pendientes.length === 0) return
    setAplicando(true)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/repaso/aplicar`,
        {},
      )
      toast.success(`repaso en marcha: ${pendientes.length} nota(s) a repartir`)
      seguirTrabajo(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setAplicando(false)
    }
  }

  const componer_fotograma = (): HTMLCanvasElement | null => {
    const video = video_ref.current
    if (!video || !video.videoWidth) return null
    const lienzo = document.createElement("canvas")
    lienzo.width = video.videoWidth
    lienzo.height = video.videoHeight
    lienzo.getContext("2d")!.drawImage(video, 0, 0)
    return lienzo
  }

  if (!ficha)
    return (
      <div className="flex justify-center py-20 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  return (
    <div className="space-y-5">
      {/* ---------------------------------------------- el vídeo montado */}
      {ficha.montado && ficha.video ? (
        <div className="space-y-2">
          <video
            ref={video_ref}
            controls
            preload="metadata"
            src={ficha.video}
            onTimeUpdate={(e) => setTVideo(e.currentTarget.currentTime)}
            className="w-full rounded-lg border bg-black"
          />
          <p className="text-xs text-muted-foreground">
            {reloj(t_video)} · {ficha.duracion ? reloj(ficha.duracion) : "—"} ·
            las notas se anclan al segundo en que se escriben
          </p>
        </div>
      ) : (
        <div className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          Todavía no hay vídeo montado: ejecuta el paso 8. Mientras tanto las
          notas se anclan contra los cortes de la voz (y «Mirar» sirve para
          revisar sin montar).
        </div>
      )}

      {/* ------------------------------------------------- nota nueva */}
      <div className="space-y-2 rounded-md border bg-card p-3">
        <div className="flex items-center gap-2">
          <StickyNote className="h-4 w-4" />
          <p className="text-sm font-medium">Nota del repaso</p>
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            {reloj(t_video)}
          </span>
        </div>
        <AreaTexto
          filas={3}
          valor={texto}
          alCambiar={(e) => setTexto(e.target.value)}
          placeholder={
            ficha.montado
              ? "el rótulo pisa la grúa… · esta cifra se dice mal… · aquí sobra la cartela…"
              : "apunta lo que cambiarás cuando haya vídeo (se ancla a los cortes de la voz)"
          }
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) anadir_nota()
          }}
        />
        {imagenes.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            {imagenes.map((nombre) => (
              <span
                key={nombre}
                className="flex items-center gap-1 rounded bg-muted px-2 py-0.5 font-mono text-xs"
              >
                {nombre}
                <button
                  title="quitar"
                  onClick={() =>
                    setImagenes((prev) => prev.filter((i) => i !== nombre))
                  }
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Boton
            tamano="pequeno"
            deshabilitado={enviando || !texto.trim()}
            onClick={anadir_nota}
          >
            {enviando ? <Loader2 className="animate-spin" /> : null}
            Anotar en {reloj(t_video)}
          </Boton>
          <Boton
            variante="contorno"
            tamano="pequeno"
            deshabilitado={subiendo || imagenes.length >= 4}
            title="Una imagen de referencia para la nota (PNG, máx. 4)"
            onClick={() => fichero_ref.current?.click()}
          >
            {subiendo ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Upload />
            )}
            Imagen de referencia
          </Boton>
          <input
            ref={fichero_ref}
            type="file"
            accept="image/png,image/jpeg"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) subir_imagen(f)
              e.target.value = ""
            }}
          />
          {ficha.montado && (
            <Boton
              variante="contorno"
              tamano="pequeno"
              deshabilitado={ocupado}
              title="Congela el fotograma y pinta encima: feedback de un instante"
              onClick={() => setCapturaAbierta(true)}
            >
              <Camera /> Capturar fotograma
            </Boton>
          )}
        </div>
      </div>

      {/* ------------------------------------------------- las notas */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium">
            {notas.length} nota{notas.length === 1 ? "" : "s"}
            {pendientes.length > 0 && ` · ${pendientes.length} pendiente(s)`}
          </p>
          {pendientes.length > 0 && (
            <Boton
              tamano="pequeno"
              className="ml-auto"
              deshabilitado={aplicando || ocupado}
              title="Reparte las notas en cambios concretos y rehace sólo lo que toca (con su coste)"
              onClick={aplicar}
            >
              {aplicando ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Play />
              )}
              Aplicar {pendientes.length} pendiente(s)
            </Boton>
          )}
        </div>
        {notas.length === 0 && (
          <p className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            Sin notas todavía: mira el vídeo, pausa donde duela y escribe.
            Después, un botón las convierte en cambios.
          </p>
        )}
        {notas.map((nota) => (
          <NotaCard
            key={nota.id}
            pid={pid}
            nota={nota}
            deshabilitado={ocupado}
            alBuscar={(t) => {
              const v = video_ref.current
              if (v) {
                v.currentTime = t
                v.play().catch(() => {})
              }
            }}
            alCambiar={cargar}
          />
        ))}
      </div>

      {/* ------------------------------------------------ las capturas */}
      <ZonaCapturas pid={pid} ocupado={ocupado} seguirTrabajo={seguirTrabajo} />

      {/* -------------------------------------------- notas de montaje */}
      <div className="space-y-2 rounded-md border bg-card p-3">
        <div className="flex items-center gap-2">
          <MessageSquareHeart className="h-4 w-4" />
          <p className="text-sm font-medium">Notas de montaje</p>
          {montaje_actualizado && (
            <span
              className="ml-auto text-xs text-muted-foreground"
              title={`guardado ${montaje_actualizado}`}
            >
              autoguardado
            </span>
          )}
        </div>
        <AreaTexto
          filas={4}
          valor={montaje}
          alCambiar={(e) => setMontaje(e.target.value)}
          placeholder="Lo que el que monta necesita recordar: música que entra, corte que se quiere seco, cortinilla del final…"
        />
      </div>

      {/* el diálogo de captura (fotograma del vídeo montado) */}
      <DialogoCaptura
        pid={pid}
        abierto={captura_abierta}
        alCambiar={setCapturaAbierta}
        paso="render"
        escena={plano_en(ficha.cortes, t_video)}
        componer={componer_fotograma}
        t_video={t_video}
        alCreada={() => cargar()}
      />
    </div>
  )
}

/** El plano que está en pantalla en un instante (búsqueda por intervalo). */
function plano_en(
  cortes: { id: string; t_in: number; t_out: number }[],
  segundo: number,
): string {
  for (const corte of cortes)
    if (segundo >= corte.t_in && segundo < corte.t_out) return corte.id
  return cortes.length > 0 ? cortes[cortes.length - 1].id : ""
}

/* ---------------------------------------------------------- una nota */

function NotaCard({
  pid,
  nota,
  deshabilitado,
  alBuscar,
  alCambiar,
}: {
  pid: string
  nota: NotaRepaso
  deshabilitado: boolean
  alBuscar: (t: number) => void
  alCambiar: () => void
}) {
  const [editando, setEditando] = useState(false)
  const [texto, setTexto] = useState(nota.texto)

  const guardar = async () => {
    try {
      await api.put(`/api/proyectos/${pid}/repaso/${nota.id}`, { texto })
      setEditando(false)
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  const borrar = async () => {
    try {
      await api.borrar(`/api/proyectos/${pid}/repaso/${nota.id}`)
      alCambiar()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          className="rounded bg-muted px-2 py-0.5 font-mono hover:bg-secondary"
          title="Buscar este instante en el vídeo"
          onClick={() => alBuscar(nota.t)}
        >
          {reloj(nota.t)}
        </button>
        {nota.plano ? (
          nota.descolgada ? (
            <Insignia variante="aviso" title="Su plano ya no existe en el vídeo actual">
              {nota.plano} ?
            </Insignia>
          ) : (
            <Insignia variante={nota.reanclada ? "aviso" : "secundario"}>
              {nota.plano}
              {nota.reanclada ? " ↻" : ""}
            </Insignia>
          )
        ) : null}
        <span className="ml-auto text-muted-foreground">{nota.id}</span>
        {nota.estado === "aplicado" ? (
          <Insignia variante="exito">aplicada</Insignia>
        ) : (
          <Insignia variante="contorno">pendiente</Insignia>
        )}
      </div>
      {editando ? (
        <div className="mt-2 space-y-2">
          <AreaTexto
            filas={3}
            valor={texto}
            alCambiar={(e) => setTexto(e.target.value)}
            autoFocus
          />
          <div className="flex gap-2">
            <Boton tamano="pequeno" onClick={guardar} deshabilitado={!texto.trim()}>
              Guardar
            </Boton>
            <Boton
              variante="contorno"
              tamano="pequeno"
              onClick={() => {
                setEditando(false)
                setTexto(nota.texto)
              }}
            >
              Cancelar
            </Boton>
          </div>
        </div>
      ) : (
        <p className="mt-1.5 whitespace-pre-wrap text-sm">{nota.texto}</p>
      )}
      {nota.imagenes?.length > 0 && (
        <div className="mt-2 flex gap-2">
          {nota.imagenes.map((nombre) => (
            <img
              key={nombre}
              src={`/a/${pid}/repaso/${nombre}`}
              alt={nombre}
              title={nombre}
              className="h-14 rounded border object-cover"
            />
          ))}
        </div>
      )}
      <div className="mt-1 flex justify-end gap-1">
        {!editando && (
          <Boton
            variante="fantasma"
            tamano="pequeno"
            deshabilitado={deshabilitado}
            onClick={() => setEditando(true)}
          >
            <Pencil /> Editar
          </Boton>
        )}
        <Boton
          variante="fantasma"
          tamano="pequeno"
          deshabilitado={deshabilitado}
          onClick={borrar}
        >
          <Trash2 /> Borrar
        </Boton>
      </div>
    </div>
  )
}

/* -------------------------------------------------------- las capturas */

function ZonaCapturas({
  pid,
  ocupado,
  seguirTrabajo,
}: {
  pid: string
  ocupado: boolean
  seguirTrabajo: (tid: string) => void
}) {
  const [capturas, setCapturas] = useState<FichaCaptura[] | null>(null)
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set())
  const [aplicando, setAplicando] = useState(false)

  const cargar = useCallback(() => {
    api
      .get<FichaCaptura[]>(`/api/proyectos/${pid}/capturas`)
      .then((fichas) => {
        setCapturas(fichas)
        setMarcadas(
          new Set(fichas.filter((f) => !f.aplicada).map((f) => f.id)),
        )
      })
      .catch(() => setCapturas([]))
  }, [pid])

  useEffect(() => {
    cargar()
  }, [cargar])

  useEffect(() => {
    if (!ocupado) cargar()
  }, [ocupado, cargar])

  const aplicar = async () => {
    const ids = [...marcadas]
    if (ids.length === 0) return
    setAplicando(true)
    try {
      const trabajo = await api.post<{ id: string }>(
        `/api/proyectos/${pid}/capturas/aplicar`,
        { ids },
      )
      toast.success(`capturas en marcha (${ids.length})`)
      seguirTrabajo(trabajo.id)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setAplicando(false)
    }
  }

  const alternar = (id: string) =>
    setMarcadas((prev) => {
      const nueva = new Set(prev)
      if (nueva.has(id)) nueva.delete(id)
      else nueva.add(id)
      return nueva
    })

  if (capturas === null) return null
  if (capturas.length === 0) return null
  const pendientes = capturas.filter((c) => !c.aplicada)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">
          Capturas anotadas
          {pendientes.length > 0 && ` · ${pendientes.length} sin aplicar`}
        </p>
        {pendientes.length > 0 && (
          <Boton
            tamano="pequeno"
            className="ml-auto"
            deshabilitado={aplicando || ocupado || marcadas.size === 0}
            title="Cada captura se vuelve feedback de SU escena y se rehace sólo esa unidad"
            onClick={aplicar}
          >
            {aplicando ? <Loader2 className="animate-spin" /> : <Play />}
            Aplicar {marcadas.size}
          </Boton>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {capturas.map((c) => (
          <div
            key={c.id}
            className={`overflow-hidden rounded-md border ${
              c.aplicada ? "opacity-60" : ""
            }`}
          >
            <img
              src={`/api/proyectos/${pid}/capturas/${c.id}/imagen`}
              alt={c.id}
              className="aspect-video w-full bg-muted object-cover"
            />
            <div className="space-y-1 p-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-mono text-muted-foreground">
                  {c.escena} · {c.paso === "render" ? "vídeo" : "previsión"}
                  {c.t_video != null && ` · ${reloj(c.t_video)}`}
                </span>
                {c.aplicada ? (
                  <Insignia variante="exito">
                    <Check className="h-3 w-3" /> aplicada
                  </Insignia>
                ) : (
                  <label className="ml-auto flex items-center gap-1">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 accent-primary"
                      checked={marcadas.has(c.id)}
                      onChange={() => alternar(c.id)}
                    />
                    aplicar
                  </label>
                )}
              </div>
              {c.comentario && <p className="line-clamp-2">{c.comentario}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ================================================== diálogo de captura == */

/** Congela un fotograma, se pinta encima y se sube como PNG anotado.
 *
 * `componer` devuelve el lienzo del fotograma (quien llama sabe si es un
 * <video> o la composición de la previsualización). Los trazos se
 * guardan NORMALIZADOS (0..1): valen a cualquier tamaño de pantalla.
 */
export function DialogoCaptura({
  pid,
  abierto,
  alCambiar,
  paso,
  escena,
  componer,
  t_video,
  t_escena,
  alCreada,
}: {
  pid: string
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  paso: "callouts" | "render"
  escena: string
  componer: () => HTMLCanvasElement | null
  t_video?: number | null
  t_escena?: number | null
  alCreada?: () => void
}) {
  const lienzo_ref = useRef<HTMLCanvasElement | null>(null)
  const fondo_ref = useRef<HTMLCanvasElement | null>(null)
  const dibujando = useRef(false)
  const [trazos, setTrazos] = useState<
    { color: string; grosor: number; puntos: { x: number; y: number }[] }[]
  >([])
  const [comentario, setComentario] = useState("")
  const [enviando, setEnviando] = useState(false)

  const COLOR = "#f0a35e"
  const GROSOR = 6

  const repintar = useCallback(() => {
    const lienzo = lienzo_ref.current
    if (!lienzo) return
    const ctx = lienzo.getContext("2d")!
    ctx.clearRect(0, 0, lienzo.width, lienzo.height)
    const fondo = fondo_ref.current
    if (fondo) ctx.drawImage(fondo, 0, 0, lienzo.width, lienzo.height)
    else {
      ctx.fillStyle = "#111"
      ctx.fillRect(0, 0, lienzo.width, lienzo.height)
    }
    const sx = lienzo.width
    const sy = lienzo.height
    for (const trazo of trazos) {
      if (trazo.puntos.length < 2) continue
      ctx.strokeStyle = trazo.color
      ctx.lineWidth = trazo.grosor * (sx / 960)
      ctx.lineJoin = "round"
      ctx.lineCap = "round"
      ctx.beginPath()
      ctx.moveTo(trazo.puntos[0].x * sx, trazo.puntos[0].y * sy)
      for (const p of trazo.puntos.slice(1)) ctx.lineTo(p.x * sx, p.y * sy)
      ctx.stroke()
    }
  }, [trazos])

  useEffect(() => {
    if (!abierto) return
    setTrazos([])
    setComentario("")
    const fondo = componer()
    fondo_ref.current = fondo
    const lienzo = lienzo_ref.current
    if (lienzo) {
      lienzo.width = fondo?.width ?? 960
      lienzo.height = fondo?.height ?? 540
    }
    repintar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto])

  useEffect(() => {
    repintar()
  }, [repintar])

  const punto_de = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    }
  }

  const al_bajar = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dibujando.current = true
    setTrazos((prev) => [
      ...prev,
      { color: COLOR, grosor: GROSOR, puntos: [punto_de(e)] },
    ])
  }
  const al_mover = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dibujando.current) return
    const p = punto_de(e)
    setTrazos((prev) => {
      const copia = [...prev]
      const ultimo = copia[copia.length - 1]
      if (ultimo) copia[copia.length - 1] = { ...ultimo, puntos: [...ultimo.puntos, p] }
      return copia
    })
  }
  const al_subir = () => {
    dibujando.current = false
  }

  const guardar = async () => {
    if (trazos.length === 0 && !comentario.trim()) {
      toast.error("pinta encima o escribe la nota: una captura vacía no dice nada")
      return
    }
    const lienzo = lienzo_ref.current
    if (!lienzo) return
    setEnviando(true)
    try {
      await api.post<FichaCaptura>(`/api/proyectos/${pid}/capturas`, {
        paso,
        escena,
        imagen: lienzo.toDataURL("image/png"),
        trazos,
        comentario,
        t_video: t_video ?? null,
        t_escena: t_escena ?? null,
      })
      toast.success("captura guardada: se aplicará a su escena")
      alCambiar(false)
      alCreada?.()
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Dialogo abierto={abierto} alCambiar={alCambiar}>
      <ContenidoDialogo className="max-w-2xl">
        <CabeceraDialogo>
          <TituloDialogo>Capturar y anotar</TituloDialogo>
          <DescripcionDialogo>
            El fotograma congelado con tus trazos encima. Al aplicarla se
            vuelve feedback de la escena {escena || "(sin escena)"} y se
            rehace sólo esa unidad — la zona que señalas se describe con
            palabras («arriba a la derecha») para quien corrige.
          </DescripcionDialogo>
        </CabeceraDialogo>
        <div className="space-y-3">
          <canvas
            ref={lienzo_ref}
            className="w-full cursor-crosshair touch-none rounded-md border bg-black"
            style={{ aspectRatio: "16 / 9" }}
            onPointerDown={al_bajar}
            onPointerMove={al_mover}
            onPointerUp={al_subir}
            onPointerLeave={al_subir}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Boton
              variante="contorno"
              tamano="pequeno"
              deshabilitado={trazos.length === 0}
              onClick={() => setTrazos((prev) => prev.slice(0, -1))}
            >
              <Undo2 /> Deshacer trazo
            </Boton>
            <Boton
              variante="contorno"
              tamano="pequeno"
              deshabilitado={trazos.length === 0}
              onClick={() => setTrazos([])}
            >
              <Eraser /> Limpiar
            </Boton>
          </div>
          <div className="space-y-1">
            <Etiqueta htmlFor="cap-comentario">Qué está mal</Etiqueta>
            <AreaTexto
              id="cap-comentario"
              filas={2}
              valor={comentario}
              alCambiar={(e) => setComentario(e.target.value)}
              placeholder="el rótulo pisa la grúa…"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Boton variante="contorno" onClick={() => alCambiar(false)}>
              Cancelar
            </Boton>
            <Boton
              onClick={guardar}
              deshabilitado={enviando || (trazos.length === 0 && !comentario.trim())}
            >
              {enviando && <Loader2 className="animate-spin" />}
              Guardar captura
            </Boton>
          </div>
        </div>
      </ContenidoDialogo>
    </Dialogo>
  )
}
