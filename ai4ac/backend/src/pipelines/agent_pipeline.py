import sys
import os
import shutil
# --- START MODIFICATION: Adjust path for potential structure changes ---
# Assuming src is one level up from pipelines directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# --- END MODIFICATION ---
import subprocess
from pathlib import Path

from docx import Document
# --- START MODIFICATION: Import specific elements for context extraction ---
from docx.text.paragraph import Paragraph
from docx.oxml.shape import CT_Inline # For finding inline shapes
from docx.oxml.ns import nsdecls, qn # Namespace declarations and qualified name helper
# --- END MODIFICATION ---
from pptx import Presentation
from pptx.slide import Slide as PptxSlide # Type hinting
from pptx.shapes.autoshape import Shape as PptxShape
from pptx.shapes.picture import Picture as PptxPicture
# --- END MODIFICATION ---
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
from typing import Optional, Dict, Any, List, Tuple
from src.config.gpu_config import get_gpu_settings
# --- START MODIFICATION: Directly use get_fallback_model (renamed) ---
from src.models.vision_processor import get_model as get_fallback_model # Keep fallback separate
# --- END MODIFICATION ---
from src.config.app_config import CUSTOM_CACHE_DIR

# --- START MODIFICATION: Import specific classes for PaliGemma ---
from transformers import AutoProcessor, PaliGemmaProcessor, PaliGemmaForConditionalGeneration
# --- END MODIFICATION ---

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
    # (remains the same)
    if not text: return []
    if RecursiveCharacterTextSplitter:
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        return splitter.split_text(text)
    tokens = text.split(); chunks = []
    for i in range(0, len(tokens), chunk_size - overlap):
        chunks.append(" ".join(tokens[i:i + chunk_size]))
    return chunks

class LangChainRAG:
    # (remains the same)
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain components not installed.")
        emb_cache_folder = os.path.join(CUSTOM_CACHE_DIR, 'sentence-transformers')
        self.embeddings = HuggingFaceEmbeddings(model_name=model_name, cache_folder=emb_cache_folder)
        self.vector_store = None
    def add_documents(self, texts):
        if not texts: return
        self.vector_store = FAISS.from_texts(texts, self.embeddings)
    def search(self, query, top_k=3):
        if not self.vector_store: return []
        results = self.vector_store.similarity_search_with_score(query, k=top_k)
        return [{'text': doc.page_content, 'score': score} for doc, score in results]

class SimpleTextRAG:
    # (remains the same)
    def __init__(self): self.chunks = []
    def add_documents(self, texts, metadatas=None): self.chunks.extend(texts)
    def search(self, query, top_k=4):
        if not self.chunks: return []
        query_words = set(query.lower().split())
        results = [{'text': chunk, 'score': len(query_words.intersection(set(chunk.lower().split())))} for chunk in self.chunks]
        results.sort(key=lambda x: x['score'], reverse=True)
        return [r for r in results if r['score'] > 1][:top_k] # Require at least 2 word overlap

# Defaults and tunables
MAX_CHUNKS = int(os.environ.get("AGENT_MAX_CHUNKS", 1000))
DEFAULT_CHUNK_SIZE = int(os.environ.get("AGENT_CHUNK_SIZE", 512))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("AGENT_CHUNK_OVERLAP", 64))
DEFAULT_MAX_WORKERS = min(4, (os.cpu_count() or 1))

_primary_model_cache = None
_primary_model_lock = threading.Lock()

_results_lock = threading.Lock()
logger = logging.getLogger(__name__)

def preprocess_image(image_bytes, max_size=512):
    # (remains the same)
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
    # (remains the same)
    if len(texts) > max_chunks:
        logger.warning(f"Limiting {len(texts)} chunks to {max_chunks}")
        return texts[:max_chunks]
    return texts

