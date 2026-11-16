// Offline fixture only: settings HTTP/storage are real; no model or real key is used.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const base=process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out=path.resolve('output/rpm-ui');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],modelRequests=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    page.on('request',r=>{if(/\/api\/(inspect\/ai|projects\/[^/]+\/ai\/)/.test(r.url()))modelRequests.push(r.url());});
    assert.equal((await(await page.request.get(base+'/api/offline-fixture')).json()).simulation,true);
    const before=await(await page.request.get(base+'/api/ai/config')).json();
    const provider=page.getByLabel('Rate limit provider',{exact:true}), model=page.getByLabel('Rate limit model',{exact:true});
    const rpm=page.getByLabel('Requests per minute (RPM)',{exact:true});
    async function save(value) {
      await rpm.fill(String(value));await page.getByRole('button',{name:'Save model RPM limit',exact:true}).click();
      await page.getByRole('status').filter({hasText:'Model RPM limit saved.'}).waitFor();
    }
    await page.goto(base);await page.getByRole('button',{name:'API settings',exact:true}).click();
    await provider.selectOption('google');await model.fill('gemini-rpm-fixture-a');await save(12);
    await page.getByText('Saved model cap: 12 RPM.',{exact:false}).waitFor();
    await model.fill('gemini-rpm-fixture-b');await save(5);
    await provider.selectOption('groq');await model.fill('groq-rpm-fixture');await save(25);
    await page.reload();await page.getByRole('button',{name:'API settings',exact:true}).click();
    await provider.selectOption('google');await model.fill('gemini-rpm-fixture-a');
    await page.waitForFunction(()=>document.querySelector('input[type="number"]').value==='12');
    assert.equal(await rpm.inputValue(),'12');
    await model.fill('gemini-rpm-fixture-b');
    await page.waitForFunction(()=>document.querySelector('input[type="number"]').value==='5');
    assert.equal(await rpm.inputValue(),'5');
    await rpm.fill('0');assert.equal(await page.getByRole('button',{name:'Save model RPM limit',exact:true}).isDisabled(),true);
    await rpm.fill('5');
    await page.getByRole('heading',{name:'Request rate limits',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'01-independent-model-caps.png'),fullPage:true});
    await page.getByRole('button',{name:'Use app starting cap',exact:true}).click();
    await page.getByText(/no model override saved/).waitFor();
    const config=await(await page.request.get(base+'/api/ai/config')).json();
    assert.equal(config.rate_limits.google['gemini-rpm-fixture-a'],12);
    assert.equal(config.rate_limits.google['gemini-rpm-fixture-b'],undefined);
    assert.equal(config.rate_limits.groq['groq-rpm-fixture'],25);
    for(const key of ['provider','model','vision_provider','vision_model','pdf_mode'])assert.equal(config[key],before[key]);
    assert.deepEqual(config.providers,before.providers,'Rate edits leave credential status intact');
    await page.getByRole('button',{name:'Edit text model limit',exact:true}).click();
    assert.equal(await provider.inputValue(),before.provider);assert.equal(await model.inputValue(),before.model);
    await page.getByRole('button',{name:'Edit visual model limit',exact:true}).click();
    assert.equal(await provider.inputValue(),before.vision_provider);assert.equal(await model.inputValue(),before.vision_model);
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('heading',{name:'Request rate limits',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'02-mobile-shared-limit-notice.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.route('**/api/ai/config',route=>{
      const old={...config};for(const key of ['rate_defaults','rate_limits','text_rpm','vision_rpm'])delete old[key];
      return route.fulfill({status:200,json:old});
    });
    await page.reload();await page.getByRole('button',{name:'API settings',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Restart the backend and refresh this page'}).waitFor();
    await page.screenshot({path:path.join(out,'03-old-backend-restart-message.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(modelRequests,[]);
    console.log(JSON.stringify({result:'PASS OFFLINE',profiles_survive_reload:true,models_independent:true,
      reset_and_validation:true,task_selection_and_keys_unchanged:true,old_backend_guard:true,mobile_overflow:false,live_model_calls:0}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
