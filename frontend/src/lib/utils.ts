import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...entradas: ClassValue[]) {
  return twMerge(clsx(entradas))
}

export function dolares(coste: number | null | undefined): string {
  if (coste == null) return "—"
  if (coste === 0) return "$0"
  if (coste < 0.01) return `$${coste.toFixed(4)}`
  return `$${coste.toFixed(2)}`
}

export function segundos(s: number | null | undefined): string {
  if (s == null) return "—"
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return m > 0 ? `${m}m ${r}s` : `${r}s`
}

/**
 * La narración tal y como suena: sin las anotaciones de voz (<break/>),
 * que el locutor calla pero en pantalla serían ruido. Es lo que se
 * muestra siempre; el texto con etiquetas solo existe para el TTS.
 */
export function sinAnotaciones(texto: string | null | undefined): string {
  return (texto ?? "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
}
