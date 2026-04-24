const json = (r: Response) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export async function getBootstrap() {
  return json(await fetch('/api/bootstrap'))
}

export async function postJobsView(body: {
  search_q: string
  days_window: number
  chart_includes: ChartIncludes
}) {
  return json(
    await fetch('/api/jobs/view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function postCareerView(body: { chart_includes: ChartIncludes }) {
  return json(
    await fetch('/api/career/view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function postJobsRefresh(body: {
  mode: string
  serpapi_query: string
  serpapi_location: string
  serpapi_pages: number
  jobs_recency_days: number
  bypass_cache: boolean
}) {
  return json(
    await fetch('/api/jobs/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export type CareerProgressEvent = {
  id?: string
  name?: string
  phase?: string
  jobs?: number
  err?: string
  total_jobs?: number
  errors?: string[]
  notes?: string[]
}

export async function postCareerRefresh(body: {
  company_ids: string[]
  bypass_cache: boolean
  stream?: boolean
}) {
  return json(
    await fetch('/api/career/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function postCareerStop() {
  return json(
    await fetch('/api/career/stop', {
      method: 'POST',
    }),
  )
}

/**
 * Server-Sent Events over POST. Calls onEvent for each `data: {...}` line, then resolves when the stream ends.
 */
export async function postCareerRefreshStream(
  body: { company_ids: string[]; bypass_cache: boolean },
  onEvent: (e: CareerProgressEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/career/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  if (!res.body) throw new Error('No response body')
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      for (const line of block.split('\n')) {
        const m = line.match(/^data:\s*(.+)/)
        if (m) {
          try {
            onEvent(JSON.parse(m[1]) as CareerProgressEvent)
          } catch {
            // ignore bad chunk
          }
        }
      }
    }
  }
  const tail = buf.trim()
  if (tail) {
    for (const line of tail.split('\n')) {
      const m = line.match(/^data:\s*(.+)/)
      if (m) {
        try {
          onEvent(JSON.parse(m[1]) as CareerProgressEvent)
        } catch {
          // ignore
        }
      }
    }
  }
}

export async function postCareerSelection(company_ids: string[]) {
  return json(
    await fetch('/api/session/career-selection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_ids }),
    }),
  )
}

export async function postTitleIgnore(text: string) {
  return json(
    await fetch('/api/filters/title-ignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),
  )
}

export async function deleteFilter(kind: 'title' | 'company' | 'category', entry: string) {
  const enc = encodeURIComponent(entry)
  return json(await fetch(`/api/filters/${kind}/${enc}`, { method: 'DELETE' }))
}

export async function addFilter(kind: 'title' | 'company' | 'category', value: string) {
  return json(
    await fetch(`/api/filters/${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    }),
  )
}

export type ChartIncludes = {
  title_tokens: string[]
  summary_tokens: string[]
  summary_buckets: string[]
  include_categories: string[]
  include_companies: string[]
  include_titles_exact: string[]
}

export const emptyIncludes = (): ChartIncludes => ({
  title_tokens: [],
  summary_tokens: [],
  summary_buckets: [],
  include_categories: [],
  include_companies: [],
  include_titles_exact: [],
})
