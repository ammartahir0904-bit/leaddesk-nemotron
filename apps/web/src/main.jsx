import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import HardwarePanel from './HardwarePanel';
import ProductBriefPanel from './ProductBriefPanel';
import QueuePanel from './QueuePanel';
import AssessmentPanel from './AssessmentPanel';
import LeadsPanel from './LeadsPanel';
import QualityPanel from './QualityPanel';
import FilesPanel from './FilesPanel';
import VoicePanel from './VoicePanel';
import ScreenPanel from './ScreenPanel';
import LearningPanel from './LearningPanel';
import WorkersPanel from './WorkersPanel';
import CorrespondencePanel from './CorrespondencePanel';
import ProspectingPanel from './ProspectingPanel';
import '@fontsource-variable/inter';
import './style.css';

// Lead-finding essentials first; older experimental tools stay available under "More tools".
const MAIN_VIEWS = [['prospects', 'Find clients'], ['leads', 'Leads'], ['research', 'Website research'],
  ['correspondence', 'Email and calendar'], ['hardware', 'AI models and hardware']];
const MORE_VIEWS = [['files', 'Files and memory'], ['voice', 'Voice'], ['screen', 'Screen context'], ['briefs', 'Product briefs'],
  ['queue', 'Research queue'], ['quality', 'Quality baseline'], ['learning', 'Learning and datasets'], ['workers', 'PC workers']];