def _clear_hf_cache(log):
    # (remains the same)
    try:
        cache_dir = CUSTOM_CACHE_DIR
        if os.path.exists(cache_dir):
            log.warning(f"Cache related issue possible. Deleting cache directory: {cache_dir}")
            shutil.rmtree(cache_dir)
            log.info("Custom Hugging Face cache directory successfully removed.")
            os.makedirs(cache_dir, exist_ok=True)
        else:
            log.warning("Custom Hugging Face cache directory not found, nothing to delete.")
    except Exception as e:
        log.error(f"Failed to clear custom Hugging Face cache automatically: {e}")

def get_primary_model(logger_instance=None):
    """Loads the primary vision model (PaliGemma) if not already loaded."""
    global _primary_model_cache
    with _primary_model_lock:
        if _primary_model_cache: return _primary_model_cache

        log = logger_instance or logger
        gpu_settings = get_gpu_settings()
        log.info(f"Using GPU settings for primary model: {gpu_settings}")

        hf_token = os.environ.get("HF_TOKEN")
        cache_dir = CUSTOM_CACHE_DIR
        log.info(f"Using custom cache directory for primary model: {cache_dir}")

        primary_model_id = "google/paligemma-3b-mix-448"

        try:
            log.info(f"Attempting to load primary RAG model: {primary_model_id}")
            processor = PaliGemmaProcessor.from_pretrained(primary_model_id, cache_dir=cache_dir)
            model = PaliGemmaForConditionalGeneration.from_pretrained(
                primary_model_id,
                torch_dtype=gpu_settings["dtype"],
                attn_implementation="eager",
                cache_dir=cache_dir
            )

            model.to(gpu_settings["device"])
            log.info(f"Successfully moved {primary_model_id} to device: {gpu_settings['device']}")

            log.info(f"Successfully loaded primary RAG pipeline with {primary_model_id}.")
            _primary_model_cache = {
                "model": model,
                "processor": processor,
                "text_rag": LangChainRAG() if LANGCHAIN_AVAILABLE else SimpleTextRAG(),
                "type": "vision_model_paligemma"
            }
            return _primary_model_cache

        except Exception as e:
            log.error(f"Failed to load primary model {primary_model_id}: {e}", exc_info=True)
            _primary_model_cache = { "model": None, "processor": None, "text_rag": SimpleTextRAG(), "type": "failed"}
            return _primary_model_cache


def retrieve_rag_context(text_rag_instance, query, k=2):
    """Wrapper for retrieving text context using the RAG instance."""
    # (remains the same)
    if not text_rag_instance: return ""
    try:
        results = text_rag_instance.search(query, top_k=k)
        return "\n".join([r['text'] for r in results])
    except Exception as e:
        logger.warning(f"Text retrieval failed: {e}")
        return ""

# --- Prompt function using simplified structure for PaliGemma ---
def create_alt_text_prompt(
    structured_context: Dict[str, Optional[str]],
    existing_alt: str,
    model_format="paligemma"
) -> str:
    """Creates a prompt tailored to the specified model format."""
    prompt_parts = []
    context_lines = []
    if structured_context.get("doc_title"):
        context_lines.append(f"Document Title: {structured_context['doc_title']}")
    if structured_context.get("slide_title"):
        context_lines.append(f"Slide Title/Header: {structured_context['slide_title']}")
    if structured_context.get("surrounding_text"):
        context_lines.append(f"Surrounding Text: {structured_context['surrounding_text'][:300]}")
    combined_context = ". ".join(filter(None, context_lines)) if context_lines else "No text context provided."

    if model_format == "paligemma":
        prompt_parts.append("<image>\n")
        prompt_parts.append(f"Context: {combined_context}. ")
        prompt_parts.append("Describe the image concisely for alt text (max 120 chars), focusing on its purpose/meaning in context. For charts/matrices, describe type/topic/trend, not labels/values.\n")
        prompt_parts.append("Alt Text:")
    elif model_format == "smolvlm":
         # QnA style for SmolVLM
         if existing_alt: combined_context += f". Existing Alt Text (Ignore if poor): {existing_alt}"
         question = (
            "Write a concise alt text (max 120 chars) describing the image's key information and purpose in this context. "
            "Avoid starting with 'Image of'. "
            "For charts/matrices/diagrams, describe the type, topic, and key trend/conclusion - DO NOT list labels or data values shown. "
            "If decorative, say 'Decorative image'."
         )
         prompt_parts.append("<image>\n")
         prompt_parts.append(f"Context: {combined_context}\n")
         prompt_parts.append(f"Question: {question}\n")
         prompt_parts.append("Answer:")
    return "".join(prompt_parts)


