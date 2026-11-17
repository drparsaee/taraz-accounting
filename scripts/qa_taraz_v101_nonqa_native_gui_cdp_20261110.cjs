'use strict';
/** Drive the native frozen Taraz WebView2 with Chrome DevTools over 127.0.0.1.
 * Operates only with a private cloned real profile prepared by the Python QA.
 * No financial command or external URL is permitted.
 */
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const crypto=require('node:crypto');

const [portArg,playwrightDir,resultArg,libraryArg]=process.argv.slice(2);
const port=Number(portArg), resultFile=path.resolve(resultArg), libraryFile=path.resolve(libraryArg);
if(!Number.isInteger(port)||port<1024||port>65535||!resultFile.includes('nonqa-native-gui-qa')||
   !libraryFile.includes('nonqa-native-gui-qa')||!playwrightDir)throw Error('QA path/port precondition failed');
const {chromium}=require(path.resolve(playwrightDir));
const marker='QA-V101-PRINT-'+crypto.randomBytes(6).toString('hex');
const observed={invoiceDesignOpened:false,templateSaved:false,templateReloaded:false,
  printed:false,financeCommandInvoked:false,noExternalRequestsObserved:true,
  blockedExternalRequests:0,qaMarkerSha256:crypto.createHash('sha256').update(marker).digest('hex')};
