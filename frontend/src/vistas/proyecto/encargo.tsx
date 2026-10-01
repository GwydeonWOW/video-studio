/**
 * El encargo: el vídeo dicho en UNA pantalla — qué se cuenta (el
 * material), cómo (el tono) y de qué largo (la duración). Es la
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
import {
  Selector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
  ValorSelector,
} from "../../components/ui/selector"

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

/* ------------------------------------------------ las llamadas a la acción */

interface RanuraCta {
  puesto: boolean
  texto: string
}

interface MomentoCta {
  id: "presentacion" | "cta_medio" | "cta_final"
  nombre: string
  pista: string
  etiqueta: string
  ejemplo: string
  ayuda?: string
}

const MOMENTOS_CTA: MomentoCta[] = [
  {
    id: "presentacion",
    nombre: "Se presenta justo después de la intro",
    pista: "en la primera escena después del gancho, nunca en el gancho",
    etiqueta: "Cómo quieres que se presente",
    ejemplo:
      "di quién soy y que en este vídeo se va a ver cómo se hace esto; " +
      "si les gusta, que le den al like, y empezamos",
    ayuda:
      "Es el patrón, no el texto: el guion lo reescribe con lo que se " +
      "enseñe en cada vídeo. Sencillo —quién eres y qué se va a ver—, sin " +
      "currículum ni «emprendedor y creador de contenido».",
  },
  {
    id: "cta_medio",
    nombre: "Llamada a la acción a mitad del vídeo",
    pista: "en el corte entre dos secciones, después de haber contado algo",
    etiqueta: "Qué quieres que pida",
    ejemplo: "que entre en mi web, donde tiene más información sobre esto",
  },
  {
    id: "cta_final",
    nombre: "Llamada a la acción al final",
    pista: "en la última escena, como despedida",
    etiqueta: "Qué quieres que pida",
    ejemplo:
      "que le dé a like y se suscriba, y que vea el vídeo de la semana " +
      "pasada sobre lo mismo",
  },
]

/** LAS TRES VIENEN APAGADAS: un vídeo no se presenta ni pide nada
 *  mientras nadie lo marque. Lo que no hay guardado cuenta como
 *  apagado (proyectos viejos), y así el prompt sale igual. */
function ctaPorDefecto(): Record<MomentoCta["id"], RanuraCta> {
  return {
    presentacion: { puesto: false, texto: "" },
    cta_medio: { puesto: false, texto: "" },
    cta_final: { puesto: false, texto: "" },
  }
}

/** La caja del servidor, con lo que falte relleno en apagado. */
function ctaDelServidor(guion: Record<string, unknown>) {
  const base = ctaPorDefecto()
  const crudo = guion.cta
  if (crudo && typeof crudo === "object") {
    for (const m of MOMENTOS_CTA) {
      const r = (crudo as Record<string, unknown>)[m.id]
      if (r && typeof r === "object") {
        const ranura = r as Record<string, unknown>
        base[m.id] = {
          puesto: ranura.puesto === true,
          texto: String(ranura.texto ?? ""),
        }
      }
    }
  }
  return base
}

