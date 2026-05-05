# Document Remediation Backend

The backend is a **FastAPI** application that serves as the core processing engine. It utilizes advanced AI models (PaliGemma, SmolVLM, Gemini) and agentic workflows to analyze documents, classify images, and generate accessibility descriptions (alt text), equations (MathML), and Tables.

## Deployment Architecture: Render vs. GPU Cloud

### Current Render Deployment (CPU Only)

The backend is currently deployed on Render's free tier.

* **Constraint:** No GPUs are available.
* **Impact:** Attempting to load PyTorch weights for PaliGemma or SmolVLM locally will result in extremely slow inference or Out-Of-Memory (OOM) crashes.
* **Workaround:** The frontend is configured to force all cloud requests through the Google Gemini API to bypass local model loading entirely.

### Future GPU Cloud Migration

To fully utilize the PyTorch vision models, the backend should be migrated to a GPU instance (e.g., AWS EC2 G4dn/G5 instances, Google Cloud Compute Engine with T4/L4 GPUs, RunPod, or Lambda Labs).

**Migration Steps:**

1. Provision a Linux instance with at least an 8GB NVIDIA GPU (16GB+ recommended).
2. Install NVIDIA CUDA drivers (12.1+).
3. Clone the repository and run the standard installation steps below.
4. Expose port 8000 (or configure a reverse proxy like Nginx/Caddy with SSL).
5. Update the `apiUrl` in the Angular frontend to point to the new IP/Domain and disable the Vercel cloud lock.

## Integrating Custom Fine-Tuned Models (Roadmap)

The codebase is currently configured with placeholders to seamlessly integrate your custom **ResNet** classification model and your **Fine-Tuned PaliGemma** model once they are ready and deployed on a GPU host.

### Steps to Activate Custom Models

1. **Load Weights:** Place your trained model weights inside the backend directory (e.g., `src/models/weights/resnet.pt` and `src/models/weights/finetuned-paligemma`).
2. **Update Model Loader:** Open `src/pipelines/agent_pipeline.py`. Navigate to the `get_primary_model()` function. Locate the `[PLACEHOLDER START: Load Custom Models]` block and instantiate your models.
3. **Activate ResNet Classification:** Inside `classify_and_generate_alt_text()`, locate the `[PLACEHOLDER START: Use ResNet for Classification]` block. Replace the temporary base PaliGemma prompt logic with your ResNet inference logic.
4. **Activate Fine-Tuned PaliGemma:** In the same function, under the `USE FINE-TUNED MODEL` block, swap the standard `model.generate(...)` call with `finetuned_model.generate(...)`.

## System Requirements (For Local/GPU Hosting)

* **GPU:** NVIDIA GPU with CUDA support (8GB VRAM minimum, 16GB+ recommended).  
* **RAM:** 16GB system RAM minimum.  
* **OS:** Linux (Ubuntu 22.04+) or Windows 10/11 (WSL2).  
* **Python:** Version **3.10** or higher.  

## Installation & Setup

1. **Create a Virtual Environment:** ```bash

   # Windows

   python -m venv venv
   .\venv\Scripts\activate

   # Linux/macOS

   python3 -m venv venv
   source venv/bin/activate

   ```

2. **Install Dependencies in Order:**
   To prevent dependency conflicts with GPU libraries, install the requirements in this exact sequence:

   ```bash
   pip install -r requirements/requirements.txt
   pip install -r requirements/requirements2.txt
   pip install -r requirements/requirements_web.txt
   ```

3. **Environment Configuration:** Create a `.env` file in the root of the `backend/` directory:

   ```env
   # Optional: API Key for Google Gemini. 
   # Not strictly required for the web app, as the frontend prompts the user for this key per-session.
   # Only needed if you are running backend scripts directly from the CLI for testing.
   GOOGLE_API_KEY=your_google_api_key_here
   
   # Hugging Face Token (Required for downloading gated local models like PaliGemma)  
   HF_TOKEN=your_hf_token_here
   
   # Strategy Configuration  
   AGENT_RAG_STRATEGY=rag
   ```

## Running the Server

Run the following command to start the backend locally:

```bash
python run_server.py
```

The API will be available at `http://localhost:8000`.

## Key Features & Endpoints

* **POST `/upload`**: Accepts `.docx` and `.pptx` files. Extracts images, slide titles, and surrounding text context. Accepts Custom Slide Ranges for PPTX.
* **GET `/status/{file_id}`**: Poll for processing progress (0-100%).  
* **GET `/images/{file_id}`**: Retrieve processed image data, classifications, and generated alt text.
* **POST `/api/regenerate-image/{file_id}`**: Force an image through a specific pipeline (e.g., Table extraction, Equation generation) and update the result.
* **POST `/alt-text/{file_id}`**: Save user-edited alt text back to the server.  
* **GET `/download/{file_id}`**: Generate and download the final remediated document with embedded alt text, MathML equations, and accessible tables.
