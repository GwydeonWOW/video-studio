import { useCallback, useEffect, useState } from "react"
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom"
import { Video } from "lucide-react"
import { api } from "./lib/api"
import { ContextoAuth, useAuth } from "./lib/auth"
import type { EstadoAuth } from "./lib/tipos"
import Login from "./vistas/Login"
import Galeria from "./vistas/Galeria"
import Proyecto from "./vistas/Proyecto"
import Configuracion from "./vistas/Configuracion"

function Cabecera() {
  const { estado } = useAuth()
  return (
    <header className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <Video className="h-5 w-5 text-primary" />
          Estudio de Vídeo
        </Link>
        <nav className="ml-auto flex items-center gap-1 text-sm">
          <Link
            to="/"
            className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            Proyectos
          </Link>
          <Link
            to="/config"
            className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            Configuración
          </Link>
          {estado?.autenticado && estado.usuario && (
            <span className="ml-2 hidden rounded-md bg-secondary px-2.5 py-1 text-xs text-muted-foreground sm:inline">
              {estado.usuario}
            </span>
          )}
        </nav>
      </div>
    </header>
  )
}

export default function App() {
  const [estado, setEstado] = useState<EstadoAuth | null>(null)
  const localizacion = useLocation()

  const recargar = useCallback(() => {
    api
      .get<EstadoAuth>("/api/auth/estado")
      .then(setEstado)
      .catch(() =>
        setEstado({
          instalacion: false,
          sin_login: false,
          usuario: null,
          autenticado: false,
        })
      )
  }, [])

  useEffect(recargar, [recargar])

  // sin ficha todavía: pantalla en blanco un instante
  if (!estado) return null

  // instalación pendiente o sesión ausente -> siempre al login
  const necesita_entrada = estado.instalacion || !estado.autenticado

  return (
    <ContextoAuth.Provider value={{ estado, recargar }}>
      {necesita_entrada ? (
        localizacion.pathname !== "/entra" ? (
          <Navigate to="/entra" replace />
        ) : (
          <Login />
        )
      ) : (
        <>
          <Cabecera />
          <main className="mx-auto max-w-7xl px-4 py-6">
            <Routes>
              <Route path="/" element={<Galeria />} />
              <Route path="/p/:pid" element={<Proyecto />} />
              <Route path="/config" element={<Configuracion />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </>
      )}
    </ContextoAuth.Provider>
  )
}
