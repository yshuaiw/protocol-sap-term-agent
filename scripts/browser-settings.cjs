// Isolated local UI fixture only. No real credentials, no provider requests.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async()=>{
  const base = process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out = path.resolve('output/screenshots/provider-settings'); fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    const fixture = await page.request.get(base+'/api/offline-fixture');
    assert.equal((await fixture.json()).simulation,true);
    const initial = await (await page.request.get(base+'/api/ai/config')).json();
    await page.goto(base);
    await page.getByRole('button',{name:'API settings',exact:true}).click();
    await page.getByRole('heading',{name:'API settings',exact:true}).waitFor();
    await page.getByLabel('Text provider',{exact:true}).selectOption('google');
    await page.getByLabel('Text model',{exact:true}).fill('gemini-2.5-flash');
    await page.getByLabel('Visual provider',{exact:true}).selectOption('anthropic');
    await page.getByLabel('Visual model',{exact:true}).fill('claude-sonnet-4-5');
    await page.getByLabel('Default document processing').selectOption('native');
    await page.getByRole('button',{name:'Save task settings',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Settings saved.'}).waitFor();
    await page.screenshot({path:path.join(out,'01-separate-task-providers.png'),fullPage:true});
    await page.reload();
    await page.getByRole('button',{name:'API settings',exact:true}).click();
    await page.getByLabel('Text model',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('Text provider',{exact:true}).inputValue(),'google');
    assert.equal(await page.getByLabel('Visual provider',{exact:true}).inputValue(),'anthropic');
    assert.equal(await page.getByLabel('Default document processing').inputValue(),'native');
    await page.getByLabel('Credential provider').selectOption('google');
    for (const [key,button] of [['ui-fixture-private-key-1','Save key'],['ui-fixture-private-key-2','Replace key']]) {
      await page.getByLabel('New API key').fill(key);
      await page.getByRole('button',{name:button,exact:true}).click();
      await page.getByRole('status').filter({hasText:'Key saved locally.'}).waitFor();
      assert.equal(await page.getByLabel('New API key').inputValue(),'');
      assert.equal((await page.content()).includes(key),false);
      assert.equal((await (await page.request.get(base+'/api/ai/config')).text()).includes(key),false);
    }
    await page.screenshot({path:path.join(out,'02-key-saved-without-echo.png'),fullPage:true});
    await page.getByRole('button',{name:'Delete key',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Key deleted'}).waitFor();
    await page.reload();await page.getByRole('button',{name:'API settings',exact:true}).click();
    await page.getByLabel('Credential provider').selectOption('google');
    await page.getByRole('status').filter({hasText:'No active key · disabled locally'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Delete key',exact:true}).isDisabled(),true);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'03-mobile-key-deleted.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.getByRole('button',{name:'Back to workspace',exact:true}).click();
    await page.getByRole('heading',{name:'Keep terminology consistent across documents.'}).waitFor();
    // Restore fixture selection only; actual machine configuration was never touched.
    const keys=['provider','model','vision_provider','vision_model','pdf_mode'];
    assert.equal((await page.request.put(base+'/api/ai/config',{data:Object.fromEntries(keys.map(k=>[k,initial[k]]))})).status(),200);
    assert.deepEqual(errors,[]);
    console.log('PASS OFFLINE UI: separate provider/model settings, save/reload, key save/replace/delete, no key echo, navigation and mobile layout. No real model calls.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
