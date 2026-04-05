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

- Fetches from the public [Remotive remote jobs API](https://remotive.com/api/remote-jobs).
- Keeps listings from the **last 30 days**.
- Assigns a **category** per job from **built-in title keywords** in code (`talenthawk/categorize.py`); first match wins, else **Other**.
- **Three filters** (JSON under `data/persistence/`): **title**, **company**, **category** — substring rules, case-insensitive. Use **-** on a row to add a rule; **✕** in the left **Filters** panel to remove.
- **Tabs**: **Included jobs** (table, search, pies) and **Hidden jobs** (charts and tables for excluded rows).

---

## Quick start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/awesomesince96/talenthawk.git
cd talenthawk
uv sync
uv run streamlit run streamlit_app.py
```

---

## Persistence (`data/persistence/`)

| File | Purpose |
|------|---------|
| `title_filter.json` | Lines matched against job **title**; hits are hidden from the main view. |
| `company_filter.json` | Lines matched against **company** name. |
| `category_filter.json` | Lines matched against the **inferred category** label. |

Empty lists `[]` are created on first run if files are missing.

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
│   ├── storage.py       # filter JSON only
│   └── settings.py      # paths + API URL
└── data/persistence/    # filter JSON (see above)
```

To change how categories are inferred, edit **`DEFAULT_CATEGORY_KEYWORDS`** in `talenthawk/categorize.py`.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
