# **Document Remediation Backend**

The backend is a **FastAPI** application that serves as the core processing engine. It utilizes advanced AI models (PaliGemma, SmolVLM) and agentic workflows to analyze documents, classify images, and generate accessibility descriptions (alt text).

## **System Requirements**

### **Hardware**

* **GPU (Highly Recommended):** NVIDIA GPU with **CUDA** support.  
  * **VRAM:** Minimum **8GB** required. **16GB+** recommended for optimal performance with vision models.  
  * **Architecture:** Ampere (RTX 30xx/A100) or newer recommended for Flash Attention support.  
* **RAM:** 16GB system RAM minimum.  
* **Storage:** \~10GB free space for model weights and cache.

### **Software**

* **OS:** Linux (Ubuntu 22.04+) or Windows 10/11 (WSL2 is highly recommended for best compatibility).  
* **Python:** Version **3.10** or higher.  
* **CUDA Drivers:** Must match the PyTorch version installed (default is CUDA 12.1).

## **Installation & Setup**

It is strongly recommended to use a virtual environment to manage dependencies.

### **1\. Create a Virtual Environment**

\# Windows  
python \-m venv venv  
.\\venv\\Scripts\\activate

\# Linux / macOS  
python3 \-m venv venv  
source venv/bin/activate

### **2\. Install Dependencies**

Dependencies are split into three files to ensure conflict-free installation of GPU-accelerated libraries. **Install them in this exact order:**

1. **PyTorch & CUDA:**  
   pip install \-r requirements/requirements.txt

2. **Machine Learning & AI Libraries:**  
   pip install \-r requirements/requirements2.txt

3. **Web Server & Utilities:**  
   pip install \-r requirements/requirements\_web.txt

### **3\. Environment Configuration**

Create a .env file in the backend/ directory. You can copy the structure below:  
\# .env file

\# API Key for Google Gemini (Used for RAG and fallback generation)  
GOOGLE\_API\_KEY=your\_google\_api\_key\_here

\# Hugging Face Token (Required for downloading gated models like PaliGemma)  
HF\_TOKEN=your\_hf\_token\_here

\# Strategy Configuration  
AGENT\_RAG\_STRATEGY=rag

\# Optional: GPU Optimization Flags  
\# FORCE\_SDPA=1  \# Uncomment to force SDPA attention if Flash Attention fails

## **Running the Server**

To start the backend server locally:  
\# Ensure your virtual environment is active  
python run\_server.py

Or directly via uvicorn:  
uvicorn src.main:app \--host 0.0.0.0 \--port 8000 \--reload

The API will be available at:

* **API Root:** http://localhost:8000  
* **Swagger Documentation:** http://localhost:8000/docs

## **Key Features & Endpoints**

* **POST /upload**: Accepts .docx and .pptx files. Extracts images, slide titles, and surrounding text context.  
* **GET /status/{file\_id}**: Poll for processing progress (0-100%).  
* **GET /images/{file\_id}**: Retrieve processed image data, classifications, and generated alt text.  
* **POST /alt-text/{file\_id}**: Save user-edited alt text back to the server.  
* **GET /download/{file\_id}**: Generate and download the final remediated document with embedded alt text.

## **Troubleshooting**

* **ImportError: libGL.so.1**: On Linux, install OpenCV dependencies: sudo apt-get install ffmpeg libsm6 libxext6.  
* **CUDA Not Found**: Run python check\_gpu.py to verify PyTorch can see your GPU. Ensure you installed the requirements from requirements.txt first.  
* **Out of Memory (OOM)**: If you have low VRAM, try closing other applications or setting FORCE\_SDPA=1 in your environment.