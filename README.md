# TalentHawk

Small local tool to **pull recent remote job listings**, **tag them by title category**, **block companies you do not want**, and **see charts** for what you keep vs. what is filtered out.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd talenthawk
uv sync
uv run streamlit run streamlit_app.py
```

`uv sync` creates `.venv`, resolves dependencies from `pyproject.toml` and `uv.lock`, and installs this package in editable mode so `import talenthawk` works.

The UI opens in your browser. On first load it calls the public [Remotive jobs API](https://remotive.com/api/remote-jobs), keeps rows whose `publication_date` is within the **last 30 days**, and applies your rules.

## Local persistence (`data/persistence/`)

| File | Purpose |
|------|---------|
| `companies_blocklist.json` | Company names to **exclude** from the Included tab and search. Matching is case-insensitive; a block entry can match as a substring of the company name (and vice versa). |
| `category_keywords.json` | Ordered rules: each category has **keywords**; the **first** category whose keyword appears in the job **title** wins; otherwise the job is **Other**. |
| `jobs_cache.json` | Optional on-disk copy of the last fetch (gitignored). Use **Load from saved cache** if the API is unreachable. |

You can edit the JSON files directly or use the sidebar / **Category rules** tab in the app.

## Charts

- **Included jobs** — searchable table and category bar chart for listings that **passed** the company blocklist.
- **Filtered-out insights** — same 30-day window, but only blocklisted companies: category distribution and **which companies** drive excluded volume.

## Notes

- The Remotive feed is a **single public source**; volume may be modest. To add ATS feeds or another API, extend `talenthawk/fetch_jobs.py` and merge results into the same schema (`title`, `company`, `published_at`, `url`, `source`).
