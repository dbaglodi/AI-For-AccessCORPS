import { Component, OnDestroy, ElementRef, ViewChild, AfterViewInit, ChangeDetectorRef } from '@angular/core'; // Import ElementRef, ViewChild, AfterViewInit, ChangeDetectorRef
import { HttpClient, HttpEventType, HttpResponse, HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { interval, Subscription } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';


@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrls: ['./app.scss']
})
// --- START MODIFICATION: Add AfterViewInit ---
export class AppComponent implements OnDestroy, AfterViewInit {
// --- END MODIFICATION ---
  selectedFile: File | null = null;
  // --- START MODIFICATION: Remove uploadProgress ---
  // uploadProgress: number = 0; // Removed
  // --- END MODIFICATION ---
  fileId: string | null = null;
  images: any[] = [];
  activeIndex: number = 0;
  loadingImages = false;
  error: string | null = null;
  updating = false;
  processing = false;
  processingStatus: any = null;
  statusCheckSubscription: Subscription | null = null;

  // --- START MODIFICATION: Add ViewChild for carousel scrolling ---
  @ViewChild('cardsViewport') cardsViewportRef!: ElementRef<HTMLDivElement>;
  @ViewChild('cardsContainer') cardsContainerRef!: ElementRef<HTMLDivElement>;
  // --- END MODIFICATION ---

  availableTags: string[] = [
    'Equation', 
    'Table', 
    'Figure', 
    'Diagram', 
    'Chart', 
    'Photo', 
    'Needs Review'
  ];

