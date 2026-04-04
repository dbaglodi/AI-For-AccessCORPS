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
from pydantic import BaseModel

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

class RegenerateRequest(BaseModel):
    image_idx: int
    forced_pipeline: str
    slide_num: Optional[int] = None
    rId: Optional[str] = None

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

# --- START MODIFICATION: Expose Content-Disposition Header ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend's origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"] # Allow frontend to read this header
)
# --- END MODIFICATION ---

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
        # Use logging instead of print for status updates if desired
        # logging.info(f"Status update: {step} - {progress}/{new_total} images processed")


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
                # Ensure correct sorting if filenames are like 0.json, 1.json, ... 10.json
                files = sorted(glob.glob(os.path.join(images_dir, "*.json")), key=lambda x: int(os.path.basename(x).split('.')[0]))
                for fpath in files:
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh: partial_images.append(json.load(fh))
                    except Exception as e:
                         logging.warning(f"Failed to load partial image data from {fpath}: {e}")
                         continue
            return JSONResponse(content={"status": status["status"], "progress": status["progress"],
                                         "current_step": status["current_step"], "images": partial_images})
    json_path = os.path.join(PROCESSED_DIR, f"{file_id}.json")
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="File processing data not found.")
    try:
        with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    except Exception as e:
        logging.error(f"Failed to read processed data for {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read processing results.")
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
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="File processing data not found")
    try:
        with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    except Exception as e:
        logging.error(f"Failed to read processed data for update {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read processing results.")

    updates = data.get("updates", []); updated_count = 0
    if len(updates) != len(results):
         logging.warning(f"Update/results count mismatch for {file_id} ({len(updates)} vs {len(results)}). Proceeding cautiously.")

    for i, update_data in enumerate(updates):
        if i < len(results):
            # Use the user-provided text if available, otherwise keep the generated one
            final_text = update_data.get("alt_text") # Assuming frontend sends edited text in 'alt_text'
            if final_text is not None: # Check if the key exists, even if the value is empty string
                results[i]["final_alt_text"] = final_text
                updated_count += 1
            elif "final_alt_text" not in results[i]: # If user didn't edit AND it wasn't set before
                results[i]["final_alt_text"] = results[i].get("generated_alt_text", "") # Default to generated

    try:
        with open(json_path, "w", encoding="utf-8") as f: json.dump(results, f)
    except Exception as e:
        logging.error(f"Failed to write updated data for {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save alt text updates.")

    return {"status": "success", "updated_count": updated_count}

