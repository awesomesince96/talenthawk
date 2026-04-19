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

export async function postCareerRefresh(body: { company_ids: string[]; bypass_cache: boolean }) {
  return json(
    await fetch('/api/career/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
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
