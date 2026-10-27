// Pure browser-controller tests with fake media devices; no microphone is used.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { encodeWav, PcmCapture, localVoices, speakLocal } from '../apps/web/src/voice-audio.js';
import { VoiceSession, waitForPoll } from '../apps/web/src/voice-session.js';

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const stream = () => { const track = { stops: 0, stop() { this.stops++; }, onended: null }; return { track, getTracks: () => [track] }; };
function audioEnvironment(getUserMedia) {
  const contexts = [], nodes = [];
  class Context {
    constructor() { this.sampleRate = 16000; this.closed = false; this.audioWorklet = { addModule: async url => { assert.equal(url, '/voice-worklet.js'); } }; contexts.push(this); }
    resume() { return Promise.resolve(); }
    close() { this.closed = true; return Promise.resolve(); }
    createMediaStreamSource() { return { connect() {} }; }
    createGain() { return { gain: {}, connect() {} }; }
  }
  class Worklet {
    constructor() { this.port = { onmessage: null, postMessage: value => { if (value.type === 'finish') queueMicrotask(() => this.port.onmessage?.({ data: { type: 'done' } })); } }; nodes.push(this); }
    connect() {} disconnect() { this.disconnected = true; }
  }
  return { capture: new PcmCapture({ getUserMedia, AudioContextClass: Context, WorkletNode: Worklet }), contexts, nodes };
}

test('PCM encoding averages 48 kHz samples into bounded mono 16 kHz WAV', async () => {
  const samples = new Float32Array(48000 / 4).fill(.5);
  const blob = encodeWav([samples.subarray(0, 5000), samples.subarray(5000)], 48000);
  const data = new DataView(await blob.arrayBuffer());
  assert.equal(blob.type, 'audio/wav'); assert.equal(blob.size, 44 + 4000 * 2);
  assert.equal(data.getUint16(22, true), 1); assert.equal(data.getUint32(24, true), 16000);
  assert.equal(data.getUint16(34, true), 16); assert.equal(data.getInt16(44, true), 16384);
});
test('encoding clamps invalid samples, rejects short input and caps duration', async () => {
  assert.throws(() => encodeWav([new Float32Array(100)], 16000), /too short/);
  assert.throws(() => encodeWav([new Float32Array(4000)], 8000), /sample rate/);
  const input = new Float32Array(16000 * 31).fill(2); input[0] = NaN; input[1] = -2;
  const blob = encodeWav([input], 16000); const data = new DataView(await blob.arrayBuffer());
  assert.equal(blob.size, 960044); assert.equal(data.getInt16(44, true), 0); assert.equal(data.getInt16(46, true), -32768);
});
test('releasing while permission is pending stops a late microphone stream', async () => {
  const pending = deferred(), media = stream(); const { capture, contexts, nodes } = audioEnvironment(() => pending.promise);
  const start = capture.start(() => {}, () => {}); capture.cancel(); pending.resolve(media);
  assert.equal(await start, false); assert.equal(media.track.stops, 1); assert.equal(contexts[0].closed, true); assert.equal(nodes.length, 0);
});
test('a stale permission rejection cannot cancel a newer recording', async () => {
  const first = deferred(), second = deferred(), media = stream(); let calls = 0;
  const { capture, contexts, nodes } = audioEnvironment(() => (++calls === 1 ? first : second).promise);
  const old = capture.start(() => {}, () => {}); capture.cancel(); const current = capture.start(() => {}, () => {});
  second.resolve(media); assert.equal(await current, true);
  first.reject(new Error('late rejected permission')); assert.equal(await old, false);
  assert.equal(contexts[1].closed, false); assert.equal(nodes[0].disconnected, undefined);
  capture.cancel(); assert.equal(contexts[1].closed, true);
});
test('permission denial and missing device support leave capture stopped', async () => {
  const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
  const { capture, contexts } = audioEnvironment(async () => { throw denied; });
  await assert.rejects(capture.start(() => {}, () => {}), /permission was denied/);
  assert.equal(contexts[0].closed, true);
  await assert.rejects(new PcmCapture({ getUserMedia: null }).start(() => {}, () => {}), /unavailable/);
});
test('finish stops tracks, flushes PCM, closes context and drops raw chunks', async () => {
  const media = stream(); const { capture, contexts, nodes } = audioEnvironment(async () => media);
  await capture.start(() => {}, () => {});
  nodes[0].port.onmessage({ data: { type: 'samples', samples: new Float32Array(4000).fill(.1) } });
  const blob = await capture.finish(); assert.equal(blob.size, 8044);
  assert.ok(media.track.stops >= 1); assert.equal(contexts[0].closed, true); assert.equal(capture.chunks.length, 0);
});
test('worklet limit and microphone disconnect invoke the stop paths', async () => {
  const media = stream(); let limits = 0, errors = 0;
  const { capture, nodes } = audioEnvironment(async () => media);
  await capture.start(() => limits++, () => errors++);
  nodes[0].port.onmessage({ data: { type: 'limit' } }); assert.equal(limits, 1);
  media.track.onended(); assert.equal(errors, 1); assert.equal(capture.stream, null);
});
test('real worklet bounds PCM to thirty seconds and flushes partial blocks', () => {
  const messages = []; let Processor;
  class Base { constructor() { this.port = { postMessage: message => messages.push(message) }; } }
  const sandbox = { AudioWorkletProcessor: Base, sampleRate: 16000, Float32Array, registerProcessor: (_name, value) => { Processor = value; } };
  vm.runInNewContext(readFileSync(new URL('../apps/web/public/voice-worklet.js', import.meta.url), 'utf8'), sandbox);
  const processor = new Processor();
  assert.equal(processor.process([[new Float32Array(16000 * 31).fill(.25)]]), false);
  assert.equal(messages.filter(item => item.type === 'samples').reduce((sum, item) => sum + item.samples.length, 0), 16000 * 30);
  assert.equal(messages.at(-1).type, 'limit');
  assert.equal(processor.process([[new Float32Array(128)]]), false);
  messages.length = 0; const short = new Processor(); short.process([[new Float32Array(128).fill(.5)]]);
  short.port.onmessage({ data: { type: 'finish' } });
  assert.equal(messages[0].samples.length, 128); assert.equal(messages.at(-1).type, 'done');
});

