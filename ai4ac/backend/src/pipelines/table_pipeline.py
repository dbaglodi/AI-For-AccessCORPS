import io
import logging
import numpy as np
from PIL import Image
import torch
from transformers import (
    TableTransformerForObjectDetection,
    DetrImageProcessor,
)

# Optional: for cell text OCR
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "pytesseract not installed. Cell text will be empty. "
        "Install with: pip install pytesseract"
    )

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx.util import Pt

logger = logging.getLogger(__name__)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_table_models = None


def get_table_models():
    """Lazy-load Table Transformer models."""
    global _table_models
    if _table_models is not None:
        return _table_models

    logger.info(f"Loading Table Transformer models on {DEVICE}...")
    try:
        # Structure recognition model (identifies rows, columns, cells)
        processor = DetrImageProcessor.from_pretrained(
            "microsoft/table-transformer-structure-recognition-v1.1-all",
            size={"height": 800, "width": 800}  # explicit h/w instead of longest_edge
        )
        model = TableTransformerForObjectDetection.from_pretrained(
            "microsoft/table-transformer-structure-recognition-v1.1-all"
        ).to(DEVICE)
        model.eval()

        _table_models = {"processor": processor, "model": model}
        logger.info("✅ Table Transformer loaded successfully.")
        return _table_models
    except Exception as e:
        logger.error(f"Failed to load Table Transformer: {e}")
        return None


def _get_cell_text(img: Image.Image, bbox: list[float]) -> str:
    if not TESSERACT_AVAILABLE:
        return ""
    x0, y0, x1, y1 = [int(v) for v in bbox]
    x0, y0 = max(0, x0 - 2), max(0, y0 - 2)
    x1, y1 = min(img.width, x1 + 2), min(img.height, y1 + 2)
    
    # Add these temporarily
    logger.info(f"Cropping cell: ({x0},{y0}) -> ({x1},{y1}) from image size {img.size}")
    
    if x1 <= x0 or y1 <= y0:
        logger.warning("Cell crop has zero or negative dimensions — skipping")
        return ""
    
    cell_img = img.crop((x0, y0, x1, y1))
    
    # Save first few crops to inspect visually
    cell_img.save(f"/tmp/debug_cell_{x0}_{y0}.png")
    
    text = pytesseract.image_to_string(cell_img, config="--psm 7").strip()
    logger.info(f"OCR result: '{text}'")
    return text


def _boxes_to_grid(
    row_boxes: list, col_boxes: list, cell_boxes: list, img: Image.Image
) -> list[list[str]]:
    """
    Given sorted row/column bounding boxes, assign each detected cell
    to a (row, col) slot and OCR the text inside.
    """
    # Sort rows top-to-bottom, columns left-to-right
    row_boxes = sorted(row_boxes, key=lambda b: b[1])
    col_boxes = sorted(col_boxes, key=lambda b: b[0])

    n_rows, n_cols = len(row_boxes), len(col_boxes)
    if n_rows == 0 or n_cols == 0:
        return []

    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]

    def center(box):
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def nearest_idx(centers, val):
        return int(np.argmin([abs(c - val) for c in centers]))

    row_centers = [(b[1] + b[3]) / 2 for b in row_boxes]
    col_centers = [(b[0] + b[2]) / 2 for b in col_boxes]

    for cell_box in cell_boxes:
        cx, cy = center(cell_box)
        r = nearest_idx(row_centers, cy)
        c = nearest_idx(col_centers, cx)
        if grid[r][c] == "":  # avoid overwriting with duplicates
            grid[r][c] = _get_cell_text(img, cell_box)

    return grid


