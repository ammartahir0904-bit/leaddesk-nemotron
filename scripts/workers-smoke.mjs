// Disposable-data browser acceptance. Simulates a paired worker with local
// synthetic measurements; this does not establish a real PC/SSH connection.
import { chromium } from '../apps/web/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.env.LEADDESK_TEST_URL || 'http://127.0.0.1:8765';
const tokenFile = process.env.LEADDESK_TEST_TOKEN_FILE || resolve('../../.local/browser-check/access-token');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true });
let page, auth, workerId, download;
try {
  const token = readFileSync(tokenFile, 'utf8').trim(); auth = { Authorization: `Bearer ${token}` };
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const run = `Fictional PC ${Date.now()}`;
  await page.goto(base);
  await page.getByLabel('Local access key').fill(token);
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await page.getByRole('button', { name: 'More tools', exact: true }).click();
  await page.getByRole('button', { name: 'PC workers', exact: true }).click();
  await page.getByText('Disabled: no active worker pairing.', { exact: false }).waitFor();
  await page.getByLabel('Computer name', { exact: true }).fill(run);
  await page.getByRole('button', { name: 'Pair PC worker', exact: true }).click();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download worker credential', exact: true }).click();
  download = await downloading;
  const credential = JSON.parse(readFileSync(await download.path(), 'utf8'));
  workerId = credential.worker_id;
  assert.equal(credential.schema_version, 1);
  assert.ok(credential.token.length >= 32);
  const workerAuth = { Authorization: `Bearer ${credential.token}` };
  await page.getByRole('button', { name: 'Forget displayed credential', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Download worker credential', exact: true }).count(), 0);
  await page.getByRole('button', { name: 'Queue worker benchmark', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Synthetic benchmark queued' }).waitFor();
  await page.getByRole('button', { name: 'Cancel worker task', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Worker task cancelled' }).waitFor();
  await page.getByRole('button', { name: 'Queue worker benchmark', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Synthetic benchmark queued' }).waitFor();
  const claimed = await page.request.post(`${base}/v1/pc-worker/claim`, { headers: { ...workerAuth, 'Idempotency-Key': `${run}-claim` } });
  assert.equal(claimed.status(), 200);
  const leased = (await claimed.json()).task;
  assert.equal(leased.worker_id, workerId);
  const report = JSON.parse(execFileSync(resolve('../../.venv/bin/python'), ['-m', 'backend.workflows.pc_executor', '2'], { cwd: resolve('../..'), encoding: 'utf8' }));
  const completed = await page.request.post(`${base}/v1/pc-worker/tasks/${leased.id}/complete`, {
    headers: workerAuth, data: { lease_token: leased.lease_token, result: report },
  });
  assert.equal(completed.status(), 200);
  await page.getByRole('button', { name: 'Refresh workers and tasks', exact: true }).click();
  await page.getByText('10 / 10 checks passed', { exact: false }).waitFor();
  await page.getByText('Worker-reported measurements;', { exact: false }).waitFor();
  let failRefresh = true;
  await page.route('**/v1/pc-workers', async route => {
    if (route.request().method() === 'GET' && failRefresh) { failRefresh = false; await route.abort(); }
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Refresh workers and tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Retry worker request', exact: true }).click();
  await page.getByRole('alert').waitFor({ state: 'detached' });
  await page.getByRole('button', { name: `Revoke ${run}`, exact: true }).click();
  await page.getByRole('button', { name: 'Confirm revoke worker', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Worker pairing revoked' }).waitFor();
  assert.equal((await page.request.post(`${base}/v1/pc-worker/claim`, { headers: { ...workerAuth, 'Idempotency-Key': `${run}-revoked` } })).status(), 401);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: explicit pairing/credential download/forget, offline queue/cancel, simulated worker completion, labelled results, refresh retry, revocation and mobile overflow; no real remote connection');
} finally {
  await download?.delete();
  if (page && auth && workerId) await page.request.post(`${base}/v1/pc-workers/${workerId}/revoke`, { headers: auth }).catch(() => {});
  await browser.close();
}
