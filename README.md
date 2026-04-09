<div align="center">

# TalentHawk

**Local remote job browser** — pull recent listings, infer a simple category from each title, and exclude rows with **title**, **company**, and **category** filters you control.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![uv](https://img.shields.io/badge/package%20manager-uv-DE5FE9?style=flat)](https://docs.astral.sh/uv/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/awesomesince96/talenthawk/blob/main/LICENSE)

</div>

---

## What it does

- **Job sources** (sidebar): **Remotive** (free, open API) and/or **SerpAPI [Google Jobs](https://serpapi.com/google-jobs-api)** (paid key; richer volume). **Merged** mode dedupes by title + company + URL. Listings load only when you click **Refresh jobs** (no automatic fetch on startup).
- **Posted within** sidebar control: **1, 3, 7, 14, or 30 days** (default 30) when a post date is present; SerpAPI rows with only relative text (“5 days ago”) are normalized when possible, otherwise kept so they are not dropped silently.
- Assigns a **category** per job from **built-in title keywords** in code (`talenthawk/categorize.py`); first match wins, else **Other**.
- **Three filters** (JSON under `data/persistence/`): **title**, **company**, **category** — substring rules, case-insensitive. Use **-** on a row to add a rule; **✕** in the left **Filters** panel to remove.
- **Tabs**: **Included jobs** (table, search, pies) and **Hidden jobs** (charts and tables for excluded rows).
- **Career page tracker**: choose tracked companies in the sidebar; **`data/mappings/career_page_mappings.json`** maps each company to a careers list URL and fetcher (starts with **Uber** → Engineering via `loadSearchJobsResults`, **USA** locations only, **50** rows sorted by **created** date, **updated** shown when present).

---

## Quick start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/awesomesince96/talenthawk.git
cd talenthawk
uv sync
uv run streamlit run streamlit_app.py
```

Then open the app and click **Refresh jobs** in the sidebar to pull listings.

### SerpAPI (optional)

1. Create an API key at [serpapi.com](https://serpapi.com/).
2. Set the key in one of these ways:
   - Copy **`.env.example`** to **`.env`** in the project root and set `SERPAPI_API_KEY` (loaded automatically when you run the app).
   - Or export `SERPAPI_API_KEY=...` in your shell before launch.
   - Or add to **`.streamlit/secrets.toml`** (create the folder/file if needed):

   ```toml
   SERPAPI_API_KEY = "your_key_here"
   ```

3. In the app sidebar, choose **SerpAPI — Google Jobs** or **Remotive + SerpAPI**, set **query** / **location**, then **Refresh jobs**.

---

## Persistence

**`data/persistence/`** (gitignored — local machine only)

| File | Purpose |
|------|---------|
| `title_filter.json` | Lines matched against job **title** (rules added with **−** on a row); hits are hidden. |
| `title_ignore_words.json` | Comma- or newline-separated phrases; if a job **title** contains any phrase (substring, case-insensitive), it is hidden. Edited in the sidebar **Title ignore words** box. |
| `company_filter.json` | Lines matched against **company** name. |
| `category_filter.json` | Lines matched against the **inferred category** label. |
| `serpapi_prefs.json` | **SerpAPI** search **query** and **location** — loaded on startup, saved when you **Refresh jobs** (local only; not sent to any API until refresh). |
| `career_page_tracker_filter.json` | Subset of company ids to load in the **Career page tracker** tab (saved from the sidebar multiselect). |

**`data/mappings/`** (versioned defaults in repo)

| File | Purpose |
|------|---------|
| `career_page_mappings.json` | **Career page tracker**: company id, display name, careers list URL, and `fetcher` id (see defaults in `talenthawk/settings.py`). |

Empty filter files default to `[]` if missing. `serpapi_prefs.json` appears after the first refresh (or you can create it by hand). On first run, `career_page_mappings.json` is created from `DEFAULT_CAREER_PAGE_MAPPINGS` in `talenthawk/settings.py` if absent.

---

## Layout

```
talenthawk/
├── streamlit_app.py
├── pyproject.toml
├── uv.lock
├── talenthawk/
│   ├── fetch_jobs.py    # fetch + normalize + date window
│   ├── categorize.py    # title → category (built-in rules)
│   ├── storage.py            # filter + SerpAPI + career tracker JSON
│   ├── career_page_tracker.py # career fetchers (e.g. Uber search API)
│   └── settings.py           # paths + API URL + defaults
└── data/
    ├── persistence/    # local-only JSON (gitignored; see Persistence)
    └── mappings/       # career_page_mappings.json (defaults in repo)
```

To change how categories are inferred, edit **`DEFAULT_CATEGORY_KEYWORDS`** in `talenthawk/categorize.py`.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
