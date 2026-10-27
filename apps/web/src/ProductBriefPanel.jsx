import React, { useEffect, useRef, useState } from 'react';
import './ProductBriefPanel.css';

const emptyOffer = { offer: '', target_geography: '', problem: '', capabilities: '', service_geography: '', exclusions: '', price: '' };
const lines = text => text.split('\n').map(value => value.trim()).filter(Boolean);

function offerPayload(form) {
  return { offer: form.offer.trim(), target_geography: form.target_geography.trim(), problem: form.problem.trim() || null,
    capabilities: lines(form.capabilities), service_geography: form.service_geography.trim() || null,
    exclusions: lines(form.exclusions), price: form.price.trim() || null };
}

function offerForm(inputs) {
  return { ...emptyOffer, ...Object.fromEntries(Object.entries(inputs).map(([name, value]) =>
    [name, Array.isArray(value) ? value.join('\n') : value || ''])) };
}

function OfferFields({ value, onChange, editing = false, disabled }) {
  const prefix = editing ? 'edit' : 'new';
  const label = editing ? 'Edit ' : '';
  const field = (name, title, limit, required = false) => <div>
    <label htmlFor={`${prefix}-${name}`}>{label}{title}</label>
    <input id={`${prefix}-${name}`} value={value[name]} onChange={event => onChange({ ...value, [name]: event.target.value })}
      maxLength={limit} minLength={required ? (name === 'offer' ? 3 : 2) : undefined} required={required} disabled={disabled}/>
  </div>;
  return <fieldset disabled={disabled} className="offer-fields">
    <legend className="sr-only">{editing ? 'Edit offer details' : 'New offer details'}</legend>
    <div className="form-grid">{field('offer', 'Offer or service', 1000, true)}{field('target_geography', 'Target geography', 200, true)}</div>
    <label htmlFor={`${prefix}-problem`}>{label}Problem you solve <span>Optional</span></label>
    <textarea id={`${prefix}-problem`} maxLength={600} rows={2} value={value.problem} onChange={event => onChange({ ...value, problem: event.target.value })}/>
    <details className="offer-options"><summary>Capabilities, service area, exclusions and price</summary>
      <label htmlFor={`${prefix}-capabilities`}>{label}Capabilities <span>One per line, up to six; 160 characters each</span></label>
      <textarea id={`${prefix}-capabilities`} maxLength={965} rows={3} value={value.capabilities} onChange={event => onChange({ ...value, capabilities: event.target.value })}/>
      <div className="form-grid">{field('service_geography', 'Service geography', 200)}{field('price', 'Your offer price', 120)}</div>
      <p className="muted">Your service area can differ from your target market. Your price is not a prospect’s budget.</p>
      <label htmlFor={`${prefix}-exclusions`}>{label}Exclusions <span>One per line, up to six; 160 characters each</span></label>
      <textarea id={`${prefix}-exclusions`} maxLength={965} rows={3} value={value.exclusions} onChange={event => onChange({ ...value, exclusions: event.target.value })}/>
    </details>
  </fieldset>;
}

