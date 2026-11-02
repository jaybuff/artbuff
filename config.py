import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else BASE_DIR / p


TV_PORT = int(os.getenv("TV_PORT", "8002"))
TV_TOKEN_FILE = _path(os.getenv("TV_TOKEN_FILE", "data/tv-token.txt"))

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8420"))

LETTERBOX_COLOR = os.getenv("LETTERBOX_COLOR", "black")
MAX_TV_UPLOADS = int(os.getenv("MAX_TV_UPLOADS", "20"))

DB_PATH = _path(os.getenv("DB_PATH", "data/artbuff.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TV_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
TV_IP_FILE = TV_TOKEN_FILE.with_name("tv-ip.txt")  # entered on the TV page
TV_MAC_FILE = TV_TOKEN_FILE.with_name("tv-mac.txt")  # learned from the TV, so it can be woken after a restart

# Hard ceiling on outbound requests/second to the Met (their stated limit is 80; we clamp to it).
MET_MAX_RPS = min(int(os.getenv("MET_MAX_RPS", "10")), 80)
LOG_FILE = _path(os.getenv("LOG_FILE", "data/artbuff.log"))

# Background cache warmer: pages ahead to prefetch (0 = off) and seconds between its requests.
WARM_PAGES = int(os.getenv("WARM_PAGES", "2"))
WARM_INTERVAL = float(os.getenv("WARM_INTERVAL", "1.0"))

# Local caches (data fetched from museums is stored here and reused)
CACHE_DIR = _path(os.getenv("CACHE_DIR", "data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_THUMBS_MB = int(os.getenv("CACHE_THUMBS_MB", "1024"))
CACHE_FULL_MB = int(os.getenv("CACHE_FULL_MB", "2048"))

# Images sent to /api/send-image. Not a cache: these are the only copies, and they're never evicted.
UPLOADS_DIR = _path(os.getenv("UPLOADS_DIR", "data/uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
