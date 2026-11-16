import React,{useEffect,useState} from 'react';

/** Read-only model text, deliberately separate from financial draft actions. */
export default function TarazAiLocalPanel({api,canEdit=false}){
  const [status,setStatus]=useState(null);
  const [model,setModel]=useState('');
  const [prompt,setPrompt]=useState('');
  const [reply,setReply]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const supported=typeof api?.tarazAiLocalStatus==='function'&&
    typeof api?.tarazAiLocalGenerate==='function';
  const refresh=async()=>{
    if(!supported)return;
    setError('');
    try{
      const found=await api.tarazAiLocalStatus();
      setStatus(found);
      const names=Array.isArray(found?.models)?found.models.map(m=>m.name):[];
      setModel(previous=>names.includes(previous)?previous:names[0]||'');
    }catch(_err){setError('دریافت وضعیت مدل محلی ممکن نیست.');}
  };
  useEffect(()=>{
    let active=true;
    if(!supported)return;
    api.tarazAiLocalStatus().then(result=>{
      if(!active)return;
      setStatus(result);
      const names=Array.isArray(result?.models)?result.models.map(m=>m.name):[];
      setModel(names[0]||'');
    }).catch(()=>{if(active)setError('دریافت وضعیت مدل محلی ممکن نیست.');});
    return ()=>{active=false;};
  },[api,supported]);
  const ask=async event=>{
    event.preventDefault();
    if(!canEdit||!model||!prompt.trim()||busy)return;
    setBusy(true);setReply('');setError('');
    try{
      const result=await api.tarazAiLocalGenerate({
        model,prompt:prompt.trim(),manualConsent:true});
      if(result?.modelRan!==true||result?.provider!=='ollama'||
          result?.journalPosted!==false||typeof result.response!=='string'){
        throw Error('Unverifiable local model response');
      }
      setReply(result.response);
    }catch(_err){
      setError('پاسخ واقعی مدل محلی تأیید نشد. وضعیت Ollama یا محدودیت زمان را بررسی کنید.');
    }finally{setBusy(false);}
  };
  return <details className="taraz-local-ai-panel">
    <summary>هوش مصنوعی ← مدل محلی (پاسخ واقعی، بدون ابزار مالی)</summary>
    <p>این قابلیت فقط متن شما را با اقدام مستقیم به Ollama همین رایانه می‌فرستد.
      به اطلاعات حسابداری دسترسی خودکار ندارد، تاریخچه را ذخیره نمی‌کند و مجوز ثبت سند مالی نمی‌دهد.</p>
    {!supported?<p role="status">نسخهٔ نصب‌شده هنوز API مدل محلی را ندارد.</p>:<>
      <div className="taraz-local-ai-row">
        <button type="button" onClick={refresh} disabled={busy}>بازخوانی مدل‌های نصب‌شده</button>
        <label>مدل نصب‌شده
          <select value={model} disabled={busy||!status?.available}
            onChange={event=>setModel(event.target.value)}>
            {(status?.models||[]).map(item=><option key={item.name} value={item.name}>
              {item.name} ({Math.ceil(item.bytes/1048576)} MB)
            </option>)}
          </select>
        </label>
      </div>
      {status?.available===false&&<p role="status">Ollama یا مدل نصب‌شده در دسترس نیست.</p>}
      {status?.hardware&&<small>
        سخت‌افزار: {status.hardware.cpu||'نامشخص'} |
        RAM آزاد: {Math.floor((status.hardware.ramAvailableBytes||0)/1073741824)} GB |
        GPU/VRAM: {status.hardware.gpu==='Unknown'?'تأییدنشده':status.hardware.gpu}
      </small>}
      <form onSubmit={ask}>
        <label htmlFor="taraz-local-ai-input">درخواست متنی فارسی</label>
        <textarea id="taraz-local-ai-input" rows={3} maxLength={600}
          value={prompt} onChange={e=>setPrompt(e.target.value)}
          placeholder="فقط یک توضیح متنی بخواهید؛ این بخش هیچ عملیات مالی انجام نمی‌دهد."/>
        <button type="submit" disabled={!canEdit||busy||!model||!prompt.trim()}>
          {busy?'در حال دریافت پاسخ مدل…':'ارسال به مدل محلی'}</button>
      </form>
      {reply&&<section className="taraz-local-ai-reply" aria-label="پاسخ واقعی مدل محلی">
        <strong>پاسخ مدل {model} (نیازمند بررسی انسانی)</strong>
        <p>{reply}</p></section>}
      {error&&<p role="alert">{error}</p>}
      <small>کیفیت فارسی و تصمیم‌های مالی مدل هنوز تأیید نشده‌اند. نصب و دانلود مدل در این نسخه فعال نیست.</small>
    </>}
  </details>;
}
