import React, {useEffect, useState} from 'react';
import {api} from './api';

export function AiPanel({project, run, busy}) {
  const [config, setConfig] = useState(null), [error, setError] = useState('');
  const [replace, setReplace] = useState(false), [mode, setMode] = useState('vision');
  async function reload() {
    try {const value = await api('/ai/config'); setConfig(value); setMode(value.pdf_mode); setError('');}
    catch (e) {setError(e.message);}
  }
  useEffect(() => {reload();}, []);
  const last = project.ai_runs?.filter(r => r.stage === 'registry_generation').at(-1);
  return <section className="ai-panel">
    <div className="section-header"><div><h2>AI terminology workflow</h2><p className="muted">Current register: {project.engine || 'legacy baseline'}. Discovery and semantic linking require source review.</p></div><button disabled={busy} onClick={reload}>Refresh AI settings</button></div>
    {error && <p role="alert">{error}</p>}
    {config && <>
      <p>Groq · {config.model} · {config.key_configured ? 'Key configured locally' : 'No key configured'}{config.offline ? ' · Model requests disabled' : ''}</p>
      {!config.key_configured && <p className="muted">Save the key in backend-only API.txt or GROQ_API_KEY, then refresh settings. Do not paste a key into the browser.</p>}
      <label>PDF and embedded-image processing<select aria-label="Visual processing mode" value={mode} onChange={e => setMode(e.target.value)}><option value="vision">Text + per-page vision ({config.vision_model || 'not configured'})</option><option value="text">Extracted text only — image coverage may remain incomplete</option></select></label>
      <p className="muted">Generation sends selected document content to Groq. Vision mode processes every selected PDF page. Model availability, quota and quality have not been live-tested.</p>
      {project.concepts.length > 0 && <label className="checkbox"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)}/>Replace this register with a new AI run; earlier corrections remain in history.</label>}
      <button className="primary" disabled={busy || !config.key_configured || config.offline || (project.concepts.length > 0 && !replace)} onClick={() => run(() => api(`/projects/${project.id}/ai/generate`, 'POST', {revision: project.revision, replace_registry: replace, pdf_mode: mode}), 'AI run saved. Review source evidence and coverage gaps before confirming concepts.')}>Generate AI register and links</button>
    </>}
    {last && <div className="ai-run"><strong>Last run: {last.status}{last.calls?.some(c=>c.simulation)?' · SIMULATED TEST RESPONSES':''}</strong><p className="muted">Text chunks {last.chunks_completed || 0}/{last.chunks_total || 0} · Visual units {last.visual_units_completed || 0} · Model operations {last.calls?.length || 0} · Reported tokens {(last.calls || []).reduce((n, c) => n + (c.usage?.total_tokens || 0), 0)}</p>{last.error && <p>{last.error}</p>}{last.coverage_gaps?.length > 0 && <details open><summary>Coverage gaps requiring review</summary>{last.coverage_gaps.map((g, i) => <p key={i}>{g}</p>)}</details>}</div>}
  </section>;
}
