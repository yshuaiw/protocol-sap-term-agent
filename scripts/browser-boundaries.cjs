// Offline fixture only. Native parsing/import are real; model answers are scripted.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

(async()=>{
  const base=process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out=path.resolve('output/boundary-ui');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],expectedErrors=[];
    let injectingRateLimit=false;
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{
      if(m.type()==='error') {
        if(injectingRateLimit && /Failed to load resource.*429/.test(m.text()))expectedErrors.push(m.text());
        else errors.push(m.text());
      }
    });
    const fixture=await page.request.get(base+'/api/offline-fixture');
    assert.equal(fixture.status(),200,'Use the isolated offline fixture server only');assert.equal((await fixture.json()).simulation,true);
    const combined=path.resolve('tmp/boundary-fixtures/combined.pdf');
    const sourceHash=crypto.createHash('sha256').update(fs.readFileSync(combined)).digest('hex');
    const first=page.getByLabel('First unit',{exact:true}),last=page.getByLabel('Last unit',{exact:true});
    async function open(file) {
      await page.getByRole('button',{name:'Import documents',exact:true}).click();
      await page.getByLabel('Select PDF or DOCX files').setInputFiles(file);
      await page.getByRole('heading',{name:'Review document boundaries',exact:true}).waitFor();
    }
    async function ask() {
      await page.getByRole('button',{name:'Ask AI for boundary suggestions',exact:true}).click();
      await page.getByRole('heading',{name:'AI boundary review',exact:true}).waitFor();
    }
    await page.goto(base);await open(combined);
    assert.equal(await last.nth(0).inputValue(),'6');assert.equal(await first.nth(1).inputValue(),'1');
    assert.equal(await page.getByRole('button',{name:'Import and save originals',exact:true}).isDisabled(),true);
    const firstResult=page.waitForResponse(r=>r.url().endsWith('/api/inspect/ai'));
    await ask();const baseline=await(await firstResult).json();
    await page.getByRole('button',{name:'Use suggested Protocol/SAP pair',exact:true}).waitFor();
    assert.equal(await last.nth(0).inputValue(),'6','AI results never silently change selections');
    assert.equal(await first.nth(1).inputValue(),'1');
    assert.equal(await page.getByText(/AI boundary suggestions are ready for your review/).count(),0);
    await page.screenshot({path:path.join(out,'01-visible-pair-proposals.png'),fullPage:true});
    await page.getByRole('button',{name:'Use suggested Protocol/SAP pair',exact:true}).click();
    assert.equal(await last.nth(0).inputValue(),'3');assert.equal(await first.nth(1).inputValue(),'4');
    const name='Combined boundary UI fixture '+Date.now();
    await page.getByLabel('Project name',{exact:true}).fill(name);
    await page.getByLabel('Version and boundary review note').fill('Synthetic independent protocol 1-3 and SAP 4-6; user-selected ranges.');
    await page.getByRole('checkbox',{name:/I checked independent documents/}).check();
    await page.getByRole('button',{name:'Import and save originals',exact:true}).click();
    await page.getByRole('heading',{name:'Terminology register',exact:true}).waitFor();
    const listed=await(await page.request.get(base+'/api/projects')).json();
    const saved=listed.find(p=>p.name===name);assert.ok(saved);
    const project=await(await page.request.get(base+'/api/projects/'+saved.id)).json();
    assert.deepEqual(project.documents.map(d=>[d.role,d.start,d.end]),[['Protocol',1,3],['SAP',4,6]]);
    assert.ok(project.documents.every(d=>d.sha256===sourceHash));
    await open('tmp/boundary-fixtures/unclassified.pdf');await ask();
    await page.getByRole('status').filter({hasText:/^No usable independent-document ranges returned/}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Use suggested Protocol/SAP pair',exact:true}).count(),0);
    await page.screenshot({path:path.join(out,'02-empty-result-is-not-success.png'),fullPage:true});
    await open(combined);
    const pattern='**/api/inspect/ai';
    await page.route(pattern,async route=>{
      const body=structuredClone(baseline);
      const sap=body.ai_suggestion.documents.find(d=>d.role==='SAP');
      Object.assign(sap,{kind:'embedded_section',applicable:false,reason:'SIMULATED UI STATE: numbered statistics chapter, not a separate SAP.'});
      Object.assign(body.ai_suggestion,{can_apply_pair:false,status:'needs_review'});
      await route.fulfill({status:200,json:body});
    });
    await ask();await page.getByText('This is a section inside another document. It cannot be used as an independent SAP.').waitFor();
    assert.equal(await page.getByRole('button',{name:'Use suggested SAP range',exact:true}).count(),0);
    await page.screenshot({path:path.join(out,'03-embedded-section-not-a-sap.png'),fullPage:true});
    await page.unroute(pattern);await open(combined);
    await page.route(pattern,async route=>{
      const body=structuredClone(baseline);
      Object.assign(body.ai_suggestion.documents[0],{requires_visual_review:true,evidence_kind:'visual_transcription'});
      await route.fulfill({status:200,json:body});
    });
    await ask();
    const apply=page.getByRole('button',{name:'Use suggested Protocol/SAP pair',exact:true});
    assert.equal(await apply.isDisabled(),true);
    const check=page.getByRole('checkbox',{name:/I checked this visual transcription/});
    await check.check();await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='Use suggested Protocol/SAP pair' && !b.disabled));
    assert.equal(await apply.isEnabled(),true);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'04-mobile-visual-review-required.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await apply.click();assert.equal(await first.nth(1).inputValue(),'4');
    assert.equal(await page.getByRole('checkbox',{name:/I checked independent documents/}).isChecked(),false);
    await page.unroute(pattern);injectingRateLimit=true;
    await page.route(pattern,route=>route.fulfill({status:429,json:{detail:'SIMULATED provider quota error; no fallback used.'}}));
    await page.getByRole('button',{name:'Ask AI for boundary suggestions',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'SIMULATED provider quota error'}).waitFor();
    assert.equal(await apply.count(),0,'Failed reruns must not expose stale applicable proposals');
    assert.equal(await first.nth(1).inputValue(),'4','A failure preserves manually applied ranges');
    await page.screenshot({path:path.join(out,'05-failure-keeps-ranges-clears-proposals.png'),fullPage:true});
    assert.equal(expectedErrors.length,1,'Only the deliberately injected HTTP 429 console error is expected');
    assert.deepEqual(errors,[],'No browser console or page errors');
    console.log(JSON.stringify({result:'PASS OFFLINE',model_responses:'scripted',combined_pair_imported:true,
      original_hash_unchanged:true,no_automatic_range_change:true,empty_result_labelled:true,
      embedded_section_blocked:true,visual_review_gate:true,error_preserves_ranges:true,stale_proposals_cleared:true,
      mobile_overflow:false,live_model_calls:0}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
