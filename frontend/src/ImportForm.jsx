import React, {useState} from 'react';
import {api} from './api';
import {BoundaryReview} from './BoundaryReview';
import {boundaryNotice, rangesValid} from './boundaryState';

export function ImportForm({run, busy}) {
  const [files, setFiles] = useState([]), [info, setInfo] = useState([]);
  const [name, setName] = useState(''), [selections, setSelections] = useState([]);
  const [note, setNote] = useState(''), [checked, setChecked] = useState(false);
  const [engine, setEngine] = useState('ai');
  const [suggestionNotice,setSuggestionNotice]=useState('');
  async function choose(event) {
    const selected = Array.from(event.target.files);
    setFiles(selected); setInfo([]); setSelections([]); setChecked(false);setSuggestionNotice('');
    if (!selected.length) return;
    await run(async () => {
      if (selected.length > 2) throw new Error('Choose two independent files or one combined PDF.');
      const details = [];
      for (const file of selected) {
        const data = new FormData(); data.append('file', file);
        details.push(await api('/inspect', 'POST', data));
      }
      setInfo(details);
      setSelections([
        {role: 'Protocol', file_index: 0, start: 1, end: details[0].pages},
        {role: 'SAP', file_index: selected.length === 2 ? 1 : 0, start: 1, end: details.at(-1).pages}
      ]);
    });
  }
  function change(i, key, value) {
    setChecked(false);
    setSelections(old => old.map((s, j) => j === i ? {...s, [key]: Number(value)} : s));
  }
  async function suggest() {
    setSuggestionNotice('');
    await run(async () => {
      const details = info.map(({ai_suggestion,model_calls,...local})=>local);
      setInfo(details);
      for (const [i,file] of files.entries()) {
        const data = new FormData(); data.append('file', file);
        details[i] = await api('/inspect/ai', 'POST', data);
      }
      setInfo([...details]);setSuggestionNotice(boundaryNotice(details));
    });
  }
  function useSuggestions(suggestions) {
    setSelections(old=>old.map(s=>({...s,...suggestions.find(d=>d.role===s.role)})));
    setChecked(false);
  }
  async function submit(event) {
    event.preventDefault();
    if(!rangesValid(selections,info))return;
    const form = new FormData();
    form.append('name', name); form.append('version_note', note); form.append('engine', engine);
    form.append('selections', JSON.stringify(selections));
    files.forEach(f => form.append('files', f));
    await run(() => api('/projects', 'POST', form), engine === 'ai' ?
      'Originals saved. Generate the AI register explicitly from the next screen.' : 'Explicit rule baseline generated.');
  }
  return <div className="content import-content">
    <h1>Import documents</h1><p className="lead">Use independent Protocol and SAP files in PDF or DOCX format, including a mixed pair. A combined PDF can be split by page range.</p>
    <form onSubmit={submit} className="import-form">
      <label>Project name<input value={name} onChange={e => setName(e.target.value)} required maxLength={200}/></label>
      <label className="upload-area">Select PDF or DOCX files<input aria-label="Select PDF or DOCX files" type="file" multiple accept=".pdf,.docx" onChange={choose} disabled={busy}/><span>File inspection is local. Model generation is a separate action.</span></label>
      {info.length > 0 && <>
        <h2>Review document boundaries</h2>
        <p className="muted">PDF ranges use physical file pages, not printed page numbers. DOCX uses one whole-document unit. A statistics chapter is not automatically a standalone SAP.</p>
        <p className="muted">AI scans a bounded index of every page, expands candidate context, and uses the selected visual route for unreadable pages when configured. Requests follow the model RPM caps in API settings; a long or scanned file may take several minutes. All ranges remain proposals until you review and apply them.</p>
        <button type="button" onClick={suggest} disabled={busy}>Ask AI for boundary suggestions</button>
        {suggestionNotice && <p role="status" className="callout">{suggestionNotice}</p>}
        <BoundaryReview files={files} info={info} onUse={useSuggestions} busy={busy}/>
        {selections.map((s, i) => <div className="range-row" key={s.role}>
          <strong>{s.role}</strong><label>Source<select value={s.file_index} onChange={e => {
            const index = Number(e.target.value);
            setChecked(false);
            setSelections(old => old.map((x, j) => j === i ? {...x, file_index: index, start: 1, end: info[index].pages} : x));
          }}>{files.map((f, j) => <option value={j} key={j}>{f.name} ({info[j].pages} {info[j].unit_label})</option>)}</select></label>
          <label>First unit<input type="number" min="1" value={s.start} disabled={info[s.file_index].format === 'docx'} onChange={e => change(i, 'start', e.target.value)}/></label>
          <label>Last unit<input type="number" min={s.start} max={info[s.file_index].pages} value={s.end} disabled={info[s.file_index].format === 'docx'} onChange={e => change(i, 'end', e.target.value)}/></label>
        </div>)}
        {!rangesValid(selections,info) && <p className="callout" role="status">Choose valid, nonoverlapping Protocol and SAP ranges before importing. A combined file initially uses the whole file for both roles; review and apply suggestions or edit the ranges manually.</p>}
        <label>Version and boundary review note<textarea value={note} onChange={e => setNote(e.target.value)} required/></label>
        <label>Register workflow<select aria-label="Register workflow" value={engine} onChange={e => setEngine(e.target.value)}><option value="ai">AI generation after import</option><option value="rules">Explicit rule baseline — no AI</option></select></label>
        <label className="checkbox"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>I checked independent documents, selected ranges and version compatibility.</label>
        <div className="callout">Original PDF and DOCX inputs are retained unchanged. Every approved edit is written to a new Word file. Model transcriptions and complex structures still require source review.</div>
        <button className="primary" disabled={busy || !checked || !name.trim() || !note.trim() || !rangesValid(selections,info)}>Import and save originals</button>
      </>}
    </form>
  </div>;
}
