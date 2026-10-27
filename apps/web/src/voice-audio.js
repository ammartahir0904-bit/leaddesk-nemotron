export const MAX_RECORDING_SECONDS = 30;

export function encodeWav(chunks, inputRate) {
  if (!Number.isFinite(inputRate) || inputRate < 16000 || inputRate > 192000) throw new Error('Unsupported microphone sample rate. Use typed input.');
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const count = Math.min(16000 * MAX_RECORDING_SECONDS, Math.floor(length * 16000 / inputRate));
  if (count < 3200) throw new Error('Recording was too short. Hold for at least 0.2 seconds or type the command.');
  const input = new Float32Array(Math.min(length, inputRate * MAX_RECORDING_SECONDS));
  let offset = 0;
  for (const chunk of chunks) { const size = Math.min(chunk.length, input.length - offset); if (size <= 0) break; input.set(chunk.subarray(0, size), offset); offset += size; }
  const buffer = new ArrayBuffer(44 + count * 2); const view = new DataView(buffer);
  const ascii = (start, text) => { for (let i = 0; i < text.length; i++) view.setUint8(start + i, text.charCodeAt(i)); };
  ascii(0, 'RIFF'); view.setUint32(4, buffer.byteLength - 8, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); ascii(36, 'data'); view.setUint32(40, count * 2, true);
  const ratio = inputRate / 16000;
  for (let i = 0; i < count; i++) {
    const start = Math.floor(i * ratio), end = Math.max(start + 1, Math.floor((i + 1) * ratio));
    let sum = 0; for (let j = start; j < end; j++) sum += Number.isFinite(input[j]) ? input[j] : 0;
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export class PcmCapture {
  constructor({ getUserMedia = globalThis.navigator?.mediaDevices?.getUserMedia?.bind(globalThis.navigator.mediaDevices),
    AudioContextClass = globalThis.AudioContext, WorkletNode = globalThis.AudioWorkletNode } = {}) {
    Object.assign(this, { getUserMedia, AudioContextClass, WorkletNode }); this.generation = 0; this.chunks = [];
  }
  async start(onLimit, onError) {
    if (!this.getUserMedia || !this.AudioContextClass || !this.WorkletNode) throw new Error('Microphone capture is unavailable. Use typed input in this browser.');
    this.cancel(); const generation = this.generation;
    try {
      this.context = new this.AudioContextClass({ sampleRate: 16000 });
      const context = this.context; const ready = context.resume(); ready.catch(() => {});
      const stream = await this.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return false; }
      this.stream = stream;
      for (const track of stream.getTracks()) track.onended = () => { if (generation === this.generation) { this.cancel(); onError(new Error('Microphone disconnected. Recording discarded.')); } };
      await context.audioWorklet.addModule('/voice-worklet.js'); await ready;
      if (generation !== this.generation) return false;
      const source = context.createMediaStreamSource(stream);
      const node = new this.WorkletNode(context, 'leaddesk-capture', { channelCount: 1, channelCountMode: 'explicit' });
      const mute = context.createGain(); mute.gain.value = 0;
      this.node = node; this.chunks = [];
      node.port.onmessage = event => {
        if (generation !== this.generation) return;
        if (event.data.type === 'samples') this.chunks.push(event.data.samples);
        if (event.data.type === 'done') this.flushed?.();
        if (event.data.type === 'limit') { this.flushed?.(); onLimit(); }
      };
      source.connect(node); node.connect(mute); mute.connect(context.destination);
      this.timer = setTimeout(onLimit, MAX_RECORDING_SECONDS * 1000);
      return true;
    } catch (error) {
      const current = generation === this.generation;
      if (!current) return false;
      this.cancel();
      throw new Error(error.name === 'NotAllowedError' ? 'Microphone permission was denied. You can still type a command.' : 'Microphone could not start. Check its permission/device or use typed input.');
    }
  }
  async finish() {
    if (!this.node) { this.cancel(); return null; }
    const generation = this.generation; const context = this.context;
    this.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    clearTimeout(this.timer);
    await new Promise(resolve => { const timer = setTimeout(resolve, 250); this.flushed = () => { clearTimeout(timer); resolve(); }; this.node.port.postMessage({ type: 'finish' }); });
    if (generation !== this.generation) return null;
    const chunks = this.chunks; const rate = context.sampleRate;
    this.cancel(); return encodeWav(chunks, rate);
  }
  cancel() {
    this.generation++; clearTimeout(this.timer); this.flushed?.(); this.flushed = null;
    this.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); }); this.stream = null;
    if (this.node) { this.node.port.onmessage = null; this.node.disconnect(); this.node = null; }
    if (this.context) { this.context.close().catch(() => {}); this.context = null; }
    this.chunks = [];
  }
}

export function localVoices(synth = globalThis.speechSynthesis) {
  return synth?.getVoices().filter(voice => voice.localService === true) || [];
}

export function speakLocal(text, voiceURI, { synth = globalThis.speechSynthesis, Utterance = globalThis.SpeechSynthesisUtterance } = {}) {
  const voice = localVoices(synth).find(item => item.voiceURI === voiceURI);
  if (!voice || !Utterance) throw new Error('The selected local speech voice is unavailable. Text remains available.');
  synth.cancel(); const utterance = new Utterance(text.slice(0, 1000)); utterance.voice = voice; utterance.lang = voice.lang;
  synth.speak(utterance); return utterance;
}