export default function ProductBriefPanel({ api, onUseBrief }) {
  const [form, setForm] = useState(emptyOffer);
  const [recent, setRecent] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editForm, setEditForm] = useState(emptyOffer);
  const [hypotheses, setHypotheses] = useState([]);
  const [checks, setChecks] = useState('');
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const request = useRef(null);

  useEffect(() => {
    let active = true;
    api('/v1/briefs').then(result => { if (active) setRecent(result); })
      .catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [api]);

  function select(brief) {
    setSelected(brief);
    setEditForm(offerForm(brief.document.input));
    setHypotheses(brief.document.hypotheses.map(({ text, review }) => ({ text, review })));
    setChecks(brief.document.verification_checks.join('\n'));
  }

  function requestHeaders(signature) {
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    return { 'Idempotency-Key': request.current.key };
  }

  async function openBrief(id) {
    setBusy(true); setError(''); setNotice('');
    try {
      const [brief, revisions] = await Promise.all([api(`/v1/briefs/${id}`), api(`/v1/briefs/${id}/revisions`)]);
      select(brief); setHistory(revisions);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function createBrief(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    const payload = offerPayload(form);
    try {
      const brief = await api('/v1/briefs', { method: 'POST', headers: requestHeaders(`create:${JSON.stringify(payload)}`), body: JSON.stringify(payload) });
      select(brief); setHistory([brief]);
      setRecent(await api('/v1/briefs'));
      request.current = null;
      setNotice('Draft saved. Review its hypotheses and verification checks before using it.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  const edited = { input: offerPayload(editForm), hypotheses, verification_checks: lines(checks) };
  const dirty = selected && JSON.stringify(edited) !== JSON.stringify({ input: selected.document.input,
    hypotheses: selected.document.hypotheses.map(({ text, review }) => ({ text, review })),
    verification_checks: selected.document.verification_checks });

  async function saveEdits(event) {
    event.preventDefault();
    if (busy || !selected || !dirty) return;
    setBusy(true); setError(''); setNotice('');
    const payload = { expected_revision: selected.revision, ...edited };
    try {
      const brief = await api(`/v1/briefs/${selected.id}`, { method: 'PATCH',
        headers: requestHeaders(`edit:${selected.id}:${JSON.stringify(payload)}`), body: JSON.stringify(payload) });
      select(brief);
      const [list, revisions] = await Promise.all([api('/v1/briefs'), api(`/v1/briefs/${brief.id}/revisions`)]);
      setRecent(list); setHistory(revisions); request.current = null;
      setNotice(`Revision ${brief.revision} saved. Earlier research keeps its original brief.`);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  function changeHypothesis(index, change) {
    setHypotheses(values => values.map((item, position) => position === index ? { ...item, ...change } : item));
  }

  return <div className="brief-panel">
    {error && <div role="alert" className="alert">{error}</div>}
    {notice && <div role="status" className="notice">{notice}</div>}
    <section className="panel" aria-labelledby="create-brief-heading">
      <div className="panel-title"><h2 id="create-brief-heading">Create a product brief</h2><span className="tag">Your inputs · No model needed</span></div>
      <p className="muted">Describe any offer and market. The draft provides starting hypotheses and checks; it does not establish buyer need.</p>
      <form onSubmit={createBrief}>
        <OfferFields value={form} onChange={setForm} disabled={busy}/>
        <div className="form-footer"><p>Drafts and edits stay in this workspace.</p><button className="primary" type="submit" disabled={busy}>Create draft brief</button></div>
      </form>
    </section>
    <section className="panel" aria-labelledby="saved-briefs-heading"><h2 id="saved-briefs-heading">Saved product briefs</h2>
      {recent.length === 0 ? <p className="muted brief-empty">No briefs yet. Create one above.</p> : <div className="brief-list">{recent.map(brief => <button key={brief.id} className={selected?.id === brief.id ? 'brief-list-item active' : 'brief-list-item'} disabled={busy} onClick={() => openBrief(brief.id)}>
        <span>{brief.document.input.offer}</span><small>{brief.document.input.target_geography} · Revision {brief.revision}</small>
      </button>)}</div>}
    </section>
    {selected && <section className="panel brief-editor" aria-labelledby="edit-brief-heading">
      <div className="panel-title"><h2 id="edit-brief-heading">Review and edit your brief</h2><span className="tag">Revision {selected.revision}</span></div>
      <p className="muted">Hypotheses are planning assumptions. Keeping one does not confirm it about any prospect. Changing offer details resets kept hypotheses to unreviewed in the saved revision.</p>
      <form onSubmit={saveEdits}>
        <OfferFields value={editForm} onChange={setEditForm} editing disabled={busy}/>
        <h3 className="brief-section-heading">Buyer hypotheses</h3>
        {hypotheses.map((hypothesis, index) => <div className="brief-hypothesis" key={index}>
          <label htmlFor={`hypothesis-${index}`}>Hypothesis {index + 1}</label>
          <textarea id={`hypothesis-${index}`} required maxLength={1600} rows={3} value={hypothesis.text} disabled={busy} onChange={event => changeHypothesis(index, { text: event.target.value })}/>
          <div className="hypothesis-actions"><div><label htmlFor={`review-${index}`}>Review hypothesis {index + 1}</label>
            <select id={`review-${index}`} value={hypothesis.review} disabled={busy} onChange={event => changeHypothesis(index, { review: event.target.value })}>
              <option value="unreviewed">Unreviewed</option><option value="kept">Keep as hypothesis</option><option value="rejected">Reject hypothesis</option>
            </select></div><button type="button" className="text-button" disabled={busy || hypotheses.length === 1} onClick={() => setHypotheses(values => values.filter((_, position) => position !== index))}>Remove hypothesis {index + 1}</button></div>
        </div>)}
        <button type="button" className="secondary" disabled={busy || hypotheses.length >= 4} onClick={() => setHypotheses(values => [...values, { text: '', review: 'unreviewed' }])}>Add hypothesis</button>
        <label htmlFor="brief-checks">Verification checks <span>One per line, up to ten; 250 characters each</span></label>
        <textarea id="brief-checks" required maxLength={2509} rows={7} value={checks} disabled={busy} onChange={event => setChecks(event.target.value)}/>
        <div className="form-footer"><p>{dirty ? 'Unsaved changes. Save them before using this brief.' : 'Saved. Research will retain this exact revision.'}</p>
          <div className="brief-buttons"><button className="secondary" type="button" disabled={busy || !dirty} onClick={() => select(selected)}>Discard edits</button>
            <button className="primary" type="submit" disabled={busy || !dirty}>Save brief changes</button></div></div>
      </form>
      <div className="brief-use"><p className="muted">Use the saved offer, target location, hypotheses and checks for a supplied website. Discovery and automatic exclusion matching are future work.</p>
        <button className="primary" type="button" disabled={busy || dirty} onClick={() => onUseBrief(selected)}>Use this brief for research</button></div>
      <details className="brief-unknowns"><summary>What remains unknown</summary><dl>{Object.entries(selected.document.unknowns).map(([name, reason]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{reason}</dd></div>)}</dl></details>
      <details className="brief-revisions"><summary>Revision history ({history.length})</summary>{history.map(brief => <article key={brief.revision}>
        <strong>Revision {brief.revision} · {new Date(brief.updated_at).toLocaleString()}</strong>
        <p>{brief.document.input.offer} · {brief.document.input.target_geography}</p>
        <p className="muted">{brief.document.generation.method === 'local_model' ? 'Local model draft · Requires review' : brief.document.generation.method === 'user_edit' ? 'Edited by you' : 'Rules draft'}</p>
      </article>)}</details>
    </section>}
  </div>;
}
