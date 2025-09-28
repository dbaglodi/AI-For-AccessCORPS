# Document Remediation Project

This repository contains a full-stack solution for document remediation, enabling users to upload `.docx` and `.pptx` files, review and update image alt text, and download accessible, remediated documents. The system uses AI agents for document summarization, image classification, and alt text generation.

## Structure
- `backend/` — FastAPI server, agent pipeline, and all backend logic
- `frontend/` — Angular app for the user interface

## Quick Start

### Backend
1. `cd backend`
2. Create a `.env` file with your API keys (see `backend/README.md`)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the server: `uvicorn main:app --reload`

### Frontend
1. `cd frontend`
2. Install dependencies: `npm install`
3. Start the dev server: `ng serve`
4. Open [http://localhost:4200](http://localhost:4200)

## Features
- Upload `.docx` and `.pptx` files
- AI-powered image classification and alt text generation
- Manual review and editing of alt text
- Download remediated files
- High-contrast, accessible UI

See `backend/README.md` and `frontend/README.md` for more details.
