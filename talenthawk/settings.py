from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENCE_DIR = DATA_DIR / "persistence"

BLOCKLIST_FILE = PERSISTENCE_DIR / "companies_blocklist.json"
BLOCKLIST_2_FILE = PERSISTENCE_DIR / "companies_blocklist_2.json"
CATEGORY_KEYWORDS_FILE = PERSISTENCE_DIR / "category_keywords.json"
JOBS_CACHE_FILE = PERSISTENCE_DIR / "jobs_cache.json"

REMOTE_JOBS_URL = "https://remotive.com/api/remote-jobs"

DEFAULT_BLOCKLIST: list[str] = []

DEFAULT_CATEGORY_KEYWORDS: list[dict] = [
    {"name": "Engineering", "keywords": ["engineer", "developer", "software", "devops", "sre", "backend", "frontend", "full stack", "fullstack"]},
    {"name": "Data & ML", "keywords": ["data scientist", "data engineer", "machine learning", "ml engineer", "analytics", "bi developer"]},
    {"name": "Product", "keywords": ["product manager", "product owner", "product lead", "technical program"]},
    {"name": "Design", "keywords": ["designer", "ux", "ui designer", "product design"]},
    {"name": "QA", "keywords": ["qa", "quality assurance", "test engineer", "sdet"]},
    {"name": "Security", "keywords": ["security", "infosec", "cyber"]},
    {"name": "Management", "keywords": ["cto", "vp engineering", "head of engineering", "engineering manager", "director"]},
]
