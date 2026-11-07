import React,{useCallback,useEffect,useState} from 'react';
import './taraz_integration_panel.css';

export default function TarazIntegrationPanel({api}) {
  const [open,setOpen]=useState(false);
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState('');
  const refresh=useCallback(async()=>{
    if(typeof api?.tarazIntegrationList!=='function'){
      setError('نسخه فعلی میزبان تراز ارتباط اختیاری با مدار را فعال نکرده است.');return;
    }
    setLoading(true);setError('');
    try {setResult(await api.tarazIntegrationList());}
    catch(e){setError(String(e?.message||e));}
    finally {setLoading(false);}
  },[api]);
  useEffect(()=>{if(open)void refresh();},[open,refresh]);
  async function review(item,decision) {
    if(typeof api.tarazIntegrationReview!=='function')return;
    const question=decision==='reviewed'?
      'این ارجاع فقط بررسی و بایگانی می‌شود؛ هیچ سند مالی صادر نخواهد شد. ادامه می‌دهید؟':
      'ارجاع بدون تغییر هیچ سند مالی رد شود؟';
    if(!window.confirm(question))return;
    setBusy(item.id);
    try {
      const answer=await api.tarazIntegrationReview(item.id,decision);
      if(answer?.financialEventCreated!==false)throw Error('نتیجه اتصال معتبر نیست');
      await refresh();
    }catch(e){setError(String(e?.message||e));}
    finally{setBusy('');}
  }
  return <section className={'taraz-bridge-panel'+(open?' open':'')} aria-label="ارتباط اختیاری با مدار">
    <button type="button" className="taraz-bridge-toggle" aria-expanded={open}
      onClick={()=>setOpen(!open)}>ارتباط با مدار {open?'−':'+'}</button>
    {open&&<div className="taraz-bridge-body">
      <header><strong>ارجاع‌های دریافتی از مدار</strong>
        <button type="button" onClick={()=>void refresh()} disabled={loading}>بازخوانی</button></header>
      <p>تسک‌ها فقط به‌عنوان پیشنهاد وارد می‌شوند. تأیید، صدور فاکتور یا ثبت سند حسابداری از این اتصال انجام نمی‌شود.</p>
      {!!error&&<p role="alert" className="taraz-bridge-error">{error}</p>}
      {loading&&<p role="status">در حال خواندن صندوق ارتباط...</p>}
      {result&&!result.connected&&<p>ارتباط هنوز فعال نیست؛ در مدار از «ارسال به تراز» استفاده کنید.</p>}
      {result?.invalidCount>0&&<p className="taraz-bridge-error">{result.invalidCount} ارجاع نامعتبر برای امنیت نمایش داده نشد.</p>}
      {result?.connected&&result.requests?.length===0&&<p>ارجاع بررسی‌نشده‌ای وجود ندارد.</p>}
      <div className="taraz-bridge-list">
        {(result?.requests||[]).map(item=><article key={item.id}>
          <strong>{item.title}</strong>
          <small>شناسه تسک: <code dir="ltr">{item.taskId}</code></small>
          {Number.isSafeInteger(item.amountRial)&&<small>مبلغ پیشنهادی: {item.amountRial.toLocaleString('fa-IR')} ریال، بدون ثبت مالی</small>}
          <div><button type="button" disabled={!!busy} onClick={()=>review(item,'reviewed')}>بررسی شد</button>
            <button type="button" disabled={!!busy} onClick={()=>review(item,'rejected')}>رد ارجاع</button></div>
        </article>)}
      </div>
    </div>}
  </section>;
}
