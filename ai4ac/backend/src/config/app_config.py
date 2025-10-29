import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
# --- START MODIFICATION: Add remediated directory ---
REMEDIATED_DIR = BASE_DIR / "data" / "remediated"
# --- END MODIFICATION ---

# --- START OF MODIFICATION: Centralize cache directory path ---
# Define a single, consistent cache path to be used across the application.
# This ensures that both model downloading and cache clearing target the same directory.
try:
    # Assumes the structure is /scratch/{project_folder}/ai4ac/backend
    SCRATCH_DIR = BASE_DIR.parent.parent
    CUSTOM_CACHE_DIR = SCRATCH_DIR / ".cache" / "huggingface"
except IndexError:
    # Fallback to a local cache within the project if the scratch structure isn't present
    CUSTOM_CACHE_DIR = BASE_DIR / "data" / "cache"
# --- END MODIFICATION ---


# Ensure directories exist
# --- START MODIFICATION: Add remediated directory to creation list ---
for dir_path in [UPLOAD_DIR, PROCESSED_DIR, REMEDIATED_DIR, CUSTOM_CACHE_DIR]:
# --- END MODIFICATION ---
    dir_path.mkdir(parents=True, exist_ok=True)

# Agent settings from environment
AGENT_MAX_CHUNKS = int(os.environ.get("AGENT_MAX_CHUNKS", 1000))
DEFAULT_CHUNK_SIZE = int(os.environ.get("AGENT_CHUNK_SIZE", 512))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("AGENT_CHUNK_OVERLAP", 64))
DEFAULT_MAX_WORKERS = min(4, (os.cpu_count() or 1))
