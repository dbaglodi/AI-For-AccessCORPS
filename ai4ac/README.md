# **AI for AccessCORPS: Document Remediation**

This project is a comprehensive full-stack solution designed to automate the remediation of documents for accessibility. It leverages advanced AI agents to analyze Microsoft Word (.docx) and PowerPoint (.pptx) files, extract images, classify them, and generate context-aware alternative text (alt text).

## **System Architecture**

The project consists of two main components:

1. **Backend (FastAPI & PyTorch):**  
   * Handles file parsing (python-docx, python-pptx).  
   * **Primary Vision Model:** Runs the AI pipeline using **PaliGemma** (a lightweight open vision-language model) for local, GPU-accelerated image understanding.  
   * **Assistant/Fallback Model:** Uses **Google Gemini** (via API) for document summarization, RAG (Retrieval-Augmented Generation), and as a robust fallback for complex image analysis.  
   * Manages GPU resources for efficient inference.  
2. **Frontend (Angular):**  
   * Provides a user-friendly interface for uploading files.  
   * Allows human-in-the-loop review and editing of generated alt text.  
   * Visualizes image classifications (tags) and processing status.

## **Technologies Used**

* **Backend:** Python, FastAPI, PyTorch, Transformers (Hugging Face), LangChain.  
* **AI Models:**  
  * **Vision:** Google PaliGemma 3B (Local execution).  
  * **Text/Reasoning:** Google Gemini 2.0 Flash (API-based).  
  * **Fallback Vision:** SmolVLM.  
* **Frontend:** TypeScript, Angular, SCSS.

## **Quick Start Guide**

### **Prerequisites**

* **Operating System:** Windows 10/11 or Linux (Ubuntu 22.04+).  
* **Hardware:** NVIDIA GPU (8GB+ VRAM) with CUDA 12.1 drivers is **highly recommended** for the backend to run PaliGemma efficiently.  
* **Software:** Python 3.10+, Node.js v18+.

### **1\. Backend Setup**

Navigate to the backend/ directory and follow the [Backend README](https://www.google.com/search?q=backend/README.md).  
**Summary:**  
cd backend  
python \-m venv venv  
\# Activate venv (Windows: venv\\Scripts\\activate, Linux: source venv/bin/activate)  
pip install \-r requirements/requirements.txt  
pip install \-r requirements/requirements2.txt  
pip install \-r requirements/requirements\_web.txt  
\# Configure .env file with GOOGLE\_API\_KEY (for Gemini) and HF\_TOKEN (for PaliGemma download)  
python run\_server.py

### **2\. Frontend Setup**

Navigate to the frontend/ directory and follow the [Frontend README](https://www.google.com/search?q=frontend/README.md).  
**Summary:**  
cd frontend  
npm install  
ng serve

### **3\. Usage**

1. Ensure the backend is running on port 8000\.  
2. Open the frontend at http://localhost:4200.  
3. Upload a document.  
4. Wait for the AI pipeline to process images (status will update automatically).  
5. Review the images, tags, and alt text. Edit as needed.  
6. Click **"Save All Alt Texts"** (optional, happens on download) or directly **"Download Document"** to get your accessible file.