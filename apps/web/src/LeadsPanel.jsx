import React, { useEffect, useState } from 'react';
import './LeadsPanel.css';

const defaults = { mode: 'live', q: '', identity: 'all', contact: 'all', analysis: 'all', fit: 'all', review: 'all' };
const words = value => value.replaceAll('_', ' ');
const date = value => value ? new Date(value).toLocaleString() : 'Not reviewed';
const filterOptions = {
  identity: ['Identity state', ['all', 'unresolved', 'source_attributed', 'disputed']],
  contact: ['Contact state', ['all', 'attributed', 'extracted', 'excluded', 'none']],
  analysis: ['Analysis state', ['all', 'not_reviewed', 'current', 'needs_review']],
  fit: ['Current fit judgement', ['all', 'unknown', 'review', 'possible_fit', 'not_a_fit']],
  review: ['Review state', ['all', 'needs_review', 'excluded', 'source_reviewed']],
};

function LeadCard({ lead, onOpenResearch }) {
  const visible = lead.contacts.filter(c => !c.excluded);
  const excluded = lead.contacts.filter(c => c.excluded);
  const contact = item => <li key={item.id} className={item.excluded ? 'lead-excluded' : ''}>
    <strong>{item.raw_value}</strong><span>{item.type} · {words(item.effective_state)} · Reachability unknown</span>
    {item.exclusion_reasons.map(reason => <small key={reason}>{reason}</small>)}
    <details><summary>Contact evidence and dates</summary>
      <small>Last checked {date(item.last_checked_at)} · Ownership review {date(item.attribution_reviewed_at)}</small>
      {item.evidence.map(evidence => <div key={evidence.id}><blockquote>{evidence.excerpt}</blockquote>
        <a href={evidence.source_url} target="_blank" rel="noreferrer">Source page ↗</a>
        <small>Retrieved {date(evidence.retrieved_at)} · Evidence {evidence.id}</small></div>)}
    </details>
  </li>;
  return <article className="panel lead-card" data-research-id={lead.id}>
    <div className="lead-card-heading"><div><p className="section-kicker">{lead.synthetic ? 'SYNTHETIC PROSPECT · FICTIONAL' : 'SAVED PROSPECT'}</p>
      <h2>{lead.business_name || lead.source_heading || 'Business name unknown'}</h2>
      {lead.branch && <p>Branch quoted by source: {lead.branch}</p>}
      <a href={lead.source_url} target="_blank" rel="noreferrer">{lead.source_url} ↗</a>
    </div><span className={`tag ${lead.review_state === 'excluded' ? 'disputed' : 'review'}`}>{words(lead.review_state)}</span></div>
    <div className="lead-states"><span>Identity: {words(lead.identity_status)}</span><span>Analysis: {words(lead.analysis_state)}</span>
      <span>Fit: {words(lead.effective_fit)} · Inference</span><span>Interest: unknown</span><span>Buyer budget: unknown</span></div>
    {lead.analysis_state === 'needs_review' && <p className="lead-stale">Analysis needs review. Saved fit: {words(lead.saved_fit)}; use the current review state.</p>}
    <div className="lead-card-grid"><section><h3>Public contacts · {visible.length} available for review</h3>
      {visible.length ? <ul className="lead-contacts">{visible.map(contact)}</ul> : <p className="muted">{excluded.length ? 'All saved contacts are excluded.' : 'No public contact was extracted.'}</p>}
      {excluded.length > 0 && <details className="lead-excluded-contacts"><summary>{excluded.length} excluded contact{excluded.length === 1 ? '' : 's'} · Audit only</summary><ul className="lead-contacts">{excluded.map(contact)}</ul></details>}
    </section><section className="lead-context"><h3>Offer and targeting</h3><p>{lead.product}</p><small>Target: {lead.target_geography} · Targeting input</small>
      <h3>Source location quote</h3><p>{lead.address || lead.service_area || 'Unknown — no source location reviewed'}</p>
      <h3>Need hypothesis · Inference</h3><p>{lead.need_hypothesis || 'Unknown — no need analysis reviewed'}</p>
      <small>Saved {date(lead.created_at)} · Analysis review {date(lead.analysis_reviewed_at)}</small>
    </section></div>
    {(lead.exclusion_reasons.length > 0 || lead.review_reasons.length > 0) && <details className="lead-reasons"><summary>Exclusions and outstanding checks</summary>
      <ul>{[...new Set([...lead.exclusion_reasons, ...lead.review_reasons])].map(reason => <li key={reason}>{reason}</li>)}</ul></details>}
    <div className="lead-card-footer"><p><strong>Next check:</strong> {lead.next_action}</p>
      <button type="button" className="secondary" onClick={() => onOpenResearch(lead.id)}>Open evidence and reviews</button></div>
  </article>;
}

