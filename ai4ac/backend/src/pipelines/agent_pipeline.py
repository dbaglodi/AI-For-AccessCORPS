import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docx import Document
from pptx import Presentation
from PIL import Image
import io
import os
import logging
import time
import json
import re
from collections import Counter
import torch
from contextlib import contextmanager
import numpy as np
import gc
import concurrent.futures
import threading
import math
from typing import Optional

# Optional imports (may be missing in some environments)
try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except Exception:
    RecursiveCharacterTextSplitter = None

try:
    from langchain_community.vectorstores import FAISS
except Exception:
    FAISS = None

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:
    HuggingFaceEmbeddings = None

try:
    from byaldi import RAGMultiModalModel
    BYALDI_AVAILABLE = True
except Exception:
    RAGMultiModalModel = None
    BYALDI_AVAILABLE = False

# --- Inlined utilities (chunker, embeddings, vectorstore, SimpleRAG, vlm, ingest) ---

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64):
    if not text:
        return []
    tokens = text.split()
    chunks = []
    i = 0
    while i < len(tokens):
        chunk = tokens[i:i+chunk_size]
        chunks.append(" ".join(chunk))
        i += chunk_size - overlap
    return chunks


# Embedding shim with lightweight fallback
_embed_client = None
def get_embedding_client(model_name: str = "sentence-transformers/all-mpnet-base-v2"):
    global _embed_client
    if _embed_client is not None:
        return _embed_client
    
    # Try GPU with better error handling
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        
        # Try GPU first with explicit CUDA device
        if torch.cuda.is_available():
            try:
                _embed_client = HuggingFaceEmbeddings(
                    model_name=model_name,
                    model_kwargs={
                        'device': 'cuda:0',
                        'torch_dtype': torch.float32  # Use float32 for stability
                    }
                )
                logger.info("Using GPU for embeddings (LangChain)")
                return _embed_client
            except Exception as e:
                logger.warning(f"GPU embedding failed, trying CPU: {e}")
        
        # Fallback to CPU
        _embed_client = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={'device': 'cpu'}
        )
        logger.info("Using CPU for embeddings (LangChain)")
        return _embed_client
        
    except Exception:
        pass
    
    # Try SentenceTransformers directly with better GPU handling
    try:
        from sentence_transformers import SentenceTransformer
        
        if torch.cuda.is_available():
            try:
                # Try to load on GPU with explicit device
                model = SentenceTransformer(model_name)
                model = model.to('cuda:0')
                logger.info("Using GPU for embeddings (SentenceTransformers)")
            except Exception as e:
                logger.warning(f"GPU SentenceTransformer failed: {e}")
                model = SentenceTransformer(model_name, device='cpu')
                logger.info("Using CPU for embeddings (SentenceTransformers)")
        else:
            model = SentenceTransformer(model_name, device='cpu')
            
        class _STWrapper:
            def embed_documents(self, texts):
                return model.encode(texts, show_progress_bar=False, convert_to_tensor=False)
        _embed_client = _STWrapper()
        return _embed_client
        
    except Exception:
        # Final fallback to hash-based embeddings
        logger.warning("All embedding methods failed, using hash fallback")
        import numpy as _np
        import hashlib
        class _HashFallback:
            def __init__(self, dim=384):
                self.dim = dim
            def _embed_one(self, text: str):
                h = hashlib.sha256((text or "").encode('utf-8')).digest()
                arr = _np.frombuffer(h, dtype=_np.uint8).astype(_np.float32)
                if arr.size >= self.dim:
                    vec = arr[:self.dim]
                else:
                    reps = _np.ceil(self.dim / arr.size).astype(int)
                    vec = _np.tile(arr, reps)[:self.dim]
                norm = _np.linalg.norm(vec) + 1e-12
                return (vec / norm).tolist()
            def embed_documents(self, texts):
                return [self._embed_one(t) for t in texts]
        _embed_client = _HashFallback()
        return _embed_client

