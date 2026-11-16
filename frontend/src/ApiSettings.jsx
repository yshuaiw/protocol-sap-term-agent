import React, {useEffect, useState} from 'react';
import {api} from './api';
import {RateLimitSettings} from './RateLimitSettings';

const selected = c => Object.fromEntries(['provider', 'model', 'vision_provider', 'vision_model', 'pdf_mode'].map(k => [k, c[k]]));

export function ApiSettings({onClose}) {
  const [config, setConfig] = useState(null), [draft, setDraft] = useState(null);
  const [credentialProvider, setCredentialProvider] = useState('groq'), [key, setKey] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => {api('/ai/config').then(c=>{setConfig(c);setDraft(selected(c));}).catch(e=>setError(e.message));}, []);
  async function change(action, message, reset=false) {
    setBusy(true); setError(''); setNotice('');
    try {
      const c = await action(); setConfig(c); if(reset)setDraft(selected(c)); setNotice(message);
    } catch(e) {setError(e.message);} finally {setKey('');setBusy(false);}
  }
  function providerChange(field, modelField, id) {
    setDraft({...draft, [field]: id, [modelField]: config.providers[id][modelField === 'model' ? 'model' : 'vision_model']});
  }
  return <div className="api-settings">
    <div className="section-header"><div><h1>API settings</h1><p className="muted">Saved on this computer. Each operation keeps the configuration it started with.</p></div><button onClick={onClose}>Back to workspace</button></div>
    {error && <p className="alert error" role="alert">{error}</p>}
    {notice && <p className="alert success" role="status">{notice}</p>}
    {config && draft && <>
      {config.offline && <p className="callout">Offline mode is active. Saving settings makes no model requests. Set TERM_AGENT_OFFLINE=0 and restart the backend to enable requests.</p>}
      <form className="settings-section" onSubmit={e=>{e.preventDefault();change(()=>api('/ai/config', 'PUT', draft), 'Settings saved. They apply to the next AI operation.', true);}}>
        <h2>Task providers and models</h2>
        <div className="settings-grid">
          <fieldset disabled={busy}><legend>Text tasks</legend>
            <label>Text provider<select aria-label="Text provider" value={draft.provider} onChange={e=>providerChange('provider', 'model', e.target.value)}>{Object.entries(config.providers).map(([id,p])=><option key={id} value={id}>{p.name}</option>)}</select></label>
            <label>Text model<input required maxLength={150} value={draft.model} onChange={e=>setDraft({...draft, model:e.target.value})}/></label>
            <p className="muted">Discovery, linking, naming review, request interpretation and advisory checks.</p>
          </fieldset>
          <fieldset disabled={busy}><legend>Visual tasks</legend>
            <label>Visual provider<select aria-label="Visual provider" value={draft.vision_provider} onChange={e=>providerChange('vision_provider', 'vision_model', e.target.value)}>{Object.entries(config.providers).filter(([,p])=>p.image_input).map(([id,p])=><option key={id} value={id}>{p.name}</option>)}</select></label>
            <label>Visual model<input required maxLength={150} value={draft.vision_model} onChange={e=>setDraft({...draft, vision_model:e.target.value})}/></label>
            <p className="muted">Page images, embedded images and supported native PDF input. Transcriptions require source review.</p>
          </fieldset>
        </div>
        <label>Default document processing<select value={draft.pdf_mode} disabled={busy} onChange={e=>setDraft({...draft, pdf_mode:e.target.value})}>
          <option value="text">Extracted text only</option>
          <option value="vision">Text + page images</option>
          <option value="native" disabled={!config.providers[draft.vision_provider]?.native_pdf}>Text + original PDF</option>
        </select></label>
        {draft.pdf_mode === 'native' && <p className="callout">The original PDF is sent once per selected page, with that page as the transcription target. Other pages in the original file are also sent. Limit: 15 MiB per original. This can use substantially more tokens. Model page attribution remains unverified.</p>}
        <p className="muted">Model IDs are editable examples, not verified availability or prices. Confirm model capabilities and account access with your provider. Text-only mode reports image coverage gaps. DOCX is read locally; embedded images use the visual provider.</p>
        <p>Failures stop the operation. Switch providers here and start a new operation manually. Cross-provider resume is not supported.</p>
        <button className="primary" disabled={busy}>Save task settings</button>
      </form>
      {config.rate_defaults ? <RateLimitSettings config={config} busy={busy} onSave={value=>change(()=>api('/ai/rate-limits','PUT',value),'Model RPM limit saved. It applies to the next operation; recent usage is retained.')}/> :
        <section className="settings-section"><h2>Request rate limits</h2><p role="status">Restart the backend and refresh this page to load configurable RPM limits.</p></section>}
      <section className="settings-section"><h2>Local credentials</h2>
        <p>Keys are stored in a plain-text local configuration file. They are excluded from Git, project bundles and history. Saved keys are never shown here.</p>
        <form onSubmit={e=>{e.preventDefault();change(()=>api(`/ai/credentials/${credentialProvider}`, 'PUT', {key}), 'Key saved locally. Credentials and model access have not been tested.');}}>
          <label>Credential provider<select disabled={busy} value={credentialProvider} onChange={e=>{setCredentialProvider(e.target.value);setKey('');setNotice('');}}>{Object.entries(config.providers).map(([id,p])=><option key={id} value={id}>{p.name}</option>)}</select></label>
          <p role="status">{config.providers[credentialProvider].key_configured ? 'Key configured' : 'No active key'} · {config.providers[credentialProvider].key_source}</p>
          <label>New API key<input type="password" autoComplete="new-password" spellCheck={false} value={key} onChange={e=>setKey(e.target.value)} maxLength={512} disabled={busy}/></label>
          <div className="actions"><button className="primary" disabled={busy || key.length < 8}>{config.providers[credentialProvider].key_configured ? 'Replace key' : 'Save key'}</button>
            <button type="button" disabled={busy || !config.providers[credentialProvider].key_configured} onClick={()=>change(()=>api(`/ai/credentials/${credentialProvider}`, 'DELETE'), 'Key deleted from managed settings. Legacy file/environment fallback is disabled for this provider.')}>Delete key</button></div>
        </form>
        <p className="muted">Groq API.txt and environment keys remain compatible. Deleting a key disables legacy fallback; the original API.txt and environment are retained. Save a new key to re-enable this provider. Keys are entered only in this local page and sent to the local backend.</p>
      </section>
    </>}
  </div>;
}
