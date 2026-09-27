import * as React from "react"
import * as SelectorPrimitivo from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "lucide-react"

import { cn } from "@/lib/utils"

interface PropsSelector {
  valor?: string
  valorPorDefecto?: string
  alCambiar?: (valor: string) => void
  deshabilitado?: boolean
  children: React.ReactNode
}

const Selector = ({
  valor,
  valorPorDefecto,
  alCambiar,
  deshabilitado,
  children,
}: PropsSelector) => (
  <SelectorPrimitivo.Root
    value={valor}
    defaultValue={valorPorDefecto}
    onValueChange={alCambiar}
    disabled={deshabilitado}
  >
    {children}
  </SelectorPrimitivo.Root>
)
const GrupoSelector = SelectorPrimitivo.Group
const ValorSelector = SelectorPrimitivo.Value

const DisparadorSelector = React.forwardRef<
  React.ElementRef<typeof SelectorPrimitivo.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectorPrimitivo.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectorPrimitivo.Trigger
    ref={ref}
    className={cn(
      "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
      className
    )}
    {...props}
  >
    {children}
    <SelectorPrimitivo.Icon asChild>
      <ChevronDown className="h-4 w-4 opacity-50" />
    </SelectorPrimitivo.Icon>
  </SelectorPrimitivo.Trigger>
))
DisparadorSelector.displayName = SelectorPrimitivo.Trigger.displayName

interface PropsContenidoSelector
  extends Omit<
    React.ComponentPropsWithoutRef<typeof SelectorPrimitivo.Content>,
    "position"
  > {
  posicion?: "item-aligned" | "popper"
}

const ContenidoSelector = React.forwardRef<
  React.ElementRef<typeof SelectorPrimitivo.Content>,
  PropsContenidoSelector
>(({ className, children, posicion = "popper", ...props }, ref) => (
  <SelectorPrimitivo.Portal>
    <SelectorPrimitivo.Content
      ref={ref}
      className={cn(
        "relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-md border bg-card text-card-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        posicion === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className
      )}
      position={posicion}
      {...props}
    >
      <SelectorPrimitivo.ScrollUpButton className="flex cursor-default items-center justify-center py-1">
        <ChevronUp className="h-4 w-4" />
      </SelectorPrimitivo.ScrollUpButton>
      <SelectorPrimitivo.Viewport
        className={cn(
          "p-1",
          posicion === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectorPrimitivo.Viewport>
      <SelectorPrimitivo.ScrollDownButton className="flex cursor-default items-center justify-center py-1">
        <ChevronDown className="h-4 w-4" />
      </SelectorPrimitivo.ScrollDownButton>
    </SelectorPrimitivo.Content>
  </SelectorPrimitivo.Portal>
))
ContenidoSelector.displayName = SelectorPrimitivo.Content.displayName

const EtiquetaSelector = React.forwardRef<
  React.ElementRef<typeof SelectorPrimitivo.Label>,
  React.ComponentPropsWithoutRef<typeof SelectorPrimitivo.Label>
>(({ className, ...props }, ref) => (
  <SelectorPrimitivo.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-sm font-semibold", className)}
    {...props}
  />
))
EtiquetaSelector.displayName = SelectorPrimitivo.Label.displayName

interface PropsOpcion
  extends Omit<
    React.ComponentPropsWithoutRef<typeof SelectorPrimitivo.Item>,
    "value"
  > {
  valor: string
}

const Opcion = React.forwardRef<
  React.ElementRef<typeof SelectorPrimitivo.Item>,
  PropsOpcion
>(({ className, children, valor, ...props }, ref) => (
  <SelectorPrimitivo.Item
    ref={ref}
    value={valor}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-secondary data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectorPrimitivo.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectorPrimitivo.ItemIndicator>
    </span>
    <SelectorPrimitivo.ItemText>{children}</SelectorPrimitivo.ItemText>
  </SelectorPrimitivo.Item>
))
Opcion.displayName = SelectorPrimitivo.Item.displayName

const SeparadorSelector = React.forwardRef<
  React.ElementRef<typeof SelectorPrimitivo.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectorPrimitivo.Separator>
>(({ className, ...props }, ref) => (
  <SelectorPrimitivo.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-border", className)}
    {...props}
  />
))
SeparadorSelector.displayName = SelectorPrimitivo.Separator.displayName

export {
  Selector,
  GrupoSelector,
  ValorSelector,
  DisparadorSelector,
  ContenidoSelector,
  EtiquetaSelector,
  Opcion,
  SeparadorSelector,
}
