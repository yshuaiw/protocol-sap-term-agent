import React, {useEffect, useState} from 'react';

export function RunBudgetSettings({config, busy, onSave}) {
  const [draft, setDraft] = useState({max_calls: config.max_calls, max_output_tokens: config.max_output_tokens});
  useEffect(() => {setDraft({max_calls: config.max_calls, max_output_tokens: config.max_output_tokens});}, [config.max_calls, config.max_output_tokens]);
  return <form className="settings-section" noValidate onSubmit={e => {
    e.preventDefault(); onSave(Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, Number(value)])));
  }}>
    <h2>Run budgets</h2>
    <p>Limits apply to the next operation. Each running operation keeps its original budgets.</p>
    <fieldset className="rate-fields" disabled={busy}>
      <label>Output tokens per response<input inputMode="numeric" value={draft.max_output_tokens}
        onChange={e => setDraft({...draft, max_output_tokens: e.target.value})}/></label>
      <label>HTTP attempts per run<input inputMode="numeric" value={draft.max_calls}
        onChange={e => setDraft({...draft, max_calls: e.target.value})}/></label>
      <p className="muted">Output: 512–131,072 tokens. Attempts: 1–1,000,000. These are application limits; your model may support less. Larger budgets can consume more tokens. Boundary scans retain smaller task-specific output caps.</p>
      <p>Cache hits use no HTTP attempts. Retries and failed requests count. Changing budgets or RPM preserves compatible accepted caches; it does not accept partial responses or resume across providers.</p>
      <div className="actions"><button className="primary">Save run budgets</button>
        <button type="button" onClick={() => onSave(config.run_limit_defaults)}>Use default budgets</button></div>
    </fieldset>
  </form>;
}
