import sys
import os
import shutil
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import subprocess

from docx import Document
from pptx import Presentation
from PIL import Image
import io
import logging
import time
import json
import re
from collections import Counter
import torch
import numpy as np
import gc
import concurrent.futures
import threading
import math
from typing import Optional
from src.config.gpu_config import get_gpu_settings
from src.models.vision_processor import get_model

# Corrected imports: Use the specific processor and the correct model class
from transformers import Idefics3Processor, AutoModelForVision2Seq
try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings
    LANGCHAIN_AVAILABLE = True
except ImportError:
    RecursiveCharacterTextSplitter, FAISS, HuggingFaceEmbeddings = None, None, None
    LANGCHAIN_AVAILABLE = False


# --- Inlined utilities ---

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64):
    if not text: return []
    if RecursiveCharacterTextSplitter:
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        return splitter.split_text(text)
    tokens = text.split(); chunks = []
    for i in range(0, len(tokens), chunk_size - overlap):
        chunks.append(" ".join(tokens[i:i + chunk_size]))
    return chunks

class LangChainRAG:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain components not installed.")
        self.embeddings = HuggingFaceEmbeddings(model_name=model_name)
        self.vector_store = None

    def add_documents(self, texts):
        if not texts: return
        self.vector_store = FAISS.from_texts(texts, self.embeddings)

    def search(self, query, top_k=3):
        if not self.vector_store: return []
        results = self.vector_store.similarity_search_with_score(query, k=top_k)
        return [{'text': doc.page_content, 'score': score} for doc, score in results]

class SimpleTextRAG:
    def __init__(self): self.chunks = []
    def add_documents(self, texts, metadatas=None): self.chunks.extend(texts)
    def search(self, query, top_k=4):
        if not self.chunks: return []
        query_words = set(query.lower().split())
        results = [{'text': chunk, 'score': len(query_words.intersection(set(chunk.lower().split())))} for chunk in self.chunks]
        results.sort(key=lambda x: x['score'], reverse=True)
        return [r for r in results if r['score'] > 0][:top_k]

from src.models.vision_processor import get_model

# Defaults and tunables
MAX_CHUNKS = int(os.environ.get("AGENT_MAX_CHUNKS", 1000))
DEFAULT_CHUNK_SIZE = int(os.environ.get("AGENT_CHUNK_SIZE", 512))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("AGENT_CHUNK_OVERLAP", 64))
DEFAULT_MAX_WORKERS = min(4, (os.cpu_count() or 1))

_rag_model_cache = None
_rag_lock = threading.Lock()
_results_lock = threading.Lock()
logger = logging.getLogger(__name__)

def preprocess_image(image_bytes, max_size=512):
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='JPEG', quality=90)
        return img_byte_arr.getvalue()
    except Exception as e:
        logger.error(f"Error preprocessing image: {e}")
        return image_bytes

def limit_chunks(texts, max_chunks=MAX_CHUNKS):
    if len(texts) > max_chunks:
        logger.warning(f"Limiting {len(texts)} chunks to {max_chunks}")
        return texts[:max_chunks]
    return texts

def _clear_hf_cache(log):
    """Directly removes the Hugging Face cache directory."""
    try:
        # Get the default cache path (usually ~/.cache/huggingface)
        cache_dir = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface')
        if os.path.exists(cache_dir):
            log.warning(f"Disk quota likely exceeded. Deleting cache directory: {cache_dir}")
            shutil.rmtree(cache_dir)
            log.info("Hugging Face cache directory successfully removed.")
        else:
            log.warning("Hugging Face cache directory not found, nothing to delete.")
    except Exception as e:
        log.error(f"Failed to clear Hugging Face cache automatically: {e}")


def get_rag_model(logger_instance=None):
    global _rag_model_cache
    with _rag_lock:
        if _rag_model_cache: return _rag_model_cache
        
        log = logger_instance or logger
        gpu_settings = get_gpu_settings()
        log.info(f"Using GPU settings: {gpu_settings}")

        hf_token = os.environ.get("HF_TOKEN")
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache")

        primary_model_id = "HuggingFaceTB/SmolVLM-Instruct"
        
        try:
            log.info(f"Attempting to load primary RAG model: {primary_model_id}")
            processor = Idefics3Processor.from_pretrained(primary_model_id, trust_remote_code=True, token=hf_token, cache_dir=cache_dir)
            
            # Use "eager" attention for compatibility
            model = AutoModelForVision2Seq.from_pretrained(
                primary_model_id,
                torch_dtype=gpu_settings["dtype"],
                attn_implementation="eager", # <--- This is the fix
                device_map="auto",
                trust_remote_code=True,
                token=hf_token,
                cache_dir=cache_dir
            )
            model.tie_weights() # Added to resolve the "weights are not tied" warning

            log.info(f"Successfully loaded primary RAG pipeline with {primary_model_id}.")
            _rag_model_cache = { "model": model, "processor": processor, "text_rag": LangChainRAG() if LANGCHAIN_AVAILABLE else SimpleTextRAG(), "type": "vision_model" }
            return _rag_model_cache

        except Exception as e:
            log.error(f"Failed to load primary model {primary_model_id}: {e}")
            _rag_model_cache = { "model": None, "processor": None, "text_rag": SimpleTextRAG(), "type": "simple"}
            return _rag_model_cache

