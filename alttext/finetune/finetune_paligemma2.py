import os
import json
from PIL import Image

import torch
from datasets import load_dataset
from transformers import (
    AutoProcessor,
    PaliGemmaForConditionalGeneration,
    TrainingArguments,
    Trainer,
)
from peft import LoraConfig, get_peft_model
from transformers import BitsAndBytesConfig

# Run for finetuning model

# Load Config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "..", "datasets")

JSONL_PATH = os.path.join(DATASETS_DIR, "hci-alt-text-dataset-20220915.jsonl")
IMAGES_DIR = os.path.join(DATASETS_DIR, "images")

MODEL_ID = "google/paligemma2-3b-pt-224"

PROMPT = "<image> Write alt text for this image."

# Load Dataset
ds = load_dataset("json", data_files=JSONL_PATH, split="train")

def add_image_path(example):
    fname = example["local_uri"][0]
    example["image_path"] = os.path.join(IMAGES_DIR, fname)
    return example

ds = ds.map(add_image_path)

# filter out missing/empty alt text and missing files
def ok(example):
    if example.get("alt_text") is None:
        return False
    if not str(example["alt_text"]).strip():
        return False
    return os.path.exists(example["image_path"])

ds = ds.filter(ok)

# split
ds = ds.train_test_split(test_size=0.02, seed=0)

# -----------------------
# Processor + Model (QLoRA)
# -----------------------
processor = AutoProcessor.from_pretrained(MODEL_ID)

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
)

model = PaliGemmaForConditionalGeneration.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
)

# LoRA adapters
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
)
model = get_peft_model(model, lora_config)

# -----------------------
# Collator (does image resize/crop/pad via processor)
# -----------------------
def collate_fn(batch):
    images = [Image.open(x["image_path"]).convert("RGB") for x in batch]
    prompts = [PROMPT for _ in batch]
    targets = [x["alt_text"] for x in batch]

    # PaliGemma uses "suffix" as the supervised target
    model_inputs = processor(
        images=images,
        text=prompts,
        suffix=targets,
        return_tensors="pt",
        padding=True,
        truncation=True,
    )

    model_inputs["labels"] = model_inputs["input_ids"].clone()
    return {k: v for k, v in model_inputs.items()}

# -----------------------
# Train
# -----------------------
args = TrainingArguments(
    output_dir="paligemma-alttext-lora",
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,
    warmup_ratio=0.03,
    num_train_epochs=1,
    logging_steps=10,
    eval_strategy="steps",
    eval_steps=200,
    save_steps=200,
    save_total_limit=2,
    fp16=not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_bf16_supported(),
    remove_unused_columns=False, 
    report_to="none",
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=ds["train"],
    eval_dataset=ds["test"],
    data_collator=collate_fn,
)

trainer.train()

# save LoRA adapter + processor
trainer.model.save_pretrained("paligemma-alttext-lora/adapter")
processor.save_pretrained("paligemma-alttext-lora/processor")