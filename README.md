<div align="center">

# TalentHawk

**Local remote job browser** — pull recent listings, infer a simple category from each title, and exclude rows with **title**, **company**, and **category** filters you control.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![React](https://img.shields.io/badge/UI-React-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![uv](https://img.shields.io/badge/package%20manager-uv-DE5FE9?style=flat)](https://docs.astral.sh/uv/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/awesomesince96/talenthawk/blob/main/LICENSE)

</div>

---

## What it does

- **Job sources** (sidebar): **Remotive** (free, open API) and/or **SerpAPI [Google Jobs](https://serpapi.com/google-jobs-api)** (paid key; richer volume). **Merged** mode dedupes by title + company + URL. Listings load when you click **Refresh jobs** (no automatic fetch on startup).
- **Posted within** sidebar control: **1, 3, 7, 14, or 30 days** (default 30) when a post date is present; SerpAPI rows with only relative text (“5 days ago”) are normalized when possible, otherwise kept so they are not dropped silently.
- Assigns a **category** per job from **built-in title keywords** in code (`talenthawk/categorize.py`); first match wins, else **Other**.
- **Three filters** (JSON under `data/persistence/`): **title**, **company**, **category** — substring rules, case-insensitive. Use **−** on a row to add a rule; **✕** in the **Filters** panel to remove.
- **Career page tracker**: choose tracked companies in the sidebar; **`data/mappings/career_page_mappings.json`** maps each company to a careers list URL and fetcher.
  - Refresh is **cache-first**: cached rows render first, then companies update progressively as live results arrive.
  - Per-company status is shown during refresh (`sent`, `fetching`, `received`, `error`) and can be stopped with **Stop**.
  - On SerpAPI **429** rate limits, tracker falls back to cached company data when available.
  - Incremental refresh uses a per-company timestamp watermark (`published_at` / `updated_at`) and only treats newer rows as new; notes include cache window (`from -> to`) per company.

The UI is a **React** app (Vite + TypeScript + Plotly) talking to a local **FastAPI** backend (`talenthawk/web_api.py`).

---

## Quick start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/), [uv](https://docs.astral.sh/uv/getting-started/installation/), and [Node.js](https://nodejs.org/) (for the React UI).

```bash
git clone https://github.com/awesomesince96/talenthawk.git
cd talenthawk
uv sync
cd web && npm install && cd ..
```

**One command (single terminal, fresh UI build each run):** deletes `web/dist`, rebuilds the React app, then serves API + static files on port 8000 with `--reload` for Python changes.

```bash
./dev.sh
```

Open **http://127.0.0.1:8000**.

**Development (two terminals, hot-reload React):** run the API and the Vite dev server. Vite proxies `/api` to the backend.

```bash
# Terminal 1 — API on http://127.0.0.1:8000
uv run uvicorn talenthawk.web_api:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — React on http://127.0.0.1:5173
cd web && npm run dev
```

Open **http://127.0.0.1:5173** and use **Refresh jobs** (Jobs API view) or **Refresh career listings** (Career tracker) to load data.

**Production-style (single process):** build the frontend, then serve API + static files from uvicorn:

```bash
cd web && npm run build && cd ..
uv run uvicorn talenthawk.web_api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** (serves the built app when `web/dist` exists).

### SerpAPI (optional)

1. Create an API key at [serpapi.com](https://serpapi.com/).
2. Set the key in one of these ways:
   - Copy **`.env.example`** to **`.env`** in the project root and set `SERPAPI_API_KEY` (loaded automatically when you run the API).
   - Or export `SERPAPI_API_KEY=...` in your shell before starting uvicorn.

3. In the app, choose **SerpAPI** or **Remotive + SerpAPI**, set **query** / **location**, then **Refresh jobs**.

---

## Persistence

**`data/persistence/`** (gitignored — local machine only)

| File | Purpose |
|------|---------|
| `title_filter.json` | Lines matched against job **title** (rules added with **−** on a row); hits are hidden. |
| `title_ignore_words.json` | Comma- or newline-separated phrases; if a job **title** contains any phrase (substring, case-insensitive), it is hidden. Edited in the sidebar **Title ignore words** box. |
| `company_filter.json` | Lines matched against **company** name. |
| `category_filter.json` | Lines matched against the **inferred category** label. |
| `serpapi_prefs.json` | **SerpAPI** search **query** and **location** — saved when you **Refresh jobs**. |
| `career_page_tracker_filter.json` | Subset of company ids for the **Career page tracker** (saved from the sidebar multiselect). |

**`data/mappings/`** (versioned defaults in repo)

| File | Purpose |
|------|---------|
| `career_page_mappings.json` | **Career page tracker**: company id, display name, careers list URL, and `fetcher` id (see defaults in `talenthawk/settings.py`). |

**`data/jobs/career/`** (gitignored cache snapshots)

- Per-company cache files used by the Career tracker.
- Used for cache-first rendering, 429 fallback, and incremental refresh watermarking.

Empty filter files default to `[]` if missing. `serpapi_prefs.json` appears after the first refresh (or you can create it by hand). On first run, `career_page_mappings.json` is created from `DEFAULT_CAREER_PAGE_MAPPINGS` in `talenthawk/settings.py` if absent.

---

## Layout

```
talenthawk/
├── pyproject.toml
├── uv.lock
├── web/                    # React (Vite) frontend
│   ├── package.json
│   └── src/
├── talenthawk/
│   ├── web_api.py          # FastAPI server + session state
│   ├── viz_core.py         # Plotly figures + filtering (shared UI logic)
│   ├── fetch_jobs.py       # fetch + normalize + date window
│   ├── categorize.py       # title → category (built-in rules)
│   ├── storage.py          # filter + SerpAPI + career tracker JSON
│   ├── career_page_tracker.py
│   └── settings.py
└── data/
    ├── persistence/        # local-only JSON (gitignored)
    └── mappings/
```

To change how categories are inferred, edit **`DEFAULT_CATEGORY_KEYWORDS`** in `talenthawk/categorize.py`.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