def embed_texts(texts, model_name=None):
    client = get_embedding_client(model_name)
    if hasattr(client, 'embed_documents'):
        return client.embed_documents(texts)
    if hasattr(client, 'embed'):
        return client.embed(texts)
    raise RuntimeError('Embedding client missing')


# Vector store with FAISS fallback
_vs_lock = threading.Lock()
class InMemoryStore:
    def __init__(self):
        self.vectors = []
        self.metadatas = []
    def add(self, vectors, metadatas):
        with _vs_lock:
            self.vectors.extend(vectors)
            self.metadatas.extend(metadatas)
    def search(self, query_vector, top_k=4):
        if not self.vectors:
            return []
        arr = np.array(self.vectors)
        q = np.array(query_vector)
        norms = np.linalg.norm(arr, axis=1) * (np.linalg.norm(q) + 1e-12)
        sims = (arr @ q) / norms
        idx = np.argsort(-sims)[:top_k]
        return [(self.metadatas[i], float(sims[i])) for i in idx]

def create_vectorstore():
    try:
        import faiss
        class FaissStore:
            def __init__(self):
                self.index = None
                self.metadatas = []
            def add(self, vectors, metadatas):
                import numpy as _np
                vecs = _np.array(vectors).astype('float32')
                if self.index is None:
                    d = vecs.shape[1]
                    self.index = faiss.IndexFlatIP(d)
                self.index.add(vecs)
                self.metadatas.extend(metadatas)
            def search(self, query_vector, top_k=4):
                import numpy as _np
                q = _np.array(query_vector).astype('float32').reshape(1, -1)
                D, I = self.index.search(q, top_k)
                results = []
                for score, idx in zip(D[0], I[0]):
                    if idx < 0:
                        continue
                    results.append((self.metadatas[idx], float(score)))
                return results
        return FaissStore()
    except Exception:
        return InMemoryStore()


# SimpleRAG: ingest + retrieve functionality
class SimpleRAG:
    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model
        self.store = create_vectorstore()
    def ingest_documents(self, docs, chunk_size=None, overlap=None):
        if chunk_size is None:
            chunk_size = DEFAULT_CHUNK_SIZE
        if overlap is None:
            overlap = DEFAULT_CHUNK_OVERLAP
        texts = []
        metadatas = []
        for doc in docs:
            content = doc.get('text') or doc.get('content') or ''
            chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
            for i, c in enumerate(chunks):
                texts.append(c)
                meta = dict(doc)
                meta['chunk_index'] = i
                metadatas.append(meta)
        if texts:
            vecs = embed_texts(texts, model_name=self.embedding_model)
            try:
                vec_list = vecs.tolist() if hasattr(vecs, 'tolist') else list(vecs)
            except Exception:
                vec_list = [list(v) for v in vecs]
            self.store.add(vec_list, metadatas)
    def add_documents(self, texts, metadatas=None):
        if not texts:
            return
        logger.info(f"SimpleRAG.add_documents called with {len(texts)} texts")
        docs = [{'text': t} for t in texts]
        logger.info(f"About to call ingest_documents with {len(docs)} docs")
        self.ingest_documents(docs)
        logger.info("ingest_documents completed successfully")
    def retrieve(self, query, top_k=4):
        qv = embed_texts([query], model_name=self.embedding_model)[0]
        return self.store.search(qv, top_k=top_k)
    def search(self, query, top_k=4):
        hits = self.retrieve(query, top_k=top_k)
        results = []
        for meta, score in hits:
            results.append({'text': meta.get('text', ''), 'score': score, 'meta': meta})
        return results
    def build_context(self, docs, query, top_k=4):
        hits = self.retrieve(query, top_k=top_k)
        pieces = [meta.get('text') or meta.get('content') or '' for meta, _ in hits]
        return "\n\n---\n\n".join(pieces)

