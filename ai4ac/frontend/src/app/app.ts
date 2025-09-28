import { Component } from '@angular/core';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrls: ['./app.scss']
})
export class AppComponent {
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
  statusCheckInterval: any = null;

  constructor(private http: HttpClient) { }

  onFileSelected(event: any) {
    this.selectedFile = event.target.files[0] || null;
  }

  uploadFile() {
    if (!this.selectedFile) return;
    const formData = new FormData();
    formData.append('file', this.selectedFile);
    this.uploadProgress = 0;
    this.error = null;
    this.processing = true;
    this.processingStatus = null;
    this.images = [];

    // Clear any existing status check interval
    if (this.statusCheckInterval) {
      clearInterval(this.statusCheckInterval);
      this.statusCheckInterval = null;
    }

    this.http.post<any>('http://localhost:8000/upload', formData, {
      reportProgress: true,
      observe: 'events'
    }).subscribe({
      next: event => {
        if (event.type === HttpEventType.UploadProgress && event.total) {
          this.uploadProgress = Math.round(100 * event.loaded / event.total);
        } else if (event.type === HttpEventType.Response) {
          this.fileId = event.body.file_id;
          // Start checking status
          this.statusCheckInterval = setInterval(() => this.checkStatus(), 1000);
        }
      },
      error: err => {
        this.error = 'Upload failed.';
        this.processing = false;
      }
    });
  }

  ngOnDestroy() {
    if (this.statusCheckInterval) {
      clearInterval(this.statusCheckInterval);
    }
  }

  checkStatus() {
    if (!this.fileId) return;

    this.http.get<any>(`http://localhost:8000/status/${this.fileId}`).subscribe({
      next: status => {
        this.processingStatus = status;

        if (status.status === 'completed') {
          // Stop checking status and fetch images
          if (this.statusCheckInterval) {
            clearInterval(this.statusCheckInterval);
            this.statusCheckInterval = null;
          }
          this.processing = false;
          this.fetchImages();
        } else if (status.status === 'error') {
          this.error = status.error;
          this.processing = false;
          if (this.statusCheckInterval) {
            clearInterval(this.statusCheckInterval);
            this.statusCheckInterval = null;
          }
        }
        else {
          // Still processing: fetch partial images incrementally
          this.processing = true;
          this.fetchImagesPartial();
        }
      },
      error: err => {
        this.error = 'Failed to check processing status.';
        this.processing = false;
        if (this.statusCheckInterval) {
          clearInterval(this.statusCheckInterval);
          this.statusCheckInterval = null;
        }
      }
    });
  }

  fetchImages() {
    if (!this.fileId) return;
    this.loadingImages = true;
    this.http.get<any>(`http://localhost:8000/images/${this.fileId}`).subscribe({
      next: res => {
        if (res.status !== 'completed') {
          // Partial response while processing — ensure we have a polling loop
          this.processing = true;
          if (!this.statusCheckInterval) {
            this.statusCheckInterval = setInterval(() => this.checkStatus(), 2000);
          }
          this.processingStatus = {
            status: res.status,
            progress: res.progress,
            current_step: res.current_step
          };
          // Append any images present so far
          if (Array.isArray(res.images)) {
            this.appendNewImages(res.images);
          }
          this.loadingImages = false;
        } else {
          // Processing complete, show images (final)
          this.images = res.images.map((img: any, idx: number) => ({
            ...img,
            userAltText: img.alt_text,
            idx
          }));
          // Set active index to the most recently generated (last) image
          this.activeIndex = Math.max(0, this.images.length - 1);
          this.processing = false;
          this.loadingImages = false;
        }
      },
      error: err => {
        this.error = 'Failed to fetch images.';
        this.loadingImages = false;
        this.processing = false;
      }
    });
  }

  fetchImagesPartial() {
    if (!this.fileId) return;
    this.http.get<any>(`http://localhost:8000/images/${this.fileId}`).subscribe({
      next: res => {
        console.log('Partial fetch response:', res); // Debug logging

        if (Array.isArray(res.images)) {
          // Show each image card as it becomes available
          this.appendNewImages(res.images);

          // Auto-scroll to newest card if we have images
          if (res.images.length > 0 && this.images.length > 0) {
            this.setActive(this.images.length - 1);
          }
        }

        // Keep processing status updated
        if (res.status === 'completed') {
          this.processing = false;
          if (this.statusCheckInterval) {
            clearInterval(this.statusCheckInterval);
            this.statusCheckInterval = null;
          }
        } else {
          // Still processing - keep showing partial results
          this.processing = true;
        }
      },
      error: err => {
        console.warn('Partial image fetch failed', err);
      }
    });
  }

  appendNewImages(receivedImages: any[]) {
    let hasNewImages = false;

    console.log('Appending images:', receivedImages.length, 'Current total:', this.images.length);

    // Use image_idx (or fallback to index) to dedupe
    for (const img of receivedImages) {
      const id = img.image_idx ?? img.idx ?? null;
      const exists = id !== null && this.images.some(i => (i.image_idx ?? i.idx) === id);

      if (!exists) {
        const mapped = {
          ...img,
          userAltText: img.alt_text || '', // Ensure userAltText is always set
          idx: this.images.length,
        };
        this.images.push(mapped);
        hasNewImages = true;
        console.log(`Added new image ${mapped.idx + 1}: ${mapped.alt_text}`);
      }
    }

    // Center on the newly appended image if we added any
    if (hasNewImages && this.images.length > 0) {
      this.setActive(this.images.length - 1);
    }
  }

  updateAltText() {
    if (!this.fileId) return;
    this.updating = true;
    const updates = this.images.map(img => ({ alt_text: img.userAltText }));
    this.http.post<any>(`http://localhost:8000/alt-text/${this.fileId}`, { updates }).subscribe({
      next: res => {
        this.updating = false;
        alert('Alt text updated! You can now download the remediated file.');
      },
      error: err => {
        this.error = 'Failed to update alt text.';
        this.updating = false;
      }
    });
  }

  // Carousel helpers
  setActive(i: number) {
    if (i < 0) i = 0;
    if (i >= this.images.length) i = this.images.length - 1;
    this.activeIndex = i;
    // scroll the card into view (best-effort)
    setTimeout(() => {
      const el = document.getElementById('image-card-' + i);
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
      }
    }, 100);
  }

  prev() {
    this.setActive(Math.max(0, this.activeIndex - 1));
  }

  next() {
    this.setActive(Math.min(this.images.length - 1, this.activeIndex + 1));
  }

  downloadFile() {
    if (!this.fileId) return;
    this.http.get(`http://localhost:8000/download/${this.fileId}`, { responseType: 'blob' }).subscribe(blob => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'remediated_file';
      a.click();
      window.URL.revokeObjectURL(url);
    });
  }

  acceptSuggestedAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      this.images[index].userAltText = this.images[index].alt_text;
    }
  }

  clearAltText(index: number) {
    if (index >= 0 && index < this.images.length) {
      this.images[index].userAltText = '';
    }
  }
}
