from fastapi import FastAPI, UploadFile, File, HTTPException, Body, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import shutil
import glob
import os
from uuid import uuid4
import json
from typing import Dict, List, Optional, Any, Callable
import importlib
import asyncio
from datetime import datetime
import logging
from dotenv import load_dotenv
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

app = FastAPI()

# --- START OF MODIFICATION ---
@app.on_event("startup")
def startup_event():
    """
    Check disk space on startup and clear the Hugging Face cache if space is low.
    """
    try:
        # Define a safe threshold in Gigabytes
        threshold_gb = 15.0
        
        # This path must match the one used in agent_pipeline.py
        try:
            # Assumes the project structure is /path/to/scratch/ai4ac/
            # Navigate up from .../backend/src/main.py to the 'scratch' directory
            scratch_dir = Path(__file__).resolve().parents[3]
            cache_dir = scratch_dir / ".cache" / "huggingface"
            logging.warning(f"Using custom cache directory for disk space check: {cache_dir}")
        except IndexError:
            logging.warning("Could not determine scratch directory structure. Using default Hugging Face cache for check.")
            cache_dir = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface')


        if os.path.exists(cache_dir):
            # Get disk usage for the partition where the cache is located
            total, used, free = shutil.disk_usage(str(cache_dir))
            free_gb = free / (1024**3)
            
            logging.warning(f"Checking Hugging Face cache disk space: {free_gb:.2f} GB free.")
            
            if free_gb < threshold_gb:
                logging.warning(f"Free space is below {threshold_gb} GB threshold. Clearing cache...")
                shutil.rmtree(cache_dir)
                logging.warning("Cache cleared successfully.")
                # Recreate the base directory so transformers doesn't complain
                os.makedirs(cache_dir, exist_ok=True)
        else:
            logging.warning(f"Hugging Face cache directory not found: {cache_dir}. Skipping disk space check.")
    except Exception as e:
        logging.error(f"Error during startup cache check: {e}")

# --- END OF MODIFICATION ---

# Load environment variables from .env file
load_dotenv()

# Allow CORS for local frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "data/uploads"
PROCESSED_DIR = "data/processed"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# Track processing status for each file
processing_status = {}

def _resolve_agent_pipeline():
    # Default to hopper pipeline unless explicitly opted out with USE_HOPPER=0
    use_hopper_env = os.environ.get("USE_HOPPER")
    use_hopper = True if use_hopper_env is None else (use_hopper_env != "0")
    # For simplicity this repo uses the single `agent_pipeline` implementation.
    try:
        mod = importlib.import_module("src.pipelines.agent_pipeline")
        logging.info("Using agent_pipeline implementation")
        return mod.run_agent_pipeline
    except Exception as exc:
        logging.error(f"Failed to import pipelines.agent_pipeline as agent_pipeline module: {exc}")
        raise

# Resolve once at module import time; this keeps behavior stable for the process lifetime.
run_agent_pipeline = _resolve_agent_pipeline()

# Lazy RAG initializer
_simple_rag = None
def get_simple_rag():
    global _simple_rag
    if _simple_rag is not None:
        return _simple_rag
    try:
        import src.pipelines.agent_pipeline as ap
        # Use in-file SimpleRAG if available
        if hasattr(ap, 'SimpleRAG'):
            _simple_rag = ap.SimpleRAG()
            logging.info('Initialized SimpleRAG from agent_pipeline')
            return _simple_rag
        logging.warning('agent_pipeline does not expose SimpleRAG')
        return None
    except Exception as exc:
        logging.warning(f'Could not initialize SimpleRAG via agent_pipeline: {exc}')
        return None

