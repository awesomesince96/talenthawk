import { useCallback, useEffect, useRef, useState } from 'react'
import type { Data, Layout } from 'plotly.js'
import {
  addFilter,
  deleteFilter,
  emptyIncludes,
  getBootstrap,
  postCareerStop,
  postCareerRefreshStream,
  postCareerView,
  postJobsRefresh,
  postJobsView,
  postCareerSelection,
  postTitleIgnore,
  type CareerProgressEvent,
  type ChartIncludes,
} from './api'
import { Plot } from './plotlySetup'
import './App.css'

type Bootstrap = Awaited<ReturnType<typeof getBootstrap>>

function statusFromCareerEvent(e: CareerProgressEvent): string {
  switch (e.phase) {
    case 'start':
      return 'sent'
    case 'work':
      return 'fetching'
    case 'cache':
      return `received · ${e.jobs ?? 0} (cache)`
    case 'done':
      return `received · ${e.jobs ?? 0}`
    case 'error':
      return `error · ${(e.err || '').slice(0, 200)}`
    case 'skip':
      return 'skipped (no network)'
    case 'stopped':
      return 'stopped'
    default:
      return '—'
  }
}

function Fig({
  fig,
  onSelected,
  onDeselect,
  onClick,
}: {
  fig: Record<string, unknown> | null | undefined
  onSelected?: (e: Readonly<Record<string, unknown>>) => void
  onDeselect?: () => void
  onClick?: (e: Readonly<Record<string, unknown>>) => void
}) {
  if (!fig || !Array.isArray(fig.data)) {
    return <p className="muted">Nothing to chart.</p>
  }
  const layout = {
    ...(fig.layout as object),
    autosize: true,
  }
  return (
    <Plot
      data={fig.data as Data[]}
      layout={layout as Partial<Layout>}
      style={{ width: '100%', minHeight: 320 }}
      useResizeHandler
      config={{ displayModeBar: true, responsive: true }}
      onSelected={onSelected as (e: Readonly<Record<string, unknown>>) => void}
      onDeselect={onDeselect}
      onClick={onClick as (e: Readonly<Record<string, unknown>>) => void}
    />
  )
}

function tokensFromHorizBar(e: Readonly<Record<string, unknown>> | null): string[] {
  if (!e || !Array.isArray((e as { points?: unknown[] }).points)) return []
  const pts = (e as { points: { y?: string; label?: string }[] }).points
  return [...new Set(pts.map((p) => String(p.y ?? p.label ?? '').trim()).filter(Boolean))]
}

function mergeIncludes(existing: string[], incoming: string[]): string[] {
  if (!incoming.length) return existing
  return [...new Set([...existing, ...incoming])]
}

type KeywordRow = { word: string; count: number }

