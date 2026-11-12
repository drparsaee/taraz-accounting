import React,{useCallback,useMemo,useRef,useState,useEffect} from 'react';
import {ArrowLeft,CheckCircle2,ClipboardList,RefreshCw,ShieldCheck,XCircle} from 'lucide-react';
import {integrationCapabilities,listTarazIntegration,reviewTarazIntegration,
  recoverTarazIntegration} from './taraz_settings_integration.js';
import './taraz_madar_dashboard.css';

const MADAR_SCOPES=[['projects','پروژه‌ها'],['tasks','کارها'],['boards','بردها'],
  ['workspaces','فضاهای کاری'],['templates','قالب‌ها']];
const DEFAULT_HOST={url:'',fingerprint:'',username:'',password:''};

/** User-approved read-only snapshots. Full Madar financial/secret data is excluded by the host. */
export function MadarDataExplorer({api,canAdmin=false}){
  const [consent,setConsent]=useState(false);
  const [source,setSource]=useState('local');
  const [scope,setScope]=useState('projects');
  const [connection,setConnection]=useState(DEFAULT_HOST);
  const [snapshot,setSnapshot]=useState(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [offset,setOffset]=useState(0);
  const generation=useRef(0),live=useRef(true);
  useEffect(()=>{live.current=true;return()=>{live.current=false;generation.current+=1;};},[]);
  const supported=typeof api?.tarazMadarDataRead==='function';
  const reset=()=>{generation.current+=1;setSnapshot(null);setError('');setOffset(0);setLoading(false);};
  const read=async(nextOffset=0)=>{
    if(!canAdmin||!supported||!consent||loading)return;
    const request=++generation.current;
    setLoading(true);setError('');
    try{
      const auth=source==='host'?{...connection}:null;
      const received=await api.tarazMadarDataRead(scope,nextOffset,50,true,auth,source);
      if(!received||received.scope!==scope||received.offset!==nextOffset||
        received.financialEventCreated!==false||
        !received.items||typeof received.items!=='object'||
        !received.counts||typeof received.counts!=='object'||
        !received.source||received.source.readOnly!==true||
        (source==='host'&&received.source.serverAclApplied!==true)||
        (source==='local'&&received.source.hostAuthenticated!==false)||
        !Array.isArray(received.items[scope])){
        throw Error('پاسخ خواندن اطلاعات مدار با قرارداد ایمن سازگار نیست.');
      }
      if(live.current&&generation.current===request){setSnapshot(received);setOffset(nextOffset);}
    }catch(_error){if(live.current&&generation.current===request){
      // A host exception may include LAN credentials, access tokens or private
      // project content. Never copy arbitrary host text into the visible UI.
      setSnapshot(null);setError('خواندن اطلاعات مدار ناموفق بود؛ اتصال، مجوز و منبع داده را بررسی کنید.');
    }}finally{if(live.current&&generation.current===request)setLoading(false);}
  };
  const entries=snapshot?.items?.[scope]||[];
  return <section className="taraz-madar-explorer" aria-label="خواندن اطلاعات مدار">
    <div className="taraz-madar-explorer-head"><h3>خواندن اطلاعات مدار</h3>
      <p>نمایش درخواستی اطلاعات مجاز پروژه‌ها و کارها، بدون تغییر داده‌ها</p></div>
    <p className="taraz-madar-boundary">این بخش فقط فیلدهای تعیین‌شده توسط API را نمایش می‌دهد؛ هزینه‌ها، حسابداری، پیوست‌ها و اطلاعات محرمانه در خروجی این API ارائه نمی‌شوند.</p>
    {!supported&&<p className="taraz-madar-empty" role="status">میزبان فعلی API خواندن پروژه‌های مدار را ارائه نمی‌کند.</p>}
    {!canAdmin&&<p className="taraz-madar-empty" role="status">خواندن اطلاعات پروژه‌های مدار در تراز نیازمند نقش مدیر است.</p>}
    {supported&&canAdmin&&<>
      <label className="taraz-madar-consent"><input type="checkbox" checked={consent}
        onChange={e=>{setConsent(e.target.checked);reset();
          if(!e.target.checked)setConnection(DEFAULT_HOST);}} disabled={loading}/>
        اجازه می‌دهم فقط با دکمه دریافت، اطلاعات انتخاب‌شده مدار خوانده شوند
      </label>
      {consent&&<>
        <div className="taraz-madar-explorer-options">
          <label>منبع داده
            <select value={source} onChange={e=>{setSource(e.target.value);reset();setConnection(DEFAULT_HOST);}}>
              <option value="local">فایل محلی همین کاربر (احتمالاً قدیمی)</option>
              <option value="host">میزبان مدار (HTTPS احراز هویت‌شده)</option>
            </select></label>
          <label>نوع اطلاعات
            <select value={scope} onChange={e=>{setScope(e.target.value);reset();}}>
              {MADAR_SCOPES.map(([key,title])=><option value={key} key={key}>{title}</option>)}
            </select></label>
        </div>
        {source==='host'&&<fieldset className="taraz-madar-host-fields">
          <legend>اتصال مستقیم به میزبان مدار</legend>
          <p>نشانی HTTPS خصوصی، اثرانگشت SHA-256 گواهی و حساب معتبر مدار را وارد کنید. اطلاعات ورود فقط در حافظه همین فرم می‌مانند.</p>
          {[['url','نشانی میزبان HTTPS','url','https://192.168.1.10:48370'],
            ['fingerprint','اثر انگشت SHA-256','text','۶۴ رقم هگزادسیمال'],
            ['username','نام کاربری مدار','text',''],
            ['password','گذرواژه مدار','password','']].map(([key,label,type,placeholder])=><label key={key}>
            {label}<input type={type} dir="ltr" autoComplete="off" placeholder={placeholder}
              value={connection[key]} onChange={e=>{setConnection(p=>({...p,[key]:e.target.value}));reset();}}/>
          </label>)}
        </fieldset>}
        <div className="taraz-madar-controls">
          <button type="button" className="taraz-madar-refresh" disabled={loading}
            onClick={()=>void read(0)}>{loading?'در حال خواندن...':'خواندن اطلاعات انتخاب‌شده'}</button>
        </div>
        {error&&<p role="alert" className="taraz-madar-error">{error}</p>}
        {snapshot&&<>
          <div className="taraz-madar-summary" aria-label="منبع و تعداد اطلاعات مدار">
            <span>منبع: {snapshot.source.kind==='madar-authorized-host-state-projection'?
              'میزبان احراز هویت‌شده مدار':'فایل محلی مدار، احراز هویت نشده'}</span>
            <span>تعداد {MADAR_SCOPES.find(([key])=>key===scope)?.[1]}: {
              Number.isSafeInteger(snapshot.counts[scope])?snapshot.counts[scope].toLocaleString('fa-IR'):'نامشخص'}</span>
            <span>دریافت‌شده در این صفحه: {entries.length.toLocaleString('fa-IR')}</span>
            {snapshot.source.mayBeStale&&<span>ممکن است داده محلی به‌روز نباشد.</span>}
            {snapshot.source.serverAclApplied===true&&<span>محدودیت دسترسی پروژه‌ها توسط میزبان اعمال شده است.</span>}
          </div>
          {entries.length===0&&<p className="taraz-madar-empty">در این صفحه رکوردی دریافت نشد.</p>}
          <div className="taraz-madar-requests">
            {entries.map((item,i)=><article className="taraz-madar-request" key={item.id||i}>
              <strong>{item.title||item.name||'رکورد بدون عنوان'}</strong>
              <div className="taraz-madar-provenance">
                <small>شناسه: <code dir="ltr">{item.id||'نامشخص'}</code></small>
                {item.projectId&&<small>پروژه: <code dir="ltr">{item.projectId}</code></small>}
                {item.status&&<small>وضعیت: {item.status}</small>}
                {item.description&&<small className="taraz-madar-record-description">{item.description}</small>}
              </div>
            </article>)}
          </div>
          <div className="taraz-madar-pagination">
            <button type="button" disabled={loading||offset===0}
              onClick={()=>void read(Math.max(0,offset-50))}>صفحه قبل</button>
            <span>از ردیف {(offset+1).toLocaleString('fa-IR')}</span>
            <button type="button" disabled={loading||snapshot.more?.[scope]!==true}
              onClick={()=>void read(offset+50)}>صفحه بعد</button>
          </div>
        </>}
      </>}
    </>}
  </section>;
}

/** On-demand authenticated bridge inbox. No ledger operation is performed here. */
export default function TarazMadarDashboard({api,canReview=false,canDraft=false,
  onDraftFromMadar=null,onOpenSection=null,compact=false,canAdmin=false}){
  const capabilities=integrationCapabilities(api);
  const [consent,setConsent]=useState(false);
  const [result,setResult]=useState(null);
  const [loading,setLoading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [status,setStatus]=useState('');
  const [query,setQuery]=useState('');
  const [filter,setFilter]=useState('pending');
  const [selection,setSelection]=useState(null);
  const generation=useRef(0);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;generation.current+=1;};},[]);

  const refresh=useCallback(async()=>{
    if(!consent||!capabilities.canList||loading||busy)return;
    const request=++generation.current;
    setLoading(true);setError('');setStatus('');
    try{
      const next=await listTarazIntegration(api);
      if(mounted.current&&generation.current===request)setResult(next);
    }catch(_error){if(mounted.current&&generation.current===request){
      setResult(null);setError('خواندن صندوق مدار ناموفق بود؛ وضعیت اتصال و مجوز را بررسی کنید.');
    }}finally{if(mounted.current&&generation.current===request)setLoading(false);}
  },[api,consent,loading,busy,capabilities.canList]);

  const changeConsent=allowed=>{
    generation.current+=1;
    setConsent(allowed);setResult(null);setSelection(null);setError('');setStatus('');
    setLoading(false);setQuery('');setFilter('pending');
  };

  const entries=useMemo(()=>{
    if(!result)return [];
    const pending=result.requests.map(item=>({...item,entryType:'pending',state:'pending'}));
    const recoveries=result.recovery.map(item=>({...item,entryType:'recovery'}));
    const needle=query.trim().toLocaleLowerCase('fa-IR');
    return [...pending,...recoveries].filter(item=>
      (filter==='all'||filter===item.entryType)&&
      (!needle||[item.title,item.taskId,item.projectId,item.id]
        .some(value=>String(value||'').toLocaleLowerCase('fa-IR').includes(needle))));
  },[result,query,filter]);

  const decide=async()=>{
    if(!consent||!selection||busy||!canReview||!capabilities.canReview)return;
    const {id,state,recovery}=selection;
    if(recovery&&!capabilities.canRecover)return;
    const request=++generation.current;
    setBusy(true);setError('');setStatus('');
    try{
      if(recovery)await recoverTarazIntegration(api,id,state);
      else await reviewTarazIntegration(api,id,state);
      if(!mounted.current||generation.current!==request)return;
      setSelection(null);
      setStatus(recovery?'تصمیم پیشین از میزبان بازیابی شد؛ سند مالی ایجاد نشد.':
        'تصمیم ارجاع در میزبان ثبت شد؛ سند مالی ایجاد نشد.');
      setLoading(true);
      try{
        const next=await listTarazIntegration(api);
        if(mounted.current&&generation.current===request)setResult(next);
      }catch(_error){if(mounted.current&&generation.current===request){
        setResult(null);setError('تصمیم به میزبان ارسال شد، اما بازخوانی صندوق ناموفق بود. وضعیت را پیش از تکرار بررسی کنید.');
      }}finally{if(mounted.current&&generation.current===request)setLoading(false);}
    }catch(_error){if(mounted.current&&generation.current===request){
      setSelection(null);
      setResult(null);
      setError('نتیجه تصمیم نامشخص است. قبل از تصمیم مجدد، صندوق و بازیابی‌های میزبان را بازخوانی کنید.');
    }}finally{if(mounted.current&&generation.current===request)setBusy(false);}
  };

  return <section dir="rtl" className={'taraz-madar-dashboard'+(compact?' taraz-madar-home':'')}
    aria-label="اطلاعات مدار">
    <header className="taraz-madar-heading">
      <div className="taraz-madar-title">
        <span className="taraz-madar-mark"><ClipboardList size={21}/></span>
        <div><small>ارتباط مدار و تراز</small><h2>اطلاعات مدار</h2>
          <p>دریافت و بررسی ارجاع‌های مدار، با تصمیم دستی شما</p></div>
      </div>
      {compact&&typeof onOpenSection==='function'&&<button type="button" className="taraz-madar-open"
        onClick={onOpenSection}>ورود به بخش اطلاعات مدار <ArrowLeft size={16}/></button>}
    </header>
    <div className="taraz-madar-connection">
      <div><strong>رابط میزبان</strong>
        <span>{capabilities.canList?'دریافت ارجاع قابل درخواست است':'دریافت ارجاع در این نسخه فعال نیست'}</span>
        <small>موجود بودن API به معنی اتصال موفق مدار نیست. اتصال با بازخوانی مشخص می‌شود.</small></div>
      <div><strong>مجوز بررسی</strong>
        <span>{canReview&&capabilities.canReview?'بررسی و رد دستی':'فقط مشاهده'}</span>
        <small>هیچ ارجاعی خودکار به فاکتور یا دفترکل تبدیل نمی‌شود.</small></div>
      {result&&<div><strong>وضعیت صندوق</strong>
        <span>{result.connected?'در دسترس':'متصل نیست'}</span>
        <small>{result.requests.length.toLocaleString('fa-IR')} ارجاع در انتظار بررسی</small></div>}
    </div>
    <div className="taraz-madar-controls">
      <label className="taraz-madar-consent">
        <input type="checkbox" checked={consent} onChange={e=>changeConsent(e.target.checked)}
          disabled={busy}/>
        اجازه می‌دهم اطلاعات صندوق مدار را به درخواست خودم بخوانم
      </label>
      <button type="button" className="taraz-madar-refresh" disabled={!consent||!capabilities.canList||busy||loading}
        onClick={()=>void refresh()}><RefreshCw size={16}/>{loading?'در حال دریافت...':'دریافت / بازخوانی ارجاع‌های مدار'}</button>
    </div>
    {error&&<p className="taraz-madar-error" role="alert">{error}</p>}
    {status&&<p className="taraz-madar-message" role="status">{status}</p>}
    {result&&consent&&<>
      <div className="taraz-madar-summary" aria-label="وضعیت ارجاع‌های مدار">
        <span><strong>{result.requests.length.toLocaleString('fa-IR')}</strong> در انتظار بررسی</span>
        <span><strong>{result.recovery.length.toLocaleString('fa-IR')}</strong> تصمیم نیازمند بازیابی</span>
        {result.pendingTruncated&&<span role="alert">فهرست ارجاع‌های در انتظار کامل نیست؛ فقط بخشی از صندوق نمایش داده شده است. برای مشاهدهٔ سایر موارد، موارد موجود را تعیین تکلیف و دوباره بازخوانی کنید.</span>}
        {result.invalidCount>0&&<span>ارجاع‌های نامعتبر: {result.invalidCount.toLocaleString('fa-IR')}</span>}
        {result.recoveryInvalidCount>0&&<span>بازیابی‌های نامعتبر: {result.recoveryInvalidCount.toLocaleString('fa-IR')}</span>}
        {result.recoveryTruncated&&<span>فهرست بازیابی ناقص است؛ اطلاعات کامل نمایش داده نشده.</span>}
      </div>
      {!result.connected&&<p className="taraz-madar-empty" role="status">صندوق مدار در میزبان در دسترس نیست. وضعیت ارسال مدار را بررسی کنید.</p>}
      <div className="taraz-madar-filters">
        <label>جست‌وجوی ارجاع
          <input type="search" value={query} onChange={e=>setQuery(e.target.value)}
            placeholder="عنوان، پروژه، تسک یا شناسه" maxLength={180}/></label>
        <label>وضعیت
          <select value={filter} onChange={e=>setFilter(e.target.value)}>
            <option value="pending">در انتظار بررسی</option>
            <option value="recovery">تصمیم‌های نیازمند بازیابی</option>
            <option value="all">همه موارد دریافتی</option>
          </select></label>
      </div>
      {entries.length===0&&<p className="taraz-madar-empty">برای فیلتر انتخابی ارجاعی یافت نشد.</p>}
      <div className="taraz-madar-requests">
        {entries.map(item=><article className="taraz-madar-request" key={item.entryType+':'+item.id}>
          <div className="taraz-madar-request-title"><strong>{item.title}</strong>
            <span className="taraz-madar-state">{item.entryType==='pending'?'منتظر بررسی':
              item.state==='rejected'?'ردشده، نیازمند بازیابی':'بررسی‌شده، نیازمند بازیابی'}</span></div>
          <div className="taraz-madar-provenance">
            <small>منبع: صندوق ارجاع مدار در میزبان تراز</small>
            <small>تسک: <code dir="ltr">{item.taskId}</code></small>
            {item.projectId&&<small>پروژه: <code dir="ltr">{item.projectId}</code></small>}
            <small>شناسه ارجاع: <code dir="ltr">{item.id}</code></small>
            {Number.isSafeInteger(item.amountRial)&&<small>مبلغ پیشنهادی: {item.amountRial.toLocaleString('fa-IR')} ریال (تأییدنشده)</small>}
          </div>
          <div className="taraz-madar-actions">
            {item.entryType==='pending'?<>
              {canDraft&&typeof onDraftFromMadar==='function'&&<button type="button"
                disabled={busy||loading} onClick={()=>onDraftFromMadar(item)}
                title="فقط شرح را به فرم پیش‌نویس می‌برد؛ مبلغ و طرف حساب باید جداگانه وارد شود.">
                آماده‌سازی متن پیش‌نویس</button>}
              {canReview&&capabilities.canReview&&<>
                <button type="button" disabled={busy||loading}
                  onClick={()=>setSelection({id:item.id,state:'reviewed',title:item.title,recovery:false})}>
                  <CheckCircle2 size={15}/> بررسی شد</button>
                <button type="button" disabled={busy||loading}
                  onClick={()=>setSelection({id:item.id,state:'rejected',title:item.title,recovery:false})}>
                  <XCircle size={15}/> رد ارجاع</button>
              </>}
            </>:canReview&&capabilities.canRecover&&<button type="button" disabled={busy||loading}
              onClick={()=>setSelection({id:item.id,state:item.state,title:item.title,recovery:true})}>
              بازیابی دستی تصمیم پیشین</button>}
          </div>
        </article>)}
      </div>
    </>}
    {selection&&consent&&<div className="taraz-madar-confirm" role="group" aria-label="تأیید دستی ارجاع مدار">
      <strong>{selection.recovery?'بازیابی تصمیم قبلی':selection.state==='rejected'?'رد ارجاع مدار':'ثبت بررسی ارجاع مدار'}</strong>
      <p>{selection.title}</p>
      <small>این اقدام فقط وضعیت ارجاع را در میزبان تغییر می‌دهد؛ سند یا رویداد حسابداری ثبت نمی‌کند.</small>
      <div><button type="button" disabled={busy} className="taraz-madar-refresh"
        onClick={()=>void decide()}>{busy?'در حال ثبت تصمیم...':'تأیید نهایی تصمیم'}</button>
        <button type="button" disabled={busy} onClick={()=>setSelection(null)}>انصراف</button></div>
    </div>}
    <p className="taraz-madar-boundary"><ShieldCheck size={16}/>
      تصمیم‌های صندوق فقط وضعیت ارجاع را تغییر می‌دهند. ثبت مالی و انتقال خودکار انجام نمی‌شود.</p>
    <MadarDataExplorer api={api} canAdmin={canAdmin}/>
  </section>;
}
