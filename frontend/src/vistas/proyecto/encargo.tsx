/**
 * El encargo: el vídeo dicho en UNA pantalla — qué se cuenta (el
 * material), cómo (el tono) y de qué largo (las escenas). Es la
 * primera de las cinco paradas del móvil y el atajo de escritorio
 * para quien no quiere vivir en nueve pestañas.
 *
 * El autoguardado es con retardo y MANDA EL DICCIONARIO ENTERO que
 * hay guardado, con solo la tecla cambiada: PUT .../params REEMPLAZA
 * los params del paso, así que mandar solo una clave borraría las
 * demás (y las sembradas por el estilo del canal con ellas). Lo que
 * el usuario no ha tocado, no se manda: los valores por defecto no
 * se escriben nunca — una firma que cambia sin motivo vuelve obsoleto
 * lo que ya se pagó.
 */
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Check, Loader2, Play } from "lucide-react"
import { api } from "../../lib/api"
import { Boton } from "../../components/ui/button"
import { Entrada } from "../../components/ui/input"
import { Etiqueta } from "../../components/ui/etiqueta"
import { AreaTexto } from "../../components/ui/textarea"

/** Los params que el encargo sabe editar, tal como están GUARDADOS. */
export interface ParamsEncargo {
  ingesta: Record<string, unknown>
  brief: Record<string, unknown>
  guion: Record<string, unknown>
}

interface PropsEncargo {
  pid: string
  ocupado: boolean
  params: ParamsEncargo
  /** si la ingesta ya tiene datos (el guion puede beber de ella) */
  material_listo: boolean
  /** true mientras no se haya generado ningún guion */
  guion_vacio: boolean
  /** lanza el paso 3 con lo escrito aquí */
  alEjecutarGuion: () => void
  /** refresca los resúmenes del proyecto (estados y obsoletos) */
  alGuardar: () => void
}

const RETARDO_MS = 800