function KeywordCountTable({
  rows,
  label,
  onAddInclude,
}: {
  rows: KeywordRow[]
  label: string
  onAddInclude?: (word: string) => void
}) {
  if (!rows.length) {
    return <p className="muted small">No tokens in the current row set.</p>
  }
  return (
    <div className="kw-all">
      <table>
        <caption>
          {label} <span className="muted">({rows.length} distinct)</span>
        </caption>
        <thead>
          <tr>
            <th scope="col">Word</th>
            <th scope="col">Rows</th>
            {onAddInclude ? <th scope="col">Include</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.word}>
              <td>{r.word}</td>
              <td className="num">{r.count}</td>
              {onAddInclude ? (
                <td className="kw-inc">
                  <button type="button" className="mini" title="Add to chart includes" onClick={() => onAddInclude(r.word)}>
                    +
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Category / company / title bars: filter key is customdata[2] (full value; empty = “Other” aggregate, not selectable). */
function matchKeysFromFacetBar(e: Readonly<Record<string, unknown>> | null): string[] {
  if (!e || !Array.isArray((e as { points?: unknown[] }).points)) return []
  const pts = (e as { points: { customdata?: unknown }[] }).points
  const keys: string[] = []
  for (const p of pts) {
    const cd = p.customdata
    if (Array.isArray(cd) && cd.length > 2 && cd[2] != null && String(cd[2]).trim().length > 0) {
      keys.push(String(cd[2]).trim())
    }
  }
  return [...new Set(keys)]
}

function truncate(s: string, n: number) {
  const t = s.trim()
  if (t.length <= n) return t
  return t.slice(0, n - 1) + '…'
}

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<'career' | 'jobs' | 'visualize'>('career')
  const [vizSource, setVizSource] = useState<'jobs' | 'career'>('career')

  const [titleIgnoreText, setTitleIgnoreText] = useState('')

  const [jobsMode, setJobsMode] = useState('remotive')
  const [serpQuery, setSerpQuery] = useState('')
  const [serpLoc, setSerpLoc] = useState('')
  const [serpPages, setSerpPages] = useState(3)
  const [jobsRecency, setJobsRecency] = useState(30)
  const [jobsBypass, setJobsBypass] = useState(false)
  const [careerBypass, setCareerBypass] = useState(false)

  const [searchQ, setSearchQ] = useState('')
  const [careerSel, setCareerSel] = useState<string[]>([])

  const [incJobs, setIncJobs] = useState<ChartIncludes>(() => emptyIncludes())
  const [incCareer, setIncCareer] = useState<ChartIncludes>(() => emptyIncludes())

  const [jobsData, setJobsData] = useState<Awaited<ReturnType<typeof postJobsView>> | null>(null)
  const [careerData, setCareerData] = useState<Awaited<ReturnType<typeof postCareerView>> | null>(null)

  const [busy, setBusy] = useState(false)
  const [careerProgress, setCareerProgress] = useState<{
    rows: { id: string; name: string; status: string }[]
    summary?: string
  } | null>(null)
  const [careerProgressOpen, setCareerProgressOpen] = useState(false)
  const careerRefreshAbortRef = useRef<AbortController | null>(null)

  const reloadBootstrap = useCallback(async () => {
    const b = await getBootstrap()
    setBoot(b)
    setTitleIgnoreText(b.filters.title_ignore_words.join(', '))
    if (b.state.jobs_fetch_mode) setJobsMode(b.state.jobs_fetch_mode)
    setSerpQuery(b.state.serpapi_query ?? '')
    setSerpLoc(b.state.serpapi_location ?? '')
    setSerpPages(b.state.serpapi_pages ?? 3)
    setJobsRecency(b.state.jobs_recency_days ?? 30)
    setCareerSel(b.state.career_tracker_selection ?? [])
    return b
  }, [])

  useEffect(() => {
    reloadBootstrap().catch((e: Error) => setErr(String(e.message)))
  }, [reloadBootstrap])

  const loadJobsView = useCallback(async () => {
    const j = await postJobsView({
      search_q: searchQ,
      days_window: jobsRecency,
      chart_includes: incJobs,
    })
    setJobsData(j)
  }, [searchQ, jobsRecency, incJobs])

  const loadCareerView = useCallback(async () => {
    const c = await postCareerView({ chart_includes: incCareer })
    setCareerData(c)
  }, [incCareer])

  useEffect(() => {
    if (!boot) return
    if (view !== 'jobs') return
    loadJobsView().catch((e: Error) => setErr(String(e.message)))
  }, [boot, view, loadJobsView])

  useEffect(() => {
    if (!boot) return
    if (view !== 'career') return
    loadCareerView().catch((e: Error) => setErr(String(e.message)))
  }, [boot, view, loadCareerView])

  useEffect(() => {
    if (!boot) return
    if (view !== 'visualize') return
    if (!jobsData) loadJobsView().catch(() => {})
    if (!careerData) loadCareerView().catch(() => {})
  }, [boot, view, jobsData, careerData, loadJobsView, loadCareerView])

  if (!boot) {
    return (
      <div className="shell">
        <p>Loading…</p>
        {err && <p className="error">{err}</p>}
      </div>
    )
  }

  const f = boot.filters
  const st = boot.state

  return (
    <div className="shell">
      {err && (
        <p className="error banner">
          {err}{' '}
          <button type="button" onClick={() => setErr(null)}>
            Dismiss
          </button>
        </p>
      )}
      <aside className="sidebar">
        <h1>TalentHawk</h1>
        <section className="block">
          <h2>Filters</h2>
          <p className="hint">
            Substring rules (case-insensitive). Title ignore hides titles containing any phrase.
          </p>
          <details>
            <summary>Title ignore words ({f.title_ignore_words.length})</summary>
            <textarea
              rows={4}
              value={titleIgnoreText}
              onChange={(e) => setTitleIgnoreText(e.target.value)}
              placeholder="e.g. manager, sales"
            />
            <button
              type="button"
              className="small"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  await postTitleIgnore(titleIgnoreText)
                  await reloadBootstrap()
                  if (view === 'jobs') await loadJobsView()
                  else await loadCareerView()
                } catch (e) {
                  setErr(String(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              Save
            </button>
          </details>
          <details>
            <summary>Title exclude ({f.title.length})</summary>
            <ul className="rules">
              {f.title.map((t: string) => (
                <li key={t}>
                  <span>{truncate(t, 42)}</span>
                  <button
                    type="button"
                    className="linkish"
                    onClick={async () => {
                      await deleteFilter('title', t)
                      await reloadBootstrap()
                      if (view === 'jobs') await loadJobsView()
                      else await loadCareerView()
                    }}
                  >
                    ✕
                  </button>
                </li>
              ))}
              {!f.title.length && <li className="muted">No rules</li>}
            </ul>
          </details>
          <details>
            <summary>Company exclude ({f.company.length})</summary>
            <ul className="rules">
              {f.company.map((t: string) => (
                <li key={t}>
                  <span>{truncate(t, 42)}</span>
                  <button
                    type="button"
                    className="linkish"
                    onClick={async () => {
                      await deleteFilter('company', t)
                      await reloadBootstrap()
                      if (view === 'jobs') await loadJobsView()
                      else await loadCareerView()
                    }}
                  >
                    ✕
                  </button>
                </li>
              ))}
              {!f.company.length && <li className="muted">No rules</li>}
            </ul>
          </details>
          <details>
            <summary>Category exclude ({f.category.length})</summary>
            <ul className="rules">
              {f.category.map((t: string) => (
                <li key={t}>
                  <span>{truncate(t, 36)}</span>
                  <button
                    type="button"
                    className="linkish"
                    onClick={async () => {
                      await deleteFilter('category', t)
                      await reloadBootstrap()
                      if (view === 'jobs') await loadJobsView()
                      else await loadCareerView()
                    }}
                  >
                    ✕
                  </button>
                </li>
              ))}
              {!f.category.length && <li className="muted">No rules</li>}
            </ul>
          </details>
        </section>

        <section className="block">
          <h2>View</h2>
          <label className="row">
            <input
              type="radio"
              name="view"
              checked={view === 'career'}
              onChange={() => setView('career')}
            />
            Career page tracker
          </label>
          <label className="row">
            <input type="radio" name="view" checked={view === 'jobs'} onChange={() => setView('jobs')} />
            Jobs API
          </label>
          <label className="row">
            <input type="radio" name="view" checked={view === 'visualize'} onChange={() => setView('visualize')} />
            Visualize
          </label>
        </section>

        {view === 'jobs' && (
          <section className="block">
            <h2>Jobs</h2>
            <p className="hint">Uses feed cache when fresh ({boot.cache_ttl_hours}h) unless fetch live.</p>
            <label>
              Source
              <select value={jobsMode} onChange={(e) => setJobsMode(e.target.value)}>
                <option value="remotive">Remotive (free)</option>
                <option value="serpapi">SerpAPI — Google Jobs</option>
                <option value="both">Remotive + SerpAPI</option>
              </select>
            </label>
            <label>
              Posted within
              <select value={jobsRecency} onChange={(e) => setJobsRecency(Number(e.target.value))}>
                {boot.recency_day_choices.map((d: number) => (
                  <option key={d} value={d}>
                    {d === 1 ? 'Last 1 day' : `Last ${d} days`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              SerpAPI query
              <input value={serpQuery} onChange={(e) => setSerpQuery(e.target.value)} />
            </label>
            <label>
              SerpAPI location (optional)
              <input value={serpLoc} onChange={(e) => setSerpLoc(e.target.value)} placeholder="United States" />
            </label>
            <label>
              SerpAPI pages (1–5)
              <input
                type="number"
                min={1}
                max={5}
                value={serpPages}
                onChange={(e) => setSerpPages(Number(e.target.value))}
              />
            </label>
            {(jobsMode === 'serpapi' || jobsMode === 'both') && !boot.serpapi_key_configured && (
              <p className="warn">Set SERPAPI_API_KEY in the environment or .env</p>
            )}
            <label className="row">
              <input type="checkbox" checked={jobsBypass} onChange={(e) => setJobsBypass(e.target.checked)} />
              Fetch live (bypass cache)
            </label>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  await postJobsRefresh({
                    mode: jobsMode,
                    serpapi_query: serpQuery,
                    serpapi_location: serpLoc,
                    serpapi_pages: serpPages,
                    jobs_recency_days: jobsRecency,
                    bypass_cache: jobsBypass,
                  })
                  await reloadBootstrap()
                  await loadJobsView()
                } catch (e) {
                  setErr(String(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              Refresh jobs
            </button>
            <p className="muted small">
              Source: {st.jobs_source ?? 'not loaded'}
              {st.jobs_error ? ` · Error: ${st.jobs_error}` : ''}
            </p>
          </section>
        )}

        {view === 'career' && (
          <section className="block">
            <h2>Career tracker</h2>
            <label>
              Companies
              <select
                multiple
                size={8}
                value={careerSel}
                onChange={async (e) => {
                  const opts = [...e.target.selectedOptions].map((o) => o.value)
                  setCareerSel(opts)
                  await postCareerSelection(opts)
                  await reloadBootstrap()
                }}
                className="multi"
              >
                {boot.career_companies.map((c: { id: string; label: string }) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="hint small">Hold Cmd/Ctrl to select multiple.</p>
            <label className="row">
              <input type="checkbox" checked={careerBypass} onChange={(e) => setCareerBypass(e.target.checked)} />
              Fetch live (bypass cache)
            </label>
          </section>
        )}
      </aside>

      <main className="main">
        {view === 'jobs' && jobsData && (
          <JobsPanel
            jobsData={jobsData}
            searchQ={searchQ}
            setSearchQ={setSearchQ}
            inc={incJobs}
            setInc={setIncJobs}
            onAddTitle={(t) => addFilter('title', t).then(() => reloadBootstrap()).then(() => loadJobsView())}
            onAddCompany={(t) => addFilter('company', t).then(() => reloadBootstrap()).then(() => loadJobsView())}
            onAddCategory={(t) => addFilter('category', t).then(() => reloadBootstrap()).then(() => loadJobsView())}
            f={f}
          />
        )}

        {view === 'career' && careerData && (
          <CareerPanel
            careerData={careerData}
            careerSel={careerSel}
            careerProgress={careerProgress}
            careerProgressOpen={careerProgressOpen}
            setCareerProgressOpen={setCareerProgressOpen}
            busy={busy}
            onRefresh={async () => {
              setBusy(true)
              setErr(null)
              setCareerProgressOpen(true)
              const ctl = new AbortController()
              careerRefreshAbortRef.current = ctl
              setCareerProgress({
                rows: careerSel.map((id) => ({
                  id,
                  name: boot.career_companies.find((c: { id: string; label: string }) => c.id === id)?.label || id,
                  status: '·',
                })),
              })
              try {
                await postCareerRefreshStream(
                  { company_ids: careerSel, bypass_cache: careerBypass },
                  (e) => {
                    if (e.phase === 'prefill') {
                      loadCareerView().catch(() => {})
                      return
                    }
                    if (e.phase === 'stopped') {
                      setCareerProgress((p) => (p ? { ...p, summary: 'Stopped by user' } : null))
                      setCareerProgressOpen(false)
                      return
                    }
                    if (e.phase === 'complete') {
                      setCareerProgress((p) =>
                        p
                          ? {
                              ...p,
                              summary: `All done · ${e.total_jobs ?? 0} jobs in table`,
                            }
                          : null,
                      )
                      setCareerProgressOpen(false)
                      return
                    }
                    if (!e.id) return
                    const st = statusFromCareerEvent(e)
                    setCareerProgress((p) => {
                      if (!p) return p
                      return {
                        ...p,
                        rows: p.rows.map((r) =>
                          r.id === e.id ? { ...r, name: e.name?.trim() || r.name, status: st } : r,
                        ),
                      }
                    })
                    if (e.phase === 'cache' || e.phase === 'done' || e.phase === 'error') {
                      loadCareerView().catch(() => {})
                    }
                  },
                  ctl.signal,
                )
                await reloadBootstrap()
                await loadCareerView()
              } catch (e) {
                if (e instanceof Error && e.name === 'AbortError') {
                  setCareerProgress((p) => (p ? { ...p, summary: 'Stopped by user' } : p))
                } else {
                  setErr(String(e))
                  setCareerProgress(null)
                }
                setCareerProgressOpen(false)
              } finally {
                setBusy(false)
                careerRefreshAbortRef.current = null
              }
            }}
            onStop={async () => {
              try {
                await postCareerStop()
              } finally {
                careerRefreshAbortRef.current?.abort()
              }
            }}
            inc={incCareer}
            setInc={setIncCareer}
            onAddTitle={(t) => addFilter('title', t).then(() => reloadBootstrap()).then(() => loadCareerView())}
            f={f}
          />
        )}

        {view === 'visualize' && (
          <VisualizePanel
            source={vizSource}
            setSource={setVizSource}
            jobsData={jobsData}
            careerData={careerData}
            incJobs={incJobs}
            setIncJobs={setIncJobs}
            incCareer={incCareer}
            setIncCareer={setIncCareer}
          />
        )}
      </main>
    </div>
  )
}

function VisualizePanel({
  source,
  setSource,
  jobsData,
  careerData,
  incJobs,
  setIncJobs,
  incCareer,
  setIncCareer,
}: {
  source: 'jobs' | 'career'
  setSource: (v: 'jobs' | 'career') => void
  jobsData: Awaited<ReturnType<typeof postJobsView>> | null
  careerData: Awaited<ReturnType<typeof postCareerView>> | null
  incJobs: ChartIncludes
  setIncJobs: (c: ChartIncludes | ((p: ChartIncludes) => ChartIncludes)) => void
  incCareer: ChartIncludes
  setIncCareer: (c: ChartIncludes | ((p: ChartIncludes) => ChartIncludes)) => void
}) {
  const data = source === 'jobs' ? jobsData : careerData
  if (!data) {
    return <p className="info">Loading data for visualization…</p>
  }
  const kw = (data as { keyword_lists?: { title: KeywordRow[]; summary: KeywordRow[] } }).keyword_lists ?? {
    title: [] as KeywordRow[],
    summary: [] as KeywordRow[],
  }
  const byWord = new Map<string, number>()
  for (const r of kw.title) byWord.set(r.word, (byWord.get(r.word) ?? 0) + r.count)
  for (const r of kw.summary) byWord.set(r.word, (byWord.get(r.word) ?? 0) + r.count)
  const words = [...byWord.entries()]
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 140)
  const maxC = words[0]?.count ?? 1
  const minC = words[words.length - 1]?.count ?? 1

  const includes = source === 'jobs' ? incJobs : incCareer
  const setIncludes = source === 'jobs' ? setIncJobs : setIncCareer
  const onToggle = (w: string) => {
    const inTitle = includes.title_tokens.includes(w)
    const inSummary = includes.summary_tokens.includes(w)
    setIncludes((p) => ({
      ...p,
      title_tokens: inTitle ? p.title_tokens.filter((x) => x !== w) : [...new Set([...p.title_tokens, w])],
      summary_tokens: inSummary ? p.summary_tokens.filter((x) => x !== w) : [...new Set([...p.summary_tokens, w])],
    }))
  }

  return (
    <>
      <div className="viz-toolbar">
        <h2>Visualize</h2>
        <label className="row">
          Source
          <select value={source} onChange={(e) => setSource(e.target.value as 'jobs' | 'career')}>
            <option value="career">Career tracker</option>
            <option value="jobs">Jobs API</option>
          </select>
        </label>
      </div>
      <p className="hint">
        Word cloud from <strong>title + description</strong> keywords. Click a word to toggle it in existing includes (title and summary tokens).
      </p>
      <div className="wordcloud">
        {words.map((w) => {
          const ratio = maxC === minC ? 1 : (w.count - minC) / (maxC - minC)
          const size = 12 + Math.round(ratio * 42)
          const active = includes.title_tokens.includes(w.word) || includes.summary_tokens.includes(w.word)
          return (
            <button
              key={w.word}
              type="button"
              className={`wc-word${active ? ' on' : ''}`}
              style={{ fontSize: `${size}px` }}
              title={`${w.word} · ${w.count} rows`}
              onClick={() => onToggle(w.word)}
            >
              {w.word}
            </button>
          )
        })}
      </div>
    </>
  )
}

function JobsPanel({
  jobsData,
  searchQ,
  setSearchQ,
  inc,
  setInc,
  onAddTitle,
  onAddCompany,
  onAddCategory,
  f,
}: {
  jobsData: Awaited<ReturnType<typeof postJobsView>>
  searchQ: string
  setSearchQ: (s: string) => void
  inc: ChartIncludes
  setInc: (c: ChartIncludes | ((p: ChartIncludes) => ChartIncludes)) => void
  onAddTitle: (t: string) => Promise<void>
  onAddCompany: (t: string) => Promise<void>
  onAddCategory: (t: string) => Promise<void>
  f: Bootstrap['filters']
}) {
  const m = jobsData.metrics
  const charts = jobsData.charts
  const rows = jobsData.jobs_visible as Record<string, string>[]
  const kwLists = (jobsData as { keyword_lists?: { title: KeywordRow[]; summary: KeywordRow[] } }).keyword_lists ?? {
    title: [] as KeywordRow[],
    summary: [] as KeywordRow[],
  }

  const hasInc =
    inc.title_tokens.length +
      inc.summary_tokens.length +
      inc.summary_buckets.length +
      inc.include_categories.length +
      inc.include_companies.length +
      inc.include_titles_exact.length >
    0

  return (
    <>
      <p className="hint">
        Window from feed dates. Results are listed first; expand Title keywords and Job summary for charts and full word lists. Title and summary keyword includes use AND matching.{' '}
        {!jobsData.has_fetched_jobs && 'Load listings with Refresh jobs in the sidebar.'}
      </p>
      <label className="search">
        Search (id, title, company, category, salary, source)
        <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />
      </label>

      <div className="incpanel">
        <strong>Chart includes</strong>
        <button type="button" className="small" disabled={!hasInc} onClick={() => setInc(emptyIncludes())}>
          Clear all chart includes
        </button>
        {!hasInc ? (
          <p className="hint small" style={{ margin: '0.35rem 0 0' }}>
            None — expand Title keywords / Job summary below and select bars to filter.
          </p>
        ) : (
          <ul>
            {inc.title_tokens.map((t) => (
              <li key={`t-${t}`}>
                Title word: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, title_tokens: p.title_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_tokens.map((t) => (
              <li key={`s-${t}`}>
                Summary word: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, summary_tokens: p.summary_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_buckets.map((t) => (
              <li key={`b-${t}`}>
                Length: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, summary_buckets: p.summary_buckets.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_categories.map((t) => (
              <li key={`cat-${t}`}>
                Category: {truncate(t, 56)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_categories: p.include_categories.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_companies.map((t) => (
              <li key={`co-${t}`}>
                Company: {truncate(t, 40)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_companies: p.include_companies.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_titles_exact.map((t) => (
              <li key={`tit-${t}`}>
                Title (exact): {truncate(t, 56)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_titles_exact: p.include_titles_exact.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <h3>Results</h3>
      <div className="metrics">
        <div>
          <span className="n">{m.fetched}</span>
          <span className="l">Fetched</span>
        </div>
        <div>
          <span className="n">{m.windowed}</span>
          <span className="l">In window</span>
        </div>
        <div>
          <span className="n">{m.shown}</span>
          <span className="l">Shown</span>
        </div>
        <div>
          <span className="n">{m.hidden_title_rules}</span>
          <span className="l">Hidden (title)</span>
        </div>
        <div>
          <span className="n">{m.hidden_title_words}</span>
          <span className="l">Hidden (words)</span>
        </div>
        <div>
          <span className="n">{m.hidden_company}</span>
          <span className="l">Hidden (co)</span>
        </div>
        <div>
          <span className="n">{m.hidden_category}</span>
          <span className="l">Hidden (cat)</span>
        </div>
      </div>

      {!jobsData.has_fetched_jobs ? (
        <p className="info">Use Refresh jobs in the sidebar.</p>
      ) : rows.length === 0 ? (
        <p className="info">No rows match your search or chart includes.</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th />
                <th>Company</th>
                <th />
                <th>Cat</th>
                <th />
                <th>Salary</th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const title = String(row.title ?? '')
                const company = String(row.company ?? '')
                const cat = String(row.category ?? '')
                const titleBlocked =
                  !title ||
                  f.title.some((x: string) => title.toLowerCase().includes(x.toLowerCase())) ||
                  f.title_ignore_words.some((x: string) => title.toLowerCase().includes(x.toLowerCase()))
                const coBlocked = !company || f.company.some((x: string) => company.toLowerCase().includes(x.toLowerCase()))
                const catBlocked = !cat || f.category.some((x: string) => cat.toLowerCase().includes(x.toLowerCase()))
                return (
                  <tr key={`${row.job_id}-${i}`}>
                    <td className="mono">{row.job_id || '—'}</td>
                    <td>{truncate(title, 72)}</td>
                    <td>
                      <button type="button" className="mini" disabled={titleBlocked} onClick={() => onAddTitle(title)} title="Exclude this title">
                        −
                      </button>
                    </td>
                    <td>{truncate(company, 36) || '—'}</td>
                    <td>
                      <button type="button" className="mini" disabled={coBlocked} onClick={() => onAddCompany(company)} title="Exclude this company">
                        −
                      </button>
                    </td>
                    <td>{truncate(cat, 22) || '—'}</td>
                    <td>
                      <button type="button" className="mini" disabled={catBlocked} onClick={() => onAddCategory(cat)} title="Exclude this category">
                        −
                      </button>
                    </td>
                    <td>{truncate(String(row.salary ?? ''), 48) || '—'}</td>
                    <td>
                      {row.url ? (
                        <a href={String(row.url)} target="_blank" rel="noreferrer">
                          Open
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <details className="exp" open>
        <summary>Title keywords — distribution &amp; full list</summary>
        <h4 className="chart-h">Top title keywords (chart)</h4>
        <p className="hint small">Click a bar or drag to box-select. A row must contain all selected title keywords. Deselect clears this chart’s filter.</p>
        <Fig
          fig={charts.title_keywords}
          onClick={(e) => {
            const t = tokensFromHorizBar(e as Readonly<Record<string, unknown>>)
            if (t.length) setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, t) }))
          }}
          onSelected={(e) => {
            const t = tokensFromHorizBar(e as Readonly<Record<string, unknown>>)
            if (!t.length) return
            setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, t) }))
          }}
          onDeselect={() => setInc((p) => ({ ...p, title_tokens: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, title_tokens: [] }))}>
          Clear title keyword includes
        </button>
        <h4 className="chart-h">All title keywords</h4>
        <p className="hint small">Every distinct token in job titles for rows in Results (stopwords removed).</p>
        <KeywordCountTable
          rows={kwLists.title}
          label="Title tokens"
          onAddInclude={(w) => setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, [w]) }))}
        />
      </details>

      <details className="exp" open>
        <summary>Job summary — keywords</summary>
        <p className="hint small">Use + to add tokens to chart includes. Clear removes all summary-word includes.</p>
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_tokens: [] }))}>
          Clear summary keyword includes
        </button>
        <h4 className="chart-h">All summary / description keywords</h4>
        <p className="hint small">Distinct tokens in posting body text for rows in Results (stopwords removed).</p>
        <KeywordCountTable
          rows={kwLists.summary}
          label="Body tokens"
          onAddInclude={(w) => setInc((p) => ({ ...p, summary_tokens: mergeIncludes(p.summary_tokens, [w]) }))}
        />
      </details>

      <details className="exp">
        <summary>Category / company / title (top values)</summary>
        <p className="hint small">Click or box-select a bar. “Other” is not a filter (aggregate only).</p>
        <h4>Category</h4>
        <Fig
          fig={charts.pie_category}
          onClick={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (keys.length) setInc((p) => ({ ...p, include_categories: mergeIncludes(p.include_categories, keys) }))
          }}
          onSelected={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (!keys.length) return
            setInc((p) => ({ ...p, include_categories: mergeIncludes(p.include_categories, keys) }))
          }}
          onDeselect={() => setInc((p) => ({ ...p, include_categories: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, include_categories: [] }))}>
          Clear category includes
        </button>
        <h4>Company</h4>
        <Fig
          fig={charts.pie_company}
          onClick={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (keys.length) setInc((p) => ({ ...p, include_companies: mergeIncludes(p.include_companies, keys) }))
          }}
          onSelected={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (!keys.length) return
            setInc((p) => ({ ...p, include_companies: mergeIncludes(p.include_companies, keys) }))
          }}
          onDeselect={() => setInc((p) => ({ ...p, include_companies: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, include_companies: [] }))}>
          Clear company includes
        </button>
        <h4>Title</h4>
        <Fig
          fig={charts.pie_title}
          onClick={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (keys.length) setInc((p) => ({ ...p, include_titles_exact: mergeIncludes(p.include_titles_exact, keys) }))
          }}
          onSelected={(e) => {
            const keys = matchKeysFromFacetBar(e as Readonly<Record<string, unknown>>)
            if (!keys.length) return
            setInc((p) => ({ ...p, include_titles_exact: mergeIncludes(p.include_titles_exact, keys) }))
          }}
          onDeselect={() => setInc((p) => ({ ...p, include_titles_exact: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, include_titles_exact: [] }))}>
          Clear title (exact) includes
        </button>
      </details>
    </>
  )
}

function CareerPanel({
  careerData,
  careerSel,
  careerProgress,
  careerProgressOpen,
  setCareerProgressOpen,
  busy,
  onRefresh,
  onStop,
  inc,
  setInc,
  onAddTitle,
  f,
}: {
  careerData: Awaited<ReturnType<typeof postCareerView>>
  careerSel: string[]
  careerProgress: { rows: { id: string; name: string; status: string }[]; summary?: string } | null
  careerProgressOpen: boolean
  setCareerProgressOpen: (v: boolean) => void
  busy: boolean
  onRefresh: () => Promise<void>
  onStop: () => Promise<void>
  inc: ChartIncludes
  setInc: (c: ChartIncludes | ((p: ChartIncludes) => ChartIncludes)) => void
  onAddTitle: (t: string) => Promise<void>
  f: Bootstrap['filters']
}) {
  const charts = careerData.charts
  const display = (careerData.rows_display ?? []) as Record<string, string>[]
  const errs = careerData.errs as string[]
  const notes = careerData.notes as string[]
  const kwLists = (careerData as { keyword_lists?: { title: KeywordRow[]; summary: KeywordRow[] } }).keyword_lists ?? {
    title: [] as KeywordRow[],
    summary: [] as KeywordRow[],
  }

  const hasInc =
    inc.title_tokens.length +
      inc.summary_tokens.length +
      inc.summary_buckets.length +
      inc.include_categories.length +
      inc.include_companies.length +
      inc.include_titles_exact.length >
    0

  return (
    <>
      <p className="hint">
        Roles from configured career APIs. Newest first where dates exist. Results are listed first; expand Title keywords and Job summary for charts and full word lists. Click or box-select to add includes.
      </p>
      <button type="button" className="primary" disabled={busy || !careerSel.length} onClick={() => onRefresh()}>
        Refresh career listings
      </button>
      {busy ? (
        <button type="button" className="small" onClick={() => onStop()} style={{ marginLeft: '0.5rem' }}>
          Stop
        </button>
      ) : null}
      {careerProgress?.rows.length ? (
        <details
          className="career-progress"
          open={careerProgressOpen}
          onToggle={(e) => setCareerProgressOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>Status by company</summary>
          <div aria-live="polite">
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {careerProgress.rows.map((r) => (
                  <tr key={r.id}>
                    <td className="career-prog-name">{truncate(r.name, 28)}</td>
                    <td className="career-prog-st">{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {careerProgress.summary ? <p className="muted small career-prog-foot">{careerProgress.summary}</p> : null}
          </div>
        </details>
      ) : null}
      {errs?.map((e) => (
        <p key={e} className="warn">
          {e}
        </p>
      ))}
      {notes?.length ? <p className="muted small">{notes.join(' · ')}</p> : null}

      <div className="incpanel">
        <strong>Chart includes</strong>
        <button type="button" className="small" disabled={!hasInc} onClick={() => setInc(emptyIncludes())}>
          Clear all chart includes
        </button>
        {!hasInc ? (
          <p className="hint small" style={{ margin: '0.35rem 0 0' }}>
            None — expand Title keywords / Job summary below and select bars to filter.
          </p>
        ) : (
          <ul>
            {inc.title_tokens.map((t) => (
              <li key={`t-${t}`}>
                Title word: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, title_tokens: p.title_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_tokens.map((t) => (
              <li key={`s-${t}`}>
                Summary word: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, summary_tokens: p.summary_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_buckets.map((t) => (
              <li key={`b-${t}`}>
                Length: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, summary_buckets: p.summary_buckets.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_categories.map((t) => (
              <li key={`cat-${t}`}>
                Category: {truncate(t, 56)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_categories: p.include_categories.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_companies.map((t) => (
              <li key={`co-${t}`}>
                Company: {truncate(t, 40)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_companies: p.include_companies.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.include_titles_exact.map((t) => (
              <li key={`tit-${t}`}>
                Title (exact): {truncate(t, 56)}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, include_titles_exact: p.include_titles_exact.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <h3>Results</h3>

      {!careerSel.length ? (
        <p className="info">Select companies in the sidebar.</p>
      ) : display.length === 0 ? (
        <p className="info">No rows (filters or chart includes may hide everything).</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th />
                <th>Company</th>
                <th>ID</th>
                <th>Location</th>
                <th>Salary</th>
                <th>Created</th>
                <th>Updated</th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody>
              {display.map((row, i) => {
                const title = String(row.title ?? '')
                const titleBlocked =
                  !title.trim() ||
                  f.title.some((x: string) => title.toLowerCase().includes(x.toLowerCase())) ||
                  f.title_ignore_words.some((x: string) => title.toLowerCase().includes(x.toLowerCase()))
                return (
                  <tr key={`${row.job_id}-${i}`}>
                    <td>{row.title_truncated}</td>
                    <td>
                      <button type="button" className="mini" disabled={titleBlocked} title="Add title exclude" onClick={() => onAddTitle(title)}>
                        ⧉
                      </button>
                    </td>
                    <td>{row.company_truncated}</td>
                    <td className="mono">{row.job_id || '—'}</td>
                    <td>{row.location_truncated}</td>
                    <td>{row.compensation_truncated || '—'}</td>
                    <td>{row.published_at || '—'}</td>
                    <td>{row.updated_at || '—'}</td>
                    <td>
                      {row.url ? (
                        <a href={row.url} target="_blank" rel="noreferrer">
                          Open
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <details className="exp" open>
        <summary>Title keywords — distribution &amp; full list</summary>
        <h4 className="chart-h">Top title keywords (chart)</h4>
        <p className="hint small">Click a bar or drag to box-select. A row must contain all selected title keywords.</p>
        <Fig
          fig={charts.title_keywords}
          onClick={(e) => {
            const t = tokensFromHorizBar(e as Readonly<Record<string, unknown>>)
            if (t.length) setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, t) }))
          }}
          onSelected={(e) => {
            const t = tokensFromHorizBar(e as Readonly<Record<string, unknown>>)
            if (!t.length) return
            setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, t) }))
          }}
          onDeselect={() => setInc((p) => ({ ...p, title_tokens: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, title_tokens: [] }))}>
          Clear title keyword includes
        </button>
        <h4 className="chart-h">All title keywords</h4>
        <p className="hint small">Every distinct token in job titles for rows in Results (stopwords removed).</p>
        <KeywordCountTable
          rows={kwLists.title}
          label="Title tokens"
          onAddInclude={(w) => setInc((p) => ({ ...p, title_tokens: mergeIncludes(p.title_tokens, [w]) }))}
        />
      </details>

      <details className="exp" open>
        <summary>Job summary — keywords</summary>
        <p className="hint small">Use + to add tokens to chart includes. Clear removes all summary-word includes.</p>
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_tokens: [] }))}>
          Clear summary keyword includes
        </button>
        <h4 className="chart-h">All summary / description keywords</h4>
        <p className="hint small">Distinct tokens in posting body text for rows in Results (stopwords removed).</p>
        <KeywordCountTable
          rows={kwLists.summary}
          label="Body tokens"
          onAddInclude={(w) => setInc((p) => ({ ...p, summary_tokens: mergeIncludes(p.summary_tokens, [w]) }))}
        />
      </details>
    </>
  )
}
