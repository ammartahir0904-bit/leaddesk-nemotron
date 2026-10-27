// Disposable synthetic records only. Only the bundled deterministic ranker executes; no model, training or promotion.
import { chromium } from '../apps/web/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.env.LEADDESK_TEST_URL || 'http://127.0.0.1:8765';
const tokenFile = process.env.LEADDESK_TEST_TOKEN_FILE || resolve('../../.local/browser-check/access-token');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true });
const run = `evaluation-smoke-${Date.now()}`;
let page, auth, exampleId, versionId, download;
try {
  const token = readFileSync(tokenFile, 'utf8').trim(); auth = { Authorization: `Bearer ${token}` };
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  async function request(method, path, body, key) {
    const response = await page.request.fetch(`${base}${path}`, { method, headers: { ...auth, ...(key ? { 'Idempotency-Key': key } : {}) }, ...(body ? { data: body } : {}) });
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  }
  const demo = await request('POST', '/v1/demo', {}, `${run}-demo`);
  const corrected = await request('POST', '/v1/feedback', { contact_id: demo.contacts[0].id, category: 'wrong_contact', comment: run });
  const sourceList = await request('GET', '/v1/learning/sources?mode=synthetic');
  const source = sourceList.items.find(item => item.ref.id === corrected.feedback[0].id);
  assert.ok(source);
  const example = await request('POST', '/v1/learning/examples', {
    source: source.ref, expected_source_hash: source.source_hash, expected_revision: 0,
    decision: 'include', reviewer: 'Fictional browser reviewer', reason: 'Synthetic source reviewed',
    input_text: `Fictional evaluation input ${run}`, observed_output: 'Fictional wrong output', expected_output: `Fictional reviewed output ${run}`,
    evidence_ids: [source.evidence[0].id], redaction_confirmed: true, permission_basis: 'Authored synthetic fixture for local testing', use_scope: 'local_evaluation',
  }, `${run}-example`);
  exampleId = example.id;
  const dataset = await request('POST', '/v1/learning/versions', {
    name: run, purpose: 'evaluation', split: 'development', mode: 'synthetic', examples: [{ id: example.id, revision: example.revision }],
  }, `${run}-dataset`);
  versionId = dataset.id;
  await page.goto(base);
  await page.getByLabel('Local access key').fill(token); await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await page.getByRole('button', { name: 'More tools', exact: true }).click();
  await page.getByRole('button', { name: 'Learning and datasets', exact: true }).click();
  await page.getByLabel('Learning record source').selectOption('synthetic');
  const versionCard = page.locator('.learning-card').filter({ hasText: run }).filter({ has: page.getByRole('button', { name: 'Inspect dataset version', exact: true }) });
  await versionCard.getByRole('button', { name: 'Inspect dataset version', exact: true }).click();
  await page.getByLabel('Candidate name').fill(run);
  await page.getByLabel('Candidate artifact SHA-256').fill('a'.repeat(64));
  await page.getByRole('button', { name: 'Prepare abstention template', exact: true }).click();
  assert.deepEqual(JSON.parse(await page.getByLabel('Candidate outputs JSON').inputValue()), [{ example_id: example.id, output: null }]);
  await page.getByLabel('Candidate outputs JSON').fill('{');
  await page.getByRole('button', { name: 'Compare candidate outputs', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Candidate outputs must be a JSON array.' }).waitFor();
  await page.getByLabel('Candidate outputs JSON').fill(JSON.stringify([{ example_id: 'foreign', output: null }]));
  await page.getByRole('button', { name: 'Compare candidate outputs', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Supply exactly one output or null abstention' }).waitFor();
  await page.getByLabel('Candidate outputs JSON').fill(JSON.stringify([{ example_id: example.id, output: example.review.expected_output }]));
  let submitted, lost = false;
  await page.route('**/v1/experiments', async route => {
    if (route.request().method() === 'POST' && !lost) {
      submitted = JSON.parse(route.request().postData());
      const response = await route.fetch(); assert.equal(response.status(), 200);
      lost = true; await route.abort('failed');
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Compare candidate outputs', exact: true }).click();
  await page.locator('.evaluation-panel [role=alert]').waitFor();
  await page.getByRole('button', { name: 'Compare candidate outputs', exact: true }).click();
  await page.getByRole('heading', { name: `Evaluation report: ${run}`, exact: true }).waitFor();
  const list = await request('GET', '/v1/experiments?mode=synthetic');
  const matching = list.items.filter(item => item.candidate_name === run);
  assert.equal(matching.length, 1); assert.equal(matching[0].report.overall.gains, 1);
  assert.equal(matching[0].report.promotion_allowed, false);
  assert.equal(matching[0].report.independent_holdout_verified, false);
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export evaluation report', exact: true }).click(); download = await downloading;
  const exported = JSON.parse(readFileSync(await download.path(), 'utf8'));
  assert.equal(exported.dataset_sha256, dataset.dataset_sha256);
  assert.equal(exported.report.mode, 'synthetic'); assert.equal(exported.report.overall.candidate_correct, 1);
  assert.equal(JSON.stringify(exported).includes(example.review.expected_output), false);
  await page.getByRole('button', { name: 'Run built-in contact ranker', exact: true }).click();
  await page.getByRole('heading', { name: 'Evaluation report: Built-in contact ranker v1', exact: true }).waitFor();
  const builtin = (await request('GET', '/v1/experiments?mode=synthetic')).items.find(item => item.candidate_name === 'Built-in contact ranker v1' && item.dataset_id === dataset.id);
  assert.equal(builtin.report.candidate_provenance, 'builtin_executed_locally');
  assert.deepEqual(builtin.report.candidate_decisions, { abstained_no_contact: 1 });
  assert.equal(builtin.report.promotion_allowed, false);
  await page.getByText(/Candidate inference took/).waitFor();
  let refreshFailed = false;
  await page.route('**/v1/experiments?*', async route => {
    if (!refreshFailed) { refreshFailed = true; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Fictional evaluation refresh failure', retryable: true }) }); }
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Refresh evaluation reports', exact: true }).click();
  await page.locator('.evaluation-panel [role=alert]').waitFor();
  await page.getByRole('button', { name: 'Refresh evaluation reports', exact: true }).click();
  await page.locator('.evaluation-panel .learning-card').filter({ hasText: run }).waitFor();
  await request('DELETE', `/v1/learning/examples/${example.id}`); exampleId = null;
  await page.getByRole('button', { name: 'Refresh evaluation reports', exact: true }).click();
  const reportCard = page.locator('.evaluation-panel .learning-card').filter({ hasText: run });
  await reportCard.getByText(/invalidated/).waitFor();
  await reportCard.getByRole('button', { name: 'Inspect evaluation report', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Export evaluation report', exact: true }).isDisabled(), true);
  const replay = await page.request.post(`${base}/v1/experiments`, { headers: { ...auth, 'Idempotency-Key': `${run}-stale` }, data: submitted });
  assert.equal(replay.status(), 409);
  await reportCard.getByRole('button', { name: 'Delete evaluation report', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delete evaluation report', exact: true }).click();
  await reportCard.waitFor({ state: 'detached' });
  const preserved = await request('GET', `/v1/research/${demo.id}`);
  assert.equal(preserved.contacts.find(item => item.id === demo.contacts[0].id).suppressed, true);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: exact-output comparison, invalid JSON/foreign coverage, lost-response replay, report export, built-in ranker run, refresh retry, invalidation/deletion and mobile overflow; no model execution');
} finally {
  await download?.delete();
  if (page && auth) {
    if (exampleId) await page.request.delete(`${base}/v1/learning/examples/${exampleId}`, { headers: auth }).catch(() => {});
    if (versionId) await page.request.delete(`${base}/v1/learning/versions/${versionId}`, { headers: auth }).catch(() => {});
  }
  await browser.close();
}
