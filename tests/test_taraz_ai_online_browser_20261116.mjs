// Disposable Vite + Chromium browser QA; all backend and network calls mocked.
// The fixture lives only in tests/output and is cleaned even after a failure.
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve,join,relative} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createServer} from 'vite';
import {chromium} from 'playwright';

const root=resolve(import.meta.dirname,'..');
const output=join(root,'tests','output');
await mkdir(output,{recursive:true});
const fixtureDir=await mkdtemp(join(output,'taraz-online-browser-qa-'));
let server;
let browser;
try{
  const html=String.raw`<!doctype html>
<html lang="fa"><head><meta charset="UTF-8"></head>
<body><div id="root"></div><script type="module">
import React from 'react';
import {createRoot} from 'react-dom/client';
import Panel from '/src/taraz_ai_online_panel.jsx';
const initial={
  configured:true, provider:'openai',
  endpoint:'https://api.openai.com/v1/chat/completions',
  model:'user-specified-model',
  inputUsdPerMillion:'2',outputUsdPerMillion:'4',generation:1,
  credentialsVerified:false,providerHealthVerified:false,
  externalTransmissionEnabled:false,aggregateCostCapEnforced:false,
  remoteRequestMade:false,
};
const calls={status:0,configure:[],clear:0,health:0,generate:0};
window.qaCalls=calls;
const api={
  tarazAiOnlineStatus:async()=>{calls.status++;return {...initial};},
  tarazAiOnlineConfigure:async request=>{
    calls.configure.push({fields:Object.keys(request).sort(),
      manualConsent:request.manualConsent,
      keyPresent:typeof request.apiKey==='string'&&request.apiKey.length>=16});
    return {...initial};
  },
  tarazAiOnlineClear:async()=>{calls.clear++;return {clearedLocally:true};},
  tarazAiOnlineHealth:async()=>{calls.health++;throw Error('Never connect');},
  tarazAiOnlineGenerate:async()=>{calls.generate++;throw Error('Never bill');},
};
createRoot(document.getElementById('root')).render(
  React.createElement(Panel,{api,canEdit:true})
);
</script></body></html>`;
  const fixture=join(fixtureDir,'index.html');
  await writeFile(fixture,html,'utf8');
  server=await createServer({
    root,logLevel:'error',
    server:{host:'127.0.0.1',port:0,strictPort:false},
  });
  await server.listen();
  const url=server.resolvedUrls.local[0]+relative(root,fixture).replaceAll('\\','/');
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url,{waitUntil:'networkidle'});
  await page.getByText('هوش مصنوعی آنلاین (فقط متن غیرمالی با رضایت جداگانه)').click();
  const save=page.getByRole('button',{name:'ذخیرهٔ امن تنظیمات'});
  const send=page.getByRole('button',{name:'ارسال همین متن با رضایت صریح'});
  const probe=page.getByRole('button',{name:'بررسی TLS بدون کلید'});
  const consent=page.locator('.taraz-online-ai-consent input[type="checkbox"]');
  await assert.rejects(save.click({timeout:300}),/Timeout/);
  assert.equal(await send.isDisabled(),true);
  assert.equal(await probe.isDisabled(),true);
  await page.locator('.taraz-online-ai-form input[type="password"]')
    .fill('synthetic-local-qa-only-random-string-123456');
  await consent.check();
  assert.equal(await save.isEnabled(),true);
  await save.click();
  await page.getByText('تنظیمات فقط در خزانهٔ ویندوز ذخیره شد.',{exact:false})
    .waitFor({state:'visible'});
  assert.equal(await consent.isChecked(),false);
  assert.equal(await send.isDisabled(),true);
  assert.equal(await probe.isDisabled(),true);
  const results=await page.evaluate(()=>window.qaCalls);
  assert.equal(results.status,1);
  assert.equal(results.configure.length,1);
  assert.equal(results.configure[0].manualConsent,true);
  assert.equal(results.configure[0].keyPresent,true);
  assert.deepEqual(results.configure[0].fields,[
    'apiKey','endpoint','inputUsdPerMillion','manualConsent',
    'model','outputUsdPerMillion','provider',
  ]);
  assert.equal(results.clear,0);
  assert.equal(results.health,0);
  assert.equal(results.generate,0);
  assert.equal(errors.length,0,errors.join('; '));
  console.log('BROWSER_OK: consent gating, reset, no online calls, no financial context');
}finally{
  if(browser)await browser.close();
  if(server)await server.close();
  await rm(fixtureDir,{recursive:true,force:true});
}
