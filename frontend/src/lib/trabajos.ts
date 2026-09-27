/** Seguimiento de trabajos en vivo vía SSE (GET /api/trabajos/{tid}/eventos). */
import { useEffect, useRef, useState } from "react"
import type { TrabajoEvento, TrabajoFicha } from "./tipos"

interface Args {
  tid: string | null
  /** Se llama una sola vez cuando el trabajo termina (hecho/fallo/cancelado). */
  alTerminar?: (ficha: TrabajoFicha) => void
}

const TERMINALES = new Set(["hecho", "fallo", "cancelado"])

export function usarTrabajo({ tid, alTerminar }: Args) {
  const [ficha, setFicha] = useState<TrabajoFicha | null>(null)
  const [lineas, setLineas] = useState<TrabajoEvento[]>([])
  const [conectado, setConectado] = useState(false)
  const al_terminar = useRef(alTerminar)
  al_terminar.current = alTerminar

  useEffect(() => {
    setFicha(null)
    setLineas([])
    setConectado(false)
    if (!tid) return

    let terminado = false
    const fuente = new EventSource(`/api/trabajos/${tid}/eventos?desde=0`)

    const al_estado = (e: MessageEvent) => {
      if (!terminado) setFicha(JSON.parse(e.data) as TrabajoFicha)
    }
    const al_avance = (e: MessageEvent) => {
      if (terminado) return
      const datos = JSON.parse(e.data) as { desde: number; eventos: TrabajoEvento[] }
      setLineas((previas) => [...previas, ...datos.eventos])
    }
    const al_fin = (e: MessageEvent) => {
      if (terminado) return
      terminado = true
      const completa = JSON.parse(e.data) as TrabajoFicha
      setFicha(completa)
      if (completa.lineas) setLineas(completa.lineas)
      setConectado(false)
      fuente.close()
      al_terminar.current?.(completa)
    }

    fuente.onopen = () => setConectado(true)
    fuente.addEventListener("estado", al_estado as EventListener)
    fuente.addEventListener("avance", al_avance as EventListener)
    fuente.addEventListener("fin", al_fin as EventListener)
    fuente.onerror = () => {
      if (terminado) return
      // el servidor cierra el flujo cuando el trabajo ya no existe
      setFicha((actual) => {
        if (actual && TERMINALES.has(actual.estado)) {
          terminado = true
          setConectado(false)
          fuente.close()
        }
        return actual
      })
    }
    return () => {
      terminado = true
      fuente.close()
    }
  }, [tid])

  return { ficha, lineas, conectado }
}
