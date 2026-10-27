import React, { useEffect, useRef, useState } from 'react';
import './WorkersPanel.css';

export default function WorkersPanel({ api }) {
  const [overview, setOverview] = useState(null);
  const [name, setName] = useState('');
  const [workerId, setWorkerId] = useState('');
  const [rounds, setRounds] = useState(2);
  const [credential, setCredential] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [revoking, setRevoking] = useState(null);
  const pairRequest = useRef(null), taskRequest = useRef(null), generation = useRef(0);

  async function refresh() {
    const revision = ++generation.current;
    const data = await api('/v1/pc-workers');
    if (revision === generation.current) setOverview(data);
  }
  useEffect(() => { refresh().catch(e => setError({ message: e.message, retry: refresh }));
    return () => { generation.current++; };
  }, [api]);

  async function run(action) {
    if (busy) return;
    setBusy(true); setError(null);
    try { await action(); await refresh(); }
    catch (e) { setError({ message: e.message || 'Connection lost. Check the local server and retry.', retry: action }); }
    finally { setBusy(false); }
  }
  function requestKey(ref, payload) {
    const signature = JSON.stringify(payload);
    if (ref.current?.signature !== signature) ref.current = { signature, key: crypto.randomUUID() };
    return ref.current.key;
  }
  function pair(event) {
    event.preventDefault();
    const payload = { name: name.trim() }, key = requestKey(pairRequest, payload);
    run(async () => {
      const result = await api('/v1/pc-workers', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload) });
      setWorkerId(result.worker.id); setCredential(current => result.credential || (current?.worker_id === result.worker.id ? current : null));
      setNotice(result.credential ? 'Worker paired. Download its credential now; it is shown only once.' : result.message);
      pairRequest.current = null; setName('');
    });
  }
  function downloadCredential() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(credential, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `leaddesk-worker-${credential.worker_id}.json`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function enqueue(event) {
    event.preventDefault();
    const payload = { worker_id: workerId, kind: 'synthetic_parser_benchmark', rounds: Number(rounds) };
    const key = requestKey(taskRequest, payload);
    run(async () => {
      const task = await api('/v1/pc-tasks', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload) });
      setSelected(task); taskRequest.current = null;
      setNotice('Synthetic benchmark queued for this worker. Offline work waits here.');
    });
  }
  const activeWorkers = overview?.workers.filter(w => w.revoked_at == null) || [];
  const chosenWorker = activeWorkers.find(w => w.id === workerId);
  const workerName = id => overview?.workers.find(w => w.id === id)?.name || id;

  return <div className="workers-panel">
    {error && <div role="alert" className="alert"><p>{error.message}</p><button className="secondary" disabled={busy} onClick={() => run(error.retry)}>Retry worker request</button></div>}
    {notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel"><h2>Optional PC worker</h2>
      <p>Pair a computer you control to run the bundled synthetic parser benchmark. Only benchmark settings are sent. Saved research, files, notes, screen and audio stay here.</p>
      <p>{overview?.enabled ? 'Pairing enabled for the listed computers.' : 'Disabled: no active worker pairing.'} A disconnected computer keeps its work queued. There is no automatic fallback.</p>
      <button className="secondary" disabled={busy} onClick={() => run(async () => {
        if (selected) setSelected(await api(`/v1/pc-tasks/${selected.id}`));
      })}>Refresh workers and tasks</button>
      <form onSubmit={pair}><label htmlFor="worker-name">Computer name</label><input id="worker-name" maxLength={80} required value={name} disabled={busy || !!credential} onChange={e => setName(e.target.value)}/>
        <button className="primary" disabled={busy || !!credential || !name.trim()}>Pair PC worker</button></form>
    </section>
    {credential && <section className="panel worker-credential"><h2>Save this worker credential</h2>
      <p>Download once, transfer privately to the paired computer and set file permissions to 600. It grants only this worker’s benchmark access. The credential is cleared when you leave this panel.</p>
      <button className="primary" onClick={downloadCredential}>Download worker credential</button>
      <button className="secondary" onClick={() => setCredential(null)}>Forget displayed credential</button>
    </section>}
    <section className="panel"><h2>Paired computers</h2>
      {overview?.workers.length === 0 && <p>No computers paired.</p>}
      {overview?.workers.map(worker => <article className="worker-card" key={worker.id}><h3>{worker.name}</h3>
        <p>{worker.connection.replaceAll('_', ' ')} · Last seen: {worker.last_seen_at == null ? 'Never' : new Date(worker.last_seen_at * 1000).toLocaleString()}</p>
        {worker.revoked_at == null && <button className="secondary" disabled={busy} onClick={() => setRevoking(worker)}>Revoke {worker.name}</button>}
      </article>)}
      {revoking && <div className="worker-card"><h3>Revoke {revoking.name}?</h3><p>This cancels its pending tasks and rejects further worker access. Saved reports remain.</p>
        <button className="primary" disabled={busy} onClick={() => { const id = revoking.id; run(async () => {
          await api(`/v1/pc-workers/${id}/revoke`, { method: 'POST' });
          if (credential?.worker_id === id) setCredential(null);
          if (selected?.worker_id === id) setSelected(await api(`/v1/pc-tasks/${selected.id}`));
          setRevoking(null); setNotice('Worker pairing revoked. Pending tasks cancelled.');
        }); }}>Confirm revoke worker</button>
        <button className="secondary" disabled={busy} onClick={() => setRevoking(null)}>Keep pairing</button>
      </div>}
    </section>
    <section className="panel"><h2>Queue a synthetic benchmark</h2>
      <form onSubmit={enqueue}><label htmlFor="task-worker">Paired worker</label><select id="task-worker" required value={chosenWorker ? workerId : ''} disabled={busy} onChange={e => setWorkerId(e.target.value)}>
        <option value="">Choose a computer</option>{activeWorkers.map(w => <option value={w.id} key={w.id}>{w.name}</option>)}
      </select><label htmlFor="worker-rounds">Benchmark rounds</label><input id="worker-rounds" type="number" min="2" max="20" required value={rounds} disabled={busy} onChange={e => setRounds(e.target.value)}/>
        <p>Five fictional cases per round. This measures the parser on the paired computer. No model is invoked.</p>
        <button className="primary" disabled={busy || !chosenWorker}>Queue worker benchmark</button></form>
    </section>
    <section className="panel"><h2>PC benchmark tasks</h2><p>Refresh to see connection and task changes. A recently seen worker may still be unreachable.</p>
      {overview?.tasks.length === 0 && <p>No worker tasks.</p>}
      {overview?.tasks.map(task => <article className="worker-card" key={task.id}><h3>{workerName(task.worker_id)} · {task.rounds} rounds</h3>
        <p>{task.status} · Attempt {task.attempts} of 3{task.error_code ? ` · ${task.error_code.replaceAll('_', ' ')}` : ''}</p>
        {task.benchmark_status && <p>Benchmark checks: {task.benchmark_status}</p>}
        <small>{task.id}</small><div className="worker-actions"><button className="secondary" disabled={busy} onClick={() => run(async () => setSelected(await api(`/v1/pc-tasks/${task.id}`)))}>Inspect worker task</button>
        {['queued', 'running'].includes(task.status) && <button className="secondary" disabled={busy} onClick={() => run(async () => {
          setSelected(await api(`/v1/pc-tasks/${task.id}/cancel`, { method: 'POST' })); setNotice('Worker task cancelled. Late results will be rejected.');
        })}>Cancel worker task</button>}</div></article>)}
    </section>
    {selected && <section className="panel worker-result"><h2>Worker task details</h2><p>{workerName(selected.worker_id)} · {selected.status} · {selected.rounds} rounds</p>
      <p>Worker-reported measurements; accuracy and hardware are not independently verified. Synthetic checks do not establish live-source quality. Model hash: none.</p>
      {selected.result ? <><p>{selected.result.passed_count} / {selected.result.check_count} checks passed · {selected.result.total_ms.toFixed(2)} ms total</p>
        <pre>{JSON.stringify(selected.result, null, 2)}</pre></> : <p>No accepted result yet.{selected.error_code ? ` ${selected.error_code.replaceAll('_', ' ')}.` : ''}</p>}
    </section>}
    <section className="panel"><h2>Connect the paired computer</h2><p>Use the same LeadDesk checkout and Python dependencies on the paired Ubuntu computer. From that computer, establish your own SSH tunnel to this laptop:</p>
      <pre>ssh -N -L 127.0.0.1:18765:127.0.0.1:8765 YOUR_USER@YOUR_LAPTOP</pre>
      <p>Keep SSH open. In another terminal on the paired computer, set the downloaded credential to mode 600 and run:</p>
      <pre>{'chmod 600 /path/to/worker-credential.json\n.venv/bin/python scripts/pc_worker.py --coordinator http://127.0.0.1:18765 --credential-file /path/to/worker-credential.json'}</pre>
      <p>SSH access must already be configured privately. LeadDesk does not configure it. Stop the worker with Ctrl+C. Disconnects retry; a stopped process loses its in-memory result and its task can retry after the lease expires.</p>
    </section>
  </div>;
}
