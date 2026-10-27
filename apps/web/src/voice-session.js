import { PcmCapture } from './voice-audio.js';

export function waitForPoll(signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
    const cancel = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, 500);
    signal.addEventListener('abort', cancel, { once: true });
  });
}

export class VoiceSession {
  constructor({ api, onChange, capture = new PcmCapture(), uuid = () => crypto.randomUUID(), wait = waitForPoll }) {
    Object.assign(this, { api, onChange, capture, uuid, wait });
    this.generation = 0; this.state = { status: 'idle', transcript: '', error: '' }; this.disposed = false;
  }
  emit(change) { this.state = { ...this.state, ...change }; if (!this.disposed) this.onChange(this.state); }
  async start(language) {
    if (this.disposed || ['permission', 'recording', 'transcribing'].includes(this.state.status)) return;
    this.cancel(); const generation = this.generation; this.language = language;
    this.emit({ status: 'permission', transcript: '', error: '' });
    try {
      const started = await this.capture.start(() => this.finish(), error => { this.cancel(); this.emit({ status: 'error', error: error.message }); });
      if (generation === this.generation && started) this.emit({ status: 'recording' });
    } catch (error) { if (generation === this.generation) this.emit({ status: 'error', error: error.message }); }
  }
  async finish() {
    if (this.state.status === 'permission') { this.cancel(); return; }
    if (this.state.status !== 'recording') return;
    const generation = this.generation;
    this.emit({ status: 'transcribing', error: '' });
    let deadlineTimer;
    try {
      let wav = await this.capture.finish();
      if (!wav || generation !== this.generation) return;
      this.jobId = this.uuid(); const jobId = this.jobId;
      this.controller = new AbortController(); const signal = this.controller.signal;
      deadlineTimer = setTimeout(() => {
        if (generation === this.generation) { this.cancel(); this.emit({ status: 'error', error: 'Transcription timed out. Try a shorter recording or type the command.' }); }
      }, 120000);
      let job = await this.api(`/v1/voice/transcriptions/${jobId}?language=${this.language}`, {
        method: 'PUT', body: wav, headers: { 'Content-Type': 'audio/wav' }, signal });
      wav = null;
      if (generation !== this.generation) return;
      // A client deadline complements the server's bounded runtime. Requests
      // cannot leave a polling loop active indefinitely after a lost server.
      const deadline = Date.now() + 120000;
      while (job.state === 'running') {
        if (Date.now() > deadline) throw new Error('Transcription timed out. Cancel it and try a shorter recording.');
        await this.wait(signal);
        if (generation !== this.generation) return;
        job = await this.api(`/v1/voice/transcriptions/${jobId}`, { signal });
        if (generation !== this.generation) return;
      }
      if (generation !== this.generation) return;
      if (job.state === 'cancelled') { this.emit({ status: 'idle', transcript: '' }); return; }
      if (job.state !== 'completed') throw new Error(job.message || 'Local transcription failed. Use typed input.');
      this.emit({ status: 'review', transcript: job.transcript || '', error: job.transcript ? '' : job.message });
    } catch (error) {
      if (generation !== this.generation || error.name === 'AbortError') return;
      this.emit({ status: 'error', error: error.message });
    } finally {
      clearTimeout(deadlineTimer);
    }
  }
  cancel() {
    this.generation++; const generation = this.generation;
    this.capture.cancel(); this.controller?.abort(); this.controller = null;
    const jobId = this.jobId; this.jobId = null;
    this.emit({ status: 'idle', transcript: '', error: '' });
    if (jobId) {
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 3000);
      return this.api(`/v1/voice/transcriptions/${jobId}`, { method: 'DELETE', signal: controller.signal }).catch(() => {
        if (generation === this.generation) this.emit({ error: 'Microphone stopped. Server cancellation could not be confirmed; no command will run. Unreviewed text expires after five minutes.' });
      }).finally(() => clearTimeout(timer));
    }
    return Promise.resolve();
  }
  dispose() { this.disposed = true; return this.cancel(); }
}
