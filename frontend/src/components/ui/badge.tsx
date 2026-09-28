import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const variantesInsignia = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variante: {
        defecto: "border-transparent bg-primary text-primary-foreground",
        secundario: "border-transparent bg-secondary text-secondary-foreground",
        destructivo:
          "border-transparent bg-destructive text-destructive-foreground",
        exito: "border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
        aviso: "border-transparent bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
        contorno: "text-foreground",
      },
    },
    defaultVariants: { variante: "defecto" },
  }
)

export interface PropsInsignia
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof variantesInsignia> {}

function Insignia({ className, variante, ...props }: PropsInsignia) {
  return (
    <div className={cn(variantesInsignia({ variante }), className)} {...props} />
  )
}

export { Insignia, variantesInsignia }
