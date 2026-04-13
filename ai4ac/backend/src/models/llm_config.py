import torch
from PIL import Image
import io
import logging
from typing import List, Dict, Any, Optional
from transformers import AutoProcessor, AutoModelForVision2Seq

# Set up device for processing
device = "cuda" if torch.cuda.is_available() else "cpu"

# Initialize model and processor
processor = AutoProcessor.from_pretrained("HuggingFaceTB/SmolVLM-Instruct")
model = AutoModelForVision2Seq.from_pretrained(
    "HuggingFaceTB/SmolVLM-Instruct",
    dtype=torch.bfloat16 if device == "cuda" else torch.float32,
    _attn_implementation="flash_attention_2" if device == "cuda" else "eager",
).to(device)

def process_image_query(image_bytes: bytes, query: str) -> str:
    """Process an image with a text query using SmolVLM"""
    try:
        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Create input messages
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": query}
                ]
            }
        ]

        # Prepare inputs
        prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=prompt, images=[image], return_tensors="pt")
        inputs = inputs.to(device)

        # Generate outputs
        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=500)
            generated_text = processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )[0]

        return generated_text

    except Exception as e:
        logging.error(f"Error in process_image_query: {e}")
        return ""

class SmolVLMLLM:
    """LLM class compatible with CrewAI using SmolVLM for both vision and text"""
    
    def create_chat_completion(self, messages: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        # Extract image and text from the messages
        image_bytes = kwargs.get('tools_args', [None])[0] if 'tools_args' in kwargs else None
        if not image_bytes:
            return {"choices": [{"message": {"content": "No image provided", "role": "assistant"}}]}
            
        # Get the last text message as the query
        query = messages[-1]["content"] if messages else ""
        
        # Process the image with SmolVLM
        response = process_image_query(image_bytes, query)
        
        return {
            "choices": [
                {
                    "message": {
                        "content": response,
                        "role": "assistant"
                    }
                }
            ]
        }
