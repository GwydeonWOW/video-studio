import { useState } from "react"
import { toast } from "sonner"
import { Loader2, Video } from "lucide-react"
import { api, ErrorApi } from "../lib/api"
import { useAuth } from "../lib/auth"
import { Boton } from "../components/ui/button"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import {
  Tarjeta,
  CabeceraTarjeta,
  TituloTarjeta,
  DescripcionTarjeta,
  ContenidoTarjeta,
} from "../components/ui/tarjeta"

export default function Login() {
  const { estado, recargar } = useAuth()
  const instalacion = estado?.instalacion ?? false
  const [contrasena, setContrasena] = useState("")
  const [confirmacion, setConfirmacion] = useState("")
  const [enviando, setEnviando] = useState(false)

  const entrar = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (instalacion && contrasena !== confirmacion) {
      toast.error("las contraseñas no coinciden")
      return
    }
    setEnviando(true)
    try {
      await api.post<{ ok: boolean }>(
        instalacion ? "/api/auth/instalar" : "/api/auth/login",
        { contrasena }
      )
      recargar()
    } catch (e) {
      toast.error(e instanceof ErrorApi ? e.message : "no se pudo entrar")
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Tarjeta className="w-full max-w-sm">
        <CabeceraTarjeta className="items-center text-center">
          <Video className="mx-auto h-10 w-10 text-primary" />
          <TituloTarjeta className="mt-2 text-xl">Estudio de Vídeo</TituloTarjeta>
          <DescripcionTarjeta>
            {instalacion
              ? "Primer arranque: define la contraseña del estudio."
              : "Introduce la contraseña del estudio."}
          </DescripcionTarjeta>
        </CabeceraTarjeta>
        <ContenidoTarjeta>
          <form onSubmit={entrar} className="space-y-4">
            <div className="space-y-2">
              <Etiqueta htmlFor="contrasena">Contraseña</Etiqueta>
              <Entrada
                id="contrasena"
                tipo="password"
                autoFocus
                required
                valor={contrasena}
                alCambiar={(e) => setContrasena(e.target.value)}
              />
            </div>
            {instalacion && (
              <div className="space-y-2">
                <Etiqueta htmlFor="confirmacion">Repite la contraseña</Etiqueta>
                <Entrada
                  id="confirmacion"
                  tipo="password"
                  required
                  valor={confirmacion}
                  alCambiar={(e) => setConfirmacion(e.target.value)}
                />
              </div>
            )}
            <Boton tipo="submit" className="w-full" deshabilitado={enviando}>
              {enviando && <Loader2 className="animate-spin" />}
              {instalacion ? "Instalar y entrar" : "Entrar"}
            </Boton>
          </form>
        </ContenidoTarjeta>
      </Tarjeta>
    </div>
  )
}