def classify_and_generate_alt_text(
    image_bytes: bytes,
    structured_context: Dict[str, Optional[str]],
    primary_model_system: Optional[Dict] = None,
    ext: str = ".pptx",
    existing_alt: str = "",
    slide_num: Optional[int] = None,
    task_idx: int = 0
):
    """Generate alt text using primary model (PaliGemma), falling back if necessary."""
    logger.info(f"Generating alt text for image {task_idx+1} ({ext})")
    processed_image = preprocess_image(image_bytes)
    alt_text = ""
    categories = ["Other"]
    primary_model_loaded = primary_model_system and primary_model_system.get("model") and primary_model_system.get("type") == "vision_model_paligemma"

    if primary_model_loaded:
        logger.info("Using primary model (PaliGemma).")
        try:
            model, processor = primary_model_system["model"], primary_model_system["processor"]
            gpu_settings = get_gpu_settings()
            prompt_text = create_alt_text_prompt(structured_context, existing_alt, model_format="paligemma")
            logger.debug(f"Primary prompt (PaliGemma):\n{prompt_text}")
            image = Image.open(io.BytesIO(processed_image))
            inputs = processor(text=prompt_text, images=image, return_tensors="pt").to(gpu_settings["device"])
            with torch.inference_mode():
                generated_ids = model.generate(**inputs, max_new_tokens=250, do_sample=False)
                prompt_len = inputs["input_ids"].shape[1]
                alt_text = processor.decode(generated_ids[0][prompt_len:], skip_special_tokens=True).strip()
            logger.info(f"Primary model (PaliGemma) generated raw: '{alt_text}'")
        except Exception as e:
            logger.error(f"Error generating alt text with primary model (PaliGemma): {e}", exc_info=True)
            alt_text = "" # Trigger fallback
    else:
        # Log reason for not using primary
        if primary_model_system is None or primary_model_system.get("type") == "failed": logger.warning("Primary model (PaliGemma) failed to load.")
        elif not primary_model_loaded: logger.warning(f"Primary model (PaliGemma) not loaded or incorrect type ('{primary_model_system.get('type')}').")
        alt_text = ""

    # Fallback Logic
    unhelpful_patterns_check = [
        r"unanswerable", r"i am unable to", r"i cannot answer", r"cannot provide",
        r"sorry, as a base vlm", # Added refusal
        r"does not require looking at the image", r"image contains text", r"image shows text",
        r"Groundtruth label", r"Predicted label", r"All Points", r"Critical Points",
        r"GroundTruth label", r"quarterly spending graph",
        r"Purpose/Purpose:", r"List of Extra Readings", r"Christopher's Broken fish",
        r"Image of:", r"Write a concise alt text", r"Answer:", r"Context:", r"Question:",
        r"CRITICAL Rules:", r"DO NOT repeat this prompt", r"Generated Alt Text:",
        r"Describe the image concisely"
    ]
    is_unhelpful = not alt_text or any(re.search(pattern, alt_text, re.IGNORECASE) for pattern in unhelpful_patterns_check)

    if is_unhelpful:
        if not primary_model_loaded: logger.warning("Attempting fallback because primary model didn't load.")
        elif not alt_text: logger.warning("Attempting fallback because primary model produced empty output.")
        else: logger.warning(f"Primary model output was unhelpful or copied prompt: '{alt_text}'. Attempting fallback.")
        try:
            fallback_model_info = get_fallback_model() # Get SmolVLM info
            if fallback_model_info and fallback_model_info.get("model"):
                logger.info("Using fallback vision model (SmolVLM).")
                from src.models.vision_processor import process_image as process_fallback_image
                fallback_prompt = create_alt_text_prompt(structured_context, existing_alt, model_format="smolvlm")
                logger.debug(f"Fallback prompt:\n{fallback_prompt}")
                alt_text = process_fallback_image(processed_image, fallback_prompt)
                logger.info(f"Fallback model generated raw: '{alt_text}'")
            else:
                 logger.error("Fallback model (SmolVLM) also failed to load.")
                 alt_text = "Image could not be processed."; categories = ["Needs Review"]
        except Exception as fallback_e:
             logger.error(f"Error during fallback generation: {fallback_e}", exc_info=True)
             alt_text = "Fallback model error."; categories = ["Needs Review"]

    # Final Post-processing
    alt_text = alt_text.replace("<|end|>", "").replace("<image>", "").replace("ASSISTANT:", "").replace("USER:", "").strip()
    alt_text = re.sub(r'^["\']|["\']$', '', alt_text)
    alt_text = re.sub(r"^(Answer:|Alt Text:)\s*", "", alt_text, flags=re.IGNORECASE).strip()

    cleanup_patterns = [
        r"unanswerable", r"i am unable to", r"i cannot answer", r"unable to provide",
        r"sorry, as a base vlm", # Added refusal
        r"does not require looking at the image", r"cannot provide alt text",
        r"based on the provided context", r"the image (?:depicts|shows|contains|is)\b", r"alt text\s*:",
        r"^(?:description|informative alt text|output|instruction|generated alt text|context:|question:|answer:|alt text:)\s*:", r"^\s*-\s+",
        r"Groundtruth label", r"Predicted label", r"All Points", r"Critical Points",
        r"GroundTruth label", r"quarterly spending graph",
        r"Purpose/Purpose:", r"List of Extra Readings", r"Christopher's Broken fish",
        r"Write a concise alt text", r"Document Title:", r"Slide Title/Header:",
        r"Surrounding Text Snippet:", r"Existing Alt Text:", r"TASK:",
        r"Image of:", r"CRITICAL Rules:", r"DO NOT repeat this prompt", r"DO NOT start with 'Image of'",
        r"Generated Alt Text:", r"Describe the image concisely"
    ]
    original_alt_text_before_cleanup = alt_text
    is_refusal_or_irrelevant = False
    refusal_keywords = ["unanswerable", "unable to", "cannot answer", "cannot provide", "sorry, as a base vlm"]
    if any(keyword in alt_text.lower() for keyword in refusal_keywords):
        logger.warning(f"Detected refusal keyword in output: '{alt_text}'. Clearing.")
        alt_text = ""; categories = ["Needs Review"]; is_refusal_or_irrelevant = True

    if not is_refusal_or_irrelevant:
        irrelevant_patterns = [
             r"Groundtruth label", r"Predicted label", r"All Points", r"Critical Points",
             r"GroundTruth label", r"quarterly spending graph"
        ]
        for pattern in irrelevant_patterns:
             cleaned_alt = re.sub(r'[^\w\s]', '', alt_text).strip()
             cleaned_pattern = re.sub(r'[^\w\s]', '', pattern).strip()
             if cleaned_alt and cleaned_pattern and (cleaned_alt.lower() == cleaned_pattern.lower() or cleaned_alt.lower().startswith(cleaned_pattern.lower())):
                 if len(cleaned_alt) < len(cleaned_pattern) + 15:
                     logger.warning(f"Detected irrelevant text reading '{pattern}' dominating output: '{alt_text}'. Clearing.")
                     alt_text = ""; categories = ["Needs Review"]; is_refusal_or_irrelevant = True; break

    if not is_refusal_or_irrelevant:
        for pattern in cleanup_patterns:
             alt_text = re.sub(f"^{pattern}\\s*", "", alt_text, flags=re.IGNORECASE | re.MULTILINE).strip()
             escaped_pattern = re.escape(pattern.strip('\\b^$'))
             if len(escaped_pattern) > 5: alt_text = re.sub(escaped_pattern, "", alt_text, flags=re.IGNORECASE).strip()
        alt_text = re.sub(r'\s{2,}', ' ', alt_text).strip()
        alt_text = re.sub(r"^\d+\.\s*", "", alt_text).strip()
        alt_text = re.sub(r'^[:\-\*]\s*', '', alt_text).strip()
        alt_text = re.sub(r'\s*[:\-\*]$', '', alt_text).strip()

    # Improved Truncation/Punctuation
    if alt_text.endswith("..."):
        logger.info(f"Cleaning trailing ellipsis from: '{alt_text}'")
        alt_text = alt_text[:-3].strip()
        last_punct_match = re.search(r'[.!?]\s*$', alt_text[-25:])
        if last_punct_match: alt_text = alt_text[:-(25-last_punct_match.end())]
        else:
             last_space = alt_text.rfind(' ')
             if last_space != -1: alt_text = alt_text[:last_space]
             if alt_text and alt_text[-1] not in ['.','!','?']: alt_text += '.'
    elif len(alt_text) > 10 and alt_text[-1] not in ['.','!','?']: alt_text += '.'

    max_len = 120
    if len(alt_text) > max_len:
         logger.warning(f"Alt text STILL exceeds {max_len} chars after cleanup ('{alt_text}'). Final truncation.")
         limit = max_len; last_sentence_end = -1
         for punct in ['.', '!', '?']: pos = alt_text[:limit].rfind(punct); last_sentence_end = max(last_sentence_end, pos)
         if last_sentence_end > limit - 30: alt_text = alt_text[:last_sentence_end + 1].strip()
         else:
             last_space_before_limit = alt_text[:limit].rfind(' ')
             if last_space_before_limit != -1:
                 alt_text = alt_text[:last_space_before_limit].strip()
                 if alt_text and alt_text[-1] not in ['.','!','?']: alt_text += '.'
             else:
                 alt_text = alt_text[:limit]
                 if alt_text and alt_text[-1] not in ['.','!','?']: alt_text += '.'

    # Handle empty alt text
    if not alt_text:
         logger.warning("Alt text became empty after cleanup/failure, using existing or placeholder.")
         alt_text = existing_alt
         if not alt_text:
             idx_str = f" {task_idx + 1}" if task_idx is not None else ""; alt_text = f"Image{idx_str}" + (f" on Slide {slide_num}" if slide_num else "")
             if categories != ["Needs Review"]: categories = ["Needs Review"]
         elif categories != ["Needs Review"]: categories = ["Chart"] if any(w in existing_alt.lower() for w in ["chart", "graph", "plot", "matrix", "table", "diagram"]) else ["Other"]

    # Re-categorize
    if categories != ["Needs Review"]:
        final_alt_lower = alt_text.lower()
        if any(w in final_alt_lower for w in ["chart", "graph", "plot", "matrix", "table"]): categories = ["Chart"]
        elif "diagram" in final_alt_lower: categories = ["Diagram"]
        elif any(w in final_alt_lower for w in ["photo", "photograph", "picture", "screenshot"]): categories = ["Photograph"]
        elif "qr code" in final_alt_lower: categories = ["QR Code"]
        elif final_alt_lower == "decorative image": categories = ["Decorative"]
        else: categories = ["Other"]

    final_alt_text_to_return = alt_text
    logger.info(f"Final alt text for image {task_idx+1}: '{final_alt_text_to_return}' (Category: {categories})")
    return categories, final_alt_text_to_return


