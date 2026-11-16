import React, {useState} from 'react';
import {api} from './api';
import {projectPath,downloadPath} from './paths';
import {sourceSlice} from './sourceText';

export function ExplanationActions({project,run,busy}) {
  const latest=project.ai_runs?.filter(r=>r.explanations).at(-1)?.explanations;
  return <section className="explanation-actions"><h2>Document-sourced explanations</h2>
    <p>New AI registers include explanation proposals. Existing projects update only when you request it. Every assertion needs source review; external knowledge is not used to fill gaps.</p>
    {latest&&<p>Last explanation update: {latest.status} · {Object.entries(latest.counts).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ')}</p>}
    <button disabled={busy||!project.concepts.length} onClick={()=>run(()=>api(projectPath(project)+'/ai/explanations','POST',{revision:project.revision}),'Explanation update saved. Review sources, conflicts and incomplete items.')}>Supplement / update explanations</button>
  </section>;
}

export function Explanations({project,concept,run,busy}) {
  const explanation=concept.explanation;
  return <section className="explanations"><h2>Explanation and supporting sources</h2>
    {!explanation&&<p>{concept.definition?'Legacy model suggestion — unverified.':'No sourced explanation yet.'}</p>}
    {concept.definition&&!explanation&&<blockquote>{concept.definition}</blockquote>}
    {explanation&&<>
      <p><strong>{({needs_review:'Needs evidence review',conflict:'Conflicting explanations — decision required',partial:'Partially completed',not_found:'No supported explanation found'})[explanation.status]||explanation.status}</strong></p>
      <p>{explanation.reason}</p>
      {explanation.relationship==='complementary'&&<p>Model proposes complementary details; sources are combined below without replacing their individual claims.</p>}
      {explanation.relationship==='uncertain'&&<p>Compatibility is uncertain. Keep explanations separate until reviewed.</p>}
      <p className="muted">Source ranges checked: {explanation.scanned}/{explanation.total}. Exact quotations establish location, not semantic correctness. Model transcriptions need comparison with the original.</p>
      {explanation.issues?.map((issue,i)=><p role="status" className="callout" key={i}>{issue}</p>)}
      {!explanation.claims.length&&<p>No evidence-backed claims retained. Do not substitute the legacy model suggestion for a sourced explanation.</p>}
      {!explanation.claims.length&&explanation.missing_reasons?.map((reason,i)=><p className="muted" key={i}>{reason}</p>)}
      {explanation.claims.map(claim=><Claim key={claim.id+':'+project.revision} {...{project,concept,claim,run,busy}}/>)}
    </>}
  </section>;
}

function Claim({project,concept,claim,run,busy}) {
  const [decision,setDecision]=useState(claim.review||'pending'),[note,setNote]=useState(claim.review_note||'');
  const stale=claim.evidence.some(e=>{
    const doc=project.documents.find(d=>d.id===e.doc_id),block=doc?.blocks.find(b=>b.id===e.block_id);
    return !block||sourceSlice(block.text,e.start,e.end)!==e.quote;
  });
  async function save(){await run(()=>api(projectPath(project)+'/explanations/'+concept.id,'PUT',{
    revision:project.revision,claim_id:claim.id,decision,note
  }),'Explanation claim review saved. Document text is unchanged.');}
  return <article className="explanation-claim">
    <strong>{claim.kind==='explicit'?'Document statement (model identified)':'Synthesis from document evidence (model inference)'} · {claim.review||'pending'}</strong>
    {claim.previous_retained&&<p>Retained from an earlier update; this update is incomplete.</p>}
    <p>{claim.statement}</p>{stale&&<p role="alert">Source text changed. Update explanations before accepting this claim.</p>}
    {claim.evidence.map((e,i)=>{
      const doc=project.documents.find(d=>d.id===e.doc_id);
      return <div className="explanation-source" key={i}><strong>{e.role} · {doc?.name} · {doc?.format==='docx'?'DOCX unit '+e.page:'PDF p'+e.page} · {e.region}</strong>
        <blockquote>{e.quote}</blockquote><p className="muted">Proposed support: {e.support}</p>
        {e.evidence_kind==='visual_transcription'&&<p>Visually unverified model transcription — check the original.</p>}
        {e.text_version==='working_after_edits'&&<p>Quote from current project text after approved edits. The immutable original retains its earlier wording.</p>}
        <a href={downloadPath(project,`/documents/${e.doc_id}/source`)+`#page=${e.page}`} target="_blank" rel="noreferrer">View explanation source</a>
        <details><summary>Exact text location</summary><p>Block {e.block_id} · Unicode characters {e.start}–{e.end}</p></details>
      </div>;
    })}
    <label>Explanation review<select aria-label="Explanation review" value={decision} onChange={e=>setDecision(e.target.value)}><option value="pending">Pending</option><option value="accepted" disabled={stale}>Accepted by reviewer</option><option value="rejected">Rejected by reviewer</option></select></label>
    <label>Explanation review note<textarea aria-label="Explanation review note" value={note} onChange={e=>setNote(e.target.value)} maxLength={2000}/></label>
    <button disabled={busy||(stale&&decision==='accepted')} onClick={save}>Save explanation review</button>
  </article>;
}