  // --- START MODIFICATION: Inject ChangeDetectorRef ---
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) { }
  // --- END MODIFICATION ---

  ngOnDestroy() {
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe();
    }
  }

  // --- START MODIFICATION: Implement AfterViewInit for potential initial scroll ---
  ngAfterViewInit() {
    // If images are loaded initially (e.g., from state), ensure scroll position is correct
    if (this.images.length > 0) {
      this.scrollToActiveIndex();
    }
  }
  // --- END MODIFICATION ---


  onFileSelected(event: any) {
    this.selectedFile = event.target.files[0] || null;
    this.resetState();
  }

  resetState() {
      // --- START MODIFICATION: Remove uploadProgress ---
      // this.uploadProgress = 0; // Removed
      // --- END MODIFICATION ---
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
    this.resetState();

    const formData = new FormData();
    formData.append('file', this.selectedFile);
    this.processing = true;
    // --- START MODIFICATION: Set initial processing status differently ---
    this.processingStatus = { current_step: 'Uploading file...' }; // Simpler initial status
    // --- END MODIFICATION ---

    this.http.post<any>('http://localhost:8000/upload', formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe({
      next: event => {
        // --- START MODIFICATION: Remove uploadProgress handling ---
        // if (event.type === HttpEventType.UploadProgress && event.total) {
        //   // this.uploadProgress = Math.round(100 * event.loaded / event.total); // Removed
        //   // Update status minimally during upload if needed, but remove progress bar value
        //   this.processingStatus = { current_step: 'Uploading...', progress: undefined };
        // } else
        // --- END MODIFICATION ---
        if (event.type === HttpEventType.Response) {
          this.fileId = event.body.file_id;
          console.log(`Upload complete. File ID: ${this.fileId}. Starting status check.`);
          this.startStatusCheck();
        }
      },
      error: (err: HttpErrorResponse) => {
        console.error('Upload failed:', err);
        this.error = `Upload failed: ${err.message || 'Server error'}`;
        this.processing = false;
        this.resetState();
      }
    });
  }

  startStatusCheck() {
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe();
    }
    if (!this.fileId) return;

    this.statusCheckSubscription = interval(2000)
      .pipe(
        switchMap(() => this.http.get<any>(`http://localhost:8000/status/${this.fileId}`)),
      )
      .subscribe({
        next: status => {
          console.log("Status update:", status);
          this.processingStatus = status;
          this.processing = (status.status === 'processing' || status.status === 'uploading');

          if (status.status === 'completed') {
            console.log('Processing completed. Stopping status check and fetching final images.');
            this.stopStatusCheck();
            this.processing = false;
            this.fetchImages(true);
          } else if (status.status === 'error') {
            console.error('Processing error reported by status endpoint:', status.error);
            this.error = `Processing failed: ${status.error}`;
            this.stopStatusCheck();
            this.processing = false;
          } else {
            console.log('Still processing, fetching partial images...');
            this.fetchImages(false);
          }
        },
        error: (err: HttpErrorResponse) => {
          console.error('Failed to check processing status:', err);
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

  // --- START MODIFICATION: Helper to map image data ---
  private mapImageData(img: any, index: number): any {
    return {
      ...img,
      userAltText: img.generated_alt_text || img.alt_text || '',
      // short_description: img.short_description || 'N/A', // Removed
      // Ensure classification is always an array
      classification: Array.isArray(img.classification) ? img.classification : [],
      originalIndex: index
    };
  }
  // --- END MODIFICATION ---

  fetchImages(isFinalFetch: boolean) {
    if (!this.fileId) return;
    this.loadingImages = isFinalFetch;

    this.http.get<any>(`http://localhost:8000/images/${this.fileId}`).subscribe({
      next: res => {
        console.log('Fetch images response:', res);

        if (res.status === 'completed') {
          // --- START MODIFICATION: Use helper for mapping ---
          const newImages = (res.images || []).map((img: any, idx: number) => this.mapImageData(img, idx));
          // --- END MODIFICATION ---
          this.images = this.sortImages(newImages); // Sort final list

          this.activeIndex = this.images.length > 0 ? 0 : 0;
          this.processing = false;
          this.loadingImages = false;
          this.stopStatusCheck();
          this.cdr.detectChanges(); // Trigger change detection
          this.scrollToActiveIndex(); // Scroll after view updates
        } else if (res.status === 'processing' || res.status === 'uploading') {
           this.processing = true;
           if (Array.isArray(res.images)) {
               this.appendNewImages(res.images);
           }
           if (!this.statusCheckSubscription && !isFinalFetch) {
               console.warn("Polling was stopped but status is not complete. Restarting poll.");
               this.startStatusCheck();
           }
           this.loadingImages = false;
        } else {
             console.warn("Unexpected status from /images endpoint:", res.status);
             this.loadingImages = false;
        }
      },
      error: (err: HttpErrorResponse) => {
        console.error('Failed to fetch images:', err);
        this.error = `Failed to fetch images: ${err.message || 'Server error'}`;
        this.loadingImages = false;
      }
    });
  }

  sortImages(imageList: any[]): any[] {
     return imageList.sort((a, b) => {
        if (a.slide_num !== b.slide_num && a.slide_num != null && b.slide_num != null) {
            return a.slide_num - b.slide_num;
        }
        // Use image_idx primarily, fall back to originalIndex
        const idxA = a.image_idx ?? a.originalIndex ?? Infinity;
        const idxB = b.image_idx ?? b.originalIndex ?? Infinity;
        return idxA - idxB;
     });
  }


  appendNewImages(receivedImages: any[]) {
    if (!receivedImages || receivedImages.length === 0) return;

    let newImagesAdded = false;
    const existingIds = new Set(this.images.map(img => img.image_idx).filter(id => id != null));

    for (const newImg of receivedImages) {
      // Use image_idx if available, otherwise assume it's new if not deeply equal to an existing one
      const isNew = newImg.image_idx != null
        ? !existingIds.has(newImg.image_idx)
        : !this.images.some(existingImg => JSON.stringify(existingImg) === JSON.stringify(newImg)); // Less efficient fallback

      if (isNew) {
        // --- START MODIFICATION: Use helper for mapping ---
        this.images.push(this.mapImageData(newImg, this.images.length));
        // --- END MODIFICATION ---

        if (newImg.image_idx != null) {
          existingIds.add(newImg.image_idx);
        }
        newImagesAdded = true;
      }
    }

    if (newImagesAdded) {
      this.images = this.sortImages(this.images); // Re-sort after adding
      console.log(`Appended/Sorted images. Total now: ${this.images.length}`);
      // Don't auto-scroll here, let the status loop handle final scroll
      // Force update the view if necessary
      this.cdr.detectChanges();
    }
  }


  updateAltText() {
    if (!this.fileId || this.images.length === 0) return;
    this.updating = true;
    this.error = null;

    const updates = this.images.map(img => ({
        image_idx: img.image_idx,
        alt_text: img.userAltText
    }));

    this.http.post<any>(`http://localhost:8000/alt-text/${this.fileId}`, { updates }).subscribe({
      next: res => {
        console.log('Alt text update successful:', res);
        this.updating = false;
      },
      error: (err: HttpErrorResponse) => {
        console.error('Failed to update alt text:', err);
        this.error = `Failed to save alt text: ${err.message || 'Server error'}`;
        this.updating = false;
      }
    });
  }

  // --- START MODIFICATION: Updated setActive and scrolling ---
  setActive(i: number) {
    if (this.images.length === 0) return;
    // Handle wrapping
    const newIndex = (i + this.images.length) % this.images.length;

    if (this.activeIndex !== newIndex) {
        this.activeIndex = newIndex;
        this.scrollToActiveIndex();
    }
  }

  scrollToActiveIndex() {
      // Use timeout to allow Angular to update the view *before* scrolling
      setTimeout(() => {
          if (this.cardsViewportRef && this.cardsContainerRef) {
              const viewport = this.cardsViewportRef.nativeElement;
              const container = this.cardsContainerRef.nativeElement;
              const cardElements = container.children;
              if (cardElements.length > this.activeIndex) {
                  const activeCard = cardElements[this.activeIndex] as HTMLElement;
                  const scrollLeft = activeCard.offsetLeft - viewport.offsetLeft; // Calculate scroll position based on card offset

                  viewport.scrollTo({
                      left: scrollLeft,
                      behavior: 'smooth'
                  });
                  console.log(`Scrolled to index ${this.activeIndex} at position ${scrollLeft}`);
              } else {
                   console.warn(`Card element for index ${this.activeIndex} not found.`);
              }
          } else {
               console.warn("Viewport or container ref not available for scrolling.");
          }
      }, 50); // Small delay might be needed
  }
  // --- END MODIFICATION ---

  // --- START MODIFICATION: Update prev/next for wrapping ---
  prev() {
    this.setActive(this.activeIndex - 1); // setActive handles wrapping
  }

  next() {
    this.setActive(this.activeIndex + 1); // setActive handles wrapping
  }
  // --- END MODIFICATION ---

  regeneratePipeline(img: any) {
    if (!this.fileId) {
      console.error("Cannot regenerate: No file ID found.");
      return;
    }

    img.isRegenerating = true;
    this.cdr.detectChanges(); // Force UI to show loading state

    const selectedPipeline = img.classification[0]; 

    const payload = {
      image_idx: img.image_idx,
      forced_pipeline: selectedPipeline,
      slide_num: img.slide_num, 
      rId: img.rId             
    };

    const url = `http://localhost:8000/api/regenerate-image/${this.fileId}`;

    this.http.post(url, payload).subscribe({
      next: (response: any) => {
        // Update the backend's generated text
        img.generated_alt_text = response.new_alt_text;
        
        // Optionally, auto-populate the user's editable textbox with the new result
        img.userAltText = response.new_alt_text; 
        
        img.isRegenerating = false;
        this.cdr.detectChanges(); // Update UI to hide loading state
      },
      error: (err: HttpErrorResponse) => {
        console.error('Failed to regenerate pipeline:', err);
        alert(`Error regenerating pipeline: ${err.message || 'Check backend console.'}`);
        img.isRegenerating = false;
        this.cdr.detectChanges();
      }
    });
  }

  downloadFile() {
    if (!this.fileId) return;
    this.error = null;

    console.log(`Attempting to download file for ID: ${this.fileId}`);

    this.http.get(`http://localhost:8000/download/${this.fileId}`, {
      responseType: 'blob',
      observe: 'response'
    }).subscribe({
        next: (response: HttpResponse<Blob>) => {
            const blob = response.body;
            console.log('Download response received. Status:', response.status);

            if (!blob || blob.size === 0) {
              console.error('Download failed: Empty or null blob received.');
              this.error = 'Download failed: Received empty file data from server.';
              return;
            }

            const contentDisposition = response.headers.get('content-disposition');
            let filename = `remediated_${this.fileId}.file`;
            console.log('Content-Disposition header:', contentDisposition);

            if (contentDisposition) {
              const filenameRegex = /filename\*?=(?:(?:UTF-8|utf-8)''|["']?)([^;"]+)["']?/;
              const matches = filenameRegex.exec(contentDisposition);
              if (matches != null && matches[1]) {
                try {
                  filename = decodeURIComponent(matches[1]);
                } catch (e) {
                  console.warn("Could not decode filename, using raw value:", matches[1]);
                  filename = matches[1];
                }
              }
            }
            console.log('Using filename:', filename);

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            console.log('Download triggered for:', filename);
        },
        error: (err: HttpErrorResponse) => {
          this.error = `Download failed: ${err.status} ${err.statusText || 'Unknown error'}`;
          console.error('Download error:', err);
        }
    });
  }


  acceptSuggestedAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      this.images[index].userAltText = this.images[index].generated_alt_text || this.images[index].alt_text || '';
    }
  }

  revertToOriginalAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      // Revert to the original alt text
      this.images[index].userAltText = this.images[index].alt_text || '';
    }
  }

  clearAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      this.images[index].userAltText = '';
    }
  }
}