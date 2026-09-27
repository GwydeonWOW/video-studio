import * as React from "react"
import * as ProgresoPrimitivo from "@radix-ui/react-progress"

import { cn } from "@/lib/utils"

interface PropsProgreso
  extends React.ComponentPropsWithoutRef<typeof ProgresoPrimitivo.Root> {
  valor?: number | null
  indicador?: string
}

const Progreso = React.forwardRef<
  React.ElementRef<typeof ProgresoPrimitivo.Root>,
  PropsProgreso
>(({ className, valor, indicador, ...props }, ref) => (
  <ProgresoPrimitivo.Root
    ref={ref}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-secondary",
      className
    )}
    {...props}
  >
    <ProgresoPrimitivo.Indicator
      className="h-full w-full flex-1 bg-primary transition-all"
      style={{
        width: indicador ?? `${Math.min(100, Math.max(0, valor ?? 0))}%`,
      }}
    />
  </ProgresoPrimitivo.Root>
))
Progreso.displayName = ProgresoPrimitivo.Root.displayName

export { Progreso }
