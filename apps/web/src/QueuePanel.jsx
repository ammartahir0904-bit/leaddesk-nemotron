import React, { useEffect, useRef, useState } from 'react';
import './QueuePanel.css';

const finished = new Set(['completed', 'partial', 'failed', 'cancelled']);
const statusText = status => status.replaceAll('_', ' ');

function JobDetail({ job, busy, onControl, onOpenResearch }) {
  const terminal = finished.has(job.status);
  return <section className="panel queue-detail" aria-labelledby="queue-detail-heading">
    <div className="panel-title"><h2 id="queue-detail-heading">Research job</h2><span className="tag queue-state" data-state={job.status}>{statusText(job.status)}</span></div>
    {job.input.synthetic && <div className="demo-banner">SYNTHETIC QUEUE DEMO · All websites and contacts are fictional. No business network requests.</div>}
    <p className="queue-offer">{job.product_brief.document.input.offer}</p>
    <p className="muted">{job.product_brief.document.input.target_geography} · Saved brief revision {job.product_brief.revision}</p>
    <dl className="queue-metrics"><div><dt>Page attempts</dt><dd>{job.page_attempts} / {job.input.page_budget}</dd></div>
      <div><dt>Active time</dt><dd>{job.active_seconds.toFixed(1)} / {job.input.time_budget_seconds} seconds</dd></div>
      <div><dt>Candidate limit</dt><dd>{job.input.candidate_limit}</dd></div></dl>
    {job.stop_reason && <p className="queue-reason">{job.stop_reason}</p>}
    {job.status === 'retry_wait' && <p className="queue-reason">Waiting until {new Date(job.next_attempt_at * 1000).toLocaleString()} before retrying.</p>}
    {job.pause_requested && job.status === 'running' && <p role="status" className="queue-reason">Pause requested. The current page may finish; no next page will start.</p>}
    {job.cancel_requested && job.status === 'running' && <p role="status" className="queue-reason">Cancellation requested. The current page may finish and its evidence will be retained.</p>}
    <div className="queue-actions">
      <button className="secondary" disabled={busy || terminal || job.pause_requested || job.cancel_requested} onClick={() => onControl('pause')}>Pause job</button>
      <button className="secondary" disabled={busy || terminal || !job.pause_requested || job.cancel_requested} onClick={() => onControl('resume')}>Resume job</button>
      <button className="secondary" disabled={busy || terminal || job.cancel_requested} onClick={() => onControl('cancel')}>Cancel job</button>
    </div>
    <h3 className="queue-section-heading">Source and candidate pages</h3>
    {job.steps.map(step => <article className="queue-step" key={step.ordinal}>
      <div className="queue-step-title"><strong>{step.kind === 'source' ? 'Supplied source page' : step.candidate.label || 'Candidate website'}</strong><span className="tag">{statusText(step.state)}</span></div>
      <p><a href={step.url} target="_blank" rel="noreferrer">{step.url} ↗</a></p>
      <p className="muted">{step.attempts} attempt{step.attempts === 1 ? '' : 's'} · {step.kind === 'source' ? 'Only outbound website links are used; directory contacts are excluded.' : 'Identity, branch and offer fit need review.'}</p>
      {step.error && <p className="queue-error">{step.error}</p>}
      {step.research_id && <button className="text-button" onClick={() => onOpenResearch(step.research_id)}>Open saved research</button>}
      {step.candidate && <details><summary>Discovery source evidence</summary><blockquote>{step.candidate.anchor_text}</blockquote>
        <p>Link in source: <span className="queue-hash">{step.candidate.source_href}</span></p>
        <p>Source page: <a className="queue-hash" href={step.candidate.source_url} target="_blank" rel="noreferrer">{step.candidate.source_url} ↗</a></p>
        <small>Retrieved {new Date(step.candidate.retrieved_at).toLocaleString()}</small>
        <small className="queue-hash">Source SHA-256: {step.candidate.source_sha256}</small>
      </details>}
    </article>)}
    <details className="queue-coverage" open><summary>Source coverage and gaps</summary><ul>{job.coverage_gaps.map(text => <li key={text}>{text}</li>)}</ul>
      {job.discovery && <p className="muted">Visible links: {job.discovery.counts.visible_links} · Same source host: {job.discovery.counts.same_host} · Duplicate: {job.discovery.counts.duplicate} · Invalid: {job.discovery.counts.invalid} · Beyond limit: {job.discovery.counts.over_limit}</p>}
    </details>
    <details className="queue-events"><summary>Activity history</summary><ol>{job.events.map(event => <li key={event.id}>
      <time>{new Date(event.created_at).toLocaleString()}</time><p>{event.message}</p>
    </li>)}</ol></details>
  </section>;
}

