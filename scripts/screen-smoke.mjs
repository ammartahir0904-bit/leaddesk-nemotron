// Fictional browser acceptance. Generated canvas stream; no real desktop is read.
import { chromium } from '../apps/web/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.env.LEADDESK_TEST_URL || 'http://127.0.0.1:8765';
const tokenFile = process.env.LEADDESK_TEST_TOKEN_FILE || resolve('../../.local/access-token');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true });
const scope = `screen-smoke-${Date.now()}`;
let page, token;
try {
  token = readFileSync(tokenFile, 'utf8').trim();
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], bodies = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/v1/screen/')) {
      const body = request.postData(); if (body) { assert.doesNotMatch(body, /data:image|base64|dataUrl/); bodies.push(JSON.parse(body)); }
    }
  });
  await page.addInitScript(() => {
    window.__screenDenied = true; window.__screenStops = 0; window.__screenCalls = 0;
    navigator.mediaDevices.getDisplayMedia = options => {
      window.__screenCalls++; window.__screenOptions = options;
      if (window.__screenDenied) return Promise.reject(new DOMException('Fictional denied permission', 'NotAllowedError'));
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
      const context = canvas.getContext('2d');
      const paint = () => { context.fillStyle = '#ffffff'; context.fillRect(0, 0, 640, 480); context.fillStyle = '#000000'; context.font = '24px sans-serif'; context.fillText('Fictional clinic template error', 30, 80); };
      paint(); const stream = canvas.captureStream(10), track = stream.getVideoTracks()[0], stop = track.stop.bind(track);
      const interval = setInterval(paint, 50);
      track.stop = () => { clearInterval(interval); if (track.readyState !== 'ended') window.__screenStops++; stop(); };
      if (window.__screenDelay) return new Promise(resolve => { window.__screenResolve = () => resolve(stream); });
      return Promise.resolve(stream);
    };
  });
  const auth = { Authorization: `Bearer ${token}` };
  await page.goto(base);
  await page.getByLabel('Local access key').fill(token); await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await page.getByRole('button', { name: 'More tools', exact: true }).click();
  await page.getByRole('button', { name: 'Screen context', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__screenCalls), 0);
  await page.getByRole('button', { name: 'Choose screen or window', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Screen permission was denied' }).waitFor();
  await page.getByLabel('Context source label').fill('Fictional editor');
  await page.getByLabel('Reviewed context text').fill('Fictional clinic template error');
  await page.getByLabel('Context action', { exact: true }).selectOption('save_note');
  await page.getByLabel('Memory scope for context action').fill(scope);
  await page.getByRole('button', { name: 'Prepare context action', exact: true }).click();
  await page.getByRole('heading', { name: 'Context action to review', exact: true }).waitFor();
  assert.equal((await (await page.request.get(`${base}/v1/memories?scope=${scope}`, { headers: auth })).json()).total, 0);
  await page.getByLabel('Reviewed context text').fill('Corrected fictional clinic template error');
  assert.equal(await page.getByRole('heading', { name: 'Context action to review', exact: true }).count(), 0);
  await page.getByRole('button', { name: 'Prepare context action', exact: true }).click();
  await page.getByRole('button', { name: 'Save reviewed context', exact: true }).click();
  await page.getByRole('heading', { name: 'Context action result', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Save reviewed context', exact: true }).click();
  await page.getByRole('status').filter({ hasText: `Saved your reviewed context in ${scope}.` }).waitFor();
  const notes = await (await page.request.get(`${base}/v1/memories?scope=${scope}`, { headers: auth })).json();
  assert.equal(notes.total, 1); assert.equal(notes.items[0].content, 'Corrected fictional clinic template error');
  await page.getByLabel('Context action', { exact: true }).selectOption('search_memories');
  await page.getByLabel('Search keywords from context').fill('clinic');
  await page.getByRole('button', { name: 'Prepare context action', exact: true }).click();
  await page.getByRole('button', { name: 'Run reviewed context search', exact: true }).click();
  await page.getByRole('heading', { name: 'Context action result', exact: true }).waitFor();
  assert.match(await page.locator('.screen-result').innerText(), /Corrected fictional clinic template error/);

  await page.evaluate(() => { window.__screenDenied = false; });
  await page.getByRole('button', { name: 'Choose screen or window', exact: true }).click();
  await page.getByAltText('Temporary preview of your selected surface').waitFor();
  assert.ok(await page.evaluate(() => window.__screenStops) > 0);
  assert.equal(await page.evaluate(() => window.__screenOptions.audio), false);
  await page.getByLabel('Context source label').fill('Generated canvas, no real desktop');
  await page.getByLabel('Reviewed context text').fill('Generated fixture text, supplied by user');
  await page.getByLabel('Search keywords from context').fill('clinic');
  await page.getByRole('button', { name: 'Prepare context action', exact: true }).click();
  await page.getByRole('heading', { name: 'Context action to review', exact: true }).waitFor();
  assert.equal(bodies.at(-1).context.frame.width, 640);
  await page.getByRole('button', { name: 'Discard screen context', exact: true }).click();
  assert.equal(await page.getByAltText('Temporary preview of your selected surface').count(), 0);
  assert.equal(await page.getByLabel('Reviewed context text').inputValue(), '');

  await page.evaluate(() => { window.__screenDelay = true; });
  await page.getByRole('button', { name: 'Choose screen or window', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Waiting for screen selection' }).waitFor();
  await page.getByRole('button', { name: 'Discard screen context', exact: true }).click();
  await page.evaluate(() => window.__screenResolve());
  await page.waitForFunction(() => window.__screenStops >= 2);
  assert.equal(await page.getByAltText('Temporary preview of your selected surface').count(), 0);
  await page.getByLabel('Reviewed context text').fill('Discard on navigation');
  await page.getByRole('button', { name: 'Voice', exact: true }).click();
  await page.getByRole('button', { name: 'Screen context', exact: true }).click();
  assert.equal(await page.getByLabel('Reviewed context text').inputValue(), '');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: fictional denied capture/text fallback, one still/track cleanup, no image upload, reviewed/idempotent save, scoped search, stale-plan invalidation, late cancellation, navigation deletion and mobile overflow');
} finally {
  if (page && token) await page.request.delete(`${base}/v1/memories/scope?scope=${encodeURIComponent(scope)}`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  await browser.close();
}
