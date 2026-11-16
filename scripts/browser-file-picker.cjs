// Offline UI check: English file controls, native picker activation and filename layout.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.DEMO_URL || 'http://127.0.0.1:8766';
  const out = path.resolve(process.env.BROWSER_OUTPUT_DIR || 'output/file-picker-browser');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({locale: 'zh-CN', viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    const fixture = await page.request.get(base + '/api/offline-fixture');
    assert.equal(fixture.status(), 200, 'Use the isolated offline fixture server');
    assert.equal((await fixture.json()).simulation, true);
    const shot = name => page.screenshot({path: path.join(out, name + '.png'), fullPage: true});
    const fits = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.goto(base);
    await page.getByRole('button', {name: 'Import documents', exact: true}).click();
    const sidebar = await page.getByRole('complementary').boundingBox();
    const main = await page.getByRole('main').boundingBox();
    assert.ok(sidebar.width >= 280, 'Desktop sidebar is wider for project names');
    assert.equal(main.x, sidebar.x + sidebar.width, 'Main content starts after the sidebar');
    await shot('01-desktop-empty');
    await page.setViewportSize({width: 390, height: 844});
    await shot('02-mobile-empty');
    await fits();
    await page.setViewportSize({width: 1440, height: 1000});
    const button = page.getByRole('button', {name: 'Choose files', exact: true});
    assert.equal(await button.count(), 1, 'The native localized control must have an English button');
    await page.getByRole('status').filter({hasText: /^No files selected$/}).waitFor();
    const input = page.getByLabel('Select PDF or DOCX files', {exact: true});
    assert.equal(await input.getAttribute('accept'), '.pdf,.docx');
    assert.equal(await input.getAttribute('multiple'), '');

    // Enter must activate the real input picker without submitting the import form.
    await page.getByLabel('Project name').focus();
    await page.keyboard.press('Tab');
    assert.equal(await button.evaluate(el => el === document.activeElement), true);
    const firstPicker = page.waitForEvent('filechooser');
    await page.keyboard.press('Enter');
    await (await firstPicker).setFiles('tmp/fixtures/Protocol.pdf');
    await page.getByRole('heading', {name: 'Review document boundaries', exact: true}).waitFor();
    await page.getByRole('status').filter({hasText: /^Protocol\.pdf$/}).waitFor();
    await shot('03-single-file');

    // A browser cancel event must preserve the previous selection and inspection.
    await input.dispatchEvent('cancel');
    await page.getByRole('status').filter({hasText: /^Protocol\.pdf$/}).waitFor();

    // Hold inspection so the disabled state is observable without timing guesses.
    let release;
    const inspection = new Promise(resolve => {release = resolve;});
    await page.route('**/api/inspect', async route => {await inspection; await route.continue();});
    const longName = 'Protocol_' + 'long-document-name-'.repeat(12) + '.pdf';
    const picker = page.waitForEvent('filechooser');
    await button.click();
    await (await picker).setFiles([
      {name: longName, mimeType: 'application/pdf', buffer: fs.readFileSync('tmp/fixtures/Protocol.pdf')},
      {name: 'Unicode-SAP.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: fs.readFileSync('tmp/fixtures/Unicode-SAP.docx')}
    ]);
    await page.waitForFunction(() => [...document.querySelectorAll('button')].find(b => b.textContent === 'Choose files')?.disabled);
    assert.equal(await input.isDisabled(), true);
    await shot('04-inspecting');
    release();
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === 'Choose files')?.disabled);
    const names = page.getByRole('status').filter({hasText: longName});
    await names.waitFor();
    assert.match(await names.innerText(), /Unicode-SAP\.docx/);
    assert.equal(await page.getByRole('combobox', {name: 'Source', exact: true}).first().locator('option').count(), 2);
    await shot('05-desktop-mixed');
    await page.setViewportSize({width: 390, height: 844});
    await shot('06-mobile-mixed');
    await fits();
    const box = await names.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 390, 'Long filenames stay inside the mobile viewport');
    assert.deepEqual(errors, [], 'No console or page errors');
    console.log('PASS: English control in zh-CN, keyboard/click picker, PDF and mixed PDF/DOCX, cancel event retention, busy state and desktop/mobile layout. No live calls; OS dialog language is outside this check.');
  } finally {
    await browser.close();
  }
})().catch(e => {console.error(e); process.exit(1);});
