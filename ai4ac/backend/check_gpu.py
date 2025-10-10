import torch

print(f"PyTorch version: {torch.__version__}")
print(f"Is CUDA available? {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA version used by PyTorch: {torch.version.cuda}")
    print(f"Number of GPUs found: {torch.cuda.device_count()}")
    print(f"GPU Name: {torch.cuda.get_device_name(0)}")
else:
    print("\nPyTorch could not find or use your GPU.")