import React from 'react';
import { EvidencePicker } from './AssessmentFields';

const tags = ['positive_fit', 'no_need', 'existing_solution', 'closed_branch', 'copied_listing', 'same_name', 'wrong_phone', 'wrong_branch', 'directory_operator', 'missing_evidence', 'other'];
const emptyVerdict = () => ({ outcome: 'unknown', evidence_ids: [], reason: '' });

export function draftAudit(item) {
  const saved = item.audit?.document;
  const contacts = new Map(saved?.contacts.map(value => [value.target_id, value]) || []);
  const claims = new Map(saved?.claims.map(value => [value.target_id, value]) || []);
  return { expected_revision: item.audit?.revision || 0, reviewer: saved?.reviewer || '',
    identity: saved?.identity || emptyVerdict(), relevance: saved?.relevance || emptyVerdict(),
    contacts: item.snapshot.lead.contacts.map(c => contacts.get(c.id) || { target_id: c.id, ...emptyVerdict() }),
    claims: item.snapshot.units.map(unit => claims.get(unit.id) || { target_id: unit.id, ...emptyVerdict() }),
    issue_tags: saved?.issue_tags || [], notes: saved?.notes || '' };
}

function VerdictFields({ id, label, value, evidence, onChange, busy, disabled = false }) {
  return <div className="quality-verdict"><label htmlFor={`${id}-outcome`}>{label}</label>
    <select id={`${id}-outcome`} value={value.outcome} disabled={busy || disabled} onChange={e => onChange({ ...value, outcome: e.target.value })}>
      <option value="unknown">Unknown · Not established</option><option value="pass">Pass · Reviewer finds support</option><option value="fail">Fail · Reviewer finds an error</option></select>
    {disabled && <small>No source-attributed identity prediction was captured; this is an abstention.</small>}
    <EvidencePicker id={`${id}-evidence`} label={`${label} evidence · Up to 4`} evidence={evidence} values={value.evidence_ids} disabled={busy}
      onChange={evidence_ids => onChange({ ...value, evidence_ids })}/>
    <label htmlFor={`${id}-reason`}>{label} reason</label><textarea id={`${id}-reason`} rows={2} maxLength={400} value={value.reason} disabled={busy}
      required={value.outcome !== 'unknown'} onChange={e => onChange({ ...value, reason: e.target.value })}/>
  </div>;
}

export default function QualityAuditForm({ item, draft, onChange, busy, onSave, history, onHistory, onOpenResearch }) {
  const snapshot = item.snapshot;
  const evidence = [...new Map([snapshot.research, ...snapshot.comparison_sources].flatMap(source => source.evidence).map(e => [e.id, e])).values()];
  function unitChange(field, index, value) { onChange({ ...draft, [field]: draft[field].map((old, i) => i === index ? value : old) }); }
  return <section className="panel quality-audit" aria-labelledby="quality-audit-heading"><h2 id="quality-audit-heading">Audit the frozen case</h2>
    <p>{snapshot.lead.business_name || snapshot.lead.source_heading || 'Name unknown'} · {snapshot.lead.product} · {snapshot.lead.target_geography}</p>
    <small>Source: {snapshot.lead.source_url} · Captured review revision {item.audit?.revision || 0}</small>
    {item.source_changed_since_snapshot && <p className="quality-callout">The live record changed after capture. Audit this frozen case; its results do not describe the changed live record.</p>}
    <p className="muted">Review exact source excerpts before choosing pass or fail. Ownership is separate from publication; relevance is an inference, not buying intent. Unknown stays unknown. This audit does not correct the live record.</p>
    <button type="button" className="text-button" disabled={busy} onClick={() => onOpenResearch(item.research_id)}>Open live evidence and corrections</button>
    <details className="quality-method"><summary>All frozen source excerpts ({evidence.length})</summary>{evidence.map(value => <div key={value.id}><blockquote>{value.excerpt}</blockquote>
      <a href={value.source_url} target="_blank" rel="noreferrer">{value.source_url}</a><small>Retrieved {new Date(value.retrieved_at).toLocaleString()} · Evidence {value.id}</small></div>)}</details>
    <form onSubmit={event => { event.preventDefault(); onSave(draft); }}>
      <label htmlFor="quality-reviewer">Reviewer label</label><input id="quality-reviewer" required minLength={2} maxLength={80} value={draft.reviewer} disabled={busy} onChange={e => onChange({ ...draft, reviewer: e.target.value })}/>
      <VerdictFields id="quality-identity" label="Identity audit" value={draft.identity} evidence={evidence} busy={busy}
        disabled={snapshot.lead.identity_status !== 'source_attributed'} onChange={identity => onChange({ ...draft, identity })}/>
      <VerdictFields id="quality-relevance" label="Offer relevance audit" value={draft.relevance} evidence={evidence} busy={busy} onChange={relevance => onChange({ ...draft, relevance })}/>
      <h3>Contact ownership audits</h3>
      {snapshot.lead.contacts.length === 0 && <p className="muted">No contact predictions in this case.</p>}
      {snapshot.lead.contacts.map((contact, index) => <details className="quality-unit" key={contact.id}><summary>{contact.raw_value} · {contact.effective_state.replaceAll('_', ' ')}</summary>
        <p>{contact.effective_state === 'attributed' ? 'Included in attribution precision.' : 'No effective ownership claim; excluded from attribution precision.'} A pass must still cite this contact’s own excerpt.</p>
        <VerdictFields id={`quality-contact-${index}`} label={`Contact ${index + 1} ownership audit`} value={draft.contacts[index]} evidence={evidence} busy={busy} onChange={value => unitChange('contacts', index, value)}/></details>)}
      <h3>Factual support audits · Inferences excluded</h3>
      {snapshot.units.map((unit, index) => <details className="quality-unit" key={unit.id}><summary>{unit.label}: {unit.value}</summary>
        <VerdictFields id={`quality-claim-${index}`} label={`Factual unit ${index + 1} support`} value={draft.claims[index]} evidence={evidence} busy={busy} onChange={value => unitChange('claims', index, value)}/></details>)}
      <fieldset className="quality-tags"><legend>Reviewer scenario/error flags</legend>{tags.map(tag => <label className="check-label" key={tag}><input type="checkbox" disabled={busy} checked={draft.issue_tags.includes(tag)}
        onChange={e => onChange({ ...draft, issue_tags: e.target.checked ? [...draft.issue_tags, tag] : draft.issue_tags.filter(value => value !== tag) })}/>{tag.replaceAll('_', ' ')}</label>)}</fieldset>
      <label htmlFor="quality-audit-notes">Audit notes</label><textarea id="quality-audit-notes" rows={2} maxLength={500} disabled={busy} value={draft.notes} onChange={e => onChange({ ...draft, notes: e.target.value })}/>
      <button className="primary" disabled={busy} type="submit">Save quality audit</button>
    </form>
    <div className="quality-actions"><button className="secondary" disabled={busy} type="button" onClick={onHistory}>Load audit revision history</button></div>
    {history && <details className="quality-method" open><summary>Saved audit revisions ({history.items.length}{history.limited ? '+' : ''})</summary>
      {history.items.map(value => <p key={value.revision}>Revision {value.revision} · {value.document.reviewer} · {new Date(value.updated_at).toLocaleString()} · Relevance {value.document.relevance.outcome}</p>)}
      {history.limited && <p>Only the latest {history.limit} revisions are shown. Earlier revisions remain saved.</p>}</details>}
  </section>;
}
