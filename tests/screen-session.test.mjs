// Generated media/controllers only. These checks do not exercise OS permissions.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CAPTURE_OPTIONS, ScreenSession, readScreenFrame } from '../apps/web/src/screen-session.js';

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function mediaStream({ audio = false, surface = 'window' } = {}) {
  const video = Object.assign(new EventTarget(), { readyState: 'live', stops: 0, stop() { this.stops++; this.readyState = 'ended'; }, getSettings: () => ({ displaySurface: surface }) });
  const sound = { stops: 0, stop() { this.stops++; } };
  return { video, sound, getTracks: () => audio ? [video, sound] : [video], getAudioTracks: () => audio ? [sound] : [], getVideoTracks: () => [video] };
}
const fixtureFrame = { dataUrl: 'data:image/webp;base64,AAAA', width: 1920, height: 1080, previewWidth: 1600, previewHeight: 900 };
function setup(getDisplayMedia, readFrame = async () => fixtureFrame, options = {}) {
  const states = [];
  const session = new ScreenSession({ media: { getDisplayMedia }, readFrame, onChange: state => states.push(state), ...options });
  return { states, session };
}

test('capture needs an explicit call, requests no audio and releases sharing before review', async () => {
  const stream = mediaStream({ audio: true }); let calls = 0;
  const { session, states } = setup(options => { calls++; assert.deepEqual(options, CAPTURE_OPTIONS); assert.equal(options.audio, false); return Promise.resolve(stream); }, async () => {
    assert.ok(stream.sound.stops > 0); return fixtureFrame;
  });
  assert.equal(calls, 0);
  const original = session.onChange;
  session.onChange = state => { if (state.status === 'review') assert.ok(stream.video.stops > 0); original(state); };
  await session.capture();
  assert.equal(calls, 1); assert.equal(session.busy, false);
  assert.deepEqual(states.map(state => state.status), ['idle', 'permission', 'capturing', 'review']);
  assert.equal(states.at(-1).frame.surface, 'window'); assert.equal(states.at(-1).frame.width, 1920);
  assert.ok(Number.isFinite(Date.parse(states.at(-1).frame.captured_at)));
  session.cancel(); assert.deepEqual(states.at(-1), { status: 'idle' });
});
test('denied or unavailable screen capture leaves a usable text fallback', async () => {
  const { session, states } = setup(async () => { throw new DOMException('Private OS diagnostic', 'NotAllowedError'); });
  await session.capture(); assert.match(states.at(-1).error, /permission was denied/); assert.doesNotMatch(states.at(-1).error, /Private OS/);
  session.media = null; await session.capture(); assert.match(states.at(-1).error, /unavailable/);
  session.dispose();
});
test('cancellation during permission stops a late stream without capturing', async () => {
  const pending = deferred(), stream = mediaStream(); let frames = 0;
  const { session, states } = setup(() => pending.promise, async () => { frames++; return fixtureFrame; });
  const operation = session.capture(); session.cancel(); await operation;
  pending.resolve(stream); await tick();
  assert.ok(stream.video.stops > 0); assert.equal(frames, 0); assert.equal(states.at(-1).status, 'idle');
});
test('late old permission rejection cannot erase a newer preview', async () => {
  const old = deferred(), current = deferred(), stream = mediaStream(); let calls = 0;
  const { session, states } = setup(() => (++calls === 1 ? old : current).promise);
  const first = session.capture(); session.cancel(); const second = session.capture();
  current.resolve(stream); await second;
  old.reject(new Error('Late failure')); await first; await tick();
  assert.equal(states.at(-1).status, 'review'); session.dispose();
});
test('permission timeout releases late tracks and does not read a frame', async () => {
  const pending = deferred(), stream = mediaStream(); let frames = 0;
  const { session, states } = setup(() => pending.promise, async () => { frames++; }, { permissionMs: 5 });
  await session.capture(); assert.equal(states.at(-1).status, 'error'); assert.equal(session.busy, false);
  pending.resolve(stream); await tick(); assert.ok(stream.video.stops > 0); assert.equal(frames, 0);
});
test('cancel during frame capture discards a late frame and aborts the reader', async () => {
  const pending = deferred(), stream = mediaStream(); let signal;
  const { session, states } = setup(async () => stream, async (_stream, value) => { signal = value; return pending.promise; });
  const operation = session.capture(); await tick();
  session.cancel(); await operation; assert.equal(signal.aborted, true); assert.ok(stream.video.stops > 0);
  pending.resolve(fixtureFrame); await tick(); assert.equal(states.at(-1).status, 'idle');
});
test('frame timeout aborts reader, stops stream and leaves no preview', async () => {
  const pending = deferred(), stream = mediaStream(); let signal;
  const { session, states } = setup(async () => stream, async (_stream, value) => { signal = value; return pending.promise; }, { frameMs: 5 });
  await session.capture(); assert.equal(signal.aborted, true); assert.ok(stream.video.stops > 0);
  assert.equal(states.at(-1).status, 'error'); assert.equal(session.busy, false); pending.resolve(fixtureFrame);
});
test('ending sharing mid-frame discards output and prevents background recapture', async () => {
  const pending = deferred(), stream = mediaStream(); let calls = 0;
  const { session, states } = setup(async () => { calls++; return stream; }, async () => pending.promise);
  const operation = session.capture(); await tick(); stream.video.dispatchEvent(new Event('ended'));
  await operation; pending.resolve(fixtureFrame); await tick();
  assert.equal(states.at(-1).status, 'error'); assert.ok(stream.video.stops > 0); assert.equal(calls, 1);
});
test('duplicate start is ignored and disposal suppresses all later results', async () => {
  const pending = deferred(), stream = mediaStream(); let calls = 0;
  const { session, states } = setup(() => { calls++; return pending.promise; });
  const operation = session.capture(); await session.capture(); assert.equal(calls, 1);
  session.dispose(); const count = states.length; await operation;
  pending.resolve(stream); await tick(); await session.capture();
  assert.ok(stream.video.stops > 0); assert.equal(states.length, count); assert.equal(calls, 1);
});
test('frame failure and ended tracks stop all media without exposing diagnostics', async () => {
  const stream = mediaStream({ audio: true });
  const { session, states } = setup(async () => stream, async () => { throw new Error('Sensitive application title'); });
  await session.capture(); assert.equal(states.at(-1).status, 'error'); assert.doesNotMatch(states.at(-1).error, /Sensitive/);
  assert.ok(stream.video.stops > 0); assert.ok(stream.sound.stops > 0);
  stream.video.readyState = 'ended'; await session.capture(); assert.equal(states.at(-1).status, 'error');
});

