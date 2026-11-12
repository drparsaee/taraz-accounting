import React,{useCallback,useEffect,useState} from 'react';
import {Check,ChevronLeft,CircleHelp,ExternalLink,Link2,Monitor,
  Moon,RefreshCw,ShieldCheck,Sun,Users,Wallet,SlidersHorizontal} from 'lucide-react';
import {readTarazSettings,saveTarazSettings,applyTarazSettings} from './taraz_settings_preferences.js';
import {integrationCapabilities,listTarazIntegration,reviewTarazIntegration,recoverTarazIntegration}
  from './taraz_settings_integration.js';
import './taraz_settings.css';

const PAGES=[
  ['general','عمومی',SlidersHorizontal],
  ['account','حساب کاربری',Users],
  ['integration','اتصال به مدار',Link2],
  ['subscription','اشتراک و خرید',Wallet]
];
const OPTIONS={
  theme:[['system','سیستم',Monitor],['light','روشن',Sun],['dark','تیره',Moon]],
  font:[['estedad','استعداد'],['vazirmatn','وزیرمتن'],['tahoma','تاهوما']],
  size:[['compact','کوچک'],['normal','معمولی'],['large','بزرگ']],
  width:[['compact','متمرکز'],['comfortable','استاندارد'],['wide','عریض']],
  motion:[['system','طبق سیستم'],['reduce','کاهش حرکت'],['full','معمولی']]
};
function Row({title,description,children}){
  return <div className="taraz-settings-row">
    <div className="taraz-settings-row-text"><strong>{title}</strong>
      {description&&<p>{description}</p>}</div>
    <div className="taraz-settings-row-control">{children}</div>
  </div>;
}
function Choice({options,value,onChange,label}){
  return <div className="taraz-settings-choice" role="group" aria-label={label}>
    {options.map(([key,title,Icon])=><button type="button" key={key}
      className={value===key?'selected':''} aria-pressed={value===key}
      onClick={()=>onChange(key)}>{Icon&&<Icon size={15} aria-hidden="true"/>}{title}</button>)}
  </div>;
}
function Section({eyebrow,title,description,children}){
  return <section className="taraz-settings-section">
    <div className="taraz-settings-section-title"><span>{eyebrow}</span><h3>{title}</h3>
      {description&&<p>{description}</p>}</div>
    <div className="taraz-settings-rows">{children}</div>
  </section>;
}