export default function QueuePanel({ api, active, onOpenResearch, onCreateBrief }) {
  const [briefs, setBriefs] = useState([]);
  const [briefId, setBriefId] = useState('');
  const [source, setSource] = useState('');
  const [pages, setPages] = useState(3);
  const [candidates, setCandidates] = useState(10);
  const [seconds, setSeconds] = useState(120);
  const [startPaused, setStartPaused] = useState(false);
  const [connector, setConnector] = useState(null);
  const [recent, setRecent] = useState([]);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const selectedId = useRef(null);
  const request = useRef(null);
  const generation = useRef(0);

  useEffect(() => {
    if (!active) return;
    let mounted = true;
    let timer;
    Promise.all([api('/v1/briefs'), api('/v1/discovery/connectors')]).then(([list, connectors]) => {
      if (!mounted) return;
      setBriefs(list); setConnector(connectors[0]);
      setBriefId(current => list.some(brief => brief.id === current) ? current : list[0]?.id || '');
    }).catch(error => { if (mounted) setError(error.message); });
    async function poll() {
      const id = selectedId.current;
      const epoch = generation.current;
      try {
        const [list, detail] = await Promise.all([api('/v1/jobs'), id ? api(`/v1/jobs/${id}`) : Promise.resolve(null)]);
        if (mounted && generation.current === epoch) {
          setPollError('');
          setRecent(list);
          if (detail && selectedId.current === id) setJob(detail);
        }
      } catch (error) { if (mounted) setPollError(error.message); }
      if (mounted) timer = setTimeout(poll, 1000);
    }
    poll();
    return () => { mounted = false; clearTimeout(timer); };
  }, [api, active]);

  async function openJob(id) {
    generation.current += 1;
    selectedId.current = id;
    setBusy(true); setError('');
    try { setJob(await api(`/v1/jobs/${id}`)); }
    catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function enqueue(synthetic) {
    const brief = briefs.find(item => item.id === briefId);
    if (!brief || busy) return;
    const payload = { brief_id: brief.id, brief_revision: brief.revision, synthetic,
      page_budget: Number(pages), candidate_limit: Number(candidates), time_budget_seconds: Number(seconds), start_paused: startPaused,
      ...(synthetic ? {} : { source_url: source.trim() }) };
    const signature = JSON.stringify(payload);
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    setBusy(true); setError(''); generation.current += 1;
    try {
      const saved = await api('/v1/jobs', { method: 'POST', headers: { 'Idempotency-Key': request.current.key }, body: signature });
      selectedId.current = saved.id; setJob(saved);
      setRecent(await api('/v1/jobs')); request.current = null;
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function control(action) {
    if (!job || busy) return;
    setBusy(true); setError(''); generation.current += 1;
    const signature = `control:${job.id}:${action}`;
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    try {
      setJob(await api(`/v1/jobs/${job.id}/control`, { method: 'POST',
        headers: { 'Idempotency-Key': request.current.key }, body: JSON.stringify({ action }) }));
      setRecent(await api('/v1/jobs')); request.current = null;
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  return <div className="queue-panel">
    {error && <div role="alert" className="alert">{error}</div>}
    {pollError && <div role="alert" className="alert">{pollError} Progress updates will retry automatically.</div>}
    <section className="panel" aria-labelledby="queue-new-heading">
      <div className="panel-title"><h2 id="queue-new-heading">Queue bounded research</h2><span className="tag">Public page links</span></div>
      <p className="muted">Supply a public directory or association page. Discover visible external links, then inspect candidate pages within your budget. No search account is connected. Jobs continue while the server runs, even if you switch panels or lock the browser workspace.</p>
      {briefs.length === 0 ? <p className="queue-empty">Create a product brief before queuing research. <button className="text-button" onClick={onCreateBrief}>Open product briefs</button></p> : <form onSubmit={event => { event.preventDefault(); enqueue(false); }}>
        <label htmlFor="queue-brief">Saved product brief</label><select id="queue-brief" value={briefId} onChange={event => setBriefId(event.target.value)} disabled={busy} required>
          {briefs.map(brief => <option key={brief.id} value={brief.id}>{brief.document.input.offer} · {brief.document.input.target_geography} · Revision {brief.revision}</option>)}
        </select>
        <label htmlFor="queue-source">Public source page</label><input id="queue-source" type="url" required maxLength={2048} placeholder="https://association.example/members" value={source} disabled={busy} onChange={event => setSource(event.target.value)}/>
        <div className="queue-budget-fields"><div><label htmlFor="queue-pages">Page attempt budget</label><input id="queue-pages" type="number" min={1} max={6} required value={pages} disabled={busy} onChange={event => setPages(event.target.value)}/></div>
          <div><label htmlFor="queue-candidates">Candidate limit</label><input id="queue-candidates" type="number" min={1} max={20} required value={candidates} disabled={busy} onChange={event => setCandidates(event.target.value)}/></div>
          <div><label htmlFor="queue-seconds">Active seconds</label><input id="queue-seconds" type="number" min={30} max={300} required value={seconds} disabled={busy} onChange={event => setSeconds(event.target.value)}/></div></div>
        <p className="muted queue-budget-note">The source page and retries consume page attempts. Robots/redirect requests also run inside each bounded page fetch. Pause and cancellation take effect between pages.</p>
        <label className="check-label"><input type="checkbox" checked={startPaused} disabled={busy} onChange={event => setStartPaused(event.target.checked)}/>Start paused</label>
        <div className="form-footer"><button className="secondary" type="button" disabled={busy} onClick={() => enqueue(true)}>Run synthetic queue demo</button>
          <button className="primary" type="submit" disabled={busy}>Queue research</button></div>
      </form>}
      {connector && <details className="queue-connector"><summary>Connector scope and limits</summary><p>{connector.access}</p><p>{connector.coverage}</p><p>{connector.cost}</p><p>{connector.freshness}</p></details>}
    </section>
    <section className="panel" aria-labelledby="queue-history-heading"><h2 id="queue-history-heading">Saved jobs</h2>
      {!recent.length ? <p className="queue-empty muted">No saved jobs yet.</p> : <div className="queue-list">{recent.map(item => <button className="queue-list-item" key={item.id} disabled={busy} onClick={() => openJob(item.id)}>
        <span>{item.input.synthetic ? 'Synthetic demo' : item.input.source_url} · {statusText(item.status)}</span><small>{new Date(item.created_at).toLocaleString()} · {item.page_attempts} page attempts</small>
      </button>)}</div>}
    </section>
    {job && <JobDetail job={job} busy={busy} onControl={control} onOpenResearch={onOpenResearch}/>}
  </div>;
}
