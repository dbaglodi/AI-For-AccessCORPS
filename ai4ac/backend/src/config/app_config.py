import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads" 
PROCESSED_DIR = BASE_DIR / "data" / "processed"
CACHE_DIR = BASE_DIR / "data" / "cache"

# Ensure directories exist
for dir_path in [UPLOAD_DIR, PROCESSED_DIR, CACHE_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Agent settings from environment
AGENT_MAX_CHUNKS = int(os.environ.get("AGENT_MAX_CHUNKS", 1000))
DEFAULT_CHUNK_SIZE = int(os.environ.get("AGENT_CHUNK_SIZE", 512))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("AGENT_CHUNK_OVERLAP", 64))
DEFAULT_MAX_WORKERS = min(4, (os.cpu_count() or 1))
