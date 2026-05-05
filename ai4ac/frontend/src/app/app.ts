import { Component, OnInit, OnDestroy, ElementRef, ViewChild, AfterViewInit, ChangeDetectorRef, HostListener } from '@angular/core'; // Import ElementRef, ViewChild, AfterViewInit, ChangeDetectorRef
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
export class AppComponent implements OnInit, OnDestroy, AfterViewInit {
  private readonly apiUrl = 'https://ai-for-accesscorps.onrender.com';
  isVercelMode: boolean = false;
  selectedFile: File | null = null;
  modelProvider: string = 'local';
  geminiApiKey: string = '';
  fileId: string | null = null;
  images: any[] = [];
  activeIndex: number = 0;
  loadingImages = false;
  error: string | null = null;
  updating = false;
  processing = false;
  processingStatus: any = null;
  statusCheckSubscription: Subscription | null = null;
  isModalOpen: boolean = false;
  selectedModalImage: string | null = null;
  selectedModalAlt: string = '';
  zoomLevel: number = 1;
  showPptxModal: boolean = false;
  processAllSlides: boolean = true;
  startSlide: number | null = null;
  endSlide: number | null = null;

  // --- START MODIFICATION: Add ViewChild for carousel scrolling ---
  @ViewChild('cardsViewport') cardsViewportRef!: ElementRef<HTMLDivElement>;
  @ViewChild('cardsContainer') cardsContainerRef!: ElementRef<HTMLDivElement>;
  // --- END MODIFICATION ---

  availableTags: string[] = [
    'Equation',
    'Table',
    'Figure',
    'Diagram',
    'Graph',
    'Photo',
    'Needs Review'
  ];

