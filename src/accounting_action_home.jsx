/**
 * UX-03/04: Read-only, source-backed action layer for accounting_view().
 *
 * Integration:
 *   <AccountingActionHome view={view} today={accountingCompanyToday(view)}
 *     canDraft={canManage||canDraft} canSettle={canManage}
 *     disabled={busy||pendingRetry} preferenceKey={currentUser?.username||''}
 *     onNavigate={gotoTab} onNewInvoice={openQuickInvoice}/>
 *
 * onNavigate accepts one existing tab ID: invoice, bill, settlements, cash,
 * reports. onNewInvoice is the host's existing draft composer callback. Neither
 * this component nor its preferences send any accounting commands.
 */
import React,{useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ArrowUpLeft,FilePlus2,FileText,Landmark,
  Wallet,ShieldAlert,ChartNoAxesCombined,SlidersHorizontal} from 'lucide-react';
import './accounting_action_home.css';
import {personalFiscalPosition} from './personal_parsian_fiscal_data.mjs';

const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const money=value=>Number.isSafeInteger(value)&&value>=0?BigInt(value):null;
const date=value=>{
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
  const d=new Date(value+'T00:00:00Z');
  return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value?value:null;
};
const values=value=>record(value)?Object.values(value):null;
const integer=value=>Number.isSafeInteger(value)&&value>=0;
const UNIT={RIAL:'ریال',TOMAN:'تومان'};
const fmtNumber=value=>value===null?'نامشخص':value.toLocaleString('fa-IR');
const fmtMoney=(value,currency)=>value===null?'نیازمند بررسی':
  `${value.toLocaleString('fa-IR')} ${UNIT[currency]||'واحد نامشخص'}`;

function openDocuments(records,today){
  if(records===null)return {amount:null,count:null,overdueAmount:null,
    overdueCount:null,undatedCount:null,invalid:true};
  let amount=0n,count=0,overdueAmount=0n,overdueCount=0,undatedCount=0,invalid=false;
  for(const item of records){
    if(!record(item)||item.status!=='issued')continue;
    const total=money(item.total),allocated=money(item.allocated),
      returned=money(item.returnedAmount??0);
    if(total===null||allocated===null||returned===null||allocated+returned>total){
      invalid=true;continue;
    }
    const due=item.dueDate;
    const dueDay=due===null||due===undefined||due===''?null:date(due);
    if(due!==null&&due!==undefined&&due!==''&&!dueDay){invalid=true;continue;}
    const outstanding=total-allocated-returned;
    if(outstanding===0n)continue;
    amount+=outstanding;count++;
    if(dueDay&&dueDay<today){overdueCount++;overdueAmount+=outstanding;}
    if(!dueDay)undatedCount++;
  }
  return {amount:invalid?null:amount,count:invalid?null:count,
    overdueAmount:invalid?null:overdueAmount,overdueCount:invalid?null:overdueCount,
    undatedCount:invalid?null:undatedCount,invalid};
}

function approvals(view){
  const sales=values(view?.invoices),purchases=values(view?.bills);
  if(sales===null||purchases===null)return null;
  const all=[...sales,...purchases];
  if(all.some(item=>!record(item)||typeof item.status!=='string'))return null;
  return {draft:all.filter(item=>item.status==='draft').length,
    approved:all.filter(item=>item.status==='approved').length};
}

function reconciliation(view){
  const bank=values(view?.bankStatements);
  if(bank===null)return null;
  if(bank.some(row=>!record(row)||(!('journalId' in row))))return null;
  return {unmatched:bank.filter(row=>!row.journalId).length,
    registered:bank.length};
}

