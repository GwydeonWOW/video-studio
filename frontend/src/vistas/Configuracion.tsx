/** Configuración del servicio: claves, modelos por rol, voces, tarifas y coste. */
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Check, Copy, KeyRound, Loader2, Mic2, Save } from "lucide-react"
import { api } from "../lib/api"
import { dolares } from "../lib/utils"
import type {
  CatalogoProveedores,
  ClaveEstado,
  CosteTotal,
  Voz,
} from "../lib/tipos"
import { Boton } from "../components/ui/button"
import { Insignia } from "../components/ui/badge"
import { Entrada } from "../components/ui/input"
import { Etiqueta } from "../components/ui/etiqueta"
import { Tarjeta, ContenidoTarjeta } from "../components/ui/tarjeta"
import {
  Selector,
  DisparadorSelector,
  ContenidoSelector,
  Opcion,
  ValorSelector,
} from "../components/ui/selector"
import {
  Pestanas,
  ListaPestanas,
  DisparadorPestanas,
  ContenidoPestanas,
} from "../components/ui/pestanas"

const ROLES: { id: string; etiqueta: string; ayuda: string }[] = [
  {
    id: "guion",
    etiqueta: "Guion",
    ayuda: "Escribe el brief y las escenas del guion.",
  },
  {
    id: "correccion",
    etiqueta: "Corrección",
    ayuda: "Reescribe escenas concretas cuando lo pides.",
  },
  {
    id: "titulos",
    etiqueta: "Títulos",
    ayuda: "Título del vídeo y textos en pantalla.",
  },
  {
    id: "descripcion",
    etiqueta: "Descripciones visuales",
    ayuda: "Prompts de imagen para los planos.",
  },
]

export default function Configuracion() {
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Configuración</h1>
      <Pestanas valorPorDefecto="claves">
        <ListaPestanas className="flex w-full flex-wrap">
          <DisparadorPestanas valor="claves">Claves</DisparadorPestanas>
          <DisparadorPestanas valor="modelos">Modelos por rol</DisparadorPestanas>
          <DisparadorPestanas valor="voces">Voces</DisparadorPestanas>
          <DisparadorPestanas valor="tarifas">Tarifas</DisparadorPestanas>
          <DisparadorPestanas valor="coste">Coste</DisparadorPestanas>
        </ListaPestanas>

        <ContenidoPestanas valor="claves" className="mt-4">
          <PestanaClaves />
        </ContenidoPestanas>
        <ContenidoPestanas valor="modelos" className="mt-4">
          <PestanaModelos />
        </ContenidoPestanas>
        <ContenidoPestanas valor="voces" className="mt-4">
          <PestanaVoces />
        </ContenidoPestanas>
        <ContenidoPestanas valor="tarifas" className="mt-4">
          <PestanaTarifas />
        </ContenidoPestanas>
        <ContenidoPestanas valor="coste" className="mt-4">
          <PestanaCoste />
        </ContenidoPestanas>
      </Pestanas>
    </div>
  )
}

/* ---------------------------------------------------------------- claves */

interface PruebaClave {
  ok: boolean
  detalle: string
}

