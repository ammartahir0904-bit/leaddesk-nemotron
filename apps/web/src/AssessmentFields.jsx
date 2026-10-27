import React from 'react';

export const emptyQuote = () => ({ value: '', evidence_ids: [] });
export const quoteInput = quote => quote?.value.trim() || quote?.evidence_ids.length ? quote : null;
export const textLines = text => text.split('\n').map(value => value.trim()).filter(Boolean);

export function EvidencePicker({ id, label, evidence, values, onChange, disabled }) {
  const selected = evidence.filter(item => values.includes(item.id));
  return <div className="evidence-picker">
    <label htmlFor={id}>{label}</label>
    <select id={id} multiple size={Math.min(4, Math.max(2, evidence.length))} value={values} disabled={disabled}
      onChange={event => onChange(Array.from(event.target.selectedOptions, option => option.value))}>
      {evidence.map(item => <option value={item.id} key={item.id}>{item.excerpt.slice(0, 100)}</option>)}
    </select>
    {selected.length > 0 && <details><summary>Read selected source excerpts ({selected.length})</summary>{selected.map(item => <div key={item.id}>
      <blockquote>{item.excerpt}</blockquote><a href={item.source_url} target="_blank" rel="noreferrer">Open source ↗</a>
      <small>Retrieved {new Date(item.retrieved_at).toLocaleString()} · Evidence {item.id}</small>
    </div>)}</details>}
  </div>;
}

export function QuoteField({ id, label, value, onChange, evidence, disabled }) {
  const quote = value || emptyQuote();
  return <div className="quote-field">
    <label htmlFor={`${id}-text`}>{label} <span>Source wording; leave blank if unknown</span></label>
    <textarea id={`${id}-text`} rows={2} maxLength={300} value={quote.value} disabled={disabled}
      onChange={event => onChange({ ...quote, value: event.target.value })}/>
    <EvidencePicker id={`${id}-evidence`} label={`${label} evidence`} evidence={evidence} values={quote.evidence_ids}
      onChange={evidence_ids => onChange({ ...quote, evidence_ids })} disabled={disabled}/>
  </div>;
}