function sessionEnvironment(api, captureChanges = {}, wait = async () => {}) {
  const states = [], calls = [];
  const capture = { start: async () => true, finish: async () => new Blob(['fictional wav fixture']), cancel() {}, ...captureChanges };
  const session = new VoiceSession({ api: async (path, options = {}) => { calls.push({ path, options }); return api(path, options); }, capture,
    uuid: () => 'fictional-session-id', wait, onChange: state => states.push(state) });
  return { session, states, calls, capture };
}
test('dictation stops at editable review and never runs a command automatically', async () => {
  let polls = 0;
  const { session, calls } = sessionEnvironment(async (path, options) => options.method === 'PUT' ? { state: 'running' } :
    { state: ++polls === 1 ? 'completed' : 'running', transcript: 'remember wrong speech transcript' });
  await session.start('ur'); await session.finish();
  assert.equal(session.state.status, 'review'); assert.equal(session.state.transcript, 'remember wrong speech transcript');
  assert.equal(calls[0].options.headers['Content-Type'], 'audio/wav'); assert.match(calls[0].path, /language=ur/);
  assert.equal(calls.some(call => call.path.includes('/commands/')), false); await session.dispose();
});
test('release before permission completes cannot upload late audio', async () => {
  const pending = deferred(); const { session, calls } = sessionEnvironment(async () => assert.fail('No API call expected'), { start: () => pending.promise });
  const start = session.start('auto'); await session.finish(); pending.resolve(true); await start;
  assert.equal(session.state.status, 'idle'); assert.equal(calls.length, 0); await session.dispose();
});
test('cancel during upload discards a late response and sends server cancellation', async () => {
  const pending = deferred();
  const { session, calls } = sessionEnvironment(async (_path, options) => options.method === 'PUT' ? pending.promise : { state: 'cancelled' });
  await session.start('en'); const result = session.finish(); await tick();
  await session.cancel(); pending.resolve({ state: 'completed', transcript: 'unwanted late transcript' }); await result;
  assert.equal(session.state.transcript, ''); assert.equal(session.state.status, 'idle');
  assert.equal(calls.some(call => call.options.method === 'DELETE'), true);
  assert.equal(calls[0].options.signal.aborted, true); await session.dispose();
});
test('cancel while polling prevents stale completion from appearing', async () => {
  const polling = deferred();
  const { session } = sessionEnvironment(async (_path, options) => options.method === 'DELETE' ? { state: 'cancelled' } : { state: 'running' }, {}, () => polling.promise);
  await session.start('en'); const result = session.finish(); await tick(); await session.cancel(); polling.resolve(); await result;
  assert.equal(session.state.status, 'idle'); assert.equal(session.state.transcript, ''); await session.dispose();
});
test('failed or silent transcription keeps typed fallback available', async () => {
  for (const job of [{ state: 'failed', message: 'Fictional ASR failure' }, { state: 'completed', transcript: '', message: 'No speech detected' }]) {
    const { session } = sessionEnvironment(async (_path, options) => options.method === 'DELETE' ? { state: 'cancelled' } : job);
    await session.start('auto'); await session.finish();
    assert.ok(session.state.error); assert.equal(session.state.transcript, ''); await session.dispose();
  }
});
test('dispose suppresses late UI updates and polling waits abort promptly', async () => {
  const pending = deferred(); const { session, states } = sessionEnvironment(async () => ({}), { start: () => pending.promise });
  const starting = session.start('auto'); await session.dispose(); const count = states.length; pending.resolve(true); await starting;
  assert.equal(states.length, count);
  const controller = new AbortController(); const wait = waitForPoll(controller.signal); controller.abort();
  await assert.rejects(wait, error => error.name === 'AbortError');
});
test('speech output excludes remote voices and rechecks a selected local voice', () => {
  const local = { voiceURI: 'local-fixture', localService: true, lang: 'en' }, remote = { voiceURI: 'remote-fixture', localService: false };
  const spoken = []; const synth = { getVoices: () => [local, remote], cancel() {}, speak: utterance => spoken.push(utterance) };
  class Utterance { constructor(text) { this.text = text; } }
  assert.deepEqual(localVoices(synth), [local]);
  assert.throws(() => speakLocal('fixture', remote.voiceURI, { synth, Utterance }), /unavailable/);
  const utterance = speakLocal('Reviewed result', local.voiceURI, { synth, Utterance });
  assert.equal(utterance.voice, local); assert.equal(spoken.length, 1);
  synth.getVoices = () => [remote]; assert.throws(() => speakLocal('fixture', local.voiceURI, { synth, Utterance }), /unavailable/);
});
