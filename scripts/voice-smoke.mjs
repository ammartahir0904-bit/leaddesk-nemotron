// Fictional browser acceptance: generated audio and mocked ASR/TTS, no real microphone/model.
import { chromium } from '../apps/web/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.env.LEADDESK_TEST_URL || 'http://127.0.0.1:8765';
const tokenFile = process.env.LEADDESK_TEST_TOKEN_FILE || resolve('../../.local/access-token');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true });
const scope = `voice-smoke-${Date.now()}`;
let page, token;
try {
  token = readFileSync(tokenFile, 'utf8').trim();
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.__voiceDenied = true;
    navigator.mediaDevices.getUserMedia = async () => {
      if (window.__voiceDenied) throw new DOMException('Synthetic denied permission', 'NotAllowedError');
      const context = new AudioContext(); const oscillator = context.createOscillator(); const gain = context.createGain();
      const destination = context.createMediaStreamDestination(); gain.gain.value = .2;
      oscillator.connect(gain); gain.connect(destination); oscillator.start(); await context.resume();
      window.__voiceFixtureContext = context;
      const track = destination.stream.getAudioTracks()[0], stop = track.stop.bind(track);
      let stopped = false;
      track.stop = () => { if (stopped) return; stopped = true; stop(); oscillator.stop(); context.close(); };
      return destination.stream;
    };
    const events = new EventTarget();
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: class { constructor(text) { this.text = text; } } });
    Object.defineProperty(window, 'speechSynthesis', { value: {
      getVoices: () => [{ voiceURI: 'fictional-local', name: 'Fictional local voice', lang: 'en', localService: true },
        { voiceURI: 'fictional-remote', name: 'Fictional remote voice', lang: 'en', localService: false }],
      addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events),
      cancel() { window.__voiceStops = (window.__voiceStops || 0) + 1; },
      speak(utterance) { window.__spokenVoice = utterance.voice.voiceURI; queueMicrotask(() => utterance.onend?.()); }
    }});
  });
  await page.route('**/v1/voice/status', route => route.fulfill({ json: {
    available: true, engine: 'fictional_browser_adapter', max_seconds: 30, reason: 'Fictional test adapter; no model is used.', cloud_enabled: false } }));
  let uploads = 0, cancels = 0, delay = false, releasePoll;
  await page.route('**/v1/voice/transcriptions/*', async route => {
    const method = route.request().method();
    if (method === 'DELETE') { cancels++; releasePoll?.(); await route.fulfill({ json: { state: 'cancelled' } }); return; }
    if (method === 'PUT') {
      uploads++; const wav = route.request().postDataBuffer();
      assert.equal(wav.subarray(0, 4).toString(), 'RIFF'); assert.ok(wav.length > 6400 && wav.length <= 1000000);
      await route.fulfill({ status: 202, json: delay ? { state: 'running' } : { state: 'completed', transcript: 'remember Wrong fictional clinic preference' } }); return;
    }
    if (delay) await new Promise(resolve => { releasePoll = resolve; });
    await route.fulfill({ json: { state: 'completed', transcript: 'remember Late unwanted fictional note' } }).catch(() => {});
  });
  await page.goto(base);
  await page.getByLabel('Local access key').fill(token); await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await page.getByRole('button', { name: 'More tools', exact: true }).click();
  await page.getByRole('button', { name: 'Voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start short recording', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Microphone permission was denied' }).waitFor();
  assert.equal(uploads, 0);
  await page.evaluate(() => { window.__voiceDenied = false; });
  await page.getByRole('button', { name: 'Start short recording', exact: true }).click();
  await page.getByText('Microphone on. Audio stays local and is not retained as a recording.', { exact: true }).waitFor();
  await page.waitForFunction(() => window.__voiceFixtureContext.currentTime > .4);
  await page.getByRole('button', { name: 'Finish short recording', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#voice-transcript').value === 'remember Wrong fictional clinic preference');
  assert.equal(uploads, 1);
  assert.equal((await page.request.get(`${base}/v1/memories?scope=${encodeURIComponent(scope)}`, { headers: { Authorization: `Bearer ${token}` } })).status(), 200);
  await page.getByLabel('Transcript or typed command').fill('remember Corrected fictional clinic preference');
  await page.getByLabel('Memory scope for voice command').fill(scope);
  await page.getByRole('button', { name: 'Prepare reviewed command', exact: true }).click();
  await page.getByRole('heading', { name: 'Action to review', exact: true }).waitFor();
  const before = await page.request.get(`${base}/v1/memories?scope=${encodeURIComponent(scope)}`, { headers: { Authorization: `Bearer ${token}` } });
  assert.equal((await before.json()).total, 0);
  assert.equal(await page.getByRole('button', { name: 'Read aloud', exact: true }).isDisabled(), true);
  assert.equal(await page.getByLabel('Local output voice').locator('option').count(), 1);
  await page.getByLabel('Enable local speech output').check();
  await page.getByRole('button', { name: 'Read aloud', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__spokenVoice), 'fictional-local');
  await page.getByRole('button', { name: 'Stop speech output', exact: true }).click();
  await page.getByRole('button', { name: 'Save reviewed memory', exact: true }).click();
  await page.getByRole('status').filter({ hasText: `Saved your reviewed note in ${scope}.` }).waitFor();
  const saved = await page.request.get(`${base}/v1/memories?scope=${encodeURIComponent(scope)}`, { headers: { Authorization: `Bearer ${token}` } });
  assert.equal((await saved.json()).items[0].content, 'Corrected fictional clinic preference');
  await page.getByLabel('Transcript or typed command').fill('search memory clinic');
  assert.equal(await page.getByRole('heading', { name: 'Action to review', exact: true }).count(), 0);
  await page.getByRole('button', { name: 'Prepare reviewed command', exact: true }).click();
  await page.getByRole('button', { name: 'Run reviewed search', exact: true }).click();
  await page.getByRole('heading', { name: 'Command result', exact: true }).waitFor();
  assert.match(await page.locator('.voice-result').innerText(), /Corrected fictional clinic preference/);
  delay = true;
  await page.getByRole('button', { name: 'Start short recording', exact: true }).click();
  await page.getByText('Microphone on. Audio stays local and is not retained as a recording.', { exact: true }).waitFor();
  await page.waitForFunction(() => window.__voiceFixtureContext.currentTime > .4);
  await page.getByRole('button', { name: 'Finish short recording', exact: true }).click();
  await page.getByText('Microphone off. Transcribing locally…', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Cancel voice command', exact: true }).click();
  await page.getByText('Microphone off.', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('Transcript or typed command').inputValue(), ''); assert.ok(cancels > 0);
  await page.getByLabel('Transcript or typed command').fill('delete all files');
  await page.getByRole('button', { name: 'Prepare reviewed command', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Supported commands' }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: fictional denied/captured microphone, PCM upload, corrected transcript, review before save, scoped search, local-only optional speech, cancel/late response, unsupported actions and mobile layout');
} finally {
  if (page && token) await page.request.delete(`${base}/v1/memories/scope?scope=${encodeURIComponent(scope)}`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  await browser.close();
}
