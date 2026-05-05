# **AI for AccessCORPS: Document Remediation**

This project is a comprehensive full-stack solution designed to automate the remediation of documents for accessibility. It leverages advanced AI agents to analyze Microsoft Word (.docx) and PowerPoint (.pptx) files, extract images, classify them, and generate context-aware alternative text (alt text).

## **Current Deployment & Future Roadmap**

The application is currently deployed using a hybrid cloud approach optimized for zero-cost hosting during development, which introduces specific hardware limitations:

* **Frontend:** Hosted on **Vercel** (`ai4ac.vercel.app`).
* **Backend:** Hosted on **Render** (Free Tier).

**Important Limitation:** Because the Render free tier does not provide GPU access, the local **PaliGemma** and **SmolVLM** vision models cannot run in the cloud environment. When accessing the web app via Vercel, the system automatically detects the environment and locks the processing pipeline to use the **Gemini 2.5 Flash Lite API** as a cloud fallback. 

**Migration Roadmap:** To unlock the full potential of the local, privacy-first AI models (including the custom ResNet and fine-tuned PaliGemma models), the backend must be migrated to a GPU-enabled cloud provider (e.g., RunPod, Lambda Labs, AWS EC2 with NVIDIA GPUs, or Google Cloud). Once migrated, the frontend configuration will be updated to point to the new GPU backend, restoring the "Local Provider" option in the UI.

## **System Architecture**

1. **Backend (FastAPI & PyTorch):** * Handles file parsing (python-docx, python-pptx).  
   * **Local Vision Pipeline (GPU Required):** Uses an intelligent routing system. Base **PaliGemma** handles complex diagrams/charts, while future updates will integrate **ResNet** for image classification and a **Fine-Tuned PaliGemma** model for domain-specific general images.
   * **Cloud/Fallback Pipeline (Gemini API):** Used dynamically when hosted on environments without GPUs (like Render), for document summarization (RAG), and as a robust fallback.
2. **Frontend (Angular):** * Provides a user-friendly interface for uploading files and choosing custom slide ranges.  
   * Automatically detects the deployment environment and locks to Gemini API when hosted on Vercel.
   * Allows human-in-the-loop review, pipeline forcing (regenerating via a specific category), and editing of generated alt text.  

## **Technologies Used**

* **Backend:** Python, FastAPI, PyTorch, Transformers (Hugging Face), LangChain.  
* **AI Models:** * **Vision:** Google PaliGemma 3B & Custom Fine-Tuned Variants (Local).  
  * **Classification:** ResNet (Local Pipeline).
  * **Text/Reasoning:** Google Gemini 2.5 Flash Lite (API-based).  
  * **Fallback Vision:** SmolVLM.  
* **Frontend:** TypeScript, Angular, SCSS.

## **Quick Start Guide**

### **1. Backend Setup**
Navigate to the `backend/` directory and follow the [Backend README](backend/README.md).  

### **2. Frontend Setup**
Navigate to the `frontend/` directory and follow the [Frontend README](frontend/README.md).  

### **3. Usage**
1. Ensure the backend is running on port 8000.  
2. Open the frontend at `http://localhost:4200` (or `ai4ac.vercel.app` for the cloud version).  
3. Upload a document (select specific slides if using a `.pptx`).  
4. Wait for the AI pipeline to process images.  
5. Review the images, tags, and alt text. Use the dropdown to force a specific pipeline (e.g., Equation, Table) and regenerate if needed.  
6. Click **"Save All Alt Texts"** or **"Download Document"** to get your accessible file.