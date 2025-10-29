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

# --- START MODIFICATION: Import config paths ---
from src.config.app_config import UPLOAD_DIR, PROCESSED_DIR, REMEDIATED_DIR, CUSTOM_CACHE_DIR
# --- END MODIFICATION ---

# --- START MODIFICATION: Import pptx/docx classes ---
from docx import Document
from pptx import Presentation
from docx.oxml.ns import qn
from pptx.shapes.picture import Picture as PptxPicture
# --- END MODIFICATION ---

app = FastAPI()

@app.on_event("startup")
def startup_event():
    """Check disk space on startup."""
    try:
        threshold_gb = 15.0
        cache_dir = CUSTOM_CACHE_DIR
        logging.warning(f"Using custom cache directory for disk space check: {cache_dir}")
        if os.path.exists(cache_dir):
            total, used, free = shutil.disk_usage(str(cache_dir))
            free_gb = free / (1024**3)
            logging.warning(f"Checking Hugging Face cache disk space: {free_gb:.2f} GB free.")
            if free_gb < threshold_gb:
                logging.warning(f"Free space below {threshold_gb} GB. Clearing cache...")
                shutil.rmtree(cache_dir)
                logging.warning("Cache cleared.")
                os.makedirs(cache_dir, exist_ok=True)
        else:
            logging.warning(f"Cache directory not found: {cache_dir}. Skipping check.")
    except Exception as e:
        logging.error(f"Error during startup cache check: {e}")

load_dotenv()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

processing_status = {}

def _resolve_agent_pipeline():
    # (function remains the same)
    try:
        mod = importlib.import_module("src.pipelines.agent_pipeline")
        logging.info("Using agent_pipeline implementation")
        return mod.run_agent_pipeline
    except Exception as exc:
        logging.error(f"Failed to import pipelines.agent_pipeline as agent_pipeline module: {exc}")
        raise

run_agent_pipeline = _resolve_agent_pipeline()

_simple_rag = None
def get_simple_rag():
    # (function remains the same)
    global _simple_rag
    if _simple_rag is not None: return _simple_rag
    try:
        import src.pipelines.agent_pipeline as ap
        if hasattr(ap, 'SimpleRAG'):
            _simple_rag = ap.SimpleRAG(); logging.info('Initialized SimpleRAG from agent_pipeline')
            return _simple_rag
        logging.warning('agent_pipeline does not expose SimpleRAG'); return None
    except Exception as exc: logging.warning(f'Could not initialize SimpleRAG via agent_pipeline: {exc}'); return None

@app.post("/upload")
async def upload_file( background_tasks: BackgroundTasks, file: UploadFile = File(description="Document file to process"), ):
    # (function remains the same)
    if not file: raise HTTPException(status_code=400, detail="No file uploaded")
    file_id = None
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".docx", ".pptx"]: raise HTTPException(status_code=400, detail="Only .docx and .pptx files are supported.")
        file_id = str(uuid4()); save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
        processing_status[file_id] = {"status": "uploading", "progress": 0, "current_step": "Uploading file",
                                      "total_images": 0, "processed_images": 0, "error": None,
                                      "started_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
                                      "filename": file.filename # Store original filename
                                     }
        try:
            with open(save_path, "wb") as buffer: content = await file.read(); buffer.write(content)
            processing_status[file_id].update({"status": "processing", "progress": 20, "current_step": "Starting analysis",
                                               "updated_at": datetime.now().isoformat()})
        except Exception as e:
            processing_status[file_id].update({"status": "error", "error": str(e), "updated_at": datetime.now().isoformat()})
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        finally: await file.close()
        background_tasks.add_task(process_document, file_id, save_path, ext)
        return {"file_id": file_id, "filename": file.filename}
    except HTTPException: raise
    except Exception as e:
        if file_id and file_id in processing_status:
            processing_status[file_id].update({"status": "error", "error": str(e), "updated_at": datetime.now().isoformat()})
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