class SimpleTextRAG:
    def __init__(self):
        self.documents = []
        self.chunks = []
    
    def ingest_documents(self, docs, chunk_size=None, overlap=None):
        if chunk_size is None:
            chunk_size = DEFAULT_CHUNK_SIZE
        if overlap is None:
            overlap = DEFAULT_CHUNK_OVERLAP
            
        for doc in docs:
            content = doc.get('text') or doc.get('content') or ''
            chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
            for i, chunk in enumerate(chunks):
                self.chunks.append({
                    'text': chunk,
                    'source': doc.get('source', 'unknown'),
                    'chunk_index': i
                })
    
    def add_documents(self, texts, metadatas=None):
        if not texts:
            return
        docs = [{'text': t, 'source': 'document'} for t in texts]
        self.ingest_documents(docs)
    
    def search(self, query, top_k=4):
        if not self.chunks:
            return []
            
        # Simple keyword-based search
        query_words = set(query.lower().split())
        results = []
        
        for chunk in self.chunks:
            chunk_words = set(chunk['text'].lower().split())
            # Count matching words
            matches = len(query_words.intersection(chunk_words))
            if matches > 0:
                # Simple scoring based on word matches
                score = matches / len(query_words)
                results.append({
                    'text': chunk['text'],
                    'score': score,
                    'meta': chunk
                })
        
        # Sort by score and return top_k
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]
    
    def retrieve(self, query, top_k=4):
        results = self.search(query, top_k)
        return [(r['meta'], r['score']) for r in results]


# VLM helper
def generate_caption(image_bytes: bytes, prompt: str = None) -> str:
    model = get_model()
    if not model:
        raise RuntimeError("Vision model not available")
    return model.process_image(image_bytes, prompt or "Generate a short alt text:")


# Ingest helpers
from pathlib import Path
from uuid import uuid4
_processed_images_dir = Path("processed")
def extract_from_docx_inline(path: str):
    try:
        from docx import Document as _Doc
    except Exception:
        raise RuntimeError("python-docx is required to extract from .docx files")
    doc = _Doc(path)
    text_parts = [p.text for p in doc.paragraphs]
    images = []
    try:
        for rel in doc.part._rels:
            r = doc.part._rels[rel]
            if "image" in r.target_ref:
                blob = r.target_part.blob
                name = f"{uuid4().hex}.png"
                out_path = _processed_images_dir / name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, 'wb') as fh:
                    fh.write(blob)
                images.append(str(out_path))
    except Exception:
        pass
    return {"text": "\n".join(text_parts), "images": images, "meta": {"source": path}}

def extract_from_pptx_inline(path: str):
    try:
        from pptx import Presentation as _Pres
    except Exception:
        raise RuntimeError("python-pptx is required to extract from .pptx files")
    prs = _Pres(path)
    slides_text = []
    images = []
    for i, slide in enumerate(prs.slides):
        parts = []
        for shape in slide.shapes:
            if hasattr(shape, 'text'):
                parts.append(shape.text)
            if getattr(shape, 'shape_type', None) and hasattr(shape, 'image'):
                try:
                    img = shape.image
                    ext = img.ext
                    blob = img.blob
                    name = f"{uuid4().hex}.{ext}"
                    out_path = _processed_images_dir / name
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(out_path, 'wb') as fh:
                        fh.write(blob)
                    images.append(str(out_path))
                except Exception:
                    pass
        slides_text.append("\n".join(parts))
    return {"text": "\n\n".join(slides_text), "images": images, "meta": {"source": path}}

# --- end inlined utilities ---

from src.models.vision_processor import get_model

# Avoid forcing CUDA_VISIBLE_DEVICES here; let environment control device selection.
# Hopper-specific optimizations are enabled when USE_HOPPER=1 in the environment.

# Defaults and tunables
MAX_CHUNKS = int(os.environ.get("AGENT_MAX_CHUNKS", 1000))
DEFAULT_CHUNK_SIZE = int(os.environ.get("AGENT_CHUNK_SIZE", 512))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("AGENT_CHUNK_OVERLAP", 64))
DEFAULT_MAX_WORKERS = min(4, (os.cpu_count() or 1))

