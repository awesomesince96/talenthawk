from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENCE_DIR = DATA_DIR / "persistence"

TITLE_FILTER_FILE = PERSISTENCE_DIR / "title_filter.json"
COMPANY_FILTER_FILE = PERSISTENCE_DIR / "company_filter.json"
CATEGORY_FILTER_FILE = PERSISTENCE_DIR / "category_filter.json"

REMOTE_JOBS_URL = "https://remotive.com/api/remote-jobs"

DEFAULT_FILTER_LIST: list[str] = []
