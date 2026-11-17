import React, {useEffect, useRef, useState} from 'react';
import {api} from './api';
const names={'ai/generate':'Register generation','ai/explanations':'Explanation update','ai/interpret':'Naming request interpretation','ai/audit':'Semantic audit','plans':'Replacement review'};

export function OperationPanel({onSettled,onActivity}) {
  const [operations,setOperations]=useState([]),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const previous=useRef([]),callback=useRef(onSettled),requested=useRef(new Set());
  const activity=useRef(onActivity);activity.current=onActivity;
  callback.current=onSettled;
  useEffect(()=>{
    let alive=true,loading=false;
    async function poll(){
      if(loading)return;loading=true;
      try{
        const current=await api('/operations');
        if(!alive)return;
        const ended=previous.current.filter(o=>!current.some(n=>n.id===o.id));
        if(ended.length){
          if(ended.some(o=>requested.current.has(o.id)||o.status==='cancelling'))setNotice('LLM operation stopped. Cancelled work was discarded; an operation that finished before cancellation keeps its saved result.');
          ended.forEach(o=>requested.current.delete(o.id));
          Promise.resolve(callback.current?.(ended)).catch(e=>{if(alive)setError(e.message);});
        }
        previous.current=current;setOperations(current);activity.current?.(current);setError('');
      }catch(e){if(alive)setError(e.message);}finally{loading=false;}
    }
    poll();const timer=setInterval(poll,700);
    return()=>{alive=false;clearInterval(timer);};
  },[]);
  async function cancel(op){
    try{
      const result=await api('/operations/cancel','POST',{ids:[op.id]});
      if(result.accepted[op.id]){
        requested.current.add(op.id);setOperations(old=>old.map(o=>o.id===op.id?{...o,status:'cancelling'}:o));
        setNotice('Cancellation requested. Waiting for local work to stop and discard new results/cache.');
      }else setNotice('Cancellation was not accepted: the operation finished or is saving. Reload to check its result.');
    }catch(e){setError(e.message);}
  }
  if(!operations.length&&!error&&!notice)return null;
  return <section className="operation-panel" aria-label="LLM operations">
    {operations.length>0&&<><strong>Active LLM operations</strong><p>Only explicit cancellation stops these tasks. Refreshing or closing the page keeps them running. Submitted requests may still consume tokens; spent tokens cannot be recovered.</p></>}
    {operations.map(op=><div className="operation-row" key={op.id}>
      <span>{names[op.kind]||op.kind} · {op.stage.replaceAll('_',' ')} · {op.status}{op.project_id&&<small>{op.project_name||'Project'} · {op.project_id.slice(0,8)}</small>}{op.progress?.candidates_total != null && <small>Linking: {op.progress.candidates_completed}/{op.progress.candidates_total} candidates · Index pages {op.progress.index_pages_current_checked||0}/{op.progress.index_pages_current||0} · Cache hits {op.progress.cache_hits||0} · HTTP attempts {op.progress.http_attempts||0}</small>}</span>
      <button disabled={op.status!=='running'} onClick={()=>cancel(op)}>{op.status==='cancelling'?'Cancelling…':op.status==='finishing'?'Saving…':'Cancel LLM operation'}</button>
    </div>)}
    {notice&&<p role="status">{notice}<button aria-label="Dismiss operation notice" onClick={()=>setNotice('')}>×</button></p>}
    {error&&<p role="alert">Unable to check LLM operations: {error}</p>}
  </section>;
}