@app.post("/api/regenerate-image/{file_id}")
async def regenerate_image(file_id: str, req: RegenerateRequest):
    """
    Forces the pipeline to re-run for a specific image using a manually selected category.
    """
    try:
        # 1. Find the original file
        orig_filename = processing_status.get(file_id, {}).get("filename", "")
        ext = os.path.splitext(orig_filename)[1].lower() if orig_filename else None
        
        orig_path = UPLOAD_DIR / f"{file_id}{ext}"
        if not orig_path.exists():
            # Fallback to glob
            found_files = list(UPLOAD_DIR.glob(f"{file_id}.*"))
            if not found_files:
                raise HTTPException(status_code=404, detail="Original file not found.")
            orig_path = found_files[0]
            ext = orig_path.suffix.lower()

        # 2. Extract the specific image bytes
        image_bytes = None
        target_shape = None
        doc = None
        pres = None
        
        if ext == ".pptx":
            pres = Presentation(orig_path)
            images = []
            for s_num, slide in enumerate(pres.slides, 1):
                for shape in slide.shapes:
                    if isinstance(shape, PptxPicture):
                        images.append((s_num, shape))
            if 1 <= req.image_idx <= len(images):
                target_shape = images[req.image_idx - 1][1]
                image_bytes = target_shape.image.blob
            else:
                raise HTTPException(status_code=404, detail="Image index out of bounds in PPTX.")
                
        elif ext == ".docx":
            doc = Document(orig_path)
            inline_shapes = list(doc.part.inline_shapes)
            if 1 <= req.image_idx <= len(inline_shapes):
                target_shape = inline_shapes[req.image_idx - 1]
                # Look up the image part by relationship ID
                rId = target_shape._inline.graphic.graphicData.pic.blipFill.blip.embed
                rel = doc.part.rels[rId]
                image_bytes = rel.target_part.blob
            else:
                raise HTTPException(status_code=404, detail="Image index out of bounds in DOCX.")

        # 3. Route to the correct pipeline
        from src.pipelines.agent_pipeline import classify_and_generate_alt_text, get_primary_model, get_context_for_image_docx, get_context_for_image_pptx
        from docx.oxml.ns import qn
        
        # ALWAYS run the visual model first to get the descriptive alt text
        primary_model = get_primary_model()
        if ext == ".docx":
            ctx = get_context_for_image_docx(doc, target_shape._inline)
        else:
            slide_target = pres.slides[req.slide_num - 1] if req.slide_num else pres.slides[images[req.image_idx-1][0]-1]
            ctx = get_context_for_image_pptx(slide_target, target_shape)
            
        # Run generation forcing the user's selected pipeline tag
        _, gen_alt, _ = classify_and_generate_alt_text(image_bytes, ctx, primary_model, ext, "", None, req.image_idx-1)
        new_alt_text = gen_alt
        doc_modified = False

        # Apply the new alt text to the original image immediately
        if ext == ".docx":
            target_shape._inline.find(qn('wp:docPr')).set('descr', new_alt_text)
            doc_modified = True
        elif ext == ".pptx":
            target_shape._element.nvPicPr.cNvPr.set('descr', new_alt_text)
            doc_modified = True

        # Now handle extra extractions (Table/Equation)
        if req.forced_pipeline == "Equation":
            from src.pipelines.equation_pipeline import extract_equations_from_image, insert_equation_into_docx
            equations = extract_equations_from_image(image_bytes)
            if equations and ext == ".docx":
                insert_equation_into_docx(doc, target_shape._inline, equations)
                doc_modified = True

        elif req.forced_pipeline == "Table":
            from src.pipelines.table_pipeline import extract_table_from_image, insert_table_into_docx, insert_table_into_pptx
            table_data = extract_table_from_image(image_bytes)
            if table_data:
                if ext == ".docx":
                    # Pass the generated alt text to the table
                    insert_table_into_docx(doc, target_shape._inline, table_data, alt_text=new_alt_text)
                    doc_modified = True
                elif ext == ".pptx":
                    slide_target = pres.slides[req.slide_num - 1] if req.slide_num else pres.slides[images[req.image_idx-1][0]-1]
                    # Pass the generated alt text to the table
                    insert_table_into_pptx(slide_target, target_shape, table_data, alt_text=new_alt_text)
                    doc_modified = True
            else:
                new_alt_text = "Failed to extract table."

        else:
            # Re-run standard vision pipeline for standard classifications (Graph, Diagram, etc.)
            from src.pipelines.agent_pipeline import classify_and_generate_alt_text, get_primary_model, get_context_for_image_docx, get_context_for_image_pptx
            primary_model = get_primary_model()
            if ext == ".docx":
                ctx = get_context_for_image_docx(doc, target_shape._inline)
            else:
                slide_target = pres.slides[req.slide_num - 1] if req.slide_num else pres.slides[images[req.image_idx-1][0]-1]
                ctx = get_context_for_image_pptx(slide_target, target_shape)
                
            # Force the categories list to start with the user's selected category
            forced_cats = [req.forced_pipeline]
            _, gen_alt, _ = classify_and_generate_alt_text(image_bytes, ctx, primary_model, ext, "", None, req.image_idx-1)
            new_alt_text = gen_alt

        # 4. Save document modifications (if equations/tables were inserted)
        if doc_modified:
            if ext == ".docx":
                doc.save(orig_path)
            elif ext == ".pptx":
                pres.save(orig_path)

        # 5. Update the JSON processing cache so the frontend stays synced
        json_path = PROCESSED_DIR / f"{file_id}.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                results = json.load(f)
                
            # Find the target image in the results array
            for res in results:
                if res.get("image_idx") == req.image_idx:
                    # Update classification order and the generated text
                    if req.forced_pipeline in res["classification"]:
                        res["classification"].remove(req.forced_pipeline)
                    res["classification"].insert(0, req.forced_pipeline)
                    
                    res["generated_alt_text"] = new_alt_text
                    res["final_alt_text"] = new_alt_text # Overwrite final alt text as well
                    break
                    
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(results, f)

        return {"status": "success", "new_alt_text": new_alt_text, "pipeline_used": req.forced_pipeline}

    except Exception as e:
        logging.error(f"Failed to regenerate image {req.image_idx} for {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{file_id}")
