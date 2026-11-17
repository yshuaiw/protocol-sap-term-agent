// Real browser with isolated persistence and deliberately scripted model content.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
(async () => {
  const base = process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out = path.resolve(process.env.BROWSER_OUTPUT_DIR || 'output/bounded-linking-browser');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    const api = async (url, method = 'GET', data) => {
      const response = await page.request.fetch(base + '/api' + url, {method, ...(data ? {data} : {})});
      assert.ok(response.ok(), await response.text()); return response.json();
    };
    assert.equal((await api('/offline-fixture')).simulation, true);
    await api('/workflow-fixture', 'POST', {delay_stage: 'linking_scan', delay: 7});
    await page.goto(base);
    await page.getByRole('button', {name: 'Import documents', exact: true}).click();
    const name = 'Bounded linking browser ' + Date.now();
    await page.getByLabel('Project name').fill(name);
    await page.getByLabel('Select PDF or DOCX files').setInputFiles(['tmp/fixtures/Protocol.pdf', 'tmp/fixtures/SAP.pdf']);
    await page.getByText('Review document boundaries', {exact: true}).waitFor();
    await page.getByRole('checkbox').check();
    await page.getByRole('button', {name: 'Import and save originals'}).click();
    await page.getByRole('heading', {name: 'Terminology register', exact: true}).waitFor();
    const project = (await api('/projects')).find(p => p.name === name);
    await page.getByLabel('Visual processing mode').selectOption('text');
    await page.getByRole('button', {name: 'Generate AI register and links'}).click();
    const active = page.getByRole('region', {name: 'LLM operations'});
    await active.getByText(/Linking: 8\/10 candidates/).waitFor();
    await active.screenshot({path: path.join(out, '01-active-progress.png')});
    await page.getByRole('status').filter({hasText: 'AI run saved'}).waitFor();
    const saved = await api('/projects/' + project.id), progress = saved.ai_runs.at(-1).linking_progress;
    assert.equal(progress.candidates_completed, 10); assert.equal(progress.candidates_total, 10);
    assert.ok(progress.index_pages_checked > 0 && progress.evidence_requests > 0);
    assert.ok(progress.max_input_characters <= 60000);
    await page.locator('.ai-run').screenshot({path: path.join(out, '02-saved-progress.png')});
    await api('/workflow-fixture', 'POST', {});
    await page.getByLabel('Replace this register with a new AI run; earlier corrections remain in history.').check();
    await page.getByRole('button', {name: 'Generate AI register and links'}).click();
    await page.getByRole('status').filter({hasText: 'AI run saved'}).waitFor();
    const replay = (await api('/projects/' + project.id)).ai_runs.at(-1);
    assert.equal(replay.http_attempts, 0); assert.ok(replay.linking_progress.cache_hits > 0);
    assert.deepEqual((await api('/workflow-fixture')).calls, []);
    await page.getByRole('button', {name: 'Large', exact: true}).click();
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('.ai-run').screenshot({path: path.join(out, '03-large-mobile.png')});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({simulation: true, progress,
      replay_http_attempts: replay.http_attempts, console_errors: errors, mobile_overflow: false}, null, 2));
    console.log('PASS OFFLINE: active/saved linking progress, accepted cache replay with HTTP 0, Large mobile layout; scripted model only.');
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exit(1);});
