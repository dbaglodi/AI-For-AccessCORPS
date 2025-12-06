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

# --- START MODIFICATION: Add placeholder image ---
UNSUPPORTED_IMAGE_PLACEHOLDER = "https://placehold.co/400x300/EFEFEF/AAAAAA?text=Unsupported+Format%5Cn(WMF/EMF)"
# --- END MODIFICATION ---

def preprocess_image(image_bytes, max_size=512):
    # (remains the same)
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        img_byte_arr = io.BytesIO()
        img_byte_arr.save(img_byte_arr, format='JPEG', quality=90)
        return img_byte_arr.getvalue()
    except Exception as e:
        # --- START MODIFICATION: Check for WMF/unidentified image errors ---
        if "cannot identify image file" in str(e) or "unsupported image type" in str(e):
             logger.warning(f"PIL cannot identify image file, likely an unsupported format (e.g., WMF/EMF). Error: {e}")
             raise ValueError("Unsupported image format") # Raise specific error
        # --- END MODIFICATION ---
        logger.error(f"Error preprocessing image: {e}")
        return image_bytes # Return original bytes on other errors

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
        # --- START MODIFICATION: Fix IndentationError ---
        return "".join([r['text'] for r in results])
    except Exception as e:
        # --- END MODIFICATION ---
        logger.warning(f"Text retrieval failed: {e}")
        return ""

# --- START MODIFICATION: Reworked two-pass prompts ---

def _get_combined_context(structured_context: Dict[str, Optional[str]]) -> str:
    """Helper to create a combined context string."""
    context_lines = []
    if structured_context.get("doc_title"):
        context_lines.append(f"Document Title: {structured_context['doc_title']}")
    if structured_context.get("slide_title"):
        context_lines.append(f"Slide Title/Header: {structured_context['slide_title']}")
    if structured_context.get("surrounding_text"):
        # Limit surrounding text in prompt
        context_lines.append(f"Surrounding Text: {structured_context['surrounding_text'][:300]}")
    return ". ".join(filter(None, context_lines)) if context_lines else "No text context provided."

def create_tagging_prompt(
    structured_context: Dict[str, Optional[str]],
    model_format="paligemma"
) -> str:
    """Creates a Pass 1 prompt to get image categories/tags."""
    combined_context = _get_combined_context(structured_context)
    prompt_parts = []
    
    # --- START MODIFICATION: Restore notebook prompt with stricter output instructions ---
    categories_prompt_text = """Categories:
Graph: Visual representations of data, typically with axes and labeled points, such as line graphs, bar graphs, and scatter plots. They display numerical data trends over time or across categories.
Chart: Broad category that includes pie charts, flow charts, and similar visuals. Charts are used to show relationships, hierarchies, or proportions among different components or processes.
Map: Geographical representations showing locations, terrain, or routes. Maps can include details like topography, political boundaries, or population density.
Diagram: Illustrative visualizations explaining concepts, structures, or processes, such as circuit diagrams, organizational charts, or flow diagrams. Diagrams often break down complex ideas.
Table: Gridded arrangements of data in rows and columns, often with headings. Tables are used for easy lookup and comparison of related information.
Photograph: Real-life images that capture a scene, object, or event, often used for documentation or visual reference.
Text: Visual representations of written information, often without additional visual elements. Text images are used to convey information directly in written form rather than through data or graphical representations.
Screenshot: Captured images from a digital interface, such as a website, software, or application screen, usually to illustrate a particular function or feature.
Equation: Visuals showing mathematical or scientific equations, formulas, or expressions.
Other: An image that does not serve any of the above purposes.

CRITICAL: Review the categories and their descriptions, then respond ONLY with the comma-separated names of the categories that apply to the image.
Example Response: Graph, Diagram
"""
    # --- END MODIFICATION ---

    if model_format == "paligemma":
        prompt_parts.append("<image>\n")
        # --- START MODIFICATION: Revert to notebook-like prompt structure ---
        prompt_parts.append(f"Using the image provided, classify it into the following categories based on its primary content and purpose.\n\n")
        prompt_parts.append(f"Context: {combined_context}\n\n")
        prompt_parts.append(f"{categories_prompt_text}\n\n")
        # --- END MODIFICATION ---
        prompt_parts.append("Selected Categories:")
    elif model_format == "smolvlm":
         prompt_parts.append("<image>\n")
         # --- START MODIFICATION: Revert to notebook-like prompt structure ---
         prompt_parts.append(f"Question: Using the image provided, classify it into the following categories based on its primary content and purpose.\n\n")
         prompt_parts.append(f"Context: {combined_context}\n\n")
         prompt_parts.append(f"{categories_prompt_text}\n\n")
         # --- END MODIFICATION ---
         prompt_parts.append("Answer:")
    return "".join(prompt_parts)

