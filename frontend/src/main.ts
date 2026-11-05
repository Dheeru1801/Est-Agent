import { bootstrapApplication } from '@angular/platform-browser';
import { Component, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  activity: string;
  steps: string[];
  streaming?: boolean;
};

type DocumentRecord = {
  id: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256: string;
  status: 'uploaded' | 'indexing' | 'indexed' | 'failed';
  is_indexed: boolean;
  parser: string | null;
  chunk_count: number;
  image_description_count: number;
  uploaded_at: string;
  index_started_at: string | null;
  indexed_at: string | null;
  error: string | null;
};

type DocumentOverview = {
  total_documents: number;
  indexed_documents: number;
  not_indexed_documents: number;
  pending_documents: number;
  status_counts: Record<string, number>;
  documents: DocumentRecord[];
};

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">G</div><span>groundwork</span></div>
        <button class="new-chat" (click)="clearChat()"><span>ï¼‹</span> New conversation</button>
        <div class="side-label">WORKSPACE</div>
        <button class="nav-item" [class.active]="view === 'chat'" (click)="view = 'chat'">
          <span>CHAT</span> Knowledge assistant
        </button>
        <button class="nav-item" [class.active]="view === 'documents'" (click)="openDocuments()">
          <span>DOCS</span> Documents <b>{{ overview?.total_documents ?? 0 }}</b>
        </button>
        <div class="sidebar-bottom">
          <span class="status-dot" [class.offline]="!configured"></span>
          <span>{{ configured ? 'Agent ready' : 'Setup needed' }}</span>
          <button class="refresh-link" (click)="checkHealth()">Refresh</button>
        </div>
      </aside>

      <main class="main" *ngIf="view === 'chat'">
        <header>
          <div><span class="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</span><h1>Ask anything.</h1>
            <p>Your documents, thoughtfully connected.</p></div>
          <button class="settings" title="Refresh backend status" (click)="checkHealth()">
            <span>{{ configured ? 'Connected' : 'Setup needed' }}</span>
          </button>
        </header>
        <section class="conversation">
          <div class="welcome" *ngIf="messages.length === 0">
            <div class="welcome-glyph">G</div>
            <div class="hello">A little more clarity,<br><em>one question away.</em></div>
            <p>Upload your notes, guides, and documents. I'll help you find the useful bits and bring them together.</p>
            <div class="suggestions">
              <button *ngFor="let prompt of prompts" (click)="send(prompt)"><span>&gt;</span>{{ prompt }}</button>
            </div>
          </div>
          <div class="messages" *ngIf="messages.length">
            <article *ngFor="let message of messages" class="message" [class.user]="message.role === 'user'">
              <div class="avatar">{{ message.role === 'user' ? 'Y' : 'G' }}</div>
              <div class="bubble">
                <div class="role">{{ message.role === 'user' ? 'YOU' : 'GROUNDWORK' }}</div>
                <div class="activity-list" *ngIf="message.role === 'assistant' && message.steps.length">
                  <div *ngFor="let step of message.steps" class="activity-step">{{ step }}</div>
                </div>
                <div class="text">{{ message.text }}<span class="stream-cursor" *ngIf="message.streaming && message.text">|</span></div>
                <div class="typing" *ngIf="message.streaming && !message.text"><i></i><i></i><i></i></div>
              </div>
            </article>
          </div>
        </section>
        <div class="composer-wrap">
          <div class="composer">
            <textarea [(ngModel)]="draft" (keydown)="onKey($event)" placeholder="Ask a question about your knowledge..." rows="1"></textarea>
            <button (click)="send()" [disabled]="!draft.trim() || thinking" aria-label="Send">Send</button>
          </div>
          <div class="fineprint">Grounded in your sources | Live activity and streamed answers</div>
        </div>
      </main>

      <main class="main documents-page" *ngIf="view === 'documents'">
        <header class="documents-header">
          <div><span class="eyebrow">KNOWLEDGE LIBRARY</span><h1>Your documents.</h1>
            <p>Upload first, then index whenever you're ready.</p></div>
          <button class="settings" (click)="refreshDocuments()"><span>Refresh</span></button>
        </header>

        <section class="document-content">
          <div class="stat-grid">
            <div class="stat-card"><span>Total documents</span><strong>{{ overview?.total_documents ?? 0 }}</strong></div>
            <div class="stat-card"><span>Indexed</span><strong>{{ overview?.indexed_documents ?? 0 }}</strong></div>
            <div class="stat-card"><span>Not yet indexed</span><strong>{{ overview?.not_indexed_documents ?? 0 }}</strong></div>
          </div>

          <div class="upload-panel">
            <div>
              <h2>Upload documents</h2>
              <p>Choose multiple files or a ZIP archive containing PDF, DOCX, TXT, Markdown, CSV, or JSON files.</p>
            </div>
            <label class="dropzone" [class.dragging]="dragging" (dragover)="onDragOver($event)" (dragleave)="dragging = false" (drop)="onDrop($event)">
              <input #filePicker type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.json,.zip" (change)="selectFiles($event)">
              <span class="drop-icon">Upload</span>
              <strong>Choose files or drop them here</strong>
              <small>Uploads are saved first; indexing is separate. Files are limited to 100 MB.</small>
            </label>
            <div class="selected-files" *ngIf="selectedFiles.length">
              <div *ngFor="let selected of selectedFiles; let i = index" class="selected-file">
                <span>{{ selected.name }}</span><small>{{ formatSize(selected.size) }}</small>
                <button (click)="removeSelected(i)" aria-label="Remove selected file">Remove</button>
              </div>
            </div>
            <div class="upload-actions">
              <button class="primary-button" (click)="uploadSelected()" [disabled]="uploading || !selectedFiles.length">
                {{ uploading ? 'Saving files...' : 'Upload files' }}
              </button>
              <button class="secondary-button" (click)="startIndexing()" [disabled]="indexing || !(overview?.pending_documents)">
                {{ indexing ? 'Indexing...' : 'Index pending documents' }}
                <span *ngIf="overview?.pending_documents">({{ overview?.pending_documents }})</span>
              </button>
            </div>
            <p class="inline-notice" *ngIf="documentNotice">{{ documentNotice }}</p>
          </div>

          <div class="library-heading"><div><h2>Document database</h2><p>{{ overview?.total_documents ?? 0 }} records in SQLite</p></div>
            <span *ngIf="refreshing">Refreshing...</span></div>
          <div class="pagination-controls"><span>Showing {{ documentRangeStart }}–{{ documentRangeEnd }} of {{ overview?.total_documents ?? 0 }}</span><div><button (click)="previousDocumentPage()" [disabled]="documentOffset === 0">Previous</button><button (click)="nextDocumentPage()" [disabled]="documentRangeEnd >= (overview?.total_documents ?? 0)">Next</button></div></div>
          <div class="table-wrap" *ngIf="overview?.documents?.length; else emptyLibrary">
            <table>
              <thead><tr><th>Document</th><th>Status</th><th>Uploaded</th><th>Index started</th><th>Indexed</th><th>Details</th></tr></thead>
              <tbody>
                <tr *ngFor="let doc of overview?.documents">
                  <td><strong class="doc-name">{{ doc.filename }}</strong><small>{{ formatSize(doc.size_bytes) }} | {{ doc.content_type || 'Unknown type' }}</small></td>
                  <td><span class="status-pill" [class]="'status-pill ' + doc.status">{{ doc.status }}</span>
                    <small>{{ doc.is_indexed ? 'Indexed' : 'Not indexed' }}</small></td>
                  <td>{{ doc.uploaded_at | date:'medium' }}</td>
                  <td>{{ doc.index_started_at ? (doc.index_started_at | date:'medium') : '-' }}</td>
                  <td>{{ doc.indexed_at ? (doc.indexed_at | date:'medium') : '-' }}</td>
                  <td><small *ngIf="doc.parser">{{ doc.parser }} | {{ doc.chunk_count }} chunks</small>
                    <small *ngIf="doc.image_description_count">{{ doc.image_description_count }} image captions</small>
                    <small class="error-detail" *ngIf="doc.error">{{ doc.error }}</small>
                    <small *ngIf="!doc.parser && !doc.error">Waiting for indexing</small>
                    <details class="metadata-details"><summary>All metadata</summary><pre>{{ doc | json }}</pre></details></td>
                </tr>
              </tbody>
            </table>
          </div>
          <ng-template #emptyLibrary><div class="empty-library">No documents uploaded yet.</div></ng-template>
        </section>
      </main>
    </div>
    <div class="toast" *ngIf="notice">{{ notice }}</div>
  `,
})
class AppComponent implements OnDestroy {
  draft = '';
  messages: ChatMessage[] = [];
  overview: DocumentOverview | null = null;
  selectedFiles: File[] = [];
  view: 'chat' | 'documents' = 'chat';
  thinking = false;
  uploading = false;
  indexing = false;
  refreshing = false;
  dragging = false;
  configured = false;
  notice = '';
  documentNotice = '';
  documentOffset = 0;
  documentPageSize = 100;
  private pollTimer?: ReturnType<typeof setInterval>;
  private api = 'http://localhost:8000/api';
  prompts = [
    'What are the key ideas in my documents?',
    'Summarize a topic across my sources',
    'Help me compare two approaches',
  ];

  constructor() {
    this.checkHealth();
    this.refreshDocuments();
  }

  ngOnDestroy() {
    if (this.pollTimer) clearInterval(this.pollTimer);
  }

  async checkHealth() {
    try {
      const response = await fetch(`${this.api}/health`);
      const data = await response.json();
      this.configured = data.configured;
    } catch {
      this.configured = false;
    }
  }

  async openDocuments() {
    this.view = 'documents';
    await this.refreshDocuments();
  }

  async refreshDocuments() {
    this.refreshing = true;
    try {
      const response = await fetch(`${this.api}/documents?limit=${this.documentPageSize}&offset=${this.documentOffset}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not load documents.');
      this.overview = data as DocumentOverview;
      this.updatePolling();
    } catch (error) {
      this.documentNotice = error instanceof Error ? error.message : 'Could not load documents.';
    } finally {
      this.refreshing = false;
    }
  }

  private updatePolling() {
    const active = (this.overview?.status_counts?.['indexing'] ?? 0) > 0;
    if (active && !this.pollTimer) {
      this.pollTimer = setInterval(() => void this.refreshDocuments(), 2500);
    } else if (!active && this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
  }

  previousDocumentPage() {
    this.documentOffset = Math.max(0, this.documentOffset - this.documentPageSize);
    void this.refreshDocuments();
  }

  nextDocumentPage() {
    if ((this.documentOffset + this.documentPageSize) < (this.overview?.total_documents ?? 0)) {
      this.documentOffset += this.documentPageSize;
      void this.refreshDocuments();
    }
  }

  get documentRangeStart(): number {
    return this.overview?.total_documents ? this.documentOffset + 1 : 0;
  }

  get documentRangeEnd(): number {
    return Math.min(this.documentOffset + (this.overview?.documents.length ?? 0), this.overview?.total_documents ?? 0);
  }

  onKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void this.send();
    }
  }

  clearChat() {
    this.messages = [];
    this.view = 'chat';
  }

  private addStep(message: ChatMessage, activity: string) {
    message.activity = activity;
    if (message.steps[message.steps.length - 1] !== activity) message.steps.push(activity);
  }

  private parseSseFrame(frame: string, message: ChatMessage): string | null {
    let eventName = 'message';
    const data: string[] = [];
    for (const line of frame.replace(/\r/g, '').split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
    if (!data.length) return null;
    const payload = JSON.parse(data.join('\n'));
    if (eventName === 'progress') this.addStep(message, payload.message);
    if (eventName === 'token') message.text += payload.text || '';
    if (eventName === 'error') return payload.message || 'The assistant could not respond.';
    if (eventName === 'done') message.activity = '';
    return null;
  }

  async send(value?: string) {
    const question = (value ?? this.draft).trim();
    if (!question || this.thinking) return;
    this.messages.push({ role: 'user', text: question, activity: '', steps: [] });
    const answer: ChatMessage = {
      role: 'assistant', text: '', activity: 'Connecting to the assistant', steps: [], streaming: true,
    };
    this.messages.push(answer);
    this.draft = '';
    this.thinking = true;
    try {
      const response = await fetch(`${this.api}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ message: question }),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'The assistant could not respond.');
      }
      if (!response.body) throw new Error('The browser could not read the response stream.');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      while (true) {
        const { value: bytes, done } = await reader.read();
        pending += decoder.decode(bytes, { stream: !done });
        const frames = pending.split(/\r?\n\r?\n/);
        pending = frames.pop() || '';
        for (const frame of frames) {
          const streamError = this.parseSseFrame(frame, answer);
          if (streamError) throw new Error(streamError);
        }
        if (done) break;
      }
      if (pending.trim()) {
        const streamError = this.parseSseFrame(pending, answer);
        if (streamError) throw new Error(streamError);
      }
      if (!answer.text) answer.text = 'The assistant returned an empty response.';
    } catch (error) {
      answer.text = error instanceof Error ? error.message : 'Could not connect to the backend.';
    } finally {
      answer.streaming = false;
      answer.activity = '';
      this.thinking = false;
    }
  }

  selectFiles(event: Event) {
    const input = event.target as HTMLInputElement;
    this.addSelectedFiles(Array.from(input.files || []));
    input.value = '';
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
    this.dragging = true;
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    this.dragging = false;
    this.addSelectedFiles(Array.from(event.dataTransfer?.files || []));
  }

  private addSelectedFiles(files: File[]) {
    const allowed = /\.(pdf|docx|txt|md|csv|json|zip)$/i;
    const accepted = files.filter(file => allowed.test(file.name));
    const rejected = files.length - accepted.length;
    this.selectedFiles = [...this.selectedFiles, ...accepted];
    if (rejected) this.documentNotice = `${rejected} unsupported file(s) were not added.`;
  }

  removeSelected(index: number) {
    this.selectedFiles = this.selectedFiles.filter((_, i) => i !== index);
  }

  async uploadSelected() {
    if (!this.selectedFiles.length || this.uploading) return;
    this.uploading = true;
    this.documentNotice = '';
    const form = new FormData();
    this.selectedFiles.forEach(file => form.append('files', file));
    try {
      const response = await fetch(`${this.api}/documents/upload`, { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed.');
      const errors = (data.errors || []).length;
      this.documentNotice = `${data.uploaded_count} file(s) saved for indexing${errors ? `; ${errors} skipped or failed` : ''}.`;
      this.selectedFiles = [];
      await this.refreshDocuments();
    } catch (error) {
      this.documentNotice = error instanceof Error ? error.message : 'Upload failed.';
    } finally {
      this.uploading = false;
    }
  }

  async startIndexing() {
    if (this.indexing) return;
    this.indexing = true;
    this.documentNotice = '';
    try {
      const response = await fetch(`${this.api}/documents/index`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not start indexing.');
      this.documentNotice = data.message;
      await this.refreshDocuments();
    } catch (error) {
      this.documentNotice = error instanceof Error ? error.message : 'Could not start indexing.';
    } finally {
      this.indexing = false;
    }
  }

  formatSize(size: number): string {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
}

bootstrapApplication(AppComponent).catch(error => console.error(error));
