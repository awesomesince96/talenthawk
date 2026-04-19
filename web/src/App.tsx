import { useCallback, useEffect, useState } from 'react'
import type { Data, Layout } from 'plotly.js'
import {
  addFilter,
  deleteFilter,
  emptyIncludes,
  getBootstrap,
  postCareerRefresh,
  postCareerView,
  postJobsRefresh,
  postJobsView,
  postCareerSelection,
  postTitleIgnore,
  type ChartIncludes,
} from './api'
import { Plot } from './plotlySetup'
import './App.css'

type Bootstrap = Awaited<ReturnType<typeof getBootstrap>>

function Fig({
  fig,
  onSelected,
  onDeselect,
}: {
  fig: Record<string, unknown> | null | undefined
  onSelected?: (e: Readonly<Record<string, unknown>>) => void
  onDeselect?: () => void
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
    />
  )
}

function tokensFromHorizBar(e: Readonly<Record<string, unknown>> | null): string[] {
  if (!e || !Array.isArray((e as { points?: unknown[] }).points)) return []
  const pts = (e as { points: { y?: string; label?: string }[] }).points
  return [...new Set(pts.map((p) => String(p.y ?? p.label ?? '').trim()).filter(Boolean))]
}

function tokensFromVertBar(e: Readonly<Record<string, unknown>> | null): string[] {
  if (!e || !Array.isArray((e as { points?: unknown[] }).points)) return []
  const pts = (e as { points: { x?: string; label?: string }[] }).points
  return [...new Set(pts.map((p) => String(p.x ?? p.label ?? '').trim()).filter(Boolean))]
}

function truncate(s: string, n: number) {
  const t = s.trim()
  if (t.length <= n) return t
  return t.slice(0, n - 1) + '…'
}

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<'career' | 'jobs'>('career')

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
            busy={busy}
            onRefresh={async () => {
              setBusy(true)
              try {
                await postCareerRefresh({ company_ids: careerSel, bypass_cache: careerBypass })
                await reloadBootstrap()
                await loadCareerView()
              } catch (e) {
                setErr(String(e))
              } finally {
                setBusy(false)
              }
            }}
            inc={incCareer}
            setInc={setIncCareer}
            onAddTitle={(t) => addFilter('title', t).then(() => reloadBootstrap()).then(() => loadCareerView())}
            f={f}
          />
        )}
      </main>
    </div>
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

  const hasInc =
    inc.title_tokens.length + inc.summary_tokens.length + inc.summary_buckets.length > 0

  return (
    <>
      <p className="hint">
        Window from feed dates. Use charts to narrow rows (OR within a chart, AND across charts).{' '}
        {!jobsData.has_fetched_jobs && 'Load listings with Refresh jobs in the sidebar.'}
      </p>
      <label className="search">
        Search (id, title, company, category, salary, source)
        <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />
      </label>

      {hasInc && (
        <div className="incpanel">
          <strong>Chart includes</strong>
          <button type="button" className="small" onClick={() => setInc(emptyIncludes())}>
            Clear chart includes
          </button>
          <ul>
            {inc.title_tokens.map((t) => (
              <li key={`t-${t}`}>
                Title: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, title_tokens: p.title_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_tokens.map((t) => (
              <li key={`s-${t}`}>
                Summary: {t}{' '}
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
          </ul>
        </div>
      )}

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

      <h3>Title keyword distribution</h3>
      <p className="hint small">Select bars to filter (Plotly box/lasso). Deselect to clear this chart.</p>
      <Fig
        fig={charts.title_keywords}
        onSelected={(e) => setInc((p) => ({ ...p, title_tokens: tokensFromHorizBar(e as Readonly<Record<string, unknown>>) }))}
        onDeselect={() => setInc((p) => ({ ...p, title_tokens: [] }))}
      />
      <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, title_tokens: [] }))}>
        Clear title chart includes
      </button>

      <details className="exp">
        <summary>Job summary distribution</summary>
        <h4>Summary length</h4>
        <Fig
          fig={charts.summary_length}
          onSelected={(e) => setInc((p) => ({ ...p, summary_buckets: tokensFromVertBar(e as Readonly<Record<string, unknown>>) }))}
          onDeselect={() => setInc((p) => ({ ...p, summary_buckets: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_buckets: [] }))}>
          Clear length includes
        </button>
        <h4>Summary keywords</h4>
        <Fig
          fig={charts.summary_keywords}
          onSelected={(e) => setInc((p) => ({ ...p, summary_tokens: tokensFromHorizBar(e as Readonly<Record<string, unknown>>) }))}
          onDeselect={() => setInc((p) => ({ ...p, summary_tokens: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_tokens: [] }))}>
          Clear summary keyword includes
        </button>
      </details>

      <details className="exp">
        <summary>Category / company / title (top values)</summary>
        <h4>Category</h4>
        <Fig fig={charts.pie_category} />
        <h4>Company</h4>
        <Fig fig={charts.pie_company} />
        <h4>Title</h4>
        <Fig fig={charts.pie_title} />
      </details>
    </>
  )
}

