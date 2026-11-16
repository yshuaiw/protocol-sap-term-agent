// Real browser + real local persistence. Model content/delays are deliberately simulated.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
  const base=process.env.DEMO_URL||'http://127.0.0.1:8766',out=path.resolve('output/cancellation-explanations-ui');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    const api=async(url,method='GET',data)=>{
      const r=await page.request.fetch(base+'/api'+url,{method,...(data?{data}: {})});
      assert.equal(r.ok(),true,await r.text());return r.json();
    };
    assert.equal((await api('/offline-fixture')).simulation,true);
    const control=data=>api('/workflow-fixture','POST',data);
    async function until(predicate){const deadline=Date.now()+20000;while(!await predicate()){assert.ok(Date.now()<deadline,'Timed out waiting for server state');await new Promise(r=>setTimeout(r,100));}}
    const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
    async function create(label){
      await page.goto(base);await page.getByRole('button',{name:'Import documents',exact:true}).click();
      const name='Cancellation explanations '+label+' '+Date.now();
      await page.getByLabel('Project name').fill(name);
      await page.getByLabel('Select PDF or DOCX files').setInputFiles(['tmp/fixtures/Protocol.pdf','tmp/fixtures/SAP.pdf']);
      await page.getByText('Review document boundaries',{exact:true}).waitFor();
      await page.getByLabel('Version and boundary review note').fill('Synthetic browser fixture.');
      await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Import and save originals'}).click();
      await page.getByRole('heading',{name:'Terminology register',exact:true}).waitFor();
      return (await api('/projects')).find(p=>p.name===name);
    }
    async function generate(){
      await page.getByRole('button',{name:'Generate AI register and links'}).click();
    }
    async function saved(){await page.getByRole('status').filter({hasText:'AI run saved'}).waitFor();}
    await control({mode:'conflict'});
    let p=await create('conflict');await generate();await saved();
    await page.getByText('Conflicting explanations — decision required',{exact:true}).waitFor();
    assert.ok(await page.getByRole('link',{name:'View explanation source',exact:true}).count()>=2);
    await page.locator('.explanations').scrollIntoViewIfNeeded();await shot('01-sourced-conflict');await page.locator('.explanations').screenshot({path:path.join(out,'10-explanation-panel-desktop.png')});
    await page.getByLabel('Explanation review',{exact:true}).first().selectOption('accepted');
    await page.getByLabel('Explanation review note',{exact:true}).first().fill('Synthetic reviewer checked the quoted assertion.');
    await page.getByRole('button',{name:'Save explanation review',exact:true}).first().click();
    await page.getByRole('status').filter({hasText:'Explanation claim review saved'}).waitFor();
    assert.equal((await api('/projects/'+p.id)).concepts[0].explanation.claims[0].review,'accepted');
    await shot('02-human-claim-review');
    const count=(await api('/workflow-fixture')).calls.length;
    await page.reload();await page.locator(`[data-project-id="${p.id}"] .project-item`).click();
    await page.getByRole('heading',{name:'Explanation and supporting sources'}).waitFor();
    assert.equal((await api('/workflow-fixture')).calls.length,count,'Opening a project must not call a model');
    await page.getByRole('button',{name:'Supplement / update explanations'}).click();
    await page.getByRole('status').filter({hasText:'Explanation update saved'}).waitFor();
    await page.setViewportSize({width:390,height:844});await page.locator('.explanations').scrollIntoViewIfNeeded();
    await shot('03-mobile-explanations');await page.locator('.explanations').screenshot({path:path.join(out,'11-explanation-panel-mobile.png')});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.setViewportSize({width:1440,height:1000});
    await control({mode:'partial'});p=await create('partial');await generate();await saved();
    await page.getByText('Partially completed',{exact:true}).waitFor();assert.ok((await api('/projects/'+p.id)).concepts.length);
    await page.locator('.explanations').scrollIntoViewIfNeeded();await shot('04-partial-register-retained');
    await control({mode:'missing'});p=await create('missing');await generate();await saved();
    await page.getByText('No supported explanation found',{exact:true}).waitFor();
    await page.locator('.explanations').scrollIntoViewIfNeeded();await shot('05-no-definition-evidence');
    await control({delay_stage:'explanation_scan',delay:7});p=await create('cancel');
    const original=await api('/projects/'+p.id);await generate();
    await page.getByRole('button',{name:'Cancel LLM operation',exact:true}).waitFor();
    await until(async()=>(await api('/operations')).some(o=>o.stage==='explanation_scan'));
    await page.reload();await page.getByRole('button',{name:'Cancel LLM operation',exact:true}).waitFor();
    await shot('06-refreshed-active-task');
    await page.getByRole('button',{name:'Cancel LLM operation',exact:true}).click();
    await page.getByRole('button',{name:'Cancelling…',exact:true}).waitFor();await shot('07-cancellation-pending');
    await until(async()=>(await api('/operations')).length===0);
    const cancelled=await api('/projects/'+p.id);
    assert.deepEqual(cancelled,original,'Cancelled generation leaves the project and history unchanged');
    assert.equal((await api('/workflow-fixture')).calls.filter(s=>s==='explanation_relation').length,0,'No late next-stage calls');
    await page.locator(`[data-project-id="${p.id}"] .project-item`).click();
    await generate();await page.getByRole('button',{name:'Cancel LLM operation',exact:true}).waitFor();
    await until(async()=>(await api('/operations')).some(o=>o.stage==='explanation_scan'));
    await page.locator(`[data-project-id="${p.id}"] .project-delete-trigger`).click();
    await page.getByRole('button',{name:'Cancel tasks and permanently delete',exact:true}).waitFor();await shot('08-cancel-delete-confirmation');
    await page.getByRole('button',{name:'Cancel tasks and permanently delete',exact:true}).click();
    await page.getByText('Cancelling LLM work; waiting to delete project files…',{exact:true}).waitFor();
    assert.ok((await api('/projects')).some(x=>x.id===p.id));
    await page.getByRole('status').filter({hasText:'Project permanently deleted'}).waitFor();
    assert.equal((await api('/projects')).some(x=>x.id===p.id),false);await shot('09-deletion-completed');
    assert.deepEqual(errors,[],'No browser errors in normal cancellation/explanation flows');
    console.log('PASS OFFLINE: sourced claims/review/conflict/missing/partial, no calls on open, refresh survival, cancellation and cancel-delete; mobile no overflow.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
