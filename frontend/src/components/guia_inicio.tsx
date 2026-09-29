/**
 * La guía de inicio: las siete tarjetas que se ven UNA VEZ por
 * instalación, no por navegador — la marca (`onboarding_visto`) vive en
 * los ajustes del servidor, y «Saltar por ahora» también la pone. Una
 * guía que reaparece en cada carga es una pantalla que se aprende a
 * cerrar sin leer.
 *
 * Las claves se piden a la misma API que Configuración: aquí nunca baja
 * una clave, solo su cola (la máscara).
 */
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Check, ExternalLink, Loader2 } from "lucide-react"
import { api } from "../lib/api"
import type { ClaveEstado } from "../lib/tipos"
import { Boton } from "./ui/button"
import { Insignia } from "./ui/badge"
import { Entrada } from "./ui/input"

interface PropsTarjetaClave {
  pista: React.ReactNode
  estado: ClaveEstado | undefined
  alGuardar: (clave: string, valor: string) => Promise<void>
  guardando: boolean
}

/** El cuerpo compartido de las tarjetas de clave: qué hace falta, en qué
 * estado está, y el campo para pegarla (Enter manda). */
function TarjetaClave({ pista, estado, alGuardar, guardando }: PropsTarjetaClave) {
  const [valor, setValor] = useState("")
  const clave = estado?.clave ?? ""

  const mandar = () => {
    const limpio = valor.trim()
    if (!limpio) {
      toast.error("pega la clave primero")
      return
    }
    alGuardar(clave, limpio)
    setValor("")
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{pista}</p>
      <div className="flex items-center gap-2 text-sm">
        {estado?.presente ? (
          <Insignia variante="exito">puesta ({estado.mascara})</Insignia>
        ) : (
          <Insignia variante="destructivo">sin poner</Insignia>
        )}
        <span className="text-xs text-muted-foreground">
          {estado?.presente
            ? "Ya está. Puedes cambiarla aquí mismo o seguir."
            : "Pégala aquí cuando la tengas."}
        </span>
      </div>
      <div className="flex gap-2">
        <Entrada
          tipo="password"
          valor={valor}
          alCambiar={(e) => setValor(e.target.value)}
          placeholder={estado?.variable ?? "la clave"}
          autoComplete="off"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              mandar()
            }
          }}
        />
        <Boton variante="secundario" deshabilitado={guardando} onClick={mandar}>
          {guardando ? <Loader2 className="animate-spin" /> : null}
          Guardar
        </Boton>
      </div>
    </div>
  )
}

function Enlace({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      className="inline-flex items-center gap-1 font-medium underline underline-offset-2"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ExternalLink className="h-3 w-3" />
    </a>
  )
}

/** Qué enseña cada tarjeta de clave, con el id de nuestro catálogo. */
const TARJETAS_CLAVE: {
  id: string
  titulo: string
  pista: React.ReactNode
}[] = [
  {
    id: "glm",
    titulo: "1 · La clave de GLM (textos e imágenes)",
    pista: (
      <>
        Escribe el guion, corrige escenas, redacta los rótulos, contesta al
        asistente de la burbuja y dibuja los planos del vídeo. Se saca de{" "}
        <Enlace href="https://z.ai">z.ai</Enlace> (API de GLM).
      </>
    ),
  },
  {
    id: "openai",
    titulo: "2 · La clave de OpenAI (textos, opcional)",
    pista: (
      <>
        Solo si prefieres GPT para los textos: las imágenes ya las dibuja
        GLM. También hay un tercer camino sin clave —conectar la cuenta de
        ChatGPT (Codex) desde Configuración. Se saca de{" "}
        <Enlace href="https://platform.openai.com/api-keys">
          platform.openai.com
        </Enlace>
        .
      </>
    ),
  },
  {
    id: "elevenlabs",
    titulo: "3 · La clave de ElevenLabs (voz)",
    pista: (
      <>
        La voz que narra el vídeo. Se saca de{" "}
        <Enlace href="https://elevenlabs.io">elevenlabs.io</Enlace>.
      </>
    ),
  },
  {
    id: "jamendo",
    titulo: "4 · La clave de Jamendo (música, opcional)",
    pista: (
      <>
        Música de fondo con licencia. Es una de las dos que se puede dejar
        para luego. Se saca de <Enlace href="https://devportal.jamendo.com">devportal.jamendo.com</Enlace>.
      </>
    ),
  },
  {
    id: "freesound",
    titulo: "5 · La clave de FreeSound (efectos, opcional)",
    pista: (
      <>
        Efectos de sonido. La otra que puede esperar. Se saca de{" "}
        <Enlace href="https://freesound.org/apiv2/apply">freesound.org</Enlace>{" "}
        (la columna «Api key», no el Client id).
      </>
    ),
  },
]

