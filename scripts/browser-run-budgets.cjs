const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
(async () => {
  const base = process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out = path.resolve(process.env.BROWSER_OUTPUT_DIR || 'output/run-budgets-browser');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    assert.equal((await (await page.request.get(base + '/api/offline-fixture')).json()).simulation, true);
    const config = async () => (await page.request.get(base + '/api/ai/config')).json();
    const before = await config();
    await page.goto(base);
    await page.getByRole('button', {name: 'API settings', exact: true}).click();
    await page.getByRole('heading', {name: 'Run budgets', exact: true}).waitFor();
    const tokens = page.getByLabel('Output tokens per response', {exact: true});
    const attempts = page.getByLabel('HTTP attempts per run', {exact: true});
    await tokens.fill('32768'); await attempts.fill('25000');
    await page.getByRole('button', {name: 'Save run budgets', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'Run budgets saved'}).waitFor();
    const saved = await config();
    assert.equal(saved.max_output_tokens, 32768); assert.equal(saved.max_calls, 25000);
    for (const key of ['provider', 'model', 'vision_provider', 'vision_model', 'pdf_mode', 'providers', 'rate_limits']) {
      assert.deepEqual(saved[key], before[key], key + ' unchanged');
    }
    const panel = page.locator('form').filter({has: page.getByRole('heading', {name: 'Run budgets', exact: true})});
    await panel.screenshot({path: path.join(out, '01-saved-desktop.png')});
    await page.reload(); await page.getByRole('button', {name: 'API settings', exact: true}).click();
    await tokens.waitFor(); assert.equal(await tokens.inputValue(), '32768');
    assert.equal(await attempts.inputValue(), '25000');
    await page.getByRole('button', {name: 'Large', exact: true}).click();
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await panel.screenshot({path: path.join(out, '02-large-mobile.png')});
    await page.getByRole('button', {name: 'Use default budgets', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'Run budgets saved'}).waitFor();
    const defaults = await config();
    assert.equal(defaults.max_calls, 10000); assert.equal(defaults.max_output_tokens, 16384);
    assert.deepEqual((await (await page.request.get(base + '/api/workflow-fixture')).json()).calls, []);
    assert.deepEqual(errors, []);
    await page.request.put(base + '/api/ai/run-limits', {data: {max_calls: before.max_calls, max_output_tokens: before.max_output_tokens}});
    console.log('PASS OFFLINE: run budgets save/reload/defaults, unchanged models/keys/RPM, large mobile layout; no model requests.');
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exit(1);});
