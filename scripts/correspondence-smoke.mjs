// Use a fresh disposable instance. Writes fictional local drafts only; no send,
// invite, account connection, source request or calendar import is performed.
import { chromium } from '../apps/web/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.env.LEADDESK_TEST_URL || 'http://127.0.0.1:8765';
const tokenFile = process.env.LEADDESK_TEST_TOKEN_FILE || resolve('../../.local/browser-check/access-token');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true });
const run = `Fictional drafts ${Date.now()}`, draftIds = [], downloads = [];
let page, auth;
try {
  const token = readFileSync(tokenFile, 'utf8').trim(); auth = { Authorization: `Bearer ${token}` };
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByLabel('Local access key').fill(token);
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await page.getByRole('button', { name: 'More tools', exact: true }).click();
  await page.getByRole('button', { name: 'Email and calendar', exact: true }).click();
  await page.getByLabel('Draft source mode').selectOption('synthetic');
  await page.getByRole('button', { name: 'New calendar draft', exact: true }).click();
  await page.getByLabel('Calendar title', { exact: true }).fill(run);
  await page.getByLabel('Calendar description', { exact: true }).fill('Fictional plain text, <script>not executed</script>.');
  await page.getByLabel('Your IANA timezone', { exact: true }).fill('America/New_York');
  await page.getByLabel('Other party’s IANA timezone', { exact: true }).fill('Asia/Karachi');
  await page.getByLabel('Start in your timezone', { exact: true }).fill('2026-03-08T02:30');
  await page.getByRole('button', { name: 'Save local draft', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'does not exist' }).waitFor();
  await page.getByLabel('Start in your timezone', { exact: true }).fill('2026-11-01T01:30');
  await page.getByRole('button', { name: 'Save local draft', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'occurs twice' }).waitFor();
  await page.getByLabel('If this local time occurs twice', { exact: true }).selectOption('1');
  let loseCreate = true;
  await page.route('**/v1/correspondence/drafts', async route => {
    if (route.request().method() === 'POST' && loseCreate) { loseCreate = false; await route.fetch(); await route.abort(); }
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Save local draft', exact: true }).click();
  await page.getByRole('button', { name: 'Retry draft request', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Local draft saved' }).waitFor();
  let drafts = (await (await page.request.get(`${base}/v1/correspondence/drafts?mode=synthetic`, { headers: auth })).json()).items;
  assert.equal(drafts.filter(d => d.title.includes(run)).length, 1);
  const calendarId = drafts.find(d => d.title.includes(run)).id; draftIds.push(calendarId);
  await page.getByText('2026-11-01T06:30:00+00:00', { exact: false }).waitFor();
  const calendarDownload = page.getByRole('button', { name: 'Download calendar file (.ics)', exact: true });
  assert.equal(await calendarDownload.isDisabled(), true);
  const approve = async () => {
    await page.getByLabel('File reviewer', { exact: true }).fill('Fictional browser reviewer');
    await page.getByLabel('Review note', { exact: true }).fill('Fictional saved file inspected for local export');
    await page.getByLabel('I reviewed this saved recipient or time, text and sharing scope for local file export.').check();
    await page.getByRole('button', { name: 'Approve this file revision', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'approved for local file export only' }).waitFor();
  };
  await approve();
  let downloading = page.waitForEvent('download'); await calendarDownload.click();
  let download = await downloading; downloads.push(download);
  const ics = readFileSync(await download.path(), 'utf8');
  assert.ok(ics.includes('DTSTART:20261101T063000Z\r\n'));
  assert.ok(ics.includes('STATUS:TENTATIVE\r\n'));
  assert.ok(!ics.includes('\r\nATTENDEE:'));
  await page.getByLabel('Calendar title', { exact: true }).fill(`${run} revised`);
  assert.equal(await calendarDownload.isDisabled(), true);
  await page.getByRole('button', { name: 'Save local draft', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Local draft saved' }).waitFor();
  assert.equal(await calendarDownload.isDisabled(), true);
  await approve();

  const response = await page.request.post(`${base}/v1/demo`, { headers: { ...auth, 'Idempotency-Key': `${run}-demo` }, data: {} });
  assert.equal(response.status(), 200); const demo = await response.json();
  const contact = demo.contacts.find(c => c.type === 'email');
  const nameEvidence = demo.evidence.find(e => e.excerpt.includes(demo.canonical_name));
  const sourceReview = await page.request.post(`${base}/v1/research/${demo.id}/identity-review`, {
    headers: { ...auth, 'Idempotency-Key': `${run}-identity` }, data: { expected_revision: 0, decision: 'source_attributed',
      source_role: 'business', business_name: { value: demo.canonical_name, evidence_ids: [nameEvidence.id] },
      contact_reviews: [{ contact_id: contact.id, decision: 'attributed', evidence_ids: contact.evidence_ids }] },
  });
  assert.equal(sourceReview.status(), 200);
  await page.getByRole('button', { name: 'Refresh drafts and review', exact: true }).click();
  await page.getByRole('button', { name: 'New email draft', exact: true }).click();
  await page.getByLabel('Source research', { exact: true }).selectOption(demo.id);
  await page.getByLabel('Your sender email', { exact: true }).fill('fictional-author@example.com');
  await page.getByLabel('Email subject', { exact: true }).fill(`${run} email`);
  await page.getByLabel('Email body', { exact: true }).fill('Fictional plain-text correspondence. No sending is authorised.');
  await page.getByRole('button', { name: 'Save local draft', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Local draft saved' }).waitFor();
  drafts = (await (await page.request.get(`${base}/v1/correspondence/drafts?mode=synthetic`, { headers: auth })).json()).items;
  const emailId = drafts.find(d => d.kind === 'email' && d.title.includes(run)).id; draftIds.push(emailId);
  await approve();
  downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download email draft (.eml)', exact: true }).click();
  download = await downloading; downloads.push(download);
  assert.ok(readFileSync(await download.path(), 'utf8').includes('X-Unsent: 1\r\n'));
  const correction = await page.request.post(`${base}/v1/feedback`, { headers: auth, data: { contact_id: contact.id, category: 'wrong_branch', comment: 'Fictional late correction' } });
  assert.equal(correction.status(), 200);
  await page.getByRole('button', { name: 'Refresh drafts and review', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'suppressed' }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Download email draft (.eml)', exact: true }).isDisabled(), true);
  const emailCard = page.locator('.correspondence-card').filter({ hasText: `${run} email` });
  await emailCard.getByRole('button', { name: 'Delete local draft', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delete local draft', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Local draft deleted' }).waitFor();
  assert.equal((await page.request.get(`${base}/v1/correspondence/drafts/${emailId}`, { headers: auth })).status(), 404);
  assert.equal((await (await page.request.get(`${base}/v1/research/${demo.id}`, { headers: auth })).json()).contacts.find(c => c.id === contact.id).suppressed, true);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: synthetic local draft editing, DST gap/fold, lost-create retry, explicit revision review, ICS/EML downloads, unsaved/edit invalidation, late suppression and deletion; no sending or import');
} finally {
  for (const download of downloads) await download.delete();
  if (page && auth) for (const id of draftIds) await page.request.delete(`${base}/v1/correspondence/drafts/${id}`, { headers: auth }).catch(() => {});
  await browser.close();
}
