/** Conmutador claro/oscuro: la elección se guarda en localStorage y
 *  el tema inicial lo fija el script de index.html (sin destello). */
import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"
import { Boton } from "./ui/button"

export function ConmutadorTema() {
  const [oscuro, setOscuro] = useState(() =>
    document.documentElement.classList.contains("dark")
  )

  useEffect(() => {
    document.documentElement.classList.toggle("dark", oscuro)
    localStorage.setItem("tema", oscuro ? "oscuro" : "claro")
  }, [oscuro])

  return (
    <Boton
      variante="fantasma"
      tamano="icono"
      title={oscuro ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
      onClick={() => setOscuro((v) => !v)}
    >
      {oscuro ? <Sun /> : <Moon />}
    </Boton>
  )
}