# --- START MODIFICATION: Updated alt text prompt to match notebook and add specific "ba/ga" instruction ---
def create_alt_text_prompt(
    structured_context: Dict[str, Optional[str]],
    categories: List[str], # <-- Takes tags as input
    existing_alt: str,
    model_format="paligemma"
) -> str:
    """Creates a Pass 2 prompt using the tags to get the full alt text."""
    combined_context = _get_combined_context(structured_context)
    prompt_parts = []
    category_str = ", ".join(categories)

    guidelines = [
        "1. Focus on describing key visual elements and their relationship to the context.",
        "2. Use clear, academic language.",
        "3. If the image shows a diagram, graph, chart, or table, describe its key components, purpose, and key takeaway. CRITICAL: DO NOT read the text labels, values, or equations aloud.",
        "   - For example, for a spectrogram, describe it as 'A spectrogram showing formants' and DO NOT read the labels like '/ba/' or '/ga/'.",
        "4. Include relevant technical terms from the context when appropriate.",
        "5. Consider how this image fits into the overall document theme.",
        "6. If decorative, respond with 'Decorative image'."
    ]
    
    prompt_text = f"""Generate a concise, descriptive alt text for this image.

Context: {combined_context}
Image Type(s): {category_str}
Existing alt text: {existing_alt if existing_alt else 'None'}

Important guidelines:
""" + "\n".join(guidelines) + "\n\nPlease provide just the alt text without any additional commentary."


    if model_format == "paligemma":
        prompt_parts.append("<image>\n")
        prompt_parts.append(prompt_text + "\n\n")
        prompt_parts.append("Alt Text:")
    elif model_format == "smolvlm":
         prompt_parts.append("<image>\n")
         # Add existing alt text to context for smolvlm
         smol_context = combined_context
         if existing_alt: 
             smol_context += f". Existing Alt Text (Ignore if poor): {existing_alt}"
         
         # Re-create guidelines for smolvlm's Q&A format
         smol_question = (
            f"Write a concise, descriptive alt text for this image, which is a {category_str}. "
            "Focus on its key information, purpose, and relationship to the context. "
            "Use clear, academic language. "
            "CRITICAL: For charts, graphs, diagrams, or spectrograms, describe the key takeaway, NOT the specific labels or data. "
            "For example, do not say '/ba/' or '/ga/'. "
            "If decorative, say 'Decorative image'."
         )
         
         prompt_parts.append(f"Context: {smol_context}\n\n")
         prompt_parts.append(f"Question: {smol_question}\n\n")
         prompt_parts.append("Answer:")
    return "".join(prompt_parts)
# --- END MODIFICATION ---

