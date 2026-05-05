# Document Remediation Frontend

The frontend is a modern **Angular** application designed to provide an accessible and intuitive interface for document remediation. It allows users to review AI-generated alt text, verify image classifications, enforce specific data pipelines, and edit descriptions before finalizing the document.

## Cloud Deployment & API Configuration

The application is currently deployed on **Vercel** (`ai4ac.vercel.app`) with the backend hosted on **Render**.

### Vercel Mode Limitations

Because the Render backend currently lacks GPU support, the frontend includes environment detection logic in `src/app/app.ts`:
* If the app detects it is running on `ai4ac.vercel.app`, it automatically locks the AI provider to **Gemini**.
* The local PaliGemma dropdown opti
* Users must provide a Gemini API key to process documents.

### Migrating to a GPU Backend

When the backend is moved from Render to a dedicated GPU cloud server (e.g., AWS, GCP, RunPod), you must update the frontend to point to the new backend URL and disable the Vercel lock:

1. Open `src/app/app.ts`.
2. Locate the `apiUrl` property at the top of the `AppComponent` class:
   ```typescript
   // Change this from the Render URL to your new GPU Server URL or IP
   private readonly apiUrl = '[https://ai-for-accesscorps.onrender.com](https://ai-for-accesscorps.onrender.com)'; 
   ```
3. Locate the `ngOnInit()` function and remove or adjust the `isVercelMode` check so the UI allows users to select the `local` (GPU-accelerated) provider again.
4. Rebuild and deploy to Vercel: `ng build --configuration production`

## Prerequisites & Installation

* **Node.js**: Version **18 LTS** or **20 LTS**.  
* **Angular CLI**: Install globally using `npm install -g @angular/cli`.

1. Navigate to the frontend directory: 
   ```bash
   cd frontend
   ```
2. Install project dependencies: 
   ```bash
   npm install
   ```

## Running the Application

### Development Server
Run the application in development mode with live reloading:
```bash
ng serve
```
* Open your browser to `http://localhost:4200`.
* The app will automatically reload if you change any source files.

### Build for Production
To build the project for deployment (output artifacts will be stored in the `dist/` directory):
```bash
ng build --configuration production
```

## Application Structure & Features

* **`src/app/app.ts`**: Main component logic handling file uploads, polling for status, Vercel mode detection, smooth scrolling, and managing the image review state.  
* **`src/app/app.html`**: The HTML template defining the layout, horizontal card scrolling, slide range modals, and form inputs.  
* **`src/app/app.scss`**: Styling for the application components.  
* **File Upload & Parsing:** Drag-and-drop or file selection for `.docx` and `.pptx` files. Includes a modal for selecting custom PowerPoint slide ranges.
* **Pipeline Forcing & Regeneration:** Users can manually override AI classifications (e.g., forcing a standard image to be read as an Equation or Table) and instantly regenerate the extraction using the specified pipeline.
* **Slide Title Management:** Automatically generates missing slide titles, syncs them across the UI, and allows manual editing.
* **Alt Text Editor:** Review generated text, revert to original/generated versions, or clear text completely.  
* **Download:** One-click download of the fully remediated document with embedded alt text, MathML, and Tables.