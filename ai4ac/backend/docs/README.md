# Backend

This folder contains the FastAPI backend for the Document Remediation project.

## Features
- File upload endpoints for `.docx` and `.pptx`
- Image extraction and context analysis
- CrewAI/ACP agent pipeline for document summarization, image classification, and alt text generation
- Endpoints for image/context retrieval, alt text update, and remediated file download

## Setup
1. Create a `.env` file with your API keys (e.g., `GOOGLE_API_KEY`)
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the server:
   ```bash
   uvicorn main:app --reload
   ```

## API Endpoints
- `POST /upload` — Upload a document
- `GET /images/{file_id}` — Get images and context
- `POST /alt-text/{file_id}` — Update alt text
- `GET /download/{file_id}` — Download remediated file

See the root README for full-stack instructions.
