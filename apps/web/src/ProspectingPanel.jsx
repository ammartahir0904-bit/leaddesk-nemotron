import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './ProspectingPanel.css';

const LeadMap = lazy(() => import('./LeadMap'));
const key = () => crypto.randomUUID();
const csvCell = value => `"${String(value ?? '').replaceAll('"', '""')}"`;

function exportCsv(search, withReview = false) {
  const header = ['name', 'category', 'address', 'opportunity_score', 'website_status', 'website_grade', 'pitch', 'phones', 'emails',
    'socials', 'sources', 'best_verified_contact', 'contact_statuses', 'competitor_findings', 'phone', 'email', 'website', 'priority_points', 'need_signals', 'map_link',
    'web_websites', 'social_pages', 'web_contacts', 'identity_check', 'website_gaps', 'fit', 'top_gaps', 'message', 'questions'];
  const rows = search.candidates.map(c => [c.name, c.category_label, c.address, c.opportunity?.score, c.opportunity?.website_status,
    c.check?.health?.grade, c.pitch_plan?.opening?.[0]?.text, allPhones(c, withReview).join(' '), allEmails(c, withReview).join(' '), Object.values(socialsOf(c)).join(' '),
    (c.sources || []).join(' + '), verifiedBest(c) ? `${verifiedBest(c).e164 || verifiedBest(c).value} (approved)` : '',
    (c.contact_review?.contacts || []).map(x => `${x.e164 || x.value}: ${x.verdict}${x.verdict === 'rejected' ? ` (${x.reasons[0]})` : ''}`).join('; '),
    (c.competitors?.findings || []).map(f => f.text).join(' | '), c.phone, c.email, c.website, c.priority_points,
    c.need_signals.join(' '), c.evidence.url, (c.enrichment?.website_candidates || []).map(w => w.url).join(' '),
    (c.enrichment?.social_pages || []).map(p => p.url).join(' '),
    [...allPhones(c, withReview), ...allEmails(c, withReview)].join(' '), c.check?.identity?.verdict,
    (c.check?.site?.signals || []).filter(g => g.gap).map(g => g.label).join('; '), c.pitch_plan?.fit,
    (c.pitch_plan?.top_gaps || []).map(g => g.label).join('; '),
    (c.message_review?.action === 'edited' ? c.message_review.text : c.ai?.method === 'ollama_pitch_polish_v1' && c.ai.accepted && !c.ai.stale ? c.ai.message : c.pitch_plan?.message) || '',
    (c.pitch_plan?.questions || []).map(q => q.text).join(' | ')]);
  const blob = new Blob([[header, ...rows].map(row => row.map(csvCell).join(',')).join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = `leaddesk-prospects-${search.id}.csv`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const QUALITY = { good: 'Looks usable', unchecked: 'Not checked', unusable: 'Probably unusable', invalid: 'Invalid', needs_check: 'Check format' };

function ContactAnalysis({ value }) {
  return <details className="prospect-analysis"><summary>Contact analysis: {value.summary}</summary>
    <ul>{value.items.map(c => <li key={c.type + c.value}><strong>{c.type === 'email' ? c.value : c.e164 || c.value}</strong> · {QUALITY[c.quality]}
      {c.type === 'phone' && c.line !== 'unknown' && ` · ${c.line === 'mobile' ? 'mobile' : 'landline/office'}`}
      {c.whatsapp_link && <> · <a href={c.whatsapp_link} target="_blank" rel="noreferrer">WhatsApp link ↗</a></>}
      {[...c.signals, ...c.warnings].map(text => <small key={text}>{text}</small>)}</li>)}</ul></details>;
}

const CONTACT_RANK = c => c.type === 'whatsapp' ? 0 : c.type === 'phone' && c.analysis?.line === 'mobile' ? 1 : c.type === 'email' ? 2 : 3;
const CONTACT_KIND = c => c.type === 'whatsapp' ? 'WhatsApp' : c.type === 'email' ? 'Email' : c.analysis?.line === 'mobile' ? 'Mobile' : 'Phone';

const contactKey = (type, value) => type === 'email' ? value.toLowerCase() : value.replace(/\D/g, '').slice(-9);

function Enrichment({ value, review, onCheck, onFeedback, busy }) {
  // The review decides: rejected contacts are not listed here either (they are in "Rejected contacts" with the reason).
  const verdicts = Object.fromEntries((review?.contacts || []).map(c => [`${c.type === 'email' ? 'email' : 'phone'}:${contactKey(c.type, c.value)}`, c]));
  const verdictOf = c => verdicts[`${c.type === 'email' ? 'email' : 'phone'}:${contactKey(c.type, c.value)}`];
  const hidden = value.contacts.filter(c => verdictOf(c)?.verdict === 'rejected').length;
  const contacts = value.contacts.filter(c => verdictOf(c)?.verdict !== 'rejected').sort((a, b) => CONTACT_RANK(a) - CONTACT_RANK(b) || (a.confidence !== 'own_page') - (b.confidence !== 'own_page'));
  const possible = value.possible_pages || [];
  return <div className="prospect-online"><strong>Found online</strong>
    {value.context && <small>Searched for {value.context.category_word || 'this business'} in {value.context.city || 'the area'}.
      {' '}Pages must mention the place, the type of business or a local phone number.</small>}
    {!value.website_candidates.length && !value.social_pages.length && !contacts.length && <p>No web results clearly name this business here.</p>}
    {contacts.length > 0 && <ul className="found-contacts">{contacts.map(c => <li key={c.type + c.value}>
      <span className={`chip chip-${REVIEW_TONE[verdictOf(c)?.verdict] || 'neutral'}`}>{verdictOf(c)?.label || 'Not reviewed'}</span>{' '}
      <span className="chip chip-neutral">{CONTACT_KIND(c)}</span>{' '}
      <strong>{c.type === 'email' ? <a href={`mailto:${c.value}`}>{c.value}</a> : c.analysis?.e164 || c.value}</strong>
      {c.analysis?.whatsapp_link && c.type !== 'email' && <> · <a href={c.analysis.whatsapp_link} target="_blank" rel="noreferrer">Open WhatsApp ↗</a></>}
      {c.type === 'phone' && c.analysis?.line === 'mobile' && <small> · mobile: may be on WhatsApp (not confirmed)</small>}
      <small>{c.confirmed_by_user ? 'You confirmed this page' : c.confidence === 'own_page' ? 'Their own page' : 'Lower confidence: another page mentioning the name'}
        {' · '}<a href={c.source_url} target="_blank" rel="noreferrer">{c.source_title || c.source_url}</a>
        {c.origin === 'result_page' ? ' · read on the page' : ' · from the search snippet'}</small>
      {c.excerpt && <small className="prospect-excerpt">“{c.excerpt}”</small>}</li>)}</ul>}
    {hidden > 0 && <small>{hidden} contact{hidden === 1 ? '' : 's'} found here failed the review and {hidden === 1 ? 'is' : 'are'} hidden (see Rejected contacts).</small>}
    {value.social_pages.length > 0 && <ul className="found-pages">{value.social_pages.map(page => <li key={page.url}>
      <a href={page.url} target="_blank" rel="noreferrer">{page.platform} ↗</a> <small>{page.title}</small>
      {page.confirmed_by_user ? <small> · confirmed by you</small> : <button className="text-button" disabled={busy}
        onClick={() => onFeedback(page.url, 'no')} title="Not this business: remove it and its contacts">Not them</button>}</li>)}</ul>}
    {value.website_candidates.map(w => <p key={w.url}>Website: <a href={w.url} target="_blank" rel="noreferrer">{w.label} ↗</a>
      {w.name_match === 'partial' && ' (name partly matches; confirm)'}{w.is_listed_website && ' (same as listed)'}
      {' '}<button className="text-button" disabled={busy} onClick={() => onCheck(w.url)}>Check this website</button>
      {' '}<button className="text-button" disabled={busy} onClick={() => onFeedback(w.url, 'no')}>Not them</button></p>)}
    {possible.length > 0 && <details className="possible-pages"><summary>Possibly a different business ({possible.length})</summary>
      <p className="lead-muted">These name the business but nothing places them here. Their contacts are not used unless you confirm.</p>
      <ul>{possible.map(p => <li key={p.url}><a href={p.url} target="_blank" rel="noreferrer">{p.title || p.label} ↗</a>
        <small>{p.reason}</small>
        <span className="feedback-buttons">Is this them?{' '}
          <button className="text-button" disabled={busy} onClick={() => onFeedback(p.url, 'yes')}>Yes</button>
          <button className="text-button" disabled={busy} onClick={() => onFeedback(p.url, 'no')}>No</button></span></li>)}</ul></details>}
    {value.page_reads?.length > 0 && <details className="prospect-reads"><summary>Pages opened: {value.page_reads.filter(r => r.status === 'read').length} read,
      {' '}{value.page_reads.reduce((n, r) => n + r.added, 0)} new contacts</summary><ul>{value.page_reads.map(r => <li key={r.url}>
      <a href={r.url} target="_blank" rel="noreferrer">{new URL(r.url).hostname}</a>: {r.status === 'read' ? `read, ${r.added} new contact${r.added === 1 ? '' : 's'}` : 'could not read'}
      {r.message && <small>{r.message}</small>}</li>)}</ul></details>}
    {value.mentions?.length > 0 && <p>Mentioned on: {value.mentions.map(m => <a key={m.url} href={m.url} target="_blank" rel="noreferrer">{m.label} ↗</a>)}</p>}
    {value.engine_report?.blocked?.length > 0 && <p className="ai-warning">Incomplete: {value.engine_report.blocked.map(b => `${b.engine} (${b.reason})`).join(', ')}.
      Missing pages or contacts may exist; search again later.</p>}
    {value.engine_report && <small>Results by engine: {Object.entries(value.engine_report.results_by_engine).map(([e, n]) => `${e} ${n}`).join(', ') || 'none'} · {value.queries.length} searches</small>}
    {value.query_failures?.length > 0 && <small className="ai-warning">{value.query_failures.length} of {value.queries.length} searches failed: {value.query_failures[0].message}</small>}
    <small>{value.notes[0]}</small>
  </div>;
}

const REVIEW_TONE = { approved: 'good', needs_review: 'warn', rejected: 'bad' };
const WRONG = [['not_theirs', 'Not theirs'], ['disconnected', 'No longer works'], ['fake', 'Fake'], ['temporary', 'Temporary address']];

function ContactRow({ c, busy, onCorrect }) {
  const [asking, setAsking] = useState(false);
  const link = c.type === 'email' ? `mailto:${c.value}` : `tel:${(c.e164 || c.value).replace(/[^\d+]/g, '')}`;
  return <li className={`review-row review-${c.verdict}`}>
    <span className={`chip chip-${REVIEW_TONE[c.verdict]}`}>{c.label}</span>{' '}
    <span className="chip chip-neutral">{c.type === 'email' ? 'Email' : c.whatsapp ? 'WhatsApp' : c.line === 'mobile' ? 'Mobile' : 'Phone'}</span>{' '}
    <strong>{c.verdict === 'rejected' ? <s>{c.e164 || c.value}</s> : <a href={link}>{c.e164 || c.value}</a>}</strong>
    {c.whatsapp_link && c.verdict !== 'rejected' && <a className="mini-link" href={c.whatsapp_link} target="_blank" rel="noreferrer">WhatsApp</a>}
    {c.network && <small> · {c.line} · {c.network}</small>}
    <ul className="verify-reasons">{c.reasons.map(r => <li key={r}>{r}</li>)}
      {c.seen_in.length > 0 && <li>Seen in: {c.seen_in.map((s, i) => <span key={s.source + i}>{i ? ', ' : ''}{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.source}</a> : s.source}{s.date ? ` (${s.date})` : ''}</span>)}</li>}</ul>
    <span className="feedback-buttons">
      {c.correction ? <><small>Your correction ({c.correction.created_at.slice(0, 10)})</small>
        <button className="text-button" disabled={busy} onClick={() => onCorrect(c, 'clear')}>Undo</button></> : <>
        {c.verdict !== 'approved' && <button className="text-button" disabled={busy} onClick={() => onCorrect(c, 'correct')}>This is correct</button>}
        {!asking ? <button className="text-button" disabled={busy} onClick={() => setAsking(true)}>Wrong…</button> :
          <>{WRONG.map(([reason, label]) => <button key={reason} className="text-button" disabled={busy} onClick={() => { setAsking(false); onCorrect(c, 'wrong', reason); }}>{label}</button>)}
            <button className="text-button" onClick={() => setAsking(false)}>Cancel</button></>}</>}
    </span>
  </li>;
}

function ReviewedContacts({ lead, busy, onCorrect }) {
  const review = lead.contact_review;
  const [type, setType] = useState('phone'), [value, setValue] = useState('');
  if (!review) return null;
  const shown = review.contacts.filter(c => c.verdict !== 'rejected'), rejected = review.contacts.filter(c => c.verdict === 'rejected');
  return <div className="reviewed-contacts">
    <p className="review-counts">{review.counts.approved} approved · {review.counts.needs_review} need review · {review.counts.rejected} rejected</p>
    {shown.length ? <ul className="review-list">{shown.map(c => <ContactRow key={c.type + c.key} c={c} busy={busy} onCorrect={onCorrect}/>)}</ul>
      : <p className="lead-muted">No contact passed the review yet. Use Find contacts online or Check website.</p>}
    {rejected.length > 0 && <details className="rejected-contacts"><summary>Rejected contacts ({rejected.length}): hidden from the list, messages and CSV</summary>
      <ul className="review-list">{rejected.map(c => <ContactRow key={c.type + c.key} c={c} busy={busy} onCorrect={onCorrect}/>)}</ul></details>}
    <form className="add-contact" onSubmit={e => { e.preventDefault(); if (value.trim()) { onCorrect({ type, value: value.trim() }, 'added'); setValue(''); } }}>
      <select aria-label="Contact type" value={type} onChange={e => setType(e.target.value)}><option value="phone">Phone</option><option value="email">Email</option></select>
      <input aria-label="A contact you know is right" value={value} maxLength={254} placeholder="Add a contact you know is right" onChange={e => setValue(e.target.value)}/>
      <button className="secondary" disabled={busy || !value.trim()}>Add</button>
    </form>
    <small>{review.note} Temporary-email list: {review.disposable_list.entries} domains ({review.disposable_list.retrieved}).</small>
  </div>;
}

function AddWebsite({ lead, busy, onCheck }) {
  const [url, setUrl] = useState(''), [open, setOpen] = useState(false);
  const hasOwn = lead.website && !lead.website_is_social;
  if (!open) return <button className="text-button" onClick={() => setOpen(true)}>{hasOwn ? 'Use a different website' : 'Add website'}</button>;
  return <form className="add-website" onSubmit={e => { e.preventDefault(); if (url.trim()) onCheck(lead, url.trim(), true); }}>
    <label htmlFor={`site-${lead.id}`}>Their website</label>
    <input id={`site-${lead.id}`} value={url} maxLength={2048} placeholder="their-business.com" onChange={e => setUrl(e.target.value)} autoFocus/>
    <button className="secondary" disabled={busy || !url.trim()}>Read website</button>
    <button type="button" className="text-button" onClick={() => setOpen(false)}>Cancel</button>
    <small>LeadDesk reads it and cross-checks the name, phone and address with this lead; a mismatch is shown.</small>
  </form>;
}

const IDENTITY = { confirmed: 'Same business (cross-checked)', probably_same: 'Probably the same business', name_only: 'Only the name matches',
  possible_other_branch: 'Possibly another branch', different_business: 'May be a different business', unverified: 'Could not cross-check' };
const STATE = { yes: '✓', no: '✗', not_found: '–', unknown: '?', info: 'ℹ' };
const CHECK = { match: 'agrees', partial: 'partly agrees', differs: 'differs', conflict: 'conflicts', not_comparable: 'not comparable' };

function SiteCheck({ check, onOpenResearch }) {
  const site = check.site, identity = check.identity;
  if (check.unreachable) return <div className="prospect-check"><strong>Website could not be loaded</strong>
    <p className="ai-warning">{check.unreachable.url}: {check.unreachable.message}</p><p>{check.relevance_note}</p></div>;
  return <div className="prospect-check"><strong>Website checked</strong>
    {identity && <div className={`identity identity-${identity.verdict}`}><strong>{IDENTITY[identity.verdict]}</strong> {identity.summary}
      <details><summary>Cross-check details</summary><ul>{identity.checks.map(c => <li key={c.field}><strong>{c.field}</strong> {CHECK[c.status]}: {c.detail}</li>)}</ul></details></div>}
    {site && <>
      <p>Read {site.pages.filter(p => p.status === 'read').length} pages: {site.pages.map(p => <span key={p.url} className="page-ref">
        {p.status === 'read' ? <a href={p.url} target="_blank" rel="noreferrer">{p.kind}</a> : <span title={p.error}>{p.kind} (not read)</span>}</span>)}</p>
      <ul className="site-signals">{site.signals.map(g => <li key={g.id} className={g.gap ? 'gap' : ''}>
        <span className={`state state-${g.state}`}>{STATE[g.state]}</span> <strong>{g.label}</strong>{g.gap && g.relevant && <span className="tag relevant">matters for your product</span>}
        <small>{g.detail}{g.evidence && <> · <a href={g.evidence.url} target="_blank" rel="noreferrer" title={g.evidence.text}>source</a></>}</small></li>)}</ul>
      {site.structured.length > 0 && <p>Business data on the site: {site.structured.slice(0, 2).map(e => `${e.name} (${e.types.join(', ')})${e.rating ? `, rated ${e.rating.value} from ${e.rating.count || '?'} reviews` : ''}`).join('; ')}</p>}
      {site.social_links.length > 0 && <p>Links on the site: {site.social_links.slice(0, 5).map(u => <a key={u} href={u} target="_blank" rel="noreferrer">{u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40)} ↗</a>)}</p>}
      {site.redirect && <small>The listed link {site.redirect.from} redirected to {site.redirect.to}.</small>}
      <small>{site.notes.join(' ')}</small></>}
    <p>{check.contacts_found} contacts found. {check.relevance_note}</p>
    {check.contact_analysis?.length > 0 && <ContactAnalysis value={{ items: check.contact_analysis, summary: 'Contacts found on their website:' }}/>}
    {check.research_id && <button className="text-button" onClick={() => onOpenResearch(check.research_id)}>Open saved research and evidence</button>}</div>;
}

function Market({ value, aiReady, busy, onRun }) {
  const ai = value.ai;
  return <section className="prospect-market"><div className="prospect-head"><div><h3>Market problems</h3>
    <p>Recurring gaps across the {value.stats.checked_websites} checked websites, {value.stats.searched_online} businesses searched online and {value.stats.analysed} AI analyses in this search.</p></div>
    {aiReady && <button className="secondary" disabled={busy || (!value.stats.items.length && !value.stats.needs.length)} onClick={onRun}>{ai ? 'Find problems again (AI)' : 'Find problems (AI)'}</button>}</div>
    {!value.stats.items.length && <p>Use "Research top 3", "Find online" or "Check website" first; counts appear here.</p>}
    <ul>{value.stats.items.map(i => <li key={i.id}><span className="evidence-ref">{i.id}</span> {i.text}<small>{i.businesses.join(', ')}</small></li>)}</ul>
    {ai && <div className="prospect-ai"><strong>AI market summary</strong> <small>{ai.model} · {ai.seconds}s · ideas to validate, not facts</small>
      <p>{ai.summary}</p><ol>{ai.problems.map(p => <li key={p.problem}><strong>{p.problem}</strong> {p.evidence_ids.map(id => <span key={id} className="evidence-ref">{id}</span>)}
        {p.unsupported_terms?.length > 0 && <span className="ai-unsupported"> ⚠ not in cited counts: {p.unsupported_terms.join(', ')}</span>}
        {p.product_idea && <p><em>Could build:</em> {p.product_idea}</p>}{p.validate_by && <p><em>Validate by asking:</em> {p.validate_by}</p>}
        <small>Businesses: {p.businesses.join(', ') || 'none'}</small></li>)}</ol></div>}
    {value.stats.notes.map(n => <small key={n}>{n}</small>)}
  </section>;
}

const VERIFY = { supported: '✓ checked', partly: '≈ partly supported', not_supported: '✗ not supported' };

const FIT = { likely: 'Likely fit', possible: 'Possible fit', unlikely: 'Unlikely fit', unknown: 'Not enough evidence' };

function AIAnalysis({ value }) {
  const byId = Object.fromEntries(value.evidence.map(e => [e.id, e]));
  return <div className={`prospect-ai fit-${value.fit}`}>
    <strong>AI analysis: {FIT[value.fit]}</strong> <small>{value.model} · {value.seconds}s · a suggestion to check, not a fact</small>
    <p>{value.need_summary}</p>
    {value.already_has_similar !== 'unknown' && <p>Already has something similar: {value.already_has_similar}</p>}
    {value.grounding?.adjusted && <p className="ai-warning">{value.grounding.adjusted}</p>}
    {value.grounding?.warnings.map(w => <p key={w} className="ai-warning">⚠ {w}</p>)}
    {value.verification?.status === 'unavailable' && <p className="ai-warning">Second AI check unavailable: {value.verification.note}</p>}
    {value.verification?.counts?.missing > 0 && <p className="ai-warning">The second AI check skipped {value.verification.counts.missing} of {value.reasons.length} reasons; those are unchecked.</p>}
    {value.reasons.length > 0 && <ul>{value.reasons.map(r => <li key={r.text}>{r.text}{r.verification && <span className={`verify verify-${r.verification.verdict}`} title={r.verification.note}> {VERIFY[r.verification.verdict]}</span>}{r.unsupported_terms?.length > 0 && <span className="ai-unsupported"> ⚠ not found in cited evidence: {r.unsupported_terms.join(', ')}</span>} {r.evidence_ids.map(id => <span key={id} className="evidence-ref"
      title={byId[id] ? `${byId[id].source}: ${byId[id].text}` : id}>{byId[id]?.url ? <a href={byId[id].url} target="_blank" rel="noreferrer">{id}</a> : id}</span>)}</li>)}</ul>}
    {value.opening_line && <p><em>Opening line:</em> {value.opening_line}</p>}
    {value.questions_to_ask.length > 0 && <p><em>Ask:</em> {value.questions_to_ask.join(' · ')}</p>}
    {value.verdict && <small>You {value.verdict === 'agree' ? 'agreed' : 'disagreed'} with this older analysis.</small>}
  </div>;
}


const uniq = values => [...new Set(values.filter(Boolean))];
const uniqOk = (c, values) => { const bad = wrong(c); return uniq(values).filter(v => !bad.has(v)); };
const VERIFY_TONE = { confirmed: 'good', corroborated: 'good', single_source: 'neutral', likely_wrong: 'bad' };
const VERIFY_ICON = { confirmed: '✓', corroborated: '✓', single_source: '?', likely_wrong: '✗' };
const verifiedBest = c => (c.contact_review?.contacts || []).find(x => x.verdict === 'approved');
const wrong = c => new Set((c.verification?.contacts || []).filter(x => x.status === 'likely_wrong').flatMap(x => [x.value, x.e164]));
// Only contacts that passed the review (approved or needs review) are used anywhere: rows, filters, messages, CSV.
const usable = (c, kind, withReview = true) => (c.contact_review?.contacts || [])
  .filter(x => x.type === kind && (x.verdict === 'approved' || (withReview && x.verdict === 'needs_review')));
const allPhones = (c, withReview = true) => usable(c, 'phone', withReview).map(x => x.e164 || x.value);
const allEmails = (c, withReview = true) => usable(c, 'email', withReview).map(x => x.value);
const SOCIAL_HOSTS = [['facebook.com', 'Facebook'], ['fb.com', 'Facebook'], ['instagram.com', 'Instagram'], ['linkedin.com', 'LinkedIn'],
  ['tiktok.com', 'TikTok'], ['x.com', 'X'], ['twitter.com', 'X'], ['youtube.com', 'YouTube'], ['linktr.ee', 'Linktree'], ['beacons.ai', 'Beacons']];
function socialsOf(c) {
  const out = {};
  // Their own website's links first (most reliable), then map data, then pages found online.
  for (const url of [...(c.site_socials || []).map(s => s.url), ...(c.socials || []), ...(c.website_is_social ? [c.website] : []),
    ...(c.enrichment?.social_pages || []).map(p => p.url)]) {
    let hostname = '';
    try { hostname = new URL(url).hostname.replace(/^www\./, ''); } catch { continue; }
    const hit = SOCIAL_HOSTS.find(([h]) => hostname === h || hostname.endsWith('.' + h));
    if (hit && !out[hit[1]]) out[hit[1]] = url;
  }
  return out;
}
const whatsappOf = c => usable(c, 'phone').find(x => x.whatsapp_link)?.whatsapp_link;
const STATUS = { none: ['No website', 'bad'], social_only: ['Social page only', 'bad'], dead_builder: ['Dead website', 'bad'],
  unreachable: ['Website down', 'bad'], free_subdomain: ['Free subdomain', 'warn'], unchecked: ['Has website', 'neutral'], ok: ['Website OK', 'good'] };
const GRADE_TONE = { A: 'good', B: 'good', C: 'warn', D: 'bad', F: 'bad' };
function CategoryPicker({ api, categories, max, selected, setSelected, onError }) {
  const [query, setQuery] = useState(''), [matches, setMatches] = useState([]);
  const byId = Object.fromEntries(categories.map(c => [c.id, c]));
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setMatches([]); return; }
    const timer = setTimeout(() => api(`/v1/prospecting/categories/search?q=${encodeURIComponent(q)}`)
      .then(value => setMatches(value.items)).catch(e => onError(e.message)), 200);
    return () => clearTimeout(timer);
  }, [api, query, onError]);
  const toggle = id => setSelected(list => list.includes(id) ? list.filter(x => x !== id) : list.length >= max ? list : [...list, id]);
  const box = c => <label key={c.id} className="prospect-option">
    <input type="checkbox" checked={selected.includes(c.id)} disabled={!selected.includes(c.id) && selected.length >= max} onChange={() => toggle(c.id)}/> {c.label}</label>;
  const grouped = list => [...new Set(list.map(c => c.group))].map(group => <fieldset key={group}><legend>{group}</legend>
    {list.filter(c => c.group === group).map(box)}</fieldset>);
  const curated = categories.filter(c => c.source === 'curated'), all = categories.filter(c => c.source !== 'curated');
  return <div className="prospect-picker">
    <label htmlFor="prospect-type-search">Search {categories.length} business types (any language: e.g. "real estate", "inmobiliaria", "wedding hall", "خياط")</label>
    <input id="prospect-type-search" maxLength={60} value={query} placeholder="Type a business type…" onChange={e => setQuery(e.target.value)}/>
    {matches.length > 0 && <ul className="prospect-matches">{matches.map(m => <li key={m.id}>
      <label className="prospect-option"><input type="checkbox" checked={selected.includes(m.id)}
        disabled={!selected.includes(m.id) && selected.length >= max} onChange={() => toggle(m.id)}/>
        <span className="prospect-match"><strong>{m.label}</strong> <small>{m.group}{m.matched && m.matched !== m.label.toLowerCase() ? ` · matches "${m.matched}"` : ''}</small></span></label></li>)}</ul>}
    {query.trim().length >= 2 && !matches.length && <p className="prospect-hint">No business type matches "{query}". Try another word, or use "Name contains" below.</p>}
    <details><summary>Common business groups ({curated.length})</summary><div className="prospect-categories">{grouped(curated)}</div></details>
    <details><summary>Browse all {all.length} OpenStreetMap business types</summary><div className="prospect-categories">{grouped(all)}</div></details>
  </div>;
}


