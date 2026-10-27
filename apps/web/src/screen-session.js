// One still per explicit click. No backend upload, storage or automatic recapture.
export const CAPTURE_OPTIONS = Object.freeze({ video: { displaySurface: 'window' }, audio: false,
  selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude', systemAudio: 'exclude' });

function stopped(stream) { for (const track of stream?.getTracks() || []) track.stop(); }
const aborted = () => new DOMException('Capture cancelled.', 'AbortError');

function bounded(promise, signal, milliseconds, message) {
  return new Promise((resolve, reject) => {
    let timer;
    const cleanup = () => { clearTimeout(timer); signal.removeEventListener('abort', cancel); };
    const cancel = () => { cleanup(); reject(aborted()); };
    if (signal.aborted) { reject(aborted()); return; }
    signal.addEventListener('abort', cancel, { once: true });
    timer = setTimeout(() => { cleanup(); reject(new Error(message)); }, milliseconds);
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

export async function readScreenFrame(stream, signal, documentObject = document) {
  const video = documentObject.createElement('video');
  const canvas = documentObject.createElement('canvas');
  video.muted = true; video.playsInline = true; video.srcObject = stream;
  let clearReady = () => {};
  try {
    const ready = new Promise((resolve, reject) => {
      const loaded = () => resolve();
      const failed = () => reject(new Error('The selected surface could not be read. Paste context text instead.'));
      video.addEventListener('loadeddata', loaded, { once: true });
      video.addEventListener('error', failed, { once: true });
      clearReady = () => { video.removeEventListener('loadeddata', loaded); video.removeEventListener('error', failed); };
      if (video.readyState >= 2) resolve();
    });
    await bounded(Promise.all([video.play(), ready]), signal, 5000, 'No screen frame arrived. Select again or paste context text.');
    if (signal.aborted) throw aborted();
    const width = video.videoWidth, height = video.videoHeight;
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 16384 || height > 16384 || width * height > 33_554_432) {
      throw new Error('The selected surface has unsupported dimensions. Choose a smaller window or paste text.');
    }
    const scale = Math.min(1, 1600 / width, 1200 / height);
    canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Screen preview is unavailable. Paste context text instead.');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/webp', .8);
    if (!/^data:image\/(webp|png);base64,/.test(dataUrl) || dataUrl.length > 2_800_000) throw new Error('Screen preview is too large. Choose a smaller window or paste text.');
    return { dataUrl, width, height, previewWidth: canvas.width, previewHeight: canvas.height };
  } finally {
    clearReady(); video.pause(); video.srcObject = null; canvas.width = 0; canvas.height = 0;
  }
}

export class ScreenSession {
  constructor({ onChange, media = globalThis.navigator?.mediaDevices, readFrame = readScreenFrame, permissionMs = 30000, frameMs = 6000 }) {
    this.onChange = onChange; this.media = media; this.readFrame = readFrame;
    this.permissionMs = permissionMs; this.frameMs = frameMs; this.epoch = 0; this.disposed = false;
  }
  emit(value) { if (!this.disposed) this.onChange(value); }
  cancel() {
    this.epoch++; this.controller?.abort(); stopped(this.stream); this.stream = null;
    this.busy = false; this.emit({ status: 'idle' });
  }
  dispose() { this.cancel(); this.disposed = true; }
  async capture() {
    if (this.busy || this.disposed) return;
    this.cancel();
    if (!this.media?.getDisplayMedia) {
      this.emit({ status: 'error', error: 'Screen selection is unavailable in this browser. Paste context text instead.' }); return;
    }
    const epoch = this.epoch, controller = new AbortController();
    this.controller = controller; this.busy = true;
    let stream, ended;
    this.emit({ status: 'permission' });
    try {
      // Invoke directly within the click's transient user activation, before await.
      const pending = this.media.getDisplayMedia(CAPTURE_OPTIONS);
      Promise.resolve(pending).then(value => { if (epoch !== this.epoch || controller.signal.aborted) stopped(value); }, () => {});
      stream = await bounded(pending, controller.signal, this.permissionMs, 'Screen selection timed out. Close the chooser and try again, or paste text.');
      if (epoch !== this.epoch) { stopped(stream); return; }
      this.stream = stream;
      for (const audio of stream.getAudioTracks()) audio.stop();
      const track = stream.getVideoTracks()[0];
      if (!track || track.readyState === 'ended') throw new Error('Screen sharing ended before a frame was captured. Paste text or select again.');
      ended = () => controller.abort(); track.addEventListener('ended', ended, { once: true });
      this.emit({ status: 'capturing' });
      const frame = await bounded(this.readFrame(stream, controller.signal), controller.signal, this.frameMs, 'Screen capture timed out. Paste context text instead.');
      if (epoch !== this.epoch || controller.signal.aborted) return;
      const surface = track.getSettings?.().displaySurface;
      // Release sharing before making a still available to the UI.
      stopped(stream); this.stream = null;
      this.emit({ status: 'review', ...frame, frame: { captured_at: new Date().toISOString(),
        surface: ['window', 'monitor', 'browser'].includes(surface) ? surface : 'unknown', width: frame.width, height: frame.height } });
    } catch (error) {
      if (epoch === this.epoch) this.emit({ status: 'error', error: error.name === 'NotAllowedError'
        ? 'Screen permission was denied. Paste context text or choose a surface again.'
        : error.name === 'AbortError' ? 'Screen sharing stopped. Paste context text or select again.'
          : 'Screen selection failed. Paste context text or try again.' });
    } finally {
      controller.abort();
      const track = stream?.getVideoTracks()[0]; if (ended) track?.removeEventListener('ended', ended);
      stopped(stream);
      if (epoch === this.epoch) { this.stream = null; this.busy = false; }
    }
  }
}
