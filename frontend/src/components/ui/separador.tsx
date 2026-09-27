import * as React from "react"
import * as SeparadorPrimitivo from "@radix-ui/react-separator"

import { cn } from "@/lib/utils"

interface PropsSeparador
  extends Omit<
      React.ComponentPropsWithoutRef<typeof SeparadorPrimitivo.Root>,
      "orientation" | "decorative"
    > {
  orientacion?: "horizontal" | "vertical"
  decorativo?: boolean
}

const Separador = React.forwardRef<
  React.ElementRef<typeof SeparadorPrimitivo.Root>,
  PropsSeparador
>(
  (
    { className, orientacion = "horizontal", decorativo = true, ...props },
    ref
  ) => (
    <SeparadorPrimitivo.Root
      ref={ref}
      decorative={decorativo}
      orientation={orientacion}
      className={cn(
        "shrink-0 bg-border",
        orientacion === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
        className
      )}
      {...props}
    />
  )
)
Separador.displayName = SeparadorPrimitivo.Root.displayName

export { Separador }
