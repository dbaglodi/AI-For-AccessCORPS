#!/usr/bin/env python3
"""
run_server.py - Run the FastAPI server with correct paths
"""
import sys
import os
from pathlib import Path

# Add the src directory to Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

# Change to the project root directory
os.chdir(Path(__file__).parent)

# Now import and run
if __name__ == "__main__":
    try:
        from main import app
        import uvicorn
        print("Starting server from project root...")
        print(f"Working directory: {os.getcwd()}")
        print(f"Python path includes: {src_dir}")
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you've installed all requirements:")
        print("  pip install -r requirements/requirements.txt")
        print("  pip install -r requirements/requirements2.txt") 
        print("  pip install -r requirements/requirements_web.txt")
    except Exception as e:
        print(f"Error starting server: {e}")
