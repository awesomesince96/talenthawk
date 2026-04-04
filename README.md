<div align="center">

# TalentHawk

**Local-first remote job intelligence** — ingest listings, apply category rules plus separate **title** and **company** filters, and visualize what you keep versus what is hidden.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![uv](https://img.shields.io/badge/package%20manager-uv-DE5FE9?style=flat)](https://docs.astral.sh/uv/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/awesomesince96/talenthawk/blob/main/LICENSE)
[![Repo](https://img.shields.io/badge/GitHub-talenthawk-181717?style=flat&logo=github)](https://github.com/awesomesince96/talenthawk)

</div>

---

## Why this exists

Hiring pipelines are noisy: the same feed mixes roles you want with companies you would never apply to, and titles that need grouping before you can reason about volume. TalentHawk treats that as a **small data pipeline plus a decision UI**: fetch normalized rows, window by recency, classify titles with explicit rules, apply **title and company filters** you control, and surface **included vs. hidden** distributions so you can see *patterns*, not just a flat list.

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [Persistence and configuration](#persistence-and-configuration)
- [Extending](#extending)
- [License](#license)

---

## Features

| Area | What you get |
|------|----------------|
| **Ingest** | Pulls from the public [Remotive remote jobs API](https://remotive.com/api/remote-jobs), normalizes to a single schema (`title`, `company`, `published_at`, `url`, `salary` when present, `source`). |
| **Time window** | Keeps listings whose `published_at` falls in the **last 30 days** (UTC-aware parsing with fallbacks for odd date strings). |
| **Categories** | Ordered keyword rules: **first matching category wins**; otherwise **Other**. Editable in the app or in JSON on disk. |
| **Filters** | Separate **title**, **company**, and **derived category** filter lists (case-insensitive substring rules, bidirectional match). Add rules from **-** beside each row (exclude from results) or edit lines in the sidebar; remove rules on **Filters & hidden jobs** or in JSON. |
| **Resilience** | Optional on-disk `jobs_cache.json` when the API is unreachable; load or refresh from the sidebar. |
| **Analytics** | [Plotly](https://plotly.com/python/) bar charts for category mix on **included** rows; **Filters & hidden jobs** shows charts and tables for listings hidden by title, company, or category filter. |

---

## Architecture

High-level flow from source to UI:

```mermaid
flowchart TB
    subgraph Sources
        API["Remotive API (remote-jobs)"]
        Disk[("jobs_cache.json (optional cache)")]
    end

    subgraph Core["talenthawk package"]
        F["fetch_jobs.py: fetch and normalize"]
        W["30-day window: filter_last_n_days"]
        C["categorize.py: keyword rules"]
        S["storage.py: JSON read and write"]
    end

    subgraph Rules["On-disk rules"]
        TF["title_filter.json"]
        CF["company_filter.json"]
        GF["category_filter.json"]
        CK["category_keywords.json"]
    end

    subgraph App["Streamlit app"]
        UI["Tabs: Included jobs, Filters & hidden jobs, Category rules"]
    end

    API --> F
    Disk -.->|"load from cache"| F
    F --> W
    S --> TF
    S --> CF
    S --> GF
    S --> CK
    TF --> UI
    CF --> UI
    GF --> UI
    CK --> C
    W --> C
    C --> UI
```

**Separation of concerns:** fetching and date filtering live in `fetch_jobs.py`, classification is pure logic in `categorize.py`, persistence is isolated in `storage.py`, and `streamlit_app.py` orchestrates session state, metrics, and charts.

---

## Quick start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/awesomesince96/talenthawk.git
cd talenthawk
uv sync
uv run streamlit run streamlit_app.py
```

- `uv sync` creates `.venv`, installs dependencies from `pyproject.toml` / `uv.lock`, and installs this package in **editable** mode so `import talenthawk` works inside the app.
- The browser UI opens locally. First load fetches from Remotive; use **Load from saved cache** if you are offline and have cached data.

---

## Project layout

```
talenthawk/
├── streamlit_app.py          # Entry UI: fetch, filter, categorize, visualize
├── pyproject.toml            # Package metadata and dependencies
├── uv.lock                   # Locked dependency versions
├── talenthawk/
│   ├── fetch_jobs.py         # HTTP fetch, normalization, date window, text-filter helper
│   ├── categorize.py         # Title → category from ordered keyword rules
│   ├── storage.py            # JSON persistence under data/persistence/
│   └── settings.py           # Paths, defaults, API URL
├── data/persistence/         # User-editable JSON (see table below)
└── LICENSE                   # Apache 2.0
```

---

## Persistence and configuration

Files under `data/persistence/` (created on first run if missing):

| File | Role |
|------|------|
| `title_filter.json` | Patterns matched against job **titles**; matching rows are hidden from the included tab and search. |
| `company_filter.json` | Patterns matched against **company** names; same behavior. On first run, if this file is missing, legacy `companies_blocklist.json` / `companies_blocklist_2.json` are merged into it once. |
| `category_filter.json` | Patterns matched against the **classified** category label (output of `category_keywords` rules), e.g. hiding all **Other** or **QA**. |
| `category_keywords.json` | Ordered rules: each category has **keywords**; the **first** category with a keyword hit in the job **title** wins; otherwise **Other**. |
| `jobs_cache.json` | Optional snapshot of the last successful fetch (**gitignored**). Use **Save current listings to cache** / **Load from saved cache** in the sidebar. |

You can edit JSON directly or use the sidebar (filter text areas), **Filters & hidden jobs** (remove **✕** on a rule), and **Category rules** in the app.

---

## Extending

- **Another job source:** Implement a fetcher that returns the same row shape as `fetch_remotive_jobs()` in [`talenthawk/fetch_jobs.py`](talenthawk/fetch_jobs.py), then merge results in the app (or extend the fetch module) before the 30-day filter.
- **Different time window:** `filter_last_n_days(..., days=30)` is called from `streamlit_app.py`; adjust or expose as a control.
- **Stricter matching:** `matches_text_filter()` in [`talenthawk/fetch_jobs.py`](talenthawk/fetch_jobs.py) applies both title and company rules (`company_is_blocked` is a thin alias). `categorize_title` in [`talenthawk/categorize.py`](talenthawk/categorize.py) is equally easy to swap for regex, allowlists, or other labelers without changing the UI layer.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).