# Caches and locks
_rag_model_cache = None
_rag_lock = threading.Lock()
_results_lock = threading.Lock()

# Module logger
logger = logging.getLogger(__name__)

def preprocess_image(image_bytes, max_size=None):
    """GPU-agnostic image preprocessing"""
    try:
        # Adaptive max_size based on available GPU memory
        if max_size is None:
            if torch.cuda.is_available():
                gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
                if gpu_memory_gb > 40:  # High-end GPU
                    max_size = 768
                elif gpu_memory_gb > 16:  # Mid-range GPU  
                    max_size = 512
                else:  # Lower-end GPU
                    max_size = 384
            else:
                max_size = 384  # Conservative for CPU
        
        with io.BytesIO(image_bytes) as img_stream:
            image = Image.open(img_stream)
            image = image.convert('RGB')
            image = image.resize((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Adjust quality based on GPU capability
            quality = 95 if torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory / 1e9 > 16 else 85
            
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG', quality=quality)
            return img_byte_arr.getvalue()
    except Exception as e:
        logger.error(f"Error preprocessing image: {e}")
        return image_bytes

def limit_chunks(texts, max_chunks=MAX_CHUNKS):
    """Limit chunks to avoid huge embedding workloads"""
    if not texts or len(texts) <= max_chunks:
        return texts
    
    logger.warning(f"Too many chunks ({len(texts)}). Merging to <= {max_chunks}")
    factor = math.ceil(len(texts) / max_chunks)
    merged = []
    for i in range(0, len(texts), factor):
        merged.append(" ".join(texts[i:i + factor]))
    return merged

import shutil
from pathlib import Path

def clear_model_cache(model_id):
    """Clear cached files for a specific model"""
    try:
        # Common cache directories
        cache_dirs = [
            Path.home() / ".cache" / "huggingface" / "hub",
            Path.home() / ".cache" / "huggingface" / "transformers", 
            Path(os.environ.get("HF_HOME", "")) / "hub" if os.environ.get("HF_HOME") else None,
            Path(os.environ.get("TRANSFORMERS_CACHE", "")) if os.environ.get("TRANSFORMERS_CACHE") else None,
        ]
        
        # Remove None entries
        cache_dirs = [d for d in cache_dirs if d is not None]
        
        for cache_dir in cache_dirs:
            if cache_dir.exists():
                # Look for model-specific directories
                for item in cache_dir.iterdir():
                    if item.is_dir() and model_id.replace("/", "--") in item.name:
                        logger.info(f"Removing cached model directory: {item}")
                        shutil.rmtree(item, ignore_errors=True)
                        
                    # Also check for files with model name
                    elif item.is_file() and model_id.replace("/", "--") in item.name:
                        logger.info(f"Removing cached model file: {item}")
                        item.unlink(missing_ok=True)
                        
    except Exception as e:
        logger.warning(f"Failed to clear cache for {model_id}: {e}")

def get_rag_model():
    """Get cached RAG model or create new one with automatic cache cleanup on failures"""
    global _rag_model_cache
    with _rag_lock:
        if _rag_model_cache is not None:
            return _rag_model_cache
            
        # Force SimpleRAG to avoid disk space issues if requested
        if os.environ.get("FORCE_SIMPLE_RAG") == "1" or not BYALDI_AVAILABLE:
            try:
                logger.info("Using SimpleTextRAG (bypassing byaldi)")
                _rag_model_cache = SimpleTextRAG()
                return _rag_model_cache
            except Exception as e:
                logger.warning(f"Failed to initialize SimpleTextRAG: {e}")
                return None

        # Model candidates - try them all
        env_model = os.environ.get("RAG_MODEL")
        candidates = []
        
        if env_model:
            candidates.append(env_model)
        
        candidates += [
            "vidore/colqwen2-v1.0",
            "vidore/colpali-v1.2", 
            "vidore/colpali",
            "vidore/colsmolvlm",
        ]

        def _safe_from_pretrained(loader_cls, model_id, **kws):
            try:
                return loader_cls.from_pretrained(model_id, **kws)
            except Exception as e:
                # If loading fails, clear the cache and try once more
                logger.warning(f"Model loading failed for {model_id}: {e}")
                logger.info(f"Clearing cache and retrying {model_id}")
                clear_model_cache(model_id)
                
                # Retry once with cleared cache
                try:
                    return loader_cls.from_pretrained(model_id, **kws)
                except Exception as e2:
                    logger.warning(f"Retry after cache clear also failed for {model_id}: {e2}")
                    raise e2

        # Try loading models
        use_optimizations = torch.cuda.is_available() and os.environ.get("USE_ADVANCED_OPTIMIZATIONS", "1") == "1"
        
        for model_id in candidates:
            try:
                kwargs = {}
                if use_optimizations:
                    kwargs.update({
                        "torch_dtype": torch.bfloat16,
                        "attn_implementation": "flash_attention_2",
                    })
                    
                logger.info(f"Attempting to load RAG model '{model_id}'")
                _rag_model_cache = _safe_from_pretrained(RAGMultiModalModel, model_id, **kwargs)
                logger.info(f"Successfully loaded RAG model: {model_id}")
                return _rag_model_cache
                
            except Exception as e:
                logger.warning(f"Failed to load RAG model '{model_id}': {e}")
                # Clear cache for this failed model
                clear_model_cache(model_id)
                _rag_model_cache = None

        logger.warning("No RAG model loaded after trying all candidates; falling back to SimpleRAG")
        
        # Final fallback to SimpleRAG
        try:
            _rag_model_cache = SimpleTextRAG()
            logger.info("Using SimpleTextRAG fallback after all model candidates failed")
            return _rag_model_cache
        except Exception as e:
            logger.warning(f"Failed to initialize SimpleTextRAG fallback: {e}")
            return None

def _detect_gpu_for_rag():
    """Detect GPU capabilities for RAG model selection"""
    if not torch.cuda.is_available():
        return {
            "architecture": "cpu",
            "can_handle_large_models": False,
            "use_optimizations": False,
            "dtype": torch.float32,
            "attention": "eager"
        }
    
    gpu_name = torch.cuda.get_device_name(0).lower()
    gpu_capability = torch.cuda.get_device_capability(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1e9  # GB
    
    # Determine capabilities - FIXED MEMORY THRESHOLDS
    if "h100" in gpu_name or "hopper" in gpu_name:
        arch = "hopper"
        can_handle_large = True  # H100 can handle large models regardless of allocated memory
        use_optimizations = True
    elif ("a100" in gpu_name or "ampere" in gpu_name) and total_memory > 15:  # Lowered from 30
        arch = "ampere"
        can_handle_large = True
        use_optimizations = True
    elif "v100" in gpu_name and total_memory > 8:  # Lowered from 15
        arch = "volta"
        can_handle_large = False
        use_optimizations = False
    elif total_memory > 6:  # Lowered from 8
        arch = "generic"
        can_handle_large = False
        use_optimizations = False
    else:
        arch = "limited"
        can_handle_large = False
        use_optimizations = False
    
    # Override from environment
    use_advanced = os.environ.get("USE_ADVANCED_OPTIMIZATIONS", "1" if use_optimizations else "0") == "1"
    
    return {
        "architecture": arch,
        "can_handle_large_models": can_handle_large,
        "use_optimizations": use_advanced and use_optimizations,
        "dtype": torch.bfloat16 if use_advanced and use_optimizations else torch.float16 if gpu_capability[0] >= 7 else torch.float32,
        "attention": "flash_attention_2" if use_advanced and use_optimizations else "eager"
    }

def extract_docx_metadata(file_path):
    """Extract metadata from DOCX file"""
    logger.info(f"Processing DOCX file: {file_path}")
    doc = Document(file_path)
    all_text = []
    headings = []
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            all_text.append(text)
            if para.style.name.startswith("Heading"):
                headings.append(text)
    
    # Create text chunks
    if RecursiveCharacterTextSplitter is None:
        texts = ['\n'.join(all_text)]
    else:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE,
            chunk_overlap=DEFAULT_CHUNK_OVERLAP
        )
        texts = text_splitter.split_text('\n'.join(all_text))
    texts = limit_chunks(texts, MAX_CHUNKS)
    
    # Initialize RAG model if available
    rag_model = get_rag_model()
    print(f"Using RAG Model: {rag_model}")
    if rag_model and texts:
        try:
            # Check if it's SimpleRAG or byaldi model
            if hasattr(rag_model, 'add_documents'):
                rag_model.add_documents(texts)
                logger.info(f"Added {len(texts)} text chunks to SimpleRAG")
            elif hasattr(rag_model, 'ingest_documents'):
                docs = [{'text': text, 'source': 'document'} for text in texts]
                rag_model.ingest_documents(docs)
                logger.info(f"Added {len(docs)} documents to RAG model")
            else:
                logger.warning("RAG model doesn't have expected methods")
                rag_model = None
        except Exception as e:
            logger.warning(f"Failed to add documents to RAG model: {e}")
            logger.exception("Full RAG error details:")
            rag_model = None
    
    # Extract keywords
    words = ' '.join(all_text).lower()
    stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
                 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'of', 'this', 'that'}
    word_list = re.findall(r'\b[a-z]{3,}\b', words)
    word_list = [word for word in word_list if word not in stop_words]
    word_freq = Counter(word_list)
    keywords = [word for word, count in word_freq.most_common(10)]
    
    return {
        "all_text": all_text,
        "headings": headings,
        "keywords": keywords,
        "rag_model": rag_model
    }

def extract_pptx_metadata(file_path):
    """Extract metadata from PPTX file"""
    pres = Presentation(file_path)
    all_text = []
    slide_headers = []
    
    for slide_num, slide in enumerate(pres.slides, start=1):
        slide_text = []
        header = ""
        
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                text = shape.text.strip()
                slide_text.append(text)
                if not header:
                    header = text.split('\n')[0]
        
        all_text.append(" ".join(slide_text))
        slide_headers.append(header)
    
    # Create chunks with slide context
    formatted_text = []
    for slide_num, (text, header) in enumerate(zip(all_text, slide_headers), start=1):
        formatted_text.append(f"Slide {slide_num} - {header}:\n{text}")
    
    if RecursiveCharacterTextSplitter is None:
        texts = ['\n\n'.join(formatted_text)]
    else:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE,
            chunk_overlap=DEFAULT_CHUNK_OVERLAP
        )
        texts = text_splitter.split_text('\n\n'.join(formatted_text))
    texts = limit_chunks(texts, MAX_CHUNKS)
    
    # Initialize RAG model
    # Initialize RAG model
    rag_model = get_rag_model()
    print(f"Using RAG Model: {rag_model}")
    if rag_model and texts:
        try:
            # Check if it's SimpleRAG or byaldi model (same as DOCX)
            if hasattr(rag_model, 'add_documents'):
                rag_model.add_documents(texts)
                logger.info(f"Added {len(texts)} text chunks to SimpleRAG")
            elif hasattr(rag_model, 'ingest_documents'):
                docs = [{'text': text, 'source': 'document'} for text in texts]
                rag_model.ingest_documents(docs)
                logger.info(f"Added {len(docs)} documents to RAG model")
            else:
                logger.warning("RAG model doesn't have expected methods")
                rag_model = None
        except Exception as e:
            logger.warning(f"Failed to add documents to RAG model: {e}")
            logger.exception("Full RAG error details:")
            rag_model = None
    
    # Extract keywords
    words = ' '.join(all_text).lower()
    stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
                 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'of', 'this', 'that'}
    word_list = re.findall(r'\b[a-z]{3,}\b', words)
    word_list = [word for word in word_list if word not in stop_words]
    word_freq = Counter(word_list)
    keywords = [word for word, count in word_freq.most_common(10)]
    
    return {
        "all_text": all_text,
        "slide_headers": slide_headers,
        "keywords": keywords,
        "rag_model": rag_model
    }