# --- START MODIFICATION: Refined context extraction helpers ---
def get_context_for_image_pptx(slide: PptxSlide, shape: PptxPicture) -> Dict[str, Optional[str]]:
    """Extracts slide title and surrounding text for a Picture shape."""
    # (Same implementation as previous)
    context = {"slide_title": None, "surrounding_text": ""}
    try: # Find Title
        title_text = None
        if slide.shapes.title and slide.shapes.title.has_text_frame and slide.shapes.title.text.strip():
            title_text = slide.shapes.title.text.strip()
        elif slide.placeholders:
            for idx in [0, 1, 13, 14]:
                 try:
                     placeholder = slide.placeholders[idx]
                     if placeholder.has_text_frame and placeholder.text and placeholder.text.strip():
                         title_text = placeholder.text.strip(); break
                 except (KeyError, IndexError): continue
        if title_text: context["slide_title"] = title_text.split('\n')[0]
    except Exception as e: logger.warning(f"Could not reliably determine slide title for slide {getattr(slide, 'slide_id', 'N/A')}: {e}")

    try: # Find Nearby Text
        shape_idx = -1; shapes_list = list(slide.shapes)
        for i, s in enumerate(shapes_list):
            if hasattr(s, 'element') and hasattr(shape, 'element') and s.element == shape.element: shape_idx = i; break
            elif hasattr(s, 'shape_id') and hasattr(shape, 'shape_id') and s.shape_id == shape.shape_id: shape_idx = i; break
        nearby_texts = []
        if shape_idx != -1:
            for offset in [-1, 1]:
                idx = shape_idx + offset
                if 0 <= idx < len(shapes_list):
                    neighbor = shapes_list[idx]
                    if hasattr(neighbor, "has_text_frame") and neighbor.has_text_frame and neighbor.text.strip():
                        nearby_texts.append(neighbor.text.strip()[:250])
        combined_text = " ".join(nearby_texts).strip()
        context["surrounding_text"] = combined_text[:400]
        if not context["surrounding_text"] and context["slide_title"]:
             context["surrounding_text"] = context["slide_title"]
    except Exception as e: logger.warning(f"Could not find nearby text for shape {getattr(shape, 'shape_id', 'N/A')}: {e}")
    return context


