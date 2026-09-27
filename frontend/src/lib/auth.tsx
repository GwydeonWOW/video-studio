/** Contexto de autenticación compartido entre App y las vistas. */
import { createContext, useContext } from "react"
import type { EstadoAuth } from "./tipos"

export const ContextoAuth = createContext<{
  estado: EstadoAuth | null
  recargar: () => void
}>({ estado: null, recargar: () => {} })

export const useAuth = () => useContext(ContextoAuth)