function ScoreBadge({ value, large }) {
  const band = value?.band || 'cool';
  return <span className={`score score-${band}${large ? ' score-large' : ''}`} title="Opportunity score: transparent points, not a probability">
    {value?.score ?? '–'}</span>;
}

function StatusChip({ lead }) {
  const status = lead.opportunity?.website_status || 'unchecked';
  const grade = lead.check?.health?.grade;
  if (grade && status === 'ok') return <span className={`chip chip-${GRADE_TONE[grade]}`}>Website grade {grade}</span>;
  const [label, tone] = STATUS[status] || STATUS.unchecked;
  return <span className={`chip chip-${tone}`}>{label}</span>;
}

function HealthCard({ health }) {
  return <section className="lead-section">
    <div className="health-head"><span className={`grade grade-${GRADE_TONE[health.grade]}`}>{health.grade}</span>
      <div><h4>Website health {health.score}/100</h4><small>{health.note}</small></div></div>
    <ul className="health-bars">{health.categories.map(c => <li key={c.id}><span>{c.label}</span>
      <span className="bar"><span style={{ width: `${100 * (c.max - c.lost) / c.max}%` }} className={c.lost === 0 ? 'full' : c.lost >= c.max / 2 ? 'low' : 'mid'}/></span>
      <small>{c.max - c.lost}/{c.max}</small></li>)}</ul>
    {health.issues.length > 0 ? <ul className="health-issues">{health.issues.map(i => <li key={i.check}><strong>−{i.points}</strong> {i.plain}
      {i.evidence?.text && <small title={i.evidence.text}> · <a href={i.evidence.url} target="_blank" rel="noreferrer">evidence</a>: {i.evidence.text.slice(0, 80)}</small>}</li>)}</ul>
      : <p className="lead-muted">No problems found on the pages read.</p>}
    {health.unmeasured.length > 0 && <small>Not measured: {health.unmeasured.join(', ')}.</small>}
  </section>;
}

