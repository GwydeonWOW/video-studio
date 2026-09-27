import * as React from "react"

import { cn } from "@/lib/utils"

interface PropsAreaTexto
  extends Omit<
      React.TextareaHTMLAttributes<HTMLTextAreaElement>,
      "value" | "onChange" | "disabled" | "rows"
    > {
  valor?: string
  alCambiar?: React.ChangeEventHandler<HTMLTextAreaElement>
  deshabilitado?: boolean
  filas?: number
}

const AreaTexto = React.forwardRef<HTMLTextAreaElement, PropsAreaTexto>(
  ({ className, valor, alCambiar, deshabilitado, filas, ...props }, ref) => {
    return (
      <textarea
        value={valor}
        onChange={alCambiar}
        disabled={deshabilitado}
        rows={filas}
        className={cn(
          "flex min-h-[60px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
AreaTexto.displayName = "AreaTexto"

export { AreaTexto }