function CareerPanel({
  careerData,
  careerSel,
  busy,
  onRefresh,
  inc,
  setInc,
  onAddTitle,
  f,
}: {
  careerData: Awaited<ReturnType<typeof postCareerView>>
  careerSel: string[]
  busy: boolean
  onRefresh: () => Promise<void>
  inc: ChartIncludes
  setInc: (c: ChartIncludes | ((p: ChartIncludes) => ChartIncludes)) => void
  onAddTitle: (t: string) => Promise<void>
  f: Bootstrap['filters']
}) {
  const charts = careerData.charts
  const display = (careerData.rows_display ?? []) as Record<string, string>[]
  const errs = careerData.errs as string[]
  const notes = careerData.notes as string[]

  const hasInc =
    inc.title_tokens.length + inc.summary_tokens.length + inc.summary_buckets.length > 0

  return (
    <>
      <p className="hint">Roles from configured career APIs. Newest first where dates exist.</p>
      <button type="button" className="primary" disabled={busy || !careerSel.length} onClick={() => onRefresh()}>
        Refresh career listings
      </button>
      {errs?.map((e) => (
        <p key={e} className="warn">
          {e}
        </p>
      ))}
      {notes?.length ? <p className="muted small">{notes.join(' · ')}</p> : null}

      {hasInc && (
        <div className="incpanel">
          <strong>Chart includes</strong>
          <button type="button" className="small" onClick={() => setInc(emptyIncludes())}>
            Clear chart includes
          </button>
          <ul>
            {inc.title_tokens.map((t) => (
              <li key={`t-${t}`}>
                Title: {t}{' '}
                <button type="button" className="linkish" onClick={() => setInc((p) => ({ ...p, title_tokens: p.title_tokens.filter((x) => x !== t) }))}>
                  ×
                </button>
              </li>
            ))}
            {inc.summary_tokens.map((t) => (
              <li key={`s-${t}`}>
                Summary: {t}{' '}
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
          </ul>
        </div>
      )}

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

      <h3>Title keyword distribution</h3>
      <Fig
        fig={charts.title_keywords}
        onSelected={(e) => setInc((p) => ({ ...p, title_tokens: tokensFromHorizBar(e as Readonly<Record<string, unknown>>) }))}
        onDeselect={() => setInc((p) => ({ ...p, title_tokens: [] }))}
      />
      <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, title_tokens: [] }))}>
        Clear title chart includes
      </button>

      <details className="exp">
        <summary>Job summary distribution</summary>
        <h4>Summary length</h4>
        <Fig
          fig={charts.summary_length}
          onSelected={(e) => setInc((p) => ({ ...p, summary_buckets: tokensFromVertBar(e as Readonly<Record<string, unknown>>) }))}
          onDeselect={() => setInc((p) => ({ ...p, summary_buckets: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_buckets: [] }))}>
          Clear length includes
        </button>
        <h4>Summary keywords</h4>
        <Fig
          fig={charts.summary_keywords}
          onSelected={(e) => setInc((p) => ({ ...p, summary_tokens: tokensFromHorizBar(e as Readonly<Record<string, unknown>>) }))}
          onDeselect={() => setInc((p) => ({ ...p, summary_tokens: [] }))}
        />
        <button type="button" className="small" onClick={() => setInc((p) => ({ ...p, summary_tokens: [] }))}>
          Clear summary keyword includes
        </button>
      </details>
    </>
  )
}
