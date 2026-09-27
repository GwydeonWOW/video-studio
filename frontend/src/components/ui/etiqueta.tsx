import * as React from "react"
import * as EtiquetaPrimitiva from "@radix-ui/react-label"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const variantesEtiqueta = cva(
  "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
)

const Etiqueta = React.forwardRef<
  React.ElementRef<typeof EtiquetaPrimitiva.Root>,
  React.ComponentPropsWithoutRef<typeof EtiquetaPrimitiva.Root> &
    VariantProps<typeof variantesEtiqueta>
>(({ className, ...props }, ref) => (
  <EtiquetaPrimitiva.Root
    ref={ref}
    className={cn(variantesEtiqueta(), className)}
    {...props}
  />
))
Etiqueta.displayName = EtiquetaPrimitiva.Root.displayName

export { Etiqueta }
