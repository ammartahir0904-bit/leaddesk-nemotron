import React, { useEffect, useRef, useState } from 'react';
import IdentityReviewForm from './IdentityReviewForm';
import NeedAnalysisForm from './NeedAnalysisForm';
import './AssessmentPanel.css';

const emptyRelated = { records: [], scope: 'Comparisons have not loaded yet.' };

export default function AssessmentPanel({ record, api, onRecordChange }) {
  const [related, setRelated] = useState(emptyRelated);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const request = useRef(null);
  useEffect(() => {
    let active = true;
    Promise.all([api(`/v1/research/${record.id}/related`), api(`/v1/research/${record.id}/assessments/history`)])
      .then(([comparisons, revisions]) => { if (active) { setRelated(comparisons); setHistory(revisions); } })
      .catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [api, record]);

  async function save(kind, payload) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    const signature = JSON.stringify({ id: record.id, kind, payload });
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await api(`/v1/research/${record.id}/${kind === 'identity' ? 'identity-review' : 'need-analysis'}`, {
        method: 'POST', headers: { 'Idempotency-Key': request.current.key }, body: JSON.stringify(payload),
      });
      onRecordChange(result); request.current = null;
      setNotice(kind === 'identity' ? 'Identity review saved. Contact ownership remains separate from reachability.' : 'Analysis saved. Hypotheses, interest and budget retain their stated limits.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  async function reload() {
    setBusy(true); setError(''); setNotice('');
    try { onRecordChange(await api(`/v1/research/${record.id}`)); }
    catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  const assessment = record.assessment;
  return <div className="assessment-panel">
    <section className="panel assessment-summary" aria-labelledby="assessment-heading">
      <div className="panel-title"><h2 id="assessment-heading">Identity and need review</h2><button type="button" className="secondary" disabled={busy} onClick={reload}>Reload saved reviews · Discard edits</button></div>
      <div className="assessment-statuses"><span>Identity: {record.identity_status.replaceAll('_', ' ')}</span>
        <span>Analysis: {(assessment?.analysis_state || 'not_reviewed').replaceAll('_', ' ')}</span><span>Interest: unknown</span><span>Buyer budget: unknown</span></div>
      <p className="muted">Source quotes are separate from review judgements. No contact is corroborated, reachability-tested or approved for outreach here.</p>
      {assessment?.identity_blockers.length > 0 && <ul className="assessment-blocker">{assessment.identity_blockers.map(text => <li key={text}>{text}</li>)}</ul>}
      {assessment?.analysis_review_reasons.length > 0 && <div role="status" className="assessment-stale"><strong>Analysis needs review</strong><ul>{assessment.analysis_review_reasons.map(text => <li key={text}>{text}</li>)}</ul></div>}
      {assessment?.analysis && <div className="assessment-saved"><h3>Saved fit judgement</h3><p>{assessment.analysis.document.fit.replaceAll('_', ' ')} · Reviewer inference{assessment.analysis_state === 'needs_review' ? ' · Needs fresh review' : ''}</p>
        <p>{assessment.analysis.document.need_hypothesis || 'No need hypothesis recorded.'}</p><small>{assessment.analysis.document.source_scope}</small></div>}
    </section>
    {error && <div role="alert" className="alert">{error}</div>}
    {notice && <div role="status" className="notice">{notice}</div>}
    <section className="panel"><IdentityReviewForm record={record} related={related} busy={busy} onSave={save}/></section>
    <section className="panel"><NeedAnalysisForm record={record} busy={busy} onSave={save}/></section>
    <section className="panel assessment-history"><details><summary>Assessment revision history ({history.length})</summary>
      {history.map(item => <article key={item.id}><strong>{item.kind === 'identity' ? 'Identity review' : 'Need analysis'} · Revision {item.revision}</strong>
        <small>{new Date(item.created_at).toLocaleString()} · Manual review</small>
        {item.kind === 'analysis' ? <p>{item.review.document.need_hypothesis || 'No need hypothesis'} · {item.review.document.fit.replaceAll('_', ' ')}</p> : <p>{item.review.document.business_name?.value || 'Name unknown'} · {item.review.document.decision.replaceAll('_', ' ')}</p>}
      </article>)}
    </details></section>
  </div>;
}
