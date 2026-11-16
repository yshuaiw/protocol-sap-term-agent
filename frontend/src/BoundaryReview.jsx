import React, {useEffect, useState} from 'react';

function Candidate({document:d, fileIndex, sourceUrl, onUse, onVerified, visualChecked, busy}) {
  const allowed=!busy && d.applicable && (!d.requires_visual_review || visualChecked);
  return <article className="boundary-candidate">
    <div className="section-header"><strong>{d.role} · {d.start}–{d.end}</strong><span className="muted">{d.kind.replaceAll('_',' ')} · {d.confidence} confidence</span></div>
    <p>{d.reason}</p>
    {d.kind === 'embedded_section' && <p className="callout">This is a section inside another document. It cannot be used as an independent SAP.</p>}
    {d.kind === 'uncertain' && <p className="callout">The boundary is uncertain. Check the source and adjust the manual ranges.</p>}
    <details><summary>Source evidence · {d.evidence_kind === 'visual_transcription' ? 'visual transcription, unverified' : 'exact native text'} · page {d.start}</summary><p>{d.evidence}</p></details>
    <div className="actions">{sourceUrl && <a href={sourceUrl+`#page=${d.start}`} target="_blank" rel="noreferrer">Open original at page {d.start}</a>}</div>
    {d.requires_visual_review && <label className="checkbox"><input type="checkbox" checked={visualChecked} onChange={e=>onVerified(d.source_id,e.target.checked)}/>I checked this visual transcription and its page against the original.</label>}
    {d.applicable && <button type="button" disabled={!allowed} onClick={()=>onUse([{role:d.role,file_index:fileIndex,start:d.start,end:d.end}])}>Use suggested {d.role} range</button>}
  </article>;
}

export function BoundaryReview({files, info, onUse, busy}) {
  const [urls,setUrls]=useState([]),[verified,setVerified]=useState({});
  useEffect(()=>{
    const next=files.map(file=>URL.createObjectURL(file));setUrls(next);
    return ()=>next.forEach(url=>URL.revokeObjectURL(url));
  },[files]);
  useEffect(()=>{setVerified({});},[info]);
  const hasResults=info.some(x=>x.ai_suggestion);
  return <section className="boundary-review" aria-label="AI boundary review">
    {hasResults && <h3>AI boundary review</h3>}
    {info.map((item,i)=>{
      const result=item.ai_suggestion;
      if(!result)return null;
      const coverage=result.coverage, pair=result.documents.filter(d=>d.applicable);
      const visualReady=pair.every(d=>!d.requires_visual_review || verified[`${i}:${d.source_id}`]);
      return <div key={i} className="boundary-file">
        <h3>{files[i].name}</h3>
        <p><strong>{result.can_apply_pair ? 'Protocol/SAP pair proposed — source review required' : 'Manual review needed — no complete independent pair confirmed'}</strong></p>
        {coverage && <p className="muted">{coverage.pages_indexed} pages indexed · {coverage.native_readable_pages} with native text · {coverage.visual_pages_read.length} visually read · {coverage.unreadable_pages.length} still unreadable. Structure excerpts were used; this is not full-text or version-compatibility certification.</p>}
        <p>{result.compatibility_note}</p>
        {!!result.issues?.length && <div className="callout"><strong>Rejected or conflicting proposals</strong>{result.issues.map((issue,j)=><p key={j}>{issue}</p>)}</div>}
        {!!result.limitations?.length && <details open><summary>Coverage and interpretation limits</summary>{result.limitations.map((limit,j)=><p key={j}>{limit}</p>)}</details>}
        {!result.documents.length && <p className="callout">No usable range suggestions were produced. This does not establish that an independent SAP is absent. Review unreadable pages, select ranges manually, or supply a separate SAP.</p>}
        {result.documents.map((d,j)=><Candidate key={`${d.source_id}:${j}`} document={d} fileIndex={i} sourceUrl={urls[i]} onUse={onUse} busy={busy} visualChecked={!!verified[`${i}:${d.source_id}`]}
          onVerified={(id,value)=>setVerified(v=>({...v,[`${i}:${id}`]:value}))}/>)}
        {result.can_apply_pair && <button type="button" className="primary" disabled={busy || !visualReady} onClick={()=>onUse(pair.map(d=>({role:d.role,file_index:i,start:d.start,end:d.end})))}>Use suggested Protocol/SAP pair</button>}
      </div>;
    })}
    <details><summary>Local title and structure excerpts</summary>{info.map((item,i)=><div key={i}><h3>{files[i].name}</h3>{!item.boundary_hints.length && <p>No native title clues were extracted; inspect source readability.</p>}{item.boundary_hints.map((hint,j)=><p key={j}><strong>Source page {hint.page}</strong><br/>{hint.evidence}</p>)}</div>)}</details>
  </section>;
}
