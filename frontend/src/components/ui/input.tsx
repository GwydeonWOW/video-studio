import * as React from "react"

import { cn } from "@/lib/utils"

interface PropsEntrada
  extends Omit<
      React.InputHTMLAttributes<HTMLInputElement>,
      "type" | "value" | "onChange" | "disabled" | "step"
    > {
  tipo?: string
  valor?: string | number
  alCambiar?: React.ChangeEventHandler<HTMLInputElement>
  deshabilitado?: boolean
  paso?: string | number
}

const Entrada = React.forwardRef<HTMLInputElement, PropsEntrada>(
  ({ className, tipo, valor, alCambiar, deshabilitado, paso, ...props }, ref) => {
    return (
      <input
        type={tipo}
        value={valor}
        onChange={alCambiar}
        disabled={deshabilitado}
        step={paso}
        className={cn(
          "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Entrada.displayName = "Entrada"

export { Entrada }
