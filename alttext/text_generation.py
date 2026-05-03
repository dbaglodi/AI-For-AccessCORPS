import torch
from PIL import Image
from transformers import AutoProcessor, PaliGemmaForConditionalGeneration
from peft import PeftModel
import os

# Run for text generation for images with finetuned model

# -------- PATHS --------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_ID = "google/paligemma2-3b-pt-224"
# ADAPTER_PATH = os.path.join(BASE_DIR, "..", "paligemma-alttext-lora", "adapter")
ADAPTER_GRAPH_PATH = os.path.join(BASE_DIR, "paligemma-alttext-lora", "graph", "adapter")
ADAPTER_DIAGRAM_PATH = os.path.join(BASE_DIR, "paligemma-alttext-lora", "diagram", "adapter")
ADAPTER_PHOTOGRAPH_PATH = os.path.join(BASE_DIR, "paligemma-alttext-lora", "photograph", "adapter")
# Input whatever image you want into want_generation folder in this directory and replace the name to get the generation
IMAGE_PATH = os.path.join(BASE_DIR, "..", "want_generation", "cave.jpg")

# -------- DEVICE --------
device = "cuda" if torch.cuda.is_available() else "cpu"

# -------- LOAD PROCESSOR --------
PROCESSOR_PATH = os.path.join(BASE_DIR, "..", "paligemma-alttext-lora", "processor")
processor = AutoProcessor.from_pretrained(PROCESSOR_PATH)

# -------- LOAD BASE MODEL --------
model = PaliGemmaForConditionalGeneration.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
).to(device)

# -------- LOAD LORA ADAPTER --------
model = PeftModel.from_pretrained(model, ADAPTER_DIAGRAM_PATH)
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
        do_sample=False,
        repetition_penalty=1.1,
        no_repeat_ngram_size=3,
    )

prompt_len = inputs["input_ids"].shape[1]
generated_tokens = output[0][prompt_len:]

result = processor.decode(output[0], skip_special_tokens=True)
print("\nGenerated Alt Text:\n")
print(result)