const safeUrl=value=>{
  try{
    const url=new URL(value);
    return url.protocol==='http:'&&(url.hostname==='127.0.0.1'||url.hostname==='localhost');
  }catch{return false;}
};
const getJson=address=>new Promise((resolve,reject)=>{
  const req=http.get(address,{timeout:1400},response=>{
    if(response.statusCode!==200){response.resume();reject(Error('Local CDP HTTP '+response.statusCode));return;}
    let raw='';response.on('data',chunk=>{raw+=chunk;if(raw.length>60000){req.destroy();reject(Error('Oversized CDP metadata'));}});
    response.on('end',()=>{try{resolve(JSON.parse(raw));}catch(e){reject(e)}});
  });
  req.on('timeout',()=>req.destroy(Error('CDP request timeout')));
  req.on('error',reject);
});
const sleep=t=>new Promise(resolve=>setTimeout(resolve,t));
let browser;
(async()=>{
  let page, context;
  const deadline=Date.now()+36000;
  while(Date.now()<deadline){
    try{
      const version=await getJson('http://127.0.0.1:'+port+'/json/version');
      if(typeof version.Browser!=='string'||!/chrome|edge/i.test(version.Browser)){
        throw Error('CDP version is not an Edge Chromium browser');
      }
      browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:3500});
      context=browser.contexts()[0];
      if(!context)throw Error('No WebView2 context exposed');
      for(const p of context.pages())if(safeUrl(p.url())&&p.url().includes('accounting.html'))page=p;
      if(page)break;
      await browser.close();browser=undefined;
    }catch(_err){if(browser){try{await browser.close()}catch{}browser=undefined;}}
    await sleep(450);
  }
  if(!page)throw Error('Native WebView2 CDP accounting.html target unavailable');
  page.setDefaultTimeout(6500);
  const external=[];
  page.on('request',request=>{
    const url=request.url();
    if(!safeUrl(url)&&!url.startsWith('blob:')&&!url.startsWith('data:'))external.push(url.slice(0,120));
  });
  await context.route('**/*',route=>{
    const url=route.request().url();
    if(safeUrl(url))return route.continue();
    observed.blockedExternalRequests++;
    return route.abort('blockedbyclient');
  });
  await page.locator('.sac-root').waitFor({timeout:11000});
  const hasBridge=await page.evaluate(()=>typeof window.madar?.standaloneAccountingTemplateSave==='function'&&
    typeof window.madar?.standaloneAccountingTemplateList==='function');
  if(!hasBridge)throw Error('Actual native template save/list methods not exposed');

  const nav=page.locator('.taraz-vt-primary [data-accounting-tab="invoiceDesign"]');
  if(await nav.count())await nav.click();
  else{
    await page.locator('.sac-nav-more-trigger').click();
    await page.locator('.taraz-vt-drawer [data-accounting-tab="invoiceDesign"]').click();
  }
  const designer=page.locator('.sac-print-designer');
  await designer.waitFor({timeout:9500});
  const title=designer.locator('label').filter({hasText:'نام قالب'}).first().locator('input');
  await title.fill(marker);
  if(await title.inputValue()!==marker)throw Error('Designer title did not update');
  const preview=designer.locator('canvas[aria-label="نمای فاکتور قابل طراحی"]');
  await preview.waitFor();
  const canvasWidth=await preview.evaluate(canvas=>canvas.width);
  if(canvasWidth<=0)throw Error('Invoice visual canvas failed to render');
  observed.invoiceDesignOpened=true;

  await page.getByRole('button',{name:'ذخیره قالب چاپ',exact:true}).click();
  const savedDeadline=Date.now()+10000;
  let saved;
  while(Date.now()<savedDeadline){
    if(fs.existsSync(libraryFile)){
      const library=JSON.parse(fs.readFileSync(libraryFile,'utf8'));
      saved=library.templates?.find(item=>item.kind==='print'&&item.title===marker);
      if(saved)break;
    }
    await sleep(300);
  }
  if(!saved||!/^[a-f0-9]{32}$/.test(saved.id))throw Error('Native template not persisted in isolated profile');
  if(saved.data?.title!==marker)throw Error('Template data differs from visible editor');
  observed.templateSaved=true;

  await page.reload({waitUntil:'domcontentloaded',timeout:12000});
  await page.locator('.sac-root').waitFor();
  const navAfter=page.locator('.taraz-vt-primary [data-accounting-tab="invoiceDesign"]');
  if(await navAfter.count())await navAfter.click();
  else{
    await page.locator('.sac-nav-more-trigger').click();
    await page.locator('.taraz-vt-drawer [data-accounting-tab="invoiceDesign"]').click();
  }
  await page.locator('.sac-print-designer').waitFor();
  const selector=page.getByRole('combobox',{name:'قالب چاپ ذخیره‌شده'});
  await selector.waitFor();
  await page.waitForFunction(id=>!!document.querySelector('select[aria-label="قالب چاپ ذخیره‌شده"] option[value="'+id+'"]'),saved.id);
  await selector.selectOption(saved.id);
  const reloadedTitle=page.locator('.sac-print-designer label').filter({hasText:'نام قالب'}).first().locator('input');
  await reloadedTitle.waitFor();
  if(await reloadedTitle.inputValue()!==marker)throw Error('Saved designer title not reloaded from native store');
  const list=await page.evaluate(()=>window.madar.standaloneAccountingTemplateList('print'));
  const content=Array.isArray(list?.templates)?list.templates:[];
  if(!content.some(item=>item.id===saved.id&&item.title===marker))throw Error('Native bridge reload did not return saved template');
  observed.templateReloaded=true;
  observed.noExternalRequestsObserved=external.length===0&&observed.blockedExternalRequests===0;
  if(!observed.noExternalRequestsObserved)throw Error('External network request observed or blocked');
  fs.writeFileSync(resultFile,JSON.stringify(observed,null,2)+'\n',{flag:'wx'});
  console.log('NATIVE_INVOICE_DESIGN_SAVED_AND_RELOADED');
})().catch(error=>{
  const failure={...observed,status:'FAIL',error:String(error.message||error).slice(0,650)};
  try{fs.writeFileSync(resultFile,JSON.stringify(failure,null,2)+'\n',{flag:'wx'})}catch{}
  console.error('NATIVE_CDP_FAIL: '+failure.error);
  process.exitCode=1;
}).finally(async()=>{if(browser){try{await browser.close()}catch{}}});
