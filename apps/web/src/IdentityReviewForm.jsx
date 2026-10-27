import React, { useEffect, useState } from 'react';
import { emptyQuote, EvidencePicker, QuoteField, quoteInput } from './AssessmentFields';

function initialReview(record) {
  const saved = record.assessment?.identity?.document;
  return {
    decision: saved?.decision || 'unresolved', source_role: saved?.source_role || 'unknown',
    business_name: saved?.business_name || emptyQuote(), branch: saved?.branch || emptyQuote(),
    address: saved?.address || emptyQuote(), service_area: saved?.service_area || emptyQuote(),
    geography: saved?.geography || 'unknown', exclusions: saved?.exclusions || 'not_checked',
    exclusion_reason: saved?.exclusion_reason || '', notes: saved?.notes || '',
    contact_reviews: record.contacts.map(contact => {
      const previous = saved?.contact_reviews.find(item => item.contact_id === contact.id);
      return { contact_id: contact.id, decision: contact.suppressed ? 'unreviewed' : previous?.decision || 'unreviewed',
        evidence_ids: previous?.evidence_ids || contact.evidence_ids };
    }),
    comparisons: saved?.comparisons || [],
  };
}

export default function IdentityReviewForm({ record, related, busy, onSave }) {
  const [form, setForm] = useState(() => initialReview(record));
  useEffect(() => { setForm(initialReview(record)); }, [record]);
  const change = (field, value) => setForm(current => ({ ...current, [field]: value }));
  function changeDecision(decision) {
    setForm(current => ({ ...current, decision, contact_reviews: current.contact_reviews.map(item =>
      decision === 'source_attributed' ? item : { ...item, decision: 'unreviewed' }) }));
  }
  function changeRole(source_role) {
    setForm(current => {
      const attributionAllowed = ['business', 'shared_brand'].includes(source_role);
      return { ...current, source_role,
        decision: !attributionAllowed && current.decision === 'source_attributed' ? 'unresolved' : current.decision,
        contact_reviews: current.contact_reviews.map(item => attributionAllowed ? item : { ...item, decision: 'unreviewed' }) };
    });
  }
  function comparisonFor(other, current = form) {
    return current.comparisons.find(item => item.research_id === other.id) || {
      research_id: other.id, decision: 'unresolved', local_evidence_ids: [], other_evidence_ids: [], reason: '',
    };
  }
  function updateComparison(other, change) {
    setForm(current => ({ ...current, comparisons: [...current.comparisons.filter(item => item.research_id !== other.id),
      { ...comparisonFor(other, current), ...change }] }));
  }
  function submit(event) {
    event.preventDefault();
    const quotes = Object.fromEntries(['business_name', 'branch', 'address', 'service_area'].map(field => [field, quoteInput(form[field])]));
    onSave('identity', { expected_revision: record.assessment?.identity?.revision || 0, ...form, ...quotes });
  }
  return <form onSubmit={submit} className="identity-review-form">
    <div className="panel-title"><h2>Business and branch review</h2><span className="tag">Revision {record.assessment?.identity?.revision || 0}</span></div>
    <p className="muted">Review the source as a person. Source attribution does not establish official ownership, independent corroboration or reachability.</p>
    <div className="form-grid"><div><label htmlFor="identity-decision">Identity decision</label>
      <select id="identity-decision" value={form.decision} disabled={busy} onChange={event => changeDecision(event.target.value)}>
        <option value="unresolved">Unresolved</option><option value="source_attributed">Source-attributed by review</option><option value="disputed">Disputed identity · Exclude this record’s contacts</option>
      </select></div><div><label htmlFor="identity-role">What kind of page is this?</label>
      <select id="identity-role" value={form.source_role} disabled={busy} onChange={event => changeRole(event.target.value)}>
        <option value="unknown">Unknown</option><option value="business">Business page</option><option value="shared_brand">Shared brand / franchise page</option><option value="directory">Directory / association</option><option value="agency">Agency / operator page</option>
      </select></div></div>
    <QuoteField id="identity-name" label="Business name" value={form.business_name} onChange={value => change('business_name', value)} evidence={record.evidence} disabled={busy}/>
    <QuoteField id="identity-branch" label="Branch" value={form.branch} onChange={value => change('branch', value)} evidence={record.evidence} disabled={busy}/>
    <details className="assessment-details"><summary>Address, service area and targeting review</summary>
      <QuoteField id="identity-address" label="Address or location" value={form.address} onChange={value => change('address', value)} evidence={record.evidence} disabled={busy}/>
      <QuoteField id="identity-service" label="Service area" value={form.service_area} onChange={value => change('service_area', value)} evidence={record.evidence} disabled={busy}/>
      <div className="form-grid"><div><label htmlFor="identity-geography">Geography judgement</label><select id="identity-geography" value={form.geography} disabled={busy} onChange={event => change('geography', event.target.value)}>
        <option value="unknown">Unknown</option><option value="matches">Source supports target geography</option><option value="outside_target">Outside target geography</option>
      </select></div><div><label htmlFor="identity-exclusions">Offer exclusions</label><select id="identity-exclusions" value={form.exclusions} disabled={busy} onChange={event => change('exclusions', event.target.value)}>
        <option value="not_checked">Not checked</option><option value="clear">Reviewed · None apply</option><option value="excluded">Reviewed · Excluded</option>
      </select></div></div>
      <label htmlFor="identity-exclusion-reason">Reason for exclusion judgement</label><textarea id="identity-exclusion-reason" rows={2} maxLength={400} value={form.exclusion_reason} disabled={busy} onChange={event => change('exclusion_reason', event.target.value)}/>
    </details>
    <details className="assessment-details"><summary>Contact attribution ({record.contacts.length})</summary>
      <p className="muted">Attribute each contact separately. A branch-specific attribution needs that branch named in the contact’s own excerpt. Use Report wrong contact to suppress a disputed value.</p>
      {record.contacts.map((contact, index) => <div className="contact-review" key={contact.id}><strong>{contact.raw_value}</strong>
        <label htmlFor={`contact-review-${index}`}>Attribution for {contact.raw_value}</label>
        <select id={`contact-review-${index}`} value={form.contact_reviews[index]?.decision || 'unreviewed'} disabled={busy || contact.suppressed}
          onChange={event => change('contact_reviews', form.contact_reviews.map(item => item.contact_id === contact.id ? { ...item, decision: event.target.value } : item))}>
          <option value="unreviewed">Unreviewed / ownership unknown</option><option value="attributed">Source-attributed to this business/branch</option>
        </select>
        {contact.suppressed && <p className="assessment-blocker">Suppressed contact; this review cannot restore it.</p>}
        <EvidencePicker id={`contact-review-evidence-${index}`} label={`Contact evidence ${index + 1}`} evidence={record.evidence}
          values={form.contact_reviews[index]?.evidence_ids || []} disabled={busy || contact.suppressed}
          onChange={evidence_ids => change('contact_reviews', form.contact_reviews.map(item => item.contact_id === contact.id ? { ...item, evidence_ids } : item))}/>
      </div>)}
    </details>
    <details className="assessment-details"><summary>Compare related records ({related.records.length})</summary>
      <p className="muted">{related.scope} Comparison decisions are reviewer judgements. Records and contacts remain separate.</p>
      {!related.records.length && <p className="muted">No related source pages found within this local comparison scope.</p>}
      {related.records.map((other, index) => { const review = comparisonFor(other); return <article className="comparison-review" key={other.id}>
        <h3>{other.name || 'Unnamed source'}</h3><p><a href={other.source_url} target="_blank" rel="noreferrer">{other.source_url} ↗</a></p>
        <p className="muted">{other.reasons.join(' · ')}{other.requires_comparison ? ' · Resolve before attribution' : ' · Comparison hint'}</p>
        <label htmlFor={`comparison-${index}`}>Comparison decision {index + 1}</label><select id={`comparison-${index}`} value={review.decision} disabled={busy} onChange={event => updateComparison(other, { decision: event.target.value })}>
          <option value="unresolved">Unresolved</option><option value="different_business">Different business</option><option value="different_branch">Same business, different branch</option><option value="same_business_branch">Same business and branch · Keep records separate</option>
        </select>
        <EvidencePicker id={`comparison-local-${index}`} label={`This record evidence ${index + 1}`} evidence={record.evidence} values={review.local_evidence_ids} disabled={busy} onChange={local_evidence_ids => updateComparison(other, { local_evidence_ids })}/>
        <EvidencePicker id={`comparison-other-${index}`} label={`Other record evidence ${index + 1}`} evidence={other.evidence} values={review.other_evidence_ids} disabled={busy} onChange={other_evidence_ids => updateComparison(other, { other_evidence_ids })}/>
        <label htmlFor={`comparison-reason-${index}`}>Comparison reason {index + 1}</label><textarea id={`comparison-reason-${index}`} maxLength={400} rows={2} value={review.reason} disabled={busy} onChange={event => updateComparison(other, { reason: event.target.value })}/>
      </article>; })}
    </details>
    <label htmlFor="identity-notes">Identity review notes <span>Judgements, not additional source facts</span></label><textarea id="identity-notes" maxLength={500} rows={2} value={form.notes} disabled={busy} onChange={event => change('notes', event.target.value)}/>
    <button className="primary assessment-save" type="submit" disabled={busy}>Save identity review</button>
  </form>;
}
