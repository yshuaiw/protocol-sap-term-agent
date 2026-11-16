import React, {useEffect, useRef, useState} from 'react';
import {api} from './api';

export function ProjectDeleteDialog({projectId, onClose, onDeleted}) {
  const dialog = useRef(null);
  const [details, setDetails] = useState(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(true), [deleting, setDeleting] = useState(false);
  async function reload() {
    setLoading(true); setError(''); setDetails(null);
    try {setDetails(await api(`/projects/${projectId}/deletion`));}
    catch(e) {setError(e.message);} finally {setLoading(false);}
  }
  useEffect(()=>{dialog.current.showModal(); reload();}, [projectId]);
  async function remove() {
    setDeleting(true); setError('');
    try {
      await api(`/projects/${projectId}`, 'DELETE', {revision:details.revision, confirmed:true});
      onDeleted(projectId);
    } catch(e) {
      setDetails(null); setError(e.message);
    } finally {setDeleting(false);}
  }
  return <dialog ref={dialog} className="delete-dialog" aria-labelledby="delete-project-title" onCancel={e=>{e.preventDefault();if(!deleting)onClose();}}>
    <h2 id="delete-project-title">Permanently delete project?</h2>
    {loading && <p role="status">Loading project details…</p>}
    {error && <p className="alert error" role="alert">{error}</p>}
    {details && <>
      <dl className="delete-details">
        <dt>Project</dt><dd>{details.name}</dd>
        <dt>Project ID</dt><dd><code>{details.id}</code></dd>
        {details.first_saved && <><dt>First saved</dt><dd>{new Date(details.first_saved).toLocaleString()}</dd></>}
        <dt>Last updated</dt><dd>{new Date(details.updated).toLocaleString()}</dd>
      </dl>
      <ul className="delete-documents">{details.documents.map((d,i)=><li key={i}><strong>{d.role}</strong>: {d.name}</li>)}</ul>
      <p>{details.concepts} concepts · {details.occurrences} occurrences · {details.snapshots} history snapshots · {details.exports} exports</p>
      <p>This permanently removes the register, all history, AI cache and run records, previews and approvals, generated files, and source copies stored in this project.</p>
      <p>External originals, downloaded ZIP/Word files, other projects and API settings are kept. <strong>You cannot undo this in the app.</strong></p>
    </>}
    {deleting && <p role="status">Deleting project files…</p>}
    <div className="actions delete-actions">
      <button type="button" autoFocus disabled={deleting} onClick={onClose}>Cancel</button>
      {!details && !loading && <button type="button" disabled={deleting} onClick={reload}>Refresh project details</button>}
      <button type="button" className="danger" disabled={loading || deleting || !details} onClick={remove}>Permanently delete</button>
    </div>
  </dialog>;
}