export function PanelEncargo({
  pid,
  ocupado,
  params,
  material_listo,
  guion_vacio,
  alEjecutarGuion,
  alGuardar,
}: PropsEncargo) {
  const [campos, setCampos] = useState(() => ({
    titulo: String(params.ingesta.titulo ?? ""),
    texto: String(params.ingesta.texto ?? ""),
    tono: String(params.brief.tono ?? ""),
    escenas: String(params.guion.escenas ?? 8),
  }))
  // lo que hay en el servidor: la base sobre la que se fusiona cada
  // guardado (PUT reemplaza, no fusiona)
  const guardados = useRef<ParamsEncargo>({ ...params })
  const [estado, setEstado] = useState<"ok" | "pendiente" | "guardando">("ok")

  const cambiar = (clave: keyof typeof campos, valor: string) =>
    setCampos((c) => ({ ...c, [clave]: valor }))

  useEffect(() => {
    // el diccionario ENTERO que se mandaría de este paso: lo guardado
    // con solo las teclas cambiadas (sin tocar la base hasta que el
    // PUT salga bien, o un fallo parecería guardado y no se reintentaría)
    const merged = (paso: "ingesta" | "brief" | "guion") => {
      const base = { ...guardados.current[paso] }
      if (paso === "ingesta") {
        if (campos.titulo !== String(base.titulo ?? "")) base.titulo = campos.titulo
        if (campos.texto !== String(base.texto ?? "")) base.texto = campos.texto
      } else if (paso === "brief") {
        if (campos.tono !== String(base.tono ?? "")) base.tono = campos.tono
      } else {
        const n = Number(campos.escenas)
        if (Number.isFinite(n) && n >= 1) base.escenas = Math.round(n)
      }
      return base
    }

    const difiere = (paso: "ingesta" | "brief" | "guion") => {
      const b = guardados.current[paso]
      if (paso === "ingesta")
        return campos.titulo !== String(b.titulo ?? "") ||
          campos.texto !== String(b.texto ?? "")
      if (paso === "brief") return campos.tono !== String(b.tono ?? "")
      const n = Number(campos.escenas)
      // ?? 8: si el servidor no trae escenas, el campo nació en 8 —
      // dejarlo intacto no es un cambio; escribirlo sería sembrar el
      // default (y volver obsoleto un guion ya pagado sin motivo)
      return Number.isFinite(n) && n >= 1 && Math.round(n) !== (b.escenas ?? 8)
    }

    const cambios: ("ingesta" | "brief" | "guion")[] =
      (["ingesta", "brief", "guion"] as const).filter(difiere)
    if (cambios.length === 0) {
      setEstado("ok")
      return
    }
    setEstado("pendiente")
    const t = setTimeout(async () => {
      setEstado("guardando")
      try {
        // un PUT por paso, en serie: cada uno con su diccionario ENTERO
        for (const paso of cambios) {
          const nuevo = merged(paso)
          await api.put(`/api/proyectos/${pid}/pasos/${paso}/params`, nuevo)
          guardados.current[paso] = nuevo
        }
        setEstado("ok")
        alGuardar()
      } catch (e) {
        toast.error(String((e as Error).message ?? e))
        setEstado("pendiente") // se reintentará con la próxima tecla
      }
    }, RETARDO_MS)
    return () => clearTimeout(t)
    // alGuardar a propósito: estable durante la vida del panel
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campos, pid])

  const puede_guion = material_listo

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        El vídeo entero dicho en una pantalla: qué se cuenta, cómo se
        cuenta y de qué largo. Se guarda solo mientras escribes; los
        nueve pasos siguen ahí arriba para el ajuste fino.
      </p>

      <div className="space-y-2">
        <Etiqueta htmlFor="encargo-titulo">Título (opcional)</Etiqueta>
        <Entrada
          id="encargo-titulo"
          valor={campos.titulo}
          alCambiar={(e) => cambiar("titulo", e.target.value)}
          placeholder="si queda vacío se toma del primer párrafo"
        />
      </div>

      <div className="space-y-2">
        <Etiqueta htmlFor="encargo-texto">Material de origen</Etiqueta>
        <AreaTexto
          id="encargo-texto"
          filas={12}
          valor={campos.texto}
          alCambiar={(e) => cambiar("texto", e.target.value)}
          placeholder="pega aquí el artículo, guion bruto o material…"
          className="font-mono text-[13px]"
        />
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          {campos.texto.trim().length} caracteres
          <span className="ml-auto inline-flex items-center gap-1">
            {estado === "guardando" ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" /> guardando…
              </>
            ) : estado === "pendiente" ? (
              "cambios sin guardar"
            ) : (
              <>
                <Check className="h-3 w-3 text-emerald-600" /> guardado
              </>
            )}
          </span>
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Etiqueta htmlFor="encargo-tono">Tono</Etiqueta>
          <Entrada
            id="encargo-tono"
            valor={campos.tono}
            alCambiar={(e) => cambiar("tono", e.target.value)}
            placeholder="cercano, divulgativo, sobrio…"
          />
          <p className="text-xs text-muted-foreground">
            la línea editorial que se le pasa al brief y al guion
          </p>
        </div>
        <div className="space-y-2">
          <Etiqueta htmlFor="encargo-escenas">Escenas</Etiqueta>
          <Entrada
            id="encargo-escenas"
            tipo="number"
            valor={campos.escenas}
            alCambiar={(e) => cambiar("escenas", e.target.value)}
            min={1}
            max={30}
          />
          <p className="text-xs text-muted-foreground">
            de cuántas escenas saldrá el guion (paso 3)
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-md border bg-card p-3">
        <Boton
          onClick={alEjecutarGuion}
          deshabilitado={ocupado || !puede_guion}
          title={
            puede_guion
              ? "Lanza el paso 3 (guion) con lo escrito aquí"
              : "Procesa el material primero: sin ingesta no hay guion del que partir"
          }
        >
          {ocupado ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Play />
          )}
          {guion_vacio ? "Generar el guion" : "Regenerar el guion"}
        </Boton>
        <p className="text-xs text-muted-foreground">
          {puede_guion
            ? "cada generación gasta tokens del modelo del guion"
            : "procesa el material primero (parada Encargo → paso 1)"}
        </p>
      </div>
    </div>
  )
}
