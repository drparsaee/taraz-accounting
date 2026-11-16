'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');
const playwright=require('playwright');
const root=path.resolve(__dirname,'..');

test('paired card reader requires a manual click and never posts finance',async t=>{
  const jsx=`import React from 'react';
import {createRoot} from 'react-dom/client';
import Panel from './src/taraz_ecosystem_link_panel.jsx';
window.qa={pair:[],finance:0,linked:false};
const api={
 tarazEcosystemConnections:async()=>({financialEventCreated:false,connections:window.qa.linked?[{workspaceId:'a'.repeat(32),peerId:'MADAR',revoked:false}]:[]}),
 tarazEcosystemPair:async r=>{window.qa.pair.push(r);window.qa.linked=true;return {connected:true,readOnly:true,financialEventCreated:false};},
 tarazEcosystemCards:async()=>({source:'MADAR',readOnly:true,financialEventCreated:false,cards:[],hasMore:false}),
 tarazEcosystemForget:async()=>({revokedLocally:true,financialEventCreated:false}),
 standaloneAccountingCommand:async()=>{window.qa.finance++;}
};
createRoot(document.getElementById('root')).render(<Panel api={api} canAdmin={true}/>);`;
  const out=(await esbuild.build({stdin:{contents:jsx,resolveDir:root,
    loader:'jsx',sourcefile:'ecosystem-browser-qa.jsx'},bundle:true,write:false,
    platform:'browser',format:'iife',outdir:'qa',logLevel:'silent',
    loader:{'.css':'css','.png':'dataurl','.svg':'dataurl'}})).outputFiles;
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage();
  await page.setContent('<div id="root"></div>');
  await page.addScriptTag({content:out.find(f=>f.path.endsWith('.js')).text});
  await page.locator('summary').click();
  const button=page.getByRole('button',{name:'اتصال با کد یک‌بارمصرف'});
  assert.equal(await button.isDisabled(),true);
  await page.getByLabel('نشانی میزبان مدار (HTTPS و IP خصوصی)').fill('https://127.0.0.1:48370');
  await page.getByLabel('SHA-256 گواهی TLS مدار (تأییدشده از راه مستقل)').fill('a'.repeat(64));
  await page.getByLabel('کد اتصال یک‌بارمصرف').fill('ABCDEFGHIJKLM');
  await page.getByLabel('اتصال این میزبان و خواندن کارت‌های مجاز را تأیید می‌کنم.').check();
  await button.click();
  await page.getByText('اتصال خواندنی مدار با هویت و گواهی مشخص ثبت شد.').waitFor();
  const r=await page.evaluate(()=>window.qa);
  assert.equal(r.pair.length,1);
  assert.equal(r.pair[0].manualConsent,true);
  assert.equal(r.finance,0);
});
