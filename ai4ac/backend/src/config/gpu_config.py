import torch
import os
import logging

logger = logging.getLogger(__name__)

def detect_gpu_capabilities():
    """Detect GPU architecture and return appropriate settings"""
    if not torch.cuda.is_available():
        return {
            "device": "cpu",
            "dtype": torch.float32,
            "attention": "eager",
            "optimizations": False,
            "architecture": "cpu"
        }

    # Check for flash_attn
    try:
        import flash_attn
        flash_attn_available = True
    except ImportError:
        flash_attn_available = False
        logger.warning("flash-attn not found. Falling back to sdpa attention.")

    gpu_name = torch.cuda.get_device_name(0).lower()
    gpu_capability = torch.cuda.get_device_capability(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1e9

    if "h100" in gpu_name or "hopper" in gpu_name:
        arch = "hopper"
        optimizations = True
    elif "a100" in gpu_name or ("a" in gpu_name and gpu_capability[0] >= 8):
        arch = "ampere"
        optimizations = True
    elif "v100" in gpu_name or gpu_capability[0] == 7:
        arch = "volta"
        optimizations = False
    else:
        arch = "legacy"
        optimizations = False

    use_advanced = os.environ.get("USE_ADVANCED_OPTIMIZATIONS", "1" if optimizations else "0") == "1"

    settings = {
        "device": "cuda",
        "architecture": arch,
        "optimizations": use_advanced and optimizations,
        "dtype": torch.bfloat16 if (use_advanced and optimizations) else torch.float16 if gpu_capability[0] >= 7 else torch.float32,
        "attention": "flash_attention_2" if (flash_attn_available and use_advanced and optimizations) else "sdpa",
        "memory_gb": total_memory
    }

    logger.info(f"Detected GPU: {gpu_name} ({arch}) - Memory: {total_memory:.1f}GB")

    return settings

def get_gpu_settings():
    """Get cached GPU settings"""
    if not hasattr(get_gpu_settings, '_cache'):
        get_gpu_settings._cache = detect_gpu_capabilities()
    return get_gpu_settings._cache
