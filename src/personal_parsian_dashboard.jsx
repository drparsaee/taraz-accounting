import React, {useEffect,useMemo,useState} from 'react';
import {personalLedgerSnapshot} from './personal_parsian_dashboard_data.js';
import {personalFiscalPosition} from './personal_parsian_fiscal_data.mjs';
import './personal_parsian_dashboard.css';

const fmt=(value)=>{
  if(!Number.isSafeInteger(value))return 'نامشخص';
  return value.toLocaleString('fa-IR');
};
export default function PersonalParsianDashboard({api,view,enabled=true,compact=false,onNavigate,fiscalYear='1405',onFiscalYearChange}){
  const [loaded,setLoaded]=useState(null);
  const [history,setHistory]=useState(null);
  const [error,setError]=useState('');
  const [pending,setPending]=useState(false);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    if(!enabled)return;
    let active=true;
    setError('');setPending(true);
    const requests=[
      view?Promise.resolve({view}):
        typeof api?.standaloneAccountingRead==='function'?Promise.resolve().then(()=>api.standaloneAccountingRead()):Promise.reject(new Error('اتصال خواندن دفتر کل موجود نیست')),
      typeof api?.standaloneAccountingParsianHistory==='function'?Promise.resolve().then(()=>api.standaloneAccountingParsianHistory()):Promise.resolve(null),
    ];
    Promise.allSettled(requests).then(([ledger,historic])=>{
      if(!active)return;
      if(ledger.status==='fulfilled')setLoaded(ledger.value?.view||null);
      else setError(String(ledger.reason?.message||ledger.reason||'داده دفتر کل در دسترس نیست'));
      if(historic.status==='fulfilled')setHistory(historic.value);
      else {setHistory(null);setError(String(historic.reason?.message||historic.reason||'Source archive unavailable'));}
    }).finally(()=>{if(active)setPending(false)});
    return ()=>{active=false};
  },[api,view,enabled,attempt]);
  const model=useMemo(()=>personalLedgerSnapshot(view||loaded,history),[view,loaded,history]);
  const fiscal=useMemo(()=>personalFiscalPosition(view||loaded,history,fiscalYear),[view,loaded,history,fiscalYear]);
  if(!enabled)return null;
  if(!model||!fiscal){
    if(pending)return <div className="ppd-skeleton" role="status">در حال خواندن دفتر کل شخصی...</div>;
    if(!error)return null;
    return <div className="ppd-error" role="alert">داده‌های تاریخی حسابداری قابل خواندن نیستند: {error}
      <button type="button" onClick={()=>setAttempt(v=>v+1)}>تلاش مجدد</button>
    </div>;
  }
  const stats=[
    {title:'مطالبات اشخاص (مانده بدهکار)',value:fiscal?.receivable,unit:'ریال',
      meta:fiscalYear==='1405'?'از حساب تفصیلی به‌روز تراز':'مانده در بکاپ سال ۱۴۰۴'},
    {title:'بدهی به اشخاص (مانده بستانکار)',value:fiscal?.payable,unit:'ریال',
      meta:'از مانده واقعی طرف‌حساب، نه فاکتورهای جدید'},
    {title:'خالص حساب اشخاص',value:fiscal?.net,unit:'ریال',
      meta:'مطالبات منهای بدهی در همین سال مالی'},
    {title:'فاکتورها و عملیات آرشیوی',value:fiscal?.invoiceCount,unit:'مورد',
      meta:'بدون ثبت سند مالی دوباره'},
  ];
  return <section className={'ppd-root'+(compact?' ppd-compact':'')} aria-label="وضعیت حسابداری شخصی منتقل‌شده از پارسیان">
    <div className="ppd-head">
      <div><span className="ppd-eyebrow">TARAZ / PARSIAN GL {fiscalYear}</span>
        <h2>خلاصه حسابداری شخصی</h2>
        <p>{fiscalYear==='1405'?'مانده‌های تاریخی به‌روز شده با ثبت‌های جدید تراز':'مانده‌های ثبت‌شده در بکاپ مستقل سال ۱۴۰۴'}؛ جدا از فاکتورهای جدید</p></div>
      <div className="ppd-year-control">
        <label htmlFor="parsian-fiscal-year">سال مالی</label>
        <select id="parsian-fiscal-year" aria-label="سال مالی داده‌های پارسیان" value={fiscalYear}
          onChange={e=>onFiscalYearChange?.(e.target.value)}>
          <option value="1405">۱۴۰۵</option><option value="1404">۱۴۰۴</option>
        </select>
      </div>
    </div>
    <div className="ppd-numbers">
      <span><strong>{fmt(fiscalYear==='1404'?model.year1404:model.year1405)}</strong> سند اصلی این سال</span>
      <span><strong>{fmt(fiscal?.invoiceCount)}</strong> فاکتور آرشیوی</span>
      <span><strong>{fmt(fiscal?.parties)}</strong> طرف‌حساب</span>
      <span><strong>{fmt(fiscal?.debtors)}</strong> بدهکار · <strong>{fmt(fiscal?.creditors)}</strong> بستانکار</span>
    </div>
    <div className="ppd-grid">
      {stats.map(x=><article className="ppd-card" key={x.title}>
        <span className="ppd-label">{x.title}</span>
        <strong className="ppd-value" dir="ltr">{x.value==null?'نامشخص':fmt(x.value)}</strong>
        <small className="ppd-unit">{x.unit}</small>
        <small className="ppd-hint">{x.meta}</small>
      </article>)}
    </div>
    {!compact&&fiscalYear==='1405'&&<div className="ppd-subledger">
      <div className="ppd-subhead"><strong>حساب‌های بانکی تاریخی</strong><span>بزرگ‌ترین مانده‌ها در آخرین بکاپ ۱۴۰۵</span></div>
      <div className="ppd-bankgrid">{model.bankAccounts.slice(0,5).map(a=><div key={a.id} className="ppd-bank">
        <span>{a.name}</span><strong dir="ltr">{fmt(a.balance)} <small>ریال</small></strong>
      </div>)}</div>
    </div>}
    {!compact&&fiscalYear==='1404'&&<div className="ppd-subledger">
      <p>گردش سال ۱۴۰۴ از سندهای منبع: صندوق {fmt((fiscal?.bankFlows.cash.debit||0)-(fiscal?.bankFlows.cash.credit||0))} ریال؛ بانک {fmt((fiscal?.bankFlows.bank.debit||0)-(fiscal?.bankFlows.bank.credit||0))} ریال. این‌ها خالص گردش ثبت‌شده‌اند، نه موجودی تأییدشده بانک.</p>
    </div>}
    <div className="ppd-footer">
      <p>سال مالی {fiscalYear}: این مبالغ مانده تفصیلی منبع هستند؛ در ۱۴۰۵ تغییرات دفتر کل تراز نیز در آن‌ها منظور شده است. مانده طرف‌حساب وضعیت تسویه تک‌تک فاکتورها نیست و نباید با اسناد جدید دوباره جمع شود.</p>
      {onNavigate&&<button type="button" onClick={onNavigate}>{compact?'ورود به حسابداری':'مشاهده حساب‌ها و دفتر کل'}</button>}
    </div>
  </section>;
}