function IntegrationSettings({api,canReview,canDraft=false,onDraftFromMadar=null}){
  const capability=integrationCapabilities(api);
  const [enabled,setEnabled]=useState(false);
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState(null);
  const [error,setError]=useState('');
  const [status,setStatus]=useState('');
  const [selected,setSelected]=useState(null);
  const [busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{
    setLoading(true);setError('');setStatus('');
    try{setResult(await listTarazIntegration(api));}
    catch(_error){setResult(null);setError('خواندن صندوق مدار ناموفق بود؛ اتصال و دسترسی را بررسی کنید.');}
    finally{setLoading(false);}
  },[api]);
  async function decide(){
    if(!selected||busy||!enabled)return;
    const {id,decision,recovery=false}=selected;
    setBusy(true);setError('');setStatus('');
    try{
      if(recovery)await recoverTarazIntegration(api,id,decision);
      else await reviewTarazIntegration(api,id,decision);
      setSelected(null);
      // Only metadata is acknowledged. A second explicit read updates the visible queue.
      setStatus(recovery?'تصمیم قبلی از ثبت پایدار بازیابی شد. هیچ سند مالی ایجاد نشد.':
        'ارجاع در صندوق اتصال بررسی شد. هیچ سند مالی ایجاد نشد.');
      setLoading(true);
      try{setResult(await listTarazIntegration(api));}
      catch(_error){setResult(null);setError('تصمیم به میزبان ارسال شد، اما بازخوانی صندوق ناموفق بود. پیش از تکرار وضعیت را بررسی کنید.');}
      finally{setLoading(false);}
    }catch(_error){setError('نتیجه تصمیم نامشخص است؛ قبل از تکرار، وضعیت صندوق و بازیابی‌ها را بررسی کنید.');}
    finally{setBusy(false);}
  }
  return <Section eyebrow="Madar + Taraz" title="اتصال اختیاری مدار به تراز"
    description="ارجاع‌های مدار صرفاً پیشنهاد هستند؛ مرور آن‌ها هیچ عملیاتی در دفترکل ایجاد نمی‌کند.">
    <Row title="اجازهٔ نمایش صندوق ارجاع‌ها"
      description="این انتخاب فقط در همین صفحه فعال است. خواندن ارجاع‌ها به فشار دادن دکمهٔ بازخوانی نیاز دارد.">
      <label className="taraz-settings-check">
        <input type="checkbox" checked={enabled} onChange={e=>{
          setEnabled(e.target.checked);setSelected(null);setResult(null);setError('');setStatus('');
        }}/><span>اجازه می‌دهم ارجاع‌های مدار را دستی بررسی کنم</span>
      </label>
    </Row>
    <Row title="وضعیت رابط میزبان"
      description="اتصال تنها زمانی فعال است که میزبان ویندوز APIهای رسمی تراز را ارائه کند.">
      <span className={'taraz-settings-status '+(capability.canList?'ok':'muted')}>
        {capability.canList?'خواندن صندوق در دسترس است':'خواندن صندوق در دسترس نیست'}</span>
      <span className={'taraz-settings-status '+(capability.canReview&&canReview?'ok':'muted')}>
        {capability.canReview&&canReview?'بررسی دستی مجاز است':'بررسی دستی غیرفعال است'}</span>
    </Row>
    <Row title="بازخوانی ارجاع‌ها" description="وضعیت از خود میزبان خوانده می‌شود و در حافظهٔ این صفحه باقی می‌ماند.">
      <button type="button" className="taraz-settings-action" disabled={!enabled||!capability.canList||loading||busy}
        onClick={()=>void refresh()}><RefreshCw size={16}/> {loading?'در حال خواندن...':'بررسی وضعیت اتصال'}</button>
    </Row>
    {error&&<div className="taraz-settings-message error" role="alert">{error}</div>}
    {status&&<div className="taraz-settings-message" role="status">{status}</div>}
    {enabled&&result&&<>
      <div className="taraz-settings-connection-summary" role="status">
        <span>صندوق مدار: <strong>{result.connected?'در دسترس':'متصل نیست'}</strong></span>
        <span>ارجاع‌های منتظر بررسی: <strong>{result.requests.length.toLocaleString('fa-IR')}</strong></span>
        {result.pendingTruncated&&<span role="alert">فهرست ارجاع‌های در انتظار ناقص است؛ پس از تعیین تکلیف موارد موجود، صندوق را دوباره بازخوانی کنید.</span>}
        {result.recovery?.length>0&&<span>تصمیم‌های ناتمام قابل بازیابی: <strong>{result.recovery.length.toLocaleString('fa-IR')}</strong></span>}
        {result.invalidCount>0&&<span>ارجاع‌های نامعتبر کنار گذاشته‌شده: {result.invalidCount.toLocaleString('fa-IR')}</span>}
        {result.recoveryInvalidCount>0&&<span>بازیابی‌های نامعتبر یا متعارض: {result.recoveryInvalidCount.toLocaleString('fa-IR')}</span>}
        {result.recoveryTruncated&&<span>فهرست بازیابی بیش از حد بزرگ است؛ بازیابی خودکار ممنوع است.</span>}
      </div>
      {result.connected&&result.requests.length===0&&
        <p className="taraz-settings-muted">ارجاع بررسی‌نشده‌ای در صندوق وجود ندارد.</p>}
      {result.requests.map(item=><article className="taraz-settings-request" key={item.id}>
        <div><strong>{item.title}</strong><small>شناسه تسک: <code dir="ltr">{item.taskId}</code></small>
          {Number.isSafeInteger(item.amountRial)&&
            <small>مبلغ پیشنهادی: {item.amountRial.toLocaleString('fa-IR')} ریال؛ ثبت‌نشده</small>}</div>
        <div className="taraz-settings-request-actions">
          {canDraft&&typeof onDraftFromMadar==='function'&&
            <button type="button" disabled={busy||loading||!enabled}
              onClick={()=>onDraftFromMadar(item)}
              title="فقط شرح را در فرم پیش‌نویس وارد می‌کند؛ طرف حساب، قیمت، مالیات و ثبت سند با شماست.">
              آماده‌سازی پیش‌نویس فروش
            </button>}
          <button type="button" disabled={!capability.canReview||!canReview||busy}
            onClick={()=>setSelected({id:item.id,decision:'reviewed',title:item.title})}>بررسی شد</button>
          <button type="button" disabled={!capability.canReview||!canReview||busy}
            onClick={()=>setSelected({id:item.id,decision:'rejected',title:item.title})}>رد ارجاع</button>
        </div>
      </article>)}
      {(result.recovery||[]).map(item=><article className="taraz-settings-request" key={'recover-'+item.id}>
        <div><strong>{item.title}</strong>
          <small>تصمیم ثبت‌شده اما ناتمام: {item.state==='reviewed'?'بررسی شد':'رد ارجاع'}</small>
          <small>این عملیات فقط همان تصمیم قبلی را تکمیل می‌کند؛ سند حسابداری ایجاد نمی‌شود.</small></div>
        <div className="taraz-settings-request-actions">
          <button type="button" disabled={!enabled||!capability.canRecover||!canReview||busy}
            onClick={()=>setSelected({id:item.id,decision:item.state,title:item.title,recovery:true})}>
            بازیابی دستی تصمیم ناتمام
          </button>
        </div>
      </article>)}
    </>}
    {selected&&enabled&&<div className="taraz-settings-review" role="group"
      aria-label="تأیید تصمیم ارجاع">
      <strong>{selected.recovery?'تأیید بازیابی تصمیم پایدار':'تأیید دستی '+(selected.decision==='reviewed'?'بررسی':'رد')+' ارجاع'}</strong>
      <p>{selected.title}؛ این عملیات تنها وضعیت ارجاع را تغییر می‌دهد و سند حسابداری نمی‌سازد.</p>
      <div><button type="button" disabled={busy} className="taraz-settings-action"
        onClick={()=>void decide()}>{busy?'در حال ثبت تصمیم...':'تأیید تصمیم'}</button>
        <button type="button" disabled={busy} onClick={()=>setSelected(null)}>انصراف</button></div>
    </div>}
    <p className="taraz-settings-privacy"><ShieldCheck size={17} aria-hidden="true"/>
      اتصال هیچ انتقال خودکار داده، صدور فاکتور یا ثبت دریافت/پرداخت ندارد.</p>
  </Section>;
}