# --- END MODIFICATION ---


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
    try:
        processed_image = preprocess_image(image_bytes)
    except ValueError as e: # Catch our specific error
        if "Unsupported image format" in str(e):
            logger.warning(f"Task {task_idx+1}: Skipping AI processing due to unsupported image format.")
            # --- START MODIFICATION: Remove short_description from return ---
            return ["Needs Review"], "Unsupported image format (WMF/EMF). Please provide alt text manually."
            # --- END MODIFICATION ---
        else:
            raise # Re-raise other unexpected errors

    alt_text = ""
    categories = ["Other"] # Default
    primary_model_loaded = primary_model_system and primary_model_system.get("model") and primary_model_system.get("type") == "vision_model_paligemma"

    # --- START MODIFICATION: Define valid categories ONCE ---
    valid_categories = ["Graph", "Chart", "Map", "Diagram", "Table", "Photograph", "Text", "Screenshot", "Equation", "Other"]
    valid_categories_map = {cat.lower(): cat for cat in valid_categories}
    # --- END MODIFICATION ---

    if primary_model_loaded:
        logger.info("Using primary model (PaliGemma) - Pass 1 (Tagging).")
        try:
            model, processor = primary_model_system["model"], primary_model_system["processor"]
            gpu_settings = get_gpu_settings()
            
            # --- START MODIFICATION: Pass 1 (Tagging) ---
            prompt_text_pass_1 = create_tagging_prompt(structured_context, model_format="paligemma")
            logger.debug(f"Primary prompt (PaliGemma) Pass 1:\n{prompt_text_pass_1}")
            image = Image.open(io.BytesIO(processed_image))
            inputs_pass_1 = processor(text=prompt_text_pass_1, images=image, return_tensors="pt").to(gpu_settings["device"])
            
            with torch.inference_mode():
                generated_ids_pass_1 = model.generate(**inputs_pass_1, max_new_tokens=100, do_sample=False) # Increased token limit for safety
                prompt_len_pass_1 = inputs_pass_1["input_ids"].shape[1]
                generated_tags = processor.decode(generated_ids_pass_1[0][prompt_len_pass_1:], skip_special_tokens=True).strip()
                generated_tags = re.sub(r"^(Category:|Answer:|Selected Categories:)\s*", "", generated_tags, flags=re.IGNORECASE).strip()
            
            # --- START MODIFICATION: Stricter cleanup logic ---
            found_categories = set()
            # Split by comma, clean up each piece, and check for exact match
            potential_tags = generated_tags.split(',')
            for tag in potential_tags:
                cleaned_tag = tag.strip().lower()
                if cleaned_tag in valid_categories_map:
                    found_categories.add(valid_categories_map[cleaned_tag])
                else:
                    # Fallback regex for cases like "graph: diagram" (no comma)
                    pattern = r'\b(' + '|'.join(re.escape(cat) for cat in valid_categories) + r')\b'
                    matches = re.findall(pattern, tag, re.IGNORECASE)
                    for match in matches:
                        found_categories.add(valid_categories_map[match.lower()])
            
            categories = list(found_categories) if found_categories else ["Other"]
            # --- END MODIFICATION ---
            logger.info(f"Primary model (PaliGemma) Pass 1 generated tags (cleaned): {categories}")
            # --- END MODIFICATION ---

            # --- START MODIFICATION: Pass 2 (Alt Text) ---
            logger.info("Using primary model (PaliGemma) - Pass 2 (Full Alt Text).")
            prompt_text_pass_2 = create_alt_text_prompt(structured_context, categories, existing_alt, model_format="paligemma")
            logger.debug(f"Primary prompt (PaliGemma) Pass 2:\n{prompt_text_pass_2}")
            inputs_pass_2 = processor(text=prompt_text_pass_2, images=image, return_tensors="pt").to(gpu_settings["device"])

            with torch.inference_mode():
                generated_ids_pass_2 = model.generate(**inputs_pass_2, max_new_tokens=250, do_sample=False)
                prompt_len_pass_2 = inputs_pass_2["input_ids"].shape[1]
                alt_text = processor.decode(generated_ids_pass_2[0][prompt_len_pass_2:], skip_special_tokens=True).strip()
            logger.info(f"Primary model (PaliGemma) Pass 2 generated raw: '{alt_text}'")
            # --- END MODIFICATION ---

        except Exception as e:
            logger.error(f"Error generating alt text with primary model (PaliGemma): {e}", exc_info=True)
            alt_text = "" # Trigger fallback
            categories = ["Other"] # Reset categories on error
    else:
        # Log reason for not using primary
        if primary_model_system is None or primary_model_system.get("type") == "failed": logger.warning("Primary model (PaliGemma) failed to load.")
        elif not primary_model_loaded: logger.warning(f"Primary model (PaliGemma) not loaded or incorrect type ('{primary_model_system.get('type')}').")
        alt_text = ""
        categories = ["Other"]

    # --- START MODIFICATION: Reworked Fallback Logic ---
    # --- START MODIFICATION: Define unhelpful_patterns_check BEFORE use ---
    unhelpful_patterns_check = [
        r"unanswerable", r"i am unable to", r"i cannot answer", r"cannot provide",
        r"sorry, as a base vlm", # Added refusal
        r"does not require looking at the image", r"image contains text", r"image shows text",
        r"Groundtruth label", r"Predicted label", r"All Points", r"Critical Points",
        r"GroundTruth label", r"quarterly spending graph",
        r"Purpose/Purpose:", r"List of Extra Readings", r"Christopher's Broken fish",
        r"Image of:", r"Write a concise alt text", r"Answer:", r"Context:", r"Question:",
        r"Generated Alt Text:",
        # --- START MODIFICATION: Fix missing quotation mark ---
        r"Describe the image concisely"
        # --- END MODIFICATION ---
    ]
    # --- END MODIFICATION ---
    is_unhelpful = not alt_text or any(re.search(pattern, alt_text, re.IGNORECASE) for pattern in unhelpful_patterns_check)

    if is_unhelpful:
        if not primary_model_loaded: logger.warning("Attempting fallback because primary model didn't load.")
        elif not alt_text: logger.warning("Attempting fallback because primary model produced empty output.")
        else: logger.warning(f"Primary model output was unhelpful or copied prompt: '{alt_text}'. Attempting fallback.")
        
        try:
            fallback_model_info = get_fallback_model() # Get SmolVLM info
            if fallback_model_info and fallback_model_info.get("model"):
                from src.models.vision_processor import process_image as process_fallback_image
                
                # Fallback Pass 1 (Tagging)
                logger.info("Using fallback vision model (SmolVLM) - Pass 1 (Tagging).")
                fallback_prompt_pass_1 = create_tagging_prompt(structured_context, model_format="smolvlm")
                logger.debug(f"Fallback prompt Pass 1:\n{fallback_prompt_pass_1}")
                generated_tags_fallback = process_fallback_image(processed_image, fallback_prompt_pass_1)
                generated_tags_fallback = re.sub(r"^(Category:|Answer:|Selected Categories:)\s*", "", generated_tags_fallback, flags=re.IGNORECASE).strip()
                
                # --- START MODIFICATION: Stricter cleanup logic ---
                found_categories = set()
                # Split by comma, clean up each piece, and check for exact match
                potential_tags = generated_tags_fallback.split(',')
                for tag in potential_tags:
                    cleaned_tag = tag.strip().lower()
                    if cleaned_tag in valid_categories_map:
                        found_categories.add(valid_categories_map[cleaned_tag])
                    else:
                        # Fallback regex for cases like "graph: diagram" (no comma)
                        pattern = r'\b(' + '|'.join(re.escape(cat) for cat in valid_categories) + r')\b'
                        matches = re.findall(pattern, tag, re.IGNORECASE)
                        for match in matches:
                            found_categories.add(valid_categories_map[match.lower()])
                
                categories = list(found_categories) if found_categories else ["Other"]
                # --- END MODIFICATION ---
                logger.info(f"Fallback model Pass 1 generated tags (cleaned): {categories}")

                # Fallback Pass 2 (Alt Text)
                logger.info("Using fallback vision model (SmolVLM) - Pass 2 (Full Alt Text).")
                fallback_prompt_pass_2 = create_alt_text_prompt(structured_context, categories, existing_alt, model_format="smolvlm")
                logger.debug(f"Fallback prompt Pass 2:\n{fallback_prompt_pass_2}")
                alt_text = process_fallback_image(processed_image, fallback_prompt_pass_2)
                logger.info(f"Fallback model Pass 2 generated raw: '{alt_text}'")
                
            else:
                 logger.error("Fallback model (SmolVLM) also failed to load.")
                 alt_text = "Image could not be processed."; categories = ["Needs Review"]
        except Exception as fallback_e:
             logger.error(f"Error during fallback generation: {fallback_e}", exc_info=True)
             alt_text = "Fallback model error."; categories = ["Needs Review"]
    # --- END MODIFICATION ---

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
        alt_text = ""; is_refusal_or_irrelevant = True

    # --- START MODIFICATION: Add check for prompt-like text ---
    if "/ba/" in alt_text or "/da/" in alt_text or "/ga/" in alt_text:
        logger.warning(f"Detected problematic text reading in output: '{alt_text}'. Clearing.")
        alt_text = ""; is_refusal_or_irrelevant = True
    # --- END MODIFICATION ---

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
                     alt_text = ""; is_refusal_or_irrelevant = True; break

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
             if "Needs Review" not in categories: categories.append("Needs Review")
         
    # --- START MODIFICATION: Remove re-categorization logic. It's now done first. ---
    # (The old logic here is removed)
    # --- END MODIFICATION ---

    final_alt_text_to_return = alt_text
    logger.info(f"Final alt text for image {task_idx+1}: '{final_alt_text_to_return}' (Category: {categories})")
    # --- START MODIFICATION: Return categories and alt_text ---
    return categories, final_alt_text_to_return
    # --- END MODIFICATION ---


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

        # --- START MODIFICATION: Handle unsupported formats ---
        image_tasks = [] # Tasks for AI processing
        placeholder_results = [] # Results for skipped images
        current_image_index = 0
        # --- END MODIFICATION ---

        if ext == ".pptx":
            try:
                pres = Presentation(file_path)
                for slide_num, slide in enumerate(pres.slides, 1):
                    for shape in slide.shapes:
                        if isinstance(shape, PptxPicture):
                            current_image_index += 1
                            try:
                                img_bytes = shape.image.blob
                                content_type = shape.image.content_type.lower()
                                
                                # Correctly access alt text via XML element attributes safely
                                alt_text = ""
                                nvPr = getattr(getattr(getattr(shape, '_element', None), 'nvPicPr', None), 'cNvPr', None)
                                if nvPr is not None:
                                    alt_text = nvPr.attrib.get('descr', '') # Use .get()

                                structured_context = get_context_for_image_pptx(slide, shape)
                                structured_context["doc_title"] = document_metadata.get('title')

                                # --- START MODIFICATION: Check for WMF/EMF ---
                                if 'wmf' in content_type or 'emf' in content_type:
                                    logger.warning(f"Skipping unsupported image format ({content_type}) for image {current_image_index} on slide {slide_num}.")
                                    placeholder_results.append({
                                        "classification": ["Needs Review"],
                                        "alt_text": alt_text,
                                        "generated_alt_text": "Unsupported image format (WMF/EMF). Please provide alt text manually.",
                                        # "short_description": "Unsupported format", # Removed
                                        "image_idx": current_image_index,
                                        "slide_num": slide_num,
                                        "image_data": UNSUPPORTED_IMAGE_PLACEHOLDER
                                    })
                                    continue # Skip to the next shape
                                # --- END MODIFICATION ---

                                image_tasks.append({
                                    "bytes": img_bytes, "alt": alt_text,
                                    "structured_context": structured_context,
                                    "slide_num": slide_num,
                                    "task_idx": current_image_index # Pass the global index
                                })
                            except Exception as img_e:
                                 shape_id_str = f"shape ID {shape.shape_id}" if hasattr(shape, 'shape_id') else "shape"
                                 logger.warning(f"Could not extract image/context from {shape_id_str} on slide {slide_num}: {img_e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing PPTX file {file_path} for images: {e}", exc_info=True)

        elif ext == ".docx" and doc_object:
            try:
                processed_rel_ids = set()
                for shape in doc_object.part.inline_shapes:
                    if hasattr(shape, 'type') and shape.type == 3: # WD_INLINE_SHAPE.PICTURE
                        current_image_index += 1
                        try:
                            inline_el = shape._inline
                            rId = inline_el.graphic.graphicData.pic.blipFill.blip.embed
                            if rId in processed_rel_ids: current_image_index -= 1; continue # Don't double count
                            
                            rel = doc_object.part.rels[rId]
                            if rel.is_external: current_image_index -= 1; continue
                            
                            processed_rel_ids.add(rId)
                            img_bytes = rel.target_part.blob
                            content_type = rel.target_part.content_type.lower()
                            alt_text = ""
                            try:
                                 docPr = inline_el.find(qn('wp:docPr'))
                                 if docPr is not None: alt_text = docPr.get('descr', '')
                            except Exception as alt_e: logger.warning(f"Error accessing docPr descr for inline shape {current_image_index}: {alt_e}")
                            
                            structured_context = get_context_for_image_docx(doc_object, inline_el)

                            # --- START MODIFICATION: Check for WMF/EMF ---
                            if 'wmf' in content_type or 'emf' in content_type:
                                logger.warning(f"Skipping unsupported image format ({content_type}) for inline DOCX image {current_image_index} (rId: {rId}).")
                                placeholder_results.append({
                                    "classification": ["Needs Review"],
                                    "alt_text": alt_text,
                                    "generated_alt_text": "Unsupported image format (WMF/EMF). Please provide alt text manually.",
                                    # "short_description": "Unsupported format", # Removed
                                    "image_idx": current_image_index,
                                    "slide_num": None,
                                    "image_data": UNSUPPORTED_IMAGE_PLACEHOLDER
                                })
                                continue # Skip to the next shape
                            # --- END MODIFICATION ---

                            image_tasks.append({"bytes": img_bytes, "alt": alt_text, "structured_context": structured_context, "slide_num": None, "task_idx": current_image_index, "rId": rId})
                        except Exception as shape_e: logger.error(f"Error processing inline shape {current_image_index}: {shape_e}", exc_info=True)
                
                for rId, rel in doc_object.part.rels.items():
                    if "image" in rel.target_ref and not rel.is_external and rId not in processed_rel_ids:
                        current_image_index += 1
                        logger.warning(f"Found image via rels (rId: {rId}) not caught by inline_shapes. Using basic context.")
                        try:
                            img_bytes = rel.target_part.blob; processed_rel_ids.add(rId)
                            content_type = rel.target_part.content_type.lower()
                        except Exception as blob_e: logger.error(f"Could not read image blob for rId {rId}: {blob_e}"); current_image_index -= 1; continue
                        
                        structured_context = {"doc_title": document_metadata.get('title'), "slide_title": None, "surrounding_text": document_metadata.get('summary', '')}
                        
                        # --- START MODIFICATION: Check for WMF/EMF ---
                        if 'wmf' in content_type or 'emf' in content_type:
                            logger.warning(f"Skipping unsupported image format ({content_type}) for rels DOCX image {current_image_index} (rId: {rId}).")
                            placeholder_results.append({
                                "classification": ["Needs Review"],
                                "alt_text": "", # No alt text available for these
                                "generated_alt_text": "Unsupported image format (WMF/EMF). Please provide alt text manually.",
                                # "short_description": "Unsupported format", # Removed
                                "image_idx": current_image_index,
                                "slide_num": None,
                                "image_data": UNSUPPORTED_IMAGE_PLACEHOLDER
                            })
                            continue # Skip to the next rel
                        # --- END MODIFICATION ---
                        
                        image_tasks.append({"bytes": img_bytes, "alt": "", "structured_context": structured_context, "slide_num": None, "task_idx": current_image_index, "rId": rId})
            except Exception as e: logger.error(f"Error processing DOCX file {file_path} for images: {e}", exc_info=True)

        # --- START MODIFICATION: Use new total count ---
        total_images = current_image_index
        # --- END MODIFICATION ---
        
        if not total_images:
            logger.warning(f"No valid images found or extracted from {file_path}")
            if progress_callback: progress_callback("No images found", 0, 0)
            return []

        # --- START MODIFICATION: Adjust processed count ---
        processed_count = len(placeholder_results) # Start count from skipped images
        # --- END MODIFICATION ---
        
        executor_class = concurrent.futures.ThreadPoolExecutor
        max_workers = 1 if gpu_settings.get("device") == "cuda" else DEFAULT_MAX_WORKERS
        logger.info(f"Using {executor_class.__name__} with max_workers={max_workers}")
        executor = executor_class(max_workers=max_workers)

        def process_single_image(task):
            nonlocal processed_count
            # --- START MODIFICATION: Use task_idx from task ---
            task_idx = task["task_idx"]
            # --- END MODIFICATION ---
            current_primary_model_system = _primary_model_cache
            try:
                # --- START MODIFICATION: Update return values ---
                categories, generated_alt = classify_and_generate_alt_text(
                # --- END MODIFICATION ---
                    image_bytes=task["bytes"], structured_context=task["structured_context"],
                    primary_model_system=current_primary_model_system, ext=ext,
                    existing_alt=task["alt"], slide_num=task.get("slide_num"), 
                    task_idx=task_idx # Pass the correct index
                )
                with _results_lock:
                    processed_count += 1
                    status_msg = f"Processing image {processed_count}/{total_images}"
                    if "Needs Review" in categories: status_msg += " (Review Recommended)"
                    if progress_callback: progress_callback(status_msg, processed_count, total_images)
                
                import base64; image_data_uri = None
                try:
                    processed_display_image = preprocess_image(task['bytes'], max_size=256)
                    b64_image = base64.b64encode(processed_display_image).decode('utf-8')
                    image_data_uri = f"data:image/jpeg;base64,{b64_image}"
                except Exception as enc_e: 
                    logger.error(f"Could not encode image {task_idx} for display: {enc_e}")
                    image_data_uri = "https://placehold.co/400x300/EFEFEF/AAAAAA?text=Preview+Error"

                # --- START MODIFICATION: Update result dictionary ---
                result_data = {"classification": categories, "alt_text": task["alt"], "generated_alt_text": generated_alt,
                        "image_idx": task_idx, # Use the global index
                        "slide_num": task.get("slide_num"), "image_data": image_data_uri}
                if "rId" in task:
                    result_data["rId"] = task["rId"]
                return result_data
                # --- END MODIFICATION ---
            except Exception as e:
                logger.error(f"Error in process_single_image task for image {task_idx}: {e}", exc_info=True)
                with _results_lock:
                    processed_count += 1
                    if progress_callback: progress_callback(f"Error processing image {processed_count}/{total_images}", processed_count, total_images)
                
                # --- START MODIFICATION: Update error result dictionary ---
                result_data = {
                    "classification": ["Needs Review"], "alt_text": task["alt"], "generated_alt_text": "Error during processing.",
                    "image_idx": task_idx,
                    "slide_num": task.get("slide_num"), "image_data": "https://placehold.co/400x300/EFEFEF/AAAAAA?text=Processing+Error"
                }
                if "rId" in task:
                    result_data["rId"] = task["rId"]
                return result_data
                # --- END MODIFICATION ---

        # --- START MODIFICATION: Use task_idx as key ---
        future_to_task_idx = {executor.submit(process_single_image, task): task["task_idx"] for task in image_tasks}
        temp_results = {}
        for future in concurrent.futures.as_completed(future_to_task_idx):
            idx = future_to_task_idx[future]
            try:
                result = future.result();
                if result: temp_results[idx] = result
            except Exception as exc: logger.error(f'Image processing task {idx} generated an exception: {exc}')

        # Combine processed results with placeholders and sort
        processed_results = [temp_results[i] for i in sorted(temp_results.keys())]
        all_results = placeholder_results + processed_results
        final_sorted_results = sorted(all_results, key=lambda r: r.get('image_idx', 0))
        # --- END MODIFICATION ---

        if progress_callback: progress_callback("Processing complete", total_images, total_images)
        logger.info(f"Pipeline finished processing {len(final_sorted_results)} images in {time.time() - pipeline_start:.2f}s")
        return final_sorted_results
    finally:
         if executor:
             logger.info("Shutting down thread pool executor."); executor.shutdown(wait=True); logger.info("Executor shut down complete.")