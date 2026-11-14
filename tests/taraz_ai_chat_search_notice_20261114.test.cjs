'use strict';
/** Synthetic React/browser UI acceptance; only reads current JSX and mock data. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
const source=path.join(root,'src','taraz_ai_chat_workspace.jsx');

test('AI chat JSX parses with the project React/esbuild transformer',()=>{
  const transformed=esbuild.transformSync(fs.readFileSync(source,'utf8'),{
    loader:'jsx',format:'esm',target:'es2022',jsx:'automatic'});
  assert.match(transformed.code,/searchTruncated/);
});

test('AI chat warns for truncated or limited history without leaking private data',async t=>{
  const playwright=require('playwright');
  const fixture=`
    import React from 'react';
    import {createRoot} from 'react-dom/client';
    import Workspace from './src/taraz_ai_chat_workspace.jsx';
    createRoot(document.getElementById('root')).render(
      <Workspace api={window.__qaChatApi} canEdit={false}/>);
  `;
  const bundle=esbuild.buildSync({stdin:{contents:fixture,loader:'jsx',
    resolveDir:root,sourcefile:'taraz-ai-search-notice-fixture.jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,
    loader:{'.css':'empty'},jsx:'automatic'}).outputFiles[0].text;
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const context=await browser.newContext({serviceWorkers:'block'});
  t.after(()=>context.close());
  const page=await context.newPage();
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error.name));
  await page.setContent('<!doctype html><html lang="fa" dir="rtl"><body><div id="root"></div></body></html>');
  await page.evaluate(()=>{
    window.__qaCalls=[];
    window.__qaErrorLeaked=false;
    window.__qaResponses={
      '':{conversations:[{id:'1',title:'گفتگوی اخیر',updated_at:'2026-11-14T18:00:00'}],
        hasMore:true,searchTruncated:false},
      'truncated':{conversations:[],hasMore:null,searchTruncated:true},
      'more':{conversations:[{id:'2',title:'گفتگوی <img src=x onerror=alert(1)>',
        updated_at:'2026-11-13T10:00:00'}],hasMore:true,searchTruncated:false},
      'none':{conversations:[],hasMore:false,searchTruncated:false},
      'legacy':{conversations:[{id:'3',title:'پاسخ قدیمی',updated_at:''}]},
    };
    window.__qaChatApi={
      tarazAiChatList:async query=>{
        window.__qaCalls.push({method:'list',query});
        if(query==='error')throw new Error('PRIVATE_SQLITE_CREDENTIAL_DO_NOT_EXPOSE');
        return window.__qaResponses[query]||{conversations:[]};
      },
      tarazAiChatRead:async()=>{throw new Error('Unexpected private read');},
      tarazAiChatCommand:async()=>{throw new Error('Unexpected mutation');},
    };
  });
  await page.addScriptTag({content:bundle});
  const search=page.getByPlaceholder('عنوان یا متن گفتگو');
  const submit=page.getByRole('button',{name:'جست‌وجو / بازخوانی'});
  const truncated=page.getByTestId('taraz-ai-search-truncated');
  const more=page.getByTestId('taraz-ai-search-more');
  await more.waitFor();
  assert.match(await more.innerText(),/گفتگوهای قدیمی‌تر/);

  await search.fill('truncated');
  await search.press('Enter');
  await truncated.waitFor();
  assert.match(await truncated.innerText(),/ممکن است ناقص/);
  assert.ok(await page.getByText('در بخش بررسی‌شدهٔ تاریخچه نتیجه‌ای پیدا نشد.').count());
  assert.equal(await page.getByText('گفتگویی در این حساب ثبت نشده است.').count(),0);
  assert.equal(await more.count(),0);

  await search.fill('more');
  await submit.click();
  await more.waitFor();
  assert.match(await more.innerText(),/نتایج بیشتری ممکن است/);
  assert.equal(await truncated.count(),0);
  assert.equal(await page.locator('.taraz-ai-conversation-list img').count(),0);
  assert.equal(await page.locator('.taraz-ai-conversation-list button').count(),1);

  await search.fill('none');
  await submit.click();
  await page.getByText('نتیجه‌ای برای این جست‌وجو یافت نشد.').waitFor();
  assert.equal(await truncated.count(),0);
  assert.equal(await more.count(),0);

  await search.fill('legacy');
  await submit.click();
  await page.getByText('پاسخ قدیمی').waitFor();
  assert.equal(await more.count(),0);
  assert.equal(await truncated.count(),0);

  await search.fill('error');
  await submit.click();
  await page.getByText(/عملیات انجام نشد/).waitFor();
  assert.doesNotMatch(await page.locator('body').innerText(),/PRIVATE_SQLITE_CREDENTIAL_DO_NOT_EXPOSE/);
  assert.deepEqual(pageErrors,[]);
  const calls=await page.evaluate(()=>window.__qaCalls);
  assert.deepEqual(calls.map(call=>call.method),Array(calls.length).fill('list'));
  assert.deepEqual(calls.map(call=>call.query),['','truncated','more','none','legacy','error']);
});
