import React,{useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ArrowUpLeft,ArrowDownLeft,BookOpen,CalendarDays,
  FilePlus2,Files,Landmark,ReceiptText,Search,Users,Wallet,Clock3,
  ShieldCheck,RefreshCw,Layers3} from 'lucide-react';
import {personalFiscalPosition} from './personal_parsian_fiscal_data.mjs';
import {personalLedgerSnapshot} from './personal_parsian_dashboard_data.js';
import {summarizeFinancialExposure} from './taraz_financial_insights.js';
import './taraz_home_command.css';

// Source-only financial intelligence. Never guess a settled invoice from a GL balance.
const L={
  eyebrow:'مرکز مدیریت مالی',
  title:'امروز در تراز',
  subtitle:'وضعیت مالی، اسناد و اشخاص در یک نگاه. مانده‌ها مستقیماً از دفترکل خوانده می‌شوند.',
  year:'سال مالی',
  source:'منبع: آرشیو پارسیان و دفترکل تراز',
  refresh:'بارخوانی داده',
  create:'فاکتور جدید',
  receive:'ثبت دریافت',
  pay:'دریافت و پرداخت',
  reports:'گزارش‌ها',
  receivable:'مطالبات از اشخاص',
  payable:'بدهی به اشخاص',
  net:'خالص حساب اشخاص',
  invoice:'فاکتورهای آرشیوی',
  positive:'بدهکار',
  negative:'بستانکار',
  sourceCurrent:'مانده ۱۴۰۵ شامل ثبت‌های جدید تراز',
  sourceArchive:'مانده ثابت از بکاپ پارسیان ۱۴۰۴',
  notAvailable:'نامشخص',
  missing:'اطلاعات معتبر برای این بازه موجود نیست.',
  peopleHeading:'اشخاص و مانده‌ها',
  peopleSubtitle:'مانده حساب تفصیلی، نه وضعیت تسویه فاکتور',
  allPeople:'فهرست اشخاص',
  topDebtors:'بدهکاران اصلی',
  topCreditors:'بستانکاران اصلی',
  noDebtors:'بدهکاری در این سال ثبت نشده است.',
  noCreditors:'بستانکاری در این سال ثبت نشده است.',
  activityHeading:'دسترسی سریع',
  activitySubtitle:'مسیرهای پرکاربرد در دفتر حسابداری',
  invoices:'فاکتورهای فروش',
  purchases:'خرید و هزینه',
  settlements:'دریافت و پرداخت',
  cash:'صندوق و بانک',
  cheques:'چک و سررسید',
  documents:'دفتر روزنامه',
  bankHeading:'خلاصه حساب‌های بانکی',
  bankSubtitle:'مانده حساب‌های تاریخی در آخرین سال مالی',
  bankNote:'این اعداد موجودی قابل برداشت یا تطبیق بانک را اثبات نمی‌کنند.',
  noBank:'مانده بانک معتبر در دفتر فعلی یافت نشد.',
  audit:'اطلاعات سنددار',
  sourceNote:'مانده اشخاص با جمع مطالبات و بدهی‌ها محاسبه شده است. تسویه هر فاکتور آرشیوی باید جداگانه احراز شود.',
  matched:'فاکتور تطبیق‌خورده',
  inventory:'فاکتور فقط انباری',
  unknown:'در حال خواندن منبع مالی...',
  archive:'آرشیو',
  viewAll:'مشاهده جزئیات',
  noSummary:'دفتر آماده است؛ اما مبنای معتبر برای نمایش وضعیت تاریخی این سال پیدا نشد.',
  error:'دریافت سوابق تاریخی ناموفق بود.',
  retry:'تلاش دوباره',
  rial:'ریال',
  persons:'نفر',
  count:'عدد',
};
const format=value=>Number.isSafeInteger(value)?
  value.toLocaleString('fa-IR'):L.notAvailable;
const unit=value=>Number.isSafeInteger(value)?format(value)+' '+L.rial:L.notAvailable;
const safePeople=(model,kind)=>!model?[]:model.people.filter(p=>
  Number.isSafeInteger(p[kind])&&p[kind]>0).sort((a,b)=>b[kind]-a[kind]).slice(0,5);