function LeadRow({ lead, selected, onSelect }) {
  const phones = allPhones(lead), emails = allEmails(lead), socials = socialsOf(lead), whatsapp = whatsappOf(lead);
  return <li className={`lead-row${selected ? ' selected' : ''}`}>
    <button className="lead-open" onClick={() => onSelect(lead.id)} aria-label={`Open ${lead.name}`}>
      <ScoreBadge value={lead.opportunity}/>
      <span className="lead-name"><strong>{lead.name}</strong><small>{lead.category_label}{lead.address ? ` · ${lead.address}` : ''}</small></span>
    </button>
    <span className="lead-status"><StatusChip lead={lead}/></span>
    <span className="lead-contact">
      {phones[0] ? <a href={`tel:${phones[0].replace(/[^\d+]/g, '')}`}>{phones[0]}</a> : <span className="lead-muted">No phone</span>}
      {verifiedBest(lead) && <span className="verified-tick" title={`Approved by the contact review: ${verifiedBest(lead).value}`}>✓ approved</span>}
      {whatsapp && <a className="mini-link" href={whatsapp} target="_blank" rel="noreferrer">WhatsApp</a>}
      {phones.length > 1 && <span className="lead-muted"> +{phones.length - 1}</span>}
      {emails[0] ? <a className="lead-email" href={`mailto:${emails[0]}`}>{emails[0]}</a> : <span className="lead-muted lead-email">No email</span>}
    </span>
    <span className="lead-social">{Object.entries(socials).map(([name, url]) => <a key={name} href={url} target="_blank" rel="noreferrer"
      className={`social social-${name.toLowerCase()}`} title={name}>{name === 'Facebook' ? 'f' : name === 'Instagram' ? 'ig' : name.slice(0, 2).toLowerCase()}</a>)}</span>
  </li>;
}

function Verification({ value }) {
  return <div className="verification">
    <ul>{value.contacts.map(c => <li key={c.type + c.value} className={`verify-row verify-${c.status}`}>
      <span className={`chip chip-${VERIFY_TONE[c.status]}`}>{VERIFY_ICON[c.status]} {c.label}</span>
      <span className="verify-value">{c.type === 'phone' ? <a href={`tel:${(c.e164 || c.value).replace(/[^\d+]/g, '')}`}>{c.e164 || c.value}</a>
        : <a href={`mailto:${c.value}`}>{c.value}</a>}
        {c.type === 'phone' && c.line && <small> · {c.line}{c.network ? ` · ${c.network}` : ''}</small>}</span>
      <ul className="verify-reasons">{c.reasons.map(r => <li key={r}>{r}</li>)}
        <li>Seen in: {c.seen_in.map((s, i) => <span key={s.source + i}>{i ? ', ' : ''}{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.source}</a> : s.source}{s.date ? ` (${s.date})` : ''}</span>)}</li></ul>
    </li>)}</ul>
    <small>{value.note} Checked {new Date(value.verified_at).toLocaleString()}.</small>
  </div>;
}

