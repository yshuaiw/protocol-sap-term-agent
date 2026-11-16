import React, {useState} from 'react';
import {api} from './api';
import {projectPath, downloadPath} from './paths';
import {AiPanel} from './AiPanel';
import {sourceSlice} from './sourceText';
import {Explanations,ExplanationActions} from './Explanations';

export function Registry({project:p,run,busy,onReview}) {
  const [query,setQuery]=useState(''), [selected,setSelected]=useState(null), [adding,setAdding]=useState(false);
  const concepts=p.concepts.filter(c=>(c.name+' '+c.aliases.join(' ')).toLowerCase().includes(query.toLowerCase()));
  const concept=p.concepts.find(c=>c.id===selected)||concepts[0];
  return <><div className="section-header"><div><h1>Terminology register</h1><p className="muted">{p.concepts.length} concepts · {p.mentions.length} occurrences · {p.mentions.filter(m=>m.status==='unresolved').length} unresolved</p></div><div className="actions"><a className="button" href={downloadPath(p,'/registry.json')}>Download register</a><button onClick={()=>setAdding(!adding)}>Add concept</button></div></div>
    <div className="callout">AI proposals and explicit rule baselines require evidence review; neither certifies complete recall. Confirm concepts only after checking occurrences, including abbreviation collisions. Registry corrections leave document text unchanged.</div>
    <AiPanel project={p} run={run} busy={busy}/>
    <ExplanationActions project={p} run={run} busy={busy}/>
    {adding&&<ConceptForm key="new" project={p} run={run} busy={busy} onSaved={()=>setAdding(false)}/>}
    <div className="registry-layout"><section className="register-list"><label className="search-label">Find a term<input type="search" placeholder="Name or alias" value={query} onChange={e=>setQuery(e.target.value)}/></label><div className="terms">{concepts.map(c=><button key={c.id} onClick={()=>{setSelected(c.id);setAdding(false);}} className={concept?.id===c.id?'term selected':'term'}><strong>{c.name}</strong><span>{c.category} · {c.confirmed?'confirmed':'needs review'} · {p.mentions.filter(m=>m.concept_id===c.id).length} matches</span>{c.aliases.length>0&&<small>{c.aliases.join(', ')}</small>}</button>)}{!concepts.length&&<p>No matches. Add a concept to index its forms throughout the documents.</p>}</div></section>
      {concept&&<section className="evidence-panel"><ConceptForm key={concept.id+':'+p.revision} project={p} concept={concept} run={run} busy={busy}/><Explanations project={p} concept={concept} run={run} busy={busy}/><div className="section-header"><h2>Occurrences and evidence</h2><button onClick={()=>onReview(concept.id)}>Plan replacement</button></div><OccurrenceList key={concept.id} project={p} concept={concept} run={run} busy={busy}/></section>}
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
  return <article className="occurrence"><div className="occurrence-meta"><strong>{m.role} · {p.documents.find(d=>d.id===m.doc_id)?.format==='docx'?'DOCX':'PDF p'+m.page} · {m.region}</strong><span className={'status '+m.status}>{m.status}</span><a target="_blank" rel="noreferrer" href={downloadPath(p,`/documents/${m.doc_id}/source`)+`#page=${m.page}`}>View source</a></div><p>{sourceSlice(m.context,0,m.start)}<mark>{m.text}</mark>{sourceSlice(m.context,m.end)}</p>{m.model_link_status==='ambiguous'&&<p className='muted'>Association needs review: {m.model_reason}</p>}<details><summary>Correct this association</summary><div className="association"><label>Concept<select value={cid} onChange={e=>setCid(e.target.value)}><option value="">Choose concept</option>{p.concepts.map(c=><option key={c.id} value={c.id}>{c.name} ({c.id.slice(0,5)})</option>)}</select></label><label>Status<select value={status} onChange={e=>setStatus(e.target.value)}>{['confirmed','unresolved','preserve'].map(x=><option key={x}>{x}</option>)}</select></label><button disabled={busy||!cid} onClick={save}>Save association</button></div></details></article>;
}
