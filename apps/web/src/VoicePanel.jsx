import React, { useEffect, useMemo, useRef, useState } from 'react';
import { localVoices, speakLocal } from './voice-audio.js';
import { VoiceSession } from './voice-session.js';
import './VoicePanel.css';

export default function VoicePanel({ api, active, onOpenFiles }) {
  const [status, setStatus] = useState(null);
  const [roots, setRoots] = useState([]);
  const [rootId, setRootId] = useState('');
  const [scope, setScope] = useState('');
  const [language, setLanguage] = useState('auto');
  const [recording, setRecording] = useState({ status: 'idle', error: '' });
  const [transcript, setTranscript] = useState('');
  const [plan, setPlan] = useState(null);
  const [result, setResult] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [voices, setVoices] = useState([]);
  const [voiceURI, setVoiceURI] = useState('');
  const [speechEnabled, setSpeechEnabled] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const commandEpoch = useRef(0); const commandAbort = useRef(null); const request = useRef(null);
  const speechEpoch = useRef(0);
  const session = useMemo(() => new VoiceSession({ api, onChange: setRecording }), [api]);
  const capturing = ['permission', 'recording', 'transcribing'].includes(recording.status);
  const disabled = capturing || !!busy;

  function invalidate() { setPlan(null); setResult(null); setPreview(null); setError(''); }
  function stopSpeech() { speechEpoch.current++; globalThis.speechSynthesis?.cancel(); setSpeaking(false); }
  function cancel(clearText = true) {
    session.cancel(); commandEpoch.current++; commandAbort.current?.abort(); setBusy(''); stopSpeech(); invalidate();
    if (clearText) setTranscript('');
  }
  useEffect(() => {
    if (recording.status === 'review') { setTranscript(recording.transcript); invalidate(); }
  }, [recording]);
  useEffect(() => {
    const synth = globalThis.speechSynthesis;
    const refresh = () => { const items = localVoices(synth); setVoices(items); setVoiceURI(value => items.some(item => item.voiceURI === value) ? value : items[0]?.voiceURI || ''); };
    refresh(); synth?.addEventListener('voiceschanged', refresh);
    return () => { synth?.removeEventListener('voiceschanged', refresh); synth?.cancel(); };
  }, []);
  useEffect(() => {
    if (!active) { session.cancel(); commandEpoch.current++; commandAbort.current?.abort(); setBusy(''); stopSpeech(); return; }
    let current = true;
    Promise.all([api('/v1/voice/status'), api('/v1/files/roots')]).then(([value, folders]) => {
      if (current) { setStatus(value); setRoots(folders.items); setRootId(id => folders.items.some(folder => folder.id === id) ? id : ''); }
    }).catch(e => { if (current) setError(e.message); });
    const hidden = () => { if (document.hidden) session.cancel(); stopSpeech(); };
    const blur = () => { session.cancel(); stopSpeech(); };
    document.addEventListener('visibilitychange', hidden); window.addEventListener('blur', blur);
    return () => { current = false; document.removeEventListener('visibilitychange', hidden); window.removeEventListener('blur', blur); };
  }, [active, api, session]);
  useEffect(() => () => { session.dispose(); commandEpoch.current++; commandAbort.current?.abort(); }, [session]);

  async function refresh() {
    setError('');
    try { const [value, folders] = await Promise.all([api('/v1/voice/status'), api('/v1/files/roots')]); setStatus(value); setRoots(folders.items); }
    catch (e) { setError(e.message); }
  }
  function start() { if (busy || !status?.available) return; invalidate(); stopSpeech(); session.start(language); }
  async function run(kind) {
    if (disabled) return;
    const epoch = ++commandEpoch.current; const controller = new AbortController(); commandAbort.current = controller;
    setBusy(kind); setError(''); setPreview(null); stopSpeech();
    try {
      const payload = { transcript, root_id: rootId || null, scope: scope.trim() || null };
      if (kind === 'prepare') {
        setPlan(null); setResult(null);
        const value = await api('/v1/voice/commands/prepare', { method: 'POST', body: JSON.stringify(payload), signal: controller.signal });
        if (epoch === commandEpoch.current) setPlan(value);
      } else {
        if (request.current?.hash !== plan.plan_hash) request.current = { hash: plan.plan_hash, key: crypto.randomUUID() };
        const value = await api('/v1/voice/commands/execute', { method: 'POST',
          headers: { 'Idempotency-Key': request.current.key }, body: JSON.stringify({ ...payload, expected_plan_hash: plan.plan_hash }), signal: controller.signal });
        if (epoch === commandEpoch.current) setResult(value);
      }
    } catch (e) { if (epoch === commandEpoch.current && e.name !== 'AbortError') setError(e.message); }
    finally { if (epoch === commandEpoch.current) setBusy(''); }
  }
  async function previewFile(item) {
    const epoch = ++commandEpoch.current; setBusy('preview'); setPreview(null); setError('');
    try { const value = await api(`/v1/files/${item.id}/preview`); if (epoch === commandEpoch.current) setPreview(value); }
    catch (e) { if (epoch === commandEpoch.current) setError(e.message); }
    finally { if (epoch === commandEpoch.current) setBusy(''); }
  }
  return <div className="voice-panel">
    <section className="panel"><h2>Push to talk</h2><p>Hold the talk button with a pointer, Space or Enter; release to transcribe up to 30 seconds. Recording stops when you leave this panel or window. Every transcript needs your review.</p>
      <p>{status?.reason || 'Checking local speech recognition…'}</p><button className="text-button" disabled={disabled} onClick={refresh}>Refresh speech availability</button>
      <label htmlFor="voice-language">Spoken language</label><select id="voice-language" value={language} disabled={disabled} onChange={e => setLanguage(e.target.value)}><option value="auto">Automatic language detection</option><option value="en">English</option><option value="ur">Urdu</option></select>
      <p className="muted">Urdu, Roman Urdu and mixed-language recognition need testing with your recordings. You can edit the result or type a command.</p>
      <div className="voice-controls"><button className={`primary voice-talk ${recording.status === 'recording' ? 'recording' : ''}`} disabled={!status?.available || !!busy || recording.status === 'transcribing'} aria-pressed={recording.status === 'recording'}
        onPointerDown={e => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); start(); }} onPointerUp={() => session.finish()} onPointerCancel={() => session.cancel()} onLostPointerCapture={() => session.finish()}
        onKeyDown={e => { if (['Space', 'Enter'].includes(e.code)) { e.preventDefault(); if (!e.repeat) start(); } }} onKeyUp={e => { if (['Space', 'Enter'].includes(e.code)) { e.preventDefault(); session.finish(); } }} onBlur={() => { if (['permission', 'recording'].includes(session.state.status)) session.cancel(); }}>
        {recording.status === 'recording' ? 'Recording · Release to transcribe' : recording.status === 'permission' ? 'Waiting for microphone permission…' : 'Hold to talk'}</button>
        <button className="secondary" disabled={!status?.available || !!busy || recording.status === 'transcribing'} onClick={() => recording.status === 'recording' ? session.finish() : start()}>{recording.status === 'recording' ? 'Finish short recording' : 'Start short recording'}</button>
        <button className="secondary" disabled={busy === 'execute'} onClick={() => cancel()}>Cancel voice command</button></div>
      <p role="status">{recording.status === 'recording' ? 'Microphone on. Audio stays local and is not retained as a recording.' : recording.status === 'permission' ? 'Awaiting microphone permission. Release or cancel to discard.' : recording.status === 'transcribing' ? 'Microphone off. Transcribing locally…' : 'Microphone off.'}</p>
      {recording.error && <p role="alert" className="alert">{recording.error}</p>}
    </section>
    <section className="panel"><h2>Review your command</h2><p>Use <strong>find files &lt;keywords&gt;</strong>, <strong>search memory &lt;keywords&gt;</strong>, or <strong>remember &lt;note&gt;</strong>. Select the folder or memory scope below. Other actions require the existing workspace controls.</p>
      <label htmlFor="voice-transcript">Transcript or typed command</label><textarea id="voice-transcript" value={transcript} maxLength={1000} disabled={disabled} onChange={e => { setTranscript(e.target.value); invalidate(); }}/>
      <label htmlFor="voice-root">Approved folder for voice search</label><select id="voice-root" value={rootId} disabled={disabled} onChange={e => { setRootId(e.target.value); invalidate(); }}><option value="">Choose an approved folder</option>{roots.map(folder => <option value={folder.id} key={folder.id}>{folder.path}</option>)}</select>
      <label htmlFor="voice-scope">Memory scope for voice command</label><input id="voice-scope" value={scope} maxLength={120} disabled={disabled} onChange={e => { setScope(e.target.value); invalidate(); }}/>
      <div className="voice-controls"><button className="primary" disabled={disabled || !transcript.trim()} onClick={() => run('prepare')}>Prepare reviewed command</button><button className="secondary" disabled={disabled} onClick={onOpenFiles}>Open files and memory</button></div>
      {busy && <p role="status">{busy === 'execute' ? 'Applying your reviewed action… An applied note is managed in Files and memory.' : 'Preparing the selected local action…'}</p>}
      {error && <p role="alert" className="alert">{error}</p>}
      {plan && <section className="voice-plan"><h3>Action to review</h3><p>{plan.summary}</p><p>{plan.risk === 'writes_memory' ? 'Writes one user-authored note to the selected memory scope.' : 'Reads the selected local scope.'}</p>
        {plan.operation.kind === 'search_files' && <p className="voice-path">Folder: {roots.find(folder => folder.id === plan.operation.root_id)?.path || 'Approval unavailable; prepare again.'}</p>}
        <button className="primary" disabled={disabled || (result?.plan_hash === plan.plan_hash && result.kind === 'remember')} onClick={() => run('execute')}>{plan.risk === 'writes_memory' ? 'Save reviewed memory' : 'Run reviewed search'}</button></section>}
      {result && <section className="voice-result"><h3>Command result</h3><p role="status">{result.summary}</p>
        {result.kind === 'search_files' && <>{result.result.stale_omitted > 0 && <p>Stale file matches were omitted. Reconcile the folder in Files and memory.</p>}{result.result.items.map(item => <article key={item.id}><strong>{item.name}</strong><p className="voice-path">{item.path}</p><blockquote>{item.excerpt || item.status}</blockquote><button className="secondary" disabled={disabled || item.status !== 'indexed'} onClick={() => previewFile(item)}>Preview voice file</button></article>)}</>}
        {result.kind === 'search_memories' && result.result.items.map(note => <article key={note.id}><strong>{note.scope} · {note.kind.replaceAll('_', ' ')}</strong><p>{note.content}</p></article>)}
        {result.kind === 'remember' && <p>{result.result.content}</p>}
      </section>}
      {preview && <section className="voice-preview"><h3>{preview.name}</h3><pre>{preview.text}</pre>{preview.truncated && <p>Preview limited to 16,000 characters.</p>}</section>}
    </section>
    <section className="panel"><h2>Optional spoken output</h2><label className="voice-check"><input type="checkbox" checked={speechEnabled} disabled={voices.length === 0} onChange={e => { setSpeechEnabled(e.target.checked); stopSpeech(); }}/>Enable local speech output</label>
      <p>Only browser voices marked as local are offered. Speech stays off until you enable it and choose Read aloud.</p>{voices.length === 0 && <p>No local speech voice is available. Results remain readable.</p>}
      <label htmlFor="voice-output">Local output voice</label><select id="voice-output" disabled={!speechEnabled || voices.length === 0} value={voiceURI} onChange={e => { setVoiceURI(e.target.value); stopSpeech(); }}>{voices.map(voice => <option key={voice.voiceURI} value={voice.voiceURI}>{voice.name} · {voice.lang}</option>)}</select>
      <div className="voice-controls"><button className="secondary" disabled={!speechEnabled || !voiceURI || (!plan && !result) || capturing || !!busy} onClick={() => {
        try { const epoch = ++speechEpoch.current; const utterance = speakLocal(result?.summary || plan.summary, voiceURI); setSpeaking(true); utterance.onend = () => { if (epoch === speechEpoch.current) setSpeaking(false); }; utterance.onerror = e => { if (epoch === speechEpoch.current) { setSpeaking(false); if (!['canceled', 'interrupted'].includes(e.error)) setError('Local speech output failed. Text remains available.'); } }; } catch (e) { setError(e.message); }
      }}>Read aloud</button><button className="secondary" onClick={stopSpeech}>Stop speech output</button></div>{speaking && <p role="status">Speaking locally…</p>}
    </section>
  </div>;
}