def extract_document_metadata(file_path, ext):
    all_text, headings = [], []
    if ext == ".docx":
        doc = Document(file_path)
        for para in doc.paragraphs:
            if para.text.strip():
                all_text.append(para.text.strip())
                if para.style.name.startswith("Heading"): headings.append(para.text.strip())
    elif ext == ".pptx":
        pres = Presentation(file_path)
        for i, slide in enumerate(pres.slides, 1):
            slide_texts = [shp.text for shp in slide.shapes if hasattr(shp, "text") and shp.text.strip()]
            if slide_texts:
                all_text.extend(slide_texts)
                headings.append(f"Slide {i}: {slide_texts[0][:50]}...")

    full_text = "\n".join(all_text)
    texts = chunk_text(full_text)
    texts = limit_chunks(texts)
    rag_system = get_rag_model()
    if rag_system and rag_system.get("text_rag"):
        rag_system["text_rag"].add_documents(texts)
    return {"rag_system": rag_system}

def retrieve_context(rag_system, query, k=2):
    if not rag_system or not rag_system.get("text_rag"): return ""
    try:
        results = rag_system["text_rag"].search(query, top_k=k)
        return "\n".join([r['text'] for r in results])
    except Exception as e:
        logger.warning(f"Text retrieval failed: {e}")
        return ""

def classify_and_generate_alt_text(image_bytes, context_text="", rag_system=None):
    logger.info(f"Generating alt text with RAG type: {rag_system.get('type', 'none') if rag_system else 'none'}")
    processed_image = preprocess_image(image_bytes)
    try:
        if rag_system and rag_system.get("model") and rag_system["type"] == "vision_model":
            model, processor = rag_system["model"], rag_system["processor"]
            rag_context = retrieve_context(rag_system, context_text)
            
            messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": f"Based on the context '{rag_context}', provide a concise, accessible alt text for this image."}]}]
            prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = processor(text=prompt, images=Image.open(io.BytesIO(processed_image)), return_tensors="pt").to(model.device)

            with torch.inference_mode():
                output = model.generate(**inputs, max_new_tokens=100)
            
            # FIX: Correctly slice the output to get only the generated text
            output_ids = output[0][len(inputs["input_ids"][0]):]
            alt_text = processor.decode(output_ids, skip_special_tokens=True).strip()

            categories = ["Other"]
            if any(w in alt_text.lower() for w in ["chart", "graph"]): categories = ["Chart"]
            elif "diagram" in alt_text.lower(): categories = ["Diagram"]
            elif "photo" in alt_text.lower(): categories = ["Photograph"]
            return categories, alt_text

        logger.warning("Falling back to smaller vision model (SmolVLM-256M-Instruct).")
        vision_model = get_model() # This is now the smaller fallback
        if vision_model and vision_model.get("model"):
            from src.models.vision_processor import process_image as process_fallback_image
            return ["Other"], process_fallback_image(processed_image, "Generate a short alt text.")
        
        logger.error("All vision models failed to load.")
        return ["Other"], "Image could not be processed."
    except Exception as e:
        logger.error(f"Error in alt text generation: {e}", exc_info=True)
        return ["Other"], "Error generating alt text."
    finally:
        gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()

def run_agent_pipeline(file_path, ext, progress_callback=None, partial_save_dir=None, **kwargs):
    pipeline_start = time.time()
    logger.info(f"Starting pipeline for {file_path}")
    meta = extract_document_metadata(file_path, ext)
    rag_system = meta.get("rag_system")
    image_tasks = []
    if ext == ".pptx":
        pres = Presentation(file_path)
        for slide_num, slide in enumerate(pres.slides, 1):
            slide_text = " ".join([shp.text for shp in slide.shapes if hasattr(shp, "text")])
            for shape in slide.shapes:
                if getattr(shape, "shape_type", None) == 13:
                    image_tasks.append({"bytes": shape.image.blob, "alt": shape._element._nvXxPr.cNvPr.attrib.get("descr", ""),"context": slide_text, "slide_num": slide_num})
    elif ext == ".docx":
        doc = Document(file_path)
        full_text = "\n".join([p.text for p in doc.paragraphs])
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                image_tasks.append({"bytes": rel.target_part.blob, "alt": "", "context": full_text, "slide_num": None})

    total_images = len(image_tasks)
    if not total_images: return []
    processed_count = 0; results = []
    def process_single_image(task_idx, task):
        nonlocal processed_count
        try:
            categories, alt_text = classify_and_generate_alt_text(task["bytes"], task["context"], rag_system)
            with _results_lock:
                processed_count += 1
                if progress_callback: progress_callback(f"Processing image {processed_count}/{total_images}", processed_count, total_images)
            import base64
            b64_image = base64.b64encode(task['bytes']).decode('utf-8')
            return {
                "classification": categories,
                "alt_text": task["alt"],  # This will be the original alt text
                "generated_alt_text": alt_text or task["alt"] or f"Image {task_idx + 1}", # The newly generated text
                "image_idx": task_idx + 1,
                "slide_num": task.get("slide_num"),
                "image_data": f"data:image/jpeg;base64,{b64_image}"
            }
        except Exception as e:
            logger.error(f"Error processing image {task_idx+1}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=DEFAULT_MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_image, i, task) for i, task in enumerate(image_tasks)]
        results = [future.result() for future in concurrent.futures.as_completed(futures) if future.result()]
    
    if progress_callback: progress_callback("Processing complete", total_images, total_images)
    logger.info(f"Pipeline finished in {time.time() - pipeline_start:.2f}s")
    return sorted(results, key=lambda x: x['image_idx'])