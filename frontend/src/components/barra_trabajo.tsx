/** Barra flotante: sigue un trabajo por SSE hasta que termina. */
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { ChevronDown, ChevronUp, Loader2, XCircle } from "lucide-react"
import { api } from "../lib/api"
import { usarTrabajo } from "../lib/trabajos"
import { NOMBRES_PASOS, type TrabajoFicha } from "../lib/tipos"
import { Boton } from "./ui/button"
import { Insignia } from "./ui/badge"
import { Progreso } from "./ui/progreso"

const COLOR_ESTADO: Record<
  string,
  "secundario" | "aviso" | "exito" | "destructivo"
> = {
  en_cola: "secundario",
  ejecutando: "aviso",
  hecho: "exito",
  fallo: "destructivo",
  cancelado: "secundario",
}

export function BarraTrabajo({
  tid,
  alTerminar,
}: {
  tid: string
  alTerminar: (ficha: TrabajoFicha) => void
}) {
  const { ficha, lineas, conectado } = usarTrabajo({ tid, alTerminar })
  const [expandido, setExpandido] = useState(false)
  const fin_lista = useRef<HTMLDivElement>(null)
  const cancelando = useRef(false)

  useEffect(() => {
    if (expandido) fin_lista.current?.scrollIntoView({ block: "end" })
  }, [lineas.length, expandido])

  const cancelar = async () => {
    if (cancelando.current) return
    cancelando.current = true
    try {
      await api.post(`/api/trabajos/${tid}/cancelar`)
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
      cancelando.current = false
    }
  }

  const estado = ficha?.estado ?? "en_cola"
  const activo = estado === "en_cola" || estado === "ejecutando"
  const nombre_paso = NOMBRES_PASOS[ficha?.paso ?? ""] ?? ficha?.paso ?? "…"
  const ultima = lineas.length > 0 ? lineas[lineas.length - 1].mensaje : ""

  return (
    <div className="fixed bottom-4 left-1/2 z-50 w-full max-w-2xl -translate-x-1/2 px-4">
      <div className="rounded-lg border bg-card p-3 shadow-lg">
        {activo && <Progreso valor={100} className="mb-2 h-1 animate-pulse" />}
        <div className="flex items-center gap-3">
          {activo ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
          ) : null}
          <Insignia variante={COLOR_ESTADO[estado] ?? "secundario"}>
            {nombre_paso}
          </Insignia>
          <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
            {ficha?.error ? (
              <span className="text-destructive">{ficha.error}</span>
            ) : (
              ultima || (conectado ? "conectado…" : "conectando…")
            )}
          </span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {lineas.length} líneas
          </span>
          <Boton
            variante="fantasma"
            tamano="icono"
            title={expandido ? "Ocultar detalle" : "Ver detalle"}
            onClick={() => setExpandido((v) => !v)}
          >
            {expandido ? <ChevronUp /> : <ChevronDown />}
          </Boton>
          {activo && (
            <Boton
              variante="fantasma"
              tamano="icono"
              title="Cancelar trabajo"
              onClick={cancelar}
            >
              <XCircle />
            </Boton>
          )}
        </div>
        {expandido && (
          <div className="mt-2 max-h-48 overflow-y-auto rounded-md bg-muted/60 p-2 font-mono text-xs leading-relaxed">
            {lineas.map((l, i) => (
              <p key={i} className="whitespace-pre-wrap">
                <span className="text-muted-foreground">
                  {new Date(l.t).toLocaleTimeString()}{" "}
                </span>
                {l.mensaje}
              </p>
            ))}
            <div ref={fin_lista} />
          </div>
        )}
      </div>
    </div>
  )
}