const FEATURE_LABEL = { online_booking: 'Booking', online_ordering: 'Ordering', whatsapp: 'WhatsApp', contact_form: 'Form', mobile: 'Mobile' };
const STATE_MARK = { yes: '✓', no: '✗', not_found: '–' };

function Competitors({ value, lead, busy, onCompare }) {
  const rows = [{ ...value.me, distance_m: 0, self: true }, ...value.competitors];
  const pending = value.unchecked_websites.length + (value.me.own_website && !value.me.website_read ? 1 : 0);
  return <section className="lead-section">
    <h4>Competitors nearby ({value.competitors.length})</h4>
    {value.findings.length ? <ul className="findings">{value.findings.map(f => <li key={f.text}>{f.text}
      {f.evidence?.filter(Boolean).slice(0, 1).map(e => <small key={e.url}> · <a href={e.url} target="_blank" rel="noreferrer">evidence</a></small>)}</li>)}</ul>
      : <p className="lead-muted">No gap versus nearby competitors found yet.</p>}
    <div className="compare-scroll"><table className="compare">
      <thead><tr><th>Business</th><th>Km</th><th>Website</th>{Object.values(FEATURE_LABEL).map(l => <th key={l}>{l}</th>)}<th>Social</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.id} className={r.self ? 'self' : ''}>
        <td>{r.self ? <strong>{lead.name} (this lead)</strong> : r.name}</td><td>{r.self ? '–' : (r.distance_m / 1000).toFixed(1)}</td>
        <td>{r.grade ? <span className={`chip chip-${GRADE_TONE[r.grade]}`}>{r.grade}</span> : <span className={`chip chip-${(STATUS[r.website_status] || STATUS.unchecked)[1]}`}>{(STATUS[r.website_status] || STATUS.unchecked)[0]}</span>}</td>
        {Object.keys(FEATURE_LABEL).map(k => <td key={k} className={`mark mark-${r.features[k] || 'none'}`}>{r.website_read ? STATE_MARK[r.features[k]] || '?' : '·'}</td>)}
        <td>{r.socials.join(', ') || '–'}</td></tr>)}</tbody></table></div>
    <small>{value.note} "·" = website not read yet.</small>
    {pending > 0 && <button className="secondary" disabled={busy} onClick={onCompare}>Read {Math.min(pending, 4)} website{pending === 1 ? '' : 's'} to compare</button>}
  </section>;
}

const FIT_STATE = { has: ['Has', 'good'], missing: ['Missing', 'bad'], not_seen: ['Not seen', 'neutral'] };
const BUILD = { keep: ['Keep', 'good'], fix: ['Fix', 'warn'], add: ['Add', 'bad'], check: ['Check', 'neutral'] };

function EvidenceRefs({ ids, evidence }) {
  const byId = Object.fromEntries((evidence || []).map(e => [e.id, e]));
  return <>{(ids || []).map(id => <span key={id} className="evidence-ref" title={byId[id]?.text || id}>
    {byId[id]?.url ? <a href={byId[id].url} target="_blank" rel="noreferrer">{id}</a> : id}</span>)}</>;
}

