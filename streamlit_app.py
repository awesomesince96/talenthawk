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
    load_blocklist,
    load_category_keywords,
    load_jobs_cache,
    persistence_paths,
    save_blocklist,
    save_category_keywords,
    save_jobs_cache,
)


def ensure_persistence_defaults() -> None:
    paths = persistence_paths()
    paths["persistence_dir"].mkdir(parents=True, exist_ok=True)
    if not paths["blocklist"].exists():
        save_blocklist(list(DEFAULT_BLOCKLIST))
    if not paths["category_keywords"].exists():
        save_category_keywords([dict(x) for x in DEFAULT_CATEGORY_KEYWORDS])


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

    if "blocklist_draft" not in st.session_state:
        st.session_state["blocklist_draft"] = "\n".join(load_blocklist())

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

        st.header("Company blocklist")
        st.caption("Ignored in search (included tab). Case-insensitive; partial name match.")
        st.text_area(
            "One company per line",
            height=160,
            label_visibility="collapsed",
            key="blocklist_draft",
        )
        if st.button("Save blocklist"):
            draft = st.session_state.get("blocklist_draft", "")
            lines = [ln.strip() for ln in draft.splitlines() if ln.strip()]
            save_blocklist(lines)
            st.session_state["blocklist_draft"] = "\n".join(lines)
            st.success(f"Saved {len(lines)} entr(y/ies).")
        if st.button("Reload blocklist from disk"):
            st.session_state["blocklist_draft"] = "\n".join(load_blocklist())
            st.rerun()

        st.header("Paths")
        for label, path in persistence_paths().items():
            st.caption(f"{label}: `{path}`")

    raw = st.session_state.get("jobs_raw") or []
    blocklist = load_blocklist()
    categories = load_category_keywords()

    windowed = filter_last_n_days(raw, days=30)
    annotated = annotate_jobs(windowed, categories)

    included = [j for j in annotated if not company_is_blocked(j["company"], blocklist)]
    excluded = [j for j in annotated if company_is_blocked(j["company"], blocklist)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fetched (all time in feed)", len(raw))
    c2.metric("Published in last 30 days", len(windowed))
    c3.metric("Included (searchable)", len(included))
    c4.metric("Excluded (blocklist)", len(excluded))

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
            st.dataframe(
                df_show[["title", "company", "category", "published_at", "url"]],
                use_container_width=True,
                hide_index=True,
            )
            if len(df_show) == 0:
                st.info("No rows match your search.")
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
        st.subheader("Filtered by company blocklist")
        st.write(
            "Same 30-day window and categories as included jobs, but only rows whose **company** matches "
            "your blocklist. Charts show **category mix** and **which companies** account for filtered volume."
        )
        df_e = pd.DataFrame(excluded)
        if df_e.empty:
            st.info("No excluded rows — add companies to the blocklist or no listings matched.")
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**Filtered jobs by category**")
                cat_counts = df_e.groupby("category").size().reset_index(name="count")
                fig_cat = px.bar(cat_counts, x="category", y="count", color="category", labels={"count": "Jobs"})
                fig_cat.update_layout(showlegend=False, xaxis_title=None)
                st.plotly_chart(fig_cat, use_container_width=True)
            with col_b:
                st.markdown("**Top companies (filtered)**")
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