def document_summarize(text, headings=None, keywords=None, doc_type="document"):
    """Create a simple document summary"""
    try:
        if isinstance(text, list):
            text = "\n".join(text)
        
        summary_parts = []
        if doc_type:
            summary_parts.append(f"This is a {doc_type}")
        if headings:
            summary_parts.append(f"with sections including: {', '.join(headings[:3])}")
        if keywords:
            summary_parts.append(f"covering topics: {', '.join(keywords[:5])}")
        
        return " ".join(summary_parts) if summary_parts else f"A {doc_type} document"
    except Exception as e:
        logger.error(f"Error in document_summarize: {e}")
        return f"A {doc_type} document"

def retrieve_context(rag_model, query, k=3):
    """Retrieve relevant context using RAG model"""
    if not rag_model:
        return "", []
    
    try:
        results = rag_model.search(query, top_k=k)
        texts = [r.get("text", "") for r in results if r.get("text")]
        combined = "\n".join(texts[:k])
        return combined, results
    except Exception as e:
        logger.warning(f"Retrieval failed: {e}")
        return "", []
def classify_and_generate_alt_text(image_bytes, context_text="", rag_model=None):
    """Classify image and generate alt text in one call"""
    logger.info(f"Starting classify_and_generate_alt_text with context: '{context_text[:100]}...'")
    
    try:
        processed_image = preprocess_image(image_bytes)
        logger.info("Image preprocessing completed")

        # Get RAG context if available
        rag_context = ""
        if rag_model and context_text:
            logger.info(f"Attempting RAG retrieval with model type: {type(rag_model)}")
            query = f"Find content related to visual elements or images: {context_text}"
            rag_context, _ = retrieve_context(rag_model, query, k=2)
            logger.info(f"RAG context retrieved: '{rag_context[:100]}...'")

        # Combine contexts
        full_context = context_text or ""
        if rag_context:
            full_context = f"{full_context}\n\nAdditional context:\n{rag_context}"

        # Create prompt for both classification and alt text
        prompt = (
            "Analyze this image and provide:\n"
            "1. Category (choose from: Graph, Chart, Map, Diagram, Table, Photograph, Text, Screenshot, Equation, Other)\n"
            "2. Brief alt text description (under 125 characters)\n"
            f"Context: {full_context[:500]}\n"
            "Format: Category: [category]\nAlt text: [description]"
        )
        logger.info(f"Created prompt: {prompt[:200]}...")

        # Process with SmolVLM
        logger.info("Getting vision model...")
        model = get_model()
        if not model:
            logger.warning("Vision model unavailable; returning fallback alt text")
            return ["Other"], "Image"

        logger.info(f"Vision model device: {model.device}, Model type: {type(model)}")
        
        logger.info("Calling model.process_image...")
        result = model.process_image(processed_image, prompt)
        logger.info(f"Vision model returned: '{result}'")

        # Parse result
        categories = ["Other"]
        alt_text = "Image"

        if result:
            lines = result.strip().split('\n')
            for line in lines:
                if line.startswith("Category:"):
                    cat = line.replace("Category:", "").strip()
                    if cat in ["Graph", "Chart", "Map", "Diagram", "Table", "Photograph", "Text", "Screenshot", "Equation", "Other"]:
                        categories = [cat]
                elif line.startswith("Alt text:"):
                    alt_text = line.replace("Alt text:", "").strip()

        logger.info(f"Final result - Categories: {categories}, Alt text: '{alt_text}'")
        return categories, alt_text

    except Exception as e:
        logger.error(f"Error in classify_and_generate_alt_text: {e}")
        logger.exception("Full traceback:")
        return ["Other"], "Image"
    finally:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

