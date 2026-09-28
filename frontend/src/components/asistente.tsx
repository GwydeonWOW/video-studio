/** El asistente: burbuja abajo a la derecha + cajón de charla.

 * Preguntar es un 202: la respuesta corre en el servidor y esta pantalla
 * la sigue sondeando la charla cada poco (con el cajón cerrado también;
 * la burbuja avisa). La charla sobrevive en localStorage y si murió por
 * un reinicio se abre otra al vuelo.
 */
import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  Bot,
  Loader2,
  MessageSquarePlus,
  SendHorizontal,
  Square,
  X,
} from "lucide-react"
import { api, ErrorApi } from "../lib/api"
import { fotoDePantalla } from "../lib/pantalla"
import type { CharlaAsistente, EstadoAsistente, TurnoAsistente } from "../lib/tipos"
import { AreaTexto } from "./ui/textarea"
import { Boton } from "./ui/button"

const CLAVE_CHARLA = "estudio.asistente.charla"
const MS_SONDEO = 1500

/* ------------------------------------------------ texto con formato ligero */

function enLinea(texto: string, base: number = 0): React.ReactNode[] {
  const pedazos: React.ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let ultimo = 0
  let clave = base
  let trozo: RegExpExecArray | null
  while ((trozo = regex.exec(texto)) !== null) {
    if (trozo.index > ultimo) pedazos.push(texto.slice(ultimo, trozo.index))
    if (trozo[0].startsWith("**")) {
      pedazos.push(<strong key={clave++}>{trozo[0].slice(2, -2)}</strong>)
    } else {
      pedazos.push(
        <code key={clave++} className="rounded bg-muted px-1 py-0.5 text-xs">
          {trozo[0].slice(1, -1)}
        </code>
      )
    }
    ultimo = trozo.index + trozo[0].length
  }
  if (ultimo < texto.length) pedazos.push(texto.slice(ultimo))
  return pedazos
}

/** Markdown ligero: párrafos, listas, títulos, código vallado, negritas. */
export function textoConFormato(texto: string): React.ReactNode[] {
  const lineas = texto.split("\n")
  const nodos: React.ReactNode[] = []
  let clave = 0
  let i = 0
  while (i < lineas.length) {
    const linea = lineas[i]
    if (linea.trim() === "") {
      i++
      continue
    }
    if (linea.startsWith("```")) {
      const codigo: string[] = []
      i++
      while (i < lineas.length && !lineas[i].startsWith("```")) {
        codigo.push(lineas[i])
        i++
      }
      i++ // la valla que cierra (si llegó)
      nodos.push(
        <pre key={clave++} className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
          <code>{codigo.join("\n")}</code>
        </pre>
      )
      continue
    }
    const titulo = /^(#{1,6})\s+(.*)$/.exec(linea)
    if (titulo) {
      nodos.push(
        <p key={clave++} className="font-semibold leading-snug">
          {enLinea(titulo[2], clave * 100)}
        </p>
      )
      i++
      continue
    }
    const es_lista = /^\s*([-*•]|\d+[.)])\s+/
    if (es_lista.test(linea)) {
      const ordenada = /^\s*\d+[.)]\s+/.test(linea)
      const puntos: React.ReactNode[] = []
      while (i < lineas.length && es_lista.test(lineas[i]) && !lineas[i].startsWith("```")) {
        const punto = lineas[i].replace(es_lista, "")
        puntos.push(<li key={puntos.length}>{enLinea(punto, clave * 100 + puntos.length)}</li>)
        i++
      }
      nodos.push(
        ordenada ? (
          <ol key={clave++} className="ml-4 list-decimal space-y-1">
            {puntos}
          </ol>
        ) : (
          <ul key={clave++} className="ml-4 list-disc space-y-1">
            {puntos}
          </ul>
        )
      )
      continue
    }
    nodos.push(<p key={clave++}>{enLinea(linea, clave * 100)}</p>)
  }
  return nodos
}

/* ---------------------------------------------------------------- el turno */

