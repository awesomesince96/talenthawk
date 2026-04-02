"""
TalentHawk — browse recent remote jobs, filter companies, and view category mix.

Run: streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from talenthawk.categorize import categorize_title
from talenthawk.fetch_jobs import (
    company_is_blocked,
    fetch_remotive_jobs,
    filter_last_n_days,
)
from talenthawk.settings import DEFAULT_BLOCKLIST, DEFAULT_CATEGORY_KEYWORDS
from talenthawk.storage import (
    load_category_keywords,
    load_company_blocklist,
    load_jobs_cache,
    persistence_paths,
    save_blocklist,
    save_category_keywords,
    save_company_blocklist,
    save_jobs_cache,
)

PAGE_SIZE = 25
MAX_TITLE_LEN = 80


def _truncate(text: str, max_len: int) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def sync_blocklist_drafts_from_disk() -> None:
    st.session_state["blocklist_draft"] = "\n".join(load_company_blocklist(1))
    st.session_state["blocklist_2_draft"] = "\n".join(load_company_blocklist(2))


def ensure_persistence_defaults() -> None:
    paths = persistence_paths()
    paths["persistence_dir"].mkdir(parents=True, exist_ok=True)
    if not paths["blocklist"].exists():
        save_blocklist(list(DEFAULT_BLOCKLIST))
    if not paths["blocklist_2"].exists():
        save_company_blocklist(2, list(DEFAULT_BLOCKLIST))
    if not paths["category_keywords"].exists():
        save_category_keywords([dict(x) for x in DEFAULT_CATEGORY_KEYWORDS])


def add_company_to_blocklist_slot(slot: int, company: str) -> None:
    """Append one company to blocklist 1 or 2 if not already matched; persist and sync sidebar text."""
    c = str(company).strip()
    if not c:
        return
    bl = load_company_blocklist(slot)
    if company_is_blocked(c, bl):
        return
    bl.append(c)
    save_company_blocklist(slot, bl)
    sync_blocklist_drafts_from_disk()


def remove_company_blocklist_entry(slot: int, entry: str) -> None:
    """Remove one exact string from the given blocklist."""
    bl = load_company_blocklist(slot)
    new_list = [x for x in bl if x != entry]
    save_company_blocklist(slot, new_list)
    sync_blocklist_drafts_from_disk()


def render_excluded_insights(df_e: pd.DataFrame) -> None:
    """Charts and table for one excluded cohort."""
    if df_e.empty:
        st.caption("No listings in this cohort.")
        return
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**By category**")
        cat_counts = df_e.groupby("category").size().reset_index(name="count")
        fig_cat = px.bar(cat_counts, x="category", y="count", color="category", labels={"count": "Jobs"})
        fig_cat.update_layout(showlegend=False, xaxis_title=None)
        st.plotly_chart(fig_cat, use_container_width=True)
    with col_b:
        st.markdown("**Top companies**")
        comp_counts = df_e.groupby("company").size().reset_index(name="count").sort_values("count", ascending=False)
        top_n = min(25, len(comp_counts))
        fig_co = px.bar(comp_counts.head(top_n), x="company", y="count", labels={"count": "Jobs"})
        fig_co.update_layout(xaxis_tickangle=-45, showlegend=False)
        st.plotly_chart(fig_co, use_container_width=True)

    st.dataframe(
        df_e[["title", "company", "category", "published_at", "url"]].sort_values("company"),
        use_container_width=True,
        hide_index=True,
    )


def annotate_jobs(jobs: list[dict], categories: list[dict]) -> list[dict]:
    out = []
    for j in jobs:
        title = j.get("title") or ""
        company = j.get("company") or ""
        cat = categorize_title(title, categories)
        row = {**j, "category": cat, "company": company, "title": title}
        out.append(row)
    return out


def load_jobs_into_session() -> None:
    """Populate ``st.session_state['jobs_raw']`` from API, falling back to disk cache."""
    try:
        raw = fetch_remotive_jobs()
        st.session_state["jobs_raw"] = raw
        st.session_state["jobs_source"] = "remotive_api"
    except Exception as e:
        cache = load_jobs_cache()
        if cache and isinstance(cache.get("jobs"), list):
            st.session_state["jobs_raw"] = cache["jobs"]
            st.session_state["jobs_source"] = f"disk_cache ({cache.get('fetched_at', '?')})"
            st.session_state["jobs_error"] = str(e)
        else:
            st.session_state["jobs_raw"] = []
            st.session_state["jobs_source"] = "none"
            st.session_state["jobs_error"] = str(e)


def main() -> None:
    st.set_page_config(page_title="TalentHawk", layout="wide")
    ensure_persistence_defaults()

    if "category_rules_draft" not in st.session_state:
        st.session_state["category_rules_draft"] = json.dumps(
            load_category_keywords(), indent=2, ensure_ascii=False
        )

    if "blocklist_draft" not in st.session_state or "blocklist_2_draft" not in st.session_state:
        sync_blocklist_drafts_from_disk()

    st.title("TalentHawk")
    st.caption(
        "Indexes remote listings from the last 30 days (Remotive), groups titles into categories, "
        "and keeps company and role rules on disk under `data/persistence/`."
    )

    if "jobs_raw" not in st.session_state:
        with st.spinner("Fetching jobs…"):
            load_jobs_into_session()

    with st.sidebar:
        st.header("Jobs")
        if st.button("Refresh from Remotive API", type="primary"):
            with st.spinner("Fetching…"):
                try:
                    raw = fetch_remotive_jobs()
                    st.session_state["jobs_raw"] = raw
                    st.session_state["jobs_source"] = "remotive_api"
                    st.session_state.pop("jobs_error", None)
                    st.success(f"Loaded {len(raw)} listings.")
                except Exception as e:
                    st.error(str(e))
        if st.button("Load from saved cache file"):
            cache = load_jobs_cache()
            if cache and isinstance(cache.get("jobs"), list):
                st.session_state["jobs_raw"] = cache["jobs"]
                st.session_state["jobs_source"] = f"disk_cache ({cache.get('fetched_at', '?')})"
                st.success(f"Loaded {len(cache['jobs'])} from cache.")
            else:
                st.warning("No cache file yet.")

        if st.button("Save current listings to cache"):
            raw = st.session_state.get("jobs_raw") or []
            if raw:
                save_jobs_cache(raw, datetime.now(timezone.utc).isoformat())
                st.success("Saved under data/persistence/jobs_cache.json.")
            else:
                st.warning("Nothing to save.")

        src = st.session_state.get("jobs_source", "?")
        st.caption(f"Source: **{src}**")
        err = st.session_state.get("jobs_error")
        if err:
            st.caption(f"Last fetch error: {err}")

        st.header("Company blocklists")
        st.caption("Two independent lists. Jobs are **included** only when the company matches neither list. Matching is case-insensitive with substring rules.")
        st.markdown("**Blocklist 1**")
        st.text_area(
            "Blocklist 1 one per line",
            height=120,
            label_visibility="collapsed",
            key="blocklist_draft",
        )
        c_bl1a, c_bl1b = st.columns(2)
        with c_bl1a:
            if st.button("Save list 1"):
                draft = st.session_state.get("blocklist_draft", "")
                lines = [ln.strip() for ln in draft.splitlines() if ln.strip()]
                save_company_blocklist(1, lines)
                sync_blocklist_drafts_from_disk()
                st.success(f"Saved {len(lines)} entr(y/ies).")
        with c_bl1b:
            if st.button("Reload list 1"):
                st.session_state["blocklist_draft"] = "\n".join(load_company_blocklist(1))
                st.rerun()

        st.markdown("**Blocklist 2**")
        st.text_area(
            "Blocklist 2 one per line",
            height=120,
            label_visibility="collapsed",
            key="blocklist_2_draft",
        )
        c_bl2a, c_bl2b = st.columns(2)
        with c_bl2a:
            if st.button("Save list 2"):
                draft = st.session_state.get("blocklist_2_draft", "")
                lines = [ln.strip() for ln in draft.splitlines() if ln.strip()]
                save_company_blocklist(2, lines)
                sync_blocklist_drafts_from_disk()
                st.success(f"Saved {len(lines)} entr(y/ies).")
        with c_bl2b:
            if st.button("Reload list 2"):
                st.session_state["blocklist_2_draft"] = "\n".join(load_company_blocklist(2))
                st.rerun()

        st.header("Paths")
        for label, path in persistence_paths().items():
            st.caption(f"{label}: `{path}`")

    raw = st.session_state.get("jobs_raw") or []
    blocklist_1 = load_company_blocklist(1)
    blocklist_2 = load_company_blocklist(2)
    categories = load_category_keywords()

    windowed = filter_last_n_days(raw, days=30)
    annotated = annotate_jobs(windowed, categories)

    def is_included(job: dict) -> bool:
        co = job.get("company") or ""
        return not company_is_blocked(co, blocklist_1) and not company_is_blocked(co, blocklist_2)

    included = [j for j in annotated if is_included(j)]
    excluded_1 = [j for j in annotated if company_is_blocked(j["company"], blocklist_1)]
    excluded_2 = [j for j in annotated if company_is_blocked(j["company"], blocklist_2)]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Fetched (all time in feed)", len(raw))
    c2.metric("Published in last 30 days", len(windowed))
    c3.metric("Included", len(included))
    c4.metric("Match list 1", len(excluded_1))
    c5.metric("Match list 2", len(excluded_2))

    tab_inc, tab_exc, tab_rules = st.tabs(["Included jobs", "Filtered-out insights", "Category rules"])

    with tab_inc:
        q = st.text_input("Search included jobs (title or company)", "")
        df_i = pd.DataFrame(included)
        if not df_i.empty:
            if q.strip():
                ql = q.lower()
                m = df_i["title"].str.lower().str.contains(ql, na=False) | df_i["company"].str.lower().str.contains(ql, na=False)
                df_show = df_i[m]
            else:
                df_show = df_i

            st.caption(
                "Each row: **title**, **company**, then **1** / **2** to add that company to blocklist 1 or 2. "
                "Buttons are disabled if the company already matches that list."
            )
            n_show = len(df_show)
            if n_show == 0:
                st.info("No rows match your search.")
            else:
                total_pages = max(1, (n_show + PAGE_SIZE - 1) // PAGE_SIZE)
                page_key = "included_jobs_page"
                if page_key in st.session_state and int(st.session_state[page_key]) > total_pages:
                    st.session_state[page_key] = total_pages
                page = st.number_input(
                    "Page",
                    min_value=1,
                    max_value=total_pages,
                    step=1,
                    key=page_key,
                )
                start = (int(page) - 1) * PAGE_SIZE
                chunk = df_show.iloc[start : start + PAGE_SIZE]
                st.caption(f"Showing {start + 1}–{min(start + PAGE_SIZE, n_show)} of {n_show}")

                hdr_t, hdr_c, hdr_1, hdr_2 = st.columns([3.2, 2.2, 0.45, 0.45])
                hdr_t.markdown("**Title**")
                hdr_c.markdown("**Company**")
                hdr_1.markdown("**1**")
                hdr_2.markdown("**2**")

                for pos in range(len(chunk)):
                    row = chunk.iloc[pos]
                    title = str(row.get("title", "") or "")
                    company = str(row.get("company", "") or "").strip()
                    row_key = f"{start}_{pos}"
                    t_col, c_col, b1_col, b2_col = st.columns([3.2, 2.2, 0.45, 0.45], vertical_alignment="center")
                    with t_col:
                        st.text(_truncate(title, MAX_TITLE_LEN))
                    with c_col:
                        st.text(company or "—")
                    with b1_col:
                        d1 = not company or company_is_blocked(company, blocklist_1)
                        if st.button(
                            "1",
                            key=f"bl1_{row_key}",
                            help="Add company to blocklist 1",
                            disabled=d1,
                        ):
                            add_company_to_blocklist_slot(1, company)
                            st.toast(f"List 1: {company}")
                            st.rerun()
                    with b2_col:
                        d2 = not company or company_is_blocked(company, blocklist_2)
                        if st.button(
                            "2",
                            key=f"bl2_{row_key}",
                            help="Add company to blocklist 2",
                            disabled=d2,
                        ):
                            add_company_to_blocklist_slot(2, company)
                            st.toast(f"List 2: {company}")
                            st.rerun()
        else:
            st.info("No jobs in the 30-day window (or feed is empty).")

        st.subheader("Category distribution (included)")
        if not df_i.empty:
            fig = px.bar(
                df_i.groupby("category").size().reset_index(name="count"),
                x="category",
                y="count",
                color="category",
                labels={"count": "Jobs"},
            )
            fig.update_layout(showlegend=False, xaxis_title=None)
            st.plotly_chart(fig, use_container_width=True)

    with tab_exc:
        st.subheader("Blocklists and filtered insights")
        st.write(
            "Manage both lists below (**✕** removes a rule). Insights use the same 30-day window as included jobs; "
            "each section shows listings whose **company** matches that list."
        )

        st.markdown("##### Blocklist 1 — active rules")
        if not blocklist_1:
            st.caption("Empty. Add from **Included jobs** (button **1**) or the sidebar.")
        else:
            for i, entry in enumerate(blocklist_1):
                c_l, c_r = st.columns([0.92, 0.08], vertical_alignment="center")
                with c_l:
                    st.text(entry)
                with c_r:
                    if st.button("✕", key=f"blocklist1_remove_{i}", help="Remove from blocklist 1"):
                        remove_company_blocklist_entry(1, entry)
                        st.toast(f"Removed from list 1: {entry}")
                        st.rerun()

        st.markdown("##### Blocklist 2 — active rules")
        if not blocklist_2:
            st.caption("Empty. Add from **Included jobs** (button **2**) or the sidebar.")
        else:
            for i, entry in enumerate(blocklist_2):
                c_l, c_r = st.columns([0.92, 0.08], vertical_alignment="center")
                with c_l:
                    st.text(entry)
                with c_r:
                    if st.button("✕", key=f"blocklist2_remove_{i}", help="Remove from blocklist 2"):
                        remove_company_blocklist_entry(2, entry)
                        st.toast(f"Removed from list 2: {entry}")
                        st.rerun()

        st.divider()
        st.markdown("### Matches blocklist 1")
        render_excluded_insights(pd.DataFrame(excluded_1))

        st.divider()
        st.markdown("### Matches blocklist 2")
        render_excluded_insights(pd.DataFrame(excluded_2))

    with tab_rules:
        st.write(
            "Rules drive title categories (first keyword match wins; otherwise **Other**). "
            "You can also edit `data/persistence/category_keywords.json` directly."
        )
        st.text_area(
            "Category rules (JSON array)",
            height=400,
            key="category_rules_draft",
        )
        col_save, col_reset = st.columns(2)
        with col_save:
            if st.button("Save category rules"):
                try:
                    draft = st.session_state.get("category_rules_draft", "")
                    parsed = json.loads(draft)
                    if not isinstance(parsed, list):
                        raise ValueError("Root must be a JSON array")
                    save_category_keywords(parsed)
                    st.session_state["category_rules_draft"] = json.dumps(parsed, indent=2, ensure_ascii=False)
                    st.success("Saved.")
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")
        with col_reset:
            if st.button("Reload rules from disk"):
                st.session_state["category_rules_draft"] = json.dumps(
                    load_category_keywords(), indent=2, ensure_ascii=False
                )
                st.rerun()


if __name__ == "__main__":
    main()