def get_context_for_image_docx(doc: Document, inline_shape_element: CT_Inline) -> Dict[str, Optional[str]]:
    """Finds the paragraph containing or immediately near an inline shape's element."""
    # (Same implementation as previous)
    context = {"doc_title": None, "slide_title": None, "surrounding_text": ""}
    if hasattr(doc, 'core_properties') and doc.core_properties.title:
         context["doc_title"] = doc.core_properties.title
    try:
        parent_paragraph_element = None; current_element = inline_shape_element.getparent()
        while current_element is not None:
             tag_name = current_element.tag
             if tag_name == '{%s}p' % nsdecls('w'): parent_paragraph_element = current_element; break
             current_element = current_element.getparent()
        if parent_paragraph_element is not None:
             doc_paragraphs = list(doc.paragraphs)
             for para_idx, p in enumerate(doc_paragraphs):
                 if p._element == parent_paragraph_element:
                     para_texts = []
                     if para_idx > 0 and doc_paragraphs[para_idx - 1].text.strip(): para_texts.append(doc_paragraphs[para_idx - 1].text.strip()[:150])
                     if p.text.strip(): para_texts.append(p.text.strip()[:300])
                     if para_idx < len(doc_paragraphs) - 1 and doc_paragraphs[para_idx + 1].text.strip(): para_texts.append(doc_paragraphs[para_idx + 1].text.strip()[:150])
                     context["surrounding_text"] = " ".join(filter(None, para_texts)).strip()
                     break
        if not context.get("surrounding_text"): logger.warning("Could not find paragraph context for docx image element.")
    except Exception as e: logger.warning(f"Error finding paragraph context for docx image: {e}", exc_info=True)
    return context
