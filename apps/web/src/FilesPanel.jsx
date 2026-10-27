import React, { useEffect, useRef, useState } from 'react';
import './FilesPanel.css';

const blankNote = { kind: 'project_context', content: '', source: '', pinned: false, expires_at: '' };
const json = (method, body) => ({ method, body: JSON.stringify(body) });

function MemoryPanel({ api }) {
  const [scope, setScope] = useState('');
  const [loadedScope, setLoadedScope] = useState('');
  const [notes, setNotes] = useState(null);
  const [draft, setDraft] = useState(blankNote);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [forgetting, setForgetting] = useState(false);
  const request = useRef(null);
  const scopeQuery = value => `scope=${encodeURIComponent(value)}`;
  async function run(action) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function reload(value = loadedScope, offset = 0) {
    const response = await api(`/v1/memories?${scopeQuery(value)}&include_expired=true&offset=${offset}`);
    setNotes(response); setLoadedScope(value); setForgetting(false);
  }
  function reset() { setDraft(blankNote); setEditing(null); request.current = null; }
  async function save(event) {
    event.preventDefault();
    await run(async () => {
      const payload = { ...draft, scope: loadedScope, expires_at: draft.expires_at ? new Date(draft.expires_at).toISOString() : null };
      if (editing) {
        await api(`/v1/memories/${editing.id}`, json('PATCH', { ...payload, expected_revision: editing.revision }));
      } else {
        const signature = JSON.stringify(payload);
        if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
        await api('/v1/memories', { ...json('POST', payload), headers: { 'Idempotency-Key': request.current.key } });
      }
      reset(); await reload(); setNotice('Scoped memory saved.');
    });
  }
  function edit(note) {
    setEditing(note); setNotice(''); setError('');
    const date = note.expires_at ? new Date(note.expires_at) : null;
    const localDate = date ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '';
    setDraft({ kind: note.kind, content: note.content, source: note.source, pinned: note.pinned, expires_at: localDate });
  }
  return <section className="panel local-memory" aria-labelledby="memory-heading">
    <h2 id="memory-heading">Scoped memory</h2>
    <p>Save your own project context and preferences. Each scope is separate; expired notes are excluded from retrieval. Notes remain local and are excluded from training.</p>
    <form onSubmit={e => { e.preventDefault(); run(async () => { await reload(scope.trim()); reset(); }); }}>
      <label htmlFor="memory-scope">Memory scope</label><input id="memory-scope" required maxLength={120} value={scope} disabled={busy} placeholder="e.g. clinic-project" onChange={e => setScope(e.target.value)}/>
      <button className="secondary" disabled={busy || !scope.trim()} type="submit">Load memory scope</button>
    </form>
    {error && <p role="alert" className="alert">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    {notes && <><p>Loaded scope: <strong>{loadedScope}</strong> · Showing {notes.items.length} of {notes.total} notes.</p>
      <div className="local-actions"><button className="secondary" disabled={busy} onClick={() => run(() => reload())}>Refresh scoped notes</button>
        <button className="secondary" disabled={busy} onClick={() => run(async () => {
          const blob = await api(`/v1/memories/export?${scopeQuery(loadedScope)}`, { download: true });
          const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'leaddesk-memories.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        })}>Export scoped notes</button>
        <button className="secondary" disabled={busy} onClick={() => setForgetting(true)}>Forget this scope</button></div>
      {forgetting && <div className="local-confirm"><p>Delete every note in “{loadedScope}”, including expired notes?</p>
        <button className="secondary" disabled={busy} onClick={() => run(async () => { await api(`/v1/memories/scope?${scopeQuery(loadedScope)}`, { method: 'DELETE' }); reset(); await reload(); setNotice('All notes in this scope deleted.'); })}>Delete all scoped notes</button>
        <button className="text-button" disabled={busy} onClick={() => setForgetting(false)}>Keep scoped notes</button></div>}
      <form onSubmit={save}>
        <h3>{editing ? `Edit note · Revision ${editing.revision}` : 'Add a scoped note'}</h3>
        <label htmlFor="memory-kind">Memory type</label><select id="memory-kind" disabled={busy} value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })}>{['preference', 'file_alias', 'project_context', 'product_fact', 'correction'].map(kind => <option key={kind} value={kind}>{kind.replaceAll('_', ' ')}</option>)}</select>
        <label htmlFor="memory-content">Memory content</label><textarea id="memory-content" required maxLength={4000} disabled={busy} value={draft.content} onChange={e => setDraft({ ...draft, content: e.target.value })}/>
        <label htmlFor="memory-source">Source or reason</label><input id="memory-source" maxLength={500} disabled={busy} value={draft.source} onChange={e => setDraft({ ...draft, source: e.target.value })}/>
        <label htmlFor="memory-expiry">Expiry (local time, optional)</label><input id="memory-expiry" type="datetime-local" disabled={busy} value={draft.expires_at} onChange={e => setDraft({ ...draft, expires_at: e.target.value })}/>
        <label className="local-check"><input type="checkbox" disabled={busy} checked={draft.pinned} onChange={e => setDraft({ ...draft, pinned: e.target.checked })}/>Pin this note</label>
        <div className="local-actions"><button className="primary" disabled={busy || !draft.content.trim()} type="submit">Save scoped memory</button>
          <button className="secondary" disabled={busy} type="button" onClick={reset}>Discard note edits</button></div>
      </form>
      <div className="memory-list">{notes.items.map(note => <article key={note.id} className="memory-note"><strong>{note.kind.replaceAll('_', ' ')}{note.pinned ? ' · Pinned' : ''}{note.expired ? ' · Expired' : ''}</strong>
        <p>{note.content}</p>{note.source && <small>Source: {note.source}</small>}<small>Revision {note.revision} · Updated {new Date(note.updated_at).toLocaleString()}{note.expires_at && ` · Expires ${new Date(note.expires_at).toLocaleString()}`}</small>
        <div className="local-actions"><button className="secondary" disabled={busy} onClick={() => edit(note)}>Edit note</button>
          <button className="text-button" disabled={busy} onClick={() => run(async () => { await api(`/v1/memories/${note.id}`, { method: 'DELETE' }); if (editing?.id === note.id) reset(); await reload(); setNotice('Note deleted.'); })}>Delete note</button></div>
      </article>)}</div>{notes.total === 0 && <p>No notes saved in this scope.</p>}
      <div className="local-actions"><button className="secondary" disabled={busy || notes.offset === 0} onClick={() => run(() => reload(loadedScope, Math.max(0, notes.offset - notes.limit)))}>Previous scoped notes</button>
        <button className="secondary" disabled={busy || notes.next_offset === null} onClick={() => run(() => reload(loadedScope, notes.next_offset))}>Next scoped notes</button></div></>}
  </section>;
}

export default function FilesPanel({ api, active }) {
  const [roots, setRoots] = useState([]);
  const [rootId, setRootId] = useState('');
  const [path, setPath] = useState('');
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [preview, setPreview] = useState(null);
  const [correctionQuery, setCorrectionQuery] = useState('');
  const [comment, setComment] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const root = roots.find(value => value.id === rootId);
  async function refresh() { setResult(null); setPreview(null); const response = await api('/v1/files/roots'); setRoots(response.items); setRootId(value => response.items.some(item => item.id === value) ? value : ''); }
  useEffect(() => {
    if (!active) return;
    setResult(null); setPreview(null);
    let current = true;
    api('/v1/files/roots').then(response => { if (current) setRoots(response.items); }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [active, api]);
  async function run(action) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function search(value = query, id = rootId) {
    setPreview(null); setResult(null);
    const response = await api('/v1/files/search', json('POST', { root_id: id, query: value }));
    setResult(response); setCorrectionQuery(response.query);
  }
  async function correct(item, decision) {
    await api('/v1/files/corrections', json('POST', { root_id: rootId, query: decision === 'wrong' ? result.query : correctionQuery,
      file_id: item.id, sha256: item.sha256, decision, comment }));
    const followup = decision === 'wrong' ? result.query : correctionQuery;
    setQuery(followup); await search(followup); setNotice('File correction saved for this query and folder.');
  }
  return <div className="files-panel">
    <section className="panel"><h2>Approved folders</h2>
      <p>Approve a dedicated project folder to index its filenames and UTF-8 text. Hidden items, dependency folders and symlinks are skipped. Folder approval does not start a scan.</p>
      <form onSubmit={e => { e.preventDefault(); run(async () => { const approved = await api('/v1/files/roots', json('POST', { path })); await refresh(); setRootId(approved.id); setResult(null); setPreview(null); setRevoking(false); setPath(''); setNotice('Folder approved. Choose Reconcile folder to index it.'); }); }}>
        <label htmlFor="approved-path">Folder path to approve</label><input id="approved-path" required maxLength={2000} placeholder="/home/you/Documents/project" value={path} disabled={busy} onChange={e => setPath(e.target.value)}/>
        <button className="primary" disabled={busy} type="submit">Approve folder</button></form>
      {roots.length === 0 && <p>No folders approved. Your files have not been indexed.</p>}
      <label htmlFor="approved-root">Search folder</label><select id="approved-root" disabled={busy} value={rootId} onChange={e => { setRootId(e.target.value); setResult(null); setPreview(null); setRevoking(false); setNotice(''); }}><option value="">Choose an approved folder</option>{roots.map(item => <option value={item.id} key={item.id}>{item.path}</option>)}</select>
      {root && <><p className="local-path">{root.path}</p><p>Last reconciliation: {root.scanned_at ? new Date(root.scanned_at).toLocaleString() : 'Not indexed'}</p>
        {root.report && <p>{root.report.partial ? 'Partial coverage' : 'Bounded scan completed'} · {root.report.entries_seen} entries inspected · {root.report.errors} read errors · {Object.entries(root.statuses).map(([name, count]) => `${count} ${name.replaceAll('_', ' ')}`).join(' · ')}</p>}
        <p className="muted">Each scan allows 500 entries, 1 MiB per text file, 8 MiB total and five seconds between file operations. PDFs and office documents are listed by filename with an unsupported status.</p>
        <div className="local-actions"><button className="secondary" disabled={busy} onClick={() => run(async () => { setResult(null); setPreview(null); const report = await api(`/v1/files/roots/${rootId}/reconcile`, { method: 'POST' }); await refresh(); setNotice(report.partial ? 'Reconciled with partial coverage. Review the indexing status.' : 'Folder reconciled. Search the current snapshot.'); })}>Reconcile folder</button>
          <button className="secondary" disabled={busy} onClick={() => setRevoking(true)}>Revoke folder approval</button></div>
        {revoking && <div className="local-confirm"><p>Remove this folder's index and file corrections? Your original files stay in place.</p><button className="secondary" disabled={busy} onClick={() => run(async () => { setResult(null); setPreview(null); await api(`/v1/files/roots/${rootId}`, { method: 'DELETE' }); setRootId(''); setRevoking(false); await refresh(); setNotice('Folder approval, indexed text and file corrections removed.'); })}>Remove folder index</button><button className="text-button" disabled={busy} onClick={() => setRevoking(false)}>Keep folder approval</button></div>}</>}
      <button className="text-button" disabled={busy} onClick={() => run(refresh)}>Refresh folder list</button>
    </section>
    {busy && <p role="status">Working with the selected local scope…</p>}{error && <div role="alert" className="alert">{error}</div>}{notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel"><h2>Find a local file</h2>
      <form onSubmit={e => { e.preventDefault(); run(() => search()); }}><label htmlFor="file-query">Filename or text keywords</label><input id="file-query" required maxLength={200} value={query} disabled={busy || !root} onChange={e => setQuery(e.target.value)}/><button className="primary" disabled={busy || !root || !query.trim()} type="submit">Search approved files</button></form>
      {result && <><p>Results for “{result.query}” · {result.coverage}</p>{result.stale_omitted > 0 && <p>{result.stale_omitted} stale matches omitted. Reconcile this folder.</p>}
        {result.items.length === 0 && <p>No current file matches. Try different keywords or reconcile the folder.</p>}
        <div className="local-matches">{result.items.map(item => <article className="file-match" key={item.id}><h3>{item.name}{item.preferred ? ' · Your preferred file' : ''}</h3><p className="local-path">{item.path}</p><small>{new Date(item.modified_ns / 1000000).toLocaleString()} · {item.size} bytes · {item.status.replaceAll('_', ' ')}</small><blockquote>{item.excerpt || 'No text preview available for this format.'}</blockquote>
          <div className="local-actions"><button className="secondary" disabled={busy || item.status !== 'indexed'} onClick={() => run(async () => { setPreview(null); setPreview(await api(`/v1/files/${item.id}/preview`)); })}>Preview file</button>
            <button className="secondary" disabled={busy} onClick={() => run(async () => { await navigator.clipboard.writeText(item.folder); setNotice('Folder path copied. Paste it into your file manager location bar.'); })}>Copy folder location</button>
            <button className="text-button" disabled={busy || !comment.trim() || item.status !== 'indexed'} onClick={() => run(() => correct(item, 'wrong'))}>Wrong file</button>
            <button className="text-button" disabled={busy || !comment.trim() || !correctionQuery.trim() || item.status !== 'indexed'} onClick={() => run(() => correct(item, 'preferred'))}>Use this file for query</button></div></article>)}</div>
        <label htmlFor="file-correction-query">Correction query</label><input id="file-correction-query" maxLength={200} disabled={busy} value={correctionQuery} onChange={e => setCorrectionQuery(e.target.value)}/><p className="muted">To correct an earlier search, find the right file, enter the earlier query here, then choose Use this file for query. Wrong file applies to the displayed results query.</p>
        <label htmlFor="file-correction-reason">Reason for file correction</label><input id="file-correction-reason" maxLength={500} disabled={busy} value={comment} onChange={e => setComment(e.target.value)}/>
        {result.corrections.length > 0 && <details><summary>Saved file corrections ({result.corrections.length})</summary>{result.corrections.map(choice => <div className="local-choice" key={choice.id}><p>{choice.decision} · {choice.relative_path} · {choice.comment}</p><button className="text-button" disabled={busy} onClick={() => run(async () => { await api(`/v1/files/corrections/${choice.id}`, { method: 'DELETE' }); await search(result.query); })}>Undo file correction</button></div>)}</details>}
      </>}
      {preview && <section className="file-preview"><h3>Text preview: {preview.name}</h3><p className="local-path">{preview.path}</p><pre>{preview.text}</pre>{preview.truncated && <p>Preview limited to the first 16,000 characters.</p>}<button className="secondary" onClick={() => setPreview(null)}>Close file preview</button></section>}
    </section>
    <MemoryPanel api={api}/>
  </div>;
}