def run_agent_pipeline(file_path, ext, progress_callback=None, partial_save_dir=None, rag_strategy='rag'):
    """Main pipeline function: extracts context, runs RAG if available, processes images and returns results."""
    pipeline_start = time.time()
    logger.info(f"Starting pipeline for {file_path}")

    # Extract metadata and setup RAG
    if ext == ".pptx":
        meta = extract_pptx_metadata(file_path)
        summary = document_summarize(
            meta["all_text"],
            headings=meta["slide_headers"],
            keywords=meta["keywords"],
            doc_type="PowerPoint presentation",
        )
        slide_headers = meta["slide_headers"]
    elif ext == ".docx":
        meta = extract_docx_metadata(file_path)
        summary = document_summarize(
            meta["all_text"],
            headings=meta["headings"],
            keywords=meta["keywords"],
            doc_type="Word document",
        )
        slide_headers = None
    else:
        logger.warning("Unsupported file extension for pipeline")
        return []

    rag_model = meta.get("rag_model")
    logger.info(f"Processing document with context: {summary}")

    # Collect image extraction tasks
    results = []
    image_tasks = []

    if ext == ".pptx":
        pres = Presentation(file_path)
        for slide_num, slide in enumerate(pres.slides, start=1):
            for shape in slide.shapes:
                if getattr(shape, "shape_type", None) == 13:  # PICTURE
                    img_bytes = shape.image.blob
                    existing_alt = shape._element._nvXxPr.cNvPr.attrib.get("descr", "")
                    image_tasks.append((img_bytes, existing_alt, slide_num))
    elif ext == ".docx":
        doc = Document(file_path)
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                img_bytes = rel.target_part.blob
                image_tasks.append((img_bytes, "", None))

    total_images = len(image_tasks)
    if total_images == 0:
        logger.info("No images found in document")
        return []

    logger.info(f"Processing {total_images} images...")
    processed_images = 0

    def process_single_image(task_idx, img_bytes, existing_alt, slide_num):
        nonlocal processed_images
        try:
            context_text = ""
            if slide_num and slide_headers and 0 <= slide_num - 1 < len(slide_headers):
                context_text = slide_headers[slide_num - 1]

            categories, alt_text = classify_and_generate_alt_text(img_bytes, context_text, rag_model)

            if not alt_text or alt_text == "Image":
                alt_text = existing_alt or f"Image {task_idx + 1}"

            # Increment processed count and report progress
            with _results_lock:
                processed_images += 1
                current_processed = processed_images

            if progress_callback:
                progress_callback(f"Processing image {current_processed}/{total_images}", current_processed, total_images)

            result = {"classification": categories, "alt_text": alt_text, "image_idx": task_idx + 1}
            if slide_num is not None:
                result["slide_num"] = slide_num

            # Write per-image partial results if requested
            if partial_save_dir:
                try:
                    images_dir = os.path.join(partial_save_dir, "images")
                    os.makedirs(images_dir, exist_ok=True)
                    out_path = os.path.join(images_dir, f"{task_idx+1}.json")
                    with _results_lock:
                        with open(out_path, "w", encoding="utf-8") as fh:
                            json.dump(result, fh)
                except Exception:
                    logger.debug("Failed to write partial image result")

            return result

        except Exception as e:
            logger.error(f"Error processing image {task_idx+1}: {e}")
            return {
                "classification": ["Other"],
                "alt_text": existing_alt or f"Image {task_idx+1}",
                "image_idx": task_idx + 1,
                "slide_num": slide_num,
                "error": str(e),
            }

    # Run tasks with controlled concurrency
    max_workers = int(os.environ.get("AGENT_MAX_WORKERS", DEFAULT_MAX_WORKERS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_single_image, idx, img, alt, slide) for idx, (img, alt, slide) in enumerate(image_tasks)]
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                with _results_lock:
                    results.append(res)
            except Exception as e:
                logger.error(f"Error processing image task: {e}")

    if progress_callback:
        progress_callback("Processing complete", processed_images, total_images)

    logger.info(f"Successfully processed {len(results)} images in {time.time() - pipeline_start:.2f}s")
    return results
