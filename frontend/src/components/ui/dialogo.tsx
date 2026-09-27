import * as React from "react"
import * as DiálogoPrimitivo from "@radix-ui/react-dialog"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

interface PropsDialogo {
  abierto?: boolean
  alCambiar?: (abierto: boolean) => void
  children: React.ReactNode
}

const Dialogo = ({ abierto, alCambiar, children }: PropsDialogo) => (
  <DiálogoPrimitivo.Root open={abierto} onOpenChange={alCambiar}>
    {children}
  </DiálogoPrimitivo.Root>
)
const CierreDialogo = DiálogoPrimitivo.Close
const DisparadorDialogo = DiálogoPrimitivo.Trigger

const ContenidoDialogo = React.forwardRef<
  React.ElementRef<typeof DiálogoPrimitivo.Content>,
  React.ComponentPropsWithoutRef<typeof DiálogoPrimitivo.Content>
>(({ className, children, ...props }, ref) => (
  <DiálogoPrimitivo.Portal>
    <DiálogoPrimitivo.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
    <DiálogoPrimitivo.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border bg-card p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DiálogoPrimitivo.Close className="absolute right-4 top-4 rounded-sm opacity-70 transition-opacity hover:opacity-100 focus:outline-none disabled:pointer-events-none">
        <X className="h-4 w-4" />
        <span className="sr-only">Cerrar</span>
      </DiálogoPrimitivo.Close>
    </DiálogoPrimitivo.Content>
  </DiálogoPrimitivo.Portal>
))
ContenidoDialogo.displayName = DiálogoPrimitivo.Content.displayName

const CabeceraDialogo = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
CabeceraDialogo.displayName = "CabeceraDialogo"

const TituloDialogo = React.forwardRef<
  React.ElementRef<typeof DiálogoPrimitivo.Title>,
  React.ComponentPropsWithoutRef<typeof DiálogoPrimitivo.Title>
>(({ className, ...props }, ref) => (
  <DiálogoPrimitivo.Title
    ref={ref}
    className={cn(
      "text-lg font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
))
TituloDialogo.displayName = DiálogoPrimitivo.Title.displayName

const DescripcionDialogo = React.forwardRef<
  React.ElementRef<typeof DiálogoPrimitivo.Description>,
  React.ComponentPropsWithoutRef<typeof DiálogoPrimitivo.Description>
>(({ className, ...props }, ref) => (
  <DiálogoPrimitivo.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
DescripcionDialogo.displayName = DiálogoPrimitivo.Description.displayName

const PieDialogo = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className
    )}
    {...props}
  />
)
PieDialogo.displayName = "PieDialogo"

export {
  Dialogo,
  DisparadorDialogo,
  CierreDialogo,
  ContenidoDialogo,
  CabeceraDialogo,
  TituloDialogo,
  DescripcionDialogo,
  PieDialogo,
}