@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(description="Document file to process"),
):
    """
    Upload a document file (.docx or .pptx) for processing.
    Returns a file ID that can be used to retrieve the processed results.
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
        
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".docx", ".pptx"]:
            raise HTTPException(status_code=400, detail="Only .docx and .pptx files are supported.")
        
        file_id = str(uuid4())
        save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
        
        # Initialize processing status
        processing_status[file_id] = {
            "status": "uploading",
            "progress": 0,
            "current_step": "Uploading file",
            "total_images": 0,
            "processed_images": 0,
            "error": None,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        # Save uploaded file
        try:
            with open(save_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
                processing_status[file_id].update({
                    "status": "processing",
                    "progress": 20,
                    "current_step": "Starting document analysis",
                    "updated_at": datetime.now().isoformat()
                })
        except Exception as e:
            processing_status[file_id].update({
                "status": "error",
                "error": str(e),
                "updated_at": datetime.now().isoformat()
            })
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        finally:
            await file.close()
            
        # Start background processing
        background_tasks.add_task(process_document, file_id, save_path, ext)
        return {"file_id": file_id, "filename": file.filename}
            
    except HTTPException:
        raise
    except Exception as e:
        if file_id in processing_status:
            processing_status[file_id].update({
                "status": "error",
                "error": str(e),
                "updated_at": datetime.now().isoformat()
            })
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

def process_document(file_id: str, save_path: str, ext: str):
    """Process document in background with status updates"""
    try:
        # Update status to processing
        processing_status[file_id].update({
            "current_step": "Extracting images and context",
            "progress": 30,
            "updated_at": datetime.now().isoformat()
        })
        # Prepare partial results directory so pipeline can write per-image outputs
        partial_dir = os.path.join(PROCESSED_DIR, file_id)
        images_partial_dir = os.path.join(partial_dir, "images")
        os.makedirs(images_partial_dir, exist_ok=True)

        # Determine RAG strategy from environment (none|rag|slide_focus)
        rag_strategy = os.environ.get('AGENT_RAG_STRATEGY', 'rag')

        # Run agent pipeline with progress callbacks and partial-save dir
        results = run_agent_pipeline(
            save_path,
            ext,
            progress_callback=lambda step, prog, total: update_processing_status(
                file_id, step, prog, total
            ),
            partial_save_dir=partial_dir,
            rag_strategy=rag_strategy
        )
        
        # Save results
        with open(os.path.join(PROCESSED_DIR, f"{file_id}.json"), "w", encoding="utf-8") as f:
            json.dump(results, f)
            
        # Update final status
        processing_status[file_id].update({
            "status": "completed",
            "progress": 100,
            "current_step": "Processing complete",
            "updated_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        processing_status[file_id].update({
            "status": "error",
            "error": str(e),
            "updated_at": datetime.now().isoformat()
        })
        # Clean up saved file if processing fails
        if os.path.exists(save_path):
            os.remove(save_path)

def update_processing_status(file_id: str, step: str, progress: int, total: int):
    """Update processing status for a file"""
    if file_id in processing_status:
        # Avoid overwriting a previously discovered total_images (e.g., temporary 1)
        current_total = processing_status[file_id].get("total_images", 0) or 0
        new_total = total
        if current_total > 1 and (not new_total or new_total <= 1):
            # keep the larger discovered total
            new_total = current_total

        processing_status[file_id].update({
            "current_step": step,
            "total_images": new_total,
            "processed_images": progress,
            "progress": 30 + (60 * (progress / max(new_total, 1))),
            "updated_at": datetime.now().isoformat()
        })
        
        # Log immediately for debugging
        print(f"Status update: {step} - {progress}/{new_total} images processed")
        logging.info(f"Status update: {step} - {progress}/{new_total} images processed")

@app.get("/status/{file_id}")
def get_status(file_id: str):
    """Get the processing status for a file"""
    if file_id not in processing_status:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=processing_status[file_id])

@app.get("/images/{file_id}")
def get_images(file_id: str):
    """Get processed images and their data for a file"""
    # First check if processing is complete
    if file_id in processing_status:
        status = processing_status[file_id]
        if status["status"] == "error":
            raise HTTPException(status_code=500, detail=status["error"])
        elif status["status"] != "completed":
            # Attempt to return any partial images written so far
            partial_dir = os.path.join(PROCESSED_DIR, file_id)
            images_dir = os.path.join(partial_dir, "images")
            partial_images = []
            if os.path.exists(images_dir):
                # load json files in sorted order
                files = sorted(glob.glob(os.path.join(images_dir, "*.json")))
                for fpath in files:
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            partial_images.append(json.load(fh))
                    except Exception:
                        continue

            return JSONResponse(content={
                "status": status["status"],
                "progress": status["progress"],
                "current_step": status["current_step"],
                "images": partial_images
            })
    
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="File not found.")
    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    return JSONResponse(content={
        "status": "completed",
        "progress": 100,
        "current_step": "Processing complete",
        "images": results
    })


@app.post('/rag/ingest')
def rag_ingest(docs: List[Dict[str, Any]]):
    """Ingest documents into the SimpleRAG instance for testing."""
    rag = get_simple_rag()
    if rag is None:
        raise HTTPException(status_code=503, detail='RAG pipeline not available')
    rag.ingest_documents(docs)
    return {'status': 'ingested', 'count': len(docs)}


@app.post('/rag/query')
def rag_query(query: Dict[str, Any]):
    rag = get_simple_rag()
    if rag is None:
        raise HTTPException(status_code=503, detail='RAG pipeline not available')
    q = query.get('query') or ''
    top_k = int(query.get('top_k', 4))
    hits = rag.retrieve(q, top_k=top_k)
    return {'query': q, 'hits': hits}

@app.post("/alt-text/{file_id}")
async def update_alt_text(
    file_id: str,
    data: Dict[str, Any] = Body(description="Updates to image alt texts")
):
    """
    Update alt text for processed images.
    The request body should contain image IDs mapped to their new alt texts.
    """
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    # Update alt text for images based on user input
    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    updates = data.get("updates", [])
    for i, update in enumerate(updates):
        if i < len(results):
            if "alt_text" in update:
                results[i]["alt_text"] = update["alt_text"]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f)
    return {"status": "success"}

@app.get("/download/{file_id}")
def download_file(file_id: str):
    import json
    ext = None
    for f in os.listdir(UPLOAD_DIR):
        if f.startswith(file_id):
            ext = os.path.splitext(f)[1]
            orig_path = os.path.join(UPLOAD_DIR, f)
            break
    if not ext:
        raise HTTPException(status_code=404, detail="File not found.")
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="No alt text data found.")
    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    # Write alt text back to file
    if ext == ".docx":
        from docx import Document
        doc = Document(orig_path)
        img_idx = 0
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref and img_idx < len(results):
                # Not all docx images have alt text, but we update if possible
                if hasattr(rel.target_part, "alt_text"):
                    rel.target_part.alt_text = results[img_idx]["alt_text"]
                img_idx += 1
        out_path = os.path.join(PROCESSED_DIR, f"remediated_{file_id}.docx")
        doc.save(out_path)
    elif ext == ".pptx":
        from pptx import Presentation
        pres = Presentation(orig_path)
        img_idx = 0
        for slide in pres.slides:
            for shape in slide.shapes:
                if shape.shape_type == 13 and img_idx < len(results):
                    shape._element._nvXxPr.cNvPr.set("descr", results[img_idx]["alt_text"])
                    img_idx += 1
        out_path = os.path.join(PROCESSED_DIR, f"remediated_{file_id}.pptx")
        pres.save(out_path)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    return FileResponse(out_path, filename=os.path.basename(out_path))