function PestanaClaves() {
  const [lista, setLista] = useState<ClaveEstado[] | null>(null)
  const [valores, setValores] = useState<Record<string, string>>({})
  const [guardando, setGuardando] = useState(false)
  const [probando, setProbando] = useState(false)
  const [pruebas, setPruebas] = useState<Record<string, PruebaClave> | null>(
    null
  )

  useEffect(() => {
    api
      .get<ClaveEstado[]>("/api/claves")
      .then(setLista)
      .catch(() => setLista([]))
  }, [])

  const guardar = async () => {
    const cuerpo: Record<string, string> = {}
    for (const [clave, valor] of Object.entries(valores))
      if (valor.trim()) cuerpo[clave] = valor.trim()
    if (Object.keys(cuerpo).length === 0) {
      toast.info("nada que guardar")
      return
    }
    setGuardando(true)
    try {
      setLista(await api.put<ClaveEstado[]>("/api/claves", cuerpo))
      setValores({})
      toast.success("claves guardadas en el servidor")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  const probar = async () => {
    setProbando(true)
    try {
      setPruebas(
        await api.post<Record<string, PruebaClave>>("/api/claves/probar")
      )
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setProbando(false)
    }
  }

  if (!lista)
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  const hay_nuevas = Object.values(valores).some((v) => v.trim() !== "")

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Las claves se guardan en el servidor y nunca vuelven al navegador;
        vacío no borra nada.
      </p>
      {lista.map((c) => {
        const prueba = pruebas?.[c.clave]
        return (
          <div key={c.clave} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Etiqueta>{c.etiqueta}</Etiqueta>
              {c.presente ? (
                <Insignia variante="exito">{c.mascara}</Insignia>
              ) : (
                <Insignia variante="secundario">sin clave</Insignia>
              )}
              {prueba &&
                (prueba.ok ? (
                  <Insignia variante="exito">ok · {prueba.detalle}</Insignia>
                ) : (
                  <Insignia variante="destructivo">
                    fallo · {prueba.detalle}
                  </Insignia>
                ))}
            </div>
            <Entrada
              tipo="password"
              autoComplete="new-password"
              valor={valores[c.clave] ?? ""}
              alCambiar={(e) =>
                setValores((prev) => ({ ...prev, [c.clave]: e.target.value }))
              }
              placeholder={`variable ${c.variable}`}
            />
            <p className="text-xs text-muted-foreground">{c.uso}</p>
          </div>
        )
      })}
      <div className="flex flex-wrap gap-2">
        <Boton onClick={guardar} deshabilitado={guardando || !hay_nuevas}>
          {guardando ? <Loader2 className="animate-spin" /> : <Save />}
          Guardar claves
        </Boton>
        <Boton
          variante="contorno"
          onClick={probar}
          deshabilitado={probando}
          title="Cada prueba es una llamada gratuita al servicio"
        >
          {probando ? <Loader2 className="animate-spin" /> : <KeyRound />}
          Probar claves
        </Boton>
      </div>
    </div>
  )
}

/* --------------------------------------------------------- modelos por rol */

function PestanaModelos() {
  const [cat, setCat] = useState<CatalogoProveedores | null>(null)
  const [seleccion, setSeleccion] = useState<
    Record<string, { proveedor: string; modelo: string }>
  >({})
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    ;(async () => {
      try {
        const c = await api.get<CatalogoProveedores>("/api/proveedores")
        setCat(c)
        const ajustes = await api.get<{ llm?: Record<string, { proveedor: string; modelo: string }> }>(
          "/api/ajustes"
        )
        const inicial: Record<string, { proveedor: string; modelo: string }> = {}
        for (const rol of ROLES) {
          const guardado = ajustes.llm?.[rol.id]
          inicial[rol.id] = guardado ?? c.roles_defecto[rol.id]
        }
        setSeleccion(inicial)
      } catch {
        toast.error("no se pudo cargar el catálogo de proveedores")
      }
    })()
  }, [])

  const cambiar_proveedor = (rol: string, proveedor: string) => {
    if (!cat) return
    const conf = cat.proveedores[proveedor]
    setSeleccion((prev) => ({
      ...prev,
      [rol]: { proveedor, modelo: conf?.defecto ?? "" },
    }))
  }

  const guardar = async () => {
    setGuardando(true)
    try {
      await api.put("/api/ajustes/llm", { llm: seleccion })
      toast.success("modelos por rol guardados")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  if (!cat)
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  const ids_proveedores = Object.keys(cat.proveedores)

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Cada tarea del pipeline puede usar un modelo distinto; el proveedor
        decide también qué clave se usa.
      </p>
      {ROLES.map((rol) => {
        const conf = seleccion[rol.id] ?? { proveedor: "", modelo: "" }
        const modelos = cat.proveedores[conf.proveedor]?.modelos ?? []
        return (
          <div
            key={rol.id}
            className="grid gap-3 rounded-md border p-3 sm:grid-cols-2"
          >
            <div className="space-y-1 sm:col-span-2">
              <p className="text-sm font-medium">{rol.etiqueta}</p>
              <p className="text-xs text-muted-foreground">{rol.ayuda}</p>
            </div>
            <div className="space-y-2">
              <Etiqueta>Proveedor</Etiqueta>
              <Selector
                valor={conf.proveedor}
                alCambiar={(v) => cambiar_proveedor(rol.id, v)}
              >
                <DisparadorSelector>
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  {ids_proveedores.map((id) => (
                    <Opcion key={id} valor={id}>
                      {cat.proveedores[id].nombre}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
            <div className="space-y-2">
              <Etiqueta>Modelo</Etiqueta>
              <Selector
                valor={conf.modelo}
                alCambiar={(v) =>
                  setSeleccion((prev) => ({
                    ...prev,
                    [rol.id]: { proveedor: conf.proveedor, modelo: v },
                  }))
                }
              >
                <DisparadorSelector>
                  <ValorSelector />
                </DisparadorSelector>
                <ContenidoSelector>
                  {modelos.map((m) => (
                    <Opcion key={m} valor={m}>
                      {m}
                    </Opcion>
                  ))}
                </ContenidoSelector>
              </Selector>
            </div>
          </div>
        )
      })}
      <Boton onClick={guardar} deshabilitado={guardando}>
        {guardando ? <Loader2 className="animate-spin" /> : <Save />}
        Guardar modelos
      </Boton>
    </div>
  )
}

/* ------------------------------------------------------------------ voces */

function PestanaVoces() {
  const [voces, setVoces] = useState<Voz[] | null>(null)
  const [probando, setProbando] = useState(false)
  const [prueba, setPrueba] = useState<{ ok: boolean; detalle: string } | null>(
    null
  )
  const [copiada, setCopiada] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Voz[]>("/api/voces")
      .then(setVoces)
      .catch(() => setVoces([]))
  }, [])

  const probar = useCallback(async () => {
    setProbando(true)
    try {
      setPrueba(await api.post<{ ok: boolean; detalle: string }>("/api/voces/probar"))
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setProbando(false)
    }
  }, [])

  const copiar = async (voice_id: string) => {
    try {
      await navigator.clipboard.writeText(voice_id)
      setCopiada(voice_id)
      setTimeout(() => setCopiada(null), 1500)
    } catch {
      toast.error("no se pudo copiar")
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Boton variante="contorno" onClick={probar} deshabilitado={probando}>
          {probando ? <Loader2 className="animate-spin" /> : <Mic2 />}
          Probar clave de ElevenLabs
        </Boton>
        {prueba &&
          (prueba.ok ? (
            <Insignia variante="exito">{prueba.detalle}</Insignia>
          ) : (
            <Insignia variante="destructivo">{prueba.detalle}</Insignia>
          ))}
      </div>
      {!voces ? (
        <div className="flex justify-center py-16 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : voces.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Sin voces: guarda la clave de ElevenLabs en la pestaña Claves y
          vuelve a entrar.
        </p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {voces.map((v) => (
            <div
              key={v.voice_id}
              className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{v.nombre}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {v.voice_id}
                </p>
              </div>
              <Boton
                variante="fantasma"
                tamano="icono"
                title="Copiar voice_id para los parámetros del paso Voz"
                onClick={() => copiar(v.voice_id)}
              >
                {copiada === v.voice_id ? <Check /> : <Copy />}
              </Boton>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* --------------------------------------------------------------- tarifas */

function PestanaTarifas() {
  const [tarifas, setTarifas] = useState<Record<string, number> | null>(null)
  const [valores, setValores] = useState<Record<string, string>>({})
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    api
      .get<Record<string, number>>("/api/coste/tarifas")
      .then((t) => {
        setTarifas(t)
        const iniciales: Record<string, string> = {}
        for (const [clave, precio] of Object.entries(t))
          iniciales[clave] = String(precio)
        setValores(iniciales)
      })
      .catch(() => setTarifas({}))
  }, [])

  const guardar = async () => {
    const cuerpo: Record<string, number> = {}
    for (const [clave, bruto] of Object.entries(valores)) {
      if (!bruto.trim()) continue
      const numero = Number(bruto.replace(",", "."))
      if (!Number.isNaN(numero)) cuerpo[clave] = numero
    }
    setGuardando(true)
    try {
      const r = await api.put<Record<string, number>>(
        "/api/coste/tarifas",
        cuerpo
      )
      setTarifas(r)
      toast.success("tarifas guardadas")
    } catch (e) {
      toast.error(String((e as Error).message ?? e))
    } finally {
      setGuardando(false)
    }
  }

  if (!tarifas)
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Precio por unidad (dólares); lo que guardas aquí manda sobre los
        defectos del servidor.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(tarifas).map(([clave, precio]) => (
          <div key={clave} className="space-y-2">
            <Etiqueta className="font-mono text-xs">{clave}</Etiqueta>
            <Entrada
              tipo="number"
              paso="any"
              min="0"
              valor={valores[clave] ?? String(precio)}
              alCambiar={(e) =>
                setValores((prev) => ({ ...prev, [clave]: e.target.value }))
              }
            />
          </div>
        ))}
      </div>
      <Boton onClick={guardar} deshabilitado={guardando}>
        {guardando ? <Loader2 className="animate-spin" /> : <Save />}
        Guardar tarifas
      </Boton>
    </div>
  )
}

/* ------------------------------------------------------------------ coste */

function PestanaCoste() {
  const [total, setTotal] = useState<CosteTotal | null>(null)

  useEffect(() => {
    api
      .get<CosteTotal>("/api/coste/global")
      .then(setTotal)
      .catch(() => setTotal(null))
  }, [])

  if (!total)
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )

  const por_operacion = Object.entries(total.por_operacion ?? {}).sort(
    (a, b) => b[1] - a[1]
  )
  const por_proveedor = Object.entries(total.por_proveedor ?? {}).sort(
    (a, b) => b[1] - a[1]
  )

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Tarjeta>
          <ContenidoTarjeta className="p-4">
            <p className="text-xs text-muted-foreground">Operaciones</p>
            <p className="text-2xl font-semibold">{total.operaciones}</p>
          </ContenidoTarjeta>
        </Tarjeta>
        <Tarjeta>
          <ContenidoTarjeta className="p-4">
            <p className="text-xs text-muted-foreground">Gastado</p>
            <p className="text-2xl font-semibold">{dolares(total.coste)}</p>
          </ContenidoTarjeta>
        </Tarjeta>
      </div>
      {por_operacion.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Por operación</p>
          <div className="space-y-1">
            {por_operacion.map(([op, coste]) => (
              <div
                key={op}
                className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-sm"
              >
                <span className="font-mono text-xs">{op}</span>
                <span className="text-muted-foreground">{dolares(coste)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {por_proveedor.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Por proveedor</p>
          <div className="space-y-1">
            {por_proveedor.map(([prov, coste]) => (
              <div
                key={prov}
                className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-sm"
              >
                <span>{prov}</span>
                <span className="text-muted-foreground">{dolares(coste)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
