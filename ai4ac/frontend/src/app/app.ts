import { Component, OnDestroy } from '@angular/core'; // Import OnDestroy
import { HttpClient, HttpEventType, HttpResponse, HttpErrorResponse } from '@angular/common/http'; // Import HttpResponse, HttpErrorResponse
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { interval, Subscription } from 'rxjs'; // Import interval and Subscription
import { switchMap, takeWhile } from 'rxjs/operators'; // Import operators


@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrls: ['./app.scss']
})
export class AppComponent implements OnDestroy { // Implement OnDestroy
  selectedFile: File | null = null;
  uploadProgress: number = 0;
  fileId: string | null = null;
  images: any[] = [];
  // index of the active/centered card in the carousel
  activeIndex: number = 0;
  loadingImages = false;
  error: string | null = null;
  updating = false;
  processing = false;
  processingStatus: any = null;
  // --- START MODIFICATION: Use RxJS interval for polling ---
  statusCheckSubscription: Subscription | null = null;
  // --- END MODIFICATION ---

  constructor(private http: HttpClient) { }

  ngOnDestroy() {
    // --- START MODIFICATION: Unsubscribe on component destruction ---
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe();
    }
    // --- END MODIFICATION ---
  }


  onFileSelected(event: any) {
    this.selectedFile = event.target.files[0] || null;
    // Reset state when a new file is selected
    this.resetState();
  }

  resetState() {
      this.uploadProgress = 0;
      this.fileId = null;
      this.images = [];
      this.activeIndex = 0;
      this.loadingImages = false;
      this.error = null;
      this.updating = false;
      this.processing = false;
      this.processingStatus = null;
      if (this.statusCheckSubscription) {
        this.statusCheckSubscription.unsubscribe();
        this.statusCheckSubscription = null;
      }
  }

  uploadFile() {
    if (!this.selectedFile) return;
    // Reset state before starting upload
    this.resetState();

    const formData = new FormData();
    formData.append('file', this.selectedFile);
    this.processing = true; // Show processing indicator early

    this.http.post<any>('http://localhost:8000/upload', formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe({
      next: event => {
        if (event.type === HttpEventType.UploadProgress && event.total) {
          this.uploadProgress = Math.round(100 * event.loaded / event.total);
          this.processingStatus = { current_step: 'Uploading...', progress: this.uploadProgress }; // Update status during upload
        } else if (event.type === HttpEventType.Response) {
          this.fileId = event.body.file_id;
          console.log(`Upload complete. File ID: ${this.fileId}. Starting status check.`);
          // --- START MODIFICATION: Use RxJS interval for polling ---
          this.startStatusCheck();
          // --- END MODIFICATION ---
        }
      },
      error: (err: HttpErrorResponse) => { // Type the error
        console.error('Upload failed:', err); // Log the full error
        this.error = `Upload failed: ${err.message || 'Server error'}`;
        this.processing = false;
        this.resetState(); // Reset fully on upload failure
      }
    });
  }

  // --- START MODIFICATION: Use RxJS interval for polling ---
  startStatusCheck() {
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe(); // Ensure previous one is stopped
    }
    if (!this.fileId) return;

    this.statusCheckSubscription = interval(2000) // Poll every 2 seconds
      .pipe(
        switchMap(() => this.http.get<any>(`http://localhost:8000/status/${this.fileId}`)),
        // Optional: Add takeWhile if you want to automatically stop after completion/error,
        // but explicit stopping is safer.
        // takeWhile(status => status.status === 'processing' || status.status === 'uploading', true)
      )
      .subscribe({
        next: status => {
          console.log("Status update:", status); // Log status updates
          this.processingStatus = status;
          this.processing = (status.status === 'processing' || status.status === 'uploading');

          if (status.status === 'completed') {
            console.log('Processing completed. Stopping status check and fetching final images.');
            this.stopStatusCheck();
            this.processing = false;
            this.fetchImages(true); // Fetch final images
          } else if (status.status === 'error') {
            console.error('Processing error reported by status endpoint:', status.error);
            this.error = `Processing failed: ${status.error}`;
            this.stopStatusCheck();
            this.processing = false;
          } else {
            // Still processing: Fetch partial images incrementally
            console.log('Still processing, fetching partial images...');
            this.fetchImages(false); // Fetch partial/current images
          }
        },
        error: (err: HttpErrorResponse) => { // Type the error
          console.error('Failed to check processing status:', err); // Log the full error
          this.error = `Status check failed: ${err.message || 'Server error'}`;
          this.stopStatusCheck();
          this.processing = false;
        }
      });
  }

  stopStatusCheck() {
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe();
      this.statusCheckSubscription = null;
      console.log("Status check stopped.");
    }
  }
  // --- END MODIFICATION ---


  // --- START MODIFICATION: Add 'isFinalFetch' parameter ---
  fetchImages(isFinalFetch: boolean) {
  // --- END MODIFICATION ---
    if (!this.fileId) return;
    // Only show loading indicator on the final fetch after completion
    this.loadingImages = isFinalFetch;

    this.http.get<any>(`http://localhost:8000/images/${this.fileId}`).subscribe({
      next: res => {
        console.log('Fetch images response:', res); // Debug logging

        if (res.status === 'completed') {
          // --- START MODIFICATION: Handle final state ---
          this.images = (res.images || []).map((img: any, idx: number) => ({
            ...img,
            userAltText: img.generated_alt_text || img.alt_text || '', // Use generated first, then original
            originalIndex: idx // Keep track if needed, maybe image_idx is better
          }));
          // Sort images based on slide_num and then image_idx if available
          this.images.sort((a, b) => {
              if (a.slide_num !== b.slide_num && a.slide_num != null && b.slide_num != null) {
                  return a.slide_num - b.slide_num;
              }
              return (a.image_idx || a.originalIndex) - (b.image_idx || b.originalIndex);
          });

          this.activeIndex = this.images.length > 0 ? 0 : 0; // Go to first image on completion
          this.processing = false; // Ensure processing is false
          this.loadingImages = false;
          this.stopStatusCheck(); // Ensure polling stops
          // --- END MODIFICATION ---
        } else if (res.status === 'processing' || res.status === 'uploading') {
           // --- START MODIFICATION: Handle partial update ---
           this.processing = true; // Ensure processing is true
           if (Array.isArray(res.images)) {
               this.appendNewImages(res.images);
               // Maybe set active index to the latest image?
               // if (this.images.length > 0) {
               //     this.setActive(this.images.length - 1);
               // }
           }
           // Ensure polling continues if it somehow stopped
           if (!this.statusCheckSubscription && !isFinalFetch) {
               console.warn("Polling was stopped but status is not complete. Restarting poll.");
               this.startStatusCheck();
           }
           this.loadingImages = false; // Don't show loading during partial fetches
           // --- END MODIFICATION ---
        } else {
             // Handle unexpected status?
             console.warn("Unexpected status from /images endpoint:", res.status);
             this.loadingImages = false;
        }
      },
      error: (err: HttpErrorResponse) => { // Type the error
        console.error('Failed to fetch images:', err); // Log the full error
        this.error = `Failed to fetch images: ${err.message || 'Server error'}`;
        this.loadingImages = false;
        // Don't stop processing indicator here if status polling might fix it
      }
    });
  }

  appendNewImages(receivedImages: any[]) {
    if (!receivedImages || receivedImages.length === 0) return;

    let newImagesAdded = false;
    const existingIds = new Set(this.images.map(img => img.image_idx)); // Use image_idx if available

    for (const newImg of receivedImages) {
      if (!existingIds.has(newImg.image_idx)) {
        this.images.push({
          ...newImg,
          userAltText: newImg.generated_alt_text || newImg.alt_text || '',
          originalIndex: this.images.length // Fallback index if image_idx is missing
        });
        existingIds.add(newImg.image_idx);
        newImagesAdded = true;
      }
    }

    if (newImagesAdded) {
      // Re-sort images after adding new ones
      this.images.sort((a, b) => {
          if (a.slide_num !== b.slide_num && a.slide_num != null && b.slide_num != null) {
              return a.slide_num - b.slide_num;
          }
          return (a.image_idx || a.originalIndex) - (b.image_idx || b.originalIndex);
      });
      console.log(`Appended images. Total now: ${this.images.length}`);
      // Optionally move to the latest added image (could be jumpy)
      // this.setActive(this.images.length - 1);
    }
  }


  updateAltText() {
    if (!this.fileId || this.images.length === 0) return;
    this.updating = true;
    this.error = null; // Clear previous errors

    // Ensure the updates array matches the current order of this.images
    const updates = this.images.map(img => ({
        image_idx: img.image_idx, // Include image_idx for potential server-side matching
        alt_text: img.userAltText
    }));

    this.http.post<any>(`http://localhost:8000/alt-text/${this.fileId}`, { updates }).subscribe({
      next: res => {
        console.log('Alt text update successful:', res);
        this.updating = false;
        // Optionally provide user feedback like a temporary success message instead of alert
        // this.showSuccessMessage('Alt text saved!');
      },
      error: (err: HttpErrorResponse) => { // Type the error
        console.error('Failed to update alt text:', err); // Log the full error
        this.error = `Failed to save alt text: ${err.message || 'Server error'}`;
        this.updating = false;
      }
    });
  }

  // Carousel helpers
  setActive(i: number) {
    const newIndex = Math.max(0, Math.min(this.images.length - 1, i));
    if (this.activeIndex !== newIndex) {
        this.activeIndex = newIndex;
        // Use timeout to ensure element exists after potential *ngFor update
        setTimeout(() => {
            const el = document.getElementById('image-card-' + this.activeIndex);
            if (el) {
                // Use scrollIntoView with options for smoother scrolling
                el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
            } else {
                console.warn(`Element image-card-${this.activeIndex} not found for scrolling.`);
            }
        }, 50); // Small delay
    }
}


  prev() {
    this.setActive(this.activeIndex - 1);
  }

  next() {
    this.setActive(this.activeIndex + 1);
  }

  downloadFile() {
    if (!this.fileId) return;
    this.error = null; // Clear previous errors

    console.log(`Attempting to download file for ID: ${this.fileId}`); // Log download attempt

    this.http.get(`http://localhost:8000/download/${this.fileId}`, {
      responseType: 'blob',
      observe: 'response' // Observe the full response to get headers
    }).subscribe({
        // --- START MODIFICATION: Use HttpResponse<Blob> and check body ---
        next: (response: HttpResponse<Blob>) => {
            const blob = response.body;
            console.log('Download response received. Status:', response.status); // Log status

            if (!blob || blob.size === 0) {
              console.error('Download failed: Empty or null blob received.');
              this.error = 'Download failed: Received empty file data from server.';
              return;
            }

            // Try to get filename from Content-Disposition header
            const contentDisposition = response.headers.get('content-disposition');
            let filename = `remediated_${this.fileId}.file`; // More specific default
            console.log('Content-Disposition header:', contentDisposition); // Log header

            if (contentDisposition) {
              // Updated regex to handle filename*=UTF-8'' format and simple filename=
              const filenameRegex = /filename\*?=(?:(?:UTF-8|utf-8)''|["']?)([^;"]+)["']?/;
              const matches = filenameRegex.exec(contentDisposition);
              if (matches != null && matches[1]) {
                try {
                  // Decode URI component for potential UTF-8 encoding
                  filename = decodeURIComponent(matches[1]);
                } catch (e) {
                  console.warn("Could not decode filename, using raw value:", matches[1]);
                  filename = matches[1]; // Use raw value if decoding fails
                }
              }
            }
            console.log('Using filename:', filename); // Log final filename

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename; // Use the extracted or default filename
            document.body.appendChild(a); // Append anchor to body for Firefox compatibility
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a); // Clean up anchor
            console.log('Download triggered for:', filename); // Log success
        },
        // --- END MODIFICATION ---
        // --- START MODIFICATION: Log specific error ---
        error: (err: HttpErrorResponse) => { // Explicitly type the error
          this.error = `Download failed: ${err.status} ${err.statusText || 'Unknown error'}`;
          console.error('Download error:', err); // Log the full error object
        }
        // --- END MODIFICATION ---
    });
  }


  acceptSuggestedAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      // Revert to the AI-generated alt text, falling back to original if generated is empty
      this.images[index].userAltText = this.images[index].generated_alt_text || this.images[index].alt_text || '';
    }
  }

  clearAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      this.images[index].userAltText = '';
    }
  }
}