const SECTIONS=[
  {id:'invoice',title:L.invoices,icon:ReceiptText},
  {id:'bill',title:L.purchases,icon:Files},
  {id:'settlements',title:L.settlements,icon:Wallet},
  {id:'cash',title:L.cash,icon:Landmark},
  {id:'cheques',title:L.cheques,icon:CalendarDays},
  {id:'journal',title:L.documents,icon:BookOpen},
];
export default function TarazHomeCommand({
  api,view,fiscalYear='1405',referenceDate='',onFiscalYearChange=()=>{},
  onNavigate=()=>{},onNewInvoice=()=>{},canDraft=false,canManage=false,
  disabled=false,
}){
  const [history,setHistory]=useState(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [retry,setRetry]=useState(0);
  // A fresh Windows-bound book is attested by the native session, not by a
  // guessed ledger revision or a user-editable company display name.
  const fresh=view?.freshWindowsWorkspace===true;
  const freshZero=fresh&&Array.isArray(view?.journals)&&view.journals.length===0&&
    Object.keys(view?.invoices||{}).length===0&&
    Object.keys(view?.bills||{}).length===0;
  useEffect(()=>{
    if(fresh){
      // The legacy API MUST reject a new book. Don't call it, then show that
      // correct security denial as an alarming, irrelevant financial error.
      setHistory(null);setError('');setLoading(false);
      return;
    }
    let alive=true;
    setLoading(true);setError('');
    Promise.resolve().then(()=>api?.standaloneAccountingParsianHistory?.()).then(data=>{
      if(!alive)return;
      setHistory(data||null);
    }).catch(err=>{
      if(!alive)return;
      setHistory(null);setError(err?.message||L.error);
    }).finally(()=>{if(alive)setLoading(false);});
    return ()=>{alive=false};
  },[api,retry,fresh]);
  const fiscal=useMemo(()=>freshZero?{
    year:fiscalYear,currency:'RIAL',receivable:0,payable:0,net:0,
    invoiceCount:0,debtors:0,creditors:0,people:[],
  }:personalFiscalPosition(view,history,fiscalYear),
    [view,history,fiscalYear,freshZero]);
  const ledger=useMemo(()=>personalLedgerSnapshot(view,history),[view,history]);
  const exposure=useMemo(()=>{
    if(!view||!/^\d{4}-\d{2}-\d{2}$/.test(referenceDate))return null;
    try{return summarizeFinancialExposure(view,{referenceDate});}
    catch{return null;}
  },[view,referenceDate]);
  const stats=[
    {key:'receivable',label:L.receivable,value:fiscal?.receivable,icon:ArrowDownLeft,tone:'blue',tab:'parties'},
    {key:'payable',label:L.payable,value:fiscal?.payable,icon:ArrowUpLeft,tone:'rose',tab:'parties'},
    {key:'net',label:L.net,value:fiscal?.net,icon:Wallet,tone:'slate',tab:'accounts'},
    {key:'invoice',label:fresh?'فاکتورهای دفتر تازه':L.invoice,value:fiscal?.invoiceCount,icon:Files,tone:'mint',tab:'invoice',isCount:true},
  ];
  const peopleGroup=(label,kind,none)=>{
    const people=safePeople(fiscal,kind);
    return <div className="tdh-party-group" data-group={kind}>
      <div className="tdh-party-heading"><strong>{label}</strong>
        <small>{kind==='receivable'?format(fiscal?.debtors):format(fiscal?.creditors)} {L.persons}</small></div>
      {people.length?<div className="tdh-people-list">
        {people.map((person,i)=><button type="button" key={person.id}
          onClick={()=>onNavigate('parties')} title={L.allPeople}
          className="tdh-person-row" disabled={disabled}>
          <span className="tdh-person-rank">{String(i+1).padStart(2,'0')}</span>
          <span className="tdh-person-name">{person.name||person.code||L.notAvailable}
            <small>{person.code||''}</small></span>
          <span className={'tdh-person-amount '+(kind==='payable'?'credit':'debit')}
            dir="ltr">{unit(person[kind])}</span>
          <ArrowLeft size={15} aria-hidden="true"/>
        </button>)}
      </div>:<p className="tdh-empty">{fiscal?none:L.missing}</p>}
    </div>;
  };
  return <section className="tdh-root" dir="rtl" aria-label={L.eyebrow}>
    <header className="tdh-hero">
      <div className="tdh-hero-title">
        <div className="tdh-hero-mark"><span className="tdh-mark-dot"/>{L.eyebrow}
          <span className="tdh-source-dot">●</span></div>
        <h1>{L.title}</h1><p>{fresh?'وضعیت دفتر جدید و اسناد همین شرکت، بدون ورود اطلاعات حسابداری قدیمی.':L.subtitle}</p>
      </div>
      <div className="tdh-hero-actions">
        <label className="tdh-year-select"><CalendarDays size={17}/>
          <span>{L.year}</span>
          <select id="taraz-home-fiscal-year" value={fiscalYear}
            onChange={event=>onFiscalYearChange(event.target.value)}>
            <option value="1405">۱۴۰۵</option><option value="1404">۱۴۰۴</option>
          </select>
        </label>
        <button type="button" className="tdh-main-cta"
          onClick={onNewInvoice} disabled={!canDraft||disabled}>
          <FilePlus2 size={17}/>{L.create}</button>
      </div>
    </header>
    {error&&<p className="tdh-warning" role="alert">{L.error} {error}
      <button type="button" onClick={()=>setRetry(x=>x+1)}>{L.retry}</button></p>}
    <div className="tdh-source-strip">
      <span><ShieldCheck size={16}/>{fresh?'دفتر تازه با هویت ویندوز، بدون دادهٔ منتقل‌شده':fiscalYear==='1405'?L.sourceCurrent:L.sourceArchive}</span>
      <span><Clock3 size={16}/>{fresh?'منبع: دفتر مستقل جدید تراز':L.source}</span>
      {loading&&<span role="status">{L.unknown}</span>}
    </div>
    <div className="tdh-stat-grid">
      {stats.map((item,i)=>{
        const Icon=item.icon;
        return <button key={item.key} type="button" disabled={disabled}
          className={'tdh-stat tdh-stat-'+item.tone}
          onClick={()=>onNavigate(item.tab)} aria-label={item.label}>
          <span className="tdh-stat-head">
            <span className="tdh-stat-label">{item.label}</span>
            <span className="tdh-stat-icon"><Icon size={19}/></span>
          </span>
          <strong className="tdh-stat-number" dir="ltr">{format(item.value)}</strong>
          <span className="tdh-stat-foot">{item.isCount?L.count:L.rial}<ArrowLeft size={15}/></span>
        </button>;
      })}
    </div>
    <div className="tdh-content-grid">
      <section className="tdh-sheet tdh-people" aria-label={L.peopleHeading}>
        <div className="tdh-sheet-head">
          <div><span className="tdh-section-flag"><Users size={15}/>{L.audit}</span>
            <h3>{L.peopleHeading}</h3><p>{L.peopleSubtitle}</p></div>
          <button className="tdh-text-button" type="button"
            onClick={()=>onNavigate('parties')}>{L.allPeople}<ArrowLeft size={16}/></button>
        </div>
        <div className="tdh-people-columns">
          {peopleGroup(L.topDebtors,'receivable',L.noDebtors)}
          {peopleGroup(L.topCreditors,'payable',L.noCreditors)}
        </div>
        <p className="tdh-note"><ShieldCheck size={16}/>{fresh?'نمایش مبالغ فقط بر پایه داده‌های دفتر فعلی انجام می‌شود؛ سوابق قدیمی وارد نشده‌اند.':L.sourceNote}</p>
      </section>
      <aside className="tdh-side">
        <section className="tdh-sheet tdh-actions" aria-label={L.activityHeading}>
          <div className="tdh-sheet-head">
            <div><span className="tdh-section-flag"><Layers3 size={15}/>{L.activitySubtitle}</span>
              <h3>{L.activityHeading}</h3></div>
          </div>
          <div className="tdh-action-grid">
            {SECTIONS.map(item=>{
              const Icon=item.icon;
              return <button type="button" key={item.id} disabled={disabled}
                onClick={()=>onNavigate(item.id)}>
                <span className="tdh-action-icon"><Icon size={18}/></span>
                <span>{item.title}</span><ArrowLeft size={15}/>
              </button>;
            })}
          </div>
        </section>
        <section className="tdh-sheet tdh-banks" aria-label={L.bankHeading}>
          <div className="tdh-sheet-head"><div><span className="tdh-section-flag"><Landmark size={15}/>{L.bankSubtitle}</span>
            <h3>{L.bankHeading}</h3></div>
            <button className="tdh-text-button" type="button" onClick={()=>onNavigate('cash')}>
              {L.viewAll}<ArrowLeft size={16}/></button></div>
          {fiscalYear==='1405'&&ledger?.bankAccounts?.length?
            <div className="tdh-bank-list">{ledger.bankAccounts.slice(0,3).map(account=>
              <div key={account.id} className="tdh-bank-row">
                <span>{account.name||account.id}</span><strong dir="ltr">{unit(account.balance)}</strong>
              </div>)}</div>:<p className="tdh-empty">{L.noBank}</p>}
          <p className="tdh-bank-note">{L.bankNote}</p>
        </section>
        <section className="tdh-sheet tdh-exposure" aria-label="سررسید اسناد عملیاتی">
          <div className="tdh-sheet-head"><div>
            <span className="tdh-section-flag"><Clock3 size={15}/>اسناد بومی تراز</span>
            <h3>سررسید و تعهدات</h3>
            <p>فقط فاکتورهای صادرشده با مانده باز، جدا از آرشیو پارسیان</p>
          </div>
          <button className="tdh-text-button" type="button" onClick={()=>onNavigate('reports')}>
            گزارش کامل<ArrowLeft size={16}/></button></div>
          {exposure?<div className="tdh-exposure-grid">
            <button type="button" onClick={()=>onNavigate('settlements')}>
              <span>دریافتنی باز</span><strong>{format(exposure.receivables.outstanding)}</strong>
              <small>{exposure.currency==='TOMAN'?'تومان':'ریال'} · {format(exposure.receivables.documentCount)} سند</small>
            </button>
            <button type="button" onClick={()=>onNavigate('settlements')}>
              <span>پرداختنی باز</span><strong>{format(exposure.payables.outstanding)}</strong>
              <small>{exposure.currency==='TOMAN'?'تومان':'ریال'} · {format(exposure.payables.documentCount)} سند</small>
            </button>
            <button type="button" onClick={()=>onNavigate('cheques')}>
              <span>چک‌های تسویه‌نشده</span>
              <strong>{format(exposure.chequeCommitments.receivableCount+exposure.chequeCommitments.payableCount)}</strong>
              <small>تعهد احتمالی، نه موجودی نقد</small>
            </button>
          </div>:<p className="tdh-empty" role="status">
            گزارش قابل تطبیق اسناد عملیاتی موجود نیست؛ مبلغ یا سررسید حدس زده نمی‌شود.
          </p>}
          <p className="tdh-bank-note">چک تا ثبت وصول یا پرداخت، به‌خودی‌خود تسویه محسوب نمی‌شود. تاریخ مرجع صرفاً برای گروه‌بندی سررسید است.</p>
        </section>
      </aside>
    </div>
    {fiscal?<div className="tdh-footnote">
      <span><ShieldCheck size={15}/>{L.audit}</span>
      <span>{format(fiscal.matchedInvoices)} {L.matched}</span>
      <span>{format(fiscal.inventoryOnlyInvoices)} {L.inventory}</span>
      <span>{L.source}</span>
    </div>:<p role="status" className="tdh-footnote">{loading?L.unknown:L.noSummary}</p>}
  </section>;
}
