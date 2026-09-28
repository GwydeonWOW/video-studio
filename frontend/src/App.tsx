import { useCallback, useEffect, useState } from "react"
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom"
import { Video, Wallet } from "lucide-react"
import { api } from "./lib/api"
import { ContextoAuth, useAuth } from "./lib/auth"
import type { Ajustes, CosteTotal, EstadoAuth } from "./lib/tipos"
import { dolares } from "./lib/utils"
import Login from "./vistas/Login"
import Galeria from "./vistas/Galeria"
import Proyecto from "./vistas/Proyecto"
import Estilo from "./vistas/Estilo"
import Configuracion from "./vistas/Configuracion"
import { ConmutadorTema } from "./components/conmutador_tema"
import { Asistente } from "./components/asistente"
import { GuiaInicio } from "./components/guia_inicio"

/** El gasto total del Estudio, siempre a la vista en la cabecera.
 * Se refresca despacio: es un contador, no un cronómetro. */
function CosteCabecera() {
  const [total, setTotal] = useState<CosteTotal | null>(null)

  useEffect(() => {
    let vivo = true
    const pedir = () =>
      api
        .get<CosteTotal>("/api/coste/global")
        .then((t) => vivo && setTotal(t))
        .catch(() => {})
    pedir()
    const id = setInterval(pedir, 15000)
    const al_ver = () => document.visibilityState === "visible" && pedir()
    document.addEventListener("visibilitychange", al_ver)
    return () => {
      vivo = false
      clearInterval(id)
      document.removeEventListener("visibilitychange", al_ver)
    }
  }, [])

  if (!total) return null
  const detalle = Object.entries(total.por_proveedor)
    .filter(([, c]) => c > 0)
    .map(([p, c]) => `${p}: ${dolares(c)}`)
    .join(" · ")
  return (
    <span
      className="hidden items-center gap-1 rounded-md bg-secondary px-2.5 py-1 text-xs text-muted-foreground md:inline-flex"
      title={
        (detalle ? `${detalle} · ` : "") +
        `${total.operaciones} operaciones · se desglosa en Configuración`
      }
    >
      <Wallet className="h-3.5 w-3.5" />
      {dolares(total.coste)}
      <span className="text-[10px]">· {total.operaciones} ops</span>
    </span>
  )
}

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
          <CosteCabecera />
          <Link
            to="/estilo"
            className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            Estilo
          </Link>
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
          <ConmutadorTema />
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
  // la guía de inicio se decide DESPUÉS de entrar: se pinta encima de la
  // pantalla de verdad, no encima de un «cargando…»
  const [guia, setGuia] = useState(false)
  const localizacion = useLocation()

  useEffect(() => {
    if (!estado || estado.instalacion || !estado.autenticado) return
    api
      .get<Ajustes>("/api/ajustes")
      .then((a) => {
        if (a.onboarding_visto === false) setGuia(true)
      })
      .catch(() => {})
  }, [estado])

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

  // el proyecto abierto en pantalla, para la foto del asistente
  const pid_ruta = /^\/p\/([^/]+)/.exec(localizacion.pathname)?.[1] ?? ""

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
              <Route path="/estilo" element={<Estilo />} />
              <Route path="/config" element={<Configuracion />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <Asistente pid={pid_ruta} />
          {guia && <GuiaInicio alCerrar={() => setGuia(false)} />}
        </>
      )}
    </ContextoAuth.Provider>
  )
}
