import { bootstrapApplication } from '@angular/platform-browser';
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

type Message = { role: 'user' | 'assistant'; text: string };

@Component({
  selector: 'app-root', standalone: true, imports: [CommonModule, FormsModule],
  template: `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">✳</div><span>groundwork</span></div>
        <button class="new-chat" (click)="clearChat()"><span>＋</span> New conversation</button>
        <div class="side-label">WORKSPACE</div>
        <div class="nav-item active"><span>◈</span> Knowledge assistant</div>
        <div class="side-label source-label">YOUR SOURCES <span>{{ documents.length }}</span></div>
        <label class="upload-card" [class.uploading]="uploading">
          <input type="file" accept=".pdf,.txt,.md,.csv,.json" (change)="upload($event)" [disabled]="uploading">
          <span class="upload-icon">↑</span><strong>{{ uploading ? 'Indexing…' : 'Add a document' }}</strong><small>PDF, TXT, MD, CSV or JSON</small>
        </label>
        <div class="doc-list"><div class="doc" *ngFor="let doc of documents"><span class="file-icon">▤</span><span>{{ doc }}</span><i>✓</i></div></div>
        <div class="sidebar-bottom"><span class="status-dot"></span><span>Agent ready</span><span class="version">v0.1</span></div>
      </aside>
      <main class="main">
        <header><div><span class="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</span><h1>Ask anything.</h1><p>Your documents, thoughtfully connected.</p></div><button class="settings" title="Backend status" (click)="checkHealth()">⚙ <span>{{ configured ? 'Connected' : 'Setup needed' }}</span></button></header>
        <section class="conversation" #conversation>
          <div class="welcome" *ngIf="messages.length === 0">
            <div class="welcome-glyph">✳</div><div class="hello">A little more clarity,<br><em>one question away.</em></div>
            <p>Upload your notes, guides, and documents. I’ll help you find the useful bits and bring them together.</p>
            <div class="suggestions"><button *ngFor="let prompt of prompts" (click)="send(prompt)"><span>↗</span>{{ prompt }}</button></div>
          </div>
          <div class="messages" *ngIf="messages.length">
            <article *ngFor="let m of messages" class="message" [class.user]="m.role === 'user'">
              <div class="avatar">{{ m.role === 'user' ? 'Y' : '✳' }}</div><div class="bubble"><div class="role">{{ m.role === 'user' ? 'YOU' : 'GROUNDWORK' }}</div><div class="text">{{ m.text }}</div></div>
            </article>
            <article *ngIf="thinking" class="message"><div class="avatar">✳</div><div class="bubble"><div class="role">GROUNDWORK</div><div class="typing"><i></i><i></i><i></i></div></div></article>
          </div>
        </section>
        <div class="composer-wrap"><div class="composer"><textarea [(ngModel)]="draft" (keydown)="onKey($event)" placeholder="Ask a question about your knowledge…" rows="1"></textarea><button (click)="send()" [disabled]="!draft.trim() || thinking" aria-label="Send">↑</button></div><div class="fineprint">Grounded in your sources · Powered by an AI agent with tools</div></div>
      </main>
    </div>
    <div class="toast" *ngIf="notice">{{ notice }}</div>
  `
})
class AppComponent {
  draft = ''; messages: Message[] = []; documents: string[] = []; thinking = false; uploading = false; configured = false; notice = '';
  prompts = ['What are the key ideas in my documents?', 'Summarize a topic across my sources', 'Help me compare two approaches'];
  private api = 'http://localhost:8000/api';
  constructor() { this.checkHealth(); }
  async checkHealth() { try { const r = await fetch(`${this.api}/health`); const d = await r.json(); this.configured = d.configured; } catch { this.configured = false; } }
  onKey(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.send(); } }
  clearChat() { this.messages = []; }
  async send(value?: string) {
    const message = (value ?? this.draft).trim(); if (!message || this.thinking) return;
    this.messages.push({ role: 'user', text: message }); this.draft = ''; this.thinking = true;
    try { const r = await fetch(`${this.api}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) }); const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'The assistant could not respond.'); this.messages.push({ role: 'assistant', text: d.answer }); }
    catch (e) { this.messages.push({ role: 'assistant', text: e instanceof Error ? e.message : 'Could not connect to the backend.' }); }
    finally { this.thinking = false; }
  }
  async upload(event: Event) {
    const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return;
    this.uploading = true; const form = new FormData(); form.append('file', file);
    try { const r = await fetch(`${this.api}/upload`, { method: 'POST', body: form }); const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'Upload failed.'); this.documents.push(file.name); this.notice = `${file.name} indexed · ${d.chunks} chunks`; }
    catch (e) { this.notice = e instanceof Error ? e.message : 'Upload failed.'; }
    finally { this.uploading = false; input.value = ''; setTimeout(() => this.notice = '', 4000); }
  }
}

bootstrapApplication(AppComponent).catch(err => console.error(err));
