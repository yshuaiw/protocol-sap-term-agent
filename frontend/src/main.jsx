import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

import {api} from './api';
import {ImportForm} from './ImportForm';
import {AiPanel} from './AiPanel';

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
    catch(e) {setError(e.message); if(project){try{setProject(await api(projectPath(project)));}catch{}} return null;} finally {setBusy(false);}
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
      <button className="primary new-project" onClick={()=>{setImporting(true);setError('');setNotice('');}}>Import documents</button>
      <label className="file-button">Open project bundle<input aria-label="Open project bundle" type="file" accept=".zip" onChange={transfer} disabled={busy}/></label>
      <h2 className="sidebar-heading">Saved projects</h2>
      <div className="project-list">{projects.length ? projects.map(p=><button key={p.id} className={project?.id===p.id&&!importing?'project-item selected':'project-item'} onClick={()=>select(p.id)} disabled={busy}><strong>{p.name}</strong><span>Revision {p.revision} · {new Date(p.updated).toLocaleDateString()}</span></button>):<p className="muted">Your projects will stay on this computer until you export a bundle.</p>}</div>
      <div className="sidebar-bottom">Local workspace · v0.2<br/>Groq AI · explicit actions</div>
    </aside>
    <main aria-busy={busy}>
      <header className="topbar"><div>{importing?'New project':project?.name||'Your workspace'}</div>{project&&!importing&&<span>Revision {project.revision}<button onClick={()=>run(()=>api(projectPath(project)))} disabled={busy}>Reload</button></span>}</header>
      {error&&<div role="alert" className="alert error">{error}<button onClick={()=>setError('')} aria-label="Dismiss error">×</button></div>}
      {notice&&<div role="status" className="alert success">{notice}</div>}
      {busy&&<div role="status" className="busy">Processing locally. Large documents and Word exports may take a few minutes…</div>}
      {importing?<ImportForm run={run} busy={busy}/>:project?<>
        <nav className="tabs" aria-label="Workflow">{[['registry','Terminology register'],['review','Replacement review'],['coverage','Documents & coverage'],['history','History & transfer']].map(([key,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}>{label}</button>)}</nav>
        <div className="content">{tab==='registry'?<Registry project={project} run={run} busy={busy} onReview={cid=>{setReviewConcept(cid);setTab('review');}}/>:tab==='review'?<Review project={project} run={run} busy={busy} initialConcept={reviewConcept}/>:tab==='coverage'?<Coverage project={project}/>:<History project={project} run={run} busy={busy}/>}</div>
      </>:<div className="welcome"><h1>Keep terminology consistent across documents.</h1><p>Import a Protocol and an independent SAP as PDF or DOCX. Review the terminology register, approve each proposed change, then export separate Word copies.</p><button className="primary" onClick={()=>setImporting(true)}>Start with your documents</button><div className="welcome-note"><strong>Prepared for local review</strong><p>Original files, registry corrections and approval history stay together. Export a project bundle to continue on another computer.</p></div></div>}
    </main>
  </div>;
}

function Registry({project:p,run,busy,onReview}) {
  const [query,setQuery]=useState(''), [selected,setSelected]=useState(null), [adding,setAdding]=useState(false);
  const concepts=p.concepts.filter(c=>(c.name+' '+c.aliases.join(' ')).toLowerCase().includes(query.toLowerCase()));
  const concept=p.concepts.find(c=>c.id===selected)||concepts[0];
  return <><div className="section-header"><div><h1>Terminology register</h1><p className="muted">{p.concepts.length} concepts · {p.mentions.length} occurrences · {p.mentions.filter(m=>m.status==='unresolved').length} unresolved</p></div><div className="actions"><a className="button" href={downloadPath(p,'/registry.json')}>Download register</a><button onClick={()=>setAdding(!adding)}>Add concept</button></div></div>
    <div className="callout">AI proposals and explicit rule baselines require evidence review; neither certifies complete recall. Confirm concepts only after checking occurrences, including abbreviation collisions. Registry corrections leave document text unchanged.</div>
    <AiPanel project={p} run={run} busy={busy}/>
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
  return <article className="occurrence"><div className="occurrence-meta"><strong>{m.role} · {p.documents.find(d=>d.id===m.doc_id)?.format==='docx'?'DOCX':'PDF p'+m.page} · {m.region}</strong><span className={'status '+m.status}>{m.status}</span><a target="_blank" rel="noreferrer" href={downloadPath(p,`/documents/${m.doc_id}/source`)+`#page=${m.page}`}>View source</a></div><p>{m.context.slice(0,m.start)}<mark>{m.text}</mark>{m.context.slice(m.end)}</p><details><summary>Correct this association</summary><div className="association"><label>Concept<select value={cid} onChange={e=>setCid(e.target.value)}><option value="">Choose concept</option>{p.concepts.map(c=><option key={c.id} value={c.id}>{c.name} ({c.id.slice(0,5)})</option>)}</select></label><label>Status<select value={status} onChange={e=>setStatus(e.target.value)}>{['confirmed','unresolved','preserve'].map(x=><option key={x}>{x}</option>)}</select></label><button disabled={busy||!cid} onClick={save}>Save association</button></div></details></article>;
}

