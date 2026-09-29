/**
 * El kit visual del canal: subir imágenes de referencia y verlas.
 *
 * Lo usan la pantalla de Estilo (el kit canónico del canal, que hereda
 * cada vídeo nuevo) y el modo light (el buzón del encargo). El
 * transporte es el mismo: base64 dentro de JSON, como las capturas.
 */
import { useRef, useState } from "react"
import { ImagePlus, Loader2, X } from "lucide-react"
import { api } from "../lib/api"
import type { ImagenAportada, RespuestaAportadas } from "../lib/tipos"

export const EXT_APORTADAS = [".png", ".jpg", ".jpeg", ".webp"]
export const MAX_MB_APORTADA = 10

const leer_como_data_url = (f: File): Promise<string> =>
  new Promise((ok, ko) => {
    const lector = new FileReader()
    lector.onload = () => ok(String(lector.result))
    lector.onerror = () => ko(lector.error ?? new Error("lectura fallida"))
    lector.readAsDataURL(f)
  })

/** Sube ficheros al endpoint que sea (base64 en JSON). Lo que no pasa,
 *  vuelve en avisos: nada tira el resto. */
export async function subir_imagenes(
  destino: string,
  ficheros: FileList | File[],
  ya: number,
  tope: number,
): Promise<{ imagenes: ImagenAportada[]; avisos: string[] }> {
  const lista = Array.from(ficheros)
  const avisos: string[] = []
  const hueco = Math.max(tope - ya, 0)
  if (lista.length > hueco)
    avisos.push(
      `el tope es ${tope}: se suben ${hueco} y se dejan ${lista.length - hueco}`,
    )
  const entradas: { nombre: string; datos: string }[] = []
  for (const f of lista.slice(0, hueco)) {
    const punto = f.name.lastIndexOf(".")
    const ext = punto < 0 ? "" : f.name.slice(punto).toLowerCase()
    if (!EXT_APORTADAS.includes(ext)) {
      avisos.push(`${f.name}: no es png, jpg ni webp`)
      continue
    }
    if (f.size > MAX_MB_APORTADA * 1024 * 1024) {
      avisos.push(`${f.name}: pesa más de ${MAX_MB_APORTADA} MB`)
      continue
    }
    entradas.push({ nombre: f.name, datos: await leer_como_data_url(f) })
  }
  if (!entradas.length) return { imagenes: [], avisos }
  const r = await api.post<RespuestaAportadas>(destino, {
    imagenes: entradas,
  })
  return { imagenes: r.imagenes, avisos: [...avisos, ...r.avisos] }
}

/** Zona de arrastre + miniaturas con su quitar. La fuente de la guía. */
export function KitVisual({
  imagenes,
  url,
  tope,
  subiendo,
  alElegir,
  alQuitar,
}: {
  imagenes: { nombre: string; origen?: string }[]
  url: (nombre: string) => string
  tope: number
  subiendo: boolean
  alElegir: (ficheros: FileList | File[]) => void
  alQuitar: (nombre: string) => void
}) {
  const [arrastrando, setArrastrando] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)
  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") entrada.current?.click()
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastrando(true)
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastrando(false)
          if (e.dataTransfer.files.length) alElegir(e.dataTransfer.files)
        }}
        className={`cursor-pointer rounded-md border border-dashed px-3 py-4 text-center text-xs transition-colors ${
          arrastrando
            ? "border-primary bg-primary/5 text-foreground"
            : "text-muted-foreground"
        }`}
      >
        {subiendo ? (
          <Loader2 className="mx-auto h-4 w-4 animate-spin" />
        ) : (
          <>
            <ImagePlus className="mx-auto mb-1 h-4 w-4" />
            <p>
              suelta aquí tu kit visual o haz clic: png · jpg · webp, hasta{" "}
              {MAX_MB_APORTADA} MB por imagen
            </p>
          </>
        )}
        <input
          ref={entrada}
          type="file"
          accept={EXT_APORTADAS.join(",")}
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) alElegir(e.target.files)
            e.target.value = ""
          }}
        />
      </div>
      {imagenes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {imagenes.map((i) => (
            <div key={i.nombre} className="group relative">
              <img
                src={url(i.nombre)}
                alt={i.origen ?? i.nombre}
                title={i.origen ?? i.nombre}
                className="h-16 w-16 rounded-md border object-cover"
              />
              <button
                type="button"
                onClick={() => alQuitar(i.nombre)}
                title="quitar"
                className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border bg-background shadow-sm"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            {imagenes.length}/{tope}
          </p>
        </div>
      )}
    </div>
  )
}