export default function TarazSettings({api,currentUser=null,canAdmin=false,canManage=false,
  canDraft=canManage,onDraftFromMadar=null,onManageUsers=null}){
  const [page,setPage]=useState('general');
  const [prefs,setPrefs]=useState(()=>readTarazSettings());
  const localOnly=currentUser?.username==='local';
  useEffect(()=>{
    // Main shell also applies preferences at startup, including when Settings is never opened.
    applyTarazSettings(prefs);
    if(prefs.theme!=='system'||typeof globalThis.matchMedia!=='function')return;
    const media=globalThis.matchMedia('(prefers-color-scheme: dark)');
    const change=()=>applyTarazSettings(prefs);
    media.addEventListener?.('change',change);
    return()=>media.removeEventListener?.('change',change);
  },[prefs]);
  useEffect(()=>{
    const sync=event=>setPrefs(readTarazSettings());
    globalThis.addEventListener?.('taraz-settings-change',sync);
    return()=>globalThis.removeEventListener?.('taraz-settings-change',sync);
  },[]);
  const update=(key,value)=>{
    const next={...prefs,[key]:value};
    setPrefs(next);
    saveTarazSettings(next);
  };
  return <div className="taraz-settings" aria-label="تنظیمات برنامه تراز">
    <header className="taraz-settings-heading"><span>تنظیمات برنامه</span>
      <h2>تنظیمات</h2><p>ظاهر و ترجیحات محیط کار، حساب کاربری و ارتباط اختیاری با مدار.</p></header>
    <div className="taraz-settings-layout">
      <nav className="taraz-settings-tabs" aria-label="بخش‌های تنظیمات">
        {PAGES.map(([id,title,Icon])=><button type="button" key={id}
          aria-current={page===id?'page':undefined} className={page===id?'active':''}
          onClick={()=>setPage(id)}><Icon size={17}/><span>{title}</span><ChevronLeft size={14}/></button>)}
      </nav>
      <div className="taraz-settings-content">
        {page==='general'&&<>
          <Section eyebrow="Appearance" title="ظاهر برنامه"
            description="تغییرات بلافاصله روی رابط اعمال می‌شوند و در اجرای بعدی باقی می‌مانند.">
            <Row title="تم برنامه" description="طبق تنظیم سیستم، روشن یا تیره">
              <Choice label="تم برنامه" options={OPTIONS.theme} value={prefs.theme}
                onChange={choice=>update('theme',choice)}/></Row>
            <Row title="نوع قلم" description="فونت خوانای متن و جدول‌های مالی">
              <Choice label="نوع قلم" options={OPTIONS.font} value={prefs.font}
                onChange={choice=>update('font',choice)}/></Row>
            <Row title="اندازه رابط" description="مقیاس متن‌ها، فرم‌ها و فاصله‌ها">
              <Choice label="اندازه رابط" options={OPTIONS.size} value={prefs.size}
                onChange={choice=>update('size',choice)}/></Row>
            <Row title="عرض محتوا" description="فضای متمرکز، استاندارد یا تمام عرض">
              <Choice label="عرض محتوا" options={OPTIONS.width} value={prefs.width}
                onChange={choice=>update('width',choice)}/></Row>
            <Row title="حرکت و انتقال" description="کاهش انیمیشن یا پیروی از ترجیح سیستم">
              <Choice label="حرکت و انتقال" options={OPTIONS.motion} value={prefs.motion}
                onChange={choice=>update('motion',choice)}/></Row>
          </Section>
          <Section eyebrow="About" title="دربارهٔ تراز">
            <Row title="تراز، حسابداری مستقل" description="مسیر انتشار و بروزرسانی تراز از مدار جداست.">
              <span className="taraz-settings-status muted">بروزرسانی خودکار هنوز در دسترس نیست</span>
            </Row>
          </Section>
        </>}
        {page==='account'&&<Section eyebrow="Identity" title="حساب کاربری"
          description="این صفحه وضعیت نشست میزبان را نشان می‌دهد؛ ساخت حساب آنلاین هنوز راه‌اندازی نشده است.">
          <Row title="حالت کاربری فعلی" description="نمایش وضعیت گزارش‌شده از میزبان، بدون ساخت حساب جدید">
            <strong className="taraz-settings-identity">
              {localOnly?'حالت محلی تک‌کاربره؛ حساب ثبت‌نام‌شده نیست':
                typeof currentUser?.username==='string'&&currentUser.username?
                currentUser.username:'وضعیت احراز هویت نامشخص'}
            </strong>
          </Row>
          <Row title="ثبت کاربر جدید" description="کاربر جدید فقط از مسیر مدیریت کاربران بومی و توسط مدیر ایجاد می‌شود.">
            {!localOnly&&canAdmin&&typeof onManageUsers==='function'?
              <button type="button" className="taraz-settings-action"
                onClick={()=>void onManageUsers()}><Users size={16}/> مدیریت کاربران و ثبت کاربر جدید</button>:
              <span className="taraz-settings-status muted">در حالت محلی تراز، مدیریت کاربران فعال نیست</span>}
          </Row>
          <Row title="ثبت‌نام آنلاین" description="حساب آنلاین و سرویس ثبت‌نام در این نسخه راه‌اندازی نشده است.">
            <span className="taraz-settings-status muted">در دسترس نیست</span>
          </Row>
        </Section>}
        {page==='integration'&&<IntegrationSettings api={api}
          canReview={canManage||canAdmin} canDraft={canDraft||canManage}
          onDraftFromMadar={onDraftFromMadar}/>}
        {page==='subscription'&&<Section eyebrow="Plans & billing"
          title="اشتراک و خرید" description="اطلاعات خرید فقط پس از اتصال به سرویس واقعی نمایش داده می‌شود.">
          <Row title="وضعیت اشتراک" description="در این نسخه سرویس استعلام اشتراک ارائه نشده است.">
            <span className="taraz-settings-status muted">نامشخص؛ سرویس اشتراک متصل نیست</span>
          </Row>
          <Row title="طرح‌ها و قیمت‌ها" description="هیچ تعرفه یا محصول قابل فروش از میزبان دریافت نشده است.">
            <span className="taraz-settings-status muted">قیمتی برای نمایش موجود نیست</span>
          </Row>
          <Row title="خرید یا تمدید" description="امکان پرداخت و ثبت سفارش تا اتصال درگاه رسمی غیرفعال است.">
            <button type="button" disabled aria-disabled="true">خرید اشتراک (غیرفعال)</button>
          </Row>
          <p className="taraz-settings-privacy"><CircleHelp size={16}/>
            نمایش این صفحه به معنی فعال‌بودن پرداخت، خرید یا داشتن اشتراک نیست.</p>
        </Section>}
      </div>
    </div>
  </div>;
}
