import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ScreenSession } from './screen-session.js';
import './ScreenPanel.css';

export default function ScreenPanel({ api, active, onOpenFiles }) {
  const [capture, setCapture] = useState({ status: 'idle' });
  const [text, setText] = useState(''); const [source, setSource] = useState('');
  const [action, setAction] = useState('search_files'); const [query, setQuery] = useState('');
  const [scope, setScope] = useState(''); const [roots, setRoots] = useState([]); const [rootId, setRootId] = useState('');
  const [plan, setPlan] = useState(null); const [result, setResult] = useState(null); const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const epoch = useRef(0), abort = useRef(null), request = useRef(null);
  const session = useMemo(() => new ScreenSession({ onChange: setCapture }), []);
  const capturing = ['permission', 'capturing'].includes(capture.status);
  const disabled = capturing || !!busy;

  function invalidate() { epoch.current++; abort.current?.abort(); setBusy(''); setPlan(null); setResult(null); setPreview(null); setError(''); setNotice(''); }
  function clear() { session.cancel(); invalidate(); setText(''); setSource(''); setQuery(''); request.current = null; }
  useEffect(() => {
    if (!active) { clear(); return; }
    let current = true;
    api('/v1/files/roots').then(value => { if (current) { setRoots(value.items); setRootId(id => value.items.some(root => root.id === id) ? id : ''); } })
      .catch(e => { if (current) setError(e.message); });
    // The browser chooser may take focus or hide this tab. Pending selection
    // remains cancellable and bounded; navigation/page exit always cancels it.
    const hidden = () => { if (document.hidden && !session.busy) clear(); };
    const exit = () => clear();
    document.addEventListener('visibilitychange', hidden); window.addEventListener('pagehide', exit);
    return () => { current = false; document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', exit); };
  }, [active, api, session]);
  useEffect(() => {
    if (capture.status !== 'review') return;
    const timer = setTimeout(clear, 5 * 60 * 1000);
    return () => clearTimeout(timer);
  }, [capture]);
  useEffect(() => () => { session.dispose(); epoch.current++; abort.current?.abort(); }, [session]);

  function change(setter, value) { invalidate(); setter(value); }
  function payload() {
    return { context: { text, source, frame: capture.status === 'review' ? capture.frame : null }, action,
      query: action === 'save_note' ? null : query, root_id: action === 'search_files' ? rootId || null : null,
      scope: action === 'search_files' ? null : scope || null };
  }
  async function run(kind, fileId) {
    if (disabled) return;
    const current = ++epoch.current, controller = new AbortController(); abort.current = controller;
    setBusy(kind); setError(''); setNotice(''); setPreview(null);
    try {
      let value;
      if (kind === 'preview') {
        value = await api(`/v1/files/${fileId}/preview`, { signal: controller.signal });
        if (current === epoch.current) setPreview(value);
      } else {
        const body = payload();
        if (kind === 'prepare') { setPlan(null); setResult(null); }
        else {
          body.expected_plan_hash = plan.plan_hash;
          if (request.current?.hash !== plan.plan_hash) request.current = { hash: plan.plan_hash, key: crypto.randomUUID() };
        }
        value = await api(`/v1/screen/commands/${kind}`, { method: 'POST', body: JSON.stringify(body),
          headers: kind === 'execute' ? { 'Idempotency-Key': request.current.key } : {}, signal: controller.signal });
        if (current === epoch.current) {
          if (kind === 'prepare') setPlan(value);
          else { setResult(value); setNotice(value.summary); }
        }
      }
    } catch (e) { if (current === epoch.current && e.name !== 'AbortError') setError(e.message); }
    finally { if (current === epoch.current) setBusy(''); }
  }
  const canPrepare = text.trim() && source.trim() && (action === 'search_files' ? rootId && query.trim() : scope.trim() && (action === 'save_note' || query.trim()));
  return <div className="screen-panel">
    <section className="panel" aria-labelledby="screen-heading"><h2 id="screen-heading">On-demand screen context</h2>
      <p>Choose a window, tab or screen in your browser’s chooser. Sharing stops after one still. The preview stays in this tab until discarded, hidden, left or five minutes pass.</p>
      <p>Type or paste the relevant text and label its source. Text entry also works without capture. Automatic text recognition and image analysis are unavailable.</p>
      <div className="screen-actions"><button className="primary" disabled={disabled} onClick={() => { clear(); session.capture(); }}>Choose screen or window</button>
        <button className="secondary" disabled={busy === 'execute' && plan?.risk === 'writes_memory'} onClick={clear}>Discard screen context</button></div>
      <p role="status">{capture.status === 'permission' ? 'Waiting for screen selection. Cancel here to ignore a late permission response.'
        : capture.status === 'capturing' ? 'Screen sharing on. Capturing one still…'
          : capture.status === 'review' ? 'Screen sharing off. Review your temporary preview.' : 'Screen sharing off.'}</p>
      {capture.error && <p role="alert" className="alert">{capture.error}</p>}
      {capture.status === 'review' && <figure><img src={capture.dataUrl} alt="Temporary preview of your selected surface"/>
        <figcaption>{capture.frame.surface} · {new Date(capture.frame.captured_at).toLocaleString()} · Full selected surface, {capture.frame.width} × {capture.frame.height} pixels. Preview may be resized.</figcaption></figure>}
      <label htmlFor="screen-source">Context source label</label><input id="screen-source" maxLength={160} disabled={disabled} value={source} placeholder="e.g. Editor — project error dialog" onChange={e => change(setSource, e.target.value)}/>
      <label htmlFor="screen-text">Reviewed context text</label><textarea id="screen-text" maxLength={4000} disabled={disabled} value={text} onChange={e => change(setText, e.target.value)}/>
      <p className="muted">Review and remove private details before preparing an action. Only this text and its source details reach your local workspace. A note is saved only when you choose Save reviewed context.</p>
    </section>
    {error && <p role="alert" className="alert">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel"><h2>Choose a local action</h2>
      <label htmlFor="screen-action">Context action</label><select id="screen-action" disabled={disabled} value={action} onChange={e => change(setAction, e.target.value)}>
        <option value="search_files">Search approved files</option><option value="search_memories">Search scoped memory</option><option value="save_note">Save context as a scoped note</option></select>
      {action === 'search_files' ? <><label htmlFor="screen-folder">Approved folder for context action</label><select id="screen-folder" disabled={disabled} value={rootId} onChange={e => change(setRootId, e.target.value)}>
        <option value="">Choose an approved folder</option>{roots.map(root => <option key={root.id} value={root.id}>{root.path}</option>)}</select>
        <button className="text-button" disabled={disabled} onClick={onOpenFiles}>Manage approved folders</button></>
        : <><label htmlFor="screen-scope">Memory scope for context action</label><input id="screen-scope" maxLength={120} disabled={disabled} value={scope} onChange={e => change(setScope, e.target.value)}/></>}
      {action !== 'save_note' && <><label htmlFor="screen-query">Search keywords from context</label><input id="screen-query" maxLength={200} disabled={disabled} value={query} onChange={e => change(setQuery, e.target.value)}/></>}
      <button className="primary" disabled={disabled || !canPrepare} onClick={() => run('prepare')}>Prepare context action</button>
      {busy && <p role="status">{busy === 'prepare' ? 'Preparing action for review…' : busy === 'preview' ? 'Checking the current file…' : 'Applying your reviewed action…'}</p>}
      {plan && <section className="screen-plan"><h3>Context action to review</h3><p>{plan.summary}</p>
        <p>Source label: {plan.context.source}. Text supplied and reviewed by you.</p><blockquote>{plan.context.text}</blockquote>
        {plan.context.frame && <p>Client-reported capture: {plan.context.frame.captured_at} · {plan.context.frame.surface} · Full surface {plan.context.frame.width} × {plan.context.frame.height}.</p>}
        <p>{plan.risk === 'writes_memory' ? 'Saves the text and source details as an editable private note. The preview image is excluded.' : 'Reads only from the selected local scope.'}</p>
        <button className="primary" disabled={disabled} onClick={() => run('execute')}>{plan.risk === 'writes_memory' ? 'Save reviewed context' : 'Run reviewed context search'}</button>
      </section>}
    </section>
    {result && <section className="panel screen-result"><h2>Context action result</h2><p>{result.summary}</p>
      {result.kind === 'search_files' && <><p>{result.result.coverage}</p>{result.result.stale_omitted > 0 && <p>{result.result.stale_omitted} stale matches omitted. Reconcile the folder in Files and memory.</p>}
        {result.result.items.map(item => <article key={item.id}><h3>{item.name}</h3><p>{item.path}</p><blockquote>{item.excerpt || 'No text preview available.'}</blockquote>
          <button className="secondary" disabled={disabled || item.status !== 'indexed'} onClick={() => run('preview', item.id)}>Preview current file</button></article>)}</>}
      {result.kind === 'search_memories' && result.result.items.map(note => <article key={note.id}><p>{note.content}</p><small>Scope: {note.scope} · Source: {note.source}</small></article>)}
      {result.kind === 'save_note' && <><blockquote>{result.result.content}</blockquote><p>Source: {result.result.source}</p><button className="secondary" disabled={disabled} onClick={onOpenFiles}>Edit or delete saved context</button></>}
      {result.result.items?.length === 0 && <p>No current matches. Try different keywords or check the selected scope.</p>}
      {preview && <section className="screen-preview"><h3>Current file: {preview.name}</h3><p>{preview.path}</p><pre>{preview.text}</pre>
        {preview.truncated && <p>Preview limited to 16,000 characters.</p>}<button className="secondary" onClick={() => setPreview(null)}>Close current file preview</button></section>}
    </section>}
  </div>;
}