def extract_table_from_image(image_bytes: bytes) -> list[list[str]]:
    models = get_table_models()
    if not models:
        return []

    try:
        img_original = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        
        # Explicitly resize to match what the processor uses internally
        img_resized = img_original.resize((800, 800), Image.Resampling.LANCZOS)
        
        # Run detection on the resized image
        inputs = models["processor"](images=img_resized, return_tensors="pt").to(DEVICE)
        
        with torch.no_grad():
            outputs = models["model"](**inputs)

        # target_sizes must match what was actually fed to the model
        target_sizes = torch.tensor([[800, 800]], device=DEVICE)
        results = models["processor"].post_process_object_detection(
            outputs, threshold=0.7, target_sizes=target_sizes
        )[0]

        id2label = models["model"].config.id2label
        row_boxes, col_boxes, cell_boxes = [], [], []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            label_name = id2label[label.item()].lower()
            coords = box.tolist()
            if "row" in label_name and "header" not in label_name:
                row_boxes.append(coords)
            elif "column" in label_name:
                col_boxes.append(coords)
            elif "cell" in label_name:
                cell_boxes.append(coords)

        logger.info(f"Detected {len(row_boxes)} rows, {len(col_boxes)} cols, {len(cell_boxes)} cells")

        if not cell_boxes and row_boxes and col_boxes:
            for r_box in row_boxes:
                for c_box in col_boxes:
                    x0 = max(r_box[0], c_box[0])
                    y0 = max(r_box[1], c_box[1])
                    x1 = min(r_box[2], c_box[2])
                    y1 = min(r_box[3], c_box[3])
                    if x1 > x0 and y1 > y0:
                        cell_boxes.append([x0, y0, x1, y1])

        # Pass img_resized so OCR crops align with detected boxes
        grid = _boxes_to_grid(row_boxes, col_boxes, cell_boxes, img_resized)
        return grid

    except Exception as e:
        logger.error(f"Table extraction failed: {e}")
        return []


def _extract_table_with_paligemma(image_bytes: bytes) -> list[list[str]]:
    """
    Fallback for borderless/complex tables — uses the already-loaded PaliGemma
    to extract table contents as JSON. No extra model needed.
    """
    try:
        # Import here to avoid circular imports
        from src.pipelines.agent_pipeline import get_primary_model
        from src.config.gpu_config import get_gpu_settings

        model_info = get_primary_model()
        if not model_info or not model_info.get("model"):
            return []

        model = model_info["model"]
        processor = model_info["processor"]
        device = get_gpu_settings()["device"]

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        prompt = (
            "<image>\n"
            "Extract the table from this image. "
            "Return ONLY a JSON array of arrays where each inner array is a row "
            "and each string is a cell value. "
            "No markdown, no backticks, just raw JSON."
        )

        inputs = processor(text=prompt, images=img, return_tensors="pt").to(device)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=500)
        raw = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

        # Clean up common model output artifacts
        raw = raw.replace("```json", "").replace("```", "").strip()

        import json
        table_data = json.loads(raw)
        if isinstance(table_data, list) and all(isinstance(r, list) for r in table_data):
            return table_data
        return []

    except Exception as e:
        logger.error(f"PaliGemma table fallback failed: {e}")
        return []

def insert_table_into_docx(doc, inline_shape_element, table_data: list[list[str]], alt_text: str = ""):
    if not table_data or not table_data[0]:
        return

    target_paragraph = None
    for p in doc.paragraphs:
        if inline_shape_element in p._element.xpath('.//wp:inline'):
            target_paragraph = p
            break

    if target_paragraph:
        rows = len(table_data)
        cols = max(len(row) for row in table_data)
        table = doc.add_table(rows=rows, cols=cols)
        table.style = 'Table Grid'
        
        for r, row_data in enumerate(table_data):
            for c, cell_text in enumerate(row_data):
                if c < cols:
                    table.cell(r, c).text = str(cell_text)
                    
        # --- NEW: Apply Alt Text to the Word Table ---
        if alt_text:
            tblDescr = OxmlElement('w:tblDescription')
            tblDescr.set(qn('w:val'), alt_text)
            table._tbl.tblPr.append(tblDescr)
        # ---------------------------------------------
            
        target_paragraph._p.addnext(table._tbl)

def insert_table_into_pptx(slide, image_shape, table_data: list[list[str]], alt_text: str = ""):
    if not table_data or not table_data[0]:
        return

    rows = len(table_data)
    cols = max(len(row) for row in table_data)
    x, y = image_shape.left, image_shape.top
    width, height = image_shape.width, image_shape.height
    
    table_shape = slide.shapes.add_table(rows, cols, x, y, width, height)
    table = table_shape.table

    for r, row_data in enumerate(table_data):
        for c, cell_text in enumerate(row_data):
            if c < cols:
                cell = table.cell(r, c)
                cell.text = str(cell_text)
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)

    # --- NEW: Apply Alt Text to the PowerPoint Table ---
    if alt_text:
        table_shape._element.nvGraphicFramePr.cNvPr.set('descr', alt_text)
    # ---------------------------------------------------

    spTree = slide.shapes._spTree
    spTree.insert(spTree.index(image_shape._element), table_shape._element)