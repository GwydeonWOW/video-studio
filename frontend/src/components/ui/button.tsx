import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const variantesBoton = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variante: {
        defecto: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructivo:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        contorno:
          "border border-input bg-card hover:bg-secondary text-foreground",
        secundario: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        fantasma: "hover:bg-secondary hover:text-foreground",
        enlace: "text-primary underline-offset-4 hover:underline",
      },
      tamano: {
        defecto: "h-9 px-4 py-2",
        pequeno: "h-8 rounded-md px-3 text-xs",
        largo: "h-10 rounded-md px-8",
        icono: "h-9 w-9",
      },
    },
    defaultVariants: { variante: "defecto", tamano: "defecto" },
  }
)

export interface PropsBoton
  extends Omit<
      React.ButtonHTMLAttributes<HTMLButtonElement>,
      "type" | "disabled"
    >,
    VariantProps<typeof variantesBoton> {
  comoHijo?: boolean
  /** type del botón HTML (submit / button / reset). */
  tipo?: "submit" | "button" | "reset"
  deshabilitado?: boolean
}

const Boton = React.forwardRef<HTMLButtonElement, PropsBoton>(
  (
    { className, variante, tamano, comoHijo = false, tipo, deshabilitado, ...props },
    ref
  ) => {
    const Comp = comoHijo ? Slot : "button"
    return (
      <Comp
        className={cn(variantesBoton({ variante, tamano, className }))}
        ref={ref}
        type={tipo}
        disabled={deshabilitado}
        {...props}
      />
    )
  }
)
Boton.displayName = "Boton"

export { Boton, variantesBoton }