function App() {
  const [key, setKey] = useState(sessionStorage.getItem('leaddesk-key') || '');
  const [unlocked, setUnlocked] = useState(false);
  // Public demo: the server says so and shares its demo key (fictional data, network actions off).
  const [demo, setDemo] = useState(null);
  useEffect(() => { fetch('/v1/demo-info').then(r => r.json()).then(value => { if (value.demo) { setDemo(value); setKey(k => k || value.key); } }).catch(() => {}); }, []);
  const [view, setView] = useState('research');
  const [moreTools, setMoreTools] = useState(() => { try { return sessionStorage.getItem('leaddesk-more-tools') === '1'; } catch { return false; } });
  useEffect(() => { try { sessionStorage.setItem('leaddesk-more-tools', moreTools ? '1' : '0'); } catch { /* storage unavailable */ } }, [moreTools]);
  const [activeBrief, setActiveBrief] = useState(null);
  const [health, setHealth] = useState('Connecting');
  const [recent, setRecent] = useState([]);
  const [record, setRecord] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [showSuppressed, setShowSuppressed] = useState(false);
  const [report, setReport] = useState(null);
  const [category, setCategory] = useState('wrong_contact');
  const [comment, setComment] = useState('');
  const [expected, setExpected] = useState('');
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ url: '', product: '', location: '' });
  const dialog = useRef(null);
  const requestRef = useRef(null);

  const api = useCallback(async (path, options = {}) => {
    const { download, ...requestOptions } = options;
    const response = await fetch(path, { ...requestOptions, headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${key}`, ...options.headers } });
    if (response.ok && download) return response.blob();
    const body = await response.json();
    if (!response.ok) {
      if (response.status === 401) { setUnlocked(false); sessionStorage.removeItem('leaddesk-key'); }
      const message = body.message || (Array.isArray(body.detail) ? body.detail.map(x => `${x.loc.at(-1)}: ${x.msg}`).join('; ') : 'Request failed.');
      throw Object.assign(new Error(message), { retryable: !!body.retryable });
    }
    return body;
  }, [key]);
  const describeError = error => ({ message: error.message || 'Connection lost. Check that LeadDesk is running and retry.', retryable: error.retryable ?? true });

  async function unlock(event) {
    event?.preventDefault(); setError(null);
    try {
      const list = await api('/v1/research');
      sessionStorage.setItem('leaddesk-key', key); setRecent(list); setUnlocked(true); setView(current => current === 'research' ? 'prospects' : current);
    } catch (e) { setError(describeError(e)); }
  }
  useEffect(() => {
    fetch('/v1/health').then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(() => setHealth('Local workspace online')).catch(() => setHealth('Backend unavailable'));
    if (key) unlock();
  }, []);
  useEffect(() => {
    if (report && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [report]);

  async function research(demo = false) {
    if (busy) return;
    setBusy(true); setError(null); setNotice('');
    const payload = activeBrief ? { url: form.url, brief_id: activeBrief.id, brief_revision: activeBrief.revision } : form;
    const demoPayload = activeBrief ? { brief_id: activeBrief.id, brief_revision: activeBrief.revision } : {};
    const requestSignature = JSON.stringify({ payload, demo });
    if (requestRef.current?.signature !== requestSignature) requestRef.current = { signature: requestSignature, key: crypto.randomUUID() };
    try {
      const result = await api(demo ? '/v1/demo' : '/v1/research', { method: 'POST',
        headers: { 'Idempotency-Key': requestRef.current.key }, body: JSON.stringify(demo ? demoPayload : payload) });
      setRecord(result); setShowSuppressed(false);
      setRecent(await api('/v1/research'));
      requestRef.current = null;
    } catch (e) { setError({ ...describeError(e), retry: () => research(demo) }); }
    finally { setBusy(false); }
  }
  async function openRecord(id) {
    setView('research');
    setError(null); setNotice(''); setBusy(true);
    try { setRecord(await api(`/v1/research/${id}`)); setShowSuppressed(false); setRecent(await api('/v1/research')); }
    catch (e) { setError(describeError(e)); }
    finally { setBusy(false); }
  }
  async function saveReport(event) {
    event.preventDefault(); setSaving(true); setError(null);
    try {
      const result = await api('/v1/feedback', { method: 'POST', body: JSON.stringify({ contact_id: report.id,
        category, comment, expected_value: expected.trim() || null }) });
      setRecord(result); setNotice('Correction saved. This contact is suppressed across research on this website.');
      dialog.current.close(); setReport(null);
    } catch (e) { setError(describeError(e)); }
    finally { setSaving(false); }
  }
  const suppressed = record?.contacts.filter(c => c.suppressed || c.review_blocked).length || 0;
  const contacts = record?.contacts.filter(c => showSuppressed || (!c.suppressed && !c.review_blocked)) || [];
  const hasIdentityExclusions = record?.contacts.some(c => c.review_blocked);
  const page = {
    prospects: { title: 'Find businesses that could buy from you.', description: 'Describe what you sell and where. Get businesses ranked by how much they need it, with phones, emails, website problems and evidence.', label: 'Find clients' },
    research: { title: 'Start with the evidence.', description: 'Turn a public website into a contact record you can inspect and correct.', label: 'Research' },
    briefs: { title: 'Define what you offer.', description: 'Keep your offer, targeting assumptions and verification checks together.', label: 'Product briefs' },
    queue: { title: 'Research at your pace.', description: 'Set a source and budget, inspect progress, and pause or resume saved work.', label: 'Research queue' },
    leads: { title: 'Review your saved prospects.', description: 'Inspect contacts, evidence and offer fit, with unknowns kept visible.', label: 'Leads' },
    quality: { title: 'Measure what the sources support.', description: 'Audit frozen research samples and see quality gaps by offer and location.', label: 'Quality' },
    learning: { title: 'Review what should teach the system.', description: 'Prepare reviewed datasets and compare supplied candidate outputs with traceable local reports.', label: 'Learning' },
    files: { title: 'Find your files. Keep useful context.', description: 'Search folders you approve and manage your own scoped notes.', label: 'Files and memory' },
    voice: { title: 'Speak, review, then act.', description: 'Use local dictation or type a command, review its scope, and choose when to run it.', label: 'Voice' },
    screen: { title: 'Bring a window into context.', description: 'Capture a temporary still, review the relevant text, and choose a local action.', label: 'Screen context' },
    workers: { title: 'Connect a computer you control.', description: 'Pair an optional PC worker and queue synthetic benchmarks.', label: 'PC workers' },
    correspondence: { title: 'Write, review, then export.', description: 'Prepare local email drafts and calendar planning files.', label: 'Email and calendar' },
    hardware: { title: 'Choose the right AI models.', description: 'See what this computer can run, which local models to install, and keep benchmark reports.', label: 'AI models and hardware' },
  }[view];

  function useBrief(brief) {
    setActiveBrief(brief);
    setForm(values => ({ ...values, product: brief.document.input.offer, location: brief.document.input.target_geography }));
    setView('research'); setError(null);
    setNotice(`Using product brief revision ${brief.revision}. Hypotheses still require evidence.`);
  }

  return <div className="workspace">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="LeadDesk home"><span className="brand-mark">L<span>·</span></span>LeadDesk</a>
      <p className="sidebar-caption">YOUR RESEARCH WORKSPACE</p>
      <nav className="workspace-nav" aria-label="Workspace panels">
        {[...MAIN_VIEWS, ...(moreTools || MORE_VIEWS.some(([id]) => id === view) ? MORE_VIEWS : [])].map(([id, label]) =>
          <button key={id} className={`nav-item ${view === id ? 'selected' : ''}`} aria-current={view === id ? 'page' : undefined}
            onClick={() => setView(id)} disabled={(id !== 'research' && !unlocked) || busy}>{label}</button>)}
        <button className="nav-more" onClick={() => setMoreTools(value => !value)} aria-expanded={moreTools}>{moreTools ? 'Fewer tools' : 'More tools'}</button>
      </nav>
      <div className="recent-heading">RECENT RESEARCH <span>{recent.length}</span></div>
      <nav aria-label="Saved research" className="recent-list">
        {recent.length === 0 && <p className="sidebar-empty">Your saved research will appear here.</p>}
        {recent.map(r => <button key={r.id} disabled={busy} className={record?.id === r.id ? 'recent active' : 'recent'} onClick={() => openRecord(r.id)}>
          <span>{r.synthetic ? 'Demo · ' : ''}{r.canonical_name || new URL(r.source_url).hostname}</span><small>{r.geography}</small>
        </button>)}
      </nav>
      <div className="local-note"><span className="status-dot"/>LOCAL FIRST<p>Your records stay on this laptop.<br/>No cloud model connected.</p></div>
    </aside>
    <main>
      <header className="topbar"><span>Personal workspace <span className="slash">/</span> {page.label}</span><span className="connection"><span className="status-dot"/>{health}</span></header>
      <div className="content">
        <div className="page-heading"><div><p className="eyebrow">LOCAL RESEARCH WORKSPACE</p><h1>{page.title}</h1>
          <p className="intro">{page.description}</p></div><span className="private-label">◈ Private workspace</span></div>
        {error && <div role="alert" className="alert"><strong>{error.message}</strong>{error.retryable && error.retry && <button className="text-button" disabled={busy} onClick={error.retry}>Retry request</button>}</div>}
        {notice && <div role="status" className="notice">{notice}</div>}
        {!unlocked ? <section className="panel unlock"><div className="section-kicker">WELCOME TO LEADDESK</div><h2>Unlock your local workspace</h2>
          {demo ? <p className="notice"><strong>Public demo.</strong> Every business, website and contact here is made up (reserved .example addresses and
            phone numbers reserved for fiction). The demo key is filled in for you. Searching the map and the web, reading websites and file tools
            are switched off here; you can review contacts, correct results, approve messages and reword a message with NVIDIA Nemotron on Nebius Token Factory.</p>
            : <p>Paste the access key printed by your launcher. The key stays in this browser tab’s session.</p>}
          <form onSubmit={unlock}><label htmlFor="key">Local access key</label><input id="key" type={demo ? 'text' : 'password'} autoComplete="off" required minLength={32} value={key} onChange={e => setKey(e.target.value)} />
            <button className="primary" type="submit">Unlock workspace <span>→</span></button></form></section> : <>
        <div hidden={view !== 'prospects'}><ProspectingPanel api={api} active={view === 'prospects'} onOpenResearch={openRecord}/></div>
        {view === 'hardware' && <HardwarePanel api={api}/>}
        {view === 'workers' && <WorkersPanel api={api}/>}
        {view === 'correspondence' && <CorrespondencePanel api={api} onOpenResearch={openRecord}/>}
        {view === 'learning' && <LearningPanel api={api} onOpenResearch={openRecord} onOpenQuality={() => setView('quality')}/>}
        <div hidden={view !== 'leads'}><LeadsPanel api={api} active={view === 'leads'} onOpenResearch={openRecord}/></div>
        <div hidden={view !== 'quality'}><QualityPanel api={api} active={view === 'quality'} onOpenResearch={openRecord}/></div>
        <div hidden={view !== 'files'}><FilesPanel api={api} active={view === 'files'}/></div>
        <div hidden={view !== 'voice'}><VoicePanel api={api} active={view === 'voice'} onOpenFiles={() => setView('files')}/></div>
        <div hidden={view !== 'screen'}><ScreenPanel api={api} active={view === 'screen'} onOpenFiles={() => setView('files')}/></div>
        <div hidden={view !== 'briefs'}><ProductBriefPanel api={api} onUseBrief={useBrief}/></div>
        <div hidden={view !== 'queue'}><QueuePanel api={api} active={view === 'queue'} onOpenResearch={openRecord} onCreateBrief={() => setView('briefs')}/></div>
        <div hidden={view !== 'research'}>
        <section className="panel research-panel" aria-labelledby="research-heading">
          <div className="panel-title"><div><span className="step">01</span><h2 id="research-heading">Research a website</h2></div><span className="tag">One page at a time</span></div>
          <form onSubmit={e => { e.preventDefault(); research(); }}>
            {activeBrief && <div className="active-brief"><strong>Using product brief · Revision {activeBrief.revision}</strong><p>Research saves this revision. Later edits do not change existing records.</p>
              <button className="text-button" type="button" disabled={busy} onClick={() => setActiveBrief(null)}>Use manual details instead</button></div>}
            <label htmlFor="url">Business website <span>Use a homepage or contact page</span></label>
            <input id="url" type="url" placeholder="https://business.com/contact" required maxLength={2048} value={form.url} disabled={busy} onChange={e => setForm({ ...form, url: e.target.value })}/>
            <div className="form-grid"><div><label htmlFor="product">What are you offering?</label><input id="product" placeholder="e.g. appointment booking software" required minLength={3} maxLength={2000} value={form.product} disabled={busy || !!activeBrief} onChange={e => setForm({ ...form, product: e.target.value })}/></div>
              <div><label htmlFor="location">Target location</label><input id="location" placeholder="e.g. Lahore, Pakistan" required minLength={2} maxLength={300} value={form.location} disabled={busy || !!activeBrief} onChange={e => setForm({ ...form, location: e.target.value })}/></div></div>
            <div className="form-footer"><p>Extracts public details. Ownership and product fit need review.</p><button className="primary" disabled={busy} type="submit">{busy ? 'Working…' : 'Research website'} <span>↗</span></button></div>
          </form>
        </section>
        {busy && <div className="working" role="status">Inspecting the page and saving source evidence…</div>}
        {!record ? <section className="empty-state"><div className="document-icon" aria-hidden="true">≡<span>✓</span></div><p className="eyebrow">A CLEAR SOURCE FOR EVERY DETAIL</p><h2>Your first research starts here.</h2><p>Add a website above, or explore a clearly labelled<br/>fictional example to see how evidence and corrections work.</p><button className="secondary" disabled={busy} onClick={() => research(true)}>Explore synthetic demo <span>→</span></button><small>No network request to a business. All demo details are invented.</small></section> : <>
        <section className="result-heading"><div><p className="eyebrow">RESEARCH RECORD</p><h2>{record.canonical_name || 'Business name unknown'}</h2><p><a href={record.source_url} target="_blank" rel="noreferrer">{record.source_url} ↗</a></p></div><span className="tag review">{record.identity_status === 'source_attributed' ? 'Source-attributed · Manual review' : record.identity_status === 'disputed' ? 'Identity disputed' : 'Identity needs review'}</span></section>
        {record.synthetic && <div className="demo-banner">SYNTHETIC DEMO · These details are fictional and must never be used as real leads.</div>}
        <div className="result-grid"><section className="panel contacts-panel"><div className="panel-title"><h2>Public contact details <span className="count">{record.contacts.length - suppressed}</span></h2><span className="tag">Source says</span></div>
          <p className="muted">Extracted from this page. Business, branch and contact ownership are unconfirmed.</p>
          {suppressed > 0 && <label className="check-label"><input type="checkbox" checked={showSuppressed} onChange={e => setShowSuppressed(e.target.checked)}/>Show {suppressed} {hasIdentityExclusions ? 'excluded' : 'suppressed'} contact{suppressed === 1 ? '' : 's'}</label>}
          {contacts.length === 0 && <p className="no-contacts">{suppressed ? 'All extracted contacts have been suppressed.' : 'No visible contacts found. Try a public contact page.'}</p>}
          {contacts.map(c => <article className={`contact ${c.suppressed || c.review_blocked ? 'suppressed' : ''}`} key={c.id}>
            <div className="contact-top"><span className="contact-kind">{c.type}</span><span className={c.suppressed || c.review_blocked ? 'state disputed' : 'state'}>{c.suppressed ? 'Disputed · suppressed' : c.review_blocked ? 'Identity disputed · Excluded' : c.attribution_state === 'attributed' ? 'Source-attributed · Reachability unknown' : 'Extracted · review needed'}</span></div>
            <p className="contact-value">{c.raw_value}</p>
            <div className="contact-actions"><span>{c.attribution_state === 'attributed' && !c.review_blocked ? 'Ownership reviewed from source; reachability unknown' : 'Ownership and reachability unknown'}</span>{!c.suppressed && <button className="text-button" onClick={() => { setReport(c); setCategory('wrong_contact'); setComment(''); setExpected(''); }}>Report wrong contact</button>}</div>
            <details><summary>View source evidence</summary>{c.evidence_ids.map(id => { const evidence = record.evidence.find(e => e.id === id); return evidence && <div className="evidence" key={id}><blockquote>{evidence.excerpt}</blockquote><a href={evidence.source_url} target="_blank" rel="noreferrer">Open source page ↗</a><small>Retrieved {new Date(evidence.retrieved_at).toLocaleString()}</small><small>Evidence ID: {id}</small><small className="hash">SHA-256: {evidence.content_hash}</small></div>; })}</details>
          </article>)}
        </section><aside className="record-context"><section className="panel"><div className="section-kicker">YOUR RESEARCH CONTEXT</div><h3>Offer</h3><p>{record.product}</p><h3>Target location</h3><p>{record.geography}</p><small>Targeting input; not a verified business address.</small>
          {record.product_brief && <details className="record-brief-details"><summary>Saved product brief · Revision {record.product_brief.revision}</summary>
            <p>Planning context; checks below are not automatically completed.</p>
            <h3>Buyer hypotheses</h3><ul>{record.product_brief.document.hypotheses.map((h, index) => <li key={index}>{h.text} ({h.review})</li>)}</ul>
            <h3>Verification checks</h3><ul>{record.product_brief.document.verification_checks.map((text, index) => <li key={index}>{text}</li>)}</ul>
            <h3>Exclusions</h3><p>{record.product_brief.document.input.exclusions.join('; ') || 'None supplied'}</p>
            <h3>Problem you solve</h3><p>{record.product_brief.document.input.problem || 'Unknown — not supplied'}</p>
            <h3>Capabilities</h3><p>{record.product_brief.document.input.capabilities.join('; ') || 'None supplied'}</p>
            <h3>Service geography</h3><p>{record.product_brief.document.input.service_geography || 'Unknown — not supplied'}</p>
            <h3>Your offer price</h3><p>{record.product_brief.document.input.price || 'Unknown — not supplied'}</p><small>Not evidence of a prospect’s budget.</small>
          </details>}
          <hr/><h3>What we checked</h3><p>{record.coverage}</p></section>
          <section className="panel unknowns"><div className="section-kicker">STILL UNKNOWN</div>{Object.entries(record.unknowns).map(([name, reason]) => <details key={name}><summary>{name.replaceAll('_', ' ')}</summary><p>{reason}</p></details>)}</section></aside></div>
        {record.claims.length > 0 && <section className="panel identity"><h2>Source identity</h2><p>The page heading is a candidate name. An agency, directory or shared branch page may describe a different business.</p>{record.claims.map(c => <details key={c.id}><summary>{c.value}</summary><blockquote>{record.evidence.find(e => e.id === c.evidence_id)?.excerpt}</blockquote><small>Source heading · evidence {c.evidence_id}</small></details>)}</section>}
        {record.feedback.length > 0 && <section className="panel history"><h2>Correction history</h2>{record.feedback.map(f => <div key={f.id}><strong>{f.category.replaceAll('_', ' ')}</strong><span>{new Date(f.created_at).toLocaleString()}</span>{f.comment && <p>{f.comment}</p>}{f.expected_value && <p>Suggested correction (unverified): {f.expected_value}</p>}</div>)}</section>}
        <AssessmentPanel key={record.id} record={record} api={api} onRecordChange={setRecord}/>
        </>}
        </div>
        <footer className="page-footer"><span>LeadDesk / Local research</span><span>Evidence before assumptions.</span><button className="text-button" onClick={() => { sessionStorage.removeItem('leaddesk-key'); setKey(''); setUnlocked(false); setView('research'); setActiveBrief(null); setRecord(null); setRecent([]); }}>Lock workspace</button></footer>
        </>}
      </div>
    </main>
    <dialog ref={dialog} onCancel={() => setReport(null)} onClose={() => setReport(null)} aria-labelledby="report-title">
      <form onSubmit={saveReport}><div className="section-kicker">CORRECT THE RECORD</div><h2 id="report-title">Report a contact</h2><p className="report-value">{report?.raw_value}</p><p>This contact will be suppressed on this website, including future research. Your correction is retained for review.</p>
        <label htmlFor="category">What went wrong?</label><select id="category" value={category} onChange={e => setCategory(e.target.value)}><option value="wrong_contact">Wrong contact</option><option value="wrong_business">Belongs to another business</option><option value="wrong_branch">Wrong branch</option><option value="stale">Out of date</option><option value="invalid">Invalid contact</option></select>
        <label htmlFor="expected">Correct value <span>Optional; saved as unverified</span></label><input id="expected" maxLength={300} value={expected} onChange={e => setExpected(e.target.value)}/>
        <label htmlFor="comment">Notes <span>Optional</span></label><textarea id="comment" rows={3} maxLength={2000} value={comment} onChange={e => setComment(e.target.value)}/>
        {error && <p role="alert" className="dialog-error">{error.message}</p>}
        <div className="dialog-actions"><button type="button" className="secondary" disabled={saving} onClick={() => { dialog.current.close(); setReport(null); }}>Cancel</button><button type="submit" className="primary" disabled={saving}>{saving ? 'Saving…' : 'Save correction & suppress'}</button></div>
      </form>
    </dialog>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
