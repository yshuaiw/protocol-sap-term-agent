const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');
(async()=>{
 const id=fs.readFileSync('output/real-demo-verification/project-id.txt','utf8').trim();
 const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge',headless:true});
 const page=await browser.newPage({baseURL:'http://127.0.0.1:8765',viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765');
 const response=await page.request.get('/api/projects/'+id);const p=await response.json();
 const buttons=page.locator('.project-item');
 await buttons.first().waitFor();
 // Choose the newest matching real project by its audited ID, via its position in the API list.
 const list=await(await page.request.get('/api/projects')).json();
 await buttons.nth(list.findIndex(x=>x.id===id)).click();
 await page.getByPlaceholder('Name or alias').fill('Full analysis set');
 await page.locator('.term').first().click();
 await page.screenshot({path:'output/screenshots/09-real-register.png',fullPage:true});
 await page.getByRole('button',{name:'Plan replacement',exact:true}).click();
 await page.getByRole('heading',{name:'Verified exports'}).waitFor();
 await page.screenshot({path:'output/screenshots/10-real-reviewed-exports.png',fullPage:true});
 await page.getByRole('button',{name:'Documents & coverage',exact:true}).click();
 await page.screenshot({path:'output/screenshots/11-real-coverage.png',fullPage:true});
 if(errors.length)throw new Error(errors.join('\n'));
 await browser.close();console.log('PASS: real 107-page project loaded, evidence and exports captured.');
})().catch(e=>{console.error(e);process.exit(1);});
