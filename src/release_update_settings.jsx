import React,{useState} from 'react';
import {CheckCircle2,Download,RefreshCw,ShieldCheck} from 'lucide-react';

/** Manual desktop updater. Host owns release URLs, SHA-256 validation and install.
 * No URL, command or filesystem path crosses from React into the native host.
 */
export default function ReleaseUpdateSettings({api,context='planner'}){
  const [busy,setBusy]=useState('');
  const [release,setRelease]=useState(null);
  const [downloaded,setDownloaded]=useState(false);
  const [scheduled,setScheduled]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const supported=typeof api?.releaseCheck==='function'&&
    typeof api?.releaseDownload==='function'&&typeof api?.releaseInstall==='function';
  const run=async(action,fn)=>{
    if(busy||!supported)return;
    setBusy(action);setError('');setMessage('');
    try{await fn();}
    catch(e){setError(e?.message||'ارتباط با سرویس امن به‌روزرسانی برقرار نشد.');}
    finally{setBusy('');}
  };
  const check=()=>run('check',async()=>{
    const next=await api.releaseCheck();
    if(!next||typeof next.available!=='boolean'||
       typeof next.current!=='string'||typeof next.latest!=='string'){
      throw Error('پاسخ سرویس به‌روزرسانی معتبر نیست.');
    }
    setRelease({available:next.available,current:next.current,latest:next.latest});
    setDownloaded(false);setScheduled(false);
    setMessage(next.available?'نسخهٔ جدید در مخزن انتشار رسمی پیدا شد.':
      'نسخهٔ جدیدتری در مخزن انتشار رسمی گزارش نشد.');
  });
  const download=()=>run('download',async()=>{
    const result=await api.releaseDownload();
    if(result?.verified!==true)throw Error('تأیید امنیت فایل نصب انجام نشد.');
    setDownloaded(true);
    setMessage('بسته پس از تطبیق SHA-256 آمادهٔ نصب است.');
  });
  const install=()=>{
    if(!globalThis.confirm?.('نصب نسخهٔ جدید بعد از بسته‌شدن کامل برنامه انجام می‌شود. قبل از خروج، داده‌ها باید طبق گیت نصب‌کننده پشتیبان‌گیری شوند. ادامه می‌دهید؟'))return;
    run('install',async()=>{
      const result=await api.releaseInstall();
      if(result?.scheduledAfterExit!==true)
        throw Error('زمان‌بندی نصب ایمن تأیید نشد.');
      setScheduled(true);
      setMessage('نصب پس از خروج کامل برنامه زمان‌بندی شد؛ برنامه را به‌طور معمول ببندید.');
    });
  };
  return <section className="setting-block madar-release-settings"
    aria-label={'به‌روزرسانی '+(context==='accounting'?'حسابداری':'تسک‌منیجر')}>
    <h3><RefreshCw size={17}/> به‌روزرسانی برنامه</h3>
    <p>حسابداری و تسک‌منیجر از بستهٔ نصب یکپارچهٔ Madar Desk استفاده می‌کنند.
      نصب فقط با تأیید کاربر و تطبیق هش SHA-256 فایل منتشرشده انجام می‌شود.</p>
    {!supported?<p role="status">بررسی به‌روزرسانی فقط در نسخهٔ نصب‌شدهٔ ویندوز در دسترس است.</p>:<>
      <div className="theme-picks">
        <button type="button" disabled={!!busy||scheduled} onClick={check}>
          <RefreshCw size={17}/> {busy==='check'?'در حال بررسی…':'بررسی به‌روزرسانی'}
        </button>
        {release?.available&&<button type="button" disabled={!!busy||downloaded||scheduled}
          onClick={download}><Download size={17}/>
          {busy==='download'?'در حال دریافت…':'دریافت و تأیید فایل'}</button>}
        {release?.available&&downloaded&&!scheduled&&<button type="button"
          disabled={!!busy} onClick={install}><ShieldCheck size={17}/>
          {busy==='install'?'در حال آماده‌سازی…':'نصب پس از خروج'}</button>}
      </div>
      {release&&<p>نسخهٔ فعلی: <strong dir="ltr">{release.current}</strong>
        {' · '}آخرین نسخهٔ گزارش‌شده: <strong dir="ltr">{release.latest}</strong></p>}
      {message&&<p role="status"><CheckCircle2 size={15} aria-hidden="true"/> {message}</p>}
      {error&&<p role="alert">{error}</p>}
    </>}
  </section>;
}