function OfferFit({ fit, busy, onOverride }) {
  const rows = fit.features.filter(r => r.enabled);
  const correct = (r, state) => { const note = state === 'clear' ? '' : (window.prompt(`Why? (optional) e.g. "${state === 'has' ? 'They take orders on WhatsApp' : 'The link is broken'}"`) ?? null);
    if (note !== null) onOverride(r.id, state, note); };
  return <section className="lead-section">
    <h4>What you offer vs. what they have <small className="lead-muted">({fit.trade_label})</small></h4>
    <ul className="fit-table">{rows.map(r => <li key={r.id}>
      <span className={`chip chip-${FIT_STATE[r.state][1]}`}>{FIT_STATE[r.state][0]}</span> <strong>{r.label}</strong>
      <small>{r.detail}{r.evidence?.url && <> · <a href={r.evidence.url} target="_blank" rel="noreferrer" title={r.evidence.text}>evidence</a></>}</small>
      {onOverride && <span className="feedback-buttons">{r.corrected ? <><small>Corrected by you</small>
        <button className="text-button" disabled={busy} onClick={() => correct(r, 'clear')}>Undo</button></> : <>Wrong? Actually
        {r.state !== 'has' && <button className="text-button" disabled={busy} onClick={() => correct(r, 'has')}>they have it</button>}
        {r.state !== 'missing' && <button className="text-button" disabled={busy} onClick={() => correct(r, 'missing')}>they don't</button>}</>}</span>}</li>)}</ul>
    {fit.competitor_findings.length > 0 && <small>Nearby: {fit.competitor_findings[0]}</small>}
    <small>{fit.note}</small>
  </section>;
}

const PROBLEMS = [['wrong_fact', 'Wrong fact'], ['wrong_business', 'Wrong business'], ['too_generic', 'Too generic'], ['tone', 'Tone']];

function PitchPlan({ lead, plan, ai, aiReady, busy, onAnalyse, review, onMessage }) {
  const [copied, setCopied] = useState(false), [editing, setEditing] = useState(false), [draft, setDraft] = useState(''), [rejecting, setRejecting] = useState(false);
  const polished = ai?.method === 'ollama_pitch_polish_v1' && ai.accepted && !ai.stale ? ai.message : null;
  const mine = review?.action === 'edited' ? review.text : null;
  const message = mine || polished || plan.message;
  const copy = () => navigator.clipboard?.writeText([message, ...plan.questions.map(q => `- ${q.text}`)].join('\n'))
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  return <section className={`lead-section pitch fit-${plan.fit}`}>
    <div className="section-head"><h4>Pitch: {FIT[plan.fit]}</h4><small className="lead-muted">{plan.points} points</small></div>
    <p>{plan.summary}</p>
    {plan.reasons.length > 0 && <ul className="reason-list">{plan.reasons.map(r => <li key={r.text}>{r.text} <EvidenceRefs ids={r.evidence_ids} evidence={plan.evidence}/></li>)}</ul>}
    {plan.top_gaps.length > 0 && <><h4>Biggest gaps</h4><ol className="gap-list">{plan.top_gaps.map(g => <li key={g.id}><strong>{g.label}</strong>: {g.detail} <EvidenceRefs ids={g.evidence_ids} evidence={plan.evidence}/></li>)}</ol></>}
    {plan.build_plan.length > 0 && <details className="build-plan"><summary>What we'd build for them ({plan.build_plan.filter(b => b.action !== 'keep').length} changes)</summary>
      <ul>{plan.build_plan.map(b => <li key={b.id}><span className={`chip chip-${BUILD[b.action][1]}`}>{BUILD[b.action][0]}</span> {b.build}</li>)}</ul></details>}
    {message && <div className="pitch-message"><h4>Opening message {mine ? <small className="lead-muted">(written by you)</small> : polished ? <small className="lead-muted">(reworded by AI, checked)</small> : <small className="lead-muted">(written by LeadDesk from the checks)</small>}</h4>
      {editing ? <><textarea aria-label="Your message" rows={5} maxLength={2000} value={draft} onChange={e => setDraft(e.target.value)}/>
        <div className="prospect-actions"><button className="secondary" disabled={busy || !draft.trim()} onClick={() => { onMessage(lead, 'edited', null, draft); setEditing(false); }}>Save my message</button>
          <button className="text-button" onClick={() => setEditing(false)}>Cancel</button></div></> : <p>{message}</p>}
      {review && <p className={`message-state message-${review.action}`}>{{ approved: '✓ You approved this message', edited: '✎ Your edited message is used', rejected: `✗ You rejected it: ${(PROBLEMS.find(p => p[0] === review.problem) || ['', ''])[1]}` }[review.action]} ({review.created_at.slice(0, 10)})
        {review.stale && ' — the facts changed since; check it again.'} <button className="text-button" disabled={busy} onClick={() => onMessage(lead, 'clear')}>Undo</button></p>}
      {!review && !editing && <div className="feedback-buttons">
        <button className="text-button" disabled={busy} onClick={() => onMessage(lead, 'approved')}>✓ Approve</button>
        <button className="text-button" disabled={busy} onClick={() => { setDraft(message); setEditing(true); }}>✎ Edit</button>
        {!rejecting ? <button className="text-button" disabled={busy} onClick={() => setRejecting(true)}>✗ Reject…</button> :
          <>{PROBLEMS.map(([id, label]) => <button key={id} className="text-button" disabled={busy} onClick={() => { setRejecting(false); onMessage(lead, 'rejected', id); }}>{label}</button>)}</>}
        {rejecting && <small> A wrong fact? Correct it in "What you offer vs. what they have" or in Contact below: the message is rebuilt from your correction.</small>}</div>}
      {!polished && plan.opening.length > 0 && <small>Based on {plan.opening.map((o, i) => <EvidenceRefs key={i} ids={o.evidence_ids} evidence={plan.evidence}/>)}</small>}
      {plan.questions.length > 0 && <><h4>Questions to ask</h4><ul>{plan.questions.map(q => <li key={q.text}>{q.text} <EvidenceRefs ids={q.evidence_ids} evidence={plan.evidence}/></li>)}</ul></>}
      <div className="prospect-actions"><button className="secondary" onClick={copy}>{copied ? 'Copied' : 'Copy message'}</button>
        {aiReady && <button className="secondary" disabled={busy} onClick={() => onAnalyse(lead)}>{ai?.method === 'ollama_pitch_polish_v1' ? 'Reword with AI again' : 'Reword with AI'}</button>}</div>
      {ai?.method === 'ollama_pitch_polish_v1' && <div className="ai-note">
        {ai.stale && <p className="ai-warning">The facts changed since the AI reworded this; LeadDesk's current wording is shown.</p>}
        {!ai.accepted && <p className="ai-warning">AI wording rejected: {ai.rejected_reasons.join('; ')}. LeadDesk's wording is kept.</p>}
        <small>{ai.note} {ai.model} · {ai.seconds}s</small>
      </div>}
    </div>}
    {!message && plan.fit === 'unknown' && <p className="lead-muted">Check their website to get a specific message.</p>}
    <details><summary>Evidence ({plan.evidence.length})</summary><ul className="evidence-list">{plan.evidence.map(e => <li key={e.id}>
      <span className="evidence-ref">{e.id}</span> {e.text} {e.url && <a href={e.url} target="_blank" rel="noreferrer">source</a>}</li>)}</ul></details>
    <small>{plan.note}</small>
  </section>;
}

function OfferPack({ search, busy, onSave }) {
  const all = useMemo(() => {
    const seen = new Map();
    for (const lead of search.candidates) for (const f of lead.offer_fit?.features || []) if (!seen.has(f.id)) seen.set(f.id, f);
    return [...seen.values()];
  }, [search]);
  const chosen = new Set(search.offer_pack || all.filter(f => f.default).map(f => f.id));
  const [draft, setDraft] = useState(chosen);
  useEffect(() => { setDraft(new Set(search.offer_pack || all.filter(f => f.default).map(f => f.id))); }, [search.offer_pack, all]);
  if (!all.length) return null;
  const toggle = id => setDraft(d => { const n = new Set(d); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return <details className="offer-pack"><summary>What you deliver ({chosen.size} of {all.length})</summary>
    <p className="hint">Tick what your product includes. Each business is compared against these, and the pitch only mentions them.</p>
    <div className="offer-pack-grid">{all.map(f => <label key={f.id} className="check"><input type="checkbox" checked={draft.has(f.id)} onChange={() => toggle(f.id)}/>
      <span>{f.build}</span></label>)}</div>
    <div className="prospect-actions"><button className="secondary" disabled={busy} onClick={() => onSave([...draft])}>Save</button>
      <button className="text-button" disabled={busy} onClick={() => onSave(null)}>Reset to suggestions</button></div>
  </details>;
}

function Screenshot({ api, id, label }) {
  const [src, setSrc] = useState(null), [failed, setFailed] = useState(false);
  useEffect(() => {
    let url = null, live = true;
    api(`/v1/prospecting/screens/${id}`, { download: true })
      .then(blob => { url = URL.createObjectURL(blob); if (live) setSrc(url); }).catch(() => live && setFailed(true));
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [api, id]);
  if (failed) return <p className="lead-muted">{label}: screenshot expired (kept 24 hours). Check the website again for a new one.</p>;
  return <figure className={`screen screen-${label.toLowerCase()}`}>{src ? <img src={src} alt={`${label} view of the website's first screen`}/> : <span className="lead-muted">Loading…</span>}
    <figcaption>{label}</figcaption></figure>;
}

const LAYOUT_STATE = { yes: ['✓', 'good'], no: ['✗', 'bad'], not_found: ['–', 'neutral'] };

function Layout({ api, layout, reading }) {
  const screens = layout.screens || {};
  return <section className="lead-section layout">
    <h4>Website layout</h4>
    <small>{layout.note}</small>
    {(screens.phone || screens.desktop) && <div className="screens">
      {screens.phone && <Screenshot api={api} id={screens.phone} label="Phone"/>}
      {screens.desktop && <Screenshot api={api} id={screens.desktop} label="Desktop"/>}</div>}
    <ul className="layout-findings">{layout.findings.map(f => <li key={f.id} className={f.gap ? 'gap' : ''}>
      <span className={`chip chip-${(LAYOUT_STATE[f.state] || ['?', 'neutral'])[1]}`}>{(LAYOUT_STATE[f.state] || ['?'])[0]}</span> <strong>{f.label}</strong>
      <small>{f.detail}{f.evidence?.text ? ` · ${f.evidence.text}` : ''}</small></li>)}</ul>
    {layout.unmeasured?.length > 0 && <small>Not measured without Chrome: {layout.unmeasured.join(', ')}.</small>}
    <details><summary>Page structure: {layout.sections.length} sections, {layout.nav.length} menu items, {layout.actions.length} buttons</summary>
      {layout.nav.length > 0 && <p><em>Menu:</em> {layout.nav.join(' · ')}</p>}
      {layout.sections.length > 0 && <ol className="layout-sections">{layout.sections.map(x => <li key={x.id}><strong>{x.label}</strong>{x.heading && x.heading !== x.label ? ` — ${x.heading}` : ''}</li>)}</ol>}
      {layout.actions.length > 0 && <p><em>Buttons:</em> {layout.actions.map((a, i) => <span key={i} className="chip chip-neutral" title={a.href}>{a.label}: {a.text}{a.first_screen_phone ? ' (first phone screen)' : ''}</span>)}</p>}
      {layout.headings.length > 0 && <p><em>Headings:</em> {layout.headings.slice(0, 10).map(h => h.text).join(' · ')}</p>}
    </details>
    {reading?.problems?.length > 0 && <div className="reading-problems"><strong>Why some pages were not read fully</strong>
      <ul>{reading.problems.map((r, i) => <li key={r.url + i}><a href={r.url} target="_blank" rel="noreferrer">{r.kind || 'page'}</a>: {r.reason}
        <small>Next step: {r.next_step}</small></li>)}</ul></div>}
    {reading?.chrome_used && <small>Drawn in Chrome on this computer ({reading.chrome_seconds}s{reading.blocked_requests ? `, ${reading.blocked_requests} private or unsafe requests blocked` : ''}).</small>}
  </section>;
}

function LeadDetail({ api, lead, offerKind, busy, aiReady, onClose, onCheck, onEnrich, onAnalyse, onOpenResearch, onVerify, onCompare, onFeedback,
  onCorrect, onOverride, onMessage, mailboxes, setMailboxes, chrome, setChrome, browser }) {
  const socials = socialsOf(lead);
  const typedSite = lead.check?.website_source === 'user_supplied' ? lead.check.website_url : null;
  const canCheck = (lead.website && !lead.website_is_social) || !!typedSite;
  return <aside className="lead-detail" aria-label={`${lead.name} details`}>
    <header className="lead-detail-head">
      <ScoreBadge value={lead.opportunity} large/>
      <div><h3>{lead.name}</h3><p>{lead.category_label}{lead.address ? ` · ${lead.address}` : ''}</p>
        <p className="lead-sources">Sources: {(lead.sources || ['OpenStreetMap']).join(' + ')}</p></div>
      <button className="icon-button" onClick={onClose} aria-label="Close details">×</button>
    </header>
    <div className="lead-detail-body">
      <section className="lead-section">
        <h4>Why this lead</h4>
        <ul className="reason-list">{(lead.opportunity?.reasons || []).map(r => <li key={r}>{r}</li>)}
          {!lead.opportunity?.reasons?.length && <li className="lead-muted">No gap or contact found yet. Use Find online or Check website.</li>}</ul>
        <small>{lead.opportunity?.note}</small>
      </section>
      {lead.pitch_plan && <PitchPlan lead={lead} plan={lead.pitch_plan} ai={lead.ai} aiReady={aiReady} busy={busy} onAnalyse={onAnalyse} review={lead.message_review} onMessage={onMessage}/>}
      <section className="lead-section">
        <div className="section-head"><h4>Contact</h4>
          <button className="secondary" disabled={busy} onClick={() => onVerify(lead)} title="Read their website and check every phone and email again">{lead.verification ? 'Review again' : 'Review contacts'}</button></div>
        <label className="check"><input type="checkbox" checked={mailboxes} onChange={e => setMailboxes(e.target.checked)}/>
          <span>Mailbox check: ask each email's mail server whether the mailbox exists. No email is sent; it contacts their mail server from your internet connection. Turn off if you prefer.</span></label>
        <ReviewedContacts lead={lead} busy={busy} onCorrect={(c, verdict, reason) => onCorrect(lead, c, verdict, reason)}/>
        <dl className="contact-grid">
          <dt>Website</dt><dd>{lead.website ? <a href={lead.website} target="_blank" rel="noreferrer">{lead.website}</a> : <span className="lead-muted">None listed</span>}
            {lead.check?.website_source === 'user_supplied' && <small>You added <a href={lead.check.website_url} target="_blank" rel="noreferrer">{lead.check.website_url}</a></small>}
            <small>{lead.opportunity?.website_status_reason}</small>
            <AddWebsite key={lead.id} lead={lead} busy={busy} onCheck={onCheck}/></dd>
          <dt>Social</dt><dd>{Object.keys(socials).length ? Object.entries(socials).map(([n, u]) => <a key={n} href={u} target="_blank" rel="noreferrer">{n}</a>) : <span className="lead-muted">None found</span>}</dd>
          <dt>Map</dt><dd><a href={lead.evidence.url} target="_blank" rel="noreferrer">Open location</a></dd>
        </dl>
        {Object.keys(lead.field_sources || {}).length > 0 && <small>Filled from Overture Maps: {Object.keys(lead.field_sources).join(', ')}.</small>}
        {lead.enrichment && <Enrichment value={lead.enrichment} review={lead.contact_review} busy={busy} onCheck={url => onCheck(lead, url)} onFeedback={(url, verdict) => onFeedback(lead, url, verdict)}/>}
      </section>
      {lead.check?.site?.layout && <Layout api={api} layout={lead.check.site.layout} reading={lead.check.site.reading}/>}
      {lead.check?.health && <HealthCard health={lead.check.health}/>}
      {lead.competitors && <Competitors value={lead.competitors} lead={lead} busy={busy} onCompare={() => onCompare(lead)}/>}
      {!lead.check && canCheck && offerKind === 'web_presence' && <section className="lead-section"><h4>Website health</h4>
        <p className="lead-muted">Check their website to get a graded report of its problems.</p></section>}
      {lead.offer_fit && <OfferFit fit={lead.offer_fit} busy={busy} onOverride={(feature, state, note) => onOverride(lead, feature, state, note)}/>}
      {lead.ai && lead.ai.method !== 'ollama_pitch_polish_v1' && <details className="lead-section"><summary>Earlier AI analysis (older method)</summary>
        <AIAnalysis value={lead.ai} busy={busy}/></details>}
      {lead.check && <details className="lead-section"><summary>Website reading details</summary><SiteCheck check={lead.check} onOpenResearch={onOpenResearch}/></details>}
      <small className="lead-muted">{lead.budget_reason} {lead.budget_signals.join(' ')}</small>
    </div>
    <footer className="lead-detail-actions">
      <ChromeToggle chrome={chrome} setChrome={setChrome} browser={browser}/>
      <button className="primary" disabled={busy} onClick={() => onEnrich(lead)}>{lead.enrichment ? 'Search online again' : 'Find contacts online'}</button>
      {canCheck && <button className="secondary" disabled={busy} onClick={() => typedSite ? onCheck(lead, typedSite, true) : onCheck(lead)}>{lead.check ? 'Check website again' : 'Check website'}</button>}
    </footer>
  </aside>;
}

function ChromeToggle({ chrome, setChrome, browser }) {
  if (browser && !browser.installed) return <small className="lead-muted chrome-toggle">{browser.message}</small>;
  return <label className="check chrome-toggle"><input type="checkbox" checked={chrome} onChange={e => setChrome(e.target.checked)}/>
    <span>Read JavaScript websites with Chrome on this computer. It loads the site like a browser, including its third-party scripts, and takes phone and desktop screenshots (deleted after 24 hours).</span></label>;
}

const FILTERS = [
  ['no_site', 'No website', l => ['none', 'social_only', 'dead_builder', 'unreachable'].includes(l.opportunity?.website_status)],
  ['weak_site', 'Weak website', l => ['free_subdomain'].includes(l.opportunity?.website_status) || ['C', 'D', 'F'].includes(l.check?.health?.grade)],
  ['phone', 'Has phone', l => allPhones(l).length > 0],
  ['email', 'Has email', l => allEmails(l).length > 0],
  ['verified', 'Approved contact', l => !!verifiedBest(l)],
  ['hot', 'Hot leads', l => l.opportunity?.band === 'hot'],
];

function Results({ search, busy, aiReady, web, ai, market, onRefresh, onResearch, onEnrichTop, onAnalyseTop, onMarketAI, onVerifyTop, onProvider, handlers }) {
  const [active, setActive] = useState([]), [text, setText] = useState(''), [sort, setSort] = useState('score');
  const [view, setView] = useState('list'), [selectedId, setSelectedId] = useState(null), [csvReview, setCsvReview] = useState(false);
  const leads = search.candidates;
  const counts = Object.fromEntries(FILTERS.map(([id, , test]) => [id, leads.filter(test).length]));
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    const list = leads.filter(l => active.every(id => FILTERS.find(f => f[0] === id)[2](l)) &&
      (!q || `${l.name} ${l.category_label} ${l.address || ''}`.toLowerCase().includes(q)));
    const order = { score: (a, b) => (b.opportunity?.score ?? 0) - (a.opportunity?.score ?? 0), name: (a, b) => a.name.localeCompare(b.name),
      contacts: (a, b) => (allPhones(b).length + allEmails(b).length) - (allPhones(a).length + allEmails(a).length) };
    return [...list].sort(order[sort]);
  }, [leads, active, text, sort]);
  const selected = leads.find(l => l.id === selectedId);
  const select = useCallback(id => setSelectedId(id), []);
  const toggle = id => setActive(list => list.includes(id) ? list.filter(x => x !== id) : [...list, id]);
  const sources = search.sources || {};
  return <section className="results">
    <div className="results-head">
      <div><h2>{leads.length} businesses · {search.place.display_name.split(',').slice(0, 2).join(',')}</h2>
        <p>{search.input.offer} · {new Date(search.retrieved_at).toLocaleString()}
          {sources.overture && ` · Overture ${sources.overture.businesses}`}{sources.openstreetmap && ` · OpenStreetMap ${sources.openstreetmap.businesses}`}</p></div>
      <div className="results-actions">
        <button className="primary" disabled={busy || !leads.length} onClick={onResearch} title="Find online, read the website and run AI for the top 3 not yet researched">Research top 3</button>
        <button className="secondary" disabled={busy || !web?.json_enabled} onClick={onEnrichTop} title={web?.json_enabled ? '' : web?.message}>Find contacts for top 10</button>
        <button className="secondary" disabled={busy || !leads.length} onClick={onVerifyTop} title="Read their websites and review every phone and email">Review contacts for top 10</button>
        {aiReady && <button className="secondary" disabled={busy} onClick={onAnalyseTop} title="Reword the top 5 messages with your local AI model; LeadDesk checks every word">AI reword top 5</button>}
        <button className="secondary" disabled={!leads.length} onClick={() => exportCsv(search, csvReview)} title="Rejected contacts are never exported">Download CSV</button>
        <label className="check csv-review"><input type="checkbox" checked={csvReview} onChange={e => setCsvReview(e.target.checked)}/><span>Include contacts that need review</span></label>
      </div>
    </div>
    <OfferPack search={search} busy={busy} onSave={handlers.onOfferPack}/>
    <div className="stats">{[['Businesses', leads.length], ['No website', counts.no_site], ['Have phone', counts.phone],
      ['Approved contact', counts.verified], ['Hot leads', counts.hot]].map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
    <div className="toolbar">
      <div className="filter-chips" role="group" aria-label="Filters">{FILTERS.map(([id, label]) => <button key={id} aria-pressed={active.includes(id)}
        className={`filter${active.includes(id) ? ' on' : ''}`} onClick={() => toggle(id)}>{label} <span>{counts[id]}</span></button>)}</div>
      <div className="toolbar-right">
        <input type="search" aria-label="Filter by name or address" placeholder="Filter by name or address" value={text} onChange={e => setText(e.target.value)}/>
        <select aria-label="Sort" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="score">Best opportunity</option><option value="contacts">Most contacts</option><option value="name">Name A–Z</option></select>
        <div className="view-toggle" role="group" aria-label="View">{['list', 'map'].map(v => <button key={v} aria-pressed={view === v}
          className={view === v ? 'on' : ''} onClick={() => setView(v)}>{v === 'list' ? 'List' : 'Map'}</button>)}</div>
      </div>
    </div>
    <div className={`results-body${selected ? ' with-detail' : ''}`}>
      <div className="results-main">
        {view === 'map' && <><Suspense fallback={<p className="lead-muted">Loading map…</p>}>
          <LeadMap leads={shown} selectedId={selectedId} onSelect={select}/></Suspense>
          <small className="lead-muted">Map tiles load from tile.openstreetmap.org while the map is open.</small></>}
        {view === 'list' && <ul className="lead-list">
          <li className="lead-row lead-header" aria-hidden="true"><span>Business</span><span>Website</span><span>Contact</span><span>Social</span></li>
          {shown.map(lead => <LeadRow key={lead.id} lead={lead} selected={lead.id === selectedId} onSelect={select}/>)}</ul>}
        {!shown.length && <p className="empty">{leads.length ? 'No business matches these filters. Remove one filter at a time.' :
          'No businesses of these types were found here. Try a wider area, more business types, or turn on Overture Maps.'}</p>}
      </div>
      {selected && <LeadDetail lead={selected} offerKind={search.offer_kind} busy={busy} aiReady={aiReady} onClose={() => setSelectedId(null)} {...handlers}/>}
    </div>
    <details className="results-more"><summary>Data sources, connections and market problems</summary>
      <button className="secondary" disabled={busy} onClick={onRefresh}>Refresh connections</button>
      <p className="hint">AI rewording: {ai?.ready ? `ready with ${ai.selected.name} (${ai.selected.provider === 'token_factory' ? 'NVIDIA Nemotron on Nebius Token Factory' : 'runs on this computer'}).` : (ai?.problem || 'Not connected.')}</p>
      <p className="hint">Web search: {web?.provider === 'tavily' ? `Tavily (${web.tavily_credits_used} credits used since start). Queries (business names, types and cities) go to Tavily.`
        : `your local SearXNG at ${web?.url || '127.0.0.1:8888'}: ${web ? web.message : 'checking…'} Searching sends business names and your location to the search engines SearXNG uses.`}</p>
      {web?.tavily_configured && <label className="check"><input type="checkbox" checked={web.provider === 'tavily'} disabled={busy}
        onChange={e => onProvider(e.target.checked ? 'tavily' : 'searxng')}/>
        <span>Use Tavily for Find online (reliable search API; uses your Tavily credits; queries are sent to Tavily). Off = local SearXNG.</span></label>}
      <ul className="coverage">{search.coverage.map(t => <li key={t}>{t}</li>)}</ul>
      {market && <Market value={market} aiReady={aiReady} busy={busy} onRun={onMarketAI}/>}
      <p className="hint">Business data © OpenStreetMap contributors (ODbL){sources.overture && '; Overture Maps Foundation (CDLA-Permissive-2.0 and per-source licences)'}.</p>
    </details>
  </section>;
}

function SiteAnalysis({ api, value, busy, aiReady, onPolish, onClose, onDelete, onOpenResearch }) {
  const item = value.item, site = value.site;
  return <section className="site-analysis" aria-label={`Website analysis of ${item.name}`}>
    <header className="lead-detail-head">
      {value.health && <span className={`grade grade-${GRADE_TONE[value.health.grade]}`}>{value.health.grade}</span>}
      <div><h3>{item.name}</h3><p><a href={value.url} target="_blank" rel="noreferrer">{value.url}</a></p>
        <p className="lead-sources">{item.category_label}{item.category_source && item.category_source !== 'unknown' ? ` (${item.category_source})` : ''} · analysed {new Date(value.created_at).toLocaleString()} · for “{value.input.offer}”</p></div>
      <button className="icon-button" onClick={onClose} aria-label="Close analysis">×</button>
    </header>
    <div className="site-analysis-body">
      <div className="site-analysis-col">
        <PitchPlan lead={item} plan={value.pitch_plan} ai={value.ai} aiReady={aiReady} busy={busy} onAnalyse={onPolish}/>
        <OfferFit fit={value.offer_fit}/>
        {value.contact_analysis.length > 0 && <section className="lead-section"><h4>Contacts on their website</h4>
          <ul className="found-contacts">{value.contact_analysis.map(c => <li key={c.type + c.value}><span className="chip chip-neutral">{c.type === 'email' ? 'Email' : c.line === 'mobile' ? 'Mobile' : 'Phone'}</span>{' '}
            <strong>{c.type === 'email' ? c.value : c.e164 || c.value}</strong>{c.whatsapp_link && <> · <a href={c.whatsapp_link} target="_blank" rel="noreferrer">WhatsApp ↗</a></>}
            <small>{c.page_kind} page · <a href={c.page_url} target="_blank" rel="noreferrer">source</a></small></li>)}</ul></section>}
        {site.social_links.length > 0 && <section className="lead-section"><h4>Social pages linked from the site</h4>
          <p>{site.social_links.slice(0, 6).map(u => <a key={u} className="mini-link" href={u} target="_blank" rel="noreferrer">{u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40)}</a>)}</p></section>}
      </div>
      <div className="site-analysis-col">
        {site.layout && <Layout api={api} layout={site.layout} reading={site.reading}/>}
        {value.health && <HealthCard health={value.health}/>}
        <details className="lead-section"><summary>Pages read ({site.pages.filter(x => x.status === 'read').length})</summary>
          <ul>{site.pages.map(x => <li key={x.url}><a href={x.url} target="_blank" rel="noreferrer">{x.kind}</a>: {x.status === 'read' ? `read${x.rendered ? ' in Chrome' : ''}, ${x.words ?? '?'} words` : x.reason || x.error}</li>)}</ul>
          <small>{site.notes.join(' ')}</small>
          {value.research_id && <button className="text-button" onClick={() => onOpenResearch(value.research_id)}>Open saved research and evidence</button>}</details>
      </div>
    </div>
    <footer className="lead-detail-actions"><button className="text-button" disabled={busy} onClick={onDelete}>Delete this analysis</button></footer>
  </section>;
}

function AnalyseWebsite({ api, offer, location, busy, run, aiReady, chrome, setChrome, browser, onOpenResearch, setError }) {
  const [url, setUrl] = useState(''), [value, setValue] = useState(null), [recent, setRecent] = useState(null);
  const pending = useRef(null);
  const refresh = useCallback(() => api('/v1/prospecting/site-analyses').then(setRecent).catch(() => setRecent(null)), [api]);
  useEffect(() => { refresh(); }, [refresh]);
  const analyse = event => {
    event.preventDefault();
    if (offer.trim().length < 3) { setError('First describe what you sell in "What do you sell?" above, so the website is compared with your offer.'); return; }
    run(`Reading ${url.trim()}${chrome ? ' in Chrome (phone and desktop)' : ''}: home, contact, about, services, reviews, gallery and team pages…`, async () => {
      const body = JSON.stringify({ url: url.trim(), offer: offer.trim(), location: location.trim(), render: chrome });
      if (pending.current?.body !== body) pending.current = { body, key: key() };
      setValue(await api('/v1/prospecting/site-analyses', { method: 'POST', headers: { 'Idempotency-Key': pending.current.key }, body }));
      pending.current = null;
      refresh();
    });
  };
  const polish = () => run('Your local AI model is rewording the message. LeadDesk checks every word…', async () => {
    setValue(await api(`/v1/prospecting/site-analyses/${value.id}/polish`, { method: 'POST' }));
  });
  const remove = () => run('Deleting analysis…', async () => {
    await api(`/v1/prospecting/site-analyses/${value.id}`, { method: 'DELETE' }); setValue(null); refresh();
  });
  return <section className="analyse-website">
    <form className="analyse-form" onSubmit={analyse}>
      <div className="field"><label htmlFor="analyse-url">Analyse a business website</label>
        <input id="analyse-url" value={url} maxLength={2048} placeholder="their-business.com" onChange={e => setUrl(e.target.value)}/></div>
      <button className="secondary" disabled={busy || url.trim().length < 4}>Analyse website</button>
    </form>
    <p className="hint">Reads their pages, layout and contacts, compares them with what you sell{offer.trim() ? ` (“${offer.trim().slice(0, 60)}”)` : ''} and writes a specific pitch.</p>
    <ChromeToggle chrome={chrome} setChrome={setChrome} browser={browser}/>
    {recent?.items?.length > 0 && !value && <details className="history"><summary>Recent website analyses ({recent.items.length})</summary>
      {recent.items.map(i => <div className="history-row" key={i.id}><span><strong>{i.name}</strong> · {i.grade ? `grade ${i.grade} · ` : ''}{FIT[i.fit]}<small>{i.url}</small></span>
        <button className="secondary" disabled={busy} onClick={() => run('Opening analysis…', async () => setValue(await api(`/v1/prospecting/site-analyses/${i.id}`)))}>Open</button></div>)}</details>}
    {value && <SiteAnalysis api={api} value={value} busy={busy} aiReady={aiReady} onPolish={polish} onClose={() => setValue(null)} onDelete={remove} onOpenResearch={onOpenResearch}/>}
  </section>;
}

const pct = r => r?.percent == null ? '–' : `${r.percent}% (${r.count}/${r.of})`;

function QualityPanel({ api, busy, run }) {
  const [report, setReport] = useState(null), [rules, setRules] = useState(null);
  const load = useCallback(() => Promise.all([api('/v1/prospecting/quality-report').then(setReport), api('/v1/prospecting/rules').then(setRules)]), [api]);
  const approve = p => run('Approving the rule and applying it to every search…', async () => {
    setRules(await api('/v1/prospecting/rules', { method: 'POST', body: JSON.stringify({ kind: p.kind, value: p.value }) })); await load(); });
  const toggle = r => run('Saving…', async () => {
    setRules(await api(`/v1/prospecting/rules/${r.id}`, { method: 'POST', body: JSON.stringify({ status: r.status === 'active' ? 'off' : 'active' }) })); await load(); });
  const download = () => {
    const rows = [['source', 'contacts', 'approved', 'needs_review', 'rejected', 'corrected_by_you'],
      ...report.contacts.by_source.map(r => [r.source, r.total, pct(r.approved), pct(r.needs_review), pct(r.rejected), pct(r.corrected_by_you)])];
    const url = URL.createObjectURL(new Blob([rows.map(r => r.map(csvCell).join(',')).join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a'); a.href = url; a.download = 'leaddesk-quality-report.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <details className="quality-panel" onToggle={e => { if (e.target.open && !report) run('Measuring result quality…', load); }}>
    <summary>Quality report and learned rules</summary>
    {report && <>
      <p className="hint">{report.note} Sample: {report.sample.searches} searches, {report.sample.contacts} contacts, {report.sample.from} to {report.sample.to}.</p>
      <div className="stats">{[['Contacts approved', pct(report.contacts.approved)], ['Need review', pct(report.contacts.needs_review)],
        ['Rejected', pct(report.contacts.rejected)], ['Messages approved as written', pct(report.messages.approved_unedited)],
        ['Messages you edited', pct(report.messages.edited)], ['Active rules', report.rules.active]].map(([l, v]) => <div key={l}><strong>{v}</strong><span>{l}</span></div>)}</div>
      <div className="compare-scroll"><table className="compare"><thead><tr><th>Source</th><th>Contacts</th><th>Approved</th><th>Needs review</th><th>Rejected</th><th>You corrected</th></tr></thead>
        <tbody>{report.contacts.by_source.map(r => <tr key={r.source}><td>{r.source}</td><td>{r.total}</td><td>{pct(r.approved)}</td><td>{pct(r.needs_review)}</td><td>{pct(r.rejected)}</td><td>{pct(r.corrected_by_you)}</td></tr>)}</tbody></table></div>
      {report.contacts.top_rejection_reasons.length > 0 && <><h4>Most common rejection reasons</h4><ul>{report.contacts.top_rejection_reasons.map(r => <li key={r.reason}>{r.reason} ({r.count})</li>)}</ul></>}
      {report.features.by_feature.length > 0 && <p>Checks you corrected: {report.features.by_feature.map(f => `${f.feature.replaceAll('_', ' ')} (${f.corrections})`).join(', ')}.</p>}
      {report.weekly.length > 0 && <details><summary>Week by week</summary><ul>{report.weekly.map(w => <li key={w.week}>{w.week}: {Object.entries(w).filter(([k]) => k !== 'week').map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`).join(', ')}</li>)}</ul></details>}
      <button className="secondary" onClick={download}>Download report CSV</button>
    </>}
    {rules && <section className="rules"><h4>Rules learned from your corrections</h4>
      <p className="hint">{rules.note}</p>
      {rules.proposals.map(p => <div key={p.kind + p.value} className="rule-proposal"><strong>Proposed:</strong> {p.description}
        <small>Would change {p.preview.contacts_changed ?? p.preview.features_changed} current result(s){p.preview.examples?.length ? `, e.g. ${p.preview.examples.slice(0, 3).join(', ')}` : ''}.
          Based on: {p.evidence.map(e => e.value || e.business).slice(0, 4).join(', ')}.</small>
        <button className="secondary" disabled={busy} onClick={() => approve(p)}>Approve rule</button></div>)}
      {!rules.proposals.length && <p className="lead-muted">No rule proposed yet: rules need {rules.minimum} or more corrections of the same kind.</p>}
      {rules.rules.length > 0 && <ul>{rules.rules.map(r => <li key={r.id}><span className={`chip chip-${r.status === 'active' ? 'good' : 'neutral'}`}>{r.status === 'active' ? 'Active' : 'Off'}</span> {r.description}
        <small> approved {r.approved_at.slice(0, 10)}</small> <button className="text-button" disabled={busy} onClick={() => toggle(r)}>{r.status === 'active' ? 'Switch off' : 'Switch on'}</button></li>)}</ul>}
    </section>}
  </details>;
}

const CONSENT_KEY = 'leaddesk.mapDataConsent';
const readConsent = () => { try { return localStorage.getItem(CONSENT_KEY) === 'yes'; } catch { return false; } };

export default function ProspectingPanel({ api, active, onOpenResearch }) {
  const [offer, setOffer] = useState(''), [website, setWebsite] = useState(''), [profile, setProfile] = useState(null);
  const [categories, setCategories] = useState([]), [selected, setSelected] = useState([]), [maxTypes, setMaxTypes] = useState(12);
  const [location, setLocation] = useState(''), [keyword, setKeyword] = useState(''), [limit, setLimit] = useState(100);
  const [consent, setConsent] = useState(readConsent), [useOverture, setUseOverture] = useState(true), [showTypes, setShowTypes] = useState(false);
  const [search, setSearch] = useState(null), [history, setHistory] = useState(null);
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  const request = useRef(null), profiled = useRef('');

  useEffect(() => {
    if (!active) return;
    api('/v1/prospecting/categories').then(value => { setCategories(value.items); setMaxTypes(value.max_selected); }).catch(e => setError(e.message));
    api('/v1/prospecting/searches').then(setHistory).catch(e => setError(e.message));
  }, [api, active]);

  async function run(label, action) {
    if (busy) return;
    setBusy(label); setError('');
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(''); }
  }
  const byId = Object.fromEntries(categories.map(c => [c.id, c]));
  const readProduct = async () => {
    const text = offer.trim();
    if (text.length < 3 || profiled.current === text + website) return;
    profiled.current = text + website;
    try {
      const value = await api('/v1/prospecting/profile', { method: 'POST', body: JSON.stringify({ offer: text, website: website.trim() || null }) });
      setProfile(value);
      setSelected(list => list.length ? list : value.suggested_categories.slice(0, maxTypes));
    } catch (e) { setError(e.message); }
  };
  const remember = value => { setConsent(value); try { localStorage.setItem(CONSENT_KEY, value ? 'yes' : 'no'); } catch { /* storage unavailable */ } };
  const find = event => { event.preventDefault(); run(useOverture ? 'Searching map data. The first search in a new area downloads Overture data (about 30–60 s); later searches there are instant…'
    : 'Searching OpenStreetMap. Busy public servers can take up to three minutes…', async () => {
    const payload = { offer, location, categories: selected, name_keyword: keyword.trim() || null, limit: Number(limit), use_public_osm: consent, use_overture: consent && useOverture };
    const signature = JSON.stringify(payload);
    if (request.current?.signature !== signature) request.current = { signature, key: key() };
    const value = await api('/v1/prospecting/searches', { method: 'POST', headers: { 'Idempotency-Key': request.current.key }, body: signature });
    request.current = null; setSearch(value);
    setHistory(await api('/v1/prospecting/searches'));
  }); };
  const reload = async () => setSearch(await api(`/v1/prospecting/searches/${search.id}`));
  const [chrome, setChromeState] = useState(() => { try { return localStorage.getItem('leaddesk.chromeReading') === 'yes'; } catch { return false; } });
  const setChrome = value => { setChromeState(value); try { localStorage.setItem('leaddesk.chromeReading', value ? 'yes' : 'no'); } catch { /* unavailable */ } };
  const [browser, setBrowser] = useState(null);
  useEffect(() => { if (active) api('/v1/prospecting/browser/status').then(setBrowser).catch(() => setBrowser(null)); }, [api, active]);
  // The mailbox check is part of the contact review: on unless you turned it off on this computer.
  const [mailboxes, setMailboxesState] = useState(() => { try { return localStorage.getItem('leaddesk.mailboxChecks') !== 'no'; } catch { return true; } });
  const setMailboxes = value => { setMailboxesState(value); try { localStorage.setItem('leaddesk.mailboxChecks', value ? 'yes' : 'no'); } catch { /* unavailable */ } };
  const handlers = {
    onCheck: (item, url, typed = false) => run(`Reading ${item.name}'s website${chrome ? ' in Chrome (phone and desktop)' : ''}…`, async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/check`, { method: 'POST', headers: { 'Idempotency-Key': key() },
        body: JSON.stringify(url ? { url, user_supplied: typed, render: chrome } : { render: chrome }) });
      await reload();
    }),
    onOfferPack: features => run('Saving what you deliver…', async () => {
      setSearch(await api(`/v1/prospecting/searches/${search.id}/offer-pack`, { method: 'POST', body: JSON.stringify({ features }) }));
    }),
    onFeedback: (item, url, verdict) => run('Saving your answer…', async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/web-feedback`, { method: 'POST', body: JSON.stringify({ url, verdict }) });
      await reload();
    }),
    onEnrich: item => run(`Searching the web for ${item.name}: its type and city, contact details, Facebook and Instagram. It opens up to 5 result pages, so this can take a minute or two…`, async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/enrich`, { method: 'POST' });
      await reload();
    }),
    onAnalyse: item => run(`Your local AI model is rewording the message for ${item.name}. On a laptop CPU this can take a minute…`, async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/analyse`, { method: 'POST' });
      await reload();
    }),
    onCorrect: (item, contact, verdict, reason) => run('Saving your correction…', async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/contact-correction`, { method: 'POST',
        body: JSON.stringify({ type: contact.type, value: contact.value, verdict, ...(reason ? { reason } : {}) }) });
      await reload();
    }),
    onOverride: (item, feature, state, note) => run('Saving your correction and rebuilding the pitch…', async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/feature-override`, { method: 'POST', body: JSON.stringify({ feature, state, note: note || '' }) });
      await reload();
    }),
    onMessage: (item, action, problem = null, text = null) => run('Saving your message review…', async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/message-review`, { method: 'POST', body: JSON.stringify({ action, problem, text }) });
      await reload();
    }),
    onVerify: item => run(`Verifying ${item.name}'s contacts: reading their website${mailboxes ? ' and asking mail servers' : ''}…`, async () => {
      await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/verify`, { method: 'POST', body: JSON.stringify({ check_mailboxes: mailboxes }) });
      await reload();
    }),
    onCompare: item => run(`Reading competitors' websites near ${item.name}. This can take a minute…`, async () => {
      const value = await api(`/v1/prospecting/searches/${search.id}/candidates/${item.id}/compare`, { method: 'POST', body: JSON.stringify({ limit: 3, render: chrome }) });
      await reload();
      const failed = value.steps.filter(s => s.status === 'failed');
      if (failed.length) setError(`Could not read: ${failed.map(f => `${f.name} (${f.message})`).join('; ')}`);
    }),
    mailboxes, setMailboxes, onOpenResearch, api, chrome, setChrome, browser,
  };
  const verifyTop = () => run(`Verifying contacts for the top 10${mailboxes ? ', including mail-server checks' : ''}. Reading websites can take a few minutes…`, async () => {
    await api(`/v1/prospecting/searches/${search.id}/verify`, { method: 'POST', body: JSON.stringify({ limit: 10, check_mailboxes: mailboxes }) });
    await reload();
  });
  const enrichTop = () => run('Finding contacts online for the top 10. This can take up to a minute per business…', async () => {
    await api(`/v1/prospecting/searches/${search.id}/enrich`, { method: 'POST', body: JSON.stringify({ limit: 10 }) });
    await reload();
  });
  const analyseTop = () => run('Your local AI model is rewording the top 5 messages one by one. This can take several minutes on a laptop…', async () => {
    const value = await api(`/v1/prospecting/searches/${search.id}/analyse`, { method: 'POST', body: JSON.stringify({ limit: 5 }) });
    await reload();
    if (value.failed.length) setError(`AI could not analyse: ${value.failed.map(f => `${f.name} (${f.message})`).join('; ')}`);
  });
  const [market, setMarket] = useState(null);
  useEffect(() => { if (active && search) api(`/v1/prospecting/searches/${search.id}/market`).then(setMarket).catch(() => setMarket(null)); }, [api, active, search]);
  const researchTop = () => run('Researching the top 3: find contacts online → read their website → AI analysis. This can take several minutes…', async () => {
    const value = await api(`/v1/prospecting/searches/${search.id}/research`, { method: 'POST', body: JSON.stringify({ limit: 3, render: chrome }) });
    await reload();
    const failed = value.items.flatMap(i => i.steps.filter(s => s.status === 'failed').map(s => `${i.name}: ${s.step.replace('_', ' ')} (${s.message})`));
    const notices = [...(value.warnings || [])];
    if (!value.researched) notices.push('No further research ran. Use the buttons on each business to redo a step.');
    if (failed.length) notices.push(`Some steps failed: ${failed.join('; ')}`);
    if (notices.length) setError(notices.join(' '));
  });
  const marketAI = () => run('AI is looking for problems shared by several businesses…', async () => {
    await api(`/v1/prospecting/searches/${search.id}/market`, { method: 'POST' });
    setMarket(await api(`/v1/prospecting/searches/${search.id}/market`));
  });
  const [ai, setAi] = useState(null);
  useEffect(() => { if (active) api('/v1/ai/status').then(setAi).catch(() => setAi(null)); }, [api, active, search?.id]);
  const [web, setWeb] = useState(null);
  useEffect(() => { if (active && search) api('/v1/prospecting/web-search/status').then(setWeb).catch(() => setWeb(null)); }, [api, active, search?.id]);
  const refreshConnections = () => run('Checking Ollama and web search…', async () => {
    setAi(null); setWeb(null);
    const results = await Promise.allSettled([api('/v1/ai/status'), api('/v1/prospecting/web-search/status')]);
    if (results[0].status === 'fulfilled') setAi(results[0].value);
    if (results[1].status === 'fulfilled') setWeb(results[1].value);
    const failures = results.filter(r => r.status === 'rejected').map(r => r.reason.message);
    if (failures.length) setError(failures.join(' '));
  });
  const ready = consent && offer.trim() && location.trim() && (selected.length || keyword.trim());

  return <section className="prospecting-panel">
    <form className="finder" onSubmit={find}>
      <div className="finder-grid">
        <div className="field field-offer"><label htmlFor="prospect-offer">What do you sell?</label>
          <input id="prospect-offer" maxLength={2000} required value={offer} placeholder="e.g. Modern websites for real estate agencies"
            onChange={e => setOffer(e.target.value)} onBlur={readProduct}/></div>
        <div className="field field-where"><label htmlFor="prospect-location">Where?</label>
          <input id="prospect-location" required maxLength={200} value={location} placeholder="City or area, anywhere in the world" onChange={e => setLocation(e.target.value)}/></div>
        <div className="field field-types"><label id="types-label">Business types</label>
          <button type="button" className="types-button" aria-labelledby="types-label" aria-expanded={showTypes} onClick={() => setShowTypes(v => !v)}>
            {selected.length ? `${selected.length} chosen` : 'Choose types'}<span aria-hidden="true">▾</span></button></div>
        <button className="primary finder-go" disabled={!!busy || !ready}>Find businesses</button>
      </div>
      {selected.length > 0 && <div className="chips">{selected.map(id => <button type="button" key={id} className="chip-remove"
        onClick={() => setSelected(list => list.filter(x => x !== id))} title="Remove">{byId[id]?.label || id} <span aria-hidden="true">×</span></button>)}</div>}
      {profile?.suggestion_reasons?.length > 0 && <p className="hint">Suggested from your product: {profile.suggestion_reasons.join('; ')}.
        {profile.offer_kind === 'web_presence' ? ' Website product: businesses with no or weak websites score higher.' : ''}</p>}
      {showTypes && <div className="types-panel"><CategoryPicker api={api} categories={categories} max={maxTypes} selected={selected} setSelected={setSelected} onError={setError}/>
        <button type="button" className="secondary" onClick={() => setShowTypes(false)}>Done</button></div>}
      <details className="finder-more"><summary>More options</summary>
        <div className="finder-options">
          <div className="field"><label htmlFor="prospect-website">Your website (optional, improves suggestions)</label>
            <input id="prospect-website" value={website} placeholder="https://your-site.com" onChange={e => setWebsite(e.target.value)} onBlur={readProduct}/></div>
          <div className="field"><label htmlFor="prospect-keyword">Name contains</label>
            <input id="prospect-keyword" maxLength={40} value={keyword} placeholder="e.g. properties" onChange={e => setKeyword(e.target.value)}/></div>
          <div className="field"><label htmlFor="prospect-limit">Maximum businesses</label>
            <input id="prospect-limit" type="number" min={1} max={300} value={limit} onChange={e => setLimit(e.target.value)}/></div>
        </div>
      </details>
      <div className="consent">
        <label className="check"><input type="checkbox" checked={consent} onChange={e => remember(e.target.checked)}/>
          <span>Search public map data. Free, no account. Your location text and business types go to OpenStreetMap; the map area is read from Overture Maps on Amazon S3. Remembered on this computer.</span></label>
        <label className="check"><input type="checkbox" checked={useOverture} onChange={e => setUseOverture(e.target.checked)}/>
          <span>Include Overture Maps (recommended: millions more businesses with phones, emails and websites)</span></label>
      </div>
    </form>

    <AnalyseWebsite api={api} offer={offer} location={location} busy={!!busy} run={run} aiReady={!!ai?.ready} chrome={chrome} setChrome={setChrome}
      browser={browser} onOpenResearch={onOpenResearch} setError={setError}/>

    {busy && <p role="status" className="notice">{busy}</p>}
    {error && <p role="alert" className="alert">{error}</p>}

    {search && <Results search={search} busy={!!busy} aiReady={!!ai?.ready} web={web} ai={ai} market={market} onRefresh={refreshConnections}
      onResearch={researchTop} onEnrichTop={enrichTop} onAnalyseTop={analyseTop} onMarketAI={marketAI} onVerifyTop={verifyTop}
      onProvider={provider => run('Switching web search…', async () => setWeb(await api('/v1/prospecting/web-search/provider', { method: 'POST', body: JSON.stringify({ provider }) })))}
      handlers={handlers}/>}

    {!search && <section className="empty-start"><h2>Find businesses that need what you sell</h2>
      <ol><li><strong>Describe your product.</strong> LeadDesk suggests which businesses buy it.</li>
        <li><strong>Pick a place</strong> anywhere in the world.</li>
        <li><strong>Get a ranked list</strong> with phones, emails, website problems and an opening line for each.</li></ol></section>}

    <QualityPanel api={api} busy={!!busy} run={run}/>

    <details className="history"><summary>Saved searches ({history?.total ?? 0})</summary>
      {!history?.items.length && <p className="hint">No searches yet.</p>}
      {history?.items.map(item => <div className="history-row" key={item.id}>
        <span><strong>{item.location}</strong> · {item.count} businesses · {new Date(item.created_at).toLocaleString()}<small>{item.offer}</small></span>
        <button className="secondary" disabled={!!busy} onClick={() => run('Opening search…', async () => setSearch(await api(`/v1/prospecting/searches/${item.id}`)))}>Open</button>
        <button className="text-button" disabled={!!busy} onClick={() => run('Deleting search…', async () => {
          await api(`/v1/prospecting/searches/${item.id}`, { method: 'DELETE' });
          if (search?.id === item.id) setSearch(null);
          setHistory(await api('/v1/prospecting/searches'));
        })}>Delete</button></div>)}
    </details>
  </section>;
}