const TOTAL = TARJETAS_CLAVE.length + 2

export function GuiaInicio({ alCerrar }: { alCerrar: () => void }) {
  const [paso, setPaso] = useState(0)
  const [claves, setClaves] = useState<ClaveEstado[] | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    api
      .get<ClaveEstado[]>("/api/claves")
      .then(setClaves)
      .catch(() => setClaves([]))
  }, [])

  const cerrar = (marcar: boolean) => {
    if (marcar) {
      // silenciosa a propósito: cerrar la guía no puede fallarle a nadie
      api.put("/api/ajustes", { onboarding_visto: true }).catch(() => {})
    }
    alCerrar()
  }

  const guardarClave = async (clave: string, valor: string) => {
    setGuardando(true)
    try {
      const lista = await api.put<ClaveEstado[]>("/api/claves", {
        [clave]: valor,
      })
      setClaves(lista)
      toast.success("clave guardada")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const ultima = paso === TOTAL - 1

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-lg border bg-card p-5 shadow-lg">
        <div className="flex items-center gap-3 text-sm">
          <span className="text-xs text-muted-foreground">
            guía de inicio · {paso + 1} de {TOTAL}
          </span>
          <div className="flex flex-1 items-center justify-center gap-1.5">
            {Array.from({ length: TOTAL }, (_, i) => (
              <span
                key={i}
                title={tituloDe(i)}
                className={`h-1.5 w-1.5 rounded-full ${
                  i < paso
                    ? "bg-primary"
                    : i === paso
                      ? "bg-primary ring-2 ring-primary/30"
                      : "bg-muted-foreground/25"
                }`}
              />
            ))}
          </div>
          <Boton
            variante="fantasma"
            tamano="pequeno"
            title="Cerrar la guía; todo esto está en Configuración"
            onClick={() => cerrar(true)}
          >
            Saltar por ahora
          </Boton>
        </div>

        <div className="mt-4 flex-1 overflow-y-auto text-sm">
          {paso === 0 && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">
                Bienvenido al Estudio de Vídeo
              </h2>
              <p className="text-muted-foreground">
                Esto convierte lo que escribas —unas notas, un artículo, tu
                propio guion— en un vídeo de animación narrada, en varios
                pasos con revisión entre ellos. Para que pueda hacerlo
                necesita hablar con cinco servicios, y cada uno pide su
                llave. Esta guía te lleva a por ellas una a una, con el
                enlace de cada sitio.
              </p>
              <ol className="list-decimal space-y-1 pl-5">
                <li>
                  <b>GLM</b>: el guion, los rótulos, el asistente de la
                  burbuja y los planos dibujados.
                </li>
                <li>
                  <b>OpenAI</b>: opcional, GPT para los textos si no usas
                  GLM. Y sin clave ninguna también se pueden escribir los
                  textos con la cuenta de ChatGPT (<b>Codex</b>): se conecta
                  desde Configuración con un código en el navegador.
                </li>
                <li>
                  <b>ElevenLabs</b>: la voz que narra.
                </li>
                <li>
                  <b>Jamendo y FreeSound</b>: música y efectos. Se pueden
                  dejar para luego; GLM y ElevenLabs son las que hacen
                  falta.
                </li>
              </ol>
              <p className="rounded-md border bg-muted/40 p-3">
                Abajo a la derecha hay una burbuja: es el asistente. Sabe
                cómo funciona todo esto y ve lo que está pasando en tu
                Estudio, así que cuando algo falle o no sepas seguir,
                pregúntale.
              </p>
              <p className="text-xs text-muted-foreground">
                Todo lo que pongas aquí se cambia después desde
                Configuración, arriba a la derecha.
              </p>
            </div>
          )}

          {paso > 0 && paso < TOTAL - 1 && (() => {
            const t = TARJETAS_CLAVE[paso - 1]
            return (
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">{t.titulo}</h2>
                <TarjetaClave
                  pista={t.pista}
                  estado={claves?.find((c) => c.clave === t.id)}
                  alGuardar={guardarClave}
                  guardando={guardando}
                />
              </div>
            )
          })()}

          {ultima && (() => {
            const presente = (id: string) =>
              !!claves?.find((c) => c.clave === id)?.presente
            const imprescindibles = ["glm", "elevenlabs"].filter(
              (id) => !presente(id),
            )
            return (
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">Todo listo</h2>
                {[
                  { id: "glm", nombre: "GLM — guion, rótulos, imágenes y el asistente" },
                  { id: "elevenlabs", nombre: "ElevenLabs — voz" },
                  { id: "openai", nombre: "OpenAI — textos (opcional)", opcional: true },
                  { id: "jamendo", nombre: "Jamendo — música", opcional: true },
                  { id: "freesound", nombre: "FreeSound — efectos", opcional: true },
                ].map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    {presente(f.id) ? (
                      <Insignia variante="exito">puesta</Insignia>
                    ) : f.opcional ? (
                      <Insignia variante="aviso">para luego</Insignia>
                    ) : (
                      <Insignia variante="destructivo">sin poner</Insignia>
                    )}
                    <span>{f.nombre}</span>
                  </div>
                ))}
                {imprescindibles.length > 0 ? (
                  <p className="rounded-md border border-amber-300/60 bg-amber-100/60 p-3 text-sm dark:bg-amber-950/40">
                    Faltan {imprescindibles.length} de las dos que hacen falta
                    para un vídeo (GLM y ElevenLabs). Sin ellas no sale el
                    vídeo entero: se ponen desde Configuración, arriba a la
                    derecha.
                  </p>
                ) : (
                  <p className="flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    Está todo. Lo siguiente es crear un estilo (cómo se dibuja
                    y cómo se cuenta) y, con él, el primer vídeo.
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  Las claves se pueden probar desde Configuración → Claves →
                  «Probar claves», sin gastar nada. Y si algo no cuadra en
                  cualquier momento, la burbuja de abajo a la derecha es el
                  asistente: pregúntale.
                </p>
              </div>
            )
          })()}
        </div>

        <div className="mt-4 flex items-center justify-between">
          {paso > 0 ? (
            <Boton
              variante="fantasma"
              tamano="pequeno"
              onClick={() => setPaso((p) => p - 1)}
            >
              ‹ Atrás
            </Boton>
          ) : (
            <span />
          )}
          {ultima ? (
            <Boton onClick={() => cerrar(true)}>
              <Check /> Empezar
            </Boton>
          ) : (
            <Boton onClick={() => setPaso((p) => p + 1)}>
              {paso === 0 ? "Vamos" : "Siguiente ›"}
            </Boton>
          )}
        </div>
      </div>
    </div>
  )
}

/** El título de cada tarjeta, para el title de los puntos. */
function tituloDe(paso: number): string {
  if (paso === 0) return "Bienvenida"
  if (paso === TOTAL - 1) return "Todo listo"
  return TARJETAS_CLAVE[paso - 1].titulo
}
