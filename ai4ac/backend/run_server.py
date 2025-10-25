#!/usr/bin/env python3
"""
run_server.py - Run the FastAPI server with correct paths and environment setup
"""
import sys
import os
from pathlib import Path

# --- START OF MODIFICATION: Force disable Flash Attention ---
# Set environment variable BEFORE importing transformers indirectly
os.environ["TRANSFORMERS_NO_FLASH_ATTENTION_2"] = "1"
print("INFO: Set TRANSFORMERS_NO_FLASH_ATTENTION_2=1 to force disable Flash Attention.")
# --- END OF MODIFICATION ---


# Add the src directory to Python path
# Ensure paths are absolute
current_file_dir = Path(__file__).parent.resolve()
src_dir = current_file_dir / "src"
project_root = current_file_dir # Assuming run_server.py is in the backend root

# Add project root and src to sys.path if not already present
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Change to the project root directory
os.chdir(project_root)

# Now import and run
if __name__ == "__main__":
    # Configure logging early
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
    logger = logging.getLogger(__name__)

    try:
        # Import necessary modules after path setup and env var setting
        from src.main import app # Corrected import path
        import uvicorn
        logger.info("Starting server from project root...")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info(f"Python path includes: {src_dir}")

        # Use reload=False for production or if reload causes issues
        # Use reload=True for development
        uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure you've installed all requirements in your virtual environment:")
        logger.error("  pip install -r requirements/requirements.txt")
        logger.error("  pip install -r requirements/requirements2.txt")
        logger.error("  pip install -r requirements/requirements_web.txt")
        logger.error(f"Current sys.path: {sys.path}")
    except Exception as e:
        logger.error(f"Error starting server: {e}", exc_info=True)