function pendingCostOfGoods(view){
  // Counts only missing movement quantities on current issued invoices; never
  // guesses a monetary cost. Incomplete stock projections are indeterminate.
  // Prefer the host's verified all-period report whenever provided.
  const verified=view?.financialReports;
  if(record(verified)&&typeof verified.profitLossComplete==='boolean'&&
      Array.isArray(verified.unpostedGoodsIssues)){
    const pending=verified.unpostedGoodsIssues;
    if(pending.some(row=>!record(row)||typeof row.invoiceId!=='string'||
      typeof row.itemId!=='string'||!integer(row.missingQuantity)))return null;
    if(verified.profitLossComplete!==(pending.length===0))return null;
    return {count:pending.length,pending:pending.map(row=>({
      invoiceId:row.invoiceId,itemId:row.itemId,
      missingQuantity:BigInt(row.missingQuantity)}))};
  }
  const invoices=values(view?.invoices),items=view?.items,
    movements=values(view?.stockMovements),returns=values(view?.returns);
  if(invoices===null||!record(items)||movements===null||returns===null)return null;
  const returned=new Map(),issued=new Map();
  const key=(invoiceId,itemId)=>invoiceId+'\u0000'+itemId;
  for(const note of returns){
    if(!record(note))return null;
    if(note.direction!=='sale'||note.kind!=='partial')continue;
    if(typeof note.documentId!=='string'||!Array.isArray(note.lines))return null;
    for(const line of note.lines){
      if(!record(line)||!integer(line.lineIndex)||!integer(line.quantity))return null;
      const entry=note.documentId+'\u0000'+line.lineIndex;
      returned.set(entry,(returned.get(entry)||0n)+BigInt(line.quantity));
    }
  }
  const reversed=new Set(movements.filter(item=>record(item)&&item.type==='inventory.reverse')
    .map(item=>item.sourceMovementId));
  for(const movement of movements){
    if(!record(movement))return null;
    if(movement.type!=='inventory.issue'||movement.reversed===true||reversed.has(movement.id))continue;
    if(typeof movement.invoiceId!=='string'||typeof movement.itemId!=='string'||
      !integer(movement.quantity))return null;
    const k=key(movement.invoiceId,movement.itemId);
    issued.set(k,(issued.get(k)||0n)+BigInt(movement.quantity));
  }
  const pending=[];
  for(const invoice of invoices){
    if(!record(invoice))return null;
    if(invoice.status!=='issued')continue;
    if(typeof invoice.id!=='string'||!Array.isArray(invoice.lines))return null;
    const perItem=new Map();
    for(let index=0;index<invoice.lines.length;index++){
      const line=invoice.lines[index];
      if(!record(line))return null;
      if(!line.itemId||items[line.itemId]?.stockTracked!==true)continue;
      if(!integer(line.quantity))return null;
      const r=Array.isArray(invoice.returnedQuantities)?
        money(invoice.returnedQuantities[index]):
        (returned.get(invoice.id+'\u0000'+index)||0n);
      if(r===null||r>BigInt(line.quantity))return null;
      const k=key(invoice.id,line.itemId);
      perItem.set(k,(perItem.get(k)||0n)+BigInt(line.quantity)-r);
    }
    for(const [k,quantity] of perItem){
      const unissued=quantity-(issued.get(k)||0n);
      if(unissued<0n)return null;
      if(unissued>0n)pending.push({invoiceId:invoice.id,
        itemId:k.slice(invoice.id.length+1),missingQuantity:unissued});
    }
  }
  return {count:pending.length,pending};
}

function postedMonthTotal(view,today,kind){
  const current=date(today);
  if(!current)return null;
  const month=current.slice(0,7), list=values(view?.[kind]);
  if(list===null)return null;
  let total=0n;
  for(const entry of list){
    if(!record(entry)||entry.reversed===true)continue;
    if(!date(entry.date))return null;
    if(entry.date.slice(0,7)!==month||entry.date>current)continue;
    const value=money(entry.total);
    if(value===null)return null;
    total+=value;
  }
  return total;
}

function salesMonthTotal(view,today){
  const current=date(today),list=values(view?.invoices);
  if(!current||list===null)return null;
  let total=0n;
  for(const invoice of list){
    if(!record(invoice)||invoice.status!=='issued')continue;
    if(!date(invoice.postingDate))return null;
    if(invoice.postingDate.slice(0,7)!==current.slice(0,7)||
        invoice.postingDate>current)continue;
    const value=money(invoice.total),returned=money(invoice.returnedAmount??0);
    if(value===null||returned===null||returned>value)return null;
    total+=value-returned;
  }
  return total;
}