function Turno({ turno }: { turno: TurnoAsistente }) {
  const tuyo = turno.quien === "tu"
  return (
    <div className={`flex ${tuyo ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] space-y-1 rounded-xl px-3 py-2 text-sm ${
          tuyo
            ? "bg-primary text-primary-foreground"
            : "bg-secondary text-secondary-foreground"
        }`}
      >
        {turno.estado === "pensando" ? (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> pensando…
          </p>
        ) : turno.estado === "cancelado" ? (
          <p className="italic text-muted-foreground">parado</p>
        ) : turno.estado === "error" ? (
          <p className="whitespace-pre-wrap text-destructive">{turno.texto}</p>
        ) : (
          textoConFormato(turno.texto)
        )}
        {turno.estado !== "pensando" && (turno.segundos || turno.tokens) ? (
          <p className={`text-[10px] ${tuyo ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
            {turno.segundos ? `${Math.round(turno.segundos)} s` : ""}
            {turno.segundos && turno.tokens ? " · " : ""}
            {turno.tokens ? `${turno.tokens} tokens` : ""}
          </p>
        ) : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ cajón */

export function Asistente({ pid }: { pid: string }) {
  const [abierto, setAbierto] = useState(false)
  const [ficha, setFicha] = useState<EstadoAsistente | null>(null)
  const [charla, setCharla] = useState<CharlaAsistente | null>(null)
  const [texto, setTexto] = useState("")
  const [aviso, setAviso] = useState("")
  const zona = useRef<HTMLDivElement>(null)
  const entrada = useRef<HTMLTextAreaElement>(null)

  const listo = ficha?.listo ?? false

  // el pulso del estado (barato: solo dice si puede contestar)
  useEffect(() => {
    api
      .get<EstadoAsistente>("/api/asistente")
      .then(setFicha)
      .catch(() => setFicha(null))
  }, [])

  const abrirCharla = useCallback(async (): Promise<CharlaAsistente | null> => {
    const cid = localStorage.getItem(CLAVE_CHARLA)
    if (cid) {
      try {
        const previa = await api.get<CharlaAsistente>(`/api/asistente/charlas/${cid}`)
        setCharla(previa)
        localStorage.setItem(CLAVE_CHARLA, previa.id)
        return previa
      } catch (fallo) {
        if (!(fallo instanceof ErrorApi) || fallo.estado !== 404) return null
        localStorage.removeItem(CLAVE_CHARLA)
      }
    }
    try {
      const nueva_charla = await api.post<CharlaAsistente>("/api/asistente/charlas")
      setCharla(nueva_charla)
      localStorage.setItem(CLAVE_CHARLA, nueva_charla.id)
      return nueva_charla
    } catch {
      return null
    }
  }, [])

  // sondeo mientras piensa (con el cajón cerrado también: la burbuja avisa)
  const ocupada = charla?.ocupada ?? false
  useEffect(() => {
    if (!ocupada || !charla?.id) return
    const cid = charla.id
    const timer = setInterval(() => {
      api
        .get<CharlaAsistente>(`/api/asistente/charlas/${cid}`)
        .then(setCharla)
        .catch(() => undefined)
    }, MS_SONDEO)
    return () => clearInterval(timer)
  }, [ocupada, charla?.id])

  // siempre al final de la conversación
  useEffect(() => {
    zona.current?.scrollTo({ top: zona.current.scrollHeight })
  }, [charla])

  useEffect(() => {
    if (abierto) entrada.current?.focus()
  }, [abierto])

  const conCuerpo = async (destino: CharlaAsistente, cuerpo: unknown) => {
    try {
      setCharla(
        await api.post<CharlaAsistente>(
          `/api/asistente/charlas/${destino.id}/mensajes`, cuerpo))
      return true
    } catch (fallo) {
      // la charla murió con un reinicio: una nueva y se reintenta una vez
      if (fallo instanceof ErrorApi && /ninguna charla/.test(fallo.message)) {
        localStorage.removeItem(CLAVE_CHARLA)
        setCharla(null)
        const renacida = await abrirCharla()
        if (renacida) {
          try {
            setCharla(
              await api.post<CharlaAsistente>(
                `/api/asistente/charlas/${renacida.id}/mensajes`, cuerpo))
            return true
          } catch (de_nuevo) {
            fallo = de_nuevo as Error
          }
        }
      }
      setAviso(fallo instanceof Error ? fallo.message : "falló el envío")
      return false
    }
  }

  const enviar = async () => {
    const pregunta = texto.trim()
    if (!pregunta) return
    setAviso("")
    if (!listo) {
      setAviso(ficha?.motivo || "el asistente no puede contestar todavía")
      return
    }
    const activa = charla ?? (await abrirCharla())
    if (!activa) {
      setAviso("no se ha podido abrir la charla")
      return
    }
    setTexto("")
    const bien = await conCuerpo(activa, {
      texto: pregunta,
      proyecto: pid,
      pantalla: fotoDePantalla(),
    })
    if (!bien) setTexto(pregunta)
  }

  const cancelar = async () => {
    if (!charla?.id) return
    try {
      const r = await api.post<{ cancelado: boolean; charla: CharlaAsistente }>(
        `/api/asistente/charlas/${charla.id}/cancelar`)
      setCharla(r.charla)
    } catch (fallo) {
      setAviso(fallo instanceof Error ? fallo.message : "no se pudo parar")
    }
  }

  const nueva = async () => {
    if (charla?.id) {
      try {
        await api.borrar(`/api/asistente/charlas/${charla.id}`)
      } catch {
        /* si ya murió, adelante */
      }
    }
    setCharla(null)
    setAviso("")
    await abrirCharla()
    entrada.current?.focus()
  }

  return (
    <>
      <button
        type="button"
        aria-label="Asistente"
        title="Asistente"
        onClick={() => setAbierto((v) => !v)}
        className="fixed bottom-4 right-4 z-50 flex h-12 w-12 items-center justify-center
                   rounded-full bg-primary text-primary-foreground shadow-lg
                   transition-transform hover:scale-105"
      >
        {ocupada ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Bot className="h-5 w-5" />
        )}
      </button>

      {abierto && (
        <section
          className="fixed bottom-20 right-4 z-50 flex h-[min(70vh,560px)] w-[min(92vw,400px)]
                     flex-col overflow-hidden rounded-xl border bg-card shadow-xl"
        >
          <header className="flex items-center gap-2 border-b px-3 py-2">
            <Bot className="h-4 w-4 text-primary" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-none">Asistente</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {ficha?.simulado ? "modo simulado · " : ""}
                {ficha?.cuenta || "…"}
              </p>
            </div>
            <Boton variante="fantasma" tamano="icono" tipo="button" title="Nueva charla" onClick={nueva}>
              <MessageSquarePlus />
            </Boton>
            <Boton variante="fantasma" tamano="icono" tipo="button" title="Cerrar" onClick={() => setAbierto(false)}>
              <X />
            </Boton>
          </header>

          {!listo && (
            <p className="border-b bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              {ficha?.motivo || "el asistente no puede contestar todavía"} ·{" "}
              <Link to="/config" className="underline" onClick={() => setAbierto(false)}>
                ir a Configuración
              </Link>
            </p>
          )}

          <div ref={zona} className="flex-1 space-y-2 overflow-y-auto p-3">
            {charla?.turnos.length ? (
              charla.turnos.map((turno) => <Turno key={turno.n} turno={turno} />)
            ) : (
              <p className="pt-8 text-center text-xs text-muted-foreground">
                Pregunta lo que quieras del estudio: ve los pasos del proyecto
                abierto, los trabajos y sus errores.
              </p>
            )}
          </div>

          {aviso && (
            <p className="border-t px-3 py-2 text-xs text-destructive">{aviso}</p>
          )}

          <form
            className="flex items-end gap-2 border-t p-2"
            onSubmit={(e) => {
              e.preventDefault()
              enviar()
            }}
          >
            <AreaTexto
              ref={entrada}
              valor={texto}
              alCambiar={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  enviar()
                }
              }}
              filas={2}
              placeholder="Pregunta al asistente… (Enter envía, Mayús+Enter salta línea)"
              className="max-h-32 min-h-[44px] flex-1 resize-none text-sm"
            />
            {ocupada ? (
              <Boton tipo="button" variante="secundario" title="Parar la respuesta" onClick={cancelar}>
                <Square className="h-4 w-4" />
              </Boton>
            ) : (
              <Boton tipo="submit" deshabilitado={!texto.trim() || !listo} title="Enviar">
                <SendHorizontal className="h-4 w-4" />
              </Boton>
            )}
          </form>
        </section>
      )}
    </>
  )
}
