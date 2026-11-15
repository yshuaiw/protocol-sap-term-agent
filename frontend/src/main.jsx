import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

import {api} from './api';
import {ImportForm} from './ImportForm';
import {Registry} from './Registry';
import {Review} from './Review';
import {Coverage, History} from './ProjectDetails';
import {ApiSettings} from './ApiSettings';
import {projectPath} from './paths';

function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
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
  async function select(id){setSettingsOpen(false);await run(()=>api('/projects/' + id)); setTab('registry');}
  async function transfer(event) {
    const file = event.target.files[0]; if(!file)return;
    const form = new FormData(); form.append('file',file);
    setSettingsOpen(false);
    await run(()=>api('/bundles','POST',form),'Project imported with its original PDFs and history.');
    event.target.value='';
  }
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand">Protocol / SAP<span>Terminology workspace</span></div>
      <button className="primary new-project" onClick={()=>{setSettingsOpen(false);setImporting(true);setError('');setNotice('');}}>Import documents</button>
      <label className="file-button">Open project bundle<input aria-label="Open project bundle" type="file" accept=".zip" onChange={transfer} disabled={busy}/></label>
      <button className="settings-button" disabled={busy} onClick={()=>{setSettingsOpen(true);setError('');setNotice('');}}>API settings</button>
      <h2 className="sidebar-heading">Saved projects</h2>
      <div className="project-list">{projects.length ? projects.map(p=><button key={p.id} className={project?.id===p.id&&!importing?'project-item selected':'project-item'} onClick={()=>select(p.id)} disabled={busy}><strong>{p.name}</strong><span>Revision {p.revision} · {new Date(p.updated).toLocaleDateString()}</span></button>):<p className="muted">Your projects will stay on this computer until you export a bundle.</p>}</div>
      <div className="sidebar-bottom">Local workspace · v0.2<br/>AI services · explicit actions</div>
    </aside>
    <main aria-busy={busy}>
      <header className="topbar"><div>{settingsOpen?'API settings':importing?'New project':project?.name||'Your workspace'}</div>{project&&!importing&&!settingsOpen&&<span>Revision {project.revision}<button onClick={()=>run(()=>api(projectPath(project)))} disabled={busy}>Reload</button></span>}</header>
      {error&&<div role="alert" className="alert error">{error}<button onClick={()=>setError('')} aria-label="Dismiss error">×</button></div>}
      {notice&&<div role="status" className="alert success">{notice}</div>}
      {busy&&<div role="status" className="busy">Processing locally. Large documents and Word exports may take a few minutes…</div>}
      {settingsOpen?<div className="content"><ApiSettings onClose={()=>setSettingsOpen(false)}/></div>:importing?<ImportForm run={run} busy={busy}/>:project?<>
        <nav className="tabs" aria-label="Workflow">{[['registry','Terminology register'],['review','Replacement review'],['coverage','Documents & coverage'],['history','History & transfer']].map(([key,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}>{label}</button>)}</nav>
        <div className="content">{tab==='registry'?<Registry project={project} run={run} busy={busy} onReview={cid=>{setReviewConcept(cid);setTab('review');}}/>:tab==='review'?<Review project={project} run={run} busy={busy} initialConcept={reviewConcept}/>:tab==='coverage'?<Coverage project={project}/>:<History project={project} run={run} busy={busy}/>}</div>
      </>:<div className="welcome"><h1>Keep terminology consistent across documents.</h1><p>Import a Protocol and an independent SAP as PDF or DOCX. Review the terminology register, approve each proposed change, then export separate Word copies.</p><button className="primary" onClick={()=>setImporting(true)}>Start with your documents</button><div className="welcome-note"><strong>Prepared for local review</strong><p>Original files, registry corrections and approval history stay together. Export a project bundle to continue on another computer.</p></div></div>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