function ledgerMonthNet(view,today){
  const journals=view?.journals,accounts=view?.accounts,current=date(today);
  if(!Array.isArray(journals)||!record(accounts)||!current)return null;
  let revenue=0n,expense=0n;
  for(const journal of journals){
    if(!record(journal)||!date(journal.date)||!Array.isArray(journal.lines))return null;
    if(journal.sourceType==='fiscal.year.close'||
      journal.date.slice(0,7)!==current.slice(0,7)||journal.date>current)continue;
    for(const line of journal.lines){
      if(!record(line)||!record(accounts[line.accountId])||
        !integer(line.debit)||!integer(line.credit))return null;
      const kind=accounts[line.accountId].kind;
      if(kind==='revenue')revenue+=BigInt(line.credit)-BigInt(line.debit);
      if(kind==='expense')expense+=BigInt(line.debit)-BigInt(line.credit);
    }
  }
  return revenue-expense;
}

/** Exact integer ledger units, with null for unavailable or untrusted totals. */
export function buildAccountingActionSummary(view,today){
  const day=date(today);
  if(!record(view)||!day||!Object.hasOwn(UNIT,view.currency)){
    return {error:'تاریخ شرکت یا واحد پولی دفتر نامعتبر است.'};
  }
  const ar=openDocuments(values(view.invoices),day),ap=openDocuments(values(view.bills),day);
  return {error:'',currency:view.currency,asOf:day,ar,ap,
    approvals:approvals(view),bank:reconciliation(view),cogs:pendingCostOfGoods(view),
    cashReceivedMonth:postedMonthTotal(view,day,'receipts'),
    cashPaidMonth:postedMonthTotal(view,day,'payments'),
    salesMonth:salesMonthTotal(view,day),
    ledgerNetMonth:ledgerMonthNet(view,day)};
}

const CARD_LABELS=[['receivables','مطالبات فروش'],['payables','بدهی خرید'],
  ['overdue','سررسیدهای گذشته'],['approvals','اسناد در انتظار اقدام'],
  ['reconciliation','مغایرت بانکی'],['cogs','بهای تمام‌شده'],
  ['performance','نقد، فروش و عملکرد']];
const DEFAULT_CARDS=CARD_LABELS.map(([id])=>id);
export function readActionHomePreferences(storage,key){
  if(!storage||!key)return DEFAULT_CARDS;
  try{
    const saved=JSON.parse(storage.getItem('madar.accounting.home.v1.'+encodeURIComponent(key)));
    if(!Array.isArray(saved)||!saved.every(v=>typeof v==='string'))return DEFAULT_CARDS;
    return DEFAULT_CARDS.filter(id=>saved.includes(id));
  }catch{return DEFAULT_CARDS;}
}

function localPreferenceStorage(storage){
  if(storage!==undefined)return storage;
  try{return typeof window==='undefined'?null:window.localStorage;}
  catch{return null;}
}