  // --- START MODIFICATION: Inject ChangeDetectorRef ---
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) { }
  // --- END MODIFICATION ---

  ngOnInit() {
    // Check if we are running in a browser (avoids errors if using Angular SSR)
    if (typeof window !== 'undefined') {
      // Check if hosted on Vercel
      this.isVercelMode = window.location.hostname === 'ai4ac.vercel.app';

      // Force Gemini if on Vercel
      if (this.isVercelMode) {
        this.modelProvider = 'gemini';
      }
    }
  }

  @HostListener('document:keydown.escape')
  handleEscapeKey() {
    if (this.isModalOpen) {
      this.closeImageModal();
    }
  }

  openImageModal(imageUrl: string, altText: string) {
    if (!imageUrl) return;
    this.selectedModalImage = imageUrl;
    this.selectedModalAlt = altText || 'Enlarged image';
    this.zoomLevel = 1;
    this.isModalOpen = true;
    document.body.style.overflow = 'hidden'; // Prevent background scrolling while modal is open
  }

  closeImageModal(event?: Event) {
    if (event) {
      event.stopPropagation();
    }
    this.isModalOpen = false;
    setTimeout(() => {
      this.selectedModalImage = null;
    }, 300); // Clear image after transition if you add CSS animations
    document.body.style.overflow = ''; // Restore scrolling
  }

  zoomIn() {
    if (this.zoomLevel < 4) {
      this.zoomLevel += 0.25;
    }
  }

  zoomOut() {
    if (this.zoomLevel > 0.5) {
      this.zoomLevel -= 0.25;
    }
  }

  resetZoom() {
    this.zoomLevel = 1;
  }

  ngOnDestroy() {
    if (this.statusCheckSubscription) {
      this.statusCheckSubscription.unsubscribe();
    }
  }

  ngAfterViewInit() {
    if (this.images.length > 0) {
      this.scrollToActiveIndex(false); // Instant snap on initial load
    }
  }


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

    // Check if the file is a PowerPoint
    if (this.selectedFile.name.toLowerCase().endsWith('.pptx')) {
      this.showPptxModal = true;
      this.processAllSlides = true; // Default to full presentation
      this.startSlide = null;
      this.endSlide = null;
    } else {
      // If it's a DOCX, proceed straight to upload
      this.executeUpload();
    }
  }

  cancelPptxModal() {
    this.showPptxModal = false;
  }

  confirmPptxUpload() {
    this.showPptxModal = false;
    this.executeUpload();
  }

  executeUpload() {
    this.resetState();

    const formData = new FormData();
    formData.append('file', this.selectedFile!);
    formData.append('provider', this.modelProvider);
    if (this.modelProvider === 'gemini' && this.geminiApiKey) {
      formData.append('api_key', this.geminiApiKey);
    }

    // Append slide range if user selected Custom Range
    if (this.selectedFile?.name.toLowerCase().endsWith('.pptx') && !this.processAllSlides) {
      if (this.startSlide) formData.append('start_slide', this.startSlide.toString());
      if (this.endSlide) formData.append('end_slide', this.endSlide.toString());
    }

    this.processing = true;
    this.processingStatus = { current_step: 'Uploading file...' };

    this.http.post<any>(`${this.apiUrl}/upload`, formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe({
      next: event => {
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
        switchMap(() => this.http.get<any>(`${this.apiUrl}/status/${this.fileId}`)),
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

  private mapImageData(img: any, index: number): any {
    const classifications = Array.isArray(img.classification) ? img.classification : [];
    
    return {
      ...img,
      userAltText: img.generated_alt_text || img.alt_text || '',
      slide_title: img.slide_title || '',
      is_generated_title: img.is_generated_title || false,
      classification: classifications,
      // explicitly set the initial dropdown value so it doesn't render blank
      selectedPipeline: classifications.length > 0 ? classifications[0] : 'Needs Review',
      originalIndex: index
    };
  }

  onSlideTitleChange(changedImg: any, newTitle: string) {
    if (!changedImg.slide_num) return;
    
    this.images.forEach(img => {
      // Sync the new title to all other images that share the same slide_num
      if (img.slide_num === changedImg.slide_num && img !== changedImg) {
        img.slide_title = newTitle;
      }
    });
  }

  fetchImages(isFinalFetch: boolean) {
    if (!this.fileId) return;
    this.loadingImages = isFinalFetch;

    this.http.get<any>(`${this.apiUrl}/images/${this.fileId}`).subscribe({
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
          
          // --- MODIFIED LINE HERE ---
          // Pass 'false' to instantly snap the first card to the center without animation
          this.scrollToActiveIndex(false); 
          
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
    const wasEmpty = this.images.length === 0; // Check if UI was empty before loop
    const existingIds = new Set(this.images.map(img => img.image_idx).filter(id => id != null));

    for (const newImg of receivedImages) {
      const isNew = newImg.image_idx != null
        ? !existingIds.has(newImg.image_idx)
        : !this.images.some(existingImg => JSON.stringify(existingImg) === JSON.stringify(newImg));

      if (isNew) {
        this.images.push(this.mapImageData(newImg, this.images.length));
        if (newImg.image_idx != null) existingIds.add(newImg.image_idx);
        newImagesAdded = true;
      }
    }

    if (newImagesAdded) {
      this.images = this.sortImages(this.images); 
      this.cdr.detectChanges();
      
      if (wasEmpty) {
         // If this is the first image added to the UI, center it instantly
         this.scrollToActiveIndex(false);
      }
    }
  }


  updateAltText() {
    if (!this.fileId || this.images.length === 0) return;
    this.updating = true;
    this.error = null;

    const updates = this.images.map(img => ({
      image_idx: img.image_idx,
      alt_text: img.userAltText,
      slide_title: img.slide_title
    }));

    this.http.post<any>(`${this.apiUrl}/alt-text/${this.fileId}`, { updates }).subscribe({
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
    const newIndex = (i + this.images.length) % this.images.length;

    if (this.activeIndex !== newIndex) {
      this.activeIndex = newIndex;
      this.scrollToActiveIndex(true); // Smooth scroll when navigating
    }
  }

  scrollToActiveIndex(smooth: boolean = true, retryCount: number = 0) {
    // Use timeout to allow Angular to update the view *before* scrolling
    setTimeout(() => {
      if (this.cardsContainerRef) {
        const container = this.cardsContainerRef.nativeElement;
        const cardElements = container.querySelectorAll('.card-wrapper');
        
        if (cardElements.length > this.activeIndex) {
          const activeCard = cardElements[this.activeIndex] as HTMLElement;
          
          activeCard.scrollIntoView({
            behavior: smooth ? 'smooth' : 'auto', // 'auto' snaps instantly on first load
            inline: 'center',
            block: 'nearest'
          });
        } else if (retryCount < 5) {
          // If Angular hasn't rendered the *ngFor items yet, wait and try again
          this.scrollToActiveIndex(smooth, retryCount + 1);
        }
      }
    }, 50);
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
    if (!img) return;

    if (!this.fileId) {
      console.error("Cannot regenerate: No file ID found.");
      return;
    }

    img.isRegenerating = true;
    this.cdr.detectChanges(); // Force UI to show loading state

    const selectedPipeline = img.selectedPipeline || img.classification[0];

    // Read the GLOBAL component state instead of the card state
    const providerToUse = this.modelProvider || 'local'; 

    const payload = {
      image_idx: img.image_idx,
      forced_pipeline: selectedPipeline,
      slide_num: img.slide_num, 
      rId: img.rId,
      provider: providerToUse, // Sends whatever the top dropdown is set to
      api_key: providerToUse === 'gemini' ? this.geminiApiKey : null
    };

    // Use this.apiUrl instead of a hardcoded or relative path
    this.http.post<any>(`${this.apiUrl}/api/regenerate-image/${this.fileId}`, payload).subscribe({
      next: (response) => {
        img.generated_alt_text = response.new_alt_text || response.generated_alt_text; // Ensure we grab new_alt_text 
        img.userAltText = img.generated_alt_text;
        
        // Update the classification array to show the new forced pipeline first
        if (img.classification && response.pipeline_used) {
            const index = img.classification.indexOf(response.pipeline_used);
            if (index > -1) img.classification.splice(index, 1);
            img.classification.unshift(response.pipeline_used);
        }
        
        img.isRegenerating = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.error("Error regenerating alt text", err);
        
        // Alert the user if the backend throws our custom 422 extraction failure error
        if (err.status === 422 && err.error && err.error.detail) {
            alert(err.error.detail);
        } else {
            alert("An error occurred while trying to regenerate the image extraction.");
        }
        
        img.isRegenerating = false;
        this.cdr.detectChanges();
      }
    });
  }

  downloadFile() {
    if (!this.fileId) return;
    this.error = null;

    console.log(`Attempting to download file for ID: ${this.fileId}`);

    this.http.get(`${this.apiUrl}/download/${this.fileId}`, {
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