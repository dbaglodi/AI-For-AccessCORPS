import torch
from PIL import Image
from transformers import AutoProcessor, PaliGemmaForConditionalGeneration
from peft import PeftModel
import os

# Run for text generation for images with finetuned model

# -------- PATHS --------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_ID = "google/paligemma2-3b-pt-224"
ADAPTER_PATH = os.path.join(BASE_DIR, "..", "paligemma-alttext-lora", "adapter")
# Input whatever image you want into want_generation folder in this directory and replace the name to get the generation
IMAGE_PATH = os.path.join(BASE_DIR, "..", "want_generation", "2_graphs.png")

# -------- DEVICE --------
device = "cuda" if torch.cuda.is_available() else "cpu"

# -------- LOAD PROCESSOR --------
processor = AutoProcessor.from_pretrained(MODEL_ID)

# -------- LOAD BASE MODEL --------
model = PaliGemmaForConditionalGeneration.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
).to(device)

# -------- LOAD LORA ADAPTER --------
model = PeftModel.from_pretrained(model, ADAPTER_PATH)
model.eval()

# -------- LOAD IMAGE --------
image = Image.open(IMAGE_PATH).convert("RGB")

prompt = "<image> Write alt text for this image."

inputs = processor(
    images=image,
    text=prompt,
    return_tensors="pt"
).to(device)

# -------- GENERATE --------
with torch.inference_mode():
    output = model.generate(
        **inputs,
        max_new_tokens=100,
        do_sample=False
    )

result = processor.decode(output[0], skip_special_tokens=True)
print("\nGenerated Alt Text:\n")
print(result)