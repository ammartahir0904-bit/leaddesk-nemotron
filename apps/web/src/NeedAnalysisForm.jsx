import React, { useEffect, useState } from 'react';
import { emptyQuote, EvidencePicker, QuoteField, quoteInput, textLines } from './AssessmentFields';

function initialAnalysis(record) {
  const saved = record.assessment?.analysis?.document;
  return { fit: saved?.fit || 'review', observations: saved?.observations.length ? saved.observations : [emptyQuote()],
    need_hypothesis: saved?.need_hypothesis || '', offer_relevance: saved?.offer_relevance || '',
    existing_solution_status: saved?.existing_solution_status || 'not_checked', existing_solutions: saved?.existing_solutions.length ? saved.existing_solutions : [emptyQuote()],
    checked_evidence_ids: saved?.checked_evidence_ids || [], replacement_reason: saved?.replacement_reason || '',
    alternative_explanations: (saved?.alternative_explanations || ['An existing solution may already meet this need.']).join('\n'),
    missing_checks: (saved?.missing_checks || ['Confirm need, current alternatives and interest through a documented interaction.']).join('\n') };
}

export default function NeedAnalysisForm({ record, busy, onSave }) {
  const [form, setForm] = useState(() => initialAnalysis(record));
  useEffect(() => { setForm(initialAnalysis(record)); }, [record]);
  const change = (field, value) => setForm(current => ({ ...current, [field]: value }));
  const changeQuote = (field, index, quote) => change(field, form[field].map((item, position) => position === index ? quote : item));
  function submit(event) {
    event.preventDefault();
    onSave('analysis', { ...form, expected_revision: record.assessment?.analysis?.revision || 0,
      observations: form.observations.map(quoteInput).filter(Boolean),
      existing_solutions: form.existing_solution_status === 'source_described' ? form.existing_solutions.map(quoteInput).filter(Boolean) : [],
      alternative_explanations: textLines(form.alternative_explanations), missing_checks: textLines(form.missing_checks) });
  }
  return <form onSubmit={submit} className="need-analysis-form">
    <div className="panel-title"><h2>Grounded need analysis</h2><span className="tag">Revision {record.assessment?.analysis?.revision || 0}</span></div>
    <p className="muted">Quote what the source says, then label your interpretation separately. No buying interest or budget is confirmed by this review.</p>
    <label htmlFor="analysis-fit">Product fit judgement</label><select id="analysis-fit" value={form.fit} disabled={busy} onChange={event => change('fit', event.target.value)}>
      <option value="unknown">Unknown</option><option value="review">Needs review</option><option value="possible_fit">Possible fit · Inference to investigate</option><option value="not_a_fit">Not a fit · Reviewer judgement</option>
    </select>
    <h3 className="assessment-section-heading">Source observations</h3>
    {form.observations.map((quote, index) => <div key={index}>
      <QuoteField id={`analysis-observation-${index}`} label={`Observation ${index + 1}`} value={quote} evidence={record.evidence} disabled={busy} onChange={value => changeQuote('observations', index, value)}/>
      {form.observations.length > 1 && <button className="text-button" type="button" disabled={busy} onClick={() => change('observations', form.observations.filter((_, position) => position !== index))}>Remove observation {index + 1}</button>}
    </div>)}
    <button className="secondary" type="button" disabled={busy || form.observations.length >= 5} onClick={() => change('observations', [...form.observations, emptyQuote()])}>Add observation</button>
    <label htmlFor="analysis-hypothesis">Need hypothesis <span>Inference</span></label><textarea id="analysis-hypothesis" rows={3} maxLength={600} value={form.need_hypothesis} disabled={busy} onChange={event => change('need_hypothesis', event.target.value)}/>
    <label htmlFor="analysis-relevance">How your offer might help <span>Inference</span></label><textarea id="analysis-relevance" rows={3} maxLength={600} value={form.offer_relevance} disabled={busy} onChange={event => change('offer_relevance', event.target.value)}/>
    <label htmlFor="analysis-existing">Existing solution check</label><select id="analysis-existing" value={form.existing_solution_status} disabled={busy} onChange={event => change('existing_solution_status', event.target.value)}>
      <option value="not_checked">Not checked</option><option value="not_described_in_selected_excerpts">Not described in the selected excerpts · May exist elsewhere</option><option value="source_described">Source describes an existing solution</option>
    </select>
    {form.existing_solution_status === 'source_described' && <>
      {form.existing_solutions.map((quote, index) => <QuoteField key={index} id={`analysis-solution-${index}`} label={`Existing solution ${index + 1}`} value={quote} evidence={record.evidence} disabled={busy} onChange={value => changeQuote('existing_solutions', index, value)}/>)}
      <button className="secondary" type="button" disabled={busy || form.existing_solutions.length >= 3} onClick={() => change('existing_solutions', [...form.existing_solutions, emptyQuote()])}>Add existing solution</button>
      <label htmlFor="analysis-replacement">Why investigate a change despite the existing solution? <span>Inference</span></label><textarea id="analysis-replacement" rows={2} maxLength={400} value={form.replacement_reason} disabled={busy} onChange={event => change('replacement_reason', event.target.value)}/>
    </>}
    <EvidencePicker id="analysis-checked" label="Excerpts checked for existing alternatives" evidence={record.evidence} values={form.checked_evidence_ids} onChange={value => change('checked_evidence_ids', value)} disabled={busy}/>
    <label htmlFor="analysis-alternatives">Competing explanations <span>One per line; up to five</span></label><textarea id="analysis-alternatives" rows={3} required maxLength={2004} value={form.alternative_explanations} disabled={busy} onChange={event => change('alternative_explanations', event.target.value)}/>
    <label htmlFor="analysis-missing">Missing checks / next actions <span>One per line; up to six</span></label><textarea id="analysis-missing" rows={3} required maxLength={2405} value={form.missing_checks} disabled={busy} onChange={event => change('missing_checks', event.target.value)}/>
    <button className="primary assessment-save" type="submit" disabled={busy}>Save need analysis</button>
  </form>;
}