function Review({project:p,run,busy,initialConcept}) {
  const [cid,setCid]=useState(p.concepts.some(c=>c.id===initialConcept)?initialConcept:p.concepts[0]?.id||''),[mappings,setMappings]=useState({});
  const [approved,setApproved]=useState([]),[ack,setAck]=useState(false),[filter,setFilter]=useState('all');
  const [mode,setMode]=useState('ai'),[requestText,setRequestText]=useState('');
  const concept=p.concepts.find(c=>c.id===cid);
  const plan=p.plans.at(-1),active=plan&&!plan.applied&&plan.base_revision===p.revision;

  useEffect(()=>{setApproved([]);setAck(false);},[plan?.id]);
  async function generate(e){e.preventDefault();await run(()=>api(projectPath(p)+'/plans','POST',{
    revision:p.revision,concept_id:cid,mode,mappings:Object.fromEntries(Object.entries(mappings).filter(([,v])=>v.trim()))
  }),'Preview saved. Select the individual updates you approve.');}
  async function apply(){await run(()=>api(projectPath(p)+`/plans/${plan.id}/apply`,'POST',{
    revision:p.revision,approved_ids:approved,coverage_acknowledged:ack
  }),'Approved changes applied and both Word copies reread. Download the verification report with the documents.');setApproved([]);setAck(false);}
  const items=plan?.items.filter(i=>filter==='all'||i.proposal===filter)||[];
  return <><div className="section-header"><div><h1>Replacement review</h1><p className="muted">Map each form explicitly. Approval applies only to selected occurrences.</p></div></div>
    {!p.concepts.length&&<div className="callout">Generate and review the AI register before planning a replacement.</div>}
    <section className="replacement-form"><label>Optional natural-language naming request<textarea value={requestText} onChange={e=>setRequestText(e.target.value)} maxLength={3000}/></label><button disabled={busy||!requestText.trim()||!p.concepts.length} onClick={()=>run(()=>api(projectPath(p)+'/ai/interpret','POST',{revision:p.revision,text:requestText}),'AI request interpretation saved for your review.')}>Interpret request with AI</button>
    {p.last_interpretation&&<div><p>{p.last_interpretation.reason}</p><p>{p.last_interpretation.semantic_risk?'Possible meaning/design change; review separately.':'Proposed naming mappings; not approved.'}</p><pre>{p.last_interpretation.mappings.map(m=>m.old+' → '+m.new).join('\n')}</pre><button disabled={busy||p.last_interpretation.semantic_risk} onClick={()=>{setCid(p.last_interpretation.concept_id);setMappings(Object.fromEntries(p.last_interpretation.mappings.map(m=>[m.old,m.new])));}}>Use proposed mappings</button></div>}</section>
    <form className="replacement-form" onSubmit={generate}><label>Review engine<select aria-label="Review engine" value={mode} onChange={e=>setMode(e.target.value)}><option value="ai">Groq semantic review</option><option value="rules">Explicit rule baseline</option></select></label><label>Concept<select aria-label="Concept" value={cid} onChange={e=>{setCid(e.target.value);setMappings({});}}>{p.concepts.map(c=><option key={c.id} value={c.id}>{c.name} · {c.confirmed?'confirmed':'unconfirmed'}</option>)}</select></label>{concept&&<div className="mapping-grid">{[...new Set([concept.name,...concept.aliases])].map(form=><label key={form}>Replace “{form}” with<input value={mappings[form]||''} placeholder="Leave blank to preserve this form" onChange={e=>setMappings({...mappings,[form]:e.target.value})} maxLength={200}/></label>)}</div>}<button className="primary" disabled={busy||!Object.values(mappings).some(x=>x.trim())}>Generate preview</button></form>
    {plan&&<><div className="section-header"><h2>Proposed occurrences</h2><span className="muted">{count(plan.items,'update')} updates · {count(plan.items,'preserve')} preserved · {count(plan.items,'unresolved')} unresolved</span></div>{!active&&<div className="callout">{plan.applied?'This preview has been applied. Generate a new preview for further changes.':'This preview is stale after a project change. Regenerate before approval.'}</div>}
      <label className="filter-label">Show<select value={filter} onChange={e=>setFilter(e.target.value)}>{['all','update','preserve','unresolved'].map(x=><option key={x}>{x}</option>)}</select></label>
      <div className="proposal-list">{items.map(i=><article key={i.id} className="proposal"><div className="proposal-check"><input type="checkbox" aria-label={`Approve ${i.role} page ${i.page} occurrence ${i.id}`} disabled={!active||i.proposal!=='update'||busy} checked={approved.includes(i.id)} onChange={e=>setApproved(e.target.checked?[...approved,i.id]:approved.filter(x=>x!==i.id))}/></div><div><div className="occurrence-meta"><strong>{i.role} · {p.documents.find(d=>d.id===i.doc_id)?.format==='docx'?'DOCX':'PDF p'+i.page} · {i.region}</strong><span className={'status '+i.proposal}>{i.proposal}</span><a href={downloadPath(p,`/documents/${i.doc_id}/source`)+`#page=${i.page}`} target="_blank" rel="noreferrer">View source</a></div><p>{i.context.slice(0,i.start)}<mark>{i.text}</mark>{i.context.slice(i.end)}</p>{i.proposal==='update'&&<p className="diff"><del>{i.text}</del><span> → </span><ins>{i.new}</ins></p>}<p className="muted">{i.reason}</p></div></article>)}</div>
      {active&&<div className="approval-bar"><label className="checkbox"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I reviewed coverage limits. Word contains reconstructed editable text and unchanged source images; image text, complex table semantics and layout are not certified.</label><button className="primary" disabled={busy||!ack||!approved.length} onClick={apply}>Apply {approved.length} approved changes & export</button></div>}
    </>}
    {p.semantic_audits?.at(-1)&&<div className="callout"><strong>Latest advisory semantic audit</strong>{p.semantic_audits.at(-1).findings.length?p.semantic_audits.at(-1).findings.map((f,i)=><p key={i}>{f.concern}: {f.evidence}</p>):<p>No concerns returned by the model. This is not proof of semantic correctness.</p>}</div>}
    {p.exports.length>0&&<div className="export-panel"><h2>Text-verified exports</h2>{p.exports.slice().reverse().map((x,i)=><div className="export-row" key={x.id}><button disabled={busy} onClick={()=>run(()=>api(projectPath(p)+'/ai/audit','POST',{revision:p.revision,export_id:x.id}),'Advisory semantic audit saved.')}>Ask AI to review meaning</button><strong>{i===0?'Latest export':`Export ${p.exports.length-i}`} · {x.verification.approved_changes.length} approved changes</strong><div className="actions">{x.files.map(file=><a key={file} className="button" href={downloadPath(p,`/exports/${x.id}/${file}`)}>{file}</a>)}</div><p className="muted">Parsed text reread: {x.verification.documents.map(d=>`${d.role} ${d.blocks_reread}/${d.blocks_expected}`).join(' · ')}. Semantic correctness and visual fidelity require review.</p></div>)}</div>}
  </>;
}