# --- END MODIFICATION ---

def run_agent_pipeline(file_path, ext, progress_callback=None, partial_save_dir=None, **kwargs):
    executor = None
    gpu_settings = get_gpu_settings()
    primary_model_system = get_primary_model() # Attempt to load PaliGemma
    text_rag_instance = SimpleTextRAG()

    try:
        pipeline_start = time.time()
        logger.info(f"Starting pipeline for {file_path}")
        document_metadata = {}; all_text_content = []; doc_object = None

        if ext == ".pptx":
            try:
                pres = Presentation(file_path)
                if hasattr(pres, 'core_properties') and pres.core_properties.title: document_metadata['title'] = pres.core_properties.title
                for slide in pres.slides:
                    slide_texts = [shp.text for shp in slide.shapes if hasattr(shp, "text") and shp.text and shp.text.strip()]
                    all_text_content.extend(slide_texts)
            except Exception as e: logger.error(f"Error reading PPTX metadata/text: {e}")
        elif ext == ".docx":
             try:
                doc = Document(file_path); doc_object = doc
                if hasattr(doc, 'core_properties') and doc.core_properties.title: document_metadata['title'] = doc.core_properties.title
                for para in doc.paragraphs:
                    if para.text and para.text.strip(): all_text_content.append(para.text.strip())
             except Exception as e: logger.error(f"Error reading DOCX metadata/text: {e}")

        full_text = "\n".join(all_text_content)
        document_metadata['summary'] = ' '.join(full_text.split()[:100])
        texts = chunk_text(full_text); texts = limit_chunks(texts)
        if texts:
            try: text_rag_instance.add_documents(texts)
            except Exception as e: logger.error(f"Failed to add documents to SimpleTextRAG: {e}")

        image_tasks = []
        if ext == ".pptx":
            # --- START MODIFICATION: Use correct XML access for alt text ---
            try:
                pres = Presentation(file_path)
                for slide_num, slide in enumerate(pres.slides, 1):
                    for shape in slide.shapes:
                        if isinstance(shape, PptxPicture):
                            try:
                                img_bytes = shape.image.blob
                                # Correctly access alt text via XML element attributes safely
                                alt_text = ""
                                nvPr = getattr(getattr(getattr(shape, '_element', None), 'nvPicPr', None), 'cNvPr', None)
                                if nvPr is not None:
                                    alt_text = nvPr.attrib.get('descr', '') # Use .get()

                                structured_context = get_context_for_image_pptx(slide, shape)
                                structured_context["doc_title"] = document_metadata.get('title')

                                image_tasks.append({
                                    "bytes": img_bytes, "alt": alt_text,
                                    "structured_context": structured_context,
                                    "slide_num": slide_num
                                })
                            except Exception as img_e:
                                 shape_id_str = f"shape ID {shape.shape_id}" if hasattr(shape, 'shape_id') else "shape"
                                 logger.warning(f"Could not extract image/context from {shape_id_str} on slide {slide_num}: {img_e}", exc_info=True) # Log traceback
            except Exception as e:
                logger.error(f"Error processing PPTX file {file_path} for images: {e}", exc_info=True)
            # --- END MODIFICATION ---

        elif ext == ".docx" and doc_object:
             # (DOCX extraction logic remains the same - already uses safe .get())
            try:
                img_counter = 0; processed_rel_ids = set()
                for shape in doc_object.part.inline_shapes:
                    if hasattr(shape, 'type') and shape.type == 3: # WD_INLINE_SHAPE.PICTURE
                        img_counter += 1
                        try:
                            inline_el = shape._inline
                            rId = inline_el.graphic.graphicData.pic.blipFill.blip.embed
                            if rId in processed_rel_ids: continue
                            rel = doc_object.part.rels[rId]
                            if not rel.is_external:
                                img_bytes = rel.target_part.blob; processed_rel_ids.add(rId)
                                alt_text = ""
                                try:
                                     docPr = inline_el.find(qn('wp:docPr'))
                                     if docPr is not None: alt_text = docPr.get('descr', '')
                                except Exception as alt_e: logger.warning(f"Error accessing docPr descr for inline shape {img_counter}: {alt_e}")
                                structured_context = get_context_for_image_docx(doc_object, inline_el)
                                image_tasks.append({"bytes": img_bytes, "alt": alt_text, "structured_context": structured_context, "slide_num": None})
                        except Exception as shape_e: logger.error(f"Error processing inline shape {img_counter}: {shape_e}", exc_info=True)
                for rId, rel in doc_object.part.rels.items():
                    if "image" in rel.target_ref and not rel.is_external and rId not in processed_rel_ids:
                        img_counter += 1; logger.warning(f"Found image via rels (rId: {rId}) not caught by inline_shapes. Using basic context.")
                        try: img_bytes = rel.target_part.blob; processed_rel_ids.add(rId)
                        except Exception as blob_e: logger.error(f"Could not read image blob for rId {rId}: {blob_e}"); continue
                        structured_context = {"doc_title": document_metadata.get('title'), "slide_title": None, "surrounding_text": document_metadata.get('summary', '')}
                        image_tasks.append({"bytes": img_bytes, "alt": "", "structured_context": structured_context, "slide_num": None})
            except Exception as e: logger.error(f"Error processing DOCX file {file_path} for images: {e}", exc_info=True)

        total_images = len(image_tasks)
        if not total_images:
            logger.warning(f"No valid images found or extracted from {file_path}")
            if progress_callback: progress_callback("No images found", 0, 0)
            return []

        processed_count = 0; results = []
        executor_class = concurrent.futures.ThreadPoolExecutor
        max_workers = 1 if gpu_settings.get("device") == "cuda" else DEFAULT_MAX_WORKERS
        logger.info(f"Using {executor_class.__name__} with max_workers={max_workers}")
        executor = executor_class(max_workers=max_workers)

        def process_single_image(task_idx, task):
            nonlocal processed_count
            current_primary_model_system = _primary_model_cache
            try:
                categories, generated_alt = classify_and_generate_alt_text(
                    image_bytes=task["bytes"], structured_context=task["structured_context"],
                    primary_model_system=current_primary_model_system, ext=ext,
                    existing_alt=task["alt"], slide_num=task.get("slide_num"), task_idx=task_idx
                )
                with _results_lock:
                    processed_count += 1
                    status_msg = f"Processing image {processed_count}/{total_images}"
                    if categories == ["Needs Review"]: status_msg += " (Review Recommended)"
                    if progress_callback: progress_callback(status_msg, processed_count, total_images)
                import base64; image_data_uri = None
                try:
                    processed_display_image = preprocess_image(task['bytes'], max_size=256)
                    b64_image = base64.b64encode(processed_display_image).decode('utf-8')
                    image_data_uri = f"data:image/jpeg;base64,{b64_image}"
                except Exception as enc_e: logger.error(f"Could not encode image {task_idx+1} for display: {enc_e}")
                return {"classification": categories, "alt_text": task["alt"], "generated_alt_text": generated_alt,
                        "image_idx": task_idx + 1, "slide_num": task.get("slide_num"), "image_data": image_data_uri}
            except Exception as e:
                logger.error(f"Error in process_single_image task for image {task_idx+1}: {e}", exc_info=True)
                with _results_lock:
                    processed_count += 1
                    if progress_callback: progress_callback(f"Error processing image {processed_count}/{total_images}", processed_count, total_images)
                return None

        future_to_task = {executor.submit(process_single_image, i, task): i for i, task in enumerate(image_tasks)}
        temp_results = {}
        for future in concurrent.futures.as_completed(future_to_task):
            idx = future_to_task[future]
            try:
                result = future.result();
                if result: temp_results[idx] = result
            except Exception as exc: logger.error(f'Image processing task {idx + 1} generated an exception: {exc}')

        results = [temp_results[i] for i in sorted(temp_results.keys())]
        if progress_callback: progress_callback("Processing complete", total_images, total_images)
        logger.info(f"Pipeline finished processing {len(results)} images in {time.time() - pipeline_start:.2f}s")
        return results
    finally:
         if executor:
             logger.info("Shutting down thread pool executor."); executor.shutdown(wait=True); logger.info("Executor shut down complete.")