def process_document(file_id: str, save_path: str, ext: str):
    # (function remains the same)
    try:
        processing_status[file_id].update({"current_step": "Extracting images/context", "progress": 30, "updated_at": datetime.now().isoformat()})
        partial_dir = os.path.join(PROCESSED_DIR, file_id); images_partial_dir = os.path.join(partial_dir, "images")
        os.makedirs(images_partial_dir, exist_ok=True)
        rag_strategy = os.environ.get('AGENT_RAG_STRATEGY', 'rag')
        results = run_agent_pipeline( save_path, ext,
            progress_callback=lambda step, prog, total: update_processing_status(file_id, step, prog, total),
            partial_save_dir=partial_dir, rag_strategy=rag_strategy )
        with open(os.path.join(PROCESSED_DIR, f"{file_id}.json"), "w", encoding="utf-8") as f: json.dump(results, f)
        processing_status[file_id].update({"status": "completed", "progress": 100, "current_step": "Processing complete",
                                           "updated_at": datetime.now().isoformat()})
    except Exception as e:
        logging.exception(f"Error in process_document for file_id {file_id}")
        processing_status[file_id].update({"status": "error", "error": str(e), "updated_at": datetime.now().isoformat()})
        if os.path.exists(save_path): os.remove(save_path)

def update_processing_status(file_id: str, step: str, progress: int, total: int):
    # (function remains the same)
    if file_id in processing_status:
        current_total = processing_status[file_id].get("total_images", 0) or 0; new_total = total
        if current_total > 1 and (not new_total or new_total <= 1): new_total = current_total
        processing_status[file_id].update({"current_step": step, "total_images": new_total, "processed_images": progress,
                                           "progress": min(100, 30 + (60 * (progress / max(new_total, 1)))),
                                           "updated_at": datetime.now().isoformat()})
        print(f"Status update: {step} - {progress}/{new_total} images processed")
        # logging.info(f"Status update: {step} - {progress}/{new_total} images processed") # Reduce log noise


@app.get("/status/{file_id}")
def get_status(file_id: str):
    # (function remains the same)
    if file_id not in processing_status: raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=processing_status[file_id])

@app.get("/images/{file_id}")
def get_images(file_id: str):
    # (function remains the same)
    if file_id in processing_status:
        status = processing_status[file_id]
        if status["status"] == "error": raise HTTPException(status_code=500, detail=status["error"])
        elif status["status"] != "completed":
            partial_dir = os.path.join(PROCESSED_DIR, file_id); images_dir = os.path.join(partial_dir, "images")
            partial_images = []
            if os.path.exists(images_dir):
                files = sorted(glob.glob(os.path.join(images_dir, "*.json")))
                for fpath in files:
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh: partial_images.append(json.load(fh))
                    except Exception: continue
            return JSONResponse(content={"status": status["status"], "progress": status["progress"],
                                         "current_step": status["current_step"], "images": partial_images})
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="File not found.")
    with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    return JSONResponse(content={"status": "completed", "progress": 100, "current_step": "Processing complete",
                                 "images": results})

@app.post('/rag/ingest')
def rag_ingest(docs: List[Dict[str, Any]]):
    # (function remains the same)
    rag = get_simple_rag();
    if rag is None: raise HTTPException(status_code=503, detail='RAG pipeline not available')
    rag.ingest_documents(docs); return {'status': 'ingested', 'count': len(docs)}

@app.post('/rag/query')
def rag_query(query: Dict[str, Any]):
    # (function remains the same)
    rag = get_simple_rag();
    if rag is None: raise HTTPException(status_code=503, detail='RAG pipeline not available')
    q = query.get('query') or ''; top_k = int(query.get('top_k', 4)); hits = rag.retrieve(q, top_k=top_k)
    return {'query': q, 'hits': hits}

@app.post("/alt-text/{file_id}")
async def update_alt_text( file_id: str, data: Dict[str, Any] = Body(description="Updates to image alt texts") ):
    # (function remains the same)
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="File not found")
    with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    updates = data.get("updates", []); updated_count = 0
    if len(updates) != len(results): logging.warning(f"Update/results count mismatch ({len(updates)} vs {len(results)}).")
    for i, update_data in enumerate(updates):
        if i < len(results):
            if "alt_text" in update_data: results[i]["final_alt_text"] = update_data["alt_text"]; updated_count += 1
            elif "final_alt_text" not in results[i]: results[i]["final_alt_text"] = results[i].get("generated_alt_text", "")
    with open(json_path, "w", encoding="utf-8") as f: json.dump(results, f)
    return {"status": "success", "updated_count": updated_count}

