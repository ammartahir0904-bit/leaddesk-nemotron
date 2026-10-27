import React, { useEffect, useRef, useState } from 'react';
import './LearningPanel.css';
import EvaluationPanel from './EvaluationPanel.jsx';

const emptyDraft = { reviewer: '', reason: '', input_text: '', observed_output: '', expected_output: '', evidence_ids: [],
  redaction_confirmed: false, permission_basis: '', business_group: '', use_scope: 'local_evaluation' };
const pageLabel = value => value ? `${value.offset + (value.items.length ? 1 : 0)}–${value.offset + value.items.length} of ${value.total}` : 'Loading…';

export default function LearningPanel({ api, onOpenResearch, onOpenQuality }) {
  const [mode, setMode] = useState('live');
  const [sources, setSources] = useState(null), [examples, setExamples] = useState(null), [versions, setVersions] = useState(null);
  const [sourceOffset, setSourceOffset] = useState(0), [exampleOffset, setExampleOffset] = useState(0), [versionOffset, setVersionOffset] = useState(0);
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false), [busy, setBusy] = useState(false);
  const [source, setSource] = useState(null), [draft, setDraft] = useState(emptyDraft), [selected, setSelected] = useState([]);
  const [name, setName] = useState(''), [purpose, setPurpose] = useState('evaluation'), [split, setSplit] = useState('development');
  const [version, setVersion] = useState(null), [deleting, setDeleting] = useState(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const request = useRef(null), pending = useRef(new AbortController());
  const disabled = busy || loading;

  useEffect(() => () => pending.current.abort(), []);
  useEffect(() => {
    let current = true; const controller = new AbortController();
    setLoading(true); setError('');
    const options = { signal: controller.signal };
    Promise.all([api(`/v1/learning/sources?mode=${mode}&offset=${sourceOffset}`, options),
      api(`/v1/learning/examples?mode=${mode}&offset=${exampleOffset}`, options), api(`/v1/learning/versions?offset=${versionOffset}`, options)])
      .then(([s, e, v]) => { if (current) { setSources(s); setExamples(e); setVersions(v); } })
      .catch(e => { if (current && e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [api, mode, sourceOffset, exampleOffset, versionOffset, refresh]);

  async function run(action) {
    if (disabled) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { if (e.name !== 'AbortError') setError(e.message); }
    finally { setBusy(false); }
  }
  async function write(path, payload) {
    const signature = JSON.stringify({ path, payload });
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    const result = await api(path, { method: 'POST', headers: { 'Idempotency-Key': request.current.key },
      body: JSON.stringify(payload), signal: pending.current.signal });
    request.current = null;
    return result;
  }
  function openSource(item) {
    setSource(item); setError(''); setNotice('');
    setDraft({ ...emptyDraft, input_text: item.evidence.map(e => e.excerpt).join('\n').slice(0, 2000), observed_output: item.observed_output.slice(0, 500),
      ...(item.example?.review || {}), redaction_confirmed: false, use_scope: item.held_out ? 'local_evaluation' : item.example?.review.use_scope || 'local_evaluation' });
  }
  function change(field, value) { setDraft(previous => ({ ...previous, [field]: value, ...(field !== 'redaction_confirmed' ? { redaction_confirmed: false } : {}) })); }
  async function saveReview(decision) {
    await run(async () => {
      const payload = { ...draft, source: source.ref, expected_source_hash: source.source_hash,
        expected_revision: source.example?.revision || 0, decision };
      if (decision === 'exclude') Object.assign(payload, { input_text: '', observed_output: '', expected_output: '', evidence_ids: [], permission_basis: '', redaction_confirmed: false });
      await write('/v1/learning/examples', payload);
      setSource(null); setDraft(emptyDraft); setSelected([]); setVersion(null); setRefresh(v => v + 1);
      setNotice(decision === 'include' ? 'Reviewed example saved. No training was run.' : 'Source excluded and copied dataset payloads invalidated.');
    });
  }
  function toggle(example) {
    if (selected.some(item => item.id === example.id)) setSelected(selected.filter(item => item.id !== example.id));
    else if (selected.length < 100) setSelected([...selected, { id: example.id, revision: example.revision }]);
    else setError('A dataset can contain at most 100 examples.');
  }
  async function createVersion(event) {
    event.preventDefault();
    await run(async () => {
      const result = await write('/v1/learning/versions', { name, purpose, split, mode, examples: selected });
      setVersion(result); setSelected([]); setRefresh(v => v + 1); setNotice('Dataset version frozen. No training or model change was performed.');
    });
  }
  async function remove() {
    await run(async () => {
      await api(`/v1/learning/${deleting.kind}/${deleting.id}`, { method: 'DELETE', signal: pending.current.signal });
      setDeleting(null); setVersion(null); setSource(null); setDraft(emptyDraft); setSelected([]); setRefresh(v => v + 1);
      setNotice('Learning material deleted. Original research and contact suppression are preserved.');
    });
  }
  async function download() {
    await run(async () => {
      const blob = await api(`/v1/learning/versions/${version.id}/export`, { download: true, signal: pending.current.signal });
      const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url;
      anchor.download = `leaddesk-dataset-${version.mode}-${version.id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice('Reviewed dataset download prepared. Manage any downloaded copies separately.');
    });
  }
  const readyReview = source && draft.reviewer.trim().length >= 2 && draft.reason.trim().length >= 3;
  return <div className="learning-panel">
    <section className="panel"><h2>Review before learning</h2>
      <p>Choose saved contact corrections or completed contact/factual quality audits. Review and redact each example, record source permission, then select its local use. Freeze datasets and compare supplied candidate outputs below.</p>
      <label htmlFor="learning-mode">Learning record source</label><select id="learning-mode" value={mode} disabled={disabled} onChange={e => {
        setMode(e.target.value); setSourceOffset(0); setExampleOffset(0); setSource(null); setDraft(emptyDraft); setSelected([]); setDeleting(null); setVersion(null);
      }}><option value="live">Real source records</option><option value="synthetic">Synthetic demos only</option></select>
      {mode === 'synthetic' && <p className="demo-banner">SYNTHETIC DATA · Fictional records cannot establish real accuracy or training benefit.</p>}
      <dl className="learning-counts"><div><dt>Available sources</dt><dd>{sources?.total ?? '—'}</dd></div>
        <div><dt>Included reviews</dt><dd>{sources?.review_counts.include ?? '—'}</dd></div><div><dt>Excluded reviews</dt><dd>{sources?.review_counts.exclude ?? '—'}</dd></div>
        <div><dt>Saved dataset versions</dt><dd>{versions?.total ?? '—'}</dd></div></dl>
      <div className="learning-actions"><button className="secondary" disabled={disabled} onClick={() => { setSource(null); setDraft(emptyDraft); setVersion(null); setSelected([]); setRefresh(v => v + 1); }}>Refresh learning data</button>
        <button className="text-button" disabled={busy} onClick={onOpenQuality}>Open quality audits</button></div>
    </section>
    {loading && <p role="status">Loading review sources and dataset versions…</p>}{busy && <p role="status">Saving or checking learning material…</p>}
    {error && <p role="alert" className="alert">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    {deleting && <section className="panel learning-confirm"><h2>Delete learning material?</h2>
      <p>{deleting.kind === 'examples' ? 'This removes the reviewed example and clears copied payloads in every affected dataset version. Those versions will no longer export.' : 'This removes the dataset version and its saved payloads. Its reviewed source examples remain available.'} Original research, feedback and suppression are retained. Downloaded copies must be managed separately.</p>
      <button className="primary" disabled={disabled} onClick={remove}>Confirm delete learning material</button><button className="secondary" disabled={busy} onClick={() => setDeleting(null)}>Keep learning material</button></section>}
    <section className="panel"><h2>Review queue</h2><p>{pageLabel(sources)}</p>
      {sources?.items.length === 0 && <p>No contact corrections or completed quality-unit audits in this source mode.</p>}
      {sources?.items.map(item => <article className="learning-card" key={item.key}><h3>{item.task.replaceAll('_', ' ')} · {item.source_verdict}</h3>
        <p>{item.source_origin}</p><p>{item.source_reason || 'No source comment.'}</p>
        <small>{item.example ? `Saved decision: ${item.example.decision}, revision ${item.example.revision}` : 'Awaiting dataset review'}{item.stale ? ' · Source changed/superseded' : ''}{item.held_out ? ' · Reserved for holdout evaluation' : ''}</small>
        <div className="learning-actions"><button className="secondary" disabled={disabled} onClick={() => openSource(item)}>Review source</button>
          <button className="text-button" disabled={busy} onClick={() => onOpenResearch(item.research_id)}>Inspect original research</button></div></article>)}
      <div className="learning-actions"><button className="secondary" disabled={disabled || !sourceOffset} onClick={() => setSourceOffset(Math.max(0, sourceOffset - 20))}>Previous learning sources</button>
        <button className="secondary" disabled={disabled || sources?.next_offset == null} onClick={() => setSourceOffset(sources.next_offset)}>Next learning sources</button></div>
    </section>
    {source && <section className="panel learning-review"><h2>Review dataset example</h2><p>Source: {source.source_origin} · {source.task.replaceAll('_', ' ')}. Only your edited fields and the displayed origin, evidence IDs/hashes and revision references enter a dataset.</p>
      {source.stale && <p role="alert">This source changed or was superseded. Refresh the original quality/feedback review before including it.</p>}
      {source.suggested_correction_unverified && <p>Suggested correction from feedback (unverified): {source.suggested_correction_unverified}</p>}
      <label htmlFor="learning-reviewer">Dataset reviewer</label><input id="learning-reviewer" maxLength={80} value={draft.reviewer} disabled={busy} onChange={e => change('reviewer', e.target.value)}/>
      <label htmlFor="learning-input">Redacted example input</label><textarea id="learning-input" maxLength={2000} value={draft.input_text} disabled={busy} onChange={e => change('input_text', e.target.value)}/>
      <label htmlFor="learning-observed">Reviewed observed output</label><textarea id="learning-observed" maxLength={500} value={draft.observed_output} disabled={busy} onChange={e => change('observed_output', e.target.value)}/>
      <label htmlFor="learning-expected">Human-reviewed expected output</label><textarea id="learning-expected" maxLength={1000} value={draft.expected_output} disabled={busy} onChange={e => change('expected_output', e.target.value)}/>
      <fieldset><legend>Supporting saved evidence</legend>{source.evidence.map(item => <label className="learning-check" key={item.id}><input type="checkbox" disabled={busy} checked={draft.evidence_ids.includes(item.id)} onChange={e => change('evidence_ids', e.target.checked ? [...draft.evidence_ids, item.id] : draft.evidence_ids.filter(id => id !== item.id))}/>
        <span>{item.excerpt}<small>{item.id} · {item.retrieved_at}</small></span></label>)}</fieldset>
      <label htmlFor="learning-reason">Reason for dataset decision</label><textarea id="learning-reason" maxLength={500} value={draft.reason} disabled={busy} onChange={e => change('reason', e.target.value)}/>
      <label htmlFor="learning-permission">Source permission basis</label><input id="learning-permission" maxLength={300} value={draft.permission_basis} disabled={busy} placeholder="Why you may use this material locally" onChange={e => change('permission_basis', e.target.value)}/>
      <label htmlFor="learning-group">Shared business group (optional)</label><input id="learning-group" maxLength={120} value={draft.business_group} disabled={busy} onChange={e => change('business_group', e.target.value)}/><p>Use the same group for the same business across different domains, or copied sources that need to stay together.</p>
      <label htmlFor="learning-use">Permitted local use</label><select id="learning-use" disabled={busy} value={draft.use_scope} onChange={e => change('use_scope', e.target.value)}><option value="local_evaluation">Local evaluation only</option><option value="local_training" disabled={source.held_out}>Local training and evaluation</option></select>
      <label className="learning-check"><input type="checkbox" checked={draft.redaction_confirmed} disabled={busy} onChange={e => change('redaction_confirmed', e.target.checked)}/><span>I reviewed the fields and removed secrets and private material that must not enter this dataset.</span></label>
      <div className="learning-actions"><button className="primary" disabled={disabled || !readyReview || source.stale || !draft.redaction_confirmed || !draft.permission_basis.trim() || !draft.input_text.trim() || !draft.observed_output.trim() || !draft.expected_output.trim() || !draft.evidence_ids.length} onClick={() => saveReview('include')}>Include reviewed example</button>
        <button className="secondary" disabled={disabled || !readyReview} onClick={() => saveReview('exclude')}>Exclude source from datasets</button>
        <button className="text-button" disabled={busy} onClick={() => { setSource(null); setDraft(emptyDraft); }}>Discard dataset review edits</button></div>
    </section>}
    <section className="panel"><h2>Build a dataset version</h2><p>Select up to 100 current included examples. Development and holdout groups cannot overlap. Every selected revision is frozen; later edits, exclusion or deletion invalidate affected versions.</p><p>Reviewed examples: {pageLabel(examples)}</p>
      {examples?.items.map(item => <article className="learning-card" key={item.id}><label className="learning-check"><input type="checkbox" disabled={disabled || !item.current || item.decision !== 'include'} checked={selected.some(value => value.id === item.id)} onChange={() => toggle(item)}/>
        <span>{item.review.expected_output || item.review.reason}<small>{item.decision} · Revision {item.revision} · {item.review.use_scope.replaceAll('_', ' ')}{!item.current ? ' · Needs source review' : ''}{item.held_out ? ' · Holdout only' : ''}</small></span></label>
        <button className="text-button" disabled={disabled} onClick={() => setDeleting({ kind: 'examples', id: item.id })}>Delete reviewed example</button></article>)}
      <div className="learning-actions"><button className="secondary" disabled={disabled || !exampleOffset} onClick={() => setExampleOffset(Math.max(0, exampleOffset - 20))}>Previous reviewed examples</button>
        <button className="secondary" disabled={disabled || examples?.next_offset == null} onClick={() => setExampleOffset(examples.next_offset)}>Next reviewed examples</button></div>
      <p>{selected.length} examples selected across pages.</p><form onSubmit={createVersion}>
        <label htmlFor="learning-name">Dataset version name</label><input id="learning-name" minLength={3} maxLength={120} required disabled={busy} value={name} onChange={e => setName(e.target.value)}/>
        <label htmlFor="learning-purpose">Dataset purpose</label><select id="learning-purpose" disabled={busy} value={purpose} onChange={e => { setPurpose(e.target.value); if (e.target.value === 'training') setSplit('development'); }}><option value="evaluation">Local evaluation</option><option value="training">Prepare for local training</option></select>
        <label htmlFor="learning-split">Dataset split</label><select id="learning-split" disabled={busy || purpose === 'training'} value={split} onChange={e => setSplit(e.target.value)}><option value="development">Development</option><option value="holdout">Holdout · Reserve from tuning</option></select>
        <button className="primary" disabled={disabled || !selected.length || name.trim().length < 3} type="submit">Freeze dataset version</button></form>
    </section>
    <section className="panel"><h2>Dataset versions</h2><p>{pageLabel(versions)} · Versions include their source mode and permitted purpose. Training has not run.</p>
      {versions?.items.map(item => <article className="learning-card" key={item.id}><h3>{item.name}</h3><p>{item.mode} · {item.purpose} · {item.split} · {item.sample_count} examples · {item.status}</p>
        <div className="learning-actions"><button className="secondary" disabled={disabled} onClick={() => run(async () => setVersion(await api(`/v1/learning/versions/${item.id}`, { signal: pending.current.signal })))}>Inspect dataset version</button>
          <button className="text-button" disabled={disabled} onClick={() => setDeleting({ kind: 'versions', id: item.id })}>Delete dataset version</button></div></article>)}
      <div className="learning-actions"><button className="secondary" disabled={disabled || !versionOffset} onClick={() => setVersionOffset(Math.max(0, versionOffset - 20))}>Previous dataset versions</button>
        <button className="secondary" disabled={disabled || versions?.next_offset == null} onClick={() => setVersionOffset(versions.next_offset)}>Next dataset versions</button></div>
      {version && <section className="learning-version"><h3>Dataset manifest: {version.name}</h3><p>{version.status} · {version.mode} · {version.purpose} · {version.split}</p><p>Dataset SHA-256: {version.dataset_sha256}</p>
        <p>{version.status === 'ready' ? 'This version can be exported after a fresh source and permission check.' : 'This version is invalidated. Its copied example payloads have been cleared; create a new version from current reviews.'}</p>
        {version.examples.map(item => <details key={item.id}><summary>Revision {item.revision} · {item.provenance.task} · {item.provenance.source_origin}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details>)}
        <button className="primary" disabled={disabled || version.status !== 'ready'} onClick={download}>Export reviewed dataset</button></section>}
    </section>
    <EvaluationPanel key={mode} api={api} dataset={version} mode={mode} revision={refresh}/>
  </div>;
}