export default function AccountingActionHome({view,today,canDraft=false,canSettle=false,
  disabled=false,preferenceKey='',onNavigate=()=>{},onNewInvoice=()=>{},storage,
  api=null,fiscalYear='1405'}){
  const summary=useMemo(()=>buildAccountingActionSummary(view,today),[view,today]);
  const [parsianHistory,setParsianHistory]=useState(null);
  const [parsianSourceError,setParsianSourceError]=useState('');
  useEffect(()=>{
    let active=true;
    if(typeof api?.standaloneAccountingParsianHistory!=='function')return;
    Promise.resolve().then(()=>api.standaloneAccountingParsianHistory())
      .then(data=>{if(active){setParsianHistory(data);setParsianSourceError('');}})
      .catch(error=>{if(active)setParsianSourceError(String(error?.message||error))});
    return()=>{active=false};
  },[api]);
  const historic=useMemo(()=>personalFiscalPosition(view,parsianHistory,fiscalYear),
    [view,parsianHistory,fiscalYear]);
  const [visible,setVisible]=useState(DEFAULT_CARDS);
  const persistent=localPreferenceStorage(storage);
  useEffect(()=>setVisible(readActionHomePreferences(persistent,preferenceKey)),
    [persistent,preferenceKey]);
  const choose=id=>{
    const next=visible.includes(id)?visible.filter(v=>v!==id):
      DEFAULT_CARDS.filter(v=>visible.includes(v)||v===id);
    setVisible(next);
    if(preferenceKey&&persistent){try{persistent.setItem('madar.accounting.home.v1.'+
      encodeURIComponent(preferenceKey),JSON.stringify(next));}catch{/* optional local layout */}}
  };
  const show=id=>visible.includes(id),unit=UNIT[summary.currency]||'';
  const nav=(tab)=>()=>onNavigate(tab);
  const actions=[
    {id:'sale',title:canDraft?'فاکتور فروش جدید':'فاکتورهای فروش',
      subtitle:canDraft?'شروع ثبت پیش‌نویس فروش':'مشاهده اسناد فروش',icon:FilePlus2,
      click:canDraft?onNewInvoice:nav('invoice'),mutation:canDraft},
    {id:'purchase',title:canDraft?'ثبت خرید':'صورتحساب‌های خرید',
      subtitle:canDraft?'ورود به ثبت صورتحساب':'مشاهده اسناد خرید',icon:FileText,
      click:nav('bill'),mutation:canDraft},
    {id:'receipt',title:canSettle?'ثبت دریافت':'پیگیری دریافت',
      subtitle:'فاکتورهای فروش و تسویه‌ها',icon:ArrowUpLeft,
      click:nav('settlements'),mutation:canSettle},
    {id:'payment',title:canSettle?'ثبت پرداخت':'پیگیری پرداخت',
      subtitle:'بدهی‌های خرید و تسویه‌ها',icon:Wallet,
      click:nav('settlements'),mutation:canSettle},
    {id:'reconcile',title:'مغایرت‌گیری',subtitle:'بررسی ردیف‌های ثبت‌شده بانک',
      icon:Landmark,click:nav('cash'),mutation:false},
    {id:'reports',title:'گزارش‌ها',subtitle:'دفترکل و گزارش مالی',
      icon:ChartNoAxesCombined,click:nav('reports'),mutation:false},
  ];
  if(summary.error)return <section className="sac-ah" role="status">{summary.error}</section>;
  const uncertain=summary.cogs===null||summary.cogs?.count>0;
  const visibleCount=show('overdue')&&summary.ar.overdueCount!==null&&
    summary.ap.overdueCount!==null?
    summary.ar.overdueCount+summary.ap.overdueCount:null;
  return <section className="sac-ah" aria-label="میز اقدامات حسابداری">
    <div className="sac-ah-title"><div><span className="sac-ah-kicker">ACTION DESK / MADAR</span>
      <h2>کارهای مالی امروز</h2><p>اقدام‌های مستقیم و وضعیت اسناد دفتر جاری تا <b dir="ltr">{summary.asOf}</b></p></div>
      <details className="sac-ah-customize"><summary><SlidersHorizontal size={17}/> تنظیم کارت‌ها</summary>
        <fieldset><legend>کارت‌های قابل نمایش برای این کاربر</legend>
          {CARD_LABELS.map(([id,label])=><label key={id}><input type="checkbox"
            checked={show(id)} onChange={()=>choose(id)}/>{label}</label>)}
        </fieldset></details></div>
    <nav className="sac-ah-actions" aria-label="اقدام‌های سریع حسابداری">
      {actions.map(({id,title,subtitle,icon:Icon,click,mutation})=><button
        key={id} type="button" onClick={click} disabled={disabled&&mutation}
        className={'sac-ah-action sac-ah-'+id}>
        <span className="sac-ah-action-icon"><Icon size={20} aria-hidden="true"/></span>
        <span><strong>{title}</strong><small>{subtitle}</small></span>
        <ArrowLeft className="sac-ah-arrow" size={18} aria-hidden="true"/>
      </button>)}
    </nav>
    {historic&&<section className="sac-ah-historical" aria-label="مطالبات و بدهی تاریخی پارسیان">
      <div className="sac-ah-history-heading">
        <div><h3>وضعیت مالی اشخاص در سال {fiscalYear}</h3>
          <p>{historic.balanceSource==='native-current'?
            'مانده تاریخی به‌روز شده با سندهای تازه دفتر کل تراز':
            'مانده مستقل منبع سال ۱۴۰۴'}؛ تسویه هر فاکتور هنوز قابل استنباط نیست.</p></div>
        <button type="button" onClick={nav('parties')}>ریزحساب اشخاص <ArrowLeft size={15}/></button>
      </div>
      <div className="sac-ah-history-grid">
        <article><span>مطالبات از اشخاص</span><strong dir="auto">{fmtMoney(BigInt(historic.receivable),'RIAL')}</strong>
          <small>{fmtNumber(historic.debtors)} شخص بدهکار</small></article>
        <article><span>بدهی به اشخاص</span><strong dir="auto">{fmtMoney(BigInt(historic.payable),'RIAL')}</strong>
          <small>{fmtNumber(historic.creditors)} شخص بستانکار</small></article>
        <article><span>خالص حساب اشخاص</span><strong dir="auto">{BigInt(historic.net).toLocaleString('fa-IR')} ریال</strong>
          <small>مطالبات منهای بدهی؛ بدون دوباره‌شماری</small></article>
        <article><span>فاکتورهای آرشیوی همان سال</span><strong>{fmtNumber(historic.invoiceCount)}</strong>
          <small>{fmtNumber(historic.matchedInvoices)} مورد با سند مالی تطبیق‌یافته</small></article>
      </div>
      <details className="sac-ah-debt-details"><summary>بزرگ‌ترین مانده‌های اشخاص همین سال</summary>
        <div className="sac-ah-debt-scroll"><table><thead><tr>
          <th>طرف‌حساب</th><th>مطالبات (ریال)</th><th>بدهی (ریال)</th>
        </tr></thead><tbody>{historic.people.filter(p=>p.signed!==0).slice(0,12).map(p=>
          <tr key={p.id}><td>{p.name}</td><td dir="ltr">{fmtNumber(p.receivable)}</td>
            <td dir="ltr">{fmtNumber(p.payable)}</td></tr>)}</tbody></table></div>
      </details>
      <p className="sac-ah-history-footnote">منبع: دفتر کل و آرشیو شخصی پارسیان. این اعداد به کارت‌های عملیاتی جدید پایین اضافه نشده‌اند.</p>
    </section>}
    {!historic&&parsianSourceError&&<p className="sac-ah-warning" role="alert">
      اطلاعات مالی پارسیان قابل خواندن نیست؛ صفر بودن کارت‌های پایین به معنی نبود بدهی تاریخی نیست.
    </p>}
    <div className="sac-ah-operational-label">شاخص‌های عملیاتی جدید تراز؛ تراز دفترکل ماه جاری ممکن است اسناد واردشده پارسیان را هم شامل شود</div>
    <div className="sac-ah-cards" aria-label="وضعیت کارهای ضروری">
      {show('receivables')&&<article className="sac-ah-card primary"><span>دریافتنی فاکتورهای جدید تراز (بدون آرشیو)</span>
        <strong dir="auto">{fmtMoney(summary.ar.amount,summary.currency)}</strong>
        <small>{fmtNumber(summary.ar.count)} سند صادرشده با مانده باز</small>
        <button type="button" onClick={nav('invoice')}>بررسی مطالبات <ArrowLeft size={15}/></button></article>}
      {show('payables')&&<article className="sac-ah-card primary"><span>پرداختنی خریدهای جدید تراز (بدون آرشیو)</span>
        <strong dir="auto">{fmtMoney(summary.ap.amount,summary.currency)}</strong>
        <small>{fmtNumber(summary.ap.count)} سند صادرشده با مانده باز</small>
        <button type="button" onClick={nav('bill')}>بررسی بدهی‌ها <ArrowLeft size={15}/></button></article>}
      {show('overdue')&&<article className="sac-ah-card"><span>اسناد جدید باز با تاریخ سررسید گذشته (بدون آرشیو)</span>
        <strong>{fmtNumber(visibleCount)} <small>سند</small></strong>
        <small>دریافتنی: {fmtNumber(summary.ar.overdueCount)} سند، {fmtMoney(summary.ar.overdueAmount,summary.currency)}</small>
        <small>پرداختنی: {fmtNumber(summary.ap.overdueCount)} سند، {fmtMoney(summary.ap.overdueAmount,summary.currency)}</small>
        <small>بدون تاریخ سررسید: دریافتنی {fmtNumber(summary.ar.undatedCount)}، پرداختنی {fmtNumber(summary.ap.undatedCount)}</small>
      </article>}
      {show('approvals')&&<article className="sac-ah-card"><span>اسناد فروش و خرید در انتظار اقدام</span>
        <strong>{fmtNumber(summary.approvals?.draft??null)} <small>پیش‌نویس</small></strong>
        <small>{fmtNumber(summary.approvals?.approved??null)} سند تأییدشده در انتظار صدور</small>
        <button type="button" onClick={nav('invoice')}>پیگیری فروش <ArrowLeft size={15}/></button></article>}
      {show('reconciliation')&&<article className="sac-ah-card"><span>صورت‌حساب بانکی ثبت‌شده و تطبیق‌نشده</span>
        <strong>{fmtNumber(summary.bank?.unmatched??null)} <small>ردیف</small></strong>
        <small>از {fmtNumber(summary.bank?.registered??null)} ردیف صورت‌حساب موجود در دفتر</small>
        <button type="button" onClick={nav('cash')}>رفتن به مغایرت‌گیری <ArrowLeft size={15}/></button></article>}
      {show('cogs')&&<article className={'sac-ah-card'+(uncertain?' attention':'')}>
        <span>کنترل ثبت بهای تمام‌شدهٔ کالا</span>
        <strong>{summary.cogs===null?'نیازمند بررسی':
          summary.cogs.count>0?`${fmtNumber(summary.cogs.count)} فروش ناقص`:'مورد باز شناسایی نشد'}</strong>
        <small>{summary.cogs===null?'اطلاعات انبار برای ارزیابی کامل نیست.':
          summary.cogs.count>0?'صدور فروش ثبت شده اما خروج انبار متناظر کامل نیست.':
            'صرفاً بر اساس اسناد و حرکت‌های انبار همین دفتر.'}</small>
        <button type="button" onClick={nav('items')}>بررسی کاردکس <ArrowLeft size={15}/></button></article>}
    </div>
    {show('performance')&&<div className="sac-ah-performance" aria-label="تفکیک نقد، فروش و عملکرد ماه جاری">
      <div><span>دریافت نقدی عملیاتی جدید (ماه جاری)</span><strong dir="auto">{fmtMoney(summary.cashReceivedMonth,summary.currency)}</strong>
        <small>پرداخت نقدی ثبت‌شده: {fmtMoney(summary.cashPaidMonth,summary.currency)}؛ جدا از فروش</small></div>
      <div><span>فروش خالص فاکتورهای جدید (ماه جاری)</span><strong dir="auto">{fmtMoney(summary.salesMonth,summary.currency)}</strong>
        <small>پس از برگشت‌های ثبت‌شدهٔ هر فاکتور</small></div>
      <div><span>تراز درآمد و هزینه دفترکل (ماه جاری، شامل اسناد واردشده)</span><strong dir="auto">{fmtMoney(summary.ledgerNetMonth,summary.currency)}</strong>
        <small>{uncertain?'سود قطعی نیست؛ ثبت هزینه کالا نیازمند کنترل است.':
          'سود قطعی تأیید نشده؛ صرفاً تراز ثبت‌شده دفترکل.'}</small></div>
      <p>همه مبالغ بر حسب {unit} و مطابق اسناد همین دفتر هستند. مانده نقدی، فروش و سود سه مفهوم مستقل‌اند.</p>
    </div>}
    {(summary.ar.invalid||summary.ap.invalid)&&<p className="sac-ah-warning" role="status">
      <ShieldAlert size={16}/> یک یا چند سند مبلغ یا سررسید نامعتبر دارد؛ جمع‌های مربوطه به جای نمایش عدد ناقص، نامشخص هستند.</p>}
  </section>;
}
