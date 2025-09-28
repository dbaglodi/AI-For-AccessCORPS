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
    
    gpu_name = torch.cuda.get_device_name(0).lower()
    gpu_capability = torch.cuda.get_device_capability(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
    
    # Determine architecture and capabilities
    if "h100" in gpu_name or "hopper" in gpu_name:
        arch = "hopper"
        optimizations = True
    elif "a100" in gpu_name or ("a" in gpu_name and gpu_capability[0] >= 8):
        arch = "ampere"
        optimizations = True
    elif "v100" in gpu_name or gpu_capability[0] == 7:
        arch = "volta"
        optimizations = False
    elif gpu_capability[0] >= 6:
        arch = "pascal_or_newer"
        optimizations = False
    else:
        arch = "legacy"
        optimizations = False
    
    # Environment overrides
    use_advanced = os.environ.get("USE_ADVANCED_OPTIMIZATIONS", "1" if optimizations else "0") == "1"
    
    settings = {
        "device": "cuda",
        "architecture": arch,
        "optimizations": use_advanced and optimizations,
        "dtype": torch.bfloat16 if (use_advanced and optimizations) else torch.float16 if gpu_capability[0] >= 7 else torch.float32,
        "attention": "flash_attention_2" if (use_advanced and optimizations) else "sdpa" if gpu_capability[0] >= 7 else "eager",
        "memory_gb": total_memory
    }
    
    logger.info(f"Detected GPU: {gpu_name} ({arch}) - Memory: {total_memory:.1f}GB")
    
    return settings

def get_gpu_settings():
    """Get cached GPU settings"""
    if not hasattr(get_gpu_settings, '_cache'):
        get_gpu_settings._cache = detect_gpu_capabilities()
    return get_gpu_settings._cache
