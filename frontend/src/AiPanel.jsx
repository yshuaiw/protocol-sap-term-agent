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
      <p>Text: {config.provider} · {config.model} · {config.key_configured ? 'Key configured locally' : 'No key configured'}{config.offline ? ' · Model requests disabled' : ''}</p>
      <p>Visual: {config.vision_provider} · {config.vision_model} · {config.vision_key_configured ? 'Key configured locally' : 'No key configured'}</p>
      {config.rate_defaults ? <p className="muted">App RPM caps: text {config.text_rpm}, visual {config.vision_rpm}. The same provider/model shares one cap. Requests may pause to respect it; edit limits in API settings.</p> : <p className="muted">Restart the backend to load configurable RPM limits.</p>}
      <p className="muted">Run budgets: {config.max_calls} HTTP attempts; {config.max_output_tokens} output tokens per response. Accepted cache hits use no attempts. Edit budgets in API settings before starting a new operation.</p>
      {!config.key_configured && <p className="muted">Open API settings to save a local credential, then refresh settings.</p>}
      <label>PDF and embedded-image processing<select aria-label="Visual processing mode" value={mode} onChange={e => setMode(e.target.value)}><option value="vision" disabled={!config.image_input}>Text + per-page vision ({config.vision_model || 'not configured'})</option><option value="native" disabled={!config.native_pdf}>Text + original PDF (supported visual providers)</option><option value="text">Extracted text only — image coverage may remain incomplete</option></select></label>
      <p className="muted">Content is sent to the selected providers. Settings are fixed when the operation starts. Failures require a manual switch and a new operation; no automatic fallback or cross-provider resume.</p>
      {mode === 'native' && <p className="callout">The full original PDF is submitted per selected page, including pages outside the selection. Native input is limited to 15 MiB and may use substantially more tokens. Source page attribution requires review.</p>}
      {project.concepts.length > 0 && <label className="checkbox"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)}/>Replace this register with a new AI run; earlier corrections remain in history.</label>}
      <button className="primary" disabled={busy || !config.key_configured || config.offline || (mode !== 'text' && (!config.vision_key_configured || (mode === 'native' ? !config.native_pdf : !config.image_input))) || (project.concepts.length > 0 && !replace)} onClick={() => run(() => api(`/projects/${project.id}/ai/generate`, 'POST', {revision: project.revision, replace_registry: replace, pdf_mode: mode}), 'AI run saved. Review source evidence and coverage gaps before confirming concepts.')}>Generate AI register and links</button>
    </>}
    {last && <div className="ai-run"><strong>Last run: {last.status}{last.calls?.some(c=>c.simulation)?' · SIMULATED TEST RESPONSES':''}</strong>{last.configuration && <p className="muted">Used text: {last.configuration.provider} · {last.configuration.model}; visual: {last.configuration.vision_provider} · {last.configuration.vision_model}; processing: {last.configuration.pdf_mode}.</p>}<p className="muted">Text chunks {last.chunks_completed || 0}/{last.chunks_total || 0} · Visual units {last.visual_units_completed || 0} · Accepted results {last.calls?.length || 0} · Cache hits {last.calls?.filter(c=>c.cached).length || 0} · HTTP attempts {last.http_attempts ?? (last.calls || []).reduce((n,c)=>n+(c.cached ? 0 : c.request_attempts || 1),0)} · Reported tokens {(last.calls || []).reduce((n, c) => n + (c.usage?.total_tokens || 0), 0)}</p>{last.linking_progress && <p className="muted">Linking: {last.linking_progress.candidates_completed}/{last.linking_progress.candidates_total} candidates · Index pages checked {last.linking_progress.index_pages_checked} · Evidence requests {last.linking_progress.evidence_requests} · Legacy batches reused {last.linking_progress.legacy_batches_reused}</p>}{last.error && <p>{last.error}</p>}{last.discovery_exclusions?.length > 0 && <details open><summary>AI scope exclusions requiring review ({last.discovery_exclusions.length})</summary><p className="muted">These model proposals were excluded as out of scope, not added to the register. Check these decisions before confirming terminology.</p>{last.discovery_exclusions.map((item,i)=><p key={i}><strong>{item.term}</strong>: {item.reason}</p>)}</details>}{last.coverage_gaps?.length > 0 && <details open><summary>Coverage gaps requiring review</summary>{last.coverage_gaps.map((g, i) => <p key={i}>{g}</p>)}</details>}</div>}
  </section>;
}
