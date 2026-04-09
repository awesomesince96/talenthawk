from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENCE_DIR = DATA_DIR / "persistence"

TITLE_FILTER_FILE = PERSISTENCE_DIR / "title_filter.json"
COMPANY_FILTER_FILE = PERSISTENCE_DIR / "company_filter.json"
CATEGORY_FILTER_FILE = PERSISTENCE_DIR / "category_filter.json"
SERPAPI_PREFS_FILE = PERSISTENCE_DIR / "serpapi_prefs.json"
CAREER_PAGE_MAPPINGS_FILE = PERSISTENCE_DIR / "career_page_mappings.json"
CAREER_PAGE_TRACKER_FILTER_FILE = PERSISTENCE_DIR / "career_page_tracker_filter.json"

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
        }
    ],
}

# Company IDs selected in the Career page tracker UI (subset of mappings).
DEFAULT_CAREER_TRACKER_FILTER: list[str] = ["uber"]