function frameEnvironment({ width = 3840, height = 2160, dataUrl = 'data:image/webp;base64,AAAA', ready = true } = {}) {
  const video = Object.assign(new EventTarget(), { readyState: ready ? 2 : 0, videoWidth: width, videoHeight: height, srcObject: null,
    paused: false, play: async () => {}, pause() { this.paused = true; } });
  const draws = [], canvas = { width: 0, height: 0, getContext: () => ({ drawImage: (...args) => draws.push(args) }), toDataURL: () => dataUrl };
  return { video, canvas, draws, document: { createElement: name => name === 'video' ? video : canvas } };
}
test('frame reader bounds preview size, records native dimensions and clears video/canvas', async () => {
  const environment = frameEnvironment(), stream = mediaStream();
  const frame = await readScreenFrame(stream, new AbortController().signal, environment.document);
  assert.equal(frame.width, 3840); assert.equal(frame.height, 2160);
  assert.equal(frame.previewWidth, 1600); assert.equal(frame.previewHeight, 900);
  assert.equal(environment.draws.length, 1); assert.equal(environment.video.srcObject, null);
  assert.equal(environment.video.paused, true); assert.equal(environment.canvas.width, 0); assert.equal(environment.canvas.height, 0);
});
test('frame reader rejects invalid dimensions, excessive output and unavailable canvas', async () => {
  for (const options of [{ width: 0 }, { width: 17000 }, { width: 8192, height: 8192 }, { dataUrl: 'data:,' }, { dataUrl: 'data:image/png;base64,' + 'A'.repeat(2_800_000) }]) {
    const environment = frameEnvironment(options);
    await assert.rejects(readScreenFrame(mediaStream(), new AbortController().signal, environment.document));
    assert.equal(environment.video.srcObject, null); assert.equal(environment.canvas.width, 0);
  }
  const environment = frameEnvironment(); environment.canvas.getContext = () => null;
  await assert.rejects(readScreenFrame(mediaStream(), new AbortController().signal, environment.document), /unavailable/);
});
test('aborting before a frame arrives removes handlers and clears media references', async () => {
  const environment = frameEnvironment({ ready: false }), controller = new AbortController();
  const operation = readScreenFrame(mediaStream(), controller.signal, environment.document);
  controller.abort(); await assert.rejects(operation, { name: 'AbortError' });
  assert.equal(environment.video.srcObject, null); assert.equal(environment.video.paused, true); assert.equal(environment.canvas.width, 0);
});