function ctaDifiere(
  local: Record<MomentoCta["id"], RanuraCta>,
  servidor: Record<MomentoCta["id"], RanuraCta>
) {
  return MOMENTOS_CTA.some(
    (m) =>
      local[m.id].puesto !== servidor[m.id].puesto ||
      local[m.id].texto.trim() !== servidor[m.id].texto.trim()
  )
}

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
    duracion: String(params.guion.duracion_min ?? 10),
    formato: String(params.brief.formato ?? "horizontal"),
  }))
  const [cta, setCta] = useState(() => ctaDelServidor(params.guion))
  // lo que hay en el servidor: la base sobre la que se fusiona cada
  // guardado (PUT reemplaza, no fusiona)
  const guardados = useRef<ParamsEncargo>({ ...params })
  const [estado, setEstado] = useState<"ok" | "pendiente" | "guardando">("ok")

  const cambiar = (clave: keyof typeof campos, valor: string) =>
    setCampos((c) => ({ ...c, [clave]: valor }))

  const cambiarCta = (id: MomentoCta["id"], parche: Partial<RanuraCta>) =>
    setCta((prev) => ({ ...prev, [id]: { ...prev[id], ...parche } }))

  useEffect(() => {
    // el diccionario ENTERO que se mandaría de este paso: lo guardado
    // con solo las teclas cambiadas (sin tocar la base hasta que el
    // PUT salga bien, o un fallo parecería guardado y no se reintentaría)
    const ctaServidor = ctaDelServidor(guardados.current.guion)
    const ctaCambia = ctaDifiere(cta, ctaServidor)
    const merged = (paso: "ingesta" | "brief" | "guion") => {
      const base = { ...guardados.current[paso] }
      if (paso === "ingesta") {
        if (campos.titulo !== String(base.titulo ?? "")) base.titulo = campos.titulo
        if (campos.texto !== String(base.texto ?? "")) base.texto = campos.texto
      } else if (paso === "brief") {
        if (campos.tono !== String(base.tono ?? "")) base.tono = campos.tono
        // ?? "horizontal": sin la tecla guardada el campo nació en
        // horizontal — dejarlo ahí no es un cambio; escribirlo sería
        // sembrar el defecto (y mover la firma de lo ya pagado)
        if (campos.formato !== String(base.formato ?? "horizontal"))
          base.formato = campos.formato
      } else {
        const n = Number(campos.duracion)
        if (Number.isFinite(n) && n >= 1) base.duracion_min = Math.round(n)
        // la caja de las llamadas a la acción solo viaja si alguien la
        // ha tocado: escribirla apagada en un proyecto que no la tenía
        // movería la firma del guion sin haber decidido nada
        if (ctaCambia) base.cta = cta
      }
      return base
    }

    const difiere = (paso: "ingesta" | "brief" | "guion") => {
      const b = guardados.current[paso]
      if (paso === "ingesta")
        return campos.titulo !== String(b.titulo ?? "") ||
          campos.texto !== String(b.texto ?? "")
      if (paso === "brief")
        return campos.tono !== String(b.tono ?? "") ||
          campos.formato !== String(b.formato ?? "horizontal")
      const n = Number(campos.duracion)
      // ?? 10: si el servidor no trae duración, el campo nació en 10 —
      // dejarlo intacto no es un cambio; escribirlo sería sembrar el
      // default (y volver obsoleto un guion ya pagado sin motivo)
      return (
        (Number.isFinite(n) && n >= 1 && Math.round(n) !== (b.duracion_min ?? 10)) ||
        ctaCambia
      )
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
  }, [campos, cta, pid])

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

      <div className="grid gap-4 sm:grid-cols-3">
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
          <Etiqueta htmlFor="encargo-duracion">Duración (min)</Etiqueta>
          <Entrada
            id="encargo-duracion"
            tipo="number"
            valor={campos.duracion}
            alCambiar={(e) => cambiar("duracion", e.target.value)}
            min={1}
            max={120}
          />
          <p className="text-xs text-muted-foreground">
            duración aproximada del vídeo: el guion sale con las escenas
            que hagan falta para durarla
          </p>
        </div>
        <div className="space-y-2">
          <Etiqueta>Formato</Etiqueta>
          <Selector
            valor={campos.formato}
            alCambiar={(v) => cambiar("formato", v)}
          >
            <DisparadorSelector>
              <ValorSelector />
            </DisparadorSelector>
            <ContenidoSelector>
              <Opcion valor="horizontal">Horizontal 16:9</Opcion>
              <Opcion valor="vertical">Vertical 9:16</Opcion>
            </ContenidoSelector>
          </Selector>
          <p className="text-xs text-muted-foreground">
            el porte del vídeo; cambiarlo tras generar deja obsoletas las
            imágenes y el montaje
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="space-y-1">
          <p className="text-sm font-medium">
            Presentación y llamadas a la acción
          </p>
          <p className="text-xs text-muted-foreground">
            las tres vienen apagadas: marca solo lo que quieras que este
            vídeo haga
          </p>
        </div>
        {MOMENTOS_CTA.map((m) => {
          const ranura = cta[m.id]
          return (
            <div
              key={m.id}
              className={
                "space-y-2 rounded-md border p-3 " +
                (ranura.puesto ? "" : "opacity-80")
              }
            >
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={ranura.puesto}
                  onChange={(e) =>
                    cambiarCta(m.id, { puesto: e.target.checked })
                  }
                />
                {m.nombre}
              </label>
              <p className="pl-6 text-xs text-muted-foreground">{m.pista}</p>
              {ranura.puesto && (
                <div className="space-y-2 pl-6">
                  <Etiqueta htmlFor={`cta-${m.id}`}>{m.etiqueta}</Etiqueta>
                  <AreaTexto
                    id={`cta-${m.id}`}
                    filas={2}
                    valor={ranura.texto}
                    alCambiar={(e) =>
                      cambiarCta(m.id, { texto: e.target.value })
                    }
                    placeholder={m.ejemplo}
                  />
                  {m.ayuda && (
                    <p className="text-xs text-muted-foreground">{m.ayuda}</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
        <p className="text-xs text-muted-foreground">
          Cada uno es una escena más del guion —misma voz, mismo tono—,
          no una cuña pegada al final. Lo que escribas es una indicación,
          no el texto final: lo redacta con las palabras de ESTE vídeo.
        </p>
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
