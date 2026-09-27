import * as React from "react"
import * as TabsPrimitivos from "@radix-ui/react-tabs"

import { cn } from "@/lib/utils"

interface PropsPestanas {
  valor?: string
  valorPorDefecto?: string
  alCambiar?: (valor: string) => void
  className?: string
  children: React.ReactNode
}

const Pestanas = ({
  valor,
  valorPorDefecto,
  alCambiar,
  className,
  children,
}: PropsPestanas) => (
  <TabsPrimitivos.Root
    value={valor}
    defaultValue={valorPorDefecto}
    onValueChange={alCambiar}
    className={cn("w-full", className)}
  >
    {children}
  </TabsPrimitivos.Root>
)
Pestanas.displayName = TabsPrimitivos.Root.displayName

const ListaPestanas = React.forwardRef<
  React.ElementRef<typeof TabsPrimitivos.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitivos.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitivos.List
    ref={ref}
    className={cn(
      "inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
      className
    )}
    {...props}
  />
))
ListaPestanas.displayName = TabsPrimitivos.List.displayName

interface PropsDisparadorPestanas
  extends Omit<
    React.ComponentPropsWithoutRef<typeof TabsPrimitivos.Trigger>,
    "value"
  > {
  valor: string
}

const DisparadorPestanas = React.forwardRef<
  React.ElementRef<typeof TabsPrimitivos.Trigger>,
  PropsDisparadorPestanas
>(({ className, valor, ...props }, ref) => (
  <TabsPrimitivos.Trigger
    ref={ref}
    value={valor}
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow",
      className
    )}
    {...props}
  />
))
DisparadorPestanas.displayName = TabsPrimitivos.Trigger.displayName

interface PropsContenidoPestanas
  extends Omit<
    React.ComponentPropsWithoutRef<typeof TabsPrimitivos.Content>,
    "value"
  > {
  valor: string
}

const ContenidoPestanas = React.forwardRef<
  React.ElementRef<typeof TabsPrimitivos.Content>,
  PropsContenidoPestanas
>(({ className, valor, ...props }, ref) => (
  <TabsPrimitivos.Content
    ref={ref}
    value={valor}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      className
    )}
    {...props}
  />
))
ContenidoPestanas.displayName = TabsPrimitivos.Content.displayName

export { Pestanas, ListaPestanas, DisparadorPestanas, ContenidoPestanas }
