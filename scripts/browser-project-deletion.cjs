// Deletes only projects created by this script on the offline fixture server.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

const digest=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function inventory(folder) {
  return Object.fromEntries(fs.readdirSync(folder,{recursive:true,withFileTypes:true})
    .filter(item=>item.isFile()).map(item=>{
      const full=path.join(item.parentPath || item.path,item.name);
      return [path.relative(folder,full),digest(full)];
    }));
}

(async()=>{
  const base=process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out=path.resolve('output/project-deletion-ui');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    const second=await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[],expected404=[],expected409=[];
    for(const p of [page,second]) {
      p.on('pageerror',e=>errors.push(e.message));
      p.on('console',m=>{if(m.type()==='error') {
        if(m.text().includes('404 (Not Found)'))expected404.push(m.text());
        else if(m.text().includes('409 (Conflict)'))expected409.push(m.text());else errors.push(m.text());
      }});
    }
    const fixture=await page.request.get(base+'/api/offline-fixture');
    assert.equal(fixture.status(),200,'Use scripts/serve-offline-fixture.py only');
    assert.equal((await fixture.json()).simulation,true);
    const root=path.resolve('tmp/offline-ui-projects');
    const sourceFiles=['tmp/fixtures/Protocol.pdf','tmp/fixtures/SAP.pdf'];
    const originalHashes=sourceFiles.map(digest);
    const name='Deletion UI fixture '+Date.now();
    async function request(method,route,data) {
      const r=await page.request.fetch(base+'/api'+route,{method,data});
      assert.equal(r.status(),200,await r.text());return r.json();
    }
    // Playwright multipart maps cannot represent duplicate names reliably; use a raw form.
    async function importPair() {
      const boundary='DeletionFixture'+Date.now();
      const parts=[];
      for(const [key,value] of Object.entries({name,version_note:'Synthetic deletion verification.',
        selections:JSON.stringify(['Protocol','SAP'].map((role,i)=>({role,file_index:i,start:1,end:1})))})) {
        parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${key}"\r\n\r\n${value}\r\n`));
      }
      sourceFiles.forEach((file,i)=>{parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${['Protocol.pdf','SAP.pdf'][i]}"\r\nContent-Type: application/pdf\r\n\r\n`),fs.readFileSync(file),Buffer.from('\r\n'));});
      parts.push(Buffer.from(`--${boundary}--\r\n`));
      const r=await page.request.post(base+'/api/projects',{headers:{'content-type':`multipart/form-data; boundary=${boundary}`},data:Buffer.concat(parts)});
      assert.equal(r.status(),200,await r.text());return r.json();
    }
    let project=await importPair();
    const route='/projects/'+project.id;
    project=await request('POST',route+'/ai/generate',{revision:project.revision,pdf_mode:'text'});
    const concept=project.concepts.find(c=>c.name==='Arm A');assert.ok(concept);
    project=await request('PUT',route+'/concepts/'+concept.id,{revision:project.revision,name:concept.name,
      category:concept.category,aliases:concept.aliases,confirmed:true});
    project=await request('POST',route+'/plans',{revision:project.revision,concept_id:concept.id,mode:'rules',mappings:{'Arm A':'Investigational Arm A'}});
    const plan=project.plans.at(-1),approved=plan.items.filter(i=>i.proposal==='update').map(i=>i.id);
    assert.ok(approved.length);
    project=await request('POST',route+'/plans/'+plan.id+'/apply',{revision:project.revision,approved_ids:approved,coverage_acknowledged:true});
    const bundle=await page.request.get(base+'/api'+route+'/bundle');assert.equal(bundle.status(),200);
    const externalBundle=path.join(out,'saved-copy.zip');fs.writeFileSync(externalBundle,await bundle.body());
    const bundleHash=digest(externalBundle);
    const neighbor=await importPair();
    const neighborBefore=inventory(path.join(root,neighbor.id)),targetBefore=inventory(path.join(root,project.id));
    assert.ok(targetBefore['project.json']);
    assert.ok(Object.keys(targetBefore).some(f=>f.startsWith('exports')));
    await page.goto(base);
    const row=p=>p.locator(`[data-project-id="${project.id}"]`);
    await row(page).getByRole('button').filter({has:page.locator('strong',{hasText:name})}).click();
    await page.getByRole('heading',{name:'Terminology register',exact:true}).waitFor();
    const deleteButton=p=>row(p).getByRole('button',{name:'Delete project '+name,exact:true});
    await deleteButton(page).click();
    const dialog=page.getByRole('dialog',{name:'Permanently delete project?'});
    await dialog.getByText(project.id,{exact:true}).waitFor();
    await dialog.getByText(`${project.concepts.length} concepts · ${project.mentions.length} occurrences`,{exact:false}).waitFor();
    await page.screenshot({path:path.join(out,'01-desktop-confirmation.png')});
    await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
    assert.deepEqual(inventory(path.join(root,project.id)),targetBefore,'Cancel preserves all internal files');
    const previewPattern='**/api'+route+'/deletion';
    await page.route(previewPattern,r=>r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({
      detail:'This project has an active operation. Wait for it to finish before deleting.'})}));
    await deleteButton(page).click();
    await dialog.getByRole('alert').filter({hasText:'active operation'}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Permanently delete',exact:true}).isDisabled(),true);
    await page.screenshot({path:path.join(out,'03-busy-refusal.png')});
    await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
    await page.unroute(previewPattern);
    assert.deepEqual(inventory(path.join(root,project.id)),targetBefore);
    await second.goto(base);
    await row(second).getByRole('button').filter({has:second.locator('strong',{hasText:name})}).click();
    await second.getByRole('heading',{name:'Terminology register',exact:true}).waitFor();
    await page.setViewportSize({width:390,height:844});
    await deleteButton(page).click();await dialog.getByText(project.id,{exact:true}).waitFor();
    await page.screenshot({path:path.join(out,'02-mobile-confirmation.png')});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.ok(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),'Dialog content wraps without horizontal scrolling');
    await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
    await page.setViewportSize({width:1440,height:1050});
    await deleteButton(page).click();await dialog.getByText(project.id,{exact:true}).waitFor();
    const currentConcept=project.concepts.find(c=>c.id===concept.id);
    project=await request('PUT',route+'/concepts/'+concept.id,{revision:project.revision,name:currentConcept.name,
      category:currentConcept.category,aliases:currentConcept.aliases,confirmed:currentConcept.confirmed,note:'Second-tab fixture edit after deletion preview.'});
    await dialog.getByRole('button',{name:'Permanently delete',exact:true}).click();
    await dialog.getByRole('alert').filter({hasText:'changed after the deletion preview'}).waitFor();
    assert.ok(fs.existsSync(path.join(root,project.id)),'Stale confirmation cannot delete the newer project');
    assert.equal(await dialog.getByRole('button',{name:'Permanently delete',exact:true}).isDisabled(),true);
    await page.screenshot({path:path.join(out,'04-stale-confirmation.png')});
    await dialog.getByRole('button',{name:'Refresh project details',exact:true}).click();
    await dialog.getByText(project.id,{exact:true}).waitFor();
    await dialog.getByRole('button',{name:'Permanently delete',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Project permanently deleted'}).waitFor();
    await page.getByRole('heading',{name:'Keep terminology consistent across documents.'}).waitFor();
    assert.equal(fs.existsSync(path.join(root,project.id)),false);
    assert.equal(await row(page).count(),0);
    assert.equal(await page.locator(`[data-project-id="${neighbor.id}"]`).count(),1);
    assert.deepEqual(inventory(path.join(root,neighbor.id)),neighborBefore);
    assert.equal(digest(externalBundle),bundleHash);assert.deepEqual(sourceFiles.map(digest),originalHashes);
    await page.screenshot({path:path.join(out,'05-project-removed.png'),fullPage:true});
    await second.getByRole('button',{name:'Reload',exact:true}).click();
    await second.getByRole('alert').filter({hasText:'Project no longer exists'}).waitFor();
    await second.getByRole('heading',{name:'Keep terminology consistent across documents.'}).waitFor();
    await row(second).waitFor({state:'detached'});
    assert.equal(await row(second).count(),0);
    await second.screenshot({path:path.join(out,'06-stale-tab.png'),fullPage:true});
    assert.ok(expected404.length<=2,'Only the deleted-project reload can produce expected HTTP 404 console notices');
    assert.ok(expected409.length<=2,'Only the intentional busy preview/stale confirmation can produce HTTP 409 notices');
    assert.deepEqual(errors,[],'No unexpected browser console/page errors');
    console.log(JSON.stringify({result:'PASS OFFLINE',deleted_project:project.id,retained_same_name_project:neighbor.id,
      cancelled_files_unchanged:true,deleted_folder_absent:true,neighbor_and_downloads_unchanged:true,stale_tab_cleared:true,
      busy_preview_simulated:true,stale_confirmation_rejected:true,expected_http404_notices:expected404.length,
      expected_http409_notices:expected409.length,unexpected_browser_errors:errors,simulation:true,live_model_calls:0}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
