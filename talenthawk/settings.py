from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENCE_DIR = DATA_DIR / "persistence"
MAPPINGS_DIR = DATA_DIR / "mappings"
JOBS_CACHE_DIR = DATA_DIR / "jobs"
JOBS_CACHE_CAREER_SUBDIR = "career"
JOBS_CACHE_FEED_SUBDIR = "feed"

TITLE_FILTER_FILE = PERSISTENCE_DIR / "title_filter.json"
TITLE_IGNORE_WORDS_FILE = PERSISTENCE_DIR / "title_ignore_words.json"
COMPANY_FILTER_FILE = PERSISTENCE_DIR / "company_filter.json"
CATEGORY_FILTER_FILE = PERSISTENCE_DIR / "category_filter.json"
SERPAPI_PREFS_FILE = PERSISTENCE_DIR / "serpapi_prefs.json"
CAREER_PAGE_TRACKER_FILTER_FILE = PERSISTENCE_DIR / "career_page_tracker_filter.json"
CAREER_PAGE_MAPPINGS_FILE = MAPPINGS_DIR / "career_page_mappings.json"

REMOTE_JOBS_URL = "https://remotive.com/api/remote-jobs"
SERPAPI_SEARCH_URL = "https://serpapi.com/search"

DEFAULT_FILTER_LIST: list[str] = []

DEFAULT_SERPAPI_QUERY = "software engineer"
DEFAULT_SERPAPI_LOCATION = "austin"

DEFAULT_CAREER_PAGE_MAPPINGS: dict[str, object] = {
    "version": 1,
    "companies": [
        {
            "id": "uber",
            "display_name": "Uber",
            "careers_list_url": "https://www.uber.com/us/en/careers/list/?department=Engineering",
            "fetcher": "uber_search_api",
        },
        {
            "id": "netflix",
            "display_name": "Netflix",
            "careers_list_url": "https://explore.jobs.netflix.net/careers",
            "fetcher": "eightfold_netflix",
            "eightfold_location": "United States",
        },
        {
            "id": "microsoft",
            "display_name": "Microsoft",
            "careers_list_url": "https://apply.careers.microsoft.com/careers",
            "fetcher": "pcsx_microsoft",
            "pcsx_query": "",
            "pcsx_location": "United States",
        },
    ],
}

# Company IDs selected in the Career page tracker UI (subset of mappings).
DEFAULT_CAREER_TRACKER_FILTER: list[str] = ["uber"]