function Coverage({project:p}) {
  return <><h1>Documents and extraction coverage</h1><p className="lead">{p.version_note}</p><div className="callout">All selected pages were inspected. Counts measure parsed word coverage, not OCR, semantic completeness or table fidelity. Visual transcriptions require source review. Native DOCX exports preserve the source package in a new file; PDF exports reconstruct text and retain original page images.</div>{p.documents.map(d=><section key={d.id} className="document-section"><div className="section-header"><div><h2>{d.role} · {d.name}</h2><p className="muted">{d.format==='docx'?'Whole DOCX':'PDF pages '+d.start+'–'+d.end} · {d.blocks.length} anchored text blocks</p></div><a className="button" target="_blank" rel="noreferrer" href={downloadPath(p,`/documents/${d.id}/source`)}>Open original document</a></div><p>{d.coverage_notice}</p><table><thead><tr><th>Source unit</th><th>Words represented / extracted</th><th>Detected tables</th><th>Images</th><th>Issues requiring review</th></tr></thead><tbody>{d.pages.map(page=><tr key={page.page}><td>{page.page}</td><td>{page.represented_words} / {page.words}</td><td>{page.tables}</td><td>{page.images}</td><td>{page.issues.length?page.issues.join(' '):'No automatic flag; visual review still needed.'}</td></tr>)}</tbody></table></section>)}</>;
}

function History({project:p,run,busy}) {
  return <><div className="section-header"><div><h1>History and transfer</h1><p className="muted">Snapshots persist on this computer. Restoring creates a new revision.</p></div><a className="button primary" href={downloadPath(p,'/bundle')}>Export project bundle</a></div><p className="lead">A bundle contains original PDFs, registry edits, previews, reviewer decisions, exports and snapshots. Open it on another computer to continue. API credentials are never included.</p><table><thead><tr><th>Revision</th><th>Saved</th><th>Action</th><th></th></tr></thead><tbody>{p.history.slice().reverse().map(h=><tr key={h.revision}><td>{h.revision}</td><td>{new Date(h.time).toLocaleString()}</td><td>{h.action}</td><td>{h.revision!==p.revision&&<button disabled={busy} onClick={()=>run(()=>api(projectPath(p)+'/restore','POST',{revision:p.revision,snapshot:h.revision}),'Snapshot restored as a new revision. Previews were cleared.')}>Restore revision {h.revision}</button>}</td></tr>)}</tbody></table></>;
}

createRoot(document.getElementById('root')).render(<App/>);
