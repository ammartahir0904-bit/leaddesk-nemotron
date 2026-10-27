import React, { useEffect, useRef, useState } from 'react';

const rate = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;

function Metrics({ value }) {
  return <span>{value.sample_count} examples · Baseline {value.baseline_correct} ({rate(value.baseline_exact_match)}) · Candidate {value.candidate_correct} ({rate(value.candidate_exact_match)}) · Gains {value.gains} · Regressions {value.regressions} · Abstentions {value.abstentions}</span>;
}

export default function EvaluationPanel({ api, dataset, mode, revision }) {
  const [name, setName] = useState(''), [artifact, setArtifact] = useState(''), [text, setText] = useState('');
  const [abstention, setAbstention] = useState('');
  const [reports, setReports] = useState(null), [report, setReport] = useState(null), [deleting, setDeleting] = useState(null);
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState('');
  const request = useRef(null), builtinRequest = useRef(null), pending = useRef(new AbortController());
  const eligible = dataset?.status === 'ready' && dataset.purpose === 'evaluation' && dataset.mode === mode;
  const disabled = busy || loading;
  useEffect(() => () => pending.current.abort(), []);
  useEffect(() => { setText(''); request.current = null; builtinRequest.current = null; }, [dataset?.id, dataset?.status]);
  useEffect(() => {
    const controller = new AbortController(); let current = true;
    setLoading(true); setError(''); setReport(null); setReports(null);
    api(`/v1/experiments?mode=${mode}&offset=${offset}`, { signal: controller.signal })
      .then(value => { if (current) setReports(value); })
      .catch(e => { if (current && e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [api, mode, offset, refresh, revision]);
  async function run(action) {
    if (disabled) return;
    setBusy(true); setError('');
    try { await action(); } catch (e) { if (e.name !== 'AbortError') setError(e.message); }
    finally { setBusy(false); }
  }
  async function compare(event) {
    event.preventDefault();
    await run(async () => {
      let predictions;
      try { predictions = JSON.parse(text); } catch { throw new Error('Candidate outputs must be a JSON array.'); }
      const payload = { dataset_id: dataset.id, dataset_sha256: dataset.dataset_sha256,
        candidate_name: name, artifact_sha256: artifact, predictions };
      const signature = JSON.stringify(payload);
      if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
      const result = await api('/v1/experiments', { method: 'POST', headers: { 'Idempotency-Key': request.current.key },
        body: signature, signal: pending.current.signal });
      request.current = null;
      setReport(result); setText('');
      // Refresh list without resetting the just-created report.
      setReports(await api(`/v1/experiments?mode=${mode}&offset=${offset}`, { signal: pending.current.signal }));
    });
  }
  async function runBuiltin(event) {
    event.preventDefault();
    await run(async () => {
      const payload = { dataset_id: dataset.id, dataset_sha256: dataset.dataset_sha256, candidate: 'contact_ranker_v1',
        abstention_output: abstention.trim() ? abstention : null };
      const signature = JSON.stringify(payload);
      if (builtinRequest.current?.signature !== signature) builtinRequest.current = { signature, key: crypto.randomUUID() };
      const result = await api('/v1/experiments/builtin', { method: 'POST', headers: { 'Idempotency-Key': builtinRequest.current.key },
        body: signature, signal: pending.current.signal });
      builtinRequest.current = null;
      setReport(result);
      setReports(await api(`/v1/experiments?mode=${mode}&offset=${offset}`, { signal: pending.current.signal }));
    });
  }
  async function download() {
    await run(async () => {
      const blob = await api(`/v1/experiments/${report.id}/export`, { download: true, signal: pending.current.signal });
      const url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = `leaddesk-evaluation-${report.id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  return <section className="panel evaluation-panel"><h2>Local candidate evaluation</h2>
    <p>Compare candidate outputs with reviewed expected text. Exact matches include whitespace. The built-in ranker runs locally; imported outputs and artifact identity are unverified. No model runs, training or promotion occur. Unsaved candidate text is temporary.</p>
    <p>Inspect a ready evaluation-purpose dataset in the current source mode above to compare it. Development comparisons are for tuning. Holdout labels may have been inspected; these comparisons cannot certify independent held-out improvement.</p>
    {eligible && <form onSubmit={runBuiltin}>
      <h3>Built-in contact ranker v1</h3>
      <p>Runs a bundled deterministic heuristic on this host. It reads only each example's reviewed input text and source domain, never the observed or expected output. It picks the best-attributed contact or abstains; factual-support examples are always abstentions. Its weights were fixed on fictional fixtures, not tuned on your data.</p>
      <label htmlFor="evaluation-abstention">Abstention text (optional; must match your reviewers' exact wording, otherwise abstentions count as incorrect)</label>
      <input id="evaluation-abstention" value={abstention} maxLength={1000} disabled={disabled} onChange={e => setAbstention(e.target.value)}/>
      <button className="primary" type="submit" disabled={disabled}>Run built-in contact ranker</button>
    </form>}
    {eligible && <form onSubmit={compare}>
      <h3>Imported candidate outputs</h3>
      <p>Selected: {dataset.name} · {dataset.mode} · {dataset.split} · {dataset.sample_count} examples</p>
      <label htmlFor="evaluation-name">Candidate name</label><input id="evaluation-name" value={name} maxLength={120} minLength={3} required disabled={disabled} onChange={e => setName(e.target.value)}/>
      <label htmlFor="evaluation-artifact">Candidate artifact SHA-256</label><input id="evaluation-artifact" value={artifact} pattern="[a-f0-9]{64}" maxLength={64} required disabled={disabled} onChange={e => setArtifact(e.target.value)}/>
      <p>Supply one entry per example: <code>{'{"example_id":"…","output":"candidate text"}'}</code>. Use JSON null for an abstention, which counts as incorrect. The whole request must fit 16,000 bytes.</p>
      <button type="button" className="secondary" disabled={disabled} onClick={() => setText(JSON.stringify(dataset.examples.map(item => ({ example_id: item.id, output: null })), null, 2))}>Prepare abstention template</button>
      <label htmlFor="evaluation-outputs">Candidate outputs JSON</label><textarea id="evaluation-outputs" rows={8} value={text} required disabled={disabled} onChange={e => setText(e.target.value)}/>
      <button className="primary" type="submit" disabled={disabled || !text}>Compare candidate outputs</button>
    </form>}
    {error && <p className="alert" role="alert">{error}</p>}
    {busy && <p role="status">Checking local evaluation…</p>}
    <div className="learning-actions"><button className="secondary" disabled={disabled} onClick={() => setRefresh(v => v + 1)}>Refresh evaluation reports</button></div>
    <h3>Saved evaluation reports</h3><p>{mode} · {reports?.total ?? '…'} reports · {loading ? 'Loading…' : `Page ${Math.floor(offset / 20) + 1}`}</p>
    {reports?.items.map(item => <article className="learning-card" key={item.id}><h4>{item.candidate_name}</h4><p>{item.status} · {item.created_at}</p>
      {item.report && <p>{item.report.mode} · {item.report.split} · <Metrics value={item.report.overall}/></p>}
      <div className="learning-actions"><button className="secondary" disabled={disabled} onClick={() => run(async () => setReport(await api(`/v1/experiments/${item.id}`, { signal: pending.current.signal })))}>Inspect evaluation report</button>
        <button className="text-button" disabled={disabled} onClick={() => setDeleting(item.id)}>Delete evaluation report</button></div>
    </article>)}
    <div className="learning-actions"><button className="secondary" disabled={disabled || !offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous evaluation reports</button>
      <button className="secondary" disabled={disabled || reports?.next_offset == null} onClick={() => setOffset(reports.next_offset)}>Next evaluation reports</button></div>
    {deleting && <div className="learning-confirm"><p>Delete this report? Its dataset and original research remain. Downloaded copies need separate removal.</p>
      <button className="primary" disabled={disabled} onClick={() => run(async () => { await api(`/v1/experiments/${deleting}`, { method: 'DELETE', signal: pending.current.signal }); setDeleting(null); setReport(null); setRefresh(v => v + 1); })}>Confirm delete evaluation report</button>
      <button className="secondary" disabled={busy} onClick={() => setDeleting(null)}>Keep evaluation report</button></div>}
    {report && <section className="learning-version"><h3>Evaluation report: {report.candidate_name}</h3>
      <p>{report.status} · Dataset SHA-256: {report.dataset_sha256}</p><p>{report.report?.candidate_provenance === 'builtin_executed_locally' ? 'Executed built-in candidate artifact' : 'Asserted candidate artifact'}: {report.artifact_sha256}</p>
      {report.report ? <><p>{report.report.mode} · {report.report.split} · {report.report.outcome.replaceAll('_', ' ')}</p>
        <p><Metrics value={report.report.overall}/></p>
        <h4>By task</h4>{Object.entries(report.report.by_task).map(([key, value]) => <p key={key}>{key}: <Metrics value={value}/></p>)}
        <h4>By domain</h4>{Object.entries(report.report.by_domain).map(([key, value]) => <p key={key}>{key}: <Metrics value={value}/></p>)}
        {report.report.candidate_decisions && <p>Candidate decisions: {Object.entries(report.report.candidate_decisions).map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`).join(' · ')}</p>}
        {report.report.limitations.map(value => <p key={value}>{value}</p>)}
        <p>Comparison took {report.report.comparison_ms.toFixed(3)} ms on this evaluation host. {report.report.candidate_inference_ms == null ? 'Candidate inference time and memory are unknown.' : `Candidate inference took ${report.report.candidate_inference_ms.toFixed(3)} ms with ${report.report.candidate_peak_memory_bytes} bytes peak traced Python memory.`} {report.report.prior_retained_dataset_reports} earlier retained reports used this dataset; deleted reports are excluded.</p>
        <details><summary>Configuration and evaluation-host hardware</summary><pre>{JSON.stringify({ configuration: report.report.configuration, hardware: report.report.hardware }, null, 2)}</pre></details>
      </> : <p>This report was invalidated. Its metrics were cleared; review the dataset sources and run a new comparison.</p>}
      <button className="primary" disabled={disabled || report.status !== 'ready'} onClick={download}>Export evaluation report</button>
    </section>}
  </section>;
}
