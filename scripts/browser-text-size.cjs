// Real local UI/state; synthetic documents and scripted provider only.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
(async () => {
  const base = process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out = path.resolve(process.env.BROWSER_OUTPUT_DIR || 'output/text-size-browser');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const page = await context.newPage(), errors = [];
    let mutations = 0;
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    page.on('request', r => {if (!['GET', 'HEAD'].includes(r.method())) mutations++;});
    const api = async route => {
      const r = await page.request.get(base + '/api' + route); assert.equal(r.ok(), true); return r.json();
    };
    assert.equal((await api('/offline-fixture')).simulation, true);
    await page.request.post(base + '/api/workflow-fixture', {data: {}});
    const shot = name => page.screenshot({path: path.join(out, name + '.png'), fullPage: true});
    const px = locator => locator.evaluate(el => parseFloat(getComputedStyle(el).fontSize));
    const fits = async () => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No page-wide overflow');
      const box = await page.getByRole('group', {name: 'Text size', exact: true}).boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= page.viewportSize().width, 'Text controls stay within the viewport');
    };
    async function size(mode) {
      const before = mutations;
      await page.getByRole('button', {name: mode, exact: true}).click();
      await page.waitForFunction(v => document.documentElement.dataset.textSize === v, mode.toLowerCase());
      assert.equal(await page.getByRole('button', {name: mode, exact: true}).getAttribute('aria-pressed'), 'true');
      assert.equal(mutations, before, 'Display toggles make no API mutations');
    }
    await page.goto(base); await shot('01-normal-welcome');
    assert.equal(await page.getByRole('button', {name: 'Normal', exact: true}).count(), 1);
    assert.equal(await px(page.locator('body')), 14);
    assert.equal(await px(page.locator('h1')), 26);
    await size('Large'); assert.equal(await px(page.locator('body')), 18);
    assert.equal(await px(page.locator('h1')), 34);
    assert.equal(await px(page.locator('.brand span')), 16);
    await page.getByRole('button', {name: 'Normal', exact: true}).focus();
    await page.keyboard.press('Space');
    await page.waitForFunction(() => document.documentElement.dataset.textSize === 'normal');
    await size('Large');
    await shot('02-large-welcome');
    await page.reload(); await page.waitForFunction(() => document.documentElement.dataset.textSize === 'large');
    const other = await context.newPage(); await other.goto(base);
    await other.waitForFunction(() => document.documentElement.dataset.textSize === 'large'); await other.close();

    await page.getByRole('button', {name: 'Import documents', exact: true}).click();
    const name = ('Presentation test ' + Date.now() + ' — ' + 'long project title '.repeat(8)).trim();
    await page.getByLabel('Project name', {exact: true}).fill(name);
    await page.getByLabel('Select PDF or DOCX files').setInputFiles(['tmp/fixtures/Protocol.pdf', 'tmp/fixtures/SAP.pdf']);
    await page.getByRole('heading', {name: 'Review document boundaries'}).waitFor();
    await page.getByLabel('Version and boundary review note').fill('Unsaved import note.');
    await page.getByRole('checkbox').check();
    await size('Normal'); await size('Large');
    assert.equal(await page.getByLabel('Project name', {exact: true}).inputValue(), name);
    assert.equal(await page.getByLabel('Version and boundary review note').inputValue(), 'Unsaved import note.');
    assert.equal(await page.getByRole('checkbox').isChecked(), true);
    assert.equal(await px(page.getByLabel('Project name', {exact: true})), 18);
    assert.equal(await px(page.getByRole('heading', {name: 'Review document boundaries'})), 24);
    await page.setViewportSize({width: 390, height: 844}); await fits(); await shot('03-large-mobile-import');
    await page.setViewportSize({width: 1440, height: 1000});
    await page.getByLabel('Register workflow').selectOption('rules');
    await page.getByRole('button', {name: 'Import and save originals'}).click();
    await page.getByRole('heading', {name: 'Terminology register', exact: true}).waitFor();
    await page.locator('.busy').waitFor({state: 'hidden'});
    const project = (await api('/projects')).find(p => p.name === name);
    assert.ok(project);
    await page.getByRole('button').filter({has: page.locator('strong', {hasText: /^Arm A$/})}).click();
    await page.getByLabel(/^Review note/).fill('Unsaved register review.');
    await page.getByRole('checkbox', {name: /Confirm all unambiguous/}).check();
    await size('Normal'); await size('Large');
    assert.equal(await page.getByLabel(/^Review note/).inputValue(), 'Unsaved register review.');
    assert.equal(await page.getByRole('checkbox', {name: /Confirm all unambiguous/}).isChecked(), true);
    assert.equal(await px(page.locator('.occurrence p').first()), 18);
    await shot('04-large-register');
    await page.getByRole('button', {name: 'Save register', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'Register saved'}).waitFor();
    await page.getByRole('button', {name: 'Replacement review', exact: true}).click();
    await page.getByLabel('Review engine', {exact: true}).selectOption('rules');
    await page.getByLabel('Concept', {exact: true}).selectOption({label: 'Arm A · confirmed'});
    await page.getByLabel('Replace “Arm A” with').fill('Investigational Arm A');
    await page.getByRole('button', {name: 'Generate preview'}).click();
    await page.getByRole('heading', {name: 'Proposed occurrences'}).waitFor();
    const approval = page.getByRole('checkbox', {name: /Approve/}).first(); await approval.check();
    await page.getByRole('checkbox', {name: /I reviewed coverage limits/}).check();
    await size('Normal'); await size('Large');
    assert.equal(await approval.isChecked(), true);
    assert.equal(await page.getByRole('checkbox', {name: /I reviewed coverage limits/}).isChecked(), true);
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({width, height: 1000}); await fits();
      await shot('05-large-review-' + width);
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.getByRole('button', {name: 'Documents & coverage', exact: true}).click();
    assert.equal(await px(page.locator('table').first()), 16); await fits();
    await page.setViewportSize({width: 390, height: 844}); await fits(); await shot('06-large-mobile-table');
    await page.setViewportSize({width: 1440, height: 1000});
    await page.getByRole('button', {name: 'Delete project ' + name, exact: true}).click();
    await page.getByRole('dialog').getByRole('heading').waitFor();
    assert.equal(await px(page.getByRole('dialog').getByRole('heading')), 24);
    await shot('07-large-dialog'); await page.getByRole('button', {name: 'Cancel', exact: true}).click();
    const saved = await api('/projects/' + project.id), settings = await api('/ai/config');
    await page.getByRole('button', {name: 'API settings', exact: true}).click();
    await page.getByLabel('Text model', {exact: true}).fill('unsaved-model-draft');
    await size('Normal'); await size('Large');
    assert.equal(await page.getByLabel('Text model', {exact: true}).inputValue(), 'unsaved-model-draft');
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({width, height: 1000}); await fits(); await shot('08-large-settings-' + width);
    }
    assert.deepEqual(await api('/ai/config'), settings);
    assert.deepEqual(await api('/projects/' + project.id), saved, 'Display preference never persists to project');
    assert.deepEqual((await api('/workflow-fixture')).calls, []);
    await page.reload(); await page.waitForFunction(() => document.documentElement.dataset.textSize === 'large');
    await size('Normal'); await page.reload();
    await page.waitForFunction(() => document.documentElement.dataset.textSize === 'normal');

    for (const blocked of [false, true]) {
      const isolated = await browser.newContext();
      await isolated.addInitScript(deny => {
        if (deny) {
          Object.defineProperty(Storage.prototype, 'getItem', {value() {throw new Error('Storage denied');}});
          Object.defineProperty(Storage.prototype, 'setItem', {value() {throw new Error('Storage denied');}});
        } else localStorage.setItem('term-agent.text-size', 'invalid');
      }, blocked);
      const tab = await isolated.newPage(); tab.on('pageerror', e => errors.push(e.message));
      await tab.goto(base); await tab.getByRole('button', {name: 'Normal', exact: true}).waitFor();
      assert.equal(await tab.locator('body').evaluate(el => getComputedStyle(el).fontSize), '14px');
      await tab.getByRole('button', {name: 'Large', exact: true}).click();
      await tab.waitForFunction(() => getComputedStyle(document.body).fontSize === '18px');
      await isolated.close();
    }

    // A delayed scripted request is allowed only in this explicit activity check.
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator(`[data-project-id="${project.id}"] .project-item`).click();
    await page.getByRole('heading', {name: 'Terminology register', exact: true}).waitFor();
    await page.locator('.busy').waitFor({state: 'hidden'});
    await page.getByLabel('Visual processing mode', {exact: true}).selectOption('text');
    await page.getByRole('checkbox', {name: /Replace this register/}).check();
    await page.request.post(base + '/api/workflow-fixture', {data: {delay_stage: 'discovery', delay: 7}});
    const original = await api('/projects/' + project.id);
    await page.getByRole('button', {name: 'Generate AI register and links'}).click();
    await page.getByRole('button', {name: 'Cancel LLM operation', exact: true}).waitFor();
    const operations = await api('/operations');
    const callsBeforeToggle = (await api('/workflow-fixture')).calls;
    await size('Large'); await size('Normal');
    assert.deepEqual((await api('/operations')).map(o => o.id), operations.map(o => o.id));
    assert.deepEqual((await api('/workflow-fixture')).calls, callsBeforeToggle, 'Toggle adds no provider attempts');
    await shot('09-active-operation-retained');
    await page.getByRole('button', {name: 'Cancel LLM operation', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'LLM operation cancelled;'}).waitFor({timeout: 20000});
    assert.deepEqual(await api('/projects/' + project.id), original);
    await page.request.post(base + '/api/workflow-fixture', {data: {}});
    assert.deepEqual(errors, []);
    console.log('PASS OFFLINE: exact font sizes, persistence/fallback, keyboard, form/approval/settings and active-task retention, local-only preference, large desktop/tablet/mobile layouts. Activity check uses a delayed scripted provider; no live calls.');
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exit(1);});
