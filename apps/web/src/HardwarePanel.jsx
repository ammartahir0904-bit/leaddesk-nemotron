import React, { useEffect, useRef, useState } from 'react';
import './HardwarePanel.css';

function bytes(value) {
  return value == null ? 'Unknown' : `${(value / 1024 ** 3).toFixed(2)} GiB`;
}

function milliseconds(value) {
  return value == null ? 'Not measured' : `${value.toFixed(2)} ms`;
}

function exportReport(report) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `leaddesk-benchmark-${report.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const FIT = { fits_gpu: 'Fits GPU', fits_cpu: 'Runs on CPU', too_big: 'Too big', no_disk: 'No disk space' };

function AIModelChoice({ api }) {
  const [state, setState] = useState(null), [choice, setChoice] = useState(''), [cloudChoice, setCloudChoice] = useState('');
  const [agree, setAgree] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const load = () => api('/v1/ai/status').then(value => {
    setState(value);
    setChoice(value.selected?.provider !== 'token_factory' && value.selected?.name || value.models[0]?.name || '');
    const cloud = value.token_factory?.models || [];
    setCloudChoice(value.selected?.provider === 'token_factory' ? value.selected.name : (cloud.find(m => /super/i.test(m.name)) || cloud[0])?.name || '');
  }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [api]);
  async function select(model, provider) {
    setBusy(true); setError('');
    try { await api('/v1/ai/model', { method: 'POST', body: JSON.stringify({ model, provider }) }); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const cloud = state?.token_factory, onCloud = state?.selected?.provider === 'token_factory';
  return <section className="panel model-advisor" aria-labelledby="ai-choice-heading">
    <div className="panel-title"><h2 id="ai-choice-heading">Model for AI rewording and analysis</h2>
      <button className="secondary" onClick={load} disabled={busy}>Refresh</button></div>
    {error && <p role="alert" className="alert">{error}</p>}
    {!state ? <p className="muted">Checking models…</p> : <>
      <p className="muted">{state.ready ? `Using ${state.selected.name} ${onCloud ? 'on Nebius Token Factory (NVIDIA Nemotron).' : 'on this computer; your data is not sent anywhere.'}` : state.problem || 'No model chosen yet.'}</p>
      <h3>NVIDIA Nemotron on Nebius Token Factory</h3>
      {!cloud?.configured ? <p className="muted">{cloud?.message}</p> : cloud.models.length ? <>
        <p className="muted">When you use a Token Factory model, LeadDesk sends the prompts it builds to Nebius: a business's public facts
          (name, type, website findings) and your product text. Nothing else, and nothing until you choose a model here. Every answer is still checked word by word.</p>
        <div className="ai-choice"><label htmlFor="cloud-model">NVIDIA models</label>
          <select id="cloud-model" value={cloudChoice} onChange={e => setCloudChoice(e.target.value)}>{cloud.models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}</select>
          {!onCloud && <label className="check"><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)}/><span>I agree to send these prompts to Nebius Token Factory.</span></label>}
          <button className="primary" disabled={busy || !cloudChoice || (!onCloud && !agree)} onClick={() => select(cloudChoice, 'token_factory')}>Use this model</button></div></>
        : <p className="muted">{cloud.message}</p>}
      <h3>Local model (Ollama)</h3>
      {!state.ollama.running ? <p className="muted">Ollama is not running. Start it with scripts/ollama.sh start.</p> : state.models.length ? <div className="ai-choice"><label htmlFor="ai-model">Installed models</label>
        <select id="ai-model" value={choice} onChange={e => setChoice(e.target.value)}>{state.models.map(m => <option key={m.name} value={m.name}>{m.name}{m.size_bytes ? ` (${bytes(m.size_bytes)})` : ''}</option>)}</select>
        <button className="secondary" disabled={busy || !choice} onClick={() => select(choice, 'ollama')}>Use this local model</button></div> : <p className="muted">No models installed yet. Run: ollama pull llama3.2:3b</p>}
    </>}
  </section>;
}

function ModelAdvisor({ api }) {
  const [value, setValue] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function check() {
    setBusy(true); setError('');
    try { setValue(await api('/v1/hardware/advisor', { method: 'POST' })); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const advice = value?.advice;
  return <section className="panel model-advisor" aria-labelledby="advisor-heading">
    <div className="panel-title"><h2 id="advisor-heading">Which AI models should this computer use?</h2>
      <button className="primary" onClick={check} disabled={busy}>{value ? 'Check again' : 'Check this computer'}</button></div>
    <p className="muted">Reads this computer's memory, processor, NVIDIA GPU and disk, checks for Ollama and its installed models, then recommends local models. Nothing is downloaded or installed for you. Run LeadDesk on your stronger PC and check there too.</p>
    {busy && <p role="status">Checking hardware and Ollama…</p>}
    {error && <p role="alert" className="alert">{error}</p>}
    {advice && <>
      <dl className="hardware-specs">
        <div><dt>Computer class</dt><dd>{advice.tier}</dd></div>
        <div><dt>GPU</dt><dd>{value.gpus.length ? value.gpus.map(g => `${g.name}${g.vram_bytes ? ` · ${bytes(g.vram_bytes)}` : ''}`).join('; ') : 'No dedicated GPU detected (an NVIDIA GPU is detected through nvidia-smi).'}</dd></div>
        <div><dt>Ollama</dt><dd>{value.ollama.running ? `Running · ${value.ollama.models.length} models installed` : value.ollama.installed ? 'Installed but not running (start it with: ollama serve)' : 'Not installed'}</dd></div>
        <div><dt>Recommended</dt><dd>{[advice.main_model, advice.embedding_model].filter(Boolean).join(' + ') || 'None fits'}</dd></div>
      </dl>
      <h3>Next steps</h3><ol className="advisor-steps">{advice.next_steps.map(step => <li key={step}><code>{step}</code></li>)}</ol>
      <div className="benchmark-table-wrap"><table><caption>Model options for this computer</caption>
        <thead><tr><th scope="col">Model</th><th scope="col">Fit</th><th scope="col">Download</th><th scope="col">What it does for you</th></tr></thead>
        <tbody>{advice.models.map(m => <tr key={m.tag} className={m.recommended ? 'advisor-pick' : ''}>
          <td><strong>{m.tag}</strong>{m.recommended && <small> Recommended</small>}{m.installed && <small> Installed</small>}</td>
          <td>{FIT[m.fit]}<small>{m.speed}</small></td><td>~{m.download_gib} GB</td><td>{m.role}<small>{m.leaddesk_use}</small></td></tr>)}</tbody>
      </table></div>
      <ul className="advisor-notes">{advice.notes.map(note => <li key={note}>{note}</li>)}</ul>
    </>}
  </section>;
}

function BenchmarkReport({ report }) {
  const parser = report.kind === 'parser';
  return <section className="panel benchmark-report" aria-labelledby="benchmark-report-heading">
    <div className="panel-title"><h2 id="benchmark-report-heading">{parser ? 'Parser benchmark' : 'Local model benchmark'}</h2>
      <span className="tag">{report.status}</span></div>
    <p className="muted">{new Date(report.measured_at).toLocaleString()} · Synthetic fixtures · {report.sample_count} checks</p>
    <div className="metric-grid">
      <div><h3>Checks passed</h3><p>{report.passed_count} / {report.sample_count}</p></div>
      {parser && <><div><h3>First round</h3><p>{milliseconds(report.timing.first_round_ms)}</p></div>
        <div><h3>Later rounds, median</h3><p>{milliseconds(report.timing.warm_round_p50_ms)}</p></div>
        <div><h3>Round p95</h3><p>{milliseconds(report.timing.round_p95_ms)}</p></div></>}
      <div><h3>Runner peak memory</h3><p>{bytes(report.memory.peak_runner_rss_bytes)}</p></div>
    </div>
    <p className="muted">{parser ? 'Each round runs five fixed cases. No model or network is used.' : `Model: ${report.model.id}. CPU inference only.`}</p>
    <details className="benchmark-details"><summary>Checks and measurement limits</summary>
      <ul>{report.limitations.map(text => <li key={text}>{text}</li>)}</ul>
      <p className="hash">Fixture SHA-256: {report.fixture_sha256}</p>
      <p className="hash">Model digest: {report.model_hash || 'None — deterministic parser'}</p>
      <div className="benchmark-table-wrap"><table><caption>Individual synthetic checks</caption>
        <thead><tr><th scope="col">Case</th><th scope="col">Round</th><th scope="col">Result</th></tr></thead>
        <tbody>{report.results.map(result => <tr key={`${result.case_id}-${result.round}`}>
          <th scope="row">{result.case_id}</th><td>{result.round}</td><td>{result.passed ? 'Passed' : result.failure || 'Failed'}</td>
        </tr>)}</tbody></table></div>
    </details>
    <button className="secondary" onClick={() => exportReport(report)}>Download report JSON</button>
  </section>;
}

export default function HardwarePanel({ api }) {
  const [profile, setProfile] = useState(null);
  const [runs, setRuns] = useState([]);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestKey = useRef(null);

  useEffect(() => {
    let active = true;
    Promise.all([api('/v1/hardware/profile', { method: 'POST' }), api('/v1/benchmarks')])
      .then(([snapshot, history]) => { if (active) { setProfile(snapshot); setRuns(history); } })
      .catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [api]);

  async function refresh() {
    setBusy(true); setError('');
    try { setProfile(await api('/v1/hardware/profile', { method: 'POST' })); }
    catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function runBenchmark() {
    if (busy) return;
    setBusy(true); setError('');
    requestKey.current ||= crypto.randomUUID();
    try {
      const saved = await api('/v1/benchmarks/parser', { method: 'POST',
        headers: { 'Idempotency-Key': requestKey.current }, body: JSON.stringify({ sample_count: 20 }) });
      setReport(saved);
      setRuns(await api('/v1/benchmarks'));
      requestKey.current = null;
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function openReport(id) {
    setBusy(true); setError('');
    try { setReport(await api(`/v1/benchmarks/${id}`)); }
    catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  return <div className="hardware-panel">
    {error && <div role="alert" className="alert">{error}</div>}
    <section className="panel" aria-labelledby="hardware-heading">
      <div className="panel-title"><h2 id="hardware-heading">This computer</h2>
        <button className="secondary" onClick={refresh} disabled={busy}>Refresh measurements</button></div>
      {!profile ? <p className="muted">{error ? 'Measurements unavailable. Refresh to retry.' : 'Reading local resource measurements…'}</p> : <>
        <p className="muted">Measured {new Date(profile.measured_at).toLocaleString()} · {profile.os.system} {profile.os.architecture}</p>
        <dl className="hardware-specs">
          <div><dt>Processor</dt><dd>{profile.cpu.model || 'Unknown'} · {profile.cpu.logical_cores ?? 'Unknown'} logical cores</dd></div>
          <div><dt>Memory</dt><dd>{bytes(profile.memory.total_bytes)} total · {bytes(profile.memory.effective_available_bytes)} available{profile.memory.reason && <small>{profile.memory.reason}</small>}</dd></div>
          <div><dt>Swap</dt><dd>{bytes(profile.memory.swap_free_bytes)} free / {bytes(profile.memory.swap_total_bytes)} total</dd></div>
          <div><dt>Storage</dt><dd>{bytes(profile.disk.free_bytes)} free on the data drive{profile.disk.reason && <small>{profile.disk.reason}</small>}</dd></div>
          <div><dt>Graphics</dt><dd>{profile.gpu.devices.length ? profile.gpu.devices.map((device, index) => <div key={index}>
            {device.driver || 'Unknown driver'} · PCI {device.vendor_id}:{device.device_id}<small>Dedicated VRAM: {bytes(device.vram_bytes)}. {device.vram_reason}</small></div>) : profile.gpu.reason}</dd></div>
        </dl>
        <div className="resource-note"><strong>CPU mode · One task at a time</strong><p>No model is selected. Cloud and remote execution are off. Hardware alone does not establish which models fit.</p>
          <p>Model benchmarks reserve 2 GiB and recheck available memory before each case. Runtime overhead can require more.</p></div>
      </>}
    </section>
    <ModelAdvisor api={api}/>
    <AIModelChoice api={api}/>
    <section className="panel benchmark-controls" aria-labelledby="benchmark-heading">
      <div><h2 id="benchmark-heading">Measure the research parser</h2><p className="muted">Run 20 rounds of five fictional cases. The report stays in this workspace.</p></div>
      <button className="primary" onClick={runBenchmark} disabled={busy}>{busy ? 'Working…' : 'Run parser benchmark'}</button>
    </section>
    {busy && <p className="working" role="status">Measuring or loading the report…</p>}
    {report && <BenchmarkReport report={report}/>}
    <section className="panel benchmark-history" aria-labelledby="benchmark-history-heading"><h2 id="benchmark-history-heading">Saved benchmarks</h2>
      {runs.length === 0 ? <p className="muted">No saved reports yet. Model benchmarks require an explicit model name and digest in the terminal.</p> : runs.map(run => <button className="benchmark-history-item" key={run.id} onClick={() => openReport(run.id)} disabled={busy}>
        <span>{run.kind === 'parser' ? 'Parser' : 'Local model'} · {run.passed_count}/{run.sample_count} passed · {run.status}</span><small>{new Date(run.created_at).toLocaleString()}</small></button>)}
    </section>
  </div>;
}
