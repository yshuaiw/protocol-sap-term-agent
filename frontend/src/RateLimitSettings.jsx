import React, {useEffect, useState} from 'react';

export function RateLimitSettings({config, busy, onSave}) {
  const [provider,setProvider]=useState(config.provider),[model,setModel]=useState(config.model);
  const saved=config.rate_limits?.[provider]?.[model];
  const starter=config.rate_defaults[provider];
  const [rpm,setRpm]=useState(saved ?? starter);
  useEffect(()=>{setRpm(saved ?? starter);},[provider,model,saved,starter]);
  const valid=Number.isInteger(Number(rpm)) && Number(rpm)>=1 && Number(rpm)<=1000 && model.trim();
  function choose(providerId, modelId) {setProvider(providerId);setModel(modelId);}
  return <form className="settings-section rate-limits" onSubmit={e=>{e.preventDefault();if(valid)onSave({provider,model:model.trim(),rpm:Number(rpm)});}}>
    <h2>Request rate limits</h2>
    <p>Set a separate RPM cap for each provider and model using your account's current limits. These caps control this app's sending rate; they do not increase provider quotas.</p>
    <p className="muted">Saved text selection: {config.provider} · {config.model} · {config.text_rpm} RPM<br/>Saved visual selection: {config.vision_provider} · {config.vision_model} · {config.vision_rpm} RPM</p>
    <div className="actions">
      <button type="button" disabled={busy} onClick={()=>choose(config.provider,config.model)}>Edit text model limit</button>
      <button type="button" disabled={busy} onClick={()=>choose(config.vision_provider,config.vision_model)}>Edit visual model limit</button>
    </div>
    <fieldset className="rate-fields" disabled={busy}>
      <label>Rate limit provider<select aria-label="Rate limit provider" value={provider} onChange={e=>choose(e.target.value,config.providers[e.target.value].model)}>{Object.entries(config.providers).map(([id,p])=><option key={id} value={id}>{p.name}</option>)}</select></label>
      <label>Rate limit model<input required value={model} maxLength={150} onChange={e=>setModel(e.target.value)}/></label>
      <label>Requests per minute (RPM)<input type="number" required min="1" max="1000" step="1" value={rpm} onChange={e=>setRpm(e.target.value)}/></label>
    </fieldset>
    <p className="muted">{saved === undefined ? `App starting cap: ${starter} RPM; no model override saved.` : `Saved model cap: ${saved} RPM.`} Starting caps are not verified account quotas. At this cap, requests start about every {valid ? (60/Number(rpm)).toFixed(1) : '—'} seconds or slower.</p>
    <p>Text and visual calls to the same provider/model share one limit across projects and tabs. Every retry counts; validated local cache hits make no request. Changes apply to the next operation and do not clear recent usage.</p>
    <p className="muted">Low RPM caps can mean long pauses. TPM, daily quotas, other applications and shared provider quota pools can still cause errors. This setting does not fix network timeouts.</p>
    <div className="actions"><button className="primary" disabled={busy || !valid}>Save model RPM limit</button>
      <button type="button" disabled={busy || saved === undefined} onClick={()=>onSave({provider,model,rpm:null})}>Use app starting cap</button></div>
    {Object.values(config.rate_limits || {}).some(models=>Object.keys(models).length>0) && <details><summary>Saved model limits</summary><ul>{Object.entries(config.rate_limits).flatMap(([p,models])=>Object.entries(models).map(([m,r])=><li key={p+':'+m}><button type="button" disabled={busy} onClick={()=>choose(p,m)}>{config.providers[p].name} · {m} · {r} RPM</button></li>))}</ul></details>}
  </form>;
}