@app.get("/download/{file_id}")
def download_file(file_id: str):
    """Applies final alt text and returns the remediated file."""
    ext = None; orig_path = None; orig_filename = None
    # Find original file
    for f in os.listdir(UPLOAD_DIR):
        if f.startswith(file_id):
            ext = os.path.splitext(f)[1]; orig_path = os.path.join(UPLOAD_DIR, f)
            orig_filename = processing_status.get(file_id, {}).get("filename", f"remediated_{file_id}{ext}")
            break
    if not ext or not orig_path: raise HTTPException(status_code=404, detail="Original uploaded file not found.")

    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="Alt text data not found.")
    with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    if not results: raise HTTPException(status_code=404, detail="Alt text data is empty.")

    out_path = os.path.join(REMEDIATED_DIR, f"remediated_{file_id}{ext}")

    try:
        if ext == ".docx":
            doc = Document(orig_path); shapes_processed = 0
            # --- START MODIFICATION: Iterate inline shapes for writing ---
            for shape in doc.part.inline_shapes:
                 if hasattr(shape, 'type') and shape.type == 3: # WD_INLINE_SHAPE.PICTURE
                    if shapes_processed < len(results):
                        final_alt_text = results[shapes_processed].get("final_alt_text", results[shapes_processed].get("generated_alt_text", ""))
                        try:
                            # Access the underlying CT_Inline element's docPr
                            docPr = shape._inline.find(qn('wp:docPr'))
                            if docPr is not None:
                                docPr.set('descr', final_alt_text) # Set the 'descr' attribute
                            else: # If docPr doesn't exist, need to create it (more complex)
                                 logger.warning(f"Cannot set alt text: wp:docPr element not found for inline shape {shapes_processed+1}")
                        except Exception as alt_e: logger.warning(f"Error setting docPr descr for inline shape {shapes_processed+1}: {alt_e}")
                        shapes_processed += 1
                    else: break # Stop if we run out of results
            if shapes_processed != len(results): logger.warning(f"DOCX Write Mismatch: Found {shapes_processed} shapes, have {len(results)} results.")
            # --- END MODIFICATION ---
            doc.save(out_path)

        elif ext == ".pptx":
            pres = Presentation(orig_path); shapes_processed = 0
            for slide in pres.slides:
                for shape in slide.shapes:
                    # --- START MODIFICATION: Use XML access to SET alt text ---
                    if isinstance(shape, PptxPicture):
                         if shapes_processed < len(results):
                            final_alt_text = results[shapes_processed].get("final_alt_text", results[shapes_processed].get("generated_alt_text", ""))
                            try:
                                # Navigate the XML tree to find cNvPr and set 'descr'
                                nvPr = getattr(getattr(getattr(shape, '_element', None), 'nvPicPr', None), 'cNvPr', None)
                                if nvPr is not None:
                                    nvPr.attrib['descr'] = final_alt_text # Set the attribute directly
                                else:
                                     logger.warning(f"Cannot set alt text: cNvPr element not found for picture shape {shapes_processed+1} on slide {slide.slide_id}")
                            except Exception as alt_e:
                                 logger.warning(f"Error setting descr attribute for picture shape {shapes_processed+1}: {alt_e}")
                            shapes_processed += 1
                         else: break # Stop if we run out of results
                if shapes_processed >= len(results): break # Stop iterating slides if all images done
            if shapes_processed != len(results): logger.warning(f"PPTX Write Mismatch: Found {shapes_processed} shapes, have {len(results)} results.")
            # --- END MODIFICATION ---
            pres.save(out_path)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type.")

    except Exception as e:
         logger.error(f"Failed to remediate and save file {file_id}: {e}", exc_info=True)
         raise HTTPException(status_code=500, detail=f"Failed to write remediated file: {e}")

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        logger.error(f"Failed to save file or file is 0 bytes: {out_path}")
        raise HTTPException(status_code=500, detail="Failed to save remediated file (0 bytes).")

    return FileResponse(out_path, filename=f"remediated_{orig_filename}")

