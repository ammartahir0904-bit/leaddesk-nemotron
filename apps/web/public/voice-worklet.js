// Same-origin PCM capture only. No speech service, network or durable storage.
class LeadDeskCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer = new Float32Array(1024); this.used = 0; this.frames = 0; this.done = false;
    this.port.onmessage = event => { if (event.data.type === 'finish') this.finish('done'); };
  }
  flush() {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage({ type: 'samples', samples }, [samples.buffer]); this.used = 0;
  }
  finish(type) { this.flush(); this.done = true; this.port.postMessage({ type }); }
  process(inputs) {
    if (this.done) return false;
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const value of channel) {
      this.buffer[this.used++] = value; this.frames++;
      if (this.used === this.buffer.length) this.flush();
      if (this.frames >= sampleRate * 30) { this.finish('limit'); return false; }
    }
    return true;
  }
}
registerProcessor('leaddesk-capture', LeadDeskCapture);
