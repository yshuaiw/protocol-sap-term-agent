import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

async function api(path, method='GET', data) {
  const options = {method};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {options.headers = {'Content-Type':'application/json'}; options.body = JSON.stringify(data);}
  const response = await fetch('/api' + path, options);
  if (!response.ok) {const error = await response.json().catch(()=>({detail:response.statusText})); throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));}
  return response.json();
}
const projectPath = p => `/projects/${p.id}`;
const downloadPath = (p, suffix) => '/api' + projectPath(p) + suffix;
const count = (list, key) => list.filter(x => x.proposal === key).length;

function App() {
  const [projects, setProjects] = useState([]), [project, setProject] = useState(null);
  const [tab, setTab] = useState('registry'), [importing, setImporting] = useState(false), [reviewConcept,setReviewConcept]=useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function refresh(){setProjects(await api('/projects'));}
  useEffect(()=>{refresh().catch(e=>setError(e.message));},[]);
  async function run(action, success='') {
    setBusy(true); setError(''); setNotice('');
    try {const result = await action(); if (result?.documents) {setProject(result); setImporting(false);} await refresh(); if(success)setNotice(success); return result;}
    catch(e) {setError(e.message); return null;} finally {setBusy(false);}
  }
  async function select(id){await run(()=>api('/projects/' + id)); setTab('registry');}
  async function transfer(event) {
    const file = event.target.files[0]; if(!file)return;
    const form = new FormData(); form.append('file',file);
    await run(()=>api('/bundles','POST',form),'Project imported with its original PDFs and history.');
    event.target.value='';
  }
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand">Protocol / SAP<span>Terminology workspace</span></div>
      <button className="primary new-project" onClick={()=>{setImporting(true);setError('');setNotice('');}}>Import PDFs</button>
      <label className="file-button">Open project bundle<input aria-label="Open project bundle" type="file" accept=".zip" onChange={transfer} disabled={busy}/></label>
      <h2 className="sidebar-heading">Saved projects</h2>
      <div className="project-list">{projects.length ? projects.map(p=><button key={p.id} className={project?.id===p.id&&!importing?'project-item selected':'project-item'} onClick={()=>select(p.id)} disabled={busy}><strong>{p.name}</strong><span>Revision {p.revision} · {new Date(p.updated).toLocaleDateString()}</span></button>):<p className="muted">Your projects will stay on this computer until you export a bundle.</p>}</div>
      <div className="sidebar-bottom">Local workspace · v0.1<br/>Rule baseline · no API calls</div>
    </aside>
    <main aria-busy={busy}>
      <header className="topbar"><div>{importing?'New project':project?.name||'Your workspace'}</div>{project&&!importing&&<span>Revision {project.revision}<button onClick={()=>run(()=>api(projectPath(project)))} disabled={busy}>Reload</button></span>}</header>
      {error&&<div role="alert" className="alert error">{error}<button onClick={()=>setError('')} aria-label="Dismiss error">×</button></div>}
      {notice&&<div role="status" className="alert success">{notice}</div>}
      {busy&&<div role="status" className="busy">Processing locally. Large documents and Word exports may take a few minutes…</div>}
      {importing?<ImportForm run={run} busy={busy}/>:project?<>
        <nav className="tabs" aria-label="Workflow">{[['registry','Terminology register'],['review','Replacement review'],['coverage','Documents & coverage'],['history','History & transfer']].map(([key,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}>{label}</button>)}</nav>
        <div className="content">{tab==='registry'?<Registry project={project} run={run} busy={busy} onReview={cid=>{setReviewConcept(cid);setTab('review');}}/>:tab==='review'?<Review project={project} run={run} busy={busy} initialConcept={reviewConcept}/>:tab==='coverage'?<Coverage project={project}/>:<History project={project} run={run} busy={busy}/>}</div>
      </>:<div className="welcome"><h1>Keep terminology consistent across documents.</h1><p>Import a Protocol and an independent SAP. Review the terminology register, approve each proposed change, then export separate Word copies.</p><button className="primary" onClick={()=>setImporting(true)}>Start with your PDFs</button><div className="welcome-note"><strong>Prepared for local review</strong><p>Original files, registry corrections and approval history stay together. Export a project bundle to continue on another computer.</p></div></div>}
    </main>
  </div>;
}

function ImportForm({run,busy}) {
  const [files,setFiles] = useState([]), [info,setInfo] = useState([]), [name,setName]=useState('');
  const [selections,setSelections]=useState([]), [note,setNote]=useState(''), [checked,setChecked]=useState(false);
  async function choose(event) {
    const selected = Array.from(event.target.files); setFiles(selected);setInfo([]);setSelections([]);setChecked(false);
    if(!selected.length)return;
    await run(async()=>{
      if(selected.length>2)throw new Error('Choose one combined PDF or two separate PDFs.');
      const details=[];
      for(const file of selected){const data=new FormData();data.append('file',file);details.push(await api('/inspect','POST',data));}
      setInfo(details);
      const boundary=selected.length===1?details[0].boundary_hints.find(h=>h.page>1&&/^statistical\s+analysis\s+plan/i.test(h.evidence.trim()))?.page:null;
      setSelections([{role:'Protocol',file_index:0,start:1,end:selected.length===2?details[0].pages:boundary?boundary-1:details[0].pages},
        {role:'SAP',file_index:selected.length===2?1:0,start:selected.length===2?1:boundary||1,end:details.at(-1).pages}]);
    });
  }
  const change=(i,key,value)=>setSelections(selections.map((s,j)=>j===i?{...s,[key]:Number(value)}:s));
  async function submit(event){event.preventDefault();const form=new FormData();form.append('name',name);form.append('version_note',note);form.append('selections',JSON.stringify(selections));files.forEach(f=>form.append('files',f));await run(()=>api('/projects','POST',form),'PDFs imported. All terminology candidates require evidence review.');}
  return <div className="content import-content"><h1>Import documents</h1><p className="lead">Use two separate PDFs, or one combined PDF containing an independent Protocol and SAP.</p>
    <form onSubmit={submit} className="import-form"><label>Project name<input value={name} onChange={e=>setName(e.target.value)} placeholder="Study name and document versions" required maxLength={200}/></label>
      <label className="upload-area">Select PDF files<input aria-label="Select PDF files" type="file" multiple accept="application/pdf" onChange={choose} disabled={busy}/><span>All selected pages will be scanned for text in every region.</span></label>
      {info.length>0&&<><h2>Review document boundaries</h2><p className="muted">Cover and title matches are suggestions. A statistical analysis chapter alone is not an independent SAP. Select the intended version, including its appendices.</p>
        {selections.map((s,i)=><div className="range-row" key={s.role}><strong>{s.role}</strong><label>Source<select value={s.file_index} onChange={e=>change(i,'file_index',e.target.value)}>{files.map((f,j)=><option value={j} key={j}>{f.name} ({info[j].pages} pages)</option>)}</select></label><label>First PDF page<input type="number" min="1" max={info[s.file_index]?.pages} value={s.start} onChange={e=>change(i,'start',e.target.value)} required/></label><label>Last PDF page<input type="number" min={s.start} max={info[s.file_index]?.pages} value={s.end} onChange={e=>change(i,'end',e.target.value)} required/></label></div>)}
        <details><summary>Title and version evidence from PDFs</summary>{info.map((x,i)=><div key={i}><h3>{files[i].name}</h3>{x.boundary_hints.slice(0,18).map(h=><p key={h.page}><strong>PDF page {h.page}</strong><br/>{h.evidence}</p>)}</div>)}</details>
        <label>Version and boundary review note<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Record protocol/SAP versions, dates, compatibility evidence and any excluded version ranges." required/></label>
        <label className="checkbox"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>I checked that these ranges contain an independent Protocol and SAP and recorded version compatibility.</label>
        <div className="callout">This version indexes extractable PDF text across all regions. Image text has no OCR. Region classification, complex tables and footnotes require visual review. Original PDFs are retained intact.</div>
        <button className="primary" disabled={busy||!checked||!name.trim()||!note.trim()}>Build terminology register</button></>}
    </form>
  </div>;
}

function Registry({project:p,run,busy,onReview}) {
  const [query,setQuery]=useState(''), [selected,setSelected]=useState(null), [adding,setAdding]=useState(false);
  const concepts=p.concepts.filter(c=>(c.name+' '+c.aliases.join(' ')).toLowerCase().includes(query.toLowerCase()));
  const concept=p.concepts.find(c=>c.id===selected)||concepts[0];
  return <><div className="section-header"><div><h1>Terminology register</h1><p className="muted">{p.concepts.length} concepts · {p.mentions.length} occurrences · {p.mentions.filter(m=>m.status==='unresolved').length} unresolved</p></div><div className="actions"><a className="button" href={downloadPath(p,'/registry.json')}>Download register</a><button onClick={()=>setAdding(!adding)}>Add concept</button></div></div>
    <div className="callout">Rule-generated candidates are not a complete or semantically validated register. Confirm a concept only after checking its occurrences; identical spellings can refer to different concepts. Registry corrections leave document text unchanged.</div>
    {adding&&<ConceptForm key="new" project={p} run={run} busy={busy} onSaved={()=>setAdding(false)}/>}
    <div className="registry-layout"><section className="register-list"><label className="search-label">Find a term<input type="search" placeholder="Name or alias" value={query} onChange={e=>setQuery(e.target.value)}/></label><div className="terms">{concepts.map(c=><button key={c.id} onClick={()=>{setSelected(c.id);setAdding(false);}} className={concept?.id===c.id?'term selected':'term'}><strong>{c.name}</strong><span>{c.category} · {c.confirmed?'confirmed':'needs review'} · {p.mentions.filter(m=>m.concept_id===c.id).length} matches</span>{c.aliases.length>0&&<small>{c.aliases.join(', ')}</small>}</button>)}{!concepts.length&&<p>No matches. Add a concept to index its forms throughout the documents.</p>}</div></section>
      {concept&&<section className="evidence-panel"><ConceptForm key={concept.id+':'+p.revision} project={p} concept={concept} run={run} busy={busy}/><div className="section-header"><h2>Occurrences and evidence</h2><button onClick={()=>onReview(concept.id)}>Plan replacement</button></div><OccurrenceList key={concept.id} project={p} concept={concept} run={run} busy={busy}/></section>}
    </div></>;
}

function ConceptForm({project:p,concept:c,run,busy,onSaved}) {
  const [name,setName]=useState(c?.name||''),[aliases,setAliases]=useState(c?.aliases.join('\n')||'');
  const [category,setCategory]=useState(c?.category||'label'),[confirmed,setConfirmed]=useState(c?.confirmed||false),[note,setNote]=useState(c?.note||'');
  async function save(e){e.preventDefault();const result=await run(()=>api(projectPath(p)+'/concepts'+(c?'/'+c.id:''),c?'PUT':'POST',{
    revision:p.revision,name,category,aliases:aliases.split('\n').map(x=>x.trim()).filter(Boolean),confirmed,note
  }),'Register saved. Document text is unchanged.');if(result)onSaved?.();}
  return <form onSubmit={save} className="concept-form"><h2>{c?'Concept details':'Add reviewer concept'}</h2><div className="form-grid"><label>Standard name<input value={name} onChange={e=>setName(e.target.value)} required maxLength={200}/></label><label>Type<select value={category} onChange={e=>setCategory(e.target.value)}>{['treatment','visit','endpoint','label'].map(x=><option key={x}>{x}</option>)}</select></label></div><label>Aliases and abbreviations <span className="muted">one per line; remove a line to delete</span><textarea rows="2" value={aliases} onChange={e=>setAliases(e.target.value)}/></label><label>Review note<textarea rows="2" value={note} onChange={e=>setNote(e.target.value)}/></label><label className="checkbox"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Confirm all unambiguous exact forms for this concept after reviewing evidence.</label><div className="actions"><button className="primary" disabled={busy||!name.trim()}>Save register</button>{c&&<span className="muted">Concept {c.id.slice(0,8)}</span>}</div>{c?.evidence&&<details><summary>Discovery evidence</summary><p>{c.evidence}</p></details>}</form>;
}

function OccurrenceList({project:p,concept,run,busy}) {
  const [page,setPage]=useState(0);
  const matches=p.mentions.filter(m=>m.concept_id===concept.id||m.candidates.includes(concept.id));
  const visible=matches.slice(page*20,page*20+20);
  return <><p className="muted">{matches.length} matches. Associations and preserve decisions can be corrected individually.</p>{visible.map(m=><Occurrence key={m.id} mention={m} project={p} run={run} busy={busy}/>)}{matches.length>20&&<div className="actions"><button disabled={page===0} onClick={()=>setPage(page-1)}>Previous</button><span>{page+1} / {Math.ceil(matches.length/20)}</span><button disabled={(page+1)*20>=matches.length} onClick={()=>setPage(page+1)}>Next</button></div>}</>;
}

function Occurrence({mention:m,project:p,run,busy}) {
  const [cid,setCid]=useState(m.concept_id||''),[status,setStatus]=useState(m.status);
  async function save(){await run(()=>api(projectPath(p)+'/mentions/'+m.id,'PUT',{revision:p.revision,concept_id:cid,status}),'Occurrence association saved.');}
  return <article className="occurrence"><div className="occurrence-meta"><strong>{m.role} · PDF p{m.page} · {m.region}</strong><span className={'status '+m.status}>{m.status}</span><a target="_blank" rel="noreferrer" href={downloadPath(p,`/documents/${m.doc_id}/source`)+`#page=${m.page}`}>View source</a></div><p>{m.context.slice(0,m.start)}<mark>{m.text}</mark>{m.context.slice(m.end)}</p><details><summary>Correct this association</summary><div className="association"><label>Concept<select value={cid} onChange={e=>setCid(e.target.value)}><option value="">Choose concept</option>{p.concepts.map(c=><option key={c.id} value={c.id}>{c.name} ({c.id.slice(0,5)})</option>)}</select></label><label>Status<select value={status} onChange={e=>setStatus(e.target.value)}>{['confirmed','unresolved','preserve'].map(x=><option key={x}>{x}</option>)}</select></label><button disabled={busy||!cid} onClick={save}>Save association</button></div></details></article>;
}

function Review({project:p,run,busy,initialConcept}) {
  const [cid,setCid]=useState(p.concepts.some(c=>c.id===initialConcept)?initialConcept:p.concepts[0]?.id||''),[mappings,setMappings]=useState({});
  const [approved,setApproved]=useState([]),[ack,setAck]=useState(false),[filter,setFilter]=useState('all');
  const concept=p.concepts.find(c=>c.id===cid);
  const plan=p.plans.at(-1),active=plan&&!plan.applied&&plan.base_revision===p.revision;
  useEffect(()=>{setMappings({});setApproved([]);setAck(false);},[cid]);
  useEffect(()=>{setApproved([]);setAck(false);},[plan?.id]);
  async function generate(e){e.preventDefault();await run(()=>api(projectPath(p)+'/plans','POST',{
    revision:p.revision,concept_id:cid,mappings:Object.fromEntries(Object.entries(mappings).filter(([,v])=>v.trim()))
  }),'Preview saved. Select the individual updates you approve.');}
  async function apply(){await run(()=>api(projectPath(p)+`/plans/${plan.id}/apply`,'POST',{
    revision:p.revision,approved_ids:approved,coverage_acknowledged:ack
  }),'Approved changes applied and both Word copies reread. Download the verification report with the documents.');setApproved([]);setAck(false);}
  const items=plan?.items.filter(i=>filter==='all'||i.proposal===filter)||[];
  return <><div className="section-header"><div><h1>Replacement review</h1><p className="muted">Map each form explicitly. Approval applies only to selected occurrences.</p></div></div>
    <form className="replacement-form" onSubmit={generate}><label>Concept<select aria-label="Concept" value={cid} onChange={e=>setCid(e.target.value)}>{p.concepts.map(c=><option key={c.id} value={c.id}>{c.name} · {c.confirmed?'confirmed':'unconfirmed'}</option>)}</select></label>{concept&&<div className="mapping-grid">{[...new Set([concept.name,...concept.aliases])].map(form=><label key={form}>Replace “{form}” with<input value={mappings[form]||''} placeholder="Leave blank to preserve this form" onChange={e=>setMappings({...mappings,[form]:e.target.value})} maxLength={200}/></label>)}</div>}<button className="primary" disabled={busy||!Object.values(mappings).some(x=>x.trim())}>Generate preview</button></form>
    {plan&&<><div className="section-header"><h2>Proposed occurrences</h2><span className="muted">{count(plan.items,'update')} updates · {count(plan.items,'preserve')} preserved · {count(plan.items,'unresolved')} unresolved</span></div>{!active&&<div className="callout">{plan.applied?'This preview has been applied. Generate a new preview for further changes.':'This preview is stale after a project change. Regenerate before approval.'}</div>}
      <label className="filter-label">Show<select value={filter} onChange={e=>setFilter(e.target.value)}>{['all','update','preserve','unresolved'].map(x=><option key={x}>{x}</option>)}</select></label>
      <div className="proposal-list">{items.map(i=><article key={i.id} className="proposal"><div className="proposal-check"><input type="checkbox" aria-label={`Approve ${i.role} page ${i.page} occurrence ${i.id}`} disabled={!active||i.proposal!=='update'||busy} checked={approved.includes(i.id)} onChange={e=>setApproved(e.target.checked?[...approved,i.id]:approved.filter(x=>x!==i.id))}/></div><div><div className="occurrence-meta"><strong>{i.role} · PDF p{i.page} · {i.region}</strong><span className={'status '+i.proposal}>{i.proposal}</span><a href={downloadPath(p,`/documents/${i.doc_id}/source`)+`#page=${i.page}`} target="_blank" rel="noreferrer">View source</a></div><p>{i.context.slice(0,i.start)}<mark>{i.text}</mark>{i.context.slice(i.end)}</p>{i.proposal==='update'&&<p className="diff"><del>{i.text}</del><span> → </span><ins>{i.new}</ins></p>}<p className="muted">{i.reason}</p></div></article>)}</div>
      {active&&<div className="approval-bar"><label className="checkbox"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I reviewed coverage limits. Word contains reconstructed editable text and unchanged source images; image text, complex table semantics and layout are not certified.</label><button className="primary" disabled={busy||!ack||!approved.length} onClick={apply}>Apply {approved.length} approved changes & export</button></div>}
    </>}
    {p.exports.length>0&&<div className="export-panel"><h2>Verified exports</h2>{p.exports.slice().reverse().map((x,i)=><div className="export-row" key={x.id}><strong>{i===0?'Latest export':`Export ${p.exports.length-i}`} · {x.verification.approved_changes.length} approved changes</strong><div className="actions">{x.files.map(file=><a key={file} className="button" href={downloadPath(p,`/exports/${x.id}/${file}`)}>{file}</a>)}</div><p className="muted">Parsed text reread: {x.verification.documents.map(d=>`${d.role} ${d.blocks_reread}/${d.blocks_expected}`).join(' · ')}. Semantic correctness and visual fidelity require review.</p></div>)}</div>}
  </>;
}

function Coverage({project:p}) {
  return <><h1>Documents and extraction coverage</h1><p className="lead">{p.version_note}</p><div className="callout">All selected pages were inspected. Counts measure parsed word coverage, not OCR, semantic completeness or table fidelity. Source images in Word retain visual content without making it editable.</div>{p.documents.map(d=><section key={d.id} className="document-section"><div className="section-header"><div><h2>{d.role} · {d.name}</h2><p className="muted">PDF pages {d.start}–{d.end} · {d.blocks.length} anchored text blocks</p></div><a className="button" target="_blank" rel="noreferrer" href={downloadPath(p,`/documents/${d.id}/source`)}>Open original PDF</a></div><p>{d.coverage_notice}</p><table><thead><tr><th>PDF page</th><th>Words represented / extracted</th><th>Detected tables</th><th>Images</th><th>Issues requiring review</th></tr></thead><tbody>{d.pages.map(page=><tr key={page.page}><td>{page.page}</td><td>{page.represented_words} / {page.words}</td><td>{page.tables}</td><td>{page.images}</td><td>{page.issues.length?page.issues.join(' '):'No automatic flag; visual review still needed.'}</td></tr>)}</tbody></table></section>)}</>;
}

function History({project:p,run,busy}) {
  return <><div className="section-header"><div><h1>History and transfer</h1><p className="muted">Snapshots persist on this computer. Restoring creates a new revision.</p></div><a className="button primary" href={downloadPath(p,'/bundle')}>Export project bundle</a></div><p className="lead">A bundle contains original PDFs, registry edits, previews, reviewer decisions, exports and snapshots. Open it on another computer to continue. API credentials are never included.</p><table><thead><tr><th>Revision</th><th>Saved</th><th>Action</th><th></th></tr></thead><tbody>{p.history.slice().reverse().map(h=><tr key={h.revision}><td>{h.revision}</td><td>{new Date(h.time).toLocaleString()}</td><td>{h.action}</td><td>{h.revision!==p.revision&&<button disabled={busy} onClick={()=>run(()=>api(projectPath(p)+'/restore','POST',{revision:p.revision,snapshot:h.revision}),'Snapshot restored as a new revision. Previews were cleared.')}>Restore revision {h.revision}</button>}</td></tr>)}</tbody></table></>;
}

createRoot(document.getElementById('root')).render(<App/>);
