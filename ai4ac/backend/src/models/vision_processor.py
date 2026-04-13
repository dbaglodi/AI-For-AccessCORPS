from PIL import Image
import io
import logging
import re
from src.config.gpu_config import get_gpu_settings
from src.config.app_config import CUSTOM_CACHE_DIR

logger = logging.getLogger(__name__)

import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import torch
    from transformers import AutoProcessor, AutoModelForVision2Seq
except ImportError:
    torch = None
    AutoProcessor = None
    AutoModelForVision2Seq = None
    logger.warning("Lite mode: vision_processor local models disabled.")

_model_cache = None

def get_model():
    """Load and cache the fallback vision model and processor"""
    global _model_cache
    if _model_cache is not None:
        if _model_cache["model"] is None:
            logger.warning("Fallback model failed to load previously. Returning None.")
            return None
        return _model_cache

    try:
        gpu_settings = get_gpu_settings()
        logger.info(f"Loading fallback vision model with settings: {gpu_settings}")

        model_id = "HuggingFaceTB/SmolVLM-Instruct"
        cache_dir = CUSTOM_CACHE_DIR

        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True, cache_dir=cache_dir)

        attention_impl = "eager" # Required by SmolVLM/Idefics3
        logger.info(f"Setting attention implementation to '{attention_impl}' for fallback model.")

        model = AutoModelForVision2Seq.from_pretrained(
            model_id,
            torch_dtype=gpu_settings["dtype"],
            trust_remote_code=True,
            attn_implementation=attention_impl,
            cache_dir=cache_dir
        )
        model.to(gpu_settings["device"])

        logger.info(f"Successfully loaded fallback vision model: {model_id}")
        _model_cache = {
            "model": model,
            "processor": processor,
            "gpu_settings": gpu_settings
        }
        return _model_cache

    except Exception as e:
        logger.error(f"An unexpected error occurred while loading the fallback model: {e}", exc_info=True)
        _model_cache = {"model": None, "processor": None, "gpu_settings": None}
        return None

def process_image(image_bytes, prompt_text):
    """Process an image using the cached fallback model and processor"""
    model_info = get_model()
    if not model_info:
        logger.error("Fallback model info not available. Cannot process image.")
        return "Error: Fallback model unavailable."

    model = model_info.get("model")
    processor = model_info.get("processor")
    gpu_settings = model_info.get("gpu_settings")

    if not model or not processor or not gpu_settings:
        logger.error("Fallback model components missing. Cannot process image.")
        return "Error: Fallback model unavailable."

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Prompt text already includes <image> token from create_alt_text_prompt in agent_pipeline
        formatted_prompt = prompt_text
        inputs = processor(text=formatted_prompt, images=image, return_tensors="pt").to(gpu_settings["device"])

        with torch.inference_mode():
            # --- START MODIFICATION: Adjust generation parameters for fallback ---
            generation_args = {
                "max_new_tokens": 250,
                 "eos_token_id": processor.tokenizer.eos_token_id if hasattr(processor, 'tokenizer') and hasattr(processor.tokenizer, 'eos_token_id') else None,
                "do_sample": True, # Keep sampling enabled for fallback
                "temperature": 0.2 # Keep low temperature
            }
            # --- END MODIFICATION ---
            generation_args = {k: v for k, v in generation_args.items() if v is not None}

            generated_ids = model.generate(**inputs, **generation_args)

            start_index = inputs['input_ids'].shape[1] if 'input_ids' in inputs else 0
            generated_ids = generated_ids[:, start_index:]

            generated_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

            # Clean up potential model outputs
            if generated_text.startswith("<image>"):
                 generated_text = generated_text[len("<image>"):].strip()
            generated_text = re.sub(r'^["\']|["\']$', '', generated_text)
            # Remove Answer prefix if it appears
            generated_text = re.sub(r"^(Answer:)\s*", "", generated_text, flags=re.IGNORECASE).strip()

            # Remove trailing ellipsis if present from truncation
            if generated_text.endswith("...") and len(generated_text) > 5:
                 last_space = generated_text[:-3].rfind(' ')
                 if last_space != -1:
                     generated_text = generated_text[:last_space]
                 else:
                     generated_text = generated_text[:-3].strip()


        return generated_text

    except Exception as e:
        logger.error(f"Error processing image with fallback model: {e}\nPrompt used:\n{formatted_prompt}", exc_info=True)
        return "Error during fallback image processing."