def download_file(file_id: str):
    """Applies final alt text and returns the remediated file."""
    ext = None; orig_path = None; orig_filename = "unknown_file"
    # Find original file and original filename
    try:
        if file_id in processing_status and "filename" in processing_status[file_id]:
            orig_filename = processing_status[file_id]["filename"]
            potential_ext = os.path.splitext(orig_filename)[1].lower()
            if potential_ext in [".docx", ".pptx"]:
                ext = potential_ext
                orig_path_check = UPLOAD_DIR / f"{file_id}{ext}"
                if orig_path_check.exists():
                    orig_path = orig_path_check
                else: # Fallback to glob if status filename is wrong/file renamed
                     logging.warning(f"Original file path from status not found ({orig_path_check}), trying glob.")
                     found_files = list(UPLOAD_DIR.glob(f"{file_id}.*"))
                     if found_files:
                         orig_path = found_files[0]
                         ext = orig_path.suffix.lower()
                         logging.warning(f"Found original file via glob: {orig_path}")
                     else:
                          raise HTTPException(status_code=404, detail="Original uploaded file not found in upload directory.")
            else:
                 raise HTTPException(status_code=400, detail="Invalid extension in processing status.")
        else: # Fallback to glob if file_id not in status or filename missing
            logging.warning(f"File ID {file_id} not found in status or filename missing, trying glob.")
            found_files = list(UPLOAD_DIR.glob(f"{file_id}.*"))
            if found_files:
                orig_path = found_files[0]
                ext = orig_path.suffix.lower()
                orig_filename = orig_path.name # Use actual found filename
                logging.warning(f"Found original file via glob: {orig_path}")
            else:
                 raise HTTPException(status_code=404, detail="Original uploaded file not found.")

        if ext not in [".docx", ".pptx"]:
             raise HTTPException(status_code=400, detail=f"Unsupported file type determined: {ext}")

    except Exception as e:
        logging.error(f"Error finding original file for {file_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error finding original file: {e}")

    json_path = PROCESSED_DIR / f"{file_id}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Alt text processing data not found.")

    try:
        with open(json_path, "r", encoding="utf-8") as f: results = json.load(f)
    except Exception as e:
        logging.error(f"Error reading alt text data for {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading alt text data.")

    if not results:
        logging.warning(f"Alt text data for {file_id} is empty.")
        # Decide if you want to allow downloading the original or raise error
        # return FileResponse(orig_path, filename=f"original_{orig_filename}")
        raise HTTPException(status_code=404, detail="Alt text data is empty, cannot remediate.")

    out_path = REMEDIATED_DIR / f"remediated_{file_id}{ext}"
    safe_orig_filename = "".join(c for c in orig_filename if c.isalnum() or c in (' ', '.', '_')).rstrip()
    download_filename = f"remediated_{safe_orig_filename}"

    try:
        logging.info(f"Applying alt text to {orig_path} -> {out_path}")
        if ext == ".docx":
            doc = Document(orig_path); shapes_processed = 0; image_index_map = {}
            # Build a map of relationship IDs to their index in the results
            for idx, res in enumerate(results):
                rId = res.get("rId") # Assuming rId was stored during extraction
                if rId: image_index_map[rId] = idx

            inline_shape_count = 0
            for shape in doc.part.inline_shapes:
                 if hasattr(shape, 'type') and shape.type == 3: # WD_INLINE_SHAPE.PICTURE
                    inline_shape_count += 1
                    current_rId = None
                    try: current_rId = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
                    except AttributeError: continue # Skip if structure is unexpected

                    result_idx = image_index_map.get(current_rId) # Look up by rId if possible
                    # Fallback to sequential index if rId mapping failed or wasn't stored
                    if result_idx is None:
                         if shapes_processed < len(results): result_idx = shapes_processed
                         else:
                              logging.warning(f"Could not find matching result for DOCX shape {inline_shape_count} (rId: {current_rId}). Skipping.")
                              continue

                    final_alt_text = results[result_idx].get("final_alt_text", results[result_idx].get("generated_alt_text", ""))
                    try:
                        docPr = shape._inline.xpath('.//wp:docPr')[0] # Use xpath to find docPr reliably
                        docPr.set('descr', final_alt_text)
                        logging.debug(f"Set alt text for DOCX shape {inline_shape_count} (rId: {current_rId}): '{final_alt_text[:30]}...'")
                    except IndexError: logging.warning(f"Cannot set alt text: wp:docPr element not found via xpath for inline shape {inline_shape_count}")
                    except Exception as alt_e: logging.warning(f"Error setting docPr descr for inline shape {inline_shape_count}: {alt_e}")
                    shapes_processed += 1 # Increment only when alt text is attempted

            if shapes_processed != len(results):
                 logging.warning(f"DOCX Write Mismatch: Attempted to set alt text for {shapes_processed} shapes, but have {len(results)} results.")
            doc.save(out_path)

        elif ext == ".pptx":
            pres = Presentation(orig_path); shapes_processed = 0
            for slide_idx, slide in enumerate(pres.slides):
                for shape_idx, shape in enumerate(slide.shapes):
                    if isinstance(shape, PptxPicture):
                         if shapes_processed < len(results):
                            final_alt_text = results[shapes_processed].get("final_alt_text", results[shapes_processed].get("generated_alt_text", ""))
                            try:
                                nvPr = shape._element.nvPicPr.cNvPr # More direct access
                                nvPr.set('descr', final_alt_text)
                                logging.debug(f"Set alt text for PPTX shape {shapes_processed+1} on slide {slide_idx+1}: '{final_alt_text[:30]}...'")
                            except AttributeError: logging.warning(f"Cannot set alt text: cNvPr element not found for picture shape {shapes_processed+1}")
                            except Exception as alt_e: logger.warning(f"Error setting descr attribute for picture shape {shapes_processed+1}: {alt_e}")
                            shapes_processed += 1
                         else: break # Stop inner loop
                if shapes_processed >= len(results): break # Stop outer loop
            if shapes_processed != len(results):
                 logging.warning(f"PPTX Write Mismatch: Set alt text for {shapes_processed} shapes, but have {len(results)} results.")
            pres.save(out_path)
        else:
            raise HTTPException(status_code=400, detail="Internal error: Unsupported file type during download.")

    except Exception as e:
         logging.exception(f"Failed to remediate and save file {file_id}: {e}") # Log full traceback
         raise HTTPException(status_code=500, detail=f"Failed to write remediated file: {str(e)}")

    if not out_path.exists() or out_path.stat().st_size == 0:
        logging.error(f"Failed to save file or file is 0 bytes: {out_path}")
        # Consider returning the original file as a fallback?
        # return FileResponse(orig_path, filename=f"original_{orig_filename}", headers={"Content-Disposition": f"attachment; filename*=UTF-8''original_{orig_filename}"})
        raise HTTPException(status_code=500, detail="Failed to save remediated file (0 bytes).")

    logging.info(f"Successfully remediated {file_id}, serving {out_path} as {download_filename}")
    return FileResponse(
        out_path,
        filename=download_filename,
        # Ensure Content-Disposition is set correctly for FileResponse
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{download_filename}"}
    )


if __name__ == "__main__":
    import uvicorn
    # --- START MODIFICATION: Ensure necessary directories exist before starting ---
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REMEDIATED_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # --- END MODIFICATION ---

    logging.basicConfig(level=logging.INFO)
    logging.info(f"Starting server... Uploads: {UPLOAD_DIR}, Processed: {PROCESSED_DIR}, Remediated: {REMEDIATED_DIR}, Cache: {CUSTOM_CACHE_DIR}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
