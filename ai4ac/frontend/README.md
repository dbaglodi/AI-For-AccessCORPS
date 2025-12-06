# **Document Remediation Frontend**

The frontend is a modern **Angular** application designed to provide an accessible and intuitive interface for document remediation. It allows users to review AI-generated alt text, verify image classifications, and edit descriptions before finalizing the document.

## **Prerequisites**

Before starting, ensure you have the following installed:

* **Node.js**: Version **18 LTS** or **20 LTS** (Recommended).  
* **NPM**: Usually included with Node.js.  
* **Angular CLI**: Install globally using:  
  npm install \-g @angular/cli

## **Installation**

1. Navigate to the frontend directory:  
   cd frontend

2. Install project dependencies:  
   npm install

## **Running the Application**

### **Development Server**

Run the application in development mode with live reloading:  
ng serve

* Open your browser to http://localhost:4200.  
* The app will automatically reload if you change any source files.

### **Build for Production**

To build the project for deployment (output artifacts will be stored in the dist/ directory):  
ng build \--configuration production

## **Application Structure**

* **src/app/app.ts**: Main component logic handling file uploads, polling for status, and managing the image review state.  
* **src/app/app.html**: The HTML template defining the layout, carousel, and form inputs.  
* **src/app/app.scss**: Styling for the application components.  
* **src/app/app.config.ts**: Angular application configuration (providers, routing).

## **Features**

* **File Upload:** Drag-and-drop or file selection for .docx and .pptx files.  
* **Real-time Progress:** Displays detailed status steps during backend processing.  
* **Image Carousel:** Navigate through extracted images with "Previous" and "Next" controls or direct jump buttons.  
* **Alt Text Editor:** Review generated text, revert to original/generated versions, or clear text completely.  
* **Tags Display:** Shows AI-generated classification tags (e.g., "Graph", "Chart").  
* **Download:** One-click download of the fully remediated document.