export default function LeadsPanel({ api, active, onOpenResearch }) {
  const [draft, setDraft] = useState(defaults);
  const [filters, setFilters] = useState(defaults);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty = JSON.stringify(draft) !== JSON.stringify(filters);
  useEffect(() => {
    if (!active) return;
    let current = true;
    setBusy(true); setError(''); setNotice(''); setData(null);
    api(`/v1/leads?${new URLSearchParams({ ...filters, offset, limit: 20 })}`)
      .then(result => { if (current) setData(result); })
      .catch(error => { if (current) setError(error.message); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [api, active, filters, offset, refresh]);

  async function download(format) {
    setExporting(true); setError(''); setNotice('');
    try {
      const blob = await api(`/v1/leads/export?${new URLSearchParams({ ...filters, format })}`, { download: true });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `leaddesk-${filters.mode}-leads.${format}`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setNotice(`${format.toUpperCase()} download prepared from a fresh snapshot of the applied filters, across all result pages in the newest 200 records. Review labels and excluded contacts are retained.`);
    } catch (error) { setError(error.message); }
    finally { setExporting(false); }
  }

  return <div className="leads-panel">
    <section className="panel" aria-labelledby="leads-heading"><div className="panel-title"><h2 id="leads-heading">Saved prospects</h2>
      <button className="secondary" type="button" disabled={busy || exporting} onClick={() => setRefresh(n => n + 1)}>Refresh prospects</button></div>
      <p className="muted">Inspect contacts, source evidence and separate review states. Each card is a saved research record; repeated pages stay separate.</p>
      <form onSubmit={event => { event.preventDefault(); setFilters({ ...draft, q: draft.q.trim() }); setDraft({ ...draft, q: draft.q.trim() }); setOffset(0); }}>
        <div className="lead-search"><div><label htmlFor="lead-mode">Record source</label><select id="lead-mode" value={draft.mode} disabled={busy || exporting} onChange={e => setDraft({ ...draft, mode: e.target.value })}><option value="live">Real source records</option><option value="synthetic">Synthetic demos only</option></select></div>
          <div><label htmlFor="lead-search">Search saved prospects</label><input id="lead-search" type="search" maxLength={200} value={draft.q} placeholder="Name, branch, contact, offer or location" onChange={e => setDraft({ ...draft, q: e.target.value })}/></div></div>
        <div className="lead-filter-grid">{Object.entries(filterOptions).map(([field, [label, values]]) => <div key={field}><label htmlFor={`lead-${field}`}>{label}</label>
          <select id={`lead-${field}`} value={draft[field]} onChange={e => setDraft({ ...draft, [field]: e.target.value })}>{values.map(value => <option key={value} value={value}>{words(value)}</option>)}</select></div>)}</div>
        <div className="lead-actions"><button className="primary" disabled={busy || exporting} type="submit">Apply prospect filters</button>
          <button className="secondary" disabled={busy || exporting} type="button" onClick={() => { setDraft(defaults); setFilters(defaults); setOffset(0); setRefresh(n => n + 1); }}>Reset filters</button>
          {dirty && <small>Apply changed filters before downloading.</small>}</div>
      </form>
    </section>
    {error && <div role="alert" className="alert">{error}<button className="text-button" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Retry prospects</button></div>}
    {notice && <p role="status" className="notice">{notice}</p>}
    {busy && <p role="status" className="working">Loading saved prospects and current review states…</p>}
    {data && <>
      {filters.mode === 'synthetic' && <p className="demo-banner">SYNTHETIC DEMOS ONLY · All records and downloads in this view are fictional.</p>}
      <section className="panel lead-overview" aria-label="Prospect coverage and exports">
        <dl className="lead-counts"><div><dt>Matching records</dt><dd>{data.coverage.matched}</dd></div>
          <div><dt>Need review</dt><dd>{data.summary.needs_review || 0}</dd></div><div><dt>Excluded</dt><dd>{data.summary.excluded || 0}</dd></div>
          <div><dt>Source reviewed</dt><dd>{data.summary.source_reviewed || 0}</dd></div></dl>
        <p className={data.coverage.scan_limited ? 'lead-stale' : 'muted'}>Checked {data.coverage.scanned} of {data.coverage.total_in_mode} saved records in this mode. {data.coverage.scan_limited && 'Coverage is limited to the newest 200 records. Older records are outside these filters and downloads.'}</p>
        <p className="muted">{data.scope}</p>
        <div className="lead-actions"><button className="secondary" disabled={busy || exporting || dirty} onClick={() => download('json')}>Download prospects JSON</button>
          <button className="secondary" disabled={busy || exporting || dirty} onClick={() => download('csv')}>Download prospects CSV</button></div>
        <small>Downloads include all matching pages within this scope, source quotes, dates, corrections and up to 100 recent review revisions per record. CSV uses one row per contact; the first row per record carries its complete audit. Excluded values are retained for audit. JSON preserves exact values; CSV protects spreadsheet formula cells. Export record data is limited to 16 MiB; larger selections require narrower filters. Empty results produce an empty file with its schema.</small>
      </section>
      <div className="lead-results" aria-live="polite">
        {!data.items.length && <section className="panel lead-empty"><h2>No saved prospects match these filters.</h2><p>Research a website, choose synthetic demos, or adjust the review filters.</p></section>}
        {data.items.map(lead => <LeadCard key={lead.id} lead={lead} onOpenResearch={onOpenResearch}/>)}
      </div>
      <nav className="lead-pagination" aria-label="Prospect result pages"><button className="secondary" disabled={offset === 0 || busy || exporting} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous prospects</button>
        <span>{data.items.length ? `${offset + 1}–${offset + data.items.length}` : '0'} of {data.coverage.matched} matching records</span>
        <button className="secondary" disabled={data.next_offset === null || busy || exporting} onClick={() => setOffset(data.next_offset)}>Next prospects</button></nav>
    </>}
  </div>;
}
