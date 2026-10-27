import React, { useEffect, useRef, useState } from 'react';
import './CorrespondencePanel.css';

const emptyEmail = () => ({ kind: 'email', research_id: '', contact_id: '', sender: '', subject: '', body: '' });
const emptyCalendar = synthetic => ({ kind: 'calendar', title: '', description: '', location: '', organizer_timezone: 'Asia/Karachi',
  counterpart_timezone: 'Europe/London', start_local: '', duration_minutes: 30, fold: null, synthetic });

export default function CorrespondencePanel({ api, onOpenResearch }) {
  const [mode, setMode] = useState('live'), [offset, setOffset] = useState(0), [sourceOffset, setSourceOffset] = useState(0);
  const [listing, setListing] = useState(null), [sources, setSources] = useState(null);
  const [selected, setSelected] = useState(null), [document, setDocument] = useState(emptyEmail);
  const [reviewer, setReviewer] = useState(''), [note, setNote] = useState(''), [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null), [notice, setNotice] = useState('');
  const receipt = useRef(null), generation = useRef(0);
  const dirty = !selected || JSON.stringify(document) !== JSON.stringify(selected.document);
  const disabled = busy || loading;

  async function loadLists() {
    const revision = ++generation.current;
    const [drafts, candidates] = await Promise.all([
      api(`/v1/correspondence/drafts?mode=${mode}&offset=${offset}`),
      api(`/v1/correspondence/sources?mode=${mode}&offset=${sourceOffset}`),
    ]);
    if (revision === generation.current) { setListing(drafts); setSources(candidates); }
  }
  useEffect(() => {
    let current = true;
    setLoading(true); setError(null);
    loadLists().catch(e => { if (current) setError({ message: e.message, retry: loadLists }); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; generation.current++; };
  }, [api, mode, offset, sourceOffset]);

  function resetReview() { setConfirmed(false); setDeleting(false); setError(null); }
  function change(field, value) { setDocument(previous => ({ ...previous, [field]: value })); resetReview(); setNotice(''); }
  function open(value) { setSelected(value); setDocument(value.document); resetReview(); setNotice(''); }
  function fresh(kind) { receipt.current = null; setSelected(null); setDocument(kind === 'email' ? emptyEmail() : emptyCalendar(mode === 'synthetic')); resetReview(); setError(null); setNotice(''); }
  async function run(action) {
    if (disabled) return;
    setBusy(true); setError(null);
    try { await action(); await loadLists(); }
    catch (e) { setError({ message: e.message || 'Connection lost. Check the local server and retry.', retry: action }); }
    finally { setBusy(false); }
  }
  function mutation(path, method, payload) {
    const signature = JSON.stringify({ path, method, payload });
    if (receipt.current?.signature !== signature) receipt.current = { signature, key: crypto.randomUUID() };
    const key = receipt.current.key;
    return async () => api(path, { method, headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload) });
  }
  function save(event) {
    event.preventDefault();
    const action = selected ? mutation(`/v1/correspondence/drafts/${selected.id}`, 'PATCH', { expected_revision: selected.revision, document })
      : mutation('/v1/correspondence/drafts', 'POST', document);
    run(async () => { const result = await action(); open(result); setNotice('Local draft saved. Review this revision before exporting.'); });
  }
  function approve(event) {
    event.preventDefault();
    const action = mutation(`/v1/correspondence/drafts/${selected.id}/review`, 'POST', {
      expected_revision: selected.revision, context_hash: selected.context_hash, reviewer, note, confirmed,
    });
    run(async () => { setSelected(await action()); setConfirmed(false); setNotice('This revision is approved for local file export only.'); });
  }
  async function download() {
    if (!selected || dirty) return;
    const { id, revision, context_hash, kind } = selected;
    const blob = await api(`/v1/correspondence/drafts/${id}/export?${new URLSearchParams({ revision, context_hash })}`, { download: true });
    const url = URL.createObjectURL(blob), link = window.document.createElement('a');
    link.href = url; link.download = `leaddesk-${id}.${kind === 'email' ? 'eml' : 'ics'}`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Local file downloaded. Sending, importing and downloaded-copy deletion are managed in your chosen client.');
  }
  const currentSource = sources?.items.find(s => s.id === document.research_id);
  const emails = currentSource?.emails || (selected?.kind === 'email' && document.research_id === selected.document.research_id ? [{ id: selected.document.contact_id, normalised_value: selected.context.recipient || 'Missing source contact' }] : []);
  const context = selected?.context;

  return <div className="correspondence-panel">
    {error && <div role="alert" className="alert"><p>{error.message}</p><button className="secondary" disabled={disabled} onClick={() => run(error.retry)}>Retry draft request</button></div>}
    {notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel"><h2>Local email and calendar drafts</h2><p>Write and review a file to use in your own email or calendar client. No account is connected. An export does not send email, invite anyone, check availability or confirm a meeting.</p><p>Save before leaving or refreshing this panel. Unsaved edits are temporary.</p>
      <label htmlFor="correspondence-mode">Draft source mode</label><select id="correspondence-mode" value={mode} disabled={disabled} onChange={e => {
        receipt.current = null; setMode(e.target.value); setOffset(0); setSourceOffset(0); setSelected(null); setDocument(emptyEmail()); resetReview();
      }}><option value="live">Real sources and personal planning</option><option value="synthetic">Synthetic demos only</option></select>
      <div className="correspondence-actions"><button className="secondary" disabled={disabled} onClick={() => fresh('email')}>New email draft</button>
        <button className="secondary" disabled={disabled} onClick={() => fresh('calendar')}>New calendar draft</button>
        <button className="secondary" disabled={disabled} onClick={() => run(async () => { if (selected) open(await api(`/v1/correspondence/drafts/${selected.id}`)); })}>Refresh drafts and review</button></div>
    </section>
    <section className="panel"><h2>{selected ? `Edit ${document.kind} draft · Revision ${selected.revision}` : `New ${document.kind} draft`}</h2>
      <form onSubmit={save}>
        {document.kind === 'email' ? <>
          <label htmlFor="email-source">Source research</label><select id="email-source" required disabled={disabled} value={document.research_id} onChange={e => {
            const source = sources.items.find(s => s.id === e.target.value);
            setDocument(previous => ({ ...previous, research_id: e.target.value, contact_id: source?.emails[0]?.id || '' })); resetReview();
          }}><option value="">Choose a saved email source</option>
            {selected?.kind === 'email' && !currentSource && <option value={selected.document.research_id}>{selected.context.source_name || 'Saved draft source'}</option>}
            {sources?.items.map(source => <option key={source.id} value={source.id}>{source.name || source.source_url}</option>)}
          </select>
          <div className="correspondence-actions"><button type="button" className="text-button" disabled={disabled || !sourceOffset} onClick={() => setSourceOffset(Math.max(0, sourceOffset - 20))}>Previous email sources</button>
            <button type="button" className="text-button" disabled={disabled || sources?.next_offset == null} onClick={() => setSourceOffset(sources.next_offset)}>Next email sources</button>
            {document.research_id && <button type="button" className="text-button" disabled={disabled} onClick={() => onOpenResearch(document.research_id)}>Open source evidence and reviews</button>}</div>
          <label htmlFor="email-contact">Source email contact</label><select id="email-contact" required disabled={disabled} value={document.contact_id} onChange={e => change('contact_id', e.target.value)}>
            <option value="">Choose an email contact</option>{emails.map(email => <option key={email.id} value={email.id}>{email.normalised_value}{email.suppressed ? ' · suppressed' : email.attribution_state === 'extracted' ? ' · attribution needs review' : ''}</option>)}
          </select><p>Contact ownership must have a current source review before export. Suppression or a source change can block an existing approval. Reachability and interest remain unconfirmed.</p>
          <label htmlFor="email-sender">Your sender email</label><input id="email-sender" type="email" maxLength={254} required value={document.sender} disabled={disabled} onChange={e => change('sender', e.target.value)}/>
          <label htmlFor="email-subject">Email subject</label><input id="email-subject" maxLength={200} required value={document.subject} disabled={disabled} onChange={e => change('subject', e.target.value)}/>
          <label htmlFor="email-body">Email body</label><textarea id="email-body" maxLength={4000} required rows={7} value={document.body} disabled={disabled} onChange={e => change('body', e.target.value)}/>
        </> : <>
          <p>{document.synthetic ? 'Fictional calendar demo. Exported title will be labelled.' : 'Personal calendar planning draft.'} No agreement or availability is recorded.</p>
          <label htmlFor="calendar-title">Calendar title</label><input id="calendar-title" maxLength={200} required value={document.title} disabled={disabled} onChange={e => change('title', e.target.value)}/>
          <label htmlFor="calendar-description">Calendar description</label><textarea id="calendar-description" maxLength={4000} rows={5} value={document.description} disabled={disabled} onChange={e => change('description', e.target.value)}/>
          <label htmlFor="calendar-location">Location or meeting details</label><input id="calendar-location" maxLength={300} value={document.location} disabled={disabled} onChange={e => change('location', e.target.value)}/>
          <label htmlFor="organizer-zone">Your IANA timezone</label><input id="organizer-zone" list="correspondence-zones" maxLength={80} required value={document.organizer_timezone} disabled={disabled} onChange={e => change('organizer_timezone', e.target.value)}/>
          <label htmlFor="counterpart-zone">Other party’s IANA timezone</label><input id="counterpart-zone" list="correspondence-zones" maxLength={80} required value={document.counterpart_timezone} disabled={disabled} onChange={e => change('counterpart_timezone', e.target.value)}/>
          <datalist id="correspondence-zones">{['Asia/Karachi', 'Europe/London', 'America/New_York', 'Asia/Dubai', 'UTC'].map(zone => <option key={zone} value={zone}/>)}</datalist>
          <label htmlFor="calendar-start">Start in your timezone</label><input id="calendar-start" type="datetime-local" required min="2000-01-01T00:00" max="2100-12-31T23:59" value={document.start_local} disabled={disabled} onChange={e => { setDocument(previous => ({ ...previous, start_local: e.target.value, fold: null })); resetReview(); }}/>
          <label htmlFor="calendar-duration">Duration in minutes</label><input id="calendar-duration" type="number" min="5" max="480" required value={document.duration_minutes} disabled={disabled} onChange={e => change('duration_minutes', Number(e.target.value))}/>
          <label htmlFor="calendar-fold">If this local time occurs twice</label><select id="calendar-fold" value={document.fold == null ? '' : String(document.fold)} disabled={disabled} onChange={e => change('fold', e.target.value === '' ? null : Number(e.target.value))}>
            <option value="">Ask me when ambiguous</option><option value="0">Earlier occurrence</option><option value="1">Later occurrence</option></select>
        </>}
        <button className="primary" disabled={disabled || !dirty}>Save local draft</button>
      </form>
    </section>
    {selected && <section className="panel correspondence-preview"><h2>Review the saved file</h2><p>{selected.synthetic ? 'SYNTHETIC DEMO · ' : ''}Revision {selected.revision} · {selected.review_state.replaceAll('_', ' ')} · Local file only</p>
      {dirty && <p role="status">You have unsaved edits. Save them before reviewing or downloading.</p>}
      {context.blockers.map((blocker, index) => <p role="alert" key={index}>{blocker}</p>)}
      {selected.kind === 'email' ? <><dl><dt>From</dt><dd>{selected.document.sender}</dd><dt>To</dt><dd>{context.recipient || 'Missing source email'}</dd><dt>Subject</dt><dd>{context.subject}</dd></dl>
        <pre>{selected.document.body}</pre><details><summary>Source evidence and current review</summary><p>{context.source_name} · {context.source_url}</p><p>Identity: {context.identity_status} · Contact: {context.contact_state}</p>
          {context.source_evidence?.map(e => <blockquote key={e.id}>{e.excerpt}<small>{e.retrieved_at}</small></blockquote>)}</details></> : <>
        <h3>{context.title || selected.document.title}</h3><pre>{selected.document.description}</pre><p>{selected.document.location}</p>
        <dl><dt>Your time · {selected.document.organizer_timezone}</dt><dd>{context.organizer_start} → {context.organizer_end}</dd>
          <dt>Other party · {selected.document.counterpart_timezone}</dt><dd>{context.counterpart_start} → {context.counterpart_end}</dd>
          <dt>UTC</dt><dd>{context.start_utc} → {context.end_utc}</dd></dl>
        <p>The file is a tentative personal planning event. It contains no attendees or invitation request and reserves no time here.</p>
      </>}
      <p>Your words remain user-authored text. Check any factual claims and sharing permission before export.</p>
      <form onSubmit={approve}><label htmlFor="draft-reviewer">File reviewer</label><input id="draft-reviewer" required maxLength={80} value={reviewer} disabled={disabled} onChange={e => { setReviewer(e.target.value); setConfirmed(false); setError(null); }}/>
        <label htmlFor="draft-review-note">Review note</label><input id="draft-review-note" required maxLength={400} value={note} disabled={disabled} onChange={e => { setNote(e.target.value); setConfirmed(false); setError(null); }}/>
        <label className="correspondence-check"><input type="checkbox" checked={confirmed} disabled={disabled || dirty} onChange={e => { setConfirmed(e.target.checked); setError(null); }}/><span>I reviewed this saved recipient or time, text and sharing scope for local file export.</span></label>
        <button className="primary" disabled={disabled || dirty || !confirmed || !reviewer.trim() || !note.trim() || context.blockers.length > 0}>Approve this file revision</button></form>
      {selected.reviewer && <p>Last file review: {selected.reviewer} · {selected.reviewed_at} · {selected.review_note}</p>}
      <button className="secondary" disabled={disabled || dirty || !selected.can_export} onClick={() => run(download)}>Download {selected.kind === 'email' ? 'email draft (.eml)' : 'calendar file (.ics)'}</button>
    </section>}
    <section className="panel"><h2>Saved local drafts</h2><p>{listing?.total ?? 0} drafts in this mode · Page {Math.floor(offset / 20) + 1}</p>
      {listing?.items.map(item => <article className="correspondence-card" key={item.id}><h3>{item.title}</h3><p>{item.kind} · Revision {item.revision} · {item.review_state.replaceAll('_', ' ')}</p>
        <button className="secondary" disabled={disabled} onClick={() => run(async () => open(await api(`/v1/correspondence/drafts/${item.id}`)))}>Open local draft</button>
        <button className="text-button" disabled={disabled} onClick={() => run(async () => { open(await api(`/v1/correspondence/drafts/${item.id}`)); setDeleting(true); })}>Delete local draft</button></article>)}
      <div className="correspondence-actions"><button className="secondary" disabled={disabled || !offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous drafts</button>
        <button className="secondary" disabled={disabled || listing?.next_offset == null} onClick={() => setOffset(listing.next_offset)}>Next drafts</button></div>
    </section>
    {deleting && selected && <section className="panel"><h2>Delete this local draft?</h2><p>This removes its text and file approval. Original source research and contact corrections stay. Downloaded copies must be deleted separately.</p>
      <button className="primary" disabled={disabled} onClick={() => { const id = selected.id; run(async () => { await api(`/v1/correspondence/drafts/${id}`, { method: 'DELETE' }); fresh(document.kind); setNotice('Local draft deleted. Original research is preserved.'); }); }}>Confirm delete local draft</button>
      <button className="secondary" disabled={disabled} onClick={() => setDeleting(false)}>Keep local draft</button></section>}
  </div>;
}
