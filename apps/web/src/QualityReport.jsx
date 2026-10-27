import React from 'react';

const percent = value => value === null ? 'Not measured' : `${(value * 100).toFixed(1)}%`;
const metrics = [['identity_accuracy', 'Identity agreement'], ['contact_attribution_precision', 'Contact attribution agreement'],
  ['factual_reference_coverage', 'Factual reference coverage'], ['audited_evidence_support', 'Audited evidence support'], ['reviewed_relevance_rate', 'Reviewed relevance · Unranked']];

function MetricTable({ results }) {
  return <div className="quality-table-wrap"><table className="quality-metrics"><caption>Saved-source audit metrics</caption>
    <thead><tr><th>Measure</th><th>Pass / reviewed</th><th>Unknown / not reviewed</th><th>Rate · 95% interval</th><th>Proposed gate</th></tr></thead>
    <tbody>{metrics.map(([key, label]) => { const metric = results[key]; return <tr key={key}><th scope="row">{label}</th>
      <td>{metric.passed} / {metric.reviewed}<small>{metric.eligible} eligible</small></td><td>{metric.unknown} / {metric.unreviewed}</td>
      <td>{percent(metric.rate)}<small>{metric.wilson_95 ? `${percent(metric.wilson_95[0])}–${percent(metric.wilson_95[1])}` : 'No interval without known judgements'}</small></td>
      <td>{metric.target === null ? 'Descriptive only' : `${percent(metric.target)} target`}<small>{metric.gate_status.replaceAll('_', ' ')}</small></td></tr>; })}</tbody>
  </table></div>;
}

export default function QualityReport({ baseline }) {
  const report = baseline.report;
  return <section className="panel quality-report" aria-labelledby="quality-report-heading"><h2 id="quality-report-heading">Quality baseline report</h2>
    {baseline.mode === 'synthetic' && <p className="demo-banner">SYNTHETIC QUALITY BASELINE · Fictional records cannot establish real-world accuracy.</p>}
    <p className="quality-callout">Release readiness: not established. Results describe manual judgements against frozen saved sources.</p>
    <dl className="quality-counts"><div><dt>Captured cases</dt><dd>{report.overall.sample_count}</dd></div><div><dt>Fully reviewed</dt><dd>{report.overall.fully_reviewed_cases}</dd></div>
      <div><dt>Changed live records</dt><dd>{report.overall.changed_since_snapshot}</dd></div><div><dt>Offer / location segments</dt><dd>{report.segments.length}</dd></div></dl>
    <p className="muted">Identity abstentions: {report.overall.identity_abstentions}. Unclaimed or excluded contacts: {report.overall.contact_abstentions_or_exclusions}. These are excluded from attribution precision and never counted as correct.</p>
    <MetricTable results={report.overall}/>
    <p className="quality-callout">Precision@20: not measured. {report.overall.precision_at_20.reason}</p>
    <h3>Results by offer and target location</h3>
    {report.segments.map((segment, index) => <details className="quality-segment" key={index}><summary>{segment.offer} · {segment.target_geography} · {segment.sample_count} case{segment.sample_count === 1 ? '' : 's'}</summary>
      <p>{segment.fully_reviewed_cases} fully reviewed · {segment.changed_since_snapshot} live records changed</p><MetricTable results={segment}/>
      <p>Reviewer flags: {Object.entries(segment.reviewer_issue_tags).map(([tag, count]) => `${tag.replaceAll('_', ' ')} (${count})`).join(', ') || 'None recorded'}</p></details>)}
    <details className="quality-method"><summary>Sample requirements, gaps and interpretation</summary><ul>{report.missing_acceptance.map(text => <li key={text}>{text}</li>)}</ul>
      <p>Real fully reviewed cases: {report.requirements.real_fully_reviewed_cases} / 60. Offer labels: {report.requirements.offer_labels} / 3. Geography labels: {report.requirements.geography_labels} / 2.</p>
      <p>Scenario flags not yet recorded: {report.requirements.scenario_tags_not_yet_recorded.map(value => value.replaceAll('_', ' ')).join(', ') || 'None; flags are reviewer supplied, not independent proof.'}</p>
      <h3>Other proposed release gates · Not measured</h3><ul>{report.other_release_gates.map(gate => <li key={gate.metric}>{gate.metric.replaceAll('_', ' ')}: {gate.reason}</li>)}</ul>
      <ul>{report.methodology.map(text => <li key={text}>{text}</li>)}</ul></details>
    <details className="quality-method"><summary>Dataset, reviewer revision and configuration</summary>
      <p>Captured {new Date(baseline.created_at).toLocaleString()} · Report generated {new Date(report.generated_at).toLocaleString()} · {baseline.split} sample</p>
      <small>Dataset SHA-256: {baseline.dataset_sha256}</small><small>Review set SHA-256: {report.review_set_sha256}</small>
      <p>{baseline.model_reason}</p><pre>{JSON.stringify({ configuration: baseline.configuration, hardware: baseline.hardware }, null, 2)}</pre></details>
  </section>;
}
