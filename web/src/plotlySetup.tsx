/**
 * plotly.js is UMD; Vite may bundle it without setting `globalThis.Plotly`.
 * Resolve the library from default / namespace imports first, then the global.
 * Never throw at module load — a thrown error here prevents React from mounting (blank page).
 */
import type { ComponentType } from 'react'
import * as factoryModule from 'react-plotly.js/factory.js'
import PlotlyDefault from 'plotly.js'
import * as PlotlyNamespace from 'plotly.js'

function getCreatePlotlyComponent(): ((plotly: unknown) => ComponentType<Record<string, unknown>>) | null {
  const m = factoryModule as unknown as { default?: unknown }
  const fn = typeof m.default === 'function' ? m.default : factoryModule
  if (typeof fn !== 'function') return null
  return fn as (plotly: unknown) => ComponentType<Record<string, unknown>>
}

function plotlyHasApi(x: unknown): x is { newPlot: (...args: unknown[]) => unknown } {
  return typeof x === 'object' && x !== null && typeof (x as { newPlot?: unknown }).newPlot === 'function'
}

function resolvePlotly(): unknown {
  const g = (globalThis as unknown as { Plotly?: unknown }).Plotly
  if (plotlyHasApi(g)) return g

  if (plotlyHasApi(PlotlyDefault)) return PlotlyDefault

  const ns = PlotlyNamespace as unknown as { default?: unknown }
  const fromNs = typeof ns.default === 'object' && ns.default !== null ? ns.default : PlotlyNamespace
  if (plotlyHasApi(fromNs)) return fromNs

  console.error('[TalentHawk] Plotly.js could not be resolved (no newPlot).', {
    globalPlotly: g,
    PlotlyDefault,
    PlotlyNamespace,
  })
  return null
}

function PlotLoadError() {
  return (
    <p className="muted" style={{ padding: '0.5rem 0' }}>
      Chart library failed to load. Check the browser console for Plotly errors.
    </p>
  )
}

const create = getCreatePlotlyComponent()
const lib = resolvePlotly()

export const Plot: ComponentType<Record<string, unknown>> =
  create && lib ? create(lib) : PlotLoadError
