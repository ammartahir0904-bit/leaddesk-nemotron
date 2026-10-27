import React, { useEffect, useRef, useState } from 'react';
import QualityAuditForm, { draftAudit } from './QualityAuditForm';
import QualityReport from './QualityReport';
import './QualityPanel.css';

export default function QualityPanel({ api, active, onOpenResearch }) {
  const [mode, setMode] = useState('live');
  const [name, setName] = useState('');
  const [split, setSplit] = useState('development');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [candidates, setCandidates] = useState(null);
  const [recent, setRecent] = useState({ items: [], total: 0, limit: 20 });
  const [selected, setSelected] = useState([]);
  const [baseline, setBaseline] = useState(null);
  const [caseId, setCaseId] = useState('');
  const [drafts, setDrafts] = useState({});
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const requestRef = useRef(null);
  const caseItem = baseline?.cases.find(item => item.research_id === caseId);
  const draft = caseItem ? drafts[caseId] || draftAudit(caseItem) : null;

  useEffect(() => {
    if (!active) return;
    let current = true;
    setLoading(true); setError(''); setCandidates(null);
    Promise.all([api(`/v1/leads?${new URLSearchParams({ mode, q: query, offset, limit: 20 })}`), api('/v1/quality/baselines')])
      .then(([list, saved]) => { if (current) { setCandidates(list); setRecent(saved); } })
      .catch(error => { if (current) setError(error.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [api, active, mode, query, offset, refresh]);

  async function write(path, payload) {
    const signature = JSON.stringify({ path, payload });
    if (requestRef.current?.signature !== signature) requestRef.current = { signature, key: crypto.randomUUID() };
    const result = await api(path, { method: 'POST', headers: { 'Idempotency-Key': requestRef.current.key }, body: JSON.stringify(payload) });
    requestRef.current = null;
    return result;
  }
  async function run(action) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); }
    catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  function showBaseline(result) {
    setBaseline(result); setCaseId(result.cases[0]?.research_id || ''); setDrafts({}); setHistory(null);
  }
  function toggle(lead) {
    if (selected.some(value => value.id === lead.id)) setSelected(selected.filter(value => value.id !== lead.id));
    else if (selected.length >= 100) setError('A baseline can contain at most 100 records.');
    else setSelected([...selected, { id: lead.id, name: lead.source_heading || lead.source_url }]);
  }
  async function create() {
    await run(async () => {
      const result = await write('/v1/quality/baselines', { name, mode, split, research_ids: selected.map(value => value.id) });
      showBaseline(result); setRefresh(value => value + 1);
      setNotice('Baseline captured. All quality judgements start unreviewed; no live records were changed.');
    });
  }
  async function save(payload) {
    const target = caseId;
    await run(async () => {
      const result = await write(`/v1/quality/baselines/${baseline.id}/cases/${target}/audit`, payload);
      setBaseline(result); setDrafts(values => Object.fromEntries(Object.entries(values).filter(([key]) => key !== target))); setHistory(null);
      setNotice('Quality audit saved as a new revision. Unknowns stay separate from pass/fail; live lead records remain unchanged.');
    });
  }
  async function download() {
    await run(async () => {
      const blob = await api(`/v1/quality/baselines/${baseline.id}/export`, { download: true });
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `leaddesk-quality-${baseline.mode}-${baseline.id}.json`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      setNotice('Quality report download prepared from saved audit revisions. Unsaved audit edits are not included.');
    });
  }

  return <div className="quality-panel">
    <section className="panel"><h2>Build a review baseline</h2><p className="muted">Freeze saved predictions before evaluating them. Choose one record per source URL, up to 100. Start with three unrelated offers, two geographies and 60 real reviewed prospects before broader quality claims.</p>
      <form onSubmit={event => { event.preventDefault(); create(); }}>
        <div className="quality-form-grid"><div><label htmlFor="quality-name">Baseline name</label><input id="quality-name" minLength={3} maxLength={120} required value={name} disabled={busy} onChange={e => setName(e.target.value)}/></div>
          <div><label htmlFor="quality-mode">Quality record source</label><select id="quality-mode" value={mode} disabled={busy || loading} onChange={e => { setMode(e.target.value); setSelected([]); setOffset(0); }}><option value="live">Real source records</option><option value="synthetic">Synthetic demos only</option></select></div>
          <div><label htmlFor="quality-split">Sample purpose</label><select id="quality-split" value={split} disabled={busy} onChange={e => setSplit(e.target.value)}><option value="development">Development review</option><option value="holdout">Holdout · Reserve from tuning</option></select></div></div>
        {mode === 'synthetic' && <p className="demo-banner">SYNTHETIC SELECTION · These samples never count towards the real review requirement.</p>}
        <label htmlFor="quality-search">Find saved records for review</label><input id="quality-search" type="search" maxLength={200} value={search} disabled={busy} onChange={e => setSearch(e.target.value)}/>
        <button className="secondary" type="button" disabled={busy || loading} onClick={() => { setQuery(search.trim()); setOffset(0); setRefresh(value => value + 1); }}>Find quality candidates</button>
        {loading && <p role="status">Loading saved review candidates…</p>}
        {candidates && <><p className="muted">Candidates cover {candidates.coverage.scanned} of {candidates.coverage.total_in_mode} records in this mode; only the newest 200 are searched.</p>
          {candidates.items.length === 0 && <p>No matching saved records. Research a website or choose synthetic demos first.</p>}
          <div className="quality-candidates">{candidates.items.map(lead => <label className="quality-candidate" key={lead.id}><input type="checkbox" checked={selected.some(value => value.id === lead.id)} disabled={busy} onChange={() => toggle(lead)}/>
            <span><strong>{lead.source_heading || 'Business name unknown'}</strong><small>{lead.product} · {lead.target_geography}</small><small>{lead.source_url}</small></span></label>)}</div>
          <div className="quality-actions"><button className="secondary" type="button" disabled={busy || loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous review candidates</button>
            <button className="secondary" type="button" disabled={busy || loading || candidates.next_offset === null} onClick={() => setOffset(candidates.next_offset)}>Next review candidates</button></div></>}
        <p>{selected.length} records selected. Selection persists across candidate pages; changing source mode clears it.</p>
        {selected.length > 0 && <details className="quality-method"><summary>Review selected records</summary>{selected.map(value => <p key={value.id}>{value.name} <button className="text-button" type="button" disabled={busy} onClick={() => setSelected(selected.filter(item => item.id !== value.id))}>Remove selected record</button></p>)}</details>}
        <button className="primary" type="submit" disabled={busy || loading || !candidates || selected.length === 0}>Capture quality baseline</button>
      </form>
    </section>
    {error && <div role="alert" className="alert">{error}<button className="text-button" disabled={busy || loading} onClick={() => setRefresh(value => value + 1)}>Retry quality lists</button></div>}
    {notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel"><div className="panel-title"><h2>Saved quality baselines</h2><button className="secondary" disabled={busy || loading} onClick={() => setRefresh(value => value + 1)}>Refresh baseline list</button></div>
      <p className="muted">Showing {recent.items.length} of {recent.total}; latest {recent.limit} baselines. Open a saved baseline to load its current audit revisions.</p>
      <div className="quality-baseline-list">{recent.items.map(item => <button type="button" className="secondary" key={item.id} disabled={busy} onClick={() => run(async () => showBaseline(await api(`/v1/quality/baselines/${item.id}`)))}>
        {item.name} · {item.mode === 'synthetic' ? 'Fictional' : 'Real sources'} · {item.sample_count} cases</button>)}</div></section>
    {baseline && <>
      <section className="panel"><h2>{baseline.name}</h2><div className="quality-actions"><button className="secondary" disabled={busy} onClick={download}>Download quality report JSON</button>
        <button className="secondary" disabled={busy} onClick={() => run(async () => showBaseline(await api(`/v1/quality/baselines/${baseline.id}`)))}>Reload baseline · Discard audit edits</button></div>
        <label htmlFor="quality-case">Case to audit</label><select id="quality-case" value={caseId} disabled={busy} onChange={e => { setCaseId(e.target.value); setHistory(null); }}>{baseline.cases.map(item => <option key={item.research_id} value={item.research_id}>{item.ordinal + 1}. {item.snapshot.lead.source_heading || 'Unknown name'} · Audit revision {item.audit?.revision || 0}</option>)}</select></section>
      <QualityReport baseline={baseline}/>
      {caseItem && <QualityAuditForm item={caseItem} draft={draft} busy={busy} history={history} onOpenResearch={onOpenResearch} onSave={save}
        onChange={value => setDrafts(values => ({ ...values, [caseId]: value }))}
        onHistory={() => run(async () => setHistory(await api(`/v1/quality/baselines/${baseline.id}/cases/${caseId}/history`)))}/>}
    </>}
  </div>;
}
