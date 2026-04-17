/**
 * Plotly is loaded from `/plotly.min.js` (see index.html), copied by `npm run copy-plotly`.
 * The UMD bundle may attach either an object or a **function** with `newPlot` on it — both are valid.
 * The react-plotly factory import may be nested as `module.default` (CJS interop).
 */
import { useLayoutEffect, useState, type ComponentType } from 'react'
import * as factoryModule from 'react-plotly.js/factory.js'

type PlotlyLike = { newPlot: (...args: unknown[]) => unknown }

function pickCallable(...xs: unknown[]): ((plotly: unknown) => ComponentType<Record<string, unknown>>) | null {
  for (const x of xs) {
    if (typeof x === 'function') return x as (plotly: unknown) => ComponentType<Record<string, unknown>>
    if (x && typeof x === 'object' && 'default' in x) {
      const d = (x as { default: unknown }).default
      if (typeof d === 'function') return d as (plotly: unknown) => ComponentType<Record<string, unknown>>
      if (d && typeof d === 'object' && 'default' in d) {
        const d2 = (d as { default: unknown }).default
        if (typeof d2 === 'function') return d2 as (plotly: unknown) => ComponentType<Record<string, unknown>>
      }
    }
  }
  return null
}

function getCreatePlotlyComponent(): ((plotly: unknown) => ComponentType<Record<string, unknown>>) | null {
  const m = factoryModule as unknown as Record<string, unknown>
  return pickCallable(m.default, m, factoryModule)
}

/** Plotly public API: `newPlot` may live on an object or a function (both are typeof that allows property access). */
function getNewPlot(x: unknown): unknown {
  if (x == null) return undefined
  if (typeof x === 'object' || typeof x === 'function') {
    return (x as { newPlot?: unknown }).newPlot
  }
  return undefined
}

function plotlyHasApi(x: unknown): x is PlotlyLike {
  return typeof getNewPlot(x) === 'function'
}

function unwrapPlotly(x: unknown): unknown {
  if (plotlyHasApi(x)) return x
  if (x && typeof x === 'object' && 'default' in x) {
    const d = (x as { default: unknown }).default
    if (plotlyHasApi(d)) return d
  }
  return null
}

function resolvePlotlyFromWindow(): unknown {
  const w = window as unknown as { Plotly?: unknown }
  return unwrapPlotly(w.Plotly)
}

function PlotLoadError() {
  return (
    <p className="muted" style={{ padding: '0.5rem 0' }}>
      Charts could not load Plotly. From the <code>web</code> folder run{' '}
      <code>npm run copy-plotly && npm run build</code>, restart the server, then hard-refresh.
    </p>
  )
}

/**
 * Drop-in replacement for react-plotly’s Plot; wires up after `window.Plotly` exists.
 */
export function Plot(props: Record<string, unknown>) {
  const [Inner, setInner] = useState<ComponentType<Record<string, unknown>> | null>(null)

  useLayoutEffect(() => {
    const create = getCreatePlotlyComponent()
    const lib = resolvePlotlyFromWindow()
    if (plotlyHasApi(lib) && create) {
      setInner(() => create(lib))
      return
    }
    console.error('[TalentHawk] Plotly or react-plotly factory failed.', {
      Plotly: (window as unknown as { Plotly?: unknown }).Plotly,
      plotlyType: typeof (window as unknown as { Plotly?: unknown }).Plotly,
      newPlotType: typeof getNewPlot((window as unknown as { Plotly?: unknown }).Plotly),
      hasFactory: Boolean(create),
    })
    setInner(() => PlotLoadError)
  }, [])

  if (!Inner) {
    return <div className="muted" style={{ minHeight: 320 }} aria-busy="true" />
  }

  return <Inner {...props} />
}
