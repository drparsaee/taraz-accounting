import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,BookOpen,Building2,Download,FileText,Landmark,Layers3,
  Plus,RefreshCw,Settings2,ShieldAlert,TrendingUp,Users,Wallet} from 'lucide-react';
import './standalone_accounting_workspace.css';
import TarazIntegrationPanel from './taraz_integration_panel.jsx';
import './standalone_accounting_ux20.css';
import './accounting_density.css';
import './accounting_vitrea.css';
import './accounting_unslop.css';
import './personal_parsian_dark_fix.css';
import {buildStandaloneDocumentExport,downloadStandaloneBlob} from './standalone_invoice_export.js';
import {buildParsianKarmaDocumentExport} from './parsian_karma_invoice_export.js';
import AccountingTopRibbon from './accounting_top_ribbon.jsx';
import ReleaseUpdateSettings from './release_update_settings.jsx';
import ParsianRawArchiveExplorer from './parsian_raw_archive_explorer.jsx';
import PersonalParsianInvoices from './personal_parsian_invoices.jsx';
import PersonalParsianDashboard from './personal_parsian_dashboard.jsx';
import PersonalParsianCompany from './personal_parsian_company.jsx';
import PersonalParsianExtended from './personal_parsian_extended.jsx';
import PersonalParsianBankMovements from './personal_parsian_bank_movements.jsx';
import ProviderCsvMigration from './provider_csv_migration.jsx';
import {buildAccountingInvoiceEntryTemplate,parseAccountingInvoiceEntryTemplate}
  from './accounting_invoice_entry_templates.js';
import AccountingPrintDesigner from './accounting_print_designer.jsx';
import {filterInvoiceRows,invoiceStatusCounts} from './accounting_invoice_quick_filter.js';
import {DEFAULT_PRINT_TEMPLATE,validatePrintTemplate,buildCustomPrintExport}
  from './accounting_print_template.js';
import {buildAccountingStructuredExport} from './accounting_structured_invoice_export.js';
import {formatAccountingJalali,parseAccountingJalali,displayAccountingDate} from './accounting_jalali_dates.js';
import AccountingJalaliField from './accounting_jalali_field.jsx';
import {InvoiceWizardNavigation,INVOICE_WIZARD_STEPS} from './accounting_invoice_wizard.jsx';
import AccountingManagementDashboard from './accounting_management_dashboard.jsx';
import AccountingActionHome from './accounting_action_home.jsx';
import {accountingPeriodRows} from './accounting_period_report.js';
import {LiveCheques,LiveInventory,BankReconciliation,
  InstalmentPlans,PayrollAndTax,FiscalYearClose,
  CompanyProfile} from './accounting_operational_panels.jsx';

// Existing TOMAN v1 ledgers remain labelled accurately; new RIAL v2 ledgers use RIAL.
const ID=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const AMOUNT=/^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$/;
const MAX=1000000000000000n;
const KINDS={asset:'دارایی',liability:'بدهی',equity:'سرمایه',revenue:'درآمد',expense:'هزینه'};
const STATES={draft:'پیش‌نویس',sent:'ارسال‌شده',accepted:'پذیرفته‌شده',
  rejected:'ردشده',converted:'تبدیل‌شده',approved:'تأییدشده',
  issued:'صادرشده',cancelled:'لغوشده',reversed:'برگشت‌شده'};
const sortMap=m=>Object.values(m||{}).sort((a,b)=>String(a.id).localeCompare(String(b.id)));
const daysSinceDue=(due,today)=>due?
  Math.floor((Date.parse(today+'T00:00:00Z')-Date.parse(due+'T00:00:00Z'))/86400000):null;
const humanSource=source=>({
  'journal.manual':'سند حسابداری','invoice.issue':'فاکتور فروش',
  'bill.issue':'صورتحساب خرید','receipt.record':'دریافت',
  'payment.record':'پرداخت','funds.transfer':'انتقال وجه',
  'funds.deposit':'واریز بانکی','journal.reverse':'برگشت سند',
})[source]||source;
const csvField=value=>{
  const str=String(value??'');
  return '"'+(/^[\s]*[=+@-]/.test(str)?"'"+str:str).replace(/"/g,'""')+'"';
};

/** Ledger-backed settlements only. Reversed postings are visible but excluded
 * from totals; no bank payout/reconciliation state is inferred from a receipt. */
export function accountingSettlementOverview(view,today=standaloneToday()){
  const base=/^\d{4}-\d{2}-\d{2}$/.test(today)?today:standaloneToday();
  const anchor=new Date(base+'T00:00:00Z');
  const months=Array.from({length:12},(_,index)=>{
    const d=new Date(Date.UTC(anchor.getUTCFullYear(),anchor.getUTCMonth()-11+index,1));
    return {key:d.toISOString().slice(0,7),received:0n,paid:0n};
  });
  const lookup=new Map(months.map(m=>[m.key,m]));
  const entries=[];let omitted=0;
  for(const [type,key] of [['receipt','receipts'],['payment','payments']]){
    const collection=view?.[key]||{};
    const records=Array.isArray(collection)?collection:Object.values(collection);
    for(const item of records){
      if(!item||typeof item.id!=='string'||!item.id||
         typeof item.date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(item.date)||
         !Number.isSafeInteger(item.total)||item.total<0){omitted++;continue;}
      const timestamp=Date.parse(item.date+'T00:00:00Z');
      if(!Number.isFinite(timestamp)||new Date(timestamp).toISOString().slice(0,10)!==item.date){omitted++;continue;}
      const record={id:item.id,type,date:item.date,total:item.total,
        partyId:item.partyId,accountId:item.accountId,reversed:item.reversed===true};
      entries.push(record);
      const month=lookup.get(item.date.slice(0,7));
      if(month&&!record.reversed){
        if(type==='receipt')month.received+=BigInt(item.total);
        else month.paid+=BigInt(item.total);
      }
    }
  }
  entries.sort((a,b)=>b.date.localeCompare(a.date)||b.id.localeCompare(a.id));
  const received=months.reduce((sum,m)=>sum+m.received,0n);
  const paid=months.reduce((sum,m)=>sum+m.paid,0n);
  const safe=n=>n<=BigInt(Number.MAX_SAFE_INTEGER)&&n>=-BigInt(Number.MAX_SAFE_INTEGER)?Number(n):null;
  const unrepresentable=safe(received)===null||safe(paid)===null||
    safe(received+paid)===null||
    months.some(m=>safe(m.received)===null||safe(m.paid)===null);
  return {months:months.map(m=>({...m,received:safe(m.received),paid:safe(m.paid)})),
    entries,received:safe(received),paid:safe(paid),net:safe(received-paid),omitted,unrepresentable,
    earliest:months[0].key,latest:months[11].key};
}

export function accountingSettlementCsv(entries,parties={},accounts={},unit='ریال'){
  const rows=[['شناسه','نوع عملیات','تاریخ میلادی','طرف حساب','حساب نقدی',
    'مبلغ ('+unit+')','وضعیت'],...entries.map(entry=>[
      entry.id,entry.type==='receipt'?'دریافت':'پرداخت',entry.date,
      parties[entry.partyId]?.name||entry.partyId||'',
      accounts[entry.accountId]?.name||entry.accountId||'',entry.total,
      entry.reversed?'برگشت شده':'ثبت شده'])];
  return '\ufeff'+rows.map(row=>row.map(csvField).join(',')).join('\r\n');
}

export function AccountingVitreaHome({view,currency,today,canDraft,canSettle=false,
  disabled,onNavigate,onNewInvoice,preferenceKey='',api=null,fiscalYear='1405'}){
  const [filter,setFilter]=useState('all');
  const overview=useMemo(()=>accountingSettlementOverview(view,today),[view,today]);
  const parties=view.parties||{},accounts=view.accounts||{};
  const receivableDocs=outstandingStandaloneDocuments(view,'receipt');
  const payableDocs=outstandingStandaloneDocuments(view,'payment');
  const unit=currency==='TOMAN'?'تومان':'ریال';
  const amount=value=>formatStandaloneMoney(value,currency);
  const filtered=overview.entries.filter(entry=>filter==='all'?true:
    filter==='reversed'?entry.reversed:entry.type===filter);
  const banks=Object.entries(accounts).filter(([,a])=>a?.liquid===true&&
    Number.isSafeInteger(a.debitMinusCredit));
  const maximum=Math.max(0,...overview.months.flatMap(m=>[m.received,m.paid]).filter(Number.isSafeInteger));
  const activity=overview.unrepresentable?null:
    overview.received+overview.paid;
  const ratio=activity>0?overview.received/activity*100:0;
  const download=()=>downloadStandaloneBlob({
    filename:'madar-settlements-'+today+'.csv',
    blob:new Blob([accountingSettlementCsv(filtered,parties,accounts,unit)],
      {type:'text/csv;charset=utf-8'})
  });
  const periodTitle=`${overview.earliest} تا ${overview.latest} (ماه میلادی)`;
  return <div className="sac-vtr-home" aria-label="نمای دریافت و پرداخت حسابداری">
    <AccountingActionHome api={api} fiscalYear={fiscalYear} view={view} today={today} canDraft={canDraft}
      canSettle={canSettle} disabled={disabled} preferenceKey={preferenceKey}
      onNavigate={onNavigate} onNewInvoice={onNewInvoice}/>
    <header className="sac-vtr-hero">
      <div className="sac-vtr-heading"><span className="sac-vtr-eyebrow">TARAZ / FINANCIAL FLOWS</span>
        <h2>دریافت‌ها و پرداخت‌ها</h2><p>گردش ثبت‌شدهٔ دفتر جاری، بدون محاسبهٔ تسویهٔ بانکی تأییدنشده</p></div>
      <div className="sac-vtr-hero-stats" aria-label="خلاصه گردش دوازده ماه اخیر">
        <div className="sac-vtr-hero-stat"><span className="sac-vtr-stat-icon"><Download size={17}/></span><div><small>دریافت ثبت‌شده</small><strong dir="auto">{amount(overview.received)}</strong></div></div>
        <div className="sac-vtr-hero-stat"><span className="sac-vtr-stat-icon"><ArrowRight size={17}/></span><div><small>پرداخت ثبت‌شده</small><strong dir="auto">{amount(overview.paid)}</strong></div></div>
        <div className="sac-vtr-hero-stat"><span className="sac-vtr-stat-icon"><TrendingUp size={17}/></span><div><small>خالص گردش نقدی این بازه</small><strong dir="auto">{amount(overview.net)}</strong></div></div>
      </div>
      {canDraft&&<button type="button" className="sac-vtr-cta" disabled={disabled}
        onClick={onNewInvoice}><Plus size={17}/> فاکتور جدید</button>}
    </header>
    {overview.omitted>0&&<div className="sac-vtr-warning" role="status">
      {overview.omitted.toLocaleString('fa-IR')} رکورد با مبلغ یا تاریخ نامعتبر از این نما کنار گذاشته شد. اطلاعات اصلی تغییر نکرده است.</div>}
    {overview.unrepresentable&&<div className="sac-vtr-warning" role="status">
      جمع برخی مبالغ از محدوده محاسبه دقیق رابط فراتر است. نمودار و نسبت‌های مرتبط نمایش داده نمی‌شوند؛ برای بررسی ارقام به دفترکل مراجعه کنید.</div>}
    <section className="sac-vtr-due" aria-label="اسناد صادرشده دارای مانده باز">
      <div className="sac-vtr-due-title">
        <h3>اسناد باز قابل پیگیری</h3>
        <p>فقط فاکتورها و صورتحساب‌های صادرشده در دفتر جاری؛ سوابق منتقل‌شده جداگانه بررسی می‌شوند.</p>
      </div>
      <div className="sac-vtr-due-items">
        <div className="sac-vtr-due-item">
          <div><span>فاکتور فروش با مانده دریافتنی</span>
            <strong>{receivableDocs.length.toLocaleString('fa-IR')} سند</strong></div>
          <div className="sac-vtr-due-actions">
            <button type="button" onClick={()=>onNavigate('invoice')}>بررسی فاکتورها <ArrowLeft size={15}/></button>
            {canSettle&&receivableDocs.length>0&&<button type="button" disabled={disabled}
              onClick={()=>onNavigate('settlements')}>ثبت دریافت</button>}
          </div>
        </div>
        <div className="sac-vtr-due-item">
          <div><span>صورتحساب خرید با مانده پرداختنی</span>
            <strong>{payableDocs.length.toLocaleString('fa-IR')} سند</strong></div>
          <div className="sac-vtr-due-actions">
            <button type="button" onClick={()=>onNavigate('bill')}>بررسی خریدها <ArrowLeft size={15}/></button>
            {canSettle&&payableDocs.length>0&&<button type="button" disabled={disabled}
              onClick={()=>onNavigate('settlements')}>ثبت پرداخت</button>}
          </div>
        </div>
      </div>
    </section>
    <div className="sac-vtr-overview-grid">
      <section className="sac-vtr-panel sac-vtr-chart-panel" aria-label="نمودار گردش دوازده ماه اخیر">
        <div className="sac-vtr-panel-head"><div><h3>گردش ماهانه</h3><small>{periodTitle}</small></div>
          <button type="button" onClick={()=>onNavigate('reports')} aria-label="نمایش گزارش کامل گردش‌ها"><ArrowLeft size={17}/></button></div>
        <div className="sac-vtr-chart-total"><strong>{amount(overview.received)}</strong><span>جمع دریافت‌های ثبت‌شده در بازه</span></div>
        <div className="sac-vtr-legend"><span><i className="receipt"/> دریافت</span><span><i className="payment"/> پرداخت</span></div>
        {!overview.unrepresentable&&maximum>0?<div className="sac-vtr-month-bars" role="img"
          aria-label="نمودار دوازده ماه اخیر؛ دریافت و پرداخت ماهانه">
          {overview.months.map(m=><div className="sac-vtr-month" key={m.key}
            title={`${m.key}: دریافت ${amount(m.received)}، پرداخت ${amount(m.paid)}`}>
            <div className="sac-vtr-bars"><span className="sac-vtr-bar receipt" style={{height:(m.received/maximum*100)+'%'}}/>
              <span className="sac-vtr-bar payment" style={{height:(m.paid/maximum*100)+'%'}}/></div>
            <small dir="ltr">{m.key.slice(5)}</small></div>)}
        </div>:<div className="sac-vtr-empty-chart">{overview.unrepresentable?
          'جمع مبالغ برای رسم نمودار دقیق بیش از محدودهٔ امن است.':
          'در دوازده ماه اخیر دریافت یا پرداخت قطعی ثبت نشده است.'}</div>}
      </section>
      <section className="sac-vtr-panel sac-vtr-ring-panel" aria-label="ترکیب گردش ثبت‌شده">
        <div className="sac-vtr-panel-head"><div><h3>ترکیب گردش نقدی</h3><small>سهم دریافت و پرداخت از کل گردش ۱۲ ماه اخیر</small></div></div>
        <div className={'sac-vtr-ring'+(activity&&!overview.unrepresentable?'':' empty')}
          style={{'--vtr-ratio':ratio+'%'}} role="img"
          aria-label={`سهم دریافت ${activity?ratio.toFixed(1):0} درصد از کل گردش`}>
          <div><strong>{activity&&!overview.unrepresentable?Math.round(ratio).toLocaleString('fa-IR')+'٪':'—'}</strong>
            <small>سهم دریافت</small></div></div>
        <div className="sac-vtr-ring-legend"><div><i className="receipt"/><span>دریافت</span><b dir="auto">{amount(overview.received)}</b></div>
          <div><i className="payment"/><span>پرداخت</span><b dir="auto">{amount(overview.paid)}</b></div></div>
        <p className="sac-vtr-note">این نمودار نسبت مبالغ ثبت‌شده را نشان می‌دهد؛ موجودی بانک یا وضعیت تسویه نیست.</p>
      </section>
    </div>
    <div className="sac-vtr-bottom-grid">
      <section className="sac-vtr-panel sac-vtr-records" aria-label="آخرین دریافت‌ها و پرداخت‌ها">
        <div className="sac-vtr-panel-head"><div><h3>آخرین دریافت‌ها و پرداخت‌ها</h3>
          <small>سوابق واقعی دفتر جاری؛ تراکنش برگشت‌خورده جدا مشخص شده است</small></div>
          <button type="button" onClick={download} disabled={!filtered.length} className="sac-vtr-export"><Download size={15}/> خروجی CSV</button></div>
        <div className="sac-vtr-tabs" role="group" aria-label="فیلتر نوع عملیات">
          {[['all','همه'],['receipt','دریافت‌ها'],['payment','پرداخت‌ها'],['reversed','برگشت‌شده']].map(([value,label])=><button
            type="button" key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}
            className={filter===value?'active':''}>{label}</button>)}</div>
        <div className="sac-vtr-table-scroll" role="region" aria-label="جدول آخرین دریافت‌ها و پرداخت‌ها" tabIndex={0}><table><thead><tr><th>عملیات / شناسه</th><th>طرف‌حساب</th>
          <th>مبلغ ({unit})</th><th>وضعیت</th><th>تاریخ</th></tr></thead><tbody>
          {filtered.slice(0,9).map(r=><tr key={r.type+'-'+r.id}>
            <td><strong>{r.type==='receipt'?'دریافت':'پرداخت'}</strong><small dir="ltr">{r.id}</small></td>
            <td>{parties[r.partyId]?.name||r.partyId||'نامشخص'}</td>
            <td dir="auto" className="sac-vtr-value">{amount(r.total)}</td>
            <td><span className={'sac-vtr-status '+(r.reversed?'reversed':'posted')}>
              {r.reversed?'برگشت‌شده':'ثبت‌شده'}</span></td>
            <td>{displayAccountingDate(r.date)}</td></tr>)}
          {!filtered.length&&<tr key="no-settlements"><td colSpan={5} className="sac-vtr-no-records">رکوردی با این فیلتر ثبت نشده است.</td></tr>}
        </tbody></table></div>
        <div className="sac-vtr-table-footer"><span>{filtered.length.toLocaleString('fa-IR')} رکورد مطابق فیلتر</span>
          <button type="button" onClick={()=>onNavigate('settlements')}>مشاهده همه در بخش دریافت و پرداخت <ArrowLeft size={15}/></button></div>
      </section>
      <aside className="sac-vtr-panel sac-vtr-banking" aria-label="حساب‌های نقدی و مسیر تطبیق بانکی">
        <div className="sac-vtr-panel-head"><div><h3>صندوق، بانک و تطبیق</h3><small>مانده حساب‌های نقدی در دفترکل</small></div></div>
        {banks.length?banks.slice(0,5).map(([id,bank])=><div key={id} className="sac-vtr-account">
          <span className="sac-vtr-account-symbol"><Landmark size={17}/></span><div><strong>{bank.name||id}</strong><small dir="ltr">{id}</small></div>
          <b dir="auto">{amount(bank.debitMinusCredit)}</b></div>):<p className="sac-vtr-no-bank">اطلاعات حساب نقدی از دفتر میزبان دریافت نشده است.</p>}
        <div className="sac-vtr-bank-message"><ShieldAlert size={17}/><span>وضعیت تطبیق هر صورت‌حساب فقط پس از بررسی عملیات بانکی قابل تأیید است.</span></div>
        <button type="button" className="sac-vtr-bank-link" onClick={()=>onNavigate('cash')}>
          مشاهده صندوق، بانک و مغایرت <ArrowLeft size={16}/></button>
      </aside>
    </div>
  </div>;
}
export function nextAccountingNumber(records,prefix,year){
  const esc=prefix.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const pat=new RegExp('^'+esc+'-'+year+'-([0-9]{1,8})$');
  const used=new Set(Object.keys(records||{}));
  let high=0;
  for(const id of used){const m=id.match(pat);if(m)high=Math.max(high,Number(m[1]));}
  for(let n=high+1;n<=99999999;n++){
    const id=prefix+'-'+year+'-'+String(n).padStart(4,'0');
    if(!used.has(id))return id;
  }
  return '';
}
const SECTIONS=[['overview','داشبورد'],['company','مشخصات شرکت'],
  ['proforma','پیش‌فاکتور مستقل'],
  ['invoice','فاکتورهای فروش'],['bill','صورتحساب‌های خرید'],
  ['contractors','کارهای پیمانکاران'],
  ['parties','اشخاص'],['migration','مهاجرت و سوابق'],['cheques','خزانه و چک'],
  ['items','کالا، انبار و کاردکس'],['settlements','دریافت، پرداخت و اقساط'],
  ['cash','صندوق، بانک و مغایرت'],['accounts','حساب‌ها و دفترکل'],
  ['journal','سند دستی و برگشت'],['reports','گزارش‌های مالی'],
  ['payroll','حقوق و مالیات'],['period','سال مالی و بستن دوره'],
  ['settings','تنظیمات حسابداری']];
export const standaloneToday=()=>{const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');};
/** Display-side company day; native host remains authoritative for posting. */
export function accountingCompanyToday(view,now=new Date()){
  // Legacy profiles are validated against the native host's UTC timestamp.
  // Never prefill a different browser-local calendar day until an explicit
  // company posting offset is stored by the financial administrator.
  const instant=now instanceof Date&&Number.isFinite(now.getTime())?now:new Date();
  const legacyDay=instant.toISOString().slice(0,10);
  const offset=view?.companyProfile?.postingUtcOffsetMinutes;
  if(!Number.isInteger(offset)||offset< -720||offset>840)return legacyDay;
  return new Date(instant.getTime()+offset*60000).toISOString().slice(0,10);
}
const validId=v=>typeof v==='string'&&ID.test(v);
const validText=(v,max=300)=>typeof v==='string'&&!!v.trim()&&v.trim().length<=max&&!/[\x00-\x1f\x7f]/.test(v);
const failure=error=>({error});
export function parseStandaloneToman(value,{allowZero=false}={}){
  if(typeof value!=='string'&&typeof value!=='number')return null;
  if(typeof value==='number'&&!Number.isSafeInteger(value))return null;
  const txt=String(value).trim().replace(/[۰-۹]/g,x=>String(x.charCodeAt(0)-1776))
    .replace(/[٠-٩]/g,x=>String(x.charCodeAt(0)-1632)).replace(/\u066c/g,',');
  if(txt.length>32||!AMOUNT.test(txt))return null;
  const exact=BigInt(txt.replace(/,/g,''));
  if(exact>MAX||(!allowZero&&exact===0n))return null;
  return Number(exact);
}
export function validStandaloneDate(text,today=standaloneToday()){
  if(typeof text!=='string'||!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(text)||text>today)return false;
  const [y,m,d]=text.split('-').map(Number),check=new Date(Date.UTC(y,m-1,d));
  // UI explicitly supports Gregorian 1900+; rejects Jalali-looking 14xx
  // rather than silently interpreting it as an ancient Gregorian year.
  return y>=1900&&check.getUTCFullYear()===y&&check.getUTCMonth()===m-1&&check.getUTCDate()===d;
}
export const formatStandaloneMoney=(n,currency='TOMAN')=>Number.isSafeInteger(n)?
  n.toLocaleString('fa-IR')+(currency==='RIAL'?' ریال':' تومان'):'نامشخص';
const parse=(value,allowZero=false)=>parseStandaloneToman(value,{allowZero});
export function previewAccountingTotal(lines,discount='0',tax='0'){
  try{
    let sum=0n;
    for(const item of lines){
      const quantity=parse(item.quantity),price=parse(item.unitPrice,true);
      if(quantity===null||price===null)return null;
      sum+=BigInt(quantity)*BigInt(price);if(sum>MAX)return null;
    }
    const d=parse(discount,true),t=parse(tax,true);
    if(d===null||t===null||BigInt(d)>sum)return null;
    const total=sum-BigInt(d)+BigInt(t);
    return total>MAX?null:{subtotal:Number(sum),discount:d,tax:t,total:Number(total)};
  }catch(_err){return null;}
}

export function buildStandaloneInvoiceCommand({kind,documentId,partyId,documentDate,lines,
    discount='0',tax='0',taxRuleId='',dueDate='',note='',eventId,
    accounts={},items={},today=standaloneToday()}){
  if(!['invoice','bill'].includes(kind)||!validId(documentId)||!validId(eventId)||!validId(partyId))
    return failure('نوع، شناسه سند یا طرف‌حساب معتبر نیست.');
  if(!validStandaloneDate(documentDate,today))return failure('تاریخ سند معتبر نیست.');
  if(dueDate&&(!validStandaloneDate(dueDate,'9999-12-31')||dueDate<documentDate))
    return failure('سررسید باید تاریخی معتبر و بعد از تاریخ فاکتور باشد.');
  if(typeof note!=='string'||note.length>1000||/[\x00-\x1f\x7f]/.test(note))
    return failure('یادداشت معتبر نیست.');
  if(!Array.isArray(lines)||!lines.length||lines.length>1000)
    return failure('سند باید ۱ تا ۱۰۰۰ ردیف صریح داشته باشد.');
  let subtotal=0n;const cleanLines=[];
  for(const line of lines){
    if(!line||!validText(line.description))return failure('شرح هر ردیف الزامی است.');
    const q=parse(line.quantity),price=parse(line.unitPrice,true);
    const code=line.accountId|| (kind==='invoice'?'4000':'5000');
    if(q===null||q>1000000||price===null)return failure('تعداد یا قیمت ردیف معتبر نیست.');
    if(!validId(code)||accounts[code]?.kind!==(kind==='invoice'?'revenue':'expense'))
      return failure('سرفصل درآمد/هزینه انتخابی وجود ندارد.');
    if(line.itemId&&(!validId(line.itemId)||items[line.itemId]?.active!==true))
      return failure('قلم انتخابی باید در کاتالوگ فعال باشد.');
    subtotal+=BigInt(q)*BigInt(price);
    if(subtotal>MAX)return failure('جمع ردیف‌ها بیش از سقف حسابداری است.');
    cleanLines.push({description:line.description.trim(),quantity:q,unitPrice:price,accountId:code,
      ...(line.itemId?{itemId:line.itemId}:{})});
  }
  const d=parse(discount,true),t=parse(tax,true);
  if(d===null||t===null||BigInt(d)>subtotal)return failure('تخفیف یا مالیات نامعتبر است.');
  const total=subtotal-BigInt(d)+BigInt(t);
  if(total<=0n||total>MAX)return failure('مبلغ نهایی سند باید مثبت و محدود باشد.');
  return {error:'',total:Number(total),command:{
    type:kind+'.create',eventId,[kind+'Id']:documentId,partyId,documentDate,lines:cleanLines,
    discount:d,tax:t,...(taxRuleId?{taxRuleId}:{}),
    ...(dueDate?{dueDate}:{}),
    ...(note.trim()?{note:note.trim()}:{})}};
}

/** Inline guidance only; final submission still goes through the authoritative
 * buildStandaloneInvoiceCommand and the host's finance role and revision gates. */
export function invoiceWizardIssues({document,rows,accounts={},items={},today,
  kind='invoice',tax='0',correctionTarget='',correctionReason='',correctionDate=''}){
  const issues=['','','','',''];
  if(!validId(document?.documentId)||!validId(document?.partyId)||
      !validStandaloneDate(document?.documentDate,today)){
    issues[0]='شماره سند، مشتری و تاریخ معتبر را تکمیل کنید.';
  }
  if(correctionTarget&&(!validText(correctionReason,1000)||
    !validStandaloneDate(correctionDate,today))){
    issues[0]='تاریخ برگشت قطعی و علت اصلاح سند صادرشده الزامی و باید معتبر باشند.';
  }
  if(!Array.isArray(rows)||rows.length<1||rows.length>1000||
    rows.some(row=>{
      const qty=parse(row?.quantity),price=parse(row?.unitPrice,true);
      const account=row?.accountId||(kind==='invoice'?'4000':'5000');
      return !validText(row?.description)||qty===null||qty>1000000||
        price===null||!validId(account)||
        accounts[account]?.kind!==(kind==='invoice'?'revenue':'expense')||
        (row?.itemId&&(!validId(row.itemId)||items[row.itemId]?.active!==true));
    })){
    issues[1]='شرح، تعداد، قیمت و سرفصل معتبر برای همه ردیف‌ها الزامی است.';
  }
  const total=previewAccountingTotal(rows,document?.discount,tax);
  if(!total||total.total<=0)issues[2]='تخفیف، مالیات یا جمع اقلام معتبر نیست؛ مبلغ نهایی باید مثبت باشد.';
  const due=document?.dueDate;
  if((due&&(!validStandaloneDate(due,'9999-12-31')||due<document.documentDate))||
    typeof document?.note!=='string'||document.note.length>1000||
    /[\x00-\x1f\x7f]/.test(document.note)){
    issues[3]='سررسید باید پس از تاریخ سند باشد؛ توضیحات را نیز بررسی کنید.';
  }
  return issues;
}

/** Sales quote only. No task/card/project ID and no posting command. */
export function buildStandaloneProformaCommand({proformaId,partyId,documentDate,validUntil='',
  lines,discount='0',tax='0',note='',eventId,accounts={},items={},today=standaloneToday(),
  update=false}){
  const built=buildStandaloneInvoiceCommand({kind:'invoice',documentId:proformaId,
    partyId,documentDate,lines,discount,tax,note,eventId,accounts,items,today});
  if(built.error)return built;
  if(validUntil&&(!validStandaloneDate(validUntil,'9999-12-31')||validUntil<documentDate))
    return failure('تاریخ اعتبار پیش‌فاکتور باید معتبر و بعد از تاریخ سند باشد.');
  const {invoiceId,...rest}=built.command;
  return {...built,command:{...rest,type:update?'proforma.update':'proforma.create',
    proformaId:invoiceId,...(validUntil?{validUntil}:{})}};
}

export function outstandingStandaloneDocuments(view,kind,partyId=''){
  if(!['receipt','payment'].includes(kind))return [];
  const docs=view?.[kind==='receipt'?'invoices':'bills'];
  if(!docs||typeof docs!=='object'||Array.isArray(docs))return [];
  return Object.values(docs).filter(d=>d&&d.status==='issued'&&validId(d.id)&&
    (!partyId||d.partyId===partyId)&&Number.isSafeInteger(d.total)&&
    Number.isSafeInteger(d.allocated)&&d.allocated>=0&&
    Number.isSafeInteger(d.returnedAmount??0)&&(d.returnedAmount??0)>=0&&
    Number.isSafeInteger(d.allocated+(d.returnedAmount??0))&&
    d.allocated+(d.returnedAmount??0)<d.total);
}
export function buildStandaloneSettlementCommand({kind,document,amount,accountId,postingDate,
    eventId,accounts={},today=standaloneToday()}){
  if(!['receipt','payment'].includes(kind)||!validId(eventId))
    return failure('نوع یا شناسه تسویه معتبر نیست.');
  if(!document||!outstandingStandaloneDocuments(
    {[kind==='receipt'?'invoices':'bills']:{[document.id]:document}},kind).length||!validId(document.partyId))
    return failure('سند صادرشده با مانده مثبت انتخاب نشده است.');
  const sum=parse(amount);
  if(sum===null||sum>document.total-document.allocated-(document.returnedAmount||0))
    return failure('مبلغ تسویه از مانده پس از مرجوعی بیشتر یا نامعتبر است.');
  if(!validId(accountId)||accounts[accountId]?.liquid!==true)return failure('حساب صندوق/بانک معتبر نیست.');
  if(!validStandaloneDate(postingDate,today)||postingDate<document.postingDate)
    return failure('تاریخ تسویه باید از تاریخ صدور سند تا امروز باشد.');
  const sales=kind==='receipt';
  return {error:'',command:{type:sales?'receipt.record':'payment.record',eventId,
    [sales?'receiptId':'paymentId']:eventId,partyId:document.partyId,
    accountId,postingDate,allocations:[{[sales?'invoiceId':'billId']:document.id,amount:sum}]}};
}
export function buildStandaloneManualCommand({lines,note,postingDate,eventId,accounts={},today=standaloneToday()}){
  if(!validId(eventId)||!validText(note,1000)||!validStandaloneDate(postingDate,today))
    return failure('شرح، تاریخ یا شناسه سند دستی معتبر نیست.');
  if(!Array.isArray(lines)||lines.length<2||lines.length>100)
    return failure('سند دستی باید ۲ تا ۱۰۰ ردیف داشته باشد.');
  let debit=0n,credit=0n;const rows=[];
  for(const row of lines){
    if(!row||!validId(row.accountId)||!accounts[row.accountId]||
      ['1200','2000'].includes(row.accountId))
      return failure('حساب دریافتنی/پرداختنی یا حساب ناشناخته در سند دستی مجاز نیست.');
    const dr=parse(row.debit,true),cr=parse(row.credit,true);
    if(dr===null||cr===null||(dr>0)===(cr>0))
      return failure('هر ردیف دقیقاً یک مبلغ مثبت بدهکار یا بستانکار نیاز دارد.');
    debit+=BigInt(dr);credit+=BigInt(cr);
    if(debit>MAX||credit>MAX)return failure('مجموع ردیف‌ها بیش از سقف است.');
    rows.push({accountId:row.accountId,debit:dr,credit:cr});
  }
  if(debit===0n||debit!==credit)return failure('سند دستی باید تراز و مثبت باشد.');
  return {error:'',command:{type:'journal.manual',eventId,postingDate,note:note.trim(),lines:rows}};
}

export function validateStandaloneResponse(payload){
  const view=payload?.view;
  if(!Number.isSafeInteger(payload?.revision)||payload.revision<0||
    !view||!['TOMAN','RIAL'].includes(view.currency)||!Array.isArray(view.journals)||
    !['accounts','parties','items','invoices','bills','receipts','payments'].every(
      k=>view[k]&&typeof view[k]==='object'&&!Array.isArray(view[k])))
    throw new Error('پاسخ میزبان با قرارداد حسابداری مستقل سازگار نیست.');
  const currentUser=payload.currentUser;
  if(currentUser!==undefined&&(
    !currentUser||typeof currentUser.username!=='string'||
    !['admin','editor','viewer'].includes(currentUser.role)||
    typeof currentUser.jobTitle!=='string'||currentUser.jobTitle.length>80))
    throw new Error('هویت نمایشی کاربر در پاسخ میزبان نامعتبر است.');
  return {...(currentUser?{currentUser}:{}),revision:payload.revision,view};
}

const T=()=>standaloneToday();
const DEFAULTS={
  party:{partyId:'',name:'',kind:'customer',creditLimit:''},
  item:{itemId:'',sku:'',name:'',kind:'service',unit:'عدد'},
  document:{documentId:'',partyId:'',documentDate:T(),dueDate:'',note:'',
    discount:'0',tax:'0',taxRuleId:''},
  proforma:{proformaId:'',partyId:'',documentDate:T(),validUntil:'',note:'',discount:'0',tax:'0'},
  settlement:{kind:'receipt',documentId:'',accountId:'1010',amount:'',postingDate:T()},
  deposit:{accountId:'1010',amount:'',postingDate:T(),note:''},
  transfer:{fromAccountId:'1010',toAccountId:'1000',amount:'',postingDate:T(),note:''},
  account:{accountId:'',name:'',kind:'expense',liquid:false,level:'kol',parentId:''},
  manual:{postingDate:T(),note:''},
  reverse:{journalId:'',postingDate:T(),reason:''},
  close:{throughDate:T()},
};
const makeLine=()=>({description:'',quantity:'1',unitPrice:'',accountId:'',itemId:''});
const makeJournalLine=()=>({accountId:'',debit:'0',credit:'0'});
const chartLevelName=level=>({kol:'کل',moein:'معین',tafsili:'تفصیلی'})[level]||'قدیمی';
function totalChartBalance(accounts,rootId){
  const linked=new Set([rootId]);
  let changed=true;
  while(changed){
    changed=false;
    for(const account of Object.values(accounts||{})){
      if(account.parentId&&linked.has(account.parentId)&&!linked.has(account.id)){
        linked.add(account.id);changed=true;
      }
    }
  }
  return [...linked].reduce((sum,id)=>sum+(accounts[id]?.debitMinusCredit||0),0);
}
const newId=()=>{
  const uuid=globalThis.crypto?.randomUUID?.();
  if(!uuid)throw new Error('تولید شناسه یکتای امن در این محیط ممکن نیست.');
  return 'evt.'+uuid;
};
const isConflict=e=>/conflict|stale|version|revision|409|تعارض|نسخه/i.test(String(e?.message||''));
function Field({label,children,wide=false}){return <label className={'sac-field'+(wide?' sac-wide':'')}>
  <span>{label}</span>{children}</label>;}
function Panel({title,description,children,compact=false}){return <section
  className={'sac-panel'+(compact?' sac-panel-invoice-compose':'')}>
  <div className="sac-panel-title"><h2>{title}</h2>{description&&<p>{description}</p>}</div>{children}</section>;}
function Empty({children}){return <p className="sac-empty">{children}</p>;}
const textOf=node=>{
  if(node===null||node===undefined||typeof node==='boolean')return '';
  if(typeof node==='string'||typeof node==='number')return String(node);
  if(Array.isArray(node))return node.map(textOf).join(' ');
  return textOf(node?.props?.children);
};
function DataTable({cols,rows,empty,focusTarget=null}){
  const [filter,setFilter]=useState(''),[column,setColumn]=useState(-1),
    [desc,setDesc]=useState(false),[visibleLimit,setVisibleLimit]=useState(100);
  const selectedRow=useRef(null),lastFocusedToken=useRef(null);
  const large=rows.length>12;
  const targetIndex=focusTarget?rows.findIndex(row=>
    row.props?.['data-accounting-search-kind']===focusTarget.kind&&
    row.props?.['data-accounting-search-id']===focusTarget.id):-1;
  useEffect(()=>{
    if(!focusTarget||targetIndex<0)return;
    // The exact selected host-authorized row may be beyond the first 100 rows.
    // Drop an old table filter/sort rather than focusing an unrelated row.
    setFilter('');setColumn(-1);setDesc(false);
    setVisibleLimit(Math.max(100,targetIndex+1));
  },[focusTarget?.token,focusTarget?.kind,focusTarget?.id,targetIndex]);
  useEffect(()=>{
    if(!focusTarget||targetIndex<0||lastFocusedToken.current===focusTarget.token||
      filter||column!==-1||visibleLimit<=targetIndex)return;
    const frame=window.requestAnimationFrame(()=>{
      const row=selectedRow.current;
      if(!row||row.dataset.accountingSearchId!==focusTarget.id)return;
      row.scrollIntoView({block:'center',behavior:'instant'});
      row.focus({preventScroll:true});
      lastFocusedToken.current=focusTarget.token;
    });
    return ()=>window.cancelAnimationFrame(frame);
  },[focusTarget?.token,focusTarget?.kind,focusTarget?.id,targetIndex,
    filter,column,visibleLimit]);
  const indexed=rows.map((row,i)=>({
    row,i,cells:React.Children.toArray(row.props.children).filter(Boolean)}));
  const matched=filter.trim()?indexed.filter(x=>textOf(x.row).toLocaleLowerCase('fa-IR')
    .includes(filter.trim().toLocaleLowerCase('fa-IR'))):indexed;
  if(column>=0)matched.sort((a,b)=>{
    const av=textOf(a.cells[column]),bv=textOf(b.cells[column]);
    const result=av.localeCompare(bv,'fa-IR',{numeric:true});
    return desc?-result:result;
  });
  // Continuous list. Rendering in batches avoids a large table freezing WebView2.
  const visible=matched.slice(0,visibleLimit);
  const remaining=Math.max(0,matched.length-visible.length);
  return rows.length?<div className="sac-table-container">
    <div className="sac-table-tools">
      {large&&<label>جست‌وجو در جدول<input type="search" aria-label="جست‌وجو در جدول"
        placeholder="نام، شماره، مبلغ یا کد..."
        value={filter} onChange={e=>{setFilter(e.target.value);setVisibleLimit(100);}}/></label>}
      <span aria-live="polite">{visible.length.toLocaleString('fa-IR')} از {matched.length.toLocaleString('fa-IR')} ردیف
        {filter?' (کل جدول: '+rows.length.toLocaleString('fa-IR')+')':''}</span>
    </div>
    <div className="sac-table-wrap" role="region" tabIndex={0}
      aria-label={'جدول حسابداری: '+cols.slice(0,3).join('، ')}><table><thead><tr>{cols.map((x,i)=>
      <th key={i}>{large?<button type="button" className="sac-table-sort"
        onClick={()=>{setColumn(i);setDesc(column===i?!desc:false);setVisibleLimit(100);}}
        aria-label={'مرتب‌سازی بر اساس '+x}>{x}{column===i?(desc?' ↓':' ↑'):''}</button>:x}</th>)}
      </tr></thead><tbody>{visible.map(x=>
        focusTarget&&x.row.props?.['data-accounting-search-kind']===focusTarget.kind&&
          x.row.props?.['data-accounting-search-id']===focusTarget.id?
          React.cloneElement(x.row,{ref:selectedRow,tabIndex:-1,
            className:'sac-search-target-row',
            'aria-label':'رکورد انتخاب‌شده: '+focusTarget.id}):x.row
      )}</tbody></table></div>
    {remaining>0&&<div className="sac-table-pagination">
      <span>{remaining.toLocaleString('fa-IR')} ردیف دیگر در همین فهرست</span>
      <button type="button" onClick={()=>setVisibleLimit(p=>p+100)}>نمایش ۱۰۰ ردیف بعدی</button>
      <button type="button" onClick={()=>setVisibleLimit(Number.MAX_SAFE_INTEGER)}>نمایش همه ردیف‌ها</button>
    </div>}
  </div>:<Empty>{empty}</Empty>;
}
function Action({children,disabled}){return <button type="submit" className="sac-primary" disabled={disabled}>{children}</button>;}

/** Entirely independent accounting desk. Host authenticates; UI never passes actor/company/proof. */
export function StandaloneAccountingWorkspace({api,onExit=()=>{},canManage=false,
  onSwitchCompany=null,onManageUsers=null,canDraft=canManage,canAdmin=canManage}){
  const [tab,setTab]=useState('overview');
  const [fiscalYear,setFiscalYear]=useState('1405');
  const [invoiceComposerOpen,setInvoiceComposerOpen]=useState(false);
  const [invoiceWizardMode,setInvoiceWizardMode]=useState('guided');
  const [invoiceWizardStep,setInvoiceWizardStep]=useState(0);
  const [invoiceWizardChecked,setInvoiceWizardChecked]=useState({});
  const [invoiceWizardError,setInvoiceWizardError]=useState('');
  const [invoiceListSearch,setInvoiceListSearch]=useState('');
  const [invoiceListStatus,setInvoiceListStatus]=useState('all');
  const [snapshot,setSnapshot]=useState(null);
  const [taxPreflight,setTaxPreflight]=useState(null);
  const [state,setState]=useState({loading:true,error:'',notice:''});
  const [busy,setBusy]=useState(false);
  const [childDrafts,setChildDrafts]=useState({});
  const childDraftsLive=useRef({});
  const reportChildDraft=useCallback((key,hasDraft)=>{
    // Update the ref immediately in the field-change event. A user can press
    // the native X before the passive React effect publishes the new state.
    childDraftsLive.current[key]=hasDraft;
    setChildDrafts(previous=>previous[key]===hasDraft?previous:
      {...previous,[key]:hasDraft});
  },[]);
  const [pendingRetry,setPendingRetry]=useState(false);
  const [forms,setForms]=useState(DEFAULTS);
  const [rows,setRows]=useState([makeLine()]);
  const [proformaRows,setProformaRows]=useState([makeLine()]);
  const [proformaEditing,setProformaEditing]=useState('');
  const [partyEditing,setPartyEditing]=useState('');
  const [partyEditReason,setPartyEditReason]=useState('');
  const [proformaConversions,setProformaConversions]=useState({});
  const [proformaReasons,setProformaReasons]=useState({});
  const [manualRows,setManualRows]=useState([makeJournalLine(),makeJournalLine()]);
  const [cancelTarget,setCancelTarget]=useState('');
  const [cancelReason,setCancelReason]=useState('');
  const [accountFilter,setAccountFilter]=useState('');
  const [selectedHistoricAccount,setSelectedHistoricAccount]=useState('');
  const [partyQuery,setPartyQuery]=useState('');
  const [reportAccount,setReportAccount]=useState('');
  const [reportFrom,setReportFrom]=useState('');
  const [reportTo,setReportTo]=useState('');
  const [historicalDebtorSearch,setHistoricalDebtorSearch]=useState('');
  const [historicalInvoiceSearch,setHistoricalInvoiceSearch]=useState('');
  const [selectedHistoricInvoice,setSelectedHistoricInvoice]=useState('');
  const [historicalReceipt,setHistoricalReceipt]=useState({
    debtorId:'',bankId:'',amount:'',postingDate:T(),note:''});
  const [issueDate,setIssueDate]=useState(T());
  const [vendorDraft,setVendorDraft]=useState({jobId:'',sourceId:'',partyId:'',
    description:'',quantity:'1',unitPrice:'',currency:'RIAL'});
  const [vendorPrices,setVendorPrices]=useState({});
  const [vendorQuantities,setVendorQuantities]=useState({});
  const [vendorSelected,setVendorSelected]=useState({});
  const [batchId,setBatchId]=useState('');
  const [batchParty,setBatchParty]=useState('');
  const [editTarget,setEditTarget]=useState('');
  const [detailTarget,setDetailTarget]=useState('');
  const [searchTarget,setSearchTarget]=useState(null);
  const searchSequence=useRef(0);
  const [reopenReason,setReopenReason]=useState('');
  const [correctionTarget,setCorrectionTarget]=useState('');
  const [correctionReason,setCorrectionReason]=useState('');
  const [returnTarget,setReturnTarget]=useState('');
  const [returnReason,setReturnReason]=useState('');
  const [returnMode,setReturnMode]=useState('full');
  const [returnQuantities,setReturnQuantities]=useState({});
  const [correctionDate,setCorrectionDate]=useState(T());
  const [filenamePattern,setFilenamePattern]=useState('madar-{kind}-{id}-{date}');
  // Do not silently brand a new company's invoice with Karma's logo.
  // The prior Parsian layout remains an explicit opt-in template.
  const [invoicePrintLayout,setInvoicePrintLayout]=useState('madar');
  const [invoiceTemplateTitle,setInvoiceTemplateTitle]=useState('قالب خدمات');
  const [invoiceTemplateImportMode,setInvoiceTemplateImportMode]=useState('replace');
  const [entryLibrary,setEntryLibrary]=useState({templates:[],defaultId:''});
  const [printLibrary,setPrintLibrary]=useState({templates:[],defaultId:''});
  const [issuerLibrary,setIssuerLibrary]=useState({templates:[],defaultId:''});
  const [entryTemplateId,setEntryTemplateId]=useState('');
  const [printTemplateId,setPrintTemplateId]=useState('');
  const [issuerId,setIssuerId]=useState('');
  const [issuerProfile,setIssuerProfile]=useState({legalName:'',nationalId:'',economicCode:'',
    postalCode:'',phone:'',address:''});
  const [templateSearch,setTemplateSearch]=useState('');
  const [invoiceCatalogSearch,setInvoiceCatalogSearch]=useState('');
  const [printTemplate,setPrintTemplate]=useState(DEFAULT_PRINT_TEMPLATE);
  const [printDesignerOpen,setPrintDesignerOpen]=useState(false);
  const live=useRef(true),request=useRef(0),locked=useRef(false),latest=useRef(null),
    pending=useRef(null),nativeClosePending=useRef(false);
  const view=snapshot?.view;
  const today=accountingCompanyToday(view);
  const lastDefaultDay=useRef(T());
  useEffect(()=>{
    if(!view||today===lastDefaultDay.current)return;
    const previous=lastDefaultDay.current;
    lastDefaultDay.current=today;
    const fields=[['document','documentDate'],['proforma','documentDate'],
      ['settlement','postingDate'],['deposit','postingDate'],
      ['transfer','postingDate'],['manual','postingDate'],
      ['reverse','postingDate'],['close','throughDate']];
    setForms(current=>{
      const next={...current};
      for(const [group,key] of fields){
        if(current[group]?.[key]===previous)next[group]={...current[group],[key]:today};
      }
      return next;
    });
    setIssueDate(date=>date===previous?today:date);
    setCorrectionDate(date=>date===previous?today:date);
    setHistoricalReceipt(prev=>prev.postingDate===previous?
      {...prev,postingDate:today}:prev);
  },[view,today]);
  const [legacyCompanySource,setLegacyCompanySource]=useState(null);
  useEffect(()=>{
    if(typeof api?.standaloneAccountingParsianCompany!=='function')return;
    let active=true;
    Promise.resolve().then(()=>api.standaloneAccountingParsianCompany())
      .then(data=>{if(active)setLegacyCompanySource(data)})
      .catch(()=>{if(active)setLegacyCompanySource(null)});
    return()=>{active=false};
  },[api]);
  const ledgerCurrency=view?.currency||'RIAL';
  const templateBridge=typeof api?.standaloneAccountingTemplateList==='function';
  const loadTemplateLibraries=async()=>{
    if(!templateBridge)return;
    try{
      const [entry,print,issuer]=await Promise.all([
        api.standaloneAccountingTemplateList('entry'),
        api.standaloneAccountingTemplateList('print'),
        api.standaloneAccountingTemplateList('issuer')]);
      setEntryLibrary(entry);setPrintLibrary(print);setIssuerLibrary(issuer);
      setEntryTemplateId(id=>id||entry.defaultId||'');
      setPrintTemplateId(id=>id||print.defaultId||'');
      setIssuerId(id=>id||issuer.defaultId||'');
      const choice=print.templates.find(t=>t.id===print.defaultId);
      if(choice){setPrintTemplate(validatePrintTemplate(choice.data));
        setInvoicePrintLayout(old=>old==='madar'?'custom':old);}
    }catch(error){setState(p=>({...p,error:'بارگذاری کتابخانه قالب‌ها: '+error.message}));}
  };
  useEffect(()=>{void loadTemplateLibraries();},[api]);
  const unitLabel=ledgerCurrency==='RIAL'?'ریال':'تومان';
  const selectedIssuer=issuerLibrary.templates.find(t=>t.id===issuerId);
  const printCompanyProfile=selectedIssuer?.data?.profile||view?.companyProfile||null;
  const moneyText=amount=>formatStandaloneMoney(amount,ledgerCurrency);
  const debitText=amount=><span className={amount>0?'sac-money-debit':'sac-money-neutral'}
    aria-label={'بدهکار '+moneyText(amount)}>{moneyText(amount)}</span>;
  const creditText=amount=><span className={amount>0?'sac-money-credit':'sac-money-neutral'}
    aria-label={'بستانکار '+moneyText(amount)}>{moneyText(amount)}</span>;
  const signedText=amount=>amount>0?debitText(amount):
    amount<0?creditText(-amount):<span className="sac-money-neutral">{moneyText(0)}</span>;
  const accounts=view?.accounts||{},parties=view?.parties||{},items=view?.items||{};
  const invoiceCatalogMatches=useMemo(()=>{
    const term=invoiceCatalogSearch.trim().toLocaleLowerCase('fa-IR');
    return Object.values(items).filter(item=>item&&item.active===true&&
      (!term||[item.name,item.sku,item.id].some(value=>String(value||'')
        .toLocaleLowerCase('fa-IR').includes(term)))).sort((a,b)=>
          String(a.name||a.id).localeCompare(String(b.name||b.id),'fa-IR'));
  },[items,invoiceCatalogSearch]);
  const historical=view?.parsianMigration||null;
  const historicalDebtors=sortMap(parties).map(p=>{
    const ident=p.sourceLedgerAccountId;
    const account=ident?accounts[ident]:null;
    return {name:p.name,sourceAccountId:ident||'',balanceRial:account?.debitMinusCredit??0};
  }).filter(x=>x.sourceAccountId&&x.balanceRial>0&&
    (!historicalDebtorSearch||
      (x.name+' '+x.sourceAccountId).toLocaleLowerCase('fa-IR').includes(
        historicalDebtorSearch.trim().toLocaleLowerCase('fa-IR'))));
  const historicalInvoices=(historical?.historicalDocuments||[]).filter(x=>
    !historicalInvoiceSearch||
    (x.number+' '+x.kind+' '+x.dateJalali+' '+x.linkedSanad)
      .toLocaleLowerCase('fa-IR').includes(
        historicalInvoiceSearch.trim().toLocaleLowerCase('fa-IR')));
  const activeHistoricInvoice=(historical?.historicalDocuments||[])
    .find(x=>x.sourceId===selectedHistoricInvoice);
  const historicalBankAccounts=sortMap(accounts).filter(x=>
    x.kind==='asset'&&/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.test(x.id));
  const activeCash=sortMap(accounts).filter(a=>a.liquid);
  const historicCash=sortMap(accounts).filter(a=>/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.test(a.id)&&a.kind==='asset');
  // A Parsian party ID is ps.parsian.1405.party.12.2.N.
  // Its posted GL counterpart is ps.parsian.account.t.12.2.N.
  // The previous mapping only matched ps.party.* and silently displayed zero.
  const historicalPartyAccounts=sortMap(parties).map(p=>{
    const prefix='ps.parsian.1405.party.';
    const suffix=p.id.startsWith(prefix)?p.id.slice(prefix.length):'';
    const postingId=/^12\.2\.[0-9]+$/.test(suffix)?
      'ps.parsian.account.t.'+suffix:null;
    const account=postingId?accounts[postingId]:null;
    return {...p,legacyId:account?postingId:null,
      historicRial:account?.debitMinusCredit??0,
      originalParsianCode:suffix||null};
  });
  const partyOptions=list=>list.filter(p=>
    !partyQuery.trim()||p.id===forms.document.partyId||p.id===forms.proforma.partyId||
    (p.name+' '+p.id).toLocaleLowerCase('fa-IR').includes(partyQuery.trim().toLocaleLowerCase('fa-IR')));
  const selectedTaxRule=view?.taxRules?.[forms.document.taxRuleId]||null;
  const selectedRuleVersion=selectedTaxRule?.history?.filter(r=>
    r.effectiveFrom<=forms.document.documentDate).slice(-1)[0]||null;
  const untaxedPreview=previewAccountingTotal(rows,forms.document.discount,'0');
  const documentTax=(selectedRuleVersion&&untaxedPreview)?
    String(Number((BigInt(untaxedPreview.subtotal-untaxedPreview.discount)*
      BigInt(selectedRuleVersion.rateBasisPoints)+5000n)/10000n)):
    forms.document.tax;
  const documentPreview=previewAccountingTotal(rows,forms.document.discount,documentTax);
  const proformaPreview=previewAccountingTotal(proformaRows,forms.proforma.discount,forms.proforma.tax);
  const displayHistoricDetails=ident=>{
    // Historic-account shortcuts must honor the unsaved-editor navigation veto.
    if(!gotoTab('accounts'))return;
    setSelectedHistoricAccount(ident);setAccountFilter(ident);
  };
  const periodReport=useMemo(()=>view?accountingPeriodRows(view,{
    fromDate:reportFrom,toDate:reportTo,accountId:reportAccount}):null,
    [view,reportFrom,reportTo,reportAccount]);
  const reportJournals=(view?.journals||[]).filter(j=>
    (!reportFrom||j.date>=reportFrom)&&(!reportTo||j.date<=reportTo));
  const exportMovements=()=>{const records=reportJournals.flatMap(j=>
    j.lines.filter(l=>!reportAccount||l.accountId===reportAccount).map(l=>[
      j.id,j.date,humanSource(j.sourceType),l.accountId,
      accounts[l.accountId]?.name||l.accountId,l.debit,l.credit]));
    const csv=[['سند','تاریخ شمسی','تاریخ میلادی','نوع','کد حساب','عنوان حساب','بدهکار '+unitLabel,
      'بستانکار '+unitLabel],...records.map(row=>[row[0],
      formatAccountingJalali(row[1],{digits:'ascii'}),...row.slice(1)])]
      .map(row=>row.map(csvField).join(',')).join('\r\n');
    downloadStandaloneBlob({filename:'madar-ledger-movements-'+
      formatAccountingJalali(today,{digits:'ascii'}).replace(/\//g,'-')+'.csv',
      blob:new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'})});
    setState(p=>({...p,error:'',notice:'خروجی CSV گردش‌های فیلترشده آماده شد.'}));
  };
  const exportPeriodSummary=()=>{
    if(!periodReport||periodReport.error)return;
    const columns=['کد حساب','عنوان','مانده افتتاحیه بدهکار','مانده افتتاحیه بستانکار',
      'گردش بدهکار','گردش بستانکار','مانده پایان بدهکار','مانده پایان بستانکار'];
    const body=periodReport.rows.map(a=>[a.accountId,a.name,
      a.openingDebit,a.openingCredit,a.debitMovement,a.creditMovement,
      a.closingDebit,a.closingCredit]);
    const csv=[['از تاریخ شمسی',displayAccountingDate(reportFrom)||'ابتدای دفتر',
      'تا تاریخ شمسی',displayAccountingDate(reportTo)||'آخرین سند','واحد',unitLabel],
      columns,...body].map(r=>r.map(csvField).join(',')).join('\r\n');
    downloadStandaloneBlob({filename:'madar-account-period-'+
      formatAccountingJalali(today,{digits:'ascii'}).replace(/\//g,'-')+'.csv',
      blob:new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'})});
    setState(p=>({...p,error:'',notice:'خروجی مانده اول دوره و پایان دوره آماده شد.'}));
  };
  const suggestedInvoiceId=nextAccountingNumber(view?.invoices||{},'INV',
    formatAccountingJalali(today,{digits:'ascii'}).slice(0,4));
  const hasUnsavedInvoice=Boolean(editTarget||correctionTarget||
    (forms.document.documentId.trim()&&forms.document.documentId!==suggestedInvoiceId)||
    forms.document.partyId||forms.document.note.trim()||forms.document.dueDate||
    forms.document.discount!=='0'||forms.document.tax!=='0'||
    forms.document.taxRuleId||forms.document.documentDate!==today||
    rows.length!==1||rows.some(row=>row.description.trim()||
      String(row.unitPrice).trim()||row.quantity!=='1'||row.accountId||row.itemId));
  const hasUnsavedProforma=Boolean(proformaEditing||
    forms.proforma.proformaId.trim()||forms.proforma.partyId||
    forms.proforma.note.trim()||forms.proforma.validUntil||
    forms.proforma.discount!=='0'||forms.proforma.tax!=='0'||
    forms.proforma.documentDate!==today||
    proformaRows.length!==1||proformaRows.some(row=>row.description.trim()||
      String(row.unitPrice).trim()||row.quantity!=='1'||row.accountId||row.itemId));
  const changedFields=group=>Object.entries(DEFAULTS[group]).some(([field,baseline])=>
    forms[group]?.[field]!==(
      ['postingDate','documentDate','throughDate'].includes(field)?today:baseline));
  const hasActiveChildDraft=()=>Boolean(
    (tab==='cash'&&childDraftsLive.current['bank-reconciliation'])||
    (tab==='settlements'&&childDraftsLive.current.installments)||
    (tab==='items'&&childDraftsLive.current.inventory)||
    (['cheques','payroll','period','company'].includes(tab)&&
      childDraftsLive.current[tab]));
  const hasUnsavedOtherEditor=Boolean(
    (tab==='parties'&&(changedFields('party')||partyEditing||partyEditReason.trim()||
      historicalReceipt.debtorId||historicalReceipt.bankId||
      historicalReceipt.amount||historicalReceipt.note.trim()||
      historicalReceipt.postingDate!==today))||
    (tab==='items'&&changedFields('item'))||
    (tab==='accounts'&&changedFields('account'))||
    (tab==='settlements'&&(changedFields('settlement')||childDrafts.installments))||
    (tab==='cash'&&(changedFields('deposit')||changedFields('transfer')||
      childDrafts['bank-reconciliation']))||
    (tab==='journal'&&(changedFields('manual')||changedFields('reverse')||
      manualRows.length!==2||manualRows.some(row=>row.accountId||
        row.debit!=='0'||row.credit!=='0'))));
  // The purchase form is always present on the bill tab, while the sale form
  // exists only when its composer is open. Protect editable proformas too:
  // they have their own rows and are not issued ledger documents.
  const hasUnsavedFinancialEditor=(hasUnsavedInvoice&&
    (tab==='bill'||(tab==='invoice'&&invoiceComposerOpen)))||
    (tab==='proforma'&&hasUnsavedProforma)||hasUnsavedOtherEditor||
    hasActiveChildDraft();
  const discardOtherEditor=()=>{
    if(tab==='parties'){
      reset('party');setPartyEditing('');setPartyEditReason('');
      setHistoricalReceipt({debtorId:'',bankId:'',amount:'',postingDate:today,note:''});
    }else if(tab==='items')reset('item');
    else if(tab==='accounts')reset('account');
    else if(tab==='settlements')reset('settlement');
    else if(tab==='cash'){
      reset('deposit');reset('transfer');
    }else if(tab==='journal'){
      reset('manual');reset('reverse');
      setManualRows([makeJournalLine(),makeJournalLine()]);
    }
  };
  // The Windows titlebar X cannot call the React navigation handler directly.
  // The native host first vetoes close, then calls this synchronously from a
  // worker thread. Never bypass confirmation when an editor contains changes.
  useEffect(()=>{
    const abortNativeClose=()=>{
      nativeClosePending.current=false;
      const root=document.querySelector('.sac-root');
      root?.removeAttribute('inert');
      root?.removeAttribute('aria-busy');
      return true;
    };
    const confirmNativeClose=()=>{
      if(nativeClosePending.current)return false;
      if(locked.current||busy||pendingRetry||state.loading){
        window.alert('عملیات مالی هنوز در حال انجام است. پس از پایان عملیات دوباره برای خروج اقدام کنید.');
        return false;
      }
      const accepted=!(hasUnsavedFinancialEditor||hasActiveChildDraft())||window.confirm(
        'اطلاعات این فرم حسابداری هنوز ذخیره نشده است. پنجره را ببندیم و تغییرات را کنار بگذاریم؟');
      if(!accepted)return false;
      // The native host verifies the final backup BEFORE it destroys this
      // WebView. Freeze edits synchronously so newer input cannot be lost
      // between the JS confirmation and the eventual native close.
      nativeClosePending.current=true;
      const root=document.querySelector('.sac-root');
      root?.setAttribute('inert','');
      root?.setAttribute('aria-busy','true');
      return true;
    };
    window.__madarAccountingConfirmNativeClose=confirmNativeClose;
    window.__madarAccountingAbortNativeClose=abortNativeClose;
    return()=>{
      if(window.__madarAccountingConfirmNativeClose===confirmNativeClose)
        delete window.__madarAccountingConfirmNativeClose;
      if(window.__madarAccountingAbortNativeClose===abortNativeClose)
        delete window.__madarAccountingAbortNativeClose;
    };
  },[busy,pendingRetry,state.loading,hasUnsavedFinancialEditor,tab]);
  const closeInvoiceComposer=({force=false}={})=>{
    if(!force&&hasUnsavedInvoice&&!window.confirm(
      'اطلاعات واردشده در فاکتور هنوز ذخیره نشده است. بدون ذخیره به فهرست بازگردیم؟'))return false;
    setInvoiceComposerOpen(false);setEditTarget('');setCorrectionTarget('');
    setCorrectionReason('');setPartyQuery('');setRows([makeLine()]);reset('document');
    setInvoiceWizardStep(0);setInvoiceWizardChecked({});setInvoiceWizardError('');
    return true;
  };
  const requestExit=()=>{
    if(busy||pendingRetry||state.loading)return false;
    // Exit is a different path from gotoTab and must not silently discard a
    // new invoice, edited draft or pending issued-invoice correction.
    // Do not reset the composer before the native host accepts the exit.
    if((hasUnsavedFinancialEditor||hasActiveChildDraft())&&
       !window.confirm('اطلاعات فرم فعلی هنوز ذخیره نشده است. از حسابداری خارج شویم و این تغییرات را کنار بگذاریم؟'))
      return false;
    onExit();
    return true;
  };
  const requestCompanySwitch=()=>{
    if(locked.current||busy||pendingRetry||state.loading||nativeClosePending.current)return false;
    if((hasUnsavedFinancialEditor||hasActiveChildDraft())&&
      !window.confirm('فرم حسابداری هنوز ذخیره نشده است. تغییرات را کنار بگذاریم و شرکت را تغییر دهیم؟'))
      return false;
    return typeof onSwitchCompany==='function'?onSwitchCompany():false;
  };
  const gotoTab=name=>{
    if(busy||pendingRetry)return false;
    // Re-selecting the purchase section is not a request to discard its form.
    // Clearing correctionTarget here silently changed bill.correct to create.
    if(name===tab&&name==='bill')return true;
    if(name===tab&&name==='proforma')return true;
    if(name===tab&&name==='invoice'&&invoiceComposerOpen){
      return closeInvoiceComposer();
    }
    if(name!==tab&&tab==='invoice'&&invoiceComposerOpen&&!closeInvoiceComposer())return false;
    if(name!==tab&&tab==='bill'&&hasUnsavedFinancialEditor){
      if(!window.confirm('اطلاعات صورتحساب خرید هنوز ذخیره نشده است. بدون ذخیره به بخش دیگری برویم؟'))
        return false;
      reset('document');setRows([makeLine()]);
    }
    if(name!==tab&&tab==='proforma'&&hasUnsavedProforma){
      if(!window.confirm('پیش‌فاکتور هنوز ذخیره نشده است. تغییرات آن را کنار بگذاریم؟'))
        return false;
      reset('proforma');setProformaRows([makeLine()]);setProformaEditing('');
    }
    if(name!==tab&&(hasUnsavedOtherEditor||hasActiveChildDraft())){
      if(!window.confirm('فرم فعلی هنوز ذخیره نشده است. تغییرات را کنار بگذاریم و به بخش دیگری برویم؟'))
        return false;
      discardOtherEditor();
    }
    if(name!==tab)setInvoiceComposerOpen(false);
    setSearchTarget(null);
    setTab(name);setCancelTarget('');setEditTarget('');
    setDetailTarget('');setReopenReason('');setCorrectionTarget('');
    setCorrectionReason('');setReturnTarget('');setReturnReason('');
    setReturnMode('full');setReturnQuantities({});
    setPartyEditing('');setPartyEditReason('');
    setProformaEditing('');return true;};
  /** A global search hit opens only records already supplied by the host for this company.
   * The same unsaved-invoice guard applies to record navigation as to menu clicks. */
  const openSearchRecord=({kind,id,tab:destination})=>{
    const locations={invoice:['invoices','invoice'],bill:['bills','bill'],
      proforma:['proformas','proforma'],party:['parties','parties'],
      account:['accounts','accounts'],journal:['journals','journal'],
      receipt:['receipts','settlements'],payment:['payments','settlements']};
    const spec=locations[kind];
    if(!spec||destination!==spec[1]||!validId(id)||!view||
      state.loading||state.error)return false;
    const collection=view?.[spec[0]];
    const record=Array.isArray(collection)?collection.find(item=>item?.id===id):
      collection&&typeof collection==='object'?collection[id]:null;
    if(!record||!gotoTab(destination))return false;
    if(kind==='invoice'||kind==='bill')setDetailTarget(id);
    else if(kind==='account'){setAccountFilter(id);setSelectedHistoricAccount(id);}
    else if(['party','journal','receipt','payment'].includes(kind))
      setSearchTarget({kind,id,token:++searchSequence.current});
    else if(kind==='receipt'||kind==='payment'){
      setForms(old=>({...old,settlement:{...old.settlement,
        kind:kind==='payment'?'payment':'receipt',documentId:''}}));
    }
    return true;
  };
  const quickAccountingAction=action=>{
    if(action==='purchase'){if(canManage||canDraft)gotoTab('bill');}
    else if(action==='payment'&&canManage&&gotoTab('settlements')){
      setForms(old=>({...old,settlement:{...old.settlement,
        kind:'payment',documentId:''}}));
    }
  };
  const openQuickInvoice=()=>{
    if(busy||pendingRetry||state.loading)return false;
    // The global "new sale" shortcut is available while editing a purchase
    // bill too. It must not bypass the bill/invoice unsaved-draft guard.
    if((hasUnsavedFinancialEditor||hasActiveChildDraft())&&
      !window.confirm('سند فعلی هنوز ذخیره نشده است. از تغییرات آن صرف‌نظر کنیم و فاکتور فروش تازه باز کنیم؟'))
      return false;
    if(tab==='proforma'&&hasUnsavedProforma){
      reset('proforma');setProformaRows([makeLine()]);setProformaEditing('');
    }
    if(hasUnsavedOtherEditor)discardOtherEditor();
    setForms(p=>({...p,document:{...DEFAULTS.document,documentDate:today,
      documentId:suggestedInvoiceId}}));
    setRows([makeLine()]);setEditTarget('');setCorrectionTarget('');
    setPartyQuery('');
    setCorrectionReason('');setInvoiceComposerOpen(true);setTab('invoice');
    setInvoiceWizardStep(0);setInvoiceWizardChecked({});setInvoiceWizardError('');
    return true;
  };
  useEffect(()=>{
    if(tab!=='invoice'||!invoiceComposerOpen)return;
    window.requestAnimationFrame(()=>{
      document.querySelector('.sac-invoice-editor input[aria-label="جست‌وجوی مشتری یا تأمین‌کننده"]')?.focus();
    });
  },[tab,invoiceComposerOpen]);
  useEffect(()=>{document.querySelector('.sac-body')?.scrollTo({top:0,behavior:'instant'});},[tab]);
  useEffect(()=>{
    if(tab==='accounts'&&selectedHistoricAccount)
      document.querySelector('#sac-account-movements')?.scrollIntoView({
        block:'start',behavior:'instant'});
  },[tab,selectedHistoricAccount]);
  const f=(group,key,value)=>{
    if(locked.current||pendingRetry||nativeClosePending.current)return;
    setForms(p=>({...p,[group]:{...p[group],[key]:value}}));
  };
  const reset=group=>setForms(p=>({...p,[group]:{...DEFAULTS[group],
    ...(['document','proforma'].includes(group)?{documentDate:today}:{}),
    ...(group==='close'?{throughDate:today}:{}),
    ...(['settlement','deposit','transfer','manual','reverse'].includes(group)?{postingDate:today}:{}),
  }}));
  const refresh=useCallback(async()=>{
    if(locked.current)return;
    const n=++request.current;
    // Never keep a previous host-authorized ledger searchable after a read failure
    // or company/role switch. Revalidate before exposing any row or deep-link.
    latest.current=null;setSnapshot(null);setSearchTarget(null);setDetailTarget('');
    setState(p=>({...p,loading:true,error:''}));
    try{
      if(typeof api?.standaloneAccountingRead!=='function')
        throw new Error('مسیر خواندن حسابداری مستقل در میزبان موجود نیست.');
      const result=validateStandaloneResponse(await api.standaloneAccountingRead());
      if(!live.current||n!==request.current)return;
      latest.current=result;setSnapshot(result);
      setState({loading:false,error:'',notice:'اطلاعات دفترکل از میزبان دریافت شد.'});
      return result;
    }catch(err){if(live.current&&n===request.current){
      latest.current=null;
      setSnapshot(null);
      setState({loading:false,
        error:err?.message||'خواندن دفترکل ناموفق بود.',notice:''});
    }}
    return null;
  },[api]);
  const requestManualRefresh=()=>{
    if(locked.current||busy||pendingRetry||nativeClosePending.current)return false;
    // refresh() removes the whole host-authorized view before the read, which
    // also unmounts nested local-only editors. Never silently discard an
    // unposted finance draft when the operator asks for a manual refresh.
    if(hasUnsavedFinancialEditor||hasActiveChildDraft()){
      if(!window.confirm('بازخوانی دفتر، فرم مالی ذخیره‌نشده را کنار می‌گذارد. تغییرات را دور بریزیم؟'))
        return false;
      discardOtherEditor();
      if(tab==='bill'){reset('document');setRows([makeLine()]);}
      if(tab==='proforma'){
        reset('proforma');setProformaRows([makeLine()]);setProformaEditing('');
      }
    }
    return refresh();
  };
  useEffect(()=>{live.current=true;void refresh();return()=>{live.current=false;request.current++;};},[refresh]);
  const send=async(command,message='ثبت در دفترکل میزبان انجام شد.')=>{
    const drafting=new Set(['party.register','invoice.create','bill.create',
      'proforma.create','proforma.update']);
    if(!(canManage||(canDraft&&drafting.has(command?.type)))||
      locked.current||nativeClosePending.current||!latest.current)return false;
    if(pending.current&&pending.current!==command){
      setState(p=>({...p,error:'ابتدا نتیجه عملیات قبلی را با همان شناسه بازیابی کنید.'}));
      return false;
    }
    if(!command||!validId(command.eventId)||!validText(command.type,50)){
      setState(p=>({...p,error:'فرمان حسابداری معتبر نیست.'}));return false;}
    locked.current=true;setBusy(true);++request.current;
    setState({loading:false,error:'',notice:''});
    try{
      if(typeof api?.standaloneAccountingCommand!=='function')
        throw new Error('مسیر ثبت حسابداری مستقل در میزبان موجود نیست.');
      const payload=await api.standaloneAccountingCommand({
        command,expectedRevision:latest.current.revision});
      const result=validateStandaloneResponse(payload);
      if(live.current){
        latest.current=result;setSnapshot(result);
        setState({loading:false,error:'',notice:message});
      }
      pending.current=null;if(live.current)setPendingRetry(false);
      return true;
    }catch(err){
      const conflict=isConflict(err);
      if(!conflict||pending.current){
        pending.current=command;
        if(live.current)setPendingRetry(true);
      }
      let synced=false;
      if(conflict&&typeof api?.standaloneAccountingRead==='function'){
        try{
          const current=validateStandaloneResponse(await api.standaloneAccountingRead());
          if(live.current){latest.current=current;setSnapshot(current);synced=true;}
        }catch(_ignored){/* Keep the draft. Explicit refresh remains available. */}
      }
      if(live.current)setState({loading:false,
        error:err?.message||'نتیجه ثبت نامشخص است؛ قبل از تلاش دوباره بازخوانی کنید.',
        notice:conflict?(synced?
          'تعارض نسخه: داده تازه بازخوانی شد. فرم ارسال نشده است؛ قبل از ثبت دوباره بررسی کنید.':
          'تعارض نسخه: بازخوانی ناموفق بود. ابتدا داده‌های دفتر را بازخوانی کنید.'):
          'ممکن است فرمان در میزبان اجرا شده باشد. قبل از تکرار، بازخوانی کنید.'});
      return false;
    }finally{locked.current=false;if(live.current)setBusy(false);}
  };
  const retryUncertain=async()=>{
    if(!pending.current||locked.current)return;
    const saved=pending.current;
    // The same eventId/payload must survive a lost response, never generate
    // a second funding, payment or manual journal event accidentally.
    const current=await refresh();
    if(current&&live.current)await send(saved,'نتیجه عملیات قبلی با همان شناسه تأیید شد.');
  };
  const execute=async(builder,message)=>{
    if((!canManage&&!canDraft)||busy||!view)return false;
    if(pending.current){
      setState(p=>({...p,error:'عملیات قبلی هنوز نتیجه قطعی ندارد. ابتدا همان شناسه را بازیابی کنید.'}));
      return false;
    }
    try{
      const out=builder(newId());
      if(out.error){setState(p=>({...p,error:out.error,notice:''}));return false;}
      if(!canManage&&(!canDraft||!['party.register','invoice.create','bill.create',
        'proforma.create','proforma.update'].includes(out.command?.type))){
        setState(p=>({...p,error:'دسترسی شما فقط به ثبت پیش‌نویس و شخص جدید محدود است.'}));
        return false;
      }
      return await send(out.command,message);
    }catch(err){setState(p=>({...p,error:err?.message||'فرمان معتبر نیست.'}));return false;}
  };
  const submit=fn=>e=>{e.preventDefault();if(!busy)void fn();};
  const textInput=(group,name,hint='',maxLength=300)=>
    <input required maxLength={maxLength} placeholder={hint} value={forms[group][name]}
      onChange={e=>f(group,name,e.target.value)}/>;
  const idInput=(group,name,hint='')=><div className="sac-id-input">
    <input required dir="ltr" maxLength={96} placeholder={hint}
      disabled={busy||pendingRetry}
      value={forms[group][name]} onChange={e=>f(group,name,e.target.value)}/>
    {(group==='document'||group==='proforma')&&<button type="button"
      disabled={busy} onClick={()=>{
        const ledger=group==='proforma'?view?.proformas:
          tab==='bill'?view?.bills:view?.invoices;
        const prefix=group==='proforma'?'PF':tab==='bill'?'BILL':'INV';
        const solarYear=formatAccountingJalali(forms[group].documentDate||today,
          {digits:'ascii'}).slice(0,4);
        const value=nextAccountingNumber(ledger,prefix,solarYear);
        if(value)f(group,name,value);
      }}>شماره خودکار</button>}
  </div>;
  const amountInput=(group,name)=><input required dir="ltr" inputMode="numeric"
    value={forms[group][name]} onChange={e=>f(group,name,e.target.value)}/>;
  const dateInput=(group,name)=><AccountingJalaliField max={today}
    value={forms[group][name]} onChange={iso=>f(group,name,iso)}/>;
  const options=(collection,placeholder)=><><option value="">{placeholder}</option>
    {collection.map(o=><option key={o.id} value={o.id}>{o.name||o.id} ({o.id})</option>)}</>;
  const accountSelect=(group,name,choices=activeCash)=><select required value={forms[group][name]}
    onChange={e=>f(group,name,e.target.value)}>{options(choices,'انتخاب حساب')}</select>;
  const docKind=tab==='bill'?'bill':'invoice',currentDocs=view?.[tab==='bill'?'bills':'invoices']||{};
  const filteredInvoiceDocs=useMemo(()=>tab==='invoice'?
    filterInvoiceRows(currentDocs,parties,invoiceListSearch,invoiceListStatus):
    sortMap(currentDocs),[tab,currentDocs,parties,invoiceListSearch,invoiceListStatus]);
  const invoiceCounts=useMemo(()=>invoiceStatusCounts(view?.invoices||{}),[view?.invoices]);
  const detailedDocument=currentDocs[detailTarget]||null;
  const returnedLines=useMemo(()=>{
    const result={};
    if(!detailedDocument)return result;
    if(Array.isArray(detailedDocument.returnedQuantities))
      return Object.fromEntries(detailedDocument.returnedQuantities.map(
        (quantity,index)=>[index,quantity]));
    for(const ret of Object.values(view?.returns||{})){
      if(ret.documentId!==detailedDocument.id||
        ret.direction!==(docKind==='invoice'?'sale':'purchase'))continue;
      for(const line of ret.lines||[]){
        if(Number.isSafeInteger(line.lineIndex)&&Number.isSafeInteger(line.quantity))
          result[line.lineIndex]=(result[line.lineIndex]||0)+line.quantity;
      }
    }
    return result;
  },[view?.returns,detailedDocument,docKind]);
  const customers=sortMap(parties).filter(p=>['customer','both'].includes(p.kind));
  const vendors=sortMap(parties).filter(p=>['vendor','both'].includes(p.kind));
  const candidates=sortMap(accounts).filter(a=>a.kind===(docKind==='invoice'?'revenue':'expense'));
  const available=outstandingStandaloneDocuments(view,forms.settlement.kind);
  const selected=available.find(d=>d.id===forms.settlement.documentId);
  const stat=useMemo(()=>{
    if(!view)return null;
    const open=kind=>Object.values(view[kind]).reduce((s,d)=>
      s+(d.status==='issued'?
        Math.max(0,d.total-d.allocated-(d.returnedAmount||0)):0),0);
    return {receivable:open('invoices'),payable:open('bills'),
      liquid:Object.values(view.accounts).filter(a=>a.liquid).reduce((s,a)=>s+a.debitMinusCredit,0),
      count:Object.values(view.invoices).filter(x=>x.status==='issued').length+
        Object.values(view.bills).filter(x=>x.status==='issued').length};
  },[view]);
  const validPostingDate=d=>validStandaloneDate(d,today)&&(!view.closedThrough||d>view.closedThrough);
  const rowUpdate=(idx,key,val)=>{
    if(locked.current||pendingRetry)return;
    setRows(p=>p.map((l,i)=>i===idx?{...l,[key]:val}:l));
  };
  const focusInvoiceCell=(index,column=0)=>{
    window.requestAnimationFrame(()=>{
      document.querySelector(`.sac-invoice-editor [data-invoice-row="${index}"][data-invoice-col="${column}"]`)?.focus();
    });
  };
  const addInvoiceRow=(clone=null)=>{
    if(locked.current||pendingRetry||rows.length>=1000)return;
    setRows(p=>[...p,clone?{...clone}:makeLine()]);
    focusInvoiceCell(rows.length,0);
  };
  const removeInvoiceRow=index=>{
    if(locked.current||pendingRetry||rows.length<2)return;
    setRows(p=>p.filter((_,i)=>i!==index));
    focusInvoiceCell(Math.max(0,Math.min(index,rows.length-2)),0);
  };
  const invoiceKeyDown=e=>{
    if(e.isComposing||e.keyCode===229||busy||pendingRetry)return;
    const target=e.target.closest?.('[data-invoice-row]');
    if(!target)return;
    const index=Number(target.dataset.invoiceRow),col=Number(target.dataset.invoiceCol);
    if(e.ctrlKey&&e.key==='Insert'){
      e.preventDefault();addInvoiceRow();return;
    }
    if(e.altKey&&e.shiftKey&&e.key.toLowerCase()==='d'){
      e.preventDefault();addInvoiceRow(rows[index]);return;
    }
    if(e.ctrlKey&&e.key==='Delete'){
      e.preventDefault();removeInvoiceRow(index);return;
    }
    if(e.key==='Enter'&&!e.shiftKey&&!e.altKey&&!e.ctrlKey){
      e.preventDefault();
      const advancedVisible=e.currentTarget.querySelector('.sac-row-advanced')?.open;
      if(col===4||(col===2&&!advancedVisible)){
        if(index===rows.length-1)addInvoiceRow();
        else focusInvoiceCell(index+1,0);
      }else focusInvoiceCell(index,col+1);
    }
  };
  const manualUpdate=(idx,key,val)=>{
    if(locked.current||pendingRetry||nativeClosePending.current)return;
    setManualRows(p=>p.map((l,i)=>i===idx?{...l,[key]:val}:l));
  };
  const updateProformaRows=mutate=>{
    if(locked.current||busy||pendingRetry||nativeClosePending.current)return;
    setProformaRows(previous=>{
      if(locked.current||nativeClosePending.current)return previous;
      return mutate(previous);
    });
  };
  const updateManualRows=mutate=>{
    if(locked.current||busy||pendingRetry||nativeClosePending.current)return;
    setManualRows(previous=>{
      if(locked.current||nativeClosePending.current)return previous;
      return mutate(previous);
    });
  };
  const blocked=!canManage||busy||pendingRetry||nativeClosePending.current;
  const draftBlocked=(!canManage&&!canDraft)||busy||pendingRetry||nativeClosePending.current;
  const wizardEnabled=tab==='invoice'&&invoiceComposerOpen&&invoiceWizardMode==='guided';
  const wizardIssues=invoiceWizardIssues({document:forms.document,rows,
    accounts,items,today,kind:docKind,tax:documentTax,
    correctionTarget,correctionReason,correctionDate});
  const showWizardStep=(index,{keepError=false}={})=>{
    setInvoiceWizardStep(index);if(!keepError)setInvoiceWizardError('');
    window.requestAnimationFrame(()=>{
      document.querySelector('.sac-body')?.scrollTo({top:0,behavior:'instant'});
      document.getElementById('sac-wizard-panel-'+INVOICE_WIZARD_STEPS[index].id)
        ?.querySelector('input:not([type=hidden]),select,textarea,button')?.focus();
    });
  };
  const goWizardStep=index=>{
    if(busy||pendingRetry||index<0||index>=INVOICE_WIZARD_STEPS.length)return;
    if(index>invoiceWizardStep){
      const checked={...invoiceWizardChecked};
      for(let i=0;i<index;i++){
        checked[i]=true;
        if(wizardIssues[i]){
          setInvoiceWizardChecked(checked);setInvoiceWizardError(wizardIssues[i]);
          showWizardStep(i,{keepError:true});return;
        }
      }
      setInvoiceWizardChecked(checked);
    }
    showWizardStep(index);
  };
  const validateInvoiceSubmission=()=>{
    if(wizardEnabled){
      setInvoiceWizardChecked({0:true,1:true,2:true,3:true});
      const index=wizardIssues.findIndex(Boolean);
      if(index!==-1){
        setInvoiceWizardError(wizardIssues[index]);showWizardStep(index,{keepError:true});
        return false;
      }
    }
    const preflight=buildStandaloneInvoiceCommand({
      kind:docKind,...forms.document,tax:documentTax,
      documentId:editTarget||forms.document.documentId,lines:rows,
      eventId:'UX-INVOICE-PREFLIGHT',accounts,items,today,
    });
    if(preflight.error){
      setInvoiceWizardError(preflight.error);
      if(wizardEnabled)showWizardStep(4,{keepError:true});
      return false;
    }
    if(correctionTarget&&!window.confirm(
      'این اصلاحیه سند قطعی قبلی را برگشت می‌دهد و پیش‌نویس جایگزین می‌سازد. '+
      'پس از ثبت، سند اصلی قابل ویرایش مستقیم نیست. ادامه می‌دهید؟'))return false;
    setInvoiceWizardError('');
    return true;
  };
  const confirmEditorReplacement=()=>{
    if(busy||pendingRetry||state.loading)return false;
    return !hasUnsavedFinancialEditor||window.confirm(
      'اطلاعات سند فعلی هنوز ذخیره نشده است. تغییرات را کنار بگذاریم و سند دیگری را باز کنیم؟');
  };
  const startEditingDocument=(d,{discardConfirmed=false}={})=>{
    if(!discardConfirmed&&!confirmEditorReplacement())return false;
    setInvoiceComposerOpen(true);
    setInvoiceWizardStep(0);setInvoiceWizardChecked({});setInvoiceWizardError('');
    setEditTarget(d.id);
    setCorrectionTarget('');
    setForms(p=>({...p,document:{
      documentId:d.id,partyId:d.partyId,documentDate:d.documentDate,
      dueDate:d.dueDate||'',note:d.note||'',discount:String(d.discount),tax:String(d.tax),
      taxRuleId:d.taxRuleId||''}}));
    setRows(d.lines.map(l=>({description:l.description,
      quantity:String(l.quantity),unitPrice:String(l.unitPrice),
      accountId:l.accountId||'',itemId:l.itemId||''})));
    return true;
  };
  const startCorrectingDocument=d=>{
    if(!confirmEditorReplacement())return false;
    setInvoiceComposerOpen(true);
    setInvoiceWizardStep(0);setInvoiceWizardChecked({});setInvoiceWizardError('');
    const prefix=(docKind==='invoice'?'INV':'BILL')+'-COR';
    const year=formatAccountingJalali(today,{digits:'ascii'}).slice(0,4);
    const newNumber=nextAccountingNumber(currentDocs,prefix,year);
    setEditTarget('');setCorrectionTarget(d.id);
    setCorrectionReason('');setCorrectionDate(today);
    setForms(p=>({...p,document:{
      documentId:newNumber,partyId:d.partyId,documentDate:today,
      dueDate:d.dueDate&&d.dueDate>=today?d.dueDate:'',note:d.note||'',
      discount:String(d.discount),tax:String(d.tax),
      taxRuleId:d.taxRuleId||''}}));
    setRows(d.lines.map(l=>({description:l.description,quantity:String(l.quantity),
      unitPrice:String(l.unitPrice),accountId:l.accountId||'',itemId:l.itemId||''})));
    return true;
  };
  const exportDocument=async(doc,format,kind=docKind)=>{
    try{
      const useParsian=kind==='invoice'&&invoicePrintLayout==='parsian-karma'&&ledgerCurrency==='RIAL';
      const common={kind,doc,party:parties[doc.partyId]?.name||doc.partyId,
        company:printCompanyProfile,currency:ledgerCurrency,pattern:filenamePattern,format};
      const output=['xlsx','rtf'].includes(format)?
        await buildAccountingStructuredExport(common):
        (invoicePrintLayout==='custom'&&kind==='invoice')?
        await buildCustomPrintExport({...common,template:validatePrintTemplate(printTemplate)}):
        useParsian?await buildParsianKarmaDocumentExport({
        kind,doc,party:parties[doc.partyId]?.name||doc.partyId,
        format,company:printCompanyProfile,
        sourceNumber:doc.sourceType==='parsian-test-copy'?
          (doc.sourceId?.match(/factor(\d+)/)?.[1]||doc.number||doc.id):
          (doc.number||doc.id),
      }):await buildStandaloneDocumentExport({
        kind,doc,party:parties[doc.partyId]?.name||doc.partyId,
        pattern:filenamePattern,format,currency:ledgerCurrency,
        company:printCompanyProfile});
      downloadStandaloneBlob(output);
      setState(p=>({...p,error:'',notice:'دانلود '+output.filename+' در مرورگر درخواست شد؛ ذخیره نهایی به مرورگر بستگی دارد.'}));
    }catch(err){setState(p=>({...p,error:err.message||'خروجی سند ناموفق بود.',notice:''}));}
  };
  const exportInvoiceEntryTemplate=()=>{
    try{
      const entry=buildAccountingInvoiceEntryTemplate(rows,{
        currency:ledgerCurrency,title:invoiceTemplateTitle});
      downloadStandaloneBlob({
        filename:'madar-invoice-rows-'+ledgerCurrency+'-'+
          formatAccountingJalali(today,{digits:'ascii'}).replace(/\//g,'-')+'.json',
        blob:new Blob([JSON.stringify(entry,null,2)],{type:'application/json;charset=utf-8'}),
      });
      setState(p=>({...p,error:'',
        notice:'قالب اقلام برای ذخیره در فایل JSON ارسال شد؛ برای استفاده مجدد آن را فراخوانی کنید.'}));
    }catch(err){
      setState(p=>({...p,error:err.message||'ذخیره قالب ناموفق بود.',notice:''}));
    }
  };
  const importInvoiceEntryTemplate=async(file)=>{
    if(!file)return;
    try{
      if(file.size>1048576)throw new Error('حجم فایل قالب از یک مگابایت بیشتر است.');
      const template=parseAccountingInvoiceEntryTemplate(await file.text(),{
        currency:ledgerCurrency});
      if(template.lines.some(row=>row.accountId&&!accounts[row.accountId]))
        throw new Error('یک سرفصل در قالب واردشده در دفتر فعلی وجود ندارد.');
      if(template.lines.some(row=>row.itemId&&!items[row.itemId]))
        throw new Error('یک قلم کاتالوگ در قالب واردشده در دفتر فعلی وجود ندارد.');
      if(invoiceTemplateImportMode==='append'&&rows.length+template.lines.length>1000)
        throw new Error('جمع تعداد ردیف‌ها از حد مجاز بیشتر است.');
      const imported=invoiceTemplateImportMode==='append'?
        [...rows,...template.lines]:template.lines;
      setRows(imported);
      setState(p=>({...p,error:'',notice:'قالب «'+template.title+
        '» به فرم اضافه شد. هیچ سند مالی ثبت نشده؛ برای ذخیره فاکتور باید «ثبت پیش‌نویس» را بزنید.'}));
    }catch(err){
      setState(p=>({...p,error:err.message||'فراخوانی قالب ناموفق بود.',notice:''}));
    }
  };
  const loadEntryFromLibrary=template=>{
    try{
      const parsed=parseAccountingInvoiceEntryTemplate(JSON.stringify(template.data),{
        currency:ledgerCurrency});
      if(parsed.lines.some(line=>(line.accountId&&!accounts[line.accountId])||
        (line.itemId&&!items[line.itemId])))throw Error('شناسه قلم یا سرفصل قالب متعلق به این دفتر نیست.');
      if(invoiceTemplateImportMode==='append'&&rows.length+parsed.lines.length>1000)
        throw Error('تعداد ردیف‌های فرم از هزار بیشتر می‌شود.');
      setRows(invoiceTemplateImportMode==='append'?[...rows,...parsed.lines]:parsed.lines);
      setInvoiceTemplateTitle(template.title);setEntryTemplateId(template.id);
      setState(p=>({...p,error:'',notice:'قالب اقلام باز شد؛ هیچ سند مالی ثبت نشده است.'}));
    }catch(err){setState(p=>({...p,error:err.message,notice:''}));}
  };
  const saveTemplateToLibrary=async kind=>{
    if(!templateBridge)return;
    try{
      const data=kind==='entry'?buildAccountingInvoiceEntryTemplate(rows,{
        currency:ledgerCurrency,title:invoiceTemplateTitle}):kind==='print'?
        validatePrintTemplate(printTemplate):{format:'madar-issuer-profile-v1',profile:{...issuerProfile}};
      const title=kind==='entry'?invoiceTemplateTitle:kind==='print'?
        printTemplate.title:issuerProfile.legalName;
      const id=kind==='entry'?entryTemplateId:kind==='print'?printTemplateId:issuerId;
      const saved=await api.standaloneAccountingTemplateSave(kind,title,data,id);
      if(kind==='entry')setEntryTemplateId(saved.id);
      else if(kind==='print')setPrintTemplateId(saved.id);
      else setIssuerId(saved.id);
      await loadTemplateLibraries();
      setState(p=>({...p,error:'',notice:'قالب «'+title+'» در کتابخانه خصوصی این دفتر ذخیره شد.'}));
    }catch(err){setState(p=>({...p,error:'ذخیره قالب: '+err.message,notice:''}));}
  };
  const libraryAction=async(kind,action,id)=>{
    if(!templateBridge||!id)return;
    try{
      if(action==='delete'){
        await api.standaloneAccountingTemplateDelete(kind,id);
        if(kind==='entry')setEntryTemplateId('');
        else if(kind==='print')setPrintTemplateId('');
        else setIssuerId('');
      }else if(action==='default')await api.standaloneAccountingTemplateDefault(kind,id);
      else if(action==='duplicate'){
        const saved=await api.standaloneAccountingTemplateDuplicate(kind,id);
        if(kind==='entry')setEntryTemplateId(saved.id);
        else if(kind==='print')setPrintTemplateId(saved.id);
        else setIssuerId(saved.id);
      }
      await loadTemplateLibraries();
      setState(p=>({...p,error:'',notice:'عملیات کتابخانه انجام شد.'}));
    }catch(err){setState(p=>({...p,error:err.message,notice:''}));}
  };

  return <div dir="rtl" className={'sac-root'+(tab==='invoice'?' sac-invoice-work-mode':
    tab==='overview'?' sac-overview-work-mode sac-vtr-overview':'')+
    (wizardEnabled?' sac-invoice-wizard-guided':'')}
    aria-label="تراز، برنامه مستقل حسابداری">
    <AccountingTopRibbon tab={tab} sections={SECTIONS}
      searchView={view} onSearchSelect={openSearchRecord}
      onQuickAction={quickAccountingAction}
      onNavigate={gotoTab} onNewInvoice={openQuickInvoice}
      onBack={()=>tab==='invoice'&&invoiceComposerOpen?
        closeInvoiceComposer():gotoTab('overview')}
      backLabel={tab==='invoice'&&invoiceComposerOpen?'بازگشت به فاکتورها':'بازگشت به صفحه اصلی'}
      onPrint={()=>detailedDocument&&void exportDocument(detailedDocument,'pdf','invoice')}
      hasPrintableInvoice={tab==='invoice'&&!!detailedDocument}
      canManage={canManage} canDraft={canManage||canDraft} canAdmin={canAdmin}
      currentUser={snapshot?.currentUser}
      currency={unitLabel} companyName={view?.companyProfile?.legalName||
        view?.companyWorkspaceLabel||''}
      onRefresh={()=>void requestManualRefresh()} onExit={requestExit} onSwitchCompany={requestCompanySwitch}
      onManageUsers={onManageUsers}
      disabled={busy||state.loading||pendingRetry}/>
    <aside className="sac-sidebar">
      <div className="sac-brand"><div className="sac-brand-icon"><Building2 size={24}/></div>
        <div><strong>تراز <span>حسابداری</span></strong><small>میز مستقل مالی</small></div></div>
      <p className="sac-nav-caption">محیط کار</p>
      <nav aria-label="ناوبری میز حسابداری" tabIndex={0}>{SECTIONS.map(([name,label],i)=>{
        const icons={overview:Landmark,company:Building2,proforma:FileText,
          invoice:FileText,bill:FileText,contractors:Layers3,parties:Users,
          migration:BookOpen,cheques:Wallet,items:Layers3,settlements:Wallet,
          cash:Landmark,accounts:BookOpen,journal:BookOpen,reports:BookOpen,
          payroll:Wallet,period:ShieldAlert,settings:Settings2};
        const Icon=icons[name]||BookOpen;
        return <button key={name} type="button" className={tab===name?'active':''}
          aria-current={tab===name?'page':undefined} onClick={()=>gotoTab(name)}>
          <Icon size={17}/><span>{label}</span></button>;
      })}</nav>
      <div className="sac-sidebar-footer"><div>واحد حسابداری: <strong>{unitLabel}</strong></div>
        <p>بدون وابستگی به تسک‌منیجر یا پروژه</p>
        <button type="button" onClick={requestExit}><ArrowRight size={17}/> خروج از حسابداری</button></div>
    </aside>
    <div className="sac-main">
      <header className="sac-header"><div><span className="sac-kicker">TARAZ / ACCOUNTING</span>
        <h1>{SECTIONS.find(s=>s[0]===tab)?.[1]}</h1>
        <p>دفترکل مستقل، مبتنی بر داده واقعی میزبان</p></div>
        <div className="sac-header-actions"><span>تمام مبالغ: {unitLabel}</span>
          <button type="button" onClick={()=>void requestManualRefresh()} disabled={busy||state.loading}>
            <RefreshCw size={16}/> بازخوانی</button></div></header>
      <div className="sac-body" role="region" aria-label="محتوای صفحه حسابداری" tabIndex={0}>
        {tab==='invoice'&&<nav className="sac-workflow-nav" aria-label="مسیر فاکتور فروش">
          <button type="button" onClick={()=>gotoTab('overview')} disabled={busy||pendingRetry}>صفحه اصلی</button>
          <span aria-hidden="true">/</span>
          <button type="button" onClick={()=>invoiceComposerOpen?
            closeInvoiceComposer():undefined} disabled={!invoiceComposerOpen||busy||pendingRetry}>
            فاکتورهای فروش
          </button>
          {invoiceComposerOpen&&<><span aria-hidden="true">/</span>
            <strong>{editTarget?'ویرایش فاکتور':correctionTarget?'اصلاح فاکتور':'فاکتور جدید'}</strong></>}
          <div className="sac-workflow-actions">
            {invoiceComposerOpen?<button type="button" className="sac-back-button"
              disabled={busy||pendingRetry} onClick={()=>closeInvoiceComposer()}>
              <ArrowRight size={16}/> بازگشت به فهرست فاکتورها
            </button>:
            (canManage||canDraft)&&<button type="button" className="sac-primary"
              onClick={openQuickInvoice} disabled={busy||pendingRetry}>
              <Plus size={16}/> ثبت فاکتور جدید
            </button>}
          </div>
        </nav>}
        {!canManage&&<div role="alert" className="sac-alert">
          <ShieldAlert size={18}/>{canDraft?
            'دسترسی ثبت اولیه: ایجاد مشتری، پیش‌فاکتور و پیش‌نویس فروش/خرید مجاز است. تأیید، صدور و تغییر اسناد قطعی فقط با مدیر انجام می‌شود.':
            'دسترسی مشاهده: مجوز ثبت، صدور یا برگشت سند ندارید.'}</div>}
        {(state.loading||state.error||state.notice)&&<div role={state.error?'alert':'status'}
          aria-live="polite" className={'sac-alert '+(state.error?'error':'info')}>
          <span>{state.loading?'دریافت داده دفترکل...':state.error||state.notice}</span>
          {!state.error&&!state.loading&&state.notice&&<button type="button"
            aria-label="بستن پیام موفقیت" onClick={()=>setState(p=>({...p,notice:''}))}>×</button>}
          {state.error&&<button type="button" disabled={busy||pendingRetry}
            title={pendingRetry?'ابتدا نتیجه عملیات را با همان شناسه بازیابی کنید.':undefined}
            onClick={()=>void requestManualRefresh()}>
            بازخوانی از میزبان</button>}</div>}
        {pendingRetry&&<div className="sac-alert error" role="alert">
          <span>نتیجه یک عملیات نامشخص است؛ برای جلوگیری از ثبت دوباره، ارسال تازه متوقف شده است.</span>
          <button type="button" disabled={busy} onClick={()=>void retryUncertain()}>
            بازیابی با همان شناسه عملیات</button>
        </div>}
        {!view&&!state.loading&&<Empty>اطلاعات قابل اتکایی از میزبان دریافت نشده است. سند یا مبلغ نمایشی ساخته نمی‌شود.</Empty>}
        {tab==='settings'&&<Panel title="تنظیمات حسابداری"
          description="نسخه حسابداری تراز، مستقل از به‌روزرسانی‌های مدار مدیریت کار.">
          <p>تراز ۱.۰.۰؛ به‌روزرسانی خودکار مستقل هنوز ارائه نشده است. این بخش هیچ ارتباطی با انتشار مدار ندارد.</p>
        </Panel>}
        {view&&<>
          {tab==='proforma'&&<>
            <Panel title="پیش‌فاکتورهای فروش مستقل"
              description="این پیشنهادها بدون ساخت تسک، پروژه یا سفارش عملیاتی صادر می‌شوند. هیچ پیش‌فاکتوری بدهی مشتری یا سند دفترکل ایجاد نمی‌کند.">
              {!view.proformas?<div className="sac-alert error" role="alert">
                میزبان از قرارداد پیش‌فاکتور مستقل پشتیبانی نمی‌کند. برای ثبت، نسخه جدید را اجرا کنید.
              </div>:<DataTable cols={['شناسه','مشتری','تاریخ / اعتبار','مبلغ','وضعیت','عملیات']}
                empty="هنوز پیش‌فاکتوری وجود ندارد."
                rows={sortMap(view.proformas).map(d=><tr key={d.id}>
                  <td><strong dir="ltr">{d.id}</strong></td>
                  <td>{parties[d.partyId]?.name||d.partyId}</td>
                  <td>{displayAccountingDate(d.documentDate)}{d.validUntil?' / '+displayAccountingDate(d.validUntil):''}</td>
                  <td>{moneyText(d.total)}</td>
                  <td><span className={'sac-pill '+d.status}>{STATES[d.status]||d.status}</span>
                    {d.convertedInvoiceId&&<small>فاکتور: {d.convertedInvoiceId}</small>}</td>
                  <td className="sac-actions">
                    {canManage&&<button type="button" disabled={busy}
                      onClick={()=>void exportDocument(d,'pdf','proforma')}>PDF پیش‌فاکتور</button>}
                    {canManage&&<button type="button" disabled={busy}
                      onClick={()=>void exportDocument(d,'png','proforma')}>PNG</button>}
                    {canManage&&d.status==='draft'&&<button type="button" disabled={busy||pendingRetry}
                      onClick={()=>{
                        if(proformaEditing===d.id)return;
                        if(hasUnsavedProforma&&!window.confirm(
                          'پیش‌فاکتور فعلی هنوز ذخیره نشده است. تغییرات آن را کنار بگذاریم و پیش‌فاکتور دیگری را ویرایش کنیم؟'))return;
                        setProformaEditing(d.id);
                        setForms(p=>({...p,proforma:{proformaId:d.id,
                          partyId:d.partyId,documentDate:d.documentDate,
                          validUntil:d.validUntil||'',note:d.note||'',
                          discount:String(d.discount),tax:String(d.tax)}}));
                        setProformaRows(d.lines.map(l=>({description:l.description,
                          quantity:String(l.quantity),unitPrice:String(l.unitPrice),
                          accountId:l.accountId||'',itemId:l.itemId||''})));
                      }}>ویرایش</button>}
                    {canManage&&d.status==='draft'&&<button type="button" disabled={busy}
                      onClick={()=>void execute(id=>({command:{type:'proforma.send',eventId:id,
                        proformaId:d.id}}),'پیش‌فاکتور برای ارائه به مشتری آماده شد؛ هنوز سند مالی نیست.')}>ثبت ارسال</button>}
                    {canManage&&d.status==='sent'&&<button type="button" disabled={busy}
                      onClick={()=>void execute(id=>({command:{type:'proforma.accept',eventId:id,
                        proformaId:d.id}}),'پذیرش پیشنهاد ثبت شد؛ برای فاکتور باید تبدیل انجام شود.')}>ثبت پذیرش</button>}
                    {canManage&&['sent','draft','accepted'].includes(d.status)&&<>
                      <input aria-label={'دلیل رد یا لغو '+d.id} maxLength={1000}
                        placeholder="دلیل رد / لغو" value={proformaReasons[d.id]||''}
                        onChange={e=>setProformaReasons(p=>({...p,[d.id]:e.target.value}))}/>
                      {d.status==='sent'&&<button type="button"
                        disabled={busy||!validText(proformaReasons[d.id]||'',1000)}
                        onClick={()=>void execute(id=>({command:{type:'proforma.reject',
                          eventId:id,proformaId:d.id,reason:proformaReasons[d.id].trim()}}),
                          'رد پیشنهاد ثبت شد.')}>رد</button>}
                      <button type="button" disabled={busy||!validText(proformaReasons[d.id]||'',1000)}
                        onClick={()=>void execute(id=>({command:{type:'proforma.cancel',
                          eventId:id,proformaId:d.id,reason:proformaReasons[d.id].trim()}}),
                          'پیش‌فاکتور لغو شد.')}>لغو</button>
                    </>}
                    {canManage&&d.status==='accepted'&&<>
                      <input dir="ltr" aria-label={'شماره فاکتور مقصد '+d.id}
                        placeholder="شناسه فاکتور فروش جدید"
                        value={proformaConversions[d.id]||''}
                        onChange={e=>setProformaConversions(p=>({...p,[d.id]:e.target.value}))}/>
                      <button type="button" disabled={busy||!validId(proformaConversions[d.id]||'')}
                        onClick={async()=>{
                          const ok=await execute(id=>({command:{type:'proforma.convert',
                            eventId:id,proformaId:d.id,invoiceId:proformaConversions[d.id],
                            documentDate:today}}),
                            'پیش‌نویس فاکتور مستقل از پیش‌فاکتور ایجاد شد؛ هنوز سند دفترکل نیست.');
                          if(ok)setTab('invoice');
                        }}>تبدیل به فاکتور</button>
                    </>}
                  </td>
                </tr>)}/>}
            </Panel>
            {(canManage||canDraft)&&<Panel title={proformaEditing?'ویرایش پیش‌فاکتور '+proformaEditing:'ایجاد پیش‌فاکتور مستقل جدید'}
              description="بدون کارت و تسک. قیمت، تخفیف و مالیات با واحد واقعی دفترکل محاسبه می‌شود؛ فقط فاکتور صادرشده اثر مالی دارد.">
              <form onSubmit={submit(async()=>{
                const created=await execute(id=>buildStandaloneProformaCommand({
                  ...forms.proforma,proformaId:proformaEditing||forms.proforma.proformaId,
                  lines:proformaRows,eventId:id,accounts,items,today,update:!!proformaEditing}),
                  proformaEditing?'تغییر پیش‌نویس پیشنهاد ثبت شد.':
                    'پیش‌فاکتور مستقل ایجاد شد؛ هیچ سند مالی ثبت نشده است.');
                if(created){
                  reset('proforma');setProformaRows([makeLine()]);setProformaEditing('');
                }
              })}>
                <div className="sac-grid">
                  <Field label="شناسه پیش‌فاکتور">{proformaEditing?
                    <input readOnly dir="ltr" value={proformaEditing}/>:
                    idInput('proforma','proformaId','PF-001')}</Field>
                  <Field label="مشتری"><select required value={forms.proforma.partyId}
                    onChange={e=>f('proforma','partyId',e.target.value)}>
                    {options(customers,'انتخاب مشتری')}</select></Field>
                  <Field label="تاریخ">{dateInput('proforma','documentDate')}</Field>
                  <Field label="اعتبار تا (اختیاری)"><AccountingJalaliField
                    required={false} min={forms.proforma.documentDate||today}
                    value={forms.proforma.validUntil}
                    onChange={iso=>f('proforma','validUntil',iso)}/></Field>
                  <Field label={`تخفیف (${unitLabel})`}>{amountInput('proforma','discount')}</Field>
                  <Field label={`مالیات صریح (${unitLabel})`}>{amountInput('proforma','tax')}</Field>
                  <Field label="شرایط و توضیحات" wide><input maxLength={1000}
                    value={forms.proforma.note} onChange={e=>f('proforma','note',e.target.value)}/></Field>
                </div>
                <div className="sac-subheading"><h3>اقلام پیشنهادی</h3><button type="button"
                  disabled={busy||pendingRetry||nativeClosePending.current}
                  onClick={()=>updateProformaRows(p=>p.length<1000?[...p,makeLine()]:p)}>
                  <Plus size={15}/> ردیف جدید</button></div>
                {proformaRows.map((r,i)=><div className="sac-doc-line" key={i}>
                  <Field label="شرح"><input required maxLength={300} value={r.description}
                    readOnly={busy||pendingRetry}
                    onChange={e=>updateProformaRows(p=>p.map((x,j)=>j===i?{...x,description:e.target.value}:x))}/></Field>
                  <Field label="تعداد"><input required dir="ltr" inputMode="numeric" value={r.quantity}
                    readOnly={busy||pendingRetry}
                    onChange={e=>updateProformaRows(p=>p.map((x,j)=>j===i?{...x,quantity:e.target.value}:x))}/></Field>
                  <Field label={`قیمت واحد (${unitLabel})`}><input required dir="ltr"
                    inputMode="numeric" value={r.unitPrice}
                    readOnly={busy||pendingRetry}
                    onChange={e=>updateProformaRows(p=>p.map((x,j)=>j===i?{...x,unitPrice:e.target.value}:x))}/></Field>
                  <Field label="حساب درآمد"><select required value={r.accountId||'4000'}
                    disabled={busy||pendingRetry}
                    onChange={e=>updateProformaRows(p=>p.map((x,j)=>j===i?{...x,accountId:e.target.value}:x))}>
                    {sortMap(accounts).filter(a=>a.kind==='revenue').map(a=>
                      <option key={a.id} value={a.id}>{a.name} ({a.id})</option>)}</select></Field>
                  <Field label="کالای کاتالوگ"><select value={r.itemId||''}
                    disabled={busy||pendingRetry}
                    onChange={e=>updateProformaRows(p=>p.map((x,j)=>j===i?{...x,itemId:e.target.value}:x))}>
                    {options(sortMap(items).filter(a=>a.active),'بدون قلم')}</select></Field>
                  <button type="button" disabled={busy||pendingRetry||proformaRows.length===1}
                    onClick={()=>updateProformaRows(p=>p.filter((_,j)=>j!==i))}>حذف</button>
                </div>)}
                <div className="sac-form-actions"><Action disabled={draftBlocked}>
                  {proformaEditing?'ثبت اصلاح':'ایجاد پیش‌فاکتور'}</Action>
                  {proformaEditing&&<button type="button" disabled={busy||pendingRetry} onClick={()=>{
                    if(hasUnsavedProforma&&!window.confirm('ویرایش فعلی پیش‌فاکتور ذخیره نشده است. آن را کنار بگذاریم؟'))return;
                    setProformaEditing('');reset('proforma');setProformaRows([makeLine()]);
                  }}>انصراف</button>}
                </div>
              </form>
            </Panel>}
          </>}
          {tab==='contractors'&&<>
            <Panel title="کارهای ارجاع‌شده به پیمانکاران" description="بدون قیمت، بدهی یا سند دفترکل ایجاد نمی‌شود. پرداخت صرفاً از بخش مالی امکان‌پذیر است.">
              <DataTable cols={['تأمین‌کننده','کار / شناسه منبع','تعداد',`قیمت واحد (${unitLabel})`,'وضعیت','عملیات']}
                empty="کاری برای پیمانکار ثبت نشده است."
                rows={sortMap(view.contractorJobs||{}).sort((a,b)=>
                  (parties[a.partyId]?.name||a.partyId).localeCompare(parties[b.partyId]?.name||b.partyId))
                  .map(j=><tr key={j.id}>
                    <td>{parties[j.partyId]?.name||j.partyId}</td>
                    <td><strong>{j.description}</strong><small dir="ltr">{j.sourceType} / {j.sourceId}</small></td>
                    <td>{j.quantity.toLocaleString('fa-IR')}</td>
                    <td>{j.unitPrice===null?'اعلام نشده':moneyText(j.unitPrice)}</td>
                    <td>{({unpriced:'در انتظار قیمت',priced:'در انتظار تطبیق',approved:'تأییدشده',billed:'در صورتحساب'})[j.status]||j.status}</td>
                    <td className="sac-actions">
                      {canManage&&['unpriced','priced'].includes(j.status)&&<>
                        <input aria-label={'قیمت '+j.id} dir="ltr" inputMode="numeric"
                          placeholder="قیمت واحد" value={vendorPrices[j.id]??''}
                          onChange={e=>setVendorPrices(p=>({...p,[j.id]:e.target.value}))}/>
                        <button type="button" disabled={blocked} onClick={()=>void execute(eventId=>{
                          const price=parse(vendorPrices[j.id]);
                          return price===null?failure(`قیمت واحد باید عدد صحیح و مثبت به ${unitLabel} باشد.`):
                            {command:{type:'contractor.job.price',eventId,jobId:j.id,
                              currency:ledgerCurrency,unitPrice:price}};
                        },'قیمت ثبت شد؛ هنوز بدهی ایجاد نشده است.')}>ثبت قیمت</button>
                      </>}
                      {canManage&&j.status==='priced'&&<>
                        <input aria-label={'تعداد تأییدشده '+j.id} dir="ltr" inputMode="numeric"
                          placeholder="تعداد فاکتور" value={vendorQuantities[j.id]??String(j.quantity)}
                          onChange={e=>setVendorQuantities(p=>({...p,[j.id]:e.target.value}))}/>
                        <button type="button" disabled={blocked} onClick={()=>void execute(eventId=>{
                          const n=parse(vendorQuantities[j.id]??String(j.quantity));
                          return n===null?failure('تعداد تطبیق‌شده معتبر نیست.'):
                            {command:{type:'contractor.job.approve',eventId,jobId:j.id,
                              confirmedQuantity:n}};
                        },'تعداد تطبیق و کار تأیید شد.')}>تطبیق</button>
                      </>}
                      {canManage&&j.status==='approved'&&<label>انتخاب برای تجمیع
                        <input type="checkbox" checked={!!vendorSelected[j.id]}
                          onChange={e=>setVendorSelected(p=>({...p,[j.id]:e.target.checked}))}/>
                      </label>}
                      {j.billedBy&&<small>فاکتور: {j.billedBy}</small>}
                    </td></tr>)}/>
            </Panel>
            {canManage&&<Panel title="ثبت ارجاع مستقل (بدون صدور بدهی)">
              <form className="sac-grid" onSubmit={submit(async()=>{
                const q=parse(vendorDraft.quantity),unit=vendorDraft.unitPrice.trim()===''?null:parse(vendorDraft.unitPrice);
                if(!validId(vendorDraft.jobId)||!validId(vendorDraft.sourceId)||
                   !validText(vendorDraft.description)||!validId(vendorDraft.partyId)||
                   q===null||q>1000000||(vendorDraft.unitPrice.trim()!==''&&unit===null)){
                  setState(p=>({...p,error:'شناسه‌ها، طرف‌حساب، شرح، تعداد یا قیمت معتبر نیست.'}));return;}
                const ok=await execute(eventId=>({command:{
                  type:'contractor.job.intake',eventId,jobId:vendorDraft.jobId,
                  sourceType:'standalone.manual',sourceId:vendorDraft.sourceId,
                  partyId:vendorDraft.partyId,description:vendorDraft.description.trim(),
                  quantity:q,unitPrice:unit,currency:ledgerCurrency}}),
                'کار پیمانکار بدون ثبت بدهی ذخیره شد.');
                if(ok)setVendorDraft({jobId:'',sourceId:'',partyId:'',
                  description:'',quantity:'1',unitPrice:'',currency:ledgerCurrency});
              })}>
                <Field label="شناسه کار"><input required dir="ltr" value={vendorDraft.jobId}
                  onChange={e=>setVendorDraft(p=>({...p,jobId:e.target.value}))}/></Field>
                <Field label="شناسه منبع"><input required dir="ltr" value={vendorDraft.sourceId}
                  onChange={e=>setVendorDraft(p=>({...p,sourceId:e.target.value}))}/></Field>
                <Field label="تأمین‌کننده"><select required value={vendorDraft.partyId}
                  onChange={e=>setVendorDraft(p=>({...p,partyId:e.target.value}))}>
                  {options(vendors,'انتخاب تأمین‌کننده')}</select></Field>
                <Field label="شرح کوتاه کار"><input required maxLength={300} value={vendorDraft.description}
                  onChange={e=>setVendorDraft(p=>({...p,description:e.target.value}))}/></Field>
                <Field label="تعداد"><input required dir="ltr" inputMode="numeric" value={vendorDraft.quantity}
                  onChange={e=>setVendorDraft(p=>({...p,quantity:e.target.value}))}/></Field>
                <Field label={`قیمت واحد (${unitLabel}، اختیاری)`}><input dir="ltr" inputMode="numeric"
                  placeholder="نامشخص" value={vendorDraft.unitPrice}
                  onChange={e=>setVendorDraft(p=>({...p,unitPrice:e.target.value}))}/></Field>
                <Action disabled={blocked}>ثبت کار</Action>
              </form>
            </Panel>}
            {canManage&&<Panel title="ساخت صورتحساب تجمیعی پیمانکار" description="فقط کارهای تطبیق‌شده یک تأمین‌کننده؛ پیش‌نویس بدهی قطعی نیست.">
              <form className="sac-grid" onSubmit={submit(async()=>{
                const jobs=Object.values(view.contractorJobs||{}).filter(j=>j.status==='approved'&&
                  vendorSelected[j.id]);
                if(!validId(batchId)||!validId(batchParty)||!jobs.length||
                   jobs.some(j=>j.partyId!==batchParty)){
                  setState(p=>({...p,error:'شناسه فاکتور و یک تأمین‌کننده مشترک برای اقلام تأییدشده لازم است.'}));return;}
                if(await execute(eventId=>({command:{type:'contractor.bill.create',
                  eventId,billId:batchId,partyId:batchParty,
                  documentDate:today,jobIds:jobs.map(j=>j.id)}}),
                  'پیش‌نویس تجمیعی در حسابداری ساخته شد؛ برای بدهی قطعی باید تأیید و صادر شود.')){
                  setVendorSelected({});setBatchId('');setBatchParty('');
                }
              })}>
                <Field label="شناسه صورتحساب"><input required dir="ltr" value={batchId}
                  onChange={e=>setBatchId(e.target.value)}/></Field>
                <Field label="تأمین‌کننده"><select required value={batchParty}
                  onChange={e=>setBatchParty(e.target.value)}>
                  {options(vendors,'انتخاب تأمین‌کننده')}</select></Field>
                <Action disabled={blocked}>آماده‌سازی پیش‌نویس تجمیعی</Action>
              </form>
            </Panel>}
          </>}
          {tab==='overview'&&<>
            <PersonalParsianDashboard api={api} view={view} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear} onNavigate={()=>setTab('parties')}/>
            <p className="ppd-context-note">{'\u0645\u0627\u0646\u062f\u0647 \u0647\u0631 \u0634\u062e\u0635 \u0627\u0632 \u062f\u0641\u062a\u0631 \u06a9\u0644 \u062e\u0648\u0627\u0646\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f. \u0648\u0636\u0639\u06cc\u062a \u062a\u0633\u0648\u06cc\u0647 \u0647\u0631 \u0641\u0627\u06a9\u062a\u0648\u0631 \u0642\u062f\u06cc\u0645\u06cc \u0645\u0633\u062a\u0642\u0644 \u0627\u0633\u062a \u0648 \u0627\u0632 \u0645\u0627\u0646\u062f\u0647 \u0627\u0634\u062e\u0627\u0635 \u0642\u0627\u0628\u0644 \u0627\u0633\u062a\u0646\u0628\u0627\u0637 \u0646\u06cc\u0633\u062a.'}</p>
            <AccountingVitreaHome api={api} fiscalYear={fiscalYear} view={view} currency={ledgerCurrency} today={today}
              canDraft={canManage||canDraft} canSettle={canManage} disabled={busy||pendingRetry}
              preferenceKey={snapshot?.currentUser?.username&&
                typeof view?.companyWorkspaceId==='string'&&
                /^[a-f0-9]{32}$/.test(view.companyWorkspaceId)?
                snapshot.currentUser.username+'|'+view.companyWorkspaceId:''}
              onNavigate={gotoTab} onNewInvoice={openQuickInvoice}/>
            <details className="sac-vtr-management-details"><summary>گزارش‌های تحلیلی و یادآورهای مدیریتی</summary>
              <AccountingManagementDashboard view={view} currency={ledgerCurrency}
                onNavigate={gotoTab}/>
            </details>
            <details className="sac-dashboard-legacy-details">
              <summary>جزئیات دفترکل، مانده‌های قبلی و سوابق انتقالی</summary>
            {historical&&<Panel title="حسابداری منتقل‌شده از پارسیان"
              description="مانده‌ها از دفترکل واقعی منتقل‌شده محاسبه شده‌اند؛ اسناد تاریخی فاکتور دوباره ثبت نشده‌اند.">
              <div className="sac-metrics">
                <div className="sac-metric"><span>حساب‌های بدهکار با مانده مثبت</span>
                  <strong>{historical.positiveDebtorCount.toLocaleString('fa-IR')}</strong>
                  <small>بر اساس حساب‌های کل/معین/تفصیلی</small></div>
                <div className="sac-metric"><span>مانده بدهکاران تاریخی</span>
                  <strong>{moneyText(historical.positiveDebtorTotal)}</strong>
                  <small>با مانده فاکتورهای جدید مخلوط نشده است</small></div>
                <div className="sac-metric"><span>فاکتورهای تاریخی منبع</span>
                  <strong>{historical.historicalInvoiceGroups.toLocaleString('fa-IR')}</strong>
                  <small>آرشیوی، بدون صدور مجدد</small></div>
              </div>
              <button type="button" className="sac-primary" onClick={()=>setTab('migration')}>
                مشاهده بدهکاران و اسناد منتقل‌شده
              </button>
            </Panel>}
            <div className="sac-metrics">{[
              ['مانده دریافتنی فاکتورهای جدید',moneyText(stat.receivable),'غیرشامل بدهکاران تاریخی؛ به کارت بالاتر توجه کنید'],
              ['مانده پرداختنی',moneyText(stat.payable),'از اسناد خرید صادرشده'],
              ['خالص صندوق و بانک',moneyText(stat.liquid),'از حساب‌های نقدی دفترکل'],
              ['اسناد صادرشده',stat.count.toLocaleString('fa-IR'),'تعداد فروش و خرید'],
            ].map(([title,value,description])=><div key={title} className="sac-metric">
              <span>{title}</span><strong>{value}</strong><small>{description}</small></div>)}</div>
            <Panel title="آخرین گردش‌های دفترکل" description="مانده‌ها از رویدادهای ثبت‌شده موتور حسابداری مشتق می‌شوند.">
              <DataTable cols={['شناسه سند','تاریخ','منبع','بدهکار','بستانکار']}
                empty="تا این لحظه سندی در دفترکل نیست."
                rows={[...view.journals].slice(-10).reverse().map(j=><tr key={j.id}>
                  <td dir="ltr">{j.id}</td><td>{displayAccountingDate(j.date)}</td><td>{humanSource(j.sourceType)}</td>
                  <td>{debitText(j.lines.reduce((s,x)=>s+x.debit,0))}</td>
                  <td>{creditText(j.lines.reduce((s,x)=>s+x.credit,0))}</td></tr>)}/></Panel>
            </details>
          </>}
          {['invoice','bill'].includes(tab)&&<>
            {tab==='invoice'&&<PersonalParsianInvoices api={api} section="invoices" fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear}/>}
            {(tab==='bill'||!invoiceComposerOpen)&&<Panel title={tab==='invoice'?'فاکتورهای فروش':'صورتحساب‌های خرید'}
              description="پیش‌نویس، تأیید و صدور مراحل جداگانه‌اند؛ مبلغ صرفاً با صدور وارد دفترکل می‌شود.">
              {tab==='invoice'&&<p className="sac-invoice-list-help">
                فاکتورهای شما در همین صفحه‌اند. برای شروع «ثبت فاکتور جدید» را بزنید.
                فاکتور ابتدا پیش‌نویس می‌شود و بعداً قابل ویرایش و تأیید است.
              </p>}
              <details className="sac-disclosure sac-list-settings">
                <summary>تنظیمات بیشتر چاپ و صدور فاکتور</summary>
              {canManage&&tab==='invoice'&&<Field label="قالب چاپ و خروجی فاکتور فروش">
                <select aria-label="قالب چاپ فاکتور" value={invoicePrintLayout}
                  onChange={e=>setInvoicePrintLayout(e.target.value)}>
                  <option value="parsian-karma">پارسیان / چاپ و تبلیغات کارما (از فایل اصلی FR3)</option>
                  <option value="madar">قالب عمومی تراز</option>
                  <option value="custom">قالب سفارشی شرکت (طراحی و ذخیره‌شده)</option>
                </select>
                <small>چیدمان پارسیان از فایل اصلی استخراج شده است؛ مشخصات پرداخت ثبت‌نشده کپی نمی‌شوند. خروجی پیش‌نویس برچسب آزمایشی دارد.</small>
              </Field>}
              {canManage&&<Field label="الگوی نام فایل PDF / PNG (قابل تنظیم)">
                <input value={filenamePattern} maxLength={150}
                  onChange={e=>setFilenamePattern(e.target.value)}
                  placeholder="madar-{kind}-{id}-{date}"/>
                <small>متغیرهای مجاز: {'{kind}'}، {'{id}'}، {'{date}'}، {'{number}'}. ذخیره و نام تکراری را مرورگر مدیریت می‌کند.</small>
              </Field>}
              {canManage&&<div className="sac-issue-date">
                <Field label="تاریخ صدور قطعی (برای سند تأییدشده)">
                  <AccountingJalaliField max={today} value={issueDate}
                    onChange={setIssueDate}/></Field>
                <span>تاریخ باید از تاریخ سند و مرز دوره بسته‌شده عقب‌تر نباشد.</span>
              </div>}
              </details>
              {tab==='invoice'&&<div className="sac-invoice-list-toolbar"
                aria-label="جست‌وجو و وضعیت فاکتورها">
                <label className="sac-invoice-list-search">جست‌وجوی فاکتور یا مشتری
                  <input type="search" value={invoiceListSearch}
                    placeholder="شماره فاکتور، نام مشتری..."
                    onChange={e=>setInvoiceListSearch(e.target.value)}/>
                </label>
                <div className="sac-invoice-status-filters" role="group"
                  aria-label="فیلتر وضعیت فاکتور">
                  {[['all','همه'],['draft','پیش‌نویس'],['approved','تأییدشده'],
                    ['issued','صادرشده']].map(([key,label])=>
                    <button key={key} type="button" aria-pressed={invoiceListStatus===key}
                      onClick={()=>setInvoiceListStatus(key)}>
                      {label} <span>{invoiceCounts[key].toLocaleString('fa-IR')}</span>
                    </button>)}
                </div>
              </div>}
              <DataTable cols={['شناسه','طرف‌حساب','تاریخ','کل','مانده','وضعیت','اقدامات']}
                empty={tab==='invoice'&&(invoiceListSearch||invoiceListStatus!=='all')?
                  'فاکتوری مطابق فیلتر پیدا نشد؛ جست‌وجو یا وضعیت را تغییر دهید.':
                  'هنوز سندی در این بخش ثبت نشده است.'}
                rows={filteredInvoiceDocs.map(d=><tr key={d.id}>
                  <td><strong dir="ltr">{d.id}</strong>
                    <small>{d.number?'شماره: '+d.number:'بدون شماره'}</small>
                    {d.sourceType==='proforma'&&<small>از پیش‌فاکتور {d.sourceId}</small>}
                  </td>
                  <td>{parties[d.partyId]?.name||d.partyId}</td><td>{displayAccountingDate(d.documentDate)}</td>
                  <td>{moneyText(d.total)}</td>
                  <td>{d.status==='issued'?(docKind==='invoice'?
                    debitText(d.total-d.allocated-(d.returnedAmount||0)):
                    creditText(d.total-d.allocated-(d.returnedAmount||0))):'—'}</td>
                  <td><span className={'sac-pill '+d.status}>{STATES[d.status]||d.status}</span>
                    <small className="sac-invoice-next-action">{d.status==='draft'?
                      'گام بعدی: بازبینی و تأیید؛ بدون ثبت دفترکل':
                      d.status==='approved'?'گام بعدی: صدور قطعی و ثبت دفترکل':
                      d.status==='issued'?(d.total>d.allocated+(d.returnedAmount||0)?
                        'سند قطعی؛ گام بعدی: تسویه و کنترل انبار':
                        'تسویه‌شده؛ مشاهده و خروجی سند در دسترس است'):
                      'وضعیت سند را در جزئیات بررسی کنید'}</small></td>
                  <td className="sac-actions">
                    <button type="button" onClick={()=>{
                      setDetailTarget(d.id);setReopenReason('');setTaxPreflight(null);
                    }}>مشاهده جزئیات</button>
                    {canManage&&<button type="button" disabled={busy}
                      onClick={()=>void exportDocument(d,'pdf')}>PDF</button>}
                    {canManage&&d.status==='draft'&&!d.contractorJobIds&&<button type="button"
                      disabled={busy} onClick={()=>startEditingDocument(d)}>ویرایش پیش‌نویس</button>}
                    {canManage&&d.status==='draft'&&<button type="button" disabled={busy}
                      onClick={()=>{
                        if(!window.confirm('پیش‌نمایش تأیید: '+d.id+' به مبلغ '+moneyText(d.total)+
                          ' تأیید می‌شود. هنوز سندی در دفترکل ثبت نخواهد شد. ادامه می‌دهید؟'))return;
                        void execute(id=>({command:{type:docKind+'.approve',
                          eventId:id,[docKind+'Id']:d.id}}),
                          'سند تأیید شد؛ هنوز صادر نشده است.');
                      }}>تأیید</button>}
                    {canManage&&d.status==='approved'&&<button type="button"
                      disabled={busy||!validPostingDate(issueDate)||issueDate<d.documentDate}
                      onClick={()=>{
                        if(!window.confirm('پیش‌نمایش صدور قطعی: سند '+d.id+' به مبلغ '+
                          moneyText(d.total)+' با تاریخ '+displayAccountingDate(issueDate)+
                          ' در دفترکل ثبت می‌شود. کنترل خروج انبار و بهای تمام‌شده '+
                          'به صورت جداگانه الزامی است. ادامه می‌دهید؟'))return;
                        void execute(id=>({command:{type:docKind+'.issue',
                          eventId:id,[docKind+'Id']:d.id,postingDate:issueDate}}),
                          'سند صادر و در دفترکل ثبت شد.');
                      }}>صدور سند</button>}
                    {d.status==='approved'&&(!validPostingDate(issueDate)||issueDate<d.documentDate)&&
                      <small className="sac-invoice-next-action" role="status">
                        برای صدور، تاریخ معتبر را در «تنظیمات بیشتر چاپ و صدور» مشخص کنید.
                      </small>}
                    {d.status==='issued'&&d.total>d.allocated+(d.returnedAmount||0)&&<button type="button" onClick={()=>{
                      if(!gotoTab('settlements'))return;
                      setForms(p=>({...p,settlement:{...p.settlement,
                        kind:docKind==='invoice'?'receipt':'payment',documentId:d.id}}));
                    }}>تسویه</button>}
                    <details className="sac-invoice-row-menu">
                      <summary aria-label={'عملیات بیشتر فاکتور '+d.id}>بیشتر</summary>
                      <div className="sac-invoice-row-menu-items">
                        {docKind==='invoice'&&typeof api?.standaloneAccountingTaxPreflight==='function'&&
                          <button type="button" disabled={busy} onClick={()=>{
                            setDetailTarget(d.id);setTaxPreflight(null);
                            void api.standaloneAccountingTaxPreflight(d.id).then(result=>{
                              setTaxPreflight({invoiceId:d.id,...result});
                            }).catch(err=>setState(p=>({...p,error:err.message||String(err)})));
                          }}>مشاور مالیاتی (پیش‌بررسی)</button>}
                        {canManage&&<>
                          <button type="button" disabled={busy} onClick={()=>void exportDocument(d,'png')}>خروجی PNG</button>
                          <button type="button" disabled={busy} onClick={()=>void exportDocument(d,'xlsx')}>خروجی Excel</button>
                          <button type="button" disabled={busy} onClick={()=>void exportDocument(d,'rtf')}>خروجی RTF</button>
                        </>}
                        {canManage&&['draft','approved'].includes(d.status)&&
                          <button type="button" disabled={busy}
                            onClick={()=>{setCancelTarget(d.id);setCancelReason('');}}>
                            لغو سند</button>}
                      </div>
                    </details>
                  </td></tr>)} />
              {detailedDocument&&<section className="sac-document-detail" aria-label="مشاهده فاکتور">
                {taxPreflight?.invoiceId===detailedDocument.id&&<aside className="sac-tax-preflight" role="status">
                  <h4>مشاور مالیاتی تراز | ارزیابی مقدماتی</h4>
                  <p>وضعیت: نیازمند بررسی انسانی. ارسال رسمی از این بخش امکان‌پذیر نیست.</p>
                  <ul>{taxPreflight.issues.map((issue,i)=><li key={i}>
                    {issue.field}: {issue.message}</li>)}</ul>
                  <small>منابع ذکرشده هنوز از نظر به‌روز بودن در تاریخ صدور تأیید نشده‌اند.</small>
                </aside>}
                <div className="sac-document-detail-header">
                  <h3>جزئیات {docKind==='invoice'?'فاکتور فروش':'صورتحساب خرید'}: <b dir="ltr">{detailedDocument.id}</b></h3>
                  <button type="button" onClick={()=>setDetailTarget('')}>بستن جزئیات</button>
                </div>
                <dl className="sac-document-info">
                  <div><dt>طرف‌حساب</dt><dd>{parties[detailedDocument.partyId]?.name||detailedDocument.partyId}</dd></div>
                  <div><dt>تاریخ سند</dt><dd>{displayAccountingDate(detailedDocument.documentDate)}</dd></div>
                  <div><dt>وضعیت</dt><dd>{STATES[detailedDocument.status]||detailedDocument.status}</dd></div>
                  <div><dt>شماره قطعی</dt><dd>{detailedDocument.number||'هنوز صادر نشده'}</dd></div>
                  <div><dt>تاریخ ثبت دفترکل</dt><dd>{detailedDocument.postingDate?
                    displayAccountingDate(detailedDocument.postingDate):'ثبت نشده'}</dd></div>
                  <div><dt>شناسه سند حسابداری</dt><dd dir="ltr">{detailedDocument.postedEntryId||'—'}</dd></div>
                  {detailedDocument.sourceType&&<div><dt>منبع</dt><dd>{detailedDocument.sourceType} / {detailedDocument.sourceId||'—'}</dd></div>}
                </dl>
                <DataTable cols={['شرح کالا یا خدمت','تعداد','قیمت واحد','جمع ردیف','کد حساب']}
                  empty="این سند ردیفی ندارد."
                  rows={(detailedDocument.lines||[]).map((line,i)=><tr key={i}>
                    <td>{line.description}</td>
                    <td>{Number(line.quantity).toLocaleString('fa-IR')}</td>
                    <td>{moneyText(line.unitPrice)}</td>
                    <td>{moneyText(line.total)}</td>
                    <td dir="ltr">{line.accountId||'—'}</td>
                  </tr>)}/>
                <p><strong>سررسید تسویه: </strong>{
                  detailedDocument.dueDate?displayAccountingDate(detailedDocument.dueDate):
                  'بدون سررسید ثبت‌شده'}</p>
                <div className="sac-document-totals">
                  <span>جمع اقلام: {moneyText(detailedDocument.subtotal)}</span>
                  <span>تخفیف: {moneyText(detailedDocument.discount)}</span>
                  <span>مالیات: {moneyText(detailedDocument.tax)}</span>
                  <strong>جمع نهایی: {moneyText(detailedDocument.total)}</strong>
                  {detailedDocument.status==='issued'&&<strong>مانده پس از مرجوعی: {
                    docKind==='invoice'?debitText(detailedDocument.total-detailedDocument.allocated-
                      (detailedDocument.returnedAmount||0)):
                    creditText(detailedDocument.total-detailedDocument.allocated-
                      (detailedDocument.returnedAmount||0))}</strong>}
                </div>
                {detailedDocument.note&&<p><strong>یادداشت: </strong>{detailedDocument.note}</p>}
                {detailedDocument.lastReopenReason&&<p><strong>آخرین علت بازگشت به پیش‌نویس: </strong>
                  {detailedDocument.lastReopenReason}</p>}
                {detailedDocument.correctedBy&&<p className="sac-inline-info">
                  این سند برگشت داده شده و سند جایگزین آن <b dir="ltr">{detailedDocument.correctedBy}</b> است.
                  <button type="button" onClick={()=>setDetailTarget(detailedDocument.correctedBy)}>
                    مشاهده جایگزین</button></p>}
                {detailedDocument.correctionOf&&<p className="sac-inline-info">
                  این سند اصلاحی سند <b dir="ltr">{detailedDocument.correctionOf}</b> است.
                  <button type="button" onClick={()=>setDetailTarget(detailedDocument.correctionOf)}>
                    مشاهده سند اصلی</button></p>}
                {detailedDocument.returnId&&<p className="sac-inline-info">
                  مرجوعی کامل این سند ثبت شده است:
                  <b dir="ltr">{detailedDocument.returnId}</b> · {detailedDocument.returnReason}
                </p>}
                {!!detailedDocument.returnedAmount&&<p className="sac-inline-info">
                  مرجوعی‌های جزئی ثبت‌شده: {moneyText(detailedDocument.returnedAmount)}.
                  سوابق آن در دفتر حسابداری مستقل محفوظ است.
                </p>}
                {sortMap(view.returns).filter(ret=>
                  ret.documentId===detailedDocument.id).length>0&&
                  <details className="sac-audit-notice">
                    <summary>سوابق مرجوعی و اسناد بستانکار/بدهکار این فاکتور</summary>
                    <DataTable cols={['شناسه مرجوعی','نوع','تاریخ','مبلغ','شرح و مقدار اقلام',
                      'دلیل','سند دفترکل']}
                    rows={sortMap(view.returns).filter(ret=>
                      ret.documentId===detailedDocument.id).map(ret=><tr key={ret.id}>
                      <td dir="ltr">{ret.id}</td>
                      <td>{ret.kind==='partial'?'مرجوعی جزئی':'مرجوعی کامل'}</td>
                      <td>{displayAccountingDate(ret.postingDate)}</td>
                      <td>{moneyText(ret.amount)}</td>
                      <td>{(ret.lines||[]).map(line=>
                        (detailedDocument.lines||[])[line.lineIndex]?.description+
                        ' × '+Number(line.quantity).toLocaleString('fa-IR')).join('، ')||'کل سند'}</td>
                      <td>{ret.reason}</td>
                      <td dir="ltr">{ret.journalId||ret.reversalJournalId||'—'}</td>
                    </tr>)}/>
                  </details>}
                <div className="sac-form-actions">
                  {canManage&&<button type="button" disabled={busy}
                    onClick={()=>void exportDocument(detailedDocument,'pdf')}>دریافت PDF</button>}
                  {canManage&&detailedDocument.status==='draft'&&
                    !detailedDocument.contractorJobIds&&
                    <button type="button" disabled={busy}
                      onClick={()=>startEditingDocument(detailedDocument)}>ویرایش فاکتور</button>}
                  {canManage&&detailedDocument.status==='approved'&&
                    !detailedDocument.contractorJobIds&&<>
                    <input aria-label="دلیل بازگرداندن فاکتور برای اصلاح" required
                      maxLength={1000} placeholder="علت اصلاح پیش از صدور"
                      value={reopenReason} onChange={e=>setReopenReason(e.target.value)}/>
                    <button type="button" disabled={busy||!validText(reopenReason,1000)}
                      onClick={async()=>{
                        if(!confirmEditorReplacement())return;
                        if(await execute(id=>({command:{
                          type:docKind+'.reopen',eventId:id,
                          [docKind+'Id']:detailedDocument.id,
                          reason:reopenReason.trim()}}),
                          'تأیید سند با رویداد قابل‌ردیابی بازگردانده شد؛ هنوز سند دفترکل ثبت نشده است.')){
                          startEditingDocument(detailedDocument,{discardConfirmed:true});setReopenReason('');
                        }
                      }}>بازگرداندن به پیش‌نویس و ویرایش</button>
                  </>}
                  {detailedDocument.status==='issued'&&<>
                    {detailedDocument.allocated===0&&!detailedDocument.contractorJobIds&&
                      !detailedDocument.returnedAmount?
                      <p className="sac-audit-notice">
                        اصلاح فاکتور قطعی به‌صورت برگشت سند اصلی و ایجاد پیش‌نویس جایگزین،
                        در یک عملیات اتمیک و با حفظ تاریخچه انجام می‌شود.
                        {canManage&&<button type="button" disabled={blocked}
                          onClick={()=>startCorrectingDocument(detailedDocument)}>
                          اصلاح فاکتور صادرشده</button>}
                        {canManage&&<button type="button" disabled={blocked} onClick={()=>{
                          setReturnTarget(detailedDocument.id);setReturnReason('');
                          setReturnMode('full');setReturnQuantities({});
                        }}>ثبت مرجوعی کامل سند</button>}</p>:
                      <p className="sac-audit-notice">
                        {detailedDocument.contractorJobIds?
                          'صورتحساب متصل به پیمانکار نیاز به تطبیق مستقل اقلام دارد.':
                          detailedDocument.returnedAmount?
                          'این سند دارای مرجوعی جزئی است. اصلاح یا مرجوعی کاملِ سند اصلی مجاز نیست؛ از مرجوعی جزئی با مقدار باقی‌مانده استفاده کنید.':
                          'این فاکتور دارای تسویه است. ابتدا دریافت‌ها یا پرداخت‌های مرتبط را با سند برگشت معتبر اصلاح کنید.'}
                      </p>}
                    {canManage&&
                      detailedDocument.total-detailedDocument.allocated-
                      (detailedDocument.returnedAmount||0)>0&&
                      !detailedDocument.contractorJobIds&&<button type="button"
                        disabled={blocked} onClick={()=>{
                          setReturnTarget(detailedDocument.id);setReturnReason('');
                          setReturnMode('partial');setReturnQuantities({});
                        }}>ثبت مرجوعی جزئی اقلام</button>}
                    {detailedDocument.allocated>0&&
                      sortMap(docKind==='invoice'?view.receipts:view.payments).filter(payment=>
                        !payment.reversed&&(payment.allocations||[]).some(a=>
                          a[docKind+'Id']===detailedDocument.id)).map(payment=>
                        <p className="sac-inline-info" key={payment.id}>
                          دریافت/پرداخت مرتبط <b dir="ltr">{payment.id}</b>:
                          {moneyText(payment.total)}
                          {canManage&&<button type="button" onClick={()=>{
                            gotoTab('journal');
                            setForms(p=>({...p,reverse:{...p.reverse,
                              journalId:payment.journalId}}));
                          }}>برگشت این تسویه در دفترکل</button>}</p>)}
                  </>}
                </div>
                {canManage&&returnTarget===detailedDocument.id&&
                  <form className="sac-cancel-form" onSubmit={submit(async()=>{
                    if(!validText(returnReason,1000)){
                      setState(p=>({...p,error:'علت مرجوعی معتبر لازم است.'}));return;
                    }
                    const selected=[];
                    if(returnMode==='partial'){
                      for(let i=0;i<detailedDocument.lines.length;i++){
                        const qty=parse(returnQuantities[i]||'0',true);
                        if(qty===null||qty>Number(detailedDocument.lines[i].quantity)-
                          (returnedLines[i]||0)){
                          setState(p=>({...p,error:'تعداد مرجوعی بیش از مقدار باقی‌مانده است.'}));return;
                        }
                        if(qty>0)selected.push({lineIndex:i,quantity:qty});
                      }
                      if(!selected.length){
                        setState(p=>({...p,error:'برای مرجوعی جزئی حداقل یک ردیف با تعداد مثبت انتخاب کنید.'}));return;
                      }
                    }
                    if(await execute(id=>({command:{
                      type:docKind+'.return',eventId:id,
                      [docKind+'Id']:detailedDocument.id,
                      returnId:'RET.'+id,postingDate:today,
                      reason:returnReason.trim(),
                      ...(returnMode==='partial'?{lines:selected}:{})
                    }}),returnMode==='partial'?
                      'مرجوعی جزئی و سند بستانکار/بدهکار مرتبط ثبت شد.':
                      'مرجوعی کامل و سند حسابداری برگشت ثبت شد.')){
                      setReturnTarget('');setReturnReason('');setReturnQuantities({});
                    }
                  })}>
                    {returnMode==='partial'&&<div className="sac-panel">
                      <strong>مقدار مرجوعی هر ردیف، بدون تغییر فاکتور اصلی</strong>
                      {(detailedDocument.lines||[]).map((line,i)=>{
                        const left=Number(line.quantity)-(returnedLines[i]||0);
                        return <Field key={i} label={line.description+' / قابل برگشت: '+
                          left.toLocaleString('fa-IR')}>
                          <input type="text" inputMode="numeric" dir="ltr" disabled={left<=0}
                            value={returnQuantities[i]||''} placeholder="۰"
                            onChange={e=>setReturnQuantities(q=>({...q,[i]:e.target.value}))}/>
                        </Field>;
                      })}
                      <p className="sac-audit-notice">اگر گردش انبار یا چک فعال به سند متصل باشد،
                        مرجوعی جزئی تا زمان تطبیق ایمن آن‌ها در میزبان رد می‌شود.</p>
                    </div>}
                    <Field label={returnMode==='partial'?'علت مرجوعی جزئی':'علت مرجوعی کامل'}>
                      <input required maxLength={1000}
                      value={returnReason} onChange={e=>setReturnReason(e.target.value)}/></Field>
                    <Action disabled={blocked||!validText(returnReason,1000)}>
                      {returnMode==='partial'?'تأیید مرجوعی جزئی':'تأیید مرجوعی و برگشت دفترکل'}</Action>
                    <button type="button" onClick={()=>{setReturnTarget('');setReturnReason('');setReturnQuantities({});}}>
                      انصراف</button>
                  </form>}
              </section>}
              {canManage&&cancelTarget&&['draft','approved'].includes(currentDocs[cancelTarget]?.status)&&
                <form className="sac-cancel-form" onSubmit={submit(async()=>{
                  if(!validText(cancelReason,1000)){setState(p=>({...p,error:'دلیل لغو سند الزامی است.'}));return;}
                  if(await execute(id=>({command:{type:docKind+'.cancel',
                    eventId:id,[docKind+'Id']:cancelTarget,reason:cancelReason.trim()}}),'سند لغو شد.')){
                    setCancelTarget('');setCancelReason('');
                  }
                })}>
                  <Field label="دلیل لغو سند"><input required maxLength={1000} value={cancelReason}
                    onChange={e=>setCancelReason(e.target.value)}/></Field>
                  <Action disabled={blocked}>ثبت لغو سند</Action>
                  <button type="button" onClick={()=>setCancelTarget('')}>انصراف</button>
                </form>}
              </Panel>}
            {(canManage||canDraft)&&(tab==='bill'||invoiceComposerOpen)&&<Panel compact={tab==='invoice'} title={correctionTarget?'اصلاح فاکتور '+correctionTarget:
              editTarget?'ویرایش فاکتور '+editTarget:tab==='invoice'?'ثبت فاکتور جدید':'ثبت صورتحساب خرید'}
              description="۱. مشتری و تاریخ را مشخص کنید. ۲. شرح، تعداد و قیمت اقلام را بنویسید. ۳. پیش‌نویس را ذخیره کنید.">
              <form className="sac-invoice-editor" noValidate={wizardEnabled}
                inert={busy||pendingRetry} aria-busy={busy||pendingRetry}
                onSubmit={submit(async()=>{
                if(!validateInvoiceSubmission())return;
                if(await execute(id=>{
                  const built=buildStandaloneInvoiceCommand({
                    kind:docKind,...forms.document,tax:documentTax,
                    documentId:editTarget||forms.document.documentId,
                    lines:rows,eventId:id,accounts,items,today});
                  if(built.error)return built;
                  if(correctionTarget){
                    built.command={
                      type:docKind+'.correct',eventId:id,
                      [docKind+'Id']:correctionTarget,replacementId:built.command[docKind+'Id'],
                      postingDate:correctionDate,documentDate:built.command.documentDate,
                      reason:correctionReason.trim(),lines:built.command.lines,
                      discount:built.command.discount,tax:built.command.tax,
                      ...(built.command.dueDate?{dueDate:built.command.dueDate}:{}),
                      ...(built.command.taxRuleId?{taxRuleId:built.command.taxRuleId}:{}),
                      ...(built.command.note?{note:built.command.note}:{})};
                  }else if(editTarget)built.command.type=docKind+'.update';
                  return built;
                },correctionTarget?'سند قبلی برگشت داده شد و پیش‌نویس جایگزین ایجاد شد؛ برای اثر مالی جدید آن را تأیید و صادر کنید.':
                  editTarget?'اصلاح پیش‌نویس با رویداد جدید ثبت شد.':
                  'پیش‌نویس سند در میزبان ثبت شد.')){
                    reset('document');setRows([makeLine()]);setEditTarget('');
                    setCorrectionTarget('');setCorrectionReason('');
                    if(tab==='invoice')setInvoiceComposerOpen(false);
                    setInvoiceWizardStep(0);setInvoiceWizardChecked({});
                  }
              })}>
                {tab==='invoice'&&<InvoiceWizardNavigation
                  step={invoiceWizardStep} mode={invoiceWizardMode}
                  onModeChange={mode=>{setInvoiceWizardMode(mode);setInvoiceWizardError('');}}
                  onStepChange={goWizardStep} disabled={busy||pendingRetry}
                  hasUnsavedChanges={hasUnsavedInvoice}/>}
                {tab==='invoice'&&invoiceWizardError&&<p role="alert"
                  className="sac-wizard-alert">{invoiceWizardError}</p>}
                {tab==='invoice'&&<div className="sac-invoice-commandbar"
                  role="toolbar" aria-label="عملیات سریع فاکتور">
                  <div className="sac-invoice-commandbar-title">
                    <strong>{editTarget?'ویرایش پیش‌نویس':correctionTarget?
                      'پیش‌نویس اصلاحی':'فاکتور فروش جدید'}</strong>
                    <small>سند تا قبل از تأیید و صدور، فقط پیش‌نویس است.</small>
                  </div>
                  <div className="sac-invoice-commandbar-actions">
                    <button type="button" onClick={()=>addInvoiceRow()}
                      disabled={busy||pendingRetry||rows.length>=1000}>
                      <Plus size={16}/> ردیف جدید
                    </button>
                    <button type="submit" className="sac-primary"
                      disabled={draftBlocked|| (!!correctionTarget&&
                        (!validText(correctionReason,1000)||!validPostingDate(correctionDate)||
                          correctionDate<currentDocs[correctionTarget]?.postingDate))}>
                      {editTarget?'ذخیره ویرایش':correctionTarget?'ثبت اصلاحیه':'ذخیره پیش‌نویس'}
                    </button>
                    <button type="button" className="sac-back-button"
                      onClick={()=>closeInvoiceComposer()} disabled={busy||pendingRetry}>
                      <ArrowRight size={16}/> فهرست فاکتورها
                    </button>
                  </div>
                </div>}
                <div className="sac-grid sac-wizard-block" data-invoice-step="0"
                  id="sac-wizard-panel-document"
                  hidden={wizardEnabled&&invoiceWizardStep!==0}>
                  <Field label="شماره داخلی فاکتور">{editTarget?
                    <input readOnly dir="ltr" value={editTarget}/>:
                    idInput('document','documentId','INV-001')}</Field>
                  <Field label={docKind==='invoice'?'مشتری':'تأمین‌کننده'}>
                    <input type="search" value={partyQuery} placeholder="جست‌وجوی نام یا کد شخص"
                      aria-label="جست‌وجوی مشتری یا تأمین‌کننده"
                      onChange={e=>setPartyQuery(e.target.value)}/>
                    <select required disabled={!!correctionTarget} value={forms.document.partyId}
                      onChange={e=>f('document','partyId',e.target.value)}>
                      {options(partyOptions(docKind==='invoice'?customers:vendors),'انتخاب طرف‌حساب')}</select></Field>
                  <Field label="تاریخ سند">{dateInput('document','documentDate')}</Field>
                  {correctionTarget&&<>
                    <Field label="تاریخ برگشت قطعی"><AccountingJalaliField
                      max={today} value={correctionDate} onChange={setCorrectionDate}/></Field>
                    <Field label="علت اصلاح (الزامی)"><input required maxLength={1000}
                      disabled={busy||pendingRetry}
                      value={correctionReason} onChange={e=>setCorrectionReason(e.target.value)}
                      placeholder="دلیل اصلاح سند صادرشده"/></Field>
                  </>}
                  {wizardEnabled&&invoiceWizardChecked[0]&&wizardIssues[0]&&
                    <p className="sac-wizard-field-error" role="alert">{wizardIssues[0]}</p>}
                </div>
                <section className="sac-wizard-block sac-wizard-tax" data-invoice-step="2"
                  id="sac-wizard-panel-tax" hidden={wizardEnabled&&invoiceWizardStep!==2}>
                  <h3 className="sac-wizard-section-title">تخفیف و مالیات</h3>
                  <div className="sac-grid">
                  <Field label={`تخفیف (${unitLabel})`}>{amountInput('document','discount')}</Field>
                  <Field label="سیاست مالیاتی"><select value={forms.document.taxRuleId}
                    onChange={e=>f('document','taxRuleId',e.target.value)}>
                    <option value="">مبلغ دستی بدون سیاست تنظیم‌شده</option>
                    {sortMap(view.taxRules).filter(r=>
                      r.history?.some(v=>v.effectiveFrom<=forms.document.documentDate)).map(r=>
                      <option key={r.id} value={r.id}>
                        {r.name} ({((r.history.filter(v=>
                          v.effectiveFrom<=forms.document.documentDate).slice(-1)[0]
                            ?.rateBasisPoints||0)/100).toLocaleString('fa-IR')}٪)</option>)}
                  </select></Field>
                  <Field label={`مالیات (${unitLabel})`}>
                    <input required dir="ltr" inputMode="numeric"
                      readOnly={!!forms.document.taxRuleId} value={documentTax}
                      onChange={e=>f('document','tax',e.target.value)}/>
                  </Field>
                  </div>
                  <p className="sac-wizard-note">محاسبهٔ مبلغ در این مرحله صرفاً پیش‌نمایش است؛
                    تا ذخیره و تأیید و صدور جداگانه انجام نشود، درآمدی ثبت نمی‌شود.</p>
                  {wizardEnabled&&invoiceWizardChecked[2]&&wizardIssues[2]&&
                    <p role="alert" className="sac-wizard-field-error">{wizardIssues[2]}</p>}
                </section>
                <section className="sac-wizard-block sac-wizard-due" data-invoice-step="3"
                  id="sac-wizard-panel-due" hidden={wizardEnabled&&invoiceWizardStep!==3}>
                  <h3 className="sac-wizard-section-title">پرداخت و سررسید</h3>
                  <p className="sac-wizard-note">در این مرحله فقط زمان پرداخت را مشخص می‌کنید.
                    ثبت واقعی دریافت وجه پس از صدور سند، از بخش دریافت و پرداخت انجام می‌شود.</p>
                  <div className="sac-grid">
                    <Field label="سررسید پرداخت (اختیاری)"><AccountingJalaliField
                      max="9999-12-31" required={false}
                      value={forms.document.dueDate||''}
                      onChange={dueDate=>f('document','dueDate',dueDate)}/></Field>
                    <Field label="یادداشت (اختیاری)" wide><input maxLength={1000}
                      value={forms.document.note} onChange={e=>f('document','note',e.target.value)}/></Field>
                  </div>
                  {wizardEnabled&&invoiceWizardChecked[3]&&wizardIssues[3]&&
                    <p role="alert" className="sac-wizard-field-error">{wizardIssues[3]}</p>}
                </section>
                <div className="sac-subheading" data-invoice-step="1"
                  hidden={wizardEnabled&&invoiceWizardStep!==1}><h3>جدول ثبت کالا و خدمات</h3><button type="button"
                  onClick={()=>addInvoiceRow()}>
                  <Plus size={15}/> افزودن ردیف</button></div>
                <p className="sac-invoice-shortcuts" data-invoice-step="1"
                  hidden={wizardEnabled&&invoiceWizardStep!==1}>
                  شرح، تعداد و قیمت را بنویسید. برای رفتن به سلول بعدی Enter بزنید.</p>
                <details className="sac-disclosure sac-invoice-extras" data-invoice-step="1"
                  hidden={wizardEnabled&&invoiceWizardStep!==1}>
                  <summary>ابزارهای بیشتر: جست‌وجوی کالا، قالب‌های آماده و میانبرها</summary>
                  <p className="sac-invoice-shortcuts">Tab / Shift+Tab: حرکت بین سلول‌ها | Ctrl+Insert: سطر جدید | Alt+Shift+D: کپی سطر | Ctrl+Delete: حذف سطر</p>
                <div className="sac-catalog-search">
                  <label>جست‌وجوی سریع کاتالوگ (نام، شناسه یا SKU)
                    <input type="search" aria-label="جست‌وجوی قلم کاتالوگ فاکتور"
                      value={invoiceCatalogSearch} placeholder="نام کالا یا کد را وارد کنید"
                      onChange={e=>setInvoiceCatalogSearch(e.target.value)}/>
                  </label>
                  <small>{invoiceCatalogMatches.length.toLocaleString('fa-IR')} قلم مطابق جست‌وجو؛ فقط ۱۵۰ نتیجه اول برای حفظ سرعت نمایش داده می‌شود. قیمت به‌صورت خودکار حدس زده نمی‌شود.</small>
                </div>
                <div className="sac-entry-template-bar" aria-label="قالب‌های ورود اطلاعات فاکتور">
                  <Field label="عنوان قالب ثبت اقلام"><input maxLength={100}
                    value={invoiceTemplateTitle}
                    onChange={e=>setInvoiceTemplateTitle(e.target.value)}
                    placeholder="مثلاً خدمات صحافی"/></Field>
                  <button type="button" disabled={busy}
                    onClick={exportInvoiceEntryTemplate}>ذخیره قالب اقلام (JSON)</button>
                  <Field label="نحوه فراخوانی قالب"><select value={invoiceTemplateImportMode}
                    onChange={e=>setInvoiceTemplateImportMode(e.target.value)}>
                    <option value="replace">جایگزینی ردیف‌های فرم</option>
                    <option value="append">الحاق به ردیف‌های فرم</option>
                  </select></Field>
                  <Field label="فراخوانی قالب ذخیره‌شده">
                    <input aria-label="فراخوانی قالب اقلام" type="file" accept=".json,application/json"
                      onChange={async e=>{
                        const file=e.target.files?.[0];e.target.value='';
                        await importInvoiceEntryTemplate(file);
                      }}/>
                  </Field>
                  <small>قالب فقط ردیف‌هاست؛ مشتری، شرکت، تسویه و شماره سند از فایل وارد نمی‌شود.</small>
                </div>
                {templateBridge&&<div className="sac-template-library" aria-label="کتابخانه قالب‌های اقلام">
                  <strong>کتابخانه قالب‌های همین شرکت</strong>
                  <input type="search" aria-label="جست‌وجوی قالب اقلام" value={templateSearch}
                    onChange={e=>setTemplateSearch(e.target.value)} placeholder="جست‌وجوی نام قالب"/>
                  <select aria-label="انتخاب قالب داخلی اقلام" value={entryTemplateId}
                    onChange={e=>setEntryTemplateId(e.target.value)}>
                    <option value="">قالب جدید</option>
                    {entryLibrary.templates.filter(t=>t.title.includes(templateSearch)).map(t=><option
                      key={t.id} value={t.id}>{t.title}{t.id===entryLibrary.defaultId?' ★':''}</option>)}
                  </select>
                  <button type="button" onClick={()=>void saveTemplateToLibrary('entry')}>ذخیره در کتابخانه</button>
                  <button type="button" disabled={!entryTemplateId} onClick={()=>{
                    const template=entryLibrary.templates.find(t=>t.id===entryTemplateId);
                    if(template)loadEntryFromLibrary(template);
                  }}>فراخوانی</button>
                  <button type="button" disabled={!entryTemplateId} onClick={()=>void libraryAction('entry','default',entryTemplateId)}>پیش‌فرض</button>
                  <button type="button" disabled={!entryTemplateId} onClick={()=>void libraryAction('entry','duplicate',entryTemplateId)}>کپی قالب</button>
                  <button type="button" disabled={!entryTemplateId} onClick={()=>void libraryAction('entry','delete',entryTemplateId)}>حذف قالب</button>
                  <button type="button" onClick={()=>{setEntryTemplateId('');setInvoiceTemplateTitle('قالب جدید');}}>ایجاد قالب دیگر</button>
                </div>}
                </details>
                <div className="sac-invoice-canvas">
                <div className="sac-invoice-lines sac-wizard-block" data-invoice-step="1"
                  id="sac-wizard-panel-lines" hidden={wizardEnabled&&invoiceWizardStep!==1}>
                <div className="sac-invoice-columns" aria-hidden="true">
                  <span>شرح کالا یا خدمات</span><span>تعداد</span><span>قیمت واحد</span>
                  <span>جمع ردیف</span><span>عملیات</span>
                </div>
                {rows.map((row,i)=><div key={i} className="sac-doc-line sac-invoice-line" onKeyDown={invoiceKeyDown}>
                  <div className="sac-invoice-row-heading">ردیف {Number(i+1).toLocaleString('fa-IR')}</div>
                  <Field label="شرح"><input data-invoice-row={i} data-invoice-col={0} required maxLength={300} value={row.description}
                    disabled={busy||pendingRetry}
                    placeholder="نام کالا یا شرح خدمات"
                    onChange={e=>rowUpdate(i,'description',e.target.value)}/></Field>
                  <Field label="تعداد"><input data-invoice-row={i} data-invoice-col={1} required dir="ltr" inputMode="numeric"
                    disabled={busy||pendingRetry}
                    value={row.quantity} onChange={e=>rowUpdate(i,'quantity',e.target.value)}/></Field>
                  <Field label={`قیمت واحد (${unitLabel})`}><input data-invoice-row={i} data-invoice-col={2} required dir="ltr" inputMode="numeric"
                    disabled={busy||pendingRetry}
                    value={row.unitPrice} onChange={e=>rowUpdate(i,'unitPrice',e.target.value)}/></Field>
                  <output className="sac-invoice-line-total" aria-label={'جمع ردیف '+(i+1)}>
                    <span className="sac-invoice-total-caption" aria-hidden="true">جمع ردیف</span>
                    {(()=>{
                      const qty=parse(row.quantity),unit=parse(row.unitPrice,true);
                      const total=qty!==null&&unit!==null?qty*unit:null;
                      return total!==null&&Number.isSafeInteger(total)?
                        moneyText(total):'—';
                    })()}
                  </output>
                  <div className="sac-invoice-line-actions">
                    <button type="button" title="کپی ردیف" disabled={rows.length>=1000}
                      onClick={()=>addInvoiceRow(row)}>کپی</button>
                    <button type="button" disabled={rows.length===1} className="sac-remove"
                      onClick={()=>removeInvoiceRow(i)}>حذف</button>
                  </div>
                  <details className="sac-row-advanced">
                    <summary>حساب / کاتالوگ ردیف {Number(i+1).toLocaleString('fa-IR')}</summary>
                    <div className="sac-row-advanced-fields">
                      <Field label="سرفصل حساب"><select data-invoice-row={i}
                        data-invoice-col={3} required
                        value={row.accountId||(docKind==='invoice'?'4000':'5000')}
                        onChange={e=>rowUpdate(i,'accountId',e.target.value)}>
                        {candidates.map(a=><option key={a.id} value={a.id}>
                          {a.name} ({a.id})</option>)}</select></Field>
                      <Field label="قلم کاتالوگ (اختیاری)"><select
                        data-invoice-row={i} data-invoice-col={4} value={row.itemId}
                        onChange={e=>{const item=items[e.target.value];setRows(p=>p.map((l,idx)=>
                          idx===i?{...l,itemId:e.target.value,
                            description:item?.name||l.description}:l));}}>
                        {options([
                          ...(row.itemId&&items[row.itemId]&&!invoiceCatalogMatches.slice(0,150)
                            .some(x=>x.id===row.itemId)?[items[row.itemId]]:[]),
                          ...invoiceCatalogMatches.slice(0,150)
                        ],'بدون قلم کاتالوگ')}</select></Field>
                    </div>
                  </details>
                </div>)}
                <div className="sac-invoice-addline">
                  <button type="button" onClick={()=>addInvoiceRow()} disabled={rows.length>=1000}>
                    <Plus size={15}/> افزودن ردیف
                  </button>
                </div>
                {wizardEnabled&&invoiceWizardChecked[1]&&wizardIssues[1]&&
                  <p role="alert" className="sac-wizard-field-error">{wizardIssues[1]}</p>}
                </div>
                <aside className="sac-invoice-summary sac-wizard-block" data-invoice-step="4"
                  id="sac-wizard-panel-review" hidden={wizardEnabled&&invoiceWizardStep!==4}
                  aria-label="خلاصه مالی فاکتور">
                  <div className="sac-invoice-summary-heading">
                    <span>خلاصه فاکتور</span>
                    <strong>{rows.length.toLocaleString('fa-IR')} ردیف</strong>
                  </div>
                  <p className="sac-wizard-review-status">گام فعلی: {correctionTarget?
                    'پیش‌نویس اصلاحی':editTarget?'ویرایش پیش‌نویس':'ایجاد پیش‌نویس'}.
                    تأیید و صدور سند، عملیات جداگانه در فهرست فاکتورها هستند.</p>
                  <div className="sac-live-total" role="status">
                    <span><span>جمع اقلام</span><b>{documentPreview?moneyText(documentPreview.subtotal):'—'}</b></span>
                    <span><span>تخفیف</span><b>{documentPreview?moneyText(documentPreview.discount):'—'}</b></span>
                    <span><span>مالیات</span><b>{documentPreview?moneyText(documentPreview.tax):'—'}</b></span>
                    <strong><span>مبلغ نهایی</span><b>{documentPreview?moneyText(documentPreview.total):'—'}</b></strong>
                  </div>
                  <p className="sac-invoice-summary-note">مبالغ بر اساس مقادیر همین فرم محاسبه می‌شوند؛
                    {correctionTarget?' ثبت اصلاحیه، سند صادرشدهٔ قبلی را برگشت می‌دهد و جایگزین را به‌صورت پیش‌نویس می‌سازد.':
                      ' ذخیره پیش‌نویس به معنی صدور قطعی نیست.'}</p>
                  <p className="sac-wizard-impact-warning" role="note">
                    {correctionTarget?
                      'هشدار: ثبت اصلاحیه، سند صادرشدهٔ قبلی را برگشت می‌دهد و یک پیش‌نویس جدید می‌سازد. پیش از ادامه، مبلغ و طرف حساب را بازبینی کنید.':
                      'پس از ذخیرهٔ پیش‌نویس، مدیر می‌تواند آن را تأیید کند؛ صدور نهایی، دفترکل را تغییر می‌دهد. وضعیت خروج انبار و بهای تمام‌شده باید جداگانه کنترل شود.'}
                  </p>
                  <button type="submit" className="sac-primary sac-summary-save"
                    disabled={draftBlocked|| (!!correctionTarget&&
                      (!validText(correctionReason,1000)||!validPostingDate(correctionDate)||
                        correctionDate<currentDocs[correctionTarget]?.postingDate))}>
                    {correctionTarget?'ثبت اصلاحیه و ایجاد پیش‌نویس جایگزین':
                      editTarget?'ذخیره ویرایش':'ذخیره پیش‌نویس'}
                  </button>
                </aside>
                </div>
                {wizardEnabled&&<div className="sac-wizard-sticky-footer"
                  role="group" aria-label="وضعیت و اقدامات مرحله فعلی فاکتور">
                  <div className="sac-wizard-sticky-amount">
                    <span>مبلغ نهایی · {unitLabel}</span>
                    <strong dir="auto">{documentPreview?moneyText(documentPreview.total):'نامشخص'}</strong>
                    <small>پیش‌نویس ذخیره‌نشده · مرحله {(invoiceWizardStep+1).toLocaleString('fa-IR')}/۵</small>
                  </div>
                  <div className="sac-wizard-sticky-actions">
                    {invoiceWizardStep>0&&<button type="button"
                      disabled={busy||pendingRetry} onClick={()=>goWizardStep(invoiceWizardStep-1)}>
                      قبلی
                    </button>}
                    {invoiceWizardStep<4?<button key="wizard-next" type="button" className="sac-primary"
                      disabled={busy||pendingRetry}
                      onClick={event=>{event.preventDefault();goWizardStep(invoiceWizardStep+1);}}>
                      ادامه: {INVOICE_WIZARD_STEPS[invoiceWizardStep+1].title}
                    </button>:<button key="wizard-save" type="submit" className="sac-primary"
                      disabled={draftBlocked}>{
                        correctionTarget?'ثبت اصلاحیه':editTarget?'ذخیره ویرایش':'ذخیره پیش‌نویس'
                      }</button>}
                  </div>
                </div>}
                <div className="sac-form-actions"><Action disabled={draftBlocked||
                  (!!correctionTarget&&(!validText(correctionReason,1000)||
                    !validPostingDate(correctionDate)||
                    correctionDate<currentDocs[correctionTarget]?.postingDate))}>
                  {correctionTarget?'برگشت سند و ساخت پیش‌نویس اصلاحی':
                    editTarget?'ثبت اصلاح پیش‌نویس':'ثبت پیش‌نویس'}</Action>
                  <button type="button" className="sac-back-button" disabled={busy||pendingRetry}
                    onClick={()=>tab==='invoice'?closeInvoiceComposer():gotoTab('overview')}>
                    <ArrowRight size={16}/> بازگشت بدون ثبت
                  </button>
                </div>
              </form></Panel>}
            {canManage&&tab==='invoice'&&!invoiceComposerOpen&&
              <details className="sac-disclosure sac-admin-tools">
                <summary>قالب‌ها و سربرگ فاکتور (ابزارهای پیشرفته)</summary>
              <Panel title="هویت‌های صادرکننده و سربرگ"
              description="صادرکننده چاپی از دفتر حسابداری مستقل است؛ انتخاب آن فقط سربرگ و فایل خروجی را تغییر می‌دهد، نه ثبت حسابداری را.">
              {templateBridge&&<div className="sac-template-library">
                <label>انتخاب صادرکننده <select aria-label="انتخاب صادرکننده چاپی" value={issuerId}
                  onChange={e=>{const id=e.target.value;setIssuerId(id);
                    const issuer=issuerLibrary.templates.find(t=>t.id===id);
                    setIssuerProfile(issuer?.data?.profile||{legalName:'',nationalId:'',economicCode:'',
                      postalCode:'',phone:'',address:''});}}>
                  <option value="">هویت ثبت‌شده دفتر حسابداری</option>
                  {issuerLibrary.templates.map(t=><option key={t.id} value={t.id}>
                    {t.title}{t.id===issuerLibrary.defaultId?' ★':''}</option>)}
                </select></label>
                <button type="button" onClick={()=>{
                  setIssuerId('');setIssuerProfile({legalName:'',nationalId:'',economicCode:'',
                    postalCode:'',phone:'',address:''});}}>صادرکننده جدید</button>
                <button type="button" disabled={!issuerProfile.legalName.trim()}
                  onClick={()=>void saveTemplateToLibrary('issuer')}>ذخیره صادرکننده</button>
                <button type="button" disabled={!issuerId}
                  onClick={()=>void libraryAction('issuer','default',issuerId)}>پیش‌فرض</button>
                <button type="button" disabled={!issuerId}
                  onClick={()=>void libraryAction('issuer','duplicate',issuerId)}>کپی هویت</button>
                <button type="button" disabled={!issuerId}
                  onClick={()=>void libraryAction('issuer','delete',issuerId)}>حذف</button>
              </div>}
              <div className="sac-grid">
                {[['legalName','عنوان قانونی'],['nationalId','شناسه ملی'],
                  ['economicCode','کد اقتصادی'],['postalCode','کد پستی'],
                  ['phone','تلفن'],['address','نشانی']].map(([key,label])=><Field key={key} label={label}>
                  <input value={issuerProfile[key]||''} maxLength={key==='address'?500:150}
                    onChange={e=>setIssuerProfile(p=>({...p,[key]:e.target.value}))}/>
                </Field>)}
              </div>
              <small>تا پیش از ذخیره، تغییرات هویت در پیش‌نمایش و خروجی اعمال نمی‌شوند؛ هویت دفتر اصلی باقی می‌ماند.</small>
            </Panel>
              <Panel title="طراح بصری قالب فاکتور"
              description="قالب چاپ، بدون ایجاد رویداد مالی، فقط برای شرکت انتخاب‌شده ذخیره می‌شود. پس از انتخاب قالب سفارشی، خروجی PDF/PNG از همین طرح ساخته می‌شود.">
              <div className="sac-template-library">
                <button type="button" onClick={()=>setPrintDesignerOpen(p=>!p)}>
                  {printDesignerOpen?'بستن طراح':'باز کردن طراح قالب چاپ'}</button>
                {templateBridge&&<><select aria-label="قالب چاپ ذخیره‌شده" value={printTemplateId}
                  onChange={e=>{const id=e.target.value;setPrintTemplateId(id);
                    const t=printLibrary.templates.find(t=>t.id===id);
                    if(t){try{setPrintTemplate(validatePrintTemplate(t.data));setInvoicePrintLayout('custom');}
                      catch(err){setState(p=>({...p,error:err.message}));}}}}>
                  <option value="">قالب جدید</option>
                  {printLibrary.templates.map(t=><option value={t.id} key={t.id}>{t.title}
                    {t.id===printLibrary.defaultId?' ★':''}</option>)}
                </select>
                <button type="button" onClick={()=>void saveTemplateToLibrary('print')}>ذخیره قالب چاپ</button>
                <button type="button" disabled={!printTemplateId}
                  onClick={()=>void libraryAction('print','default',printTemplateId)}>پیش‌فرض شرکت</button>
                <button type="button" disabled={!printTemplateId}
                  onClick={()=>void libraryAction('print','duplicate',printTemplateId)}>کپی</button>
                <button type="button" disabled={!printTemplateId}
                  onClick={()=>void libraryAction('print','delete',printTemplateId)}>حذف</button></>}
                <button type="button" onClick={()=>{
                  setPrintTemplateId('');setPrintTemplate({...DEFAULT_PRINT_TEMPLATE,
                    fields:DEFAULT_PRINT_TEMPLATE.fields.map(f=>({...f})),table:{...DEFAULT_PRINT_TEMPLATE.table}});
                  setPrintDesignerOpen(true);
                }}>قالب چاپ جدید</button>
                {detailedDocument&&<><button type="button" disabled={busy}
                  onClick={()=>{setInvoicePrintLayout('custom');void buildCustomPrintExport({
                    template:printTemplate,kind:'invoice',doc:detailedDocument,
                    party:parties[detailedDocument.partyId]?.name||detailedDocument.partyId,
                    company:printCompanyProfile,currency:ledgerCurrency,
                    format:'pdf',pattern:filenamePattern}).then(downloadStandaloneBlob)
                    .catch(err=>setState(p=>({...p,error:err.message})));}}>PDF قالب سفارشی</button></>}
              </div>
              {printDesignerOpen&&<AccountingPrintDesigner value={printTemplate} onChange={setPrintTemplate}
                disabled={busy} context={{kind:'invoice',doc:detailedDocument,
                  party:detailedDocument?parties[detailedDocument.partyId]?.name:'مشتری نمونه',
                  company:printCompanyProfile,currency:ledgerCurrency}}/>}
            </Panel></details>}
          </>}
          {tab==='parties'&&<>
            <PersonalParsianInvoices api={api} section="parties" fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear}/>
            {historicalDebtors.length>0&&<Panel title="بدهکاران منتقل‌شده از پارسیان"
              description="این مانده‌ها از حساب‌های ثبت‌شده دفترکل پارسیان هستند؛ نه فاکتورهای جدید تراز. ارتباط با تسویه عملیاتی هنوز جداست.">
              <Field label="جست‌وجوی بدهکار">
                <input type="search" value={historicalDebtorSearch}
                  onChange={e=>setHistoricalDebtorSearch(e.target.value)}
                  placeholder="نام یا کد حساب"/>
              </Field>
              <DataTable cols={['کد حساب پارسیان','نام بدهکار','مانده ریال','جزئیات']}
                empty="حساب بدهکار با مانده مثبت پیدا نشد."
                rows={historicalDebtors.map(d=><tr key={d.sourceAccountId}>
                  <td dir="ltr">{d.sourceAccountId}</td>
                  <td>{d.name}</td><td>{moneyText(d.balanceRial)}</td>
                  <td><button type="button" onClick={()=>displayHistoricDetails(d.sourceAccountId)}>
                    ریزگردش حساب</button></td></tr>)}/>
              <p>جمع مانده بدهکاران تاریخی: <strong>{moneyText(historicalDebtors.reduce((sum,p)=>sum+p.balanceRial,0))}</strong></p>
            </Panel>}
            {historicalDebtors.length>0&&historicalBankAccounts.length>0&&canManage&&<Panel title="ثبت وصول طلب تاریخی در دفترکل"
              description="مبلغ بدهکار پارسیان کاهش و مانده حساب صندوق/بانک منتخب افزایش می‌یابد. این یک سند دوطرفه دفترکل است، نه تسویه فاکتور قدیمی یا صدور درآمد جدید.">
              <form className="sac-grid" onSubmit={submit(async()=>{
                const d=accounts[historicalReceipt.debtorId];
                const bank=accounts[historicalReceipt.bankId];
                const amount=parse(historicalReceipt.amount);
                if(!d||!/^ps\.parsian\.account\.t\.12\.2\.[0-9]+$/.test(d.id)||
                  !bank||!/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.test(bank.id)||
                  d.kind!=='asset'||bank.kind!=='asset'||
                  amount===null||amount>d.debitMinusCredit||
                  !validPostingDate(historicalReceipt.postingDate)){
                  setState(p=>({...p,error:'مشتری، بانک، تاریخ یا مبلغ وصول تاریخی معتبر نیست.'}));
                  return;
                }
                const note='وصول طلب تاریخی پارسیان / '+d.id+
                  (historicalReceipt.note.trim()?' / '+historicalReceipt.note.trim():'');
                if(note.length>1000||/[\x00-\x1f\x7f]/.test(note)){
                  setState(p=>({...p,error:'شرح وصول معتبر نیست.'}));return;
                }
                const accepted=window.confirm(
                  'تأیید ثبت وصول طلب تاریخی به مبلغ '+moneyText(amount)+
                  '\nبدهکار: '+d.name+'\nحساب مقصد: '+bank.name+
                  '\nاین کار یک سند مالی جدید در دفتر کل ثبت می‌کند. ادامه می‌دهید؟');
                if(!accepted)return;
                const succeeded=await execute(id=>buildStandaloneManualCommand({
                  eventId:id,postingDate:historicalReceipt.postingDate,note,
                  lines:[
                    {accountId:bank.id,debit:String(amount),credit:'0'},
                    {accountId:d.id,debit:'0',credit:String(amount)},
                  ],accounts,today,
                }));
                if(succeeded)setHistoricalReceipt({
                  debtorId:'',bankId:'',amount:'',postingDate:today,note:''});
              })}>
                <Field label="بدهکار تاریخی">
                  <select required value={historicalReceipt.debtorId}
                    onChange={e=>setHistoricalReceipt(s=>({...s,debtorId:e.target.value}))}>
                    <option value="">انتخاب مشتری</option>
                    {historicalDebtors.map(d=><option value={d.sourceAccountId}
                      key={d.sourceAccountId}>{d.name} ({moneyText(d.balanceRial)})</option>)}
                  </select>
                </Field>
                <Field label="حساب مقصد صندوق / بانک پارسیان">
                  <select required value={historicalReceipt.bankId}
                    onChange={e=>setHistoricalReceipt(s=>({...s,bankId:e.target.value}))}>
                    <option value="">انتخاب بانک / صندوق</option>
                    {historicalBankAccounts.map(b=><option key={b.id} value={b.id}>
                      {b.name} ({b.id})</option>)}
                  </select>
                </Field>
                <Field label="مبلغ وصول (ریال)"><input required dir="ltr"
                  inputMode="numeric" value={historicalReceipt.amount}
                  onChange={e=>setHistoricalReceipt(s=>({...s,amount:e.target.value}))}/>
                </Field>
                <Field label="تاریخ ثبت"><AccountingJalaliField max={today}
                  value={historicalReceipt.postingDate}
                  onChange={postingDate=>setHistoricalReceipt(s=>({...s,postingDate}))}/>
                </Field>
                <Field label="شرح اختیاری"><input maxLength={750}
                  value={historicalReceipt.note} placeholder="شماره رسید یا توضیح"
                  onChange={e=>setHistoricalReceipt(s=>({...s,note:e.target.value}))}/>
                </Field>
                <div className="sac-form-actions"><Action disabled={blocked}>
                  ثبت سند وصول تاریخی</Action></div>
              </form>
            </Panel>}
            <Panel title="طرف‌حساب‌ها" description="مانده تاریخی دفترکل و مانده فاکتورهای جدید تفکیک شده‌اند. مانده تاریخی دوباره به اسناد عملیاتی افزوده نشده است.">
              <DataTable cols={['شناسه','نام','نقش','سقف اعتبار','مانده تاریخی','دریافتنی جدید','پرداختنی جدید','گردش','ویرایش']}
                empty="هیچ شخصی در دفتر ثبت نشده است."
                focusTarget={searchTarget?.kind==='party'?searchTarget:null}
                rows={historicalPartyAccounts.map(p=><tr key={p.id}
                  data-accounting-search-kind="party" data-accounting-search-id={p.id}>
                  <td dir="ltr">{p.id}</td>
                  <td>{p.name}</td><td>{p.kind==='both'?'مشتری و تأمین‌کننده':
                    p.kind==='vendor'?'تأمین‌کننده':'مشتری'}</td>
                  <td>{p.creditLimit===null||p.creditLimit===undefined?'نامحدود':moneyText(p.creditLimit)}</td>
                  <td>{signedText(p.historicRial)}</td>
                  <td>{debitText(p.receivable)}</td>
                  <td>{creditText(p.payable)}</td>
                  <td>{p.legacyId&&<button type="button" onClick={()=>displayHistoricDetails(p.legacyId)}>
                    ریزگردش</button>}</td>
                  <td>{canManage&&<button type="button" onClick={()=>{
                    setPartyEditing(p.id);
                    setForms(s=>({...s,party:{partyId:p.id,name:p.name,kind:p.kind,
                      creditLimit:p.creditLimit===null||p.creditLimit===undefined?'':String(p.creditLimit)}}));
                    setPartyEditReason('');
                  }}>ویرایش مشخصات</button>}
                    {!!p.changeHistory?.length&&<details><summary>
                      {p.changeHistory.length.toLocaleString('fa-IR')} اصلاح ثبت‌شده</summary>
                      {p.changeHistory.map(item=><p key={item.eventId}>
                        {displayAccountingDate(item.at.slice(0,10))}: {item.reason}
                        {' / '}{item.before.name} ← {item.after.name}</p>)}
                    </details>}</td></tr>)} /></Panel>
            {(canManage||canDraft)&&<Panel title={partyEditing?'ویرایش شخص '+partyEditing:'ثبت شخص جدید'}>
              <form className="sac-grid" onSubmit={submit(async()=>{
              const x=forms.party;
              const credit=x.creditLimit.trim()===''?null:parseStandaloneToman(x.creditLimit,{allowZero:true});
              if(!validId(x.partyId)||!validText(x.name)||credit===null&&x.creditLimit.trim()!==''){
                setState(p=>({...p,error:'شناسه و نام معتبر لازم است.'}));return;}
              if(partyEditing&&!validText(partyEditReason,1000)){
                setState(p=>({...p,error:'دلیل اصلاح مشخصات شخص الزامی است.'}));return;}
              if(await execute(id=>({command:partyEditing?{
                type:'party.update',eventId:id,partyId:partyEditing,name:x.name.trim(),
                kind:x.kind,creditLimit:credit,reason:partyEditReason.trim(),
              }:{
                type:'party.register',eventId:id,
                partyId:x.partyId,name:x.name.trim(),kind:x.kind,creditLimit:credit,
              }}),partyEditing?'اصلاح شخص با تاریخچه معتبر ثبت شد.':'شخص جدید ثبت شد.')){
                reset('party');setPartyEditing('');setPartyEditReason('');
              }
            })}>
              <Field label="شناسه">{partyEditing?<input dir="ltr" readOnly value={partyEditing}/>:
                idInput('party','partyId','PERSON-001')}</Field>
              <Field label="نام">{textInput('party','name')}</Field>
              <Field label="نقش"><select value={forms.party.kind} onChange={e=>f('party','kind',e.target.value)}>
                <option value="customer">مشتری</option><option value="vendor">تأمین‌کننده</option>
                <option value="both">هر دو</option></select></Field>
              <Field label="سقف اعتبار مشتری (خالی = نامحدود)"><input
                dir="ltr" inputMode="numeric" placeholder={'به '+unitLabel}
                value={forms.party.creditLimit} onChange={e=>f('party','creditLimit',e.target.value)}/></Field>
              {partyEditing&&<Field label="علت ویرایش"><input required maxLength={1000}
                value={partyEditReason} onChange={e=>setPartyEditReason(e.target.value)}/></Field>}
              <div className="sac-form-actions"><Action disabled={draftBlocked}>
                {partyEditing?'ثبت تغییرات شخص':'ثبت شخص'}</Action>
                {partyEditing&&<button type="button" onClick={()=>{
                  setPartyEditing('');setPartyEditReason('');reset('party');
                }}>انصراف از ویرایش</button>}</div>
            </form></Panel>}
          </>}
          {tab==='migration'&&<>
            <PersonalParsianExtended api={api} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear} section="all"/>
            <PersonalParsianInvoices api={api} section="parties" fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear}/>
            <ProviderCsvMigration api={api} canAdmin={canAdmin}/>
            <ParsianRawArchiveExplorer api={api} canAdmin={canAdmin}/>
            {!historical?<Panel title="سوابق پارسیان"
              description="این دفتر فاقد بسته معتبر اطلاعات تاریخی پارسیان است.">
              <Empty>فقط در دفتر آزمایشی انتقال، آرشیو تاریخی نمایش داده می‌شود.</Empty>
            </Panel>:<>
              <Panel title="اطلاعات واقعی منتقل‌شده"
                description={historical.sourceStatus}>
                <div className="sac-metrics">
                  <div className="sac-metric"><span>جدول‌های آرشیوشده</span>
                    <strong>{historical.archiveBaseTables.toLocaleString('fa-IR')}</strong></div>
                  <div className="sac-metric"><span>سطرهای آرشیوشده</span>
                    <strong>{historical.archiveRows.toLocaleString('fa-IR')}</strong></div>
                  <div className="sac-metric"><span>گروه فاکتورهای تاریخی</span>
                    <strong>{historical.historicalInvoiceGroups.toLocaleString('fa-IR')}</strong></div>
                </div>
                <p>اسناد مالیِ انتقال‌یافته در «حساب‌ها و دفترکل» هستند. فاکتورهای
                  قدیمی این بخش آرشیوی‌اند و دوباره بدهکاری ایجاد نمی‌کنند.</p>
              </Panel>
              <Panel title="لیست بدهکاران پارسیان" description="فقط مانده مثبت حساب‌های دریافتنی دفترکل">
                <Field label="جست‌وجوی نام یا کد"><input type="search"
                  value={historicalDebtorSearch}
                  onChange={e=>setHistoricalDebtorSearch(e.target.value)}
                  placeholder="جست‌وجوی بدهکار"/></Field>
                <DataTable cols={['حساب','نام','مانده بدهکار (ریال)']}
                  empty="مانده بدهکار یافت نشد."
                  rows={historicalDebtors.map(d=><tr key={d.sourceAccountId}>
                    <td dir="ltr">{d.sourceAccountId}</td>
                    <td>{d.name}</td><td>{debitText(d.balanceRial)}</td></tr>)}/>
                <p>جمع مانده: <strong>{moneyText(historicalDebtors.reduce((sum,p)=>sum+p.balanceRial,0))}</strong></p>
              </Panel>
              <Panel title="فاکتورهای تاریخی پارسیان"
                description="نمایش خواندنیِ اسناد اصلی؛ قیمت، مالیات و تسویه را بدون نگاشت تأییدشده محاسبه یا ثبت مجدد نمی‌کنیم.">
                <Field label="جست‌وجوی شماره / تاریخ / نوع">
                  <input type="search" value={historicalInvoiceSearch}
                    onChange={e=>setHistoricalInvoiceSearch(e.target.value)}
                    placeholder="فاکتورهای قبلی پارسیان"/>
                </Field>
                <DataTable cols={['شماره','نوع سند','تاریخ شمسی','سطر','شماره سند دفترکل','جزئیات']}
                  empty="فاکتور تاریخی در این آرشیو پیدا نشد."
                  rows={historicalInvoices.map(f=><tr key={f.sourceId}>
                    <td>{f.number}</td><td>{f.kind}</td>
                    <td dir="ltr">{f.dateJalali}</td>
                    <td>{f.lineCount.toLocaleString('fa-IR')}</td>
                    <td dir="ltr">{f.linkedSanad}</td>
                    <td><button type="button" onClick={()=>setSelectedHistoricInvoice(f.sourceId)}>
                      دیدن اقلام</button></td></tr>)}/>
                {activeHistoricInvoice&&<div className="sac-historic-detail">
                  <h3>فاکتور پارسیان شماره {activeHistoricInvoice.number}</h3>
                  <p>نوع: {activeHistoricInvoice.kind} | تاریخ: {activeHistoricInvoice.dateJalali}
                    {' '}| کد طرف حساب: {activeHistoricInvoice.sourcePartyPath||'نامشخص'}
                    {' '}| وضعیت سند مرتبط: {activeHistoricInvoice.linkedJournalExists?
                      'شماره سند پیدا شد':'نیازمند تطبیق'}</p>
                  <p>تعداد و قیمت زیر، مقادیر خام ثبت‌شده پارسیان هستند.
                    بدون نگاشت رسمی تخفیف و مالیات، مانده فاکتور محاسبه نشده است.</p>
                  <DataTable cols={['ردیف اصلی','کالا / شرح','کد کالا','تعداد خام','قیمت خام','تخفیف خام']}
                    empty="ردیفی پیدا نشد."
                    rows={(activeHistoricInvoice.sourceRows||[]).map(l=><tr key={l.sourceRowId}>
                      <td>{l.sourceRowId}</td><td>{l.goodsName||'بدون شرح'}</td>
                      <td dir="ltr">{l.sourceGoodsCode}</td><td>{l.quantitySource}</td>
                      <td>{l.unitPriceSource}</td><td>{l.discountSource}</td></tr>)}/>
                  <button type="button" onClick={()=>setSelectedHistoricInvoice('')}>بستن جزئیات</button>
                </div>}
              </Panel>
              <Panel title="وضعیت چک و انبار منتقل‌شده"
                description="نمایش اطلاعات آرشیوشده، نه موجودی یا چک عملیاتی تأییدشده">
                <div className="sac-metrics">
                  <div className="sac-metric"><span>ردیف چک اصلی در پارسیان</span>
                    <strong>{historical.historicalCheques.toLocaleString('fa-IR')}</strong></div>
                  <div className="sac-metric"><span>ردیف اطلاعات مرتبط با چک</span>
                    <strong>{historical.historicalTopCheckRows.toLocaleString('fa-IR')}</strong></div>
                  <div className="sac-metric"><span>اقلام کاتالوگ پارسیان</span>
                    <strong>{historical.historicalProducts.toLocaleString('fa-IR')}</strong></div>
                </div>
                <p>چک‌های فعال، سررسیدها، ورود و خروج انبار و قیمت تمام‌شده
                  تا زمان بررسی معنای فیلدها و تطبیق با اسناد مالی نباید به‌عنوان
                  گردش عملیاتی جدید ساخته شوند.</p>
              </Panel>
            </>}
          </>}
          {tab==='cheques'&&<>
            <PersonalParsianExtended api={api} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear} section="due"/>
            <LiveCheques view={view} canManage={canManage} disabled={blocked}
              execute={execute} today={today} unit={unitLabel}
              onDraftChange={reportChildDraft}/>
            <Panel title="سوابق چک پارسیان" description="صرفاً آرشیو جدا از چک‌های عملیاتی جدید؛
              تا تطبیق منبع به‌عنوان چک زنده محسوب نمی‌شود.">
            {historical?<><div className="sac-metrics">
              <div className="sac-metric"><span>چک‌های اصلی ثبت‌شده</span>
                <strong>{historical.historicalCheques.toLocaleString('fa-IR')}</strong></div>
              <div className="sac-metric"><span>اطلاعات جانبی چک در منبع</span>
                <strong>{historical.historicalTopCheckRows.toLocaleString('fa-IR')}</strong></div>
            </div><p>وجود ردیف جانبی به معنی چک وصول‌نشده نیست.</p></>:
              <Empty>آرشیو پارسیان در این دفتر متصل نیست.</Empty>}
            </Panel></>}
          {tab==='items'&&<>
            <PersonalParsianExtended api={api} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear} section="goods"/>
            {historical&&<Panel title="وضعیت انبار انتقالی"
              description="کالاهای واردشده فعلاً کاتالوگ‌اند؛ موجودی و بهای تمام‌شده از سابقه پارسیان قطعی نشده است.">
              <p>{historical.historicalProducts.toLocaleString('fa-IR')} قلم در آرشیو پارسیان،
                {sortMap(items).length.toLocaleString('fa-IR')} قلم در کاتالوگ تراز. تا تطبیق
                موجودی و سند بهای تمام‌شده، سفارش یا فروش خودکار نباید به موجودی ساختگی متکی باشد.</p>
              <DataTable cols={['کد کالا','نام کالا','واحد منبع','مقدار خام پارسیان','وضعیت']}
                empty="قلم آرشیوشده‌ای وجود ندارد."
                rows={(historical.historicCatalogSourceRows||[]).map(x=><tr key={x.sourceGoodsCode}>
                  <td dir="ltr">{x.sourceGoodsCode}</td><td>{x.name}</td>
                  <td>{x.unitName||'نامشخص'}</td><td>{x.rawCountNumber||'نامشخص'}</td>
                  <td>تأیید موجودی نشده</td></tr>)}/>
            </Panel>}
            <Panel title="کاتالوگ کالا و خدمات" description="کالاهای دارای رهگیری از طریق عملیات انبار ثبت می‌شوند؛ خدمات موجودی فیزیکی ندارند.">
              <DataTable cols={['شناسه','SKU','نام','نوع','واحد','وضعیت']}
                empty="هیچ کالا یا خدمتی ثبت نشده است." rows={sortMap(items).map(item=>
                  <tr key={item.id}><td dir="ltr">{item.id}</td><td>{item.sku}</td><td>{item.name}</td>
                  <td>{item.kind==='goods'?'کالا':'خدمت'}</td><td>{item.unit}</td>
                  <td>{item.active?'فعال':'غیرفعال'}</td></tr>)} /></Panel>
            {canManage&&<Panel title="ثبت قلم کاتالوگ"><form className="sac-grid" onSubmit={submit(async()=>{
              const x=forms.item;
              if(!validId(x.itemId)||!validText(x.sku,64)||!validText(x.name)||
                !validText(x.unit,40)){setState(p=>({...p,error:'فیلدهای قلم معتبر نیست.'}));return;}
              if(await execute(id=>({command:{type:'item.create',eventId:id,itemId:x.itemId,
                sku:x.sku.trim(),name:x.name.trim(),kind:x.kind,unit:x.unit.trim()}})))reset('item');
            })}>
              <Field label="شناسه">{idInput('item','itemId','ITEM-001')}</Field>
              <Field label="SKU">{textInput('item','sku','',64)}</Field>
              <Field label="نام">{textInput('item','name')}</Field>
              <Field label="نوع"><select value={forms.item.kind} onChange={e=>f('item','kind',e.target.value)}>
                <option value="service">خدمت</option><option value="goods">کالا</option></select></Field>
              <Field label="واحد">{textInput('item','unit','',40)}</Field>
              <div className="sac-form-actions"><Action disabled={blocked}>ثبت کالا / خدمت</Action></div>
            </form></Panel>}
            <LiveInventory view={view} canManage={canManage} canAdmin={canAdmin} disabled={blocked}
              execute={execute} today={today} unit={unitLabel}
              onDraftChange={reportChildDraft}/>
          </>}
          {tab==='settlements'&&<>
            <PersonalParsianBankMovements api={api} view={view} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear}/>
            <Panel title="دریافت‌ها و پرداخت‌ها" description="تمام مبالغ از رسیدها و پرداخت‌های ثبت‌شده موتور حسابداری خوانده می‌شوند.">
              {['receipts','payments'].map(key=><div key={key} className="sac-list-section">
                <h3>{key==='receipts'?'دریافت‌های ثبت‌شده':'پرداخت‌های ثبت‌شده'}</h3>
                <DataTable cols={['شناسه','طرف‌حساب','تاریخ','حساب نقدی','مبلغ','وضعیت']}
                  focusTarget={searchTarget?.kind===(key==='receipts'?'receipt':'payment')?
                    searchTarget:null}
                  empty="تراکنشی ثبت نشده است." rows={sortMap(view[key]).map(r=><tr key={r.id}
                    data-accounting-search-kind={key==='receipts'?'receipt':'payment'}
                    data-accounting-search-id={r.id}>
                    <td dir="ltr">{r.id}</td><td>{parties[r.partyId]?.name||r.partyId}</td>
                    <td>{displayAccountingDate(r.date)}</td><td>{accounts[r.accountId]?.name||r.accountId}</td>
                    <td>{moneyText(r.total)}</td>
                    <td>{r.reversed?'برگشت‌شده':'قطعی'}</td></tr>)} />
              </div>)}
            </Panel>
            {canManage&&<Panel title="تسویه سند صادرشده"
              description="هر دریافت/پرداخت مستقیماً به یک سند صادرشده با مانده مثبت تخصیص می‌یابد.">
              <form className="sac-grid" onSubmit={submit(async()=>{
                if(await execute(id=>buildStandaloneSettlementCommand({
                  ...forms.settlement,document:selected,eventId:id,accounts,today}),
                  'دریافت / پرداخت و تخصیص در دفترکل ثبت شد.'))reset('settlement');
              })}>
                <Field label="نوع تراکنش"><select value={forms.settlement.kind}
                  onChange={e=>setForms(p=>({...p,settlement:{...p.settlement,
                    kind:e.target.value,documentId:''}}))}>
                  <option value="receipt">دریافت از مشتری</option>
                  <option value="payment">پرداخت به تأمین‌کننده</option></select></Field>
                <Field label="سند دارای مانده"><select required value={forms.settlement.documentId}
                  onChange={e=>f('settlement','documentId',e.target.value)}>
                  <option value="">انتخاب سند صادرشده</option>
                  {available.map(d=><option key={d.id} value={d.id}>
                    {d.id} | {parties[d.partyId]?.name||d.partyId} | {
                      moneyText(d.total-d.allocated-(d.returnedAmount||0))}
                  </option>)}</select></Field>
                <Field label="حساب صندوق / بانک">{accountSelect('settlement','accountId')}</Field>
                  <Field label={`مبلغ تسویه (${unitLabel})`}>{amountInput('settlement','amount')}</Field>
                <Field label="تاریخ تسویه">{dateInput('settlement','postingDate')}</Field>
                <div className="sac-form-actions"><Action disabled={blocked||!selected}>ثبت تسویه</Action></div>
              </form>
            </Panel>}
            <InstalmentPlans view={view} canManage={canManage} disabled={blocked}
              execute={execute} today={today} unit={unitLabel}
              onDraftChange={reportChildDraft}/>
          </>}
          {tab==='cash'&&<>
            <PersonalParsianBankMovements api={api} view={view} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear}/>
            {historical&&<Panel title="مانده واقعی صندوق و بانک انتقالی پارسیان"
              description="این حساب‌ها از سندهای دفترکل تاریخی خوانده می‌شوند؛ اتصال کامل به عملیات خزانه و مغایرت‌گیری بانکی هنوز انجام نشده است.">
              <DataTable cols={['کد حساب اصلی','بانک یا صندوق','مانده ریالی دفترکل','ریزگردش']}
                empty="حساب بانک یا صندوق تاریخی یافت نشد."
                rows={historicCash.map(a=><tr key={a.id}>
                  <td dir="ltr">{a.id}</td><td>{a.name}</td>
                  <td>{signedText(a.debitMinusCredit)}</td>
                  <td><button type="button" onClick={()=>displayHistoricDetails(a.id)}>گردش</button></td>
                </tr>)}/>
            </Panel>}
            <Panel title="مانده حساب‌های نقدی" description="مانده خالص بانک و صندوق؛ هیچ تراکنش نمایشی اضافه نشده است.">
              <DataTable cols={['شناسه','نام حساب','مانده بدهکار − بستانکار']}
                empty="حساب نقدی در دفترکل موجود نیست." rows={activeCash.map(a=><tr key={a.id}>
                  <td dir="ltr">{a.id}</td><td>{a.name}</td>
                  <td>{signedText(a.debitMinusCredit)}</td></tr>)} /></Panel>
            {canManage&&<div className="sac-columns">
              {canAdmin&&<Panel title="واریز وجه" description="واریز به صندوق یا بانک در برابر حساب سرمایه ۳۰۰۰ ثبت می‌شود.">
                <form className="sac-grid" onSubmit={submit(async()=>{
                  const x=forms.deposit,sum=parse(x.amount);
                  if(sum===null||!accounts[x.accountId]?.liquid||!validText(x.note,1000)||
                    !validPostingDate(x.postingDate)){
                    setState(p=>({...p,error:'مبلغ، تاریخ، حساب یا شرح واریز نامعتبر است.'}));return;}
                  if(await execute(id=>({command:{type:'funds.deposit',eventId:id,
                    accountId:x.accountId,amount:sum,postingDate:x.postingDate,note:x.note.trim()}})))
                    reset('deposit');
                })}>
                  <Field label="حساب دریافت‌کننده">{accountSelect('deposit','accountId')}</Field>
                  <Field label={`مبلغ ${unitLabel}`}>{amountInput('deposit','amount')}</Field>
                  <Field label="تاریخ">{dateInput('deposit','postingDate')}</Field>
                  <Field label="شرح">{textInput('deposit','note','',1000)}</Field>
                  <div className="sac-form-actions"><Action disabled={blocked}>ثبت واریز</Action></div>
                </form>
              </Panel>}
              <Panel title="انتقال صندوق و بانک" description="انتقال وجه با دو حساب نقدی متفاوت؛ کنترل موجودی در میزبان انجام می‌شود.">
                <form className="sac-grid" onSubmit={submit(async()=>{
                  const x=forms.transfer,sum=parse(x.amount);
                  if(sum===null||x.fromAccountId===x.toAccountId||
                    !accounts[x.fromAccountId]?.liquid||!accounts[x.toAccountId]?.liquid||
                    !validPostingDate(x.postingDate)||!validText(x.note,1000)){
                    setState(p=>({...p,error:'اطلاعات انتقال، حساب‌ها یا مبلغ معتبر نیست.'}));return;}
                  if(await execute(id=>({command:{type:'funds.transfer',eventId:id,
                    fromAccountId:x.fromAccountId,toAccountId:x.toAccountId,
                    amount:sum,postingDate:x.postingDate,note:x.note.trim()}})))reset('transfer');
                })}>
                  <Field label="حساب مبدأ">{accountSelect('transfer','fromAccountId')}</Field>
                  <Field label="حساب مقصد">{accountSelect('transfer','toAccountId')}</Field>
                  <Field label={`مبلغ ${unitLabel}`}>{amountInput('transfer','amount')}</Field>
                  <Field label="تاریخ">{dateInput('transfer','postingDate')}</Field>
                  <Field label="شرح">{textInput('transfer','note','',1000)}</Field>
                  <div className="sac-form-actions"><Action disabled={blocked}>ثبت انتقال</Action></div>
                </form>
              </Panel>
            </div>}
            <BankReconciliation view={view} canManage={canManage} disabled={blocked}
              execute={execute} today={today} unit={unitLabel}
              onDraftChange={reportChildDraft}/>
          </>}
          {tab==='accounts'&&<>
            {historical&&<Panel title="درخت کدینگ منتقل‌شده پارسیان"
              description="نمایش مسیر کل، معین و تفصیلی با شناسه اصلی؛ برای مشاهده گردش روی حساب کلیک کنید.">
              {Object.entries(sortMap(accounts).filter(a=>a.id.startsWith('ps.')).reduce((all,a)=>{
                const parts=a.id.split('.');
                if(parts.length===4){const group=parts[1];(all[group]??=[]).push(a);}return all;
              },{})).sort((a,b)=>a[0].localeCompare(b[0],'fa-IR',{numeric:true})).map(([kol,list])=>
                <details key={kol} className="sac-chart-group">
                  <summary>حساب کل {kol} · {list.length.toLocaleString('fa-IR')} حساب تفصیلی</summary>
                  {Object.entries(list.reduce((r,a)=>{const m=a.id.split('.')[2];(r[m]??=[]).push(a);return r;},{}))
                    .map(([moeen,nodes])=><details key={moeen} className="sac-chart-sub">
                      <summary>معین {moeen} · {nodes.length.toLocaleString('fa-IR')} حساب</summary>
                      {nodes.map(a=><button key={a.id} type="button"
                        onClick={()=>{setAccountFilter(a.id);setSelectedHistoricAccount(a.id);}}
                        className="sac-chart-account">{a.name} · {a.id} · {moneyText(a.debitMinusCredit)}</button>)}
                    </details>)}
                </details>)}
            </Panel>}
            <Panel title="درخت عملیاتی کل، معین و تفصیلی"
              description="روابط والد/فرزند صرفاً برای حساب‌های ثبت‌شده به‌صورت معتبر است. مانده تجمیعی نمایشی است و بار دوم به تراز آزمایشی اضافه نمی‌شود.">
              {sortMap(accounts).filter(a=>a.level==='kol').map(kol=>
                <details className="sac-chart-group" key={kol.id}>
                  <summary>{kol.name} · {kol.id} · کل · مانده تجمیعی: {
                    signedText(totalChartBalance(accounts,kol.id))}</summary>
                  {sortMap(accounts).filter(a=>a.parentId===kol.id).map(moein=>
                    <details className="sac-chart-sub" key={moein.id}>
                      <summary>{moein.name} · {moein.id} · معین · مانده تجمیعی: {
                        signedText(totalChartBalance(accounts,moein.id))}</summary>
                      {sortMap(accounts).filter(a=>a.parentId===moein.id).map(tafsili=>
                        <button type="button" key={tafsili.id} className="sac-chart-account"
                          onClick={()=>{setAccountFilter(tafsili.id);setSelectedHistoricAccount(tafsili.id);}}>
                          {tafsili.name} · {tafsili.id} · تفصیلی · {signedText(tafsili.debitMinusCredit)}
                        </button>)}
                    </details>)}
                </details>)}
            </Panel>
            <Panel title="سرفصل‌ها و مانده‌ها" description={`حساب‌های دفترکل مستقل ${unitLabel} با تفکیک سطح و حساب والد.`}>
              <DataTable cols={['شناسه','عنوان','سطح','حساب والد','ماهیت','نقدی','خالص بدهکار − بستانکار','مانده طبیعی']}
                empty="حسابی دریافت نشده است." rows={sortMap(accounts).map(a=><tr key={a.id}>
                  <td dir="ltr">{a.id}</td><td>{a.name}</td>
                  <td>{chartLevelName(a.level)}</td>
                  <td>{a.parentId?accounts[a.parentId]?.name||a.parentId:'—'}</td>
                  <td>{KINDS[a.kind]||a.kind}</td>
                  <td>{a.liquid?'بله':'خیر'}</td><td>{signedText(a.debitMinusCredit)}</td>
                  <td>{moneyText(a.normalBalance)}</td></tr>)} /></Panel>
            {canAdmin&&<Panel title="ایجاد حساب کل، معین یا تفصیلی" description="ساختار سلسله‌مراتبی با کنترل نوع و سطح والد؛ سوابق قدیمی یا واحد پول اسناد تغییر نمی‌کند.">
              <form className="sac-grid" onSubmit={submit(async()=>{
                const x=forms.account;
                if(!validId(x.accountId)||!validText(x.name)||!(x.kind in KINDS)||
                  (x.liquid&&(x.kind!=='asset'||x.level!=='kol'))||
                  (x.level!=='kol'&&!validId(x.parentId))){
                  setState(p=>({...p,error:'عنوان، شناسه یا ماهیت حساب معتبر نیست.'}));return;}
                if(await execute(id=>({command:{type:'account.create',eventId:id,
                  accountId:x.accountId,name:x.name.trim(),kind:x.kind,
                  liquid:x.liquid,level:x.level,
                  ...(x.level!=='kol'?{parentId:x.parentId}:{})}})))
                  reset('account');
              })}>
                <Field label="شناسه حساب">{idInput('account','accountId','6100')}</Field>
                <Field label="عنوان">{textInput('account','name')}</Field>
                <Field label="ماهیت"><select value={forms.account.kind}
                  onChange={e=>setForms(p=>({...p,account:{...p.account,
                    kind:e.target.value,parentId:''}}))}>
                  {Object.entries(KINDS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></Field>
                <Field label="سطح حساب"><select value={forms.account.level}
                  onChange={e=>setForms(p=>({...p,account:{...p.account,
                    level:e.target.value,parentId:'',liquid:false}}))}>
                  <option value="kol">کل</option>
                  <option value="moein">معین (زیرمجموعه کل)</option>
                  <option value="tafsili">تفصیلی (زیرمجموعه معین)</option></select></Field>
                {forms.account.level!=='kol'&&<Field label="حساب والد">
                  <select required value={forms.account.parentId}
                    onChange={e=>f('account','parentId',e.target.value)}>
                    {options(sortMap(accounts).filter(a=>a.kind===forms.account.kind&&
                      a.level===(forms.account.level==='moein'?'kol':'moein')),'انتخاب حساب والد')}
                  </select></Field>}
                <Field label="حساب نقدی"><select value={forms.account.liquid?'yes':'no'}
                  disabled={forms.account.level!=='kol'}
                  onChange={e=>f('account','liquid',e.target.value==='yes')}>
                  <option value="no">خیر</option><option value="yes">بله (فقط دارایی)</option></select></Field>
                <div className="sac-form-actions"><Action disabled={blocked}>ثبت حساب</Action></div>
              </form>
            </Panel>}
            <div id="sac-account-movements">
            <Panel title="ریزگردش دفترکل" description="خطوط ثبت‌شده دفتر بر اساس کد حساب قابل فیلترند.">
              {selectedHistoricAccount&&<div className="sac-inline-info">
                ریزگردش حساب انتخاب‌شده: <strong>{accounts[selectedHistoricAccount]?.name}</strong>
                <button type="button" onClick={()=>{setSelectedHistoricAccount('');setAccountFilter('');}}>نمایش همه</button>
              </div>}
              <Field label="حساب"><select value={accountFilter} onChange={e=>setAccountFilter(e.target.value)}>
                {options(sortMap(accounts),'همه حساب‌ها')}</select></Field>
              <DataTable cols={['شناسه سند','تاریخ','منبع','حساب','شخص','بدهکار','بستانکار']}
                empty="برای این حساب گردش ثبت‌شده‌ای وجود ندارد."
                rows={view.journals.flatMap(j=>(j.lines||[]).filter(l=>
                  !accountFilter||l.accountId===accountFilter).map((l,i)=><tr key={j.id+':'+i}>
                    <td dir="ltr">{j.id}</td><td>{displayAccountingDate(j.date)}</td><td>{humanSource(j.sourceType)}</td>
                    <td>{accounts[l.accountId]?.name||l.accountId}</td>
                    <td>{parties[l.partyId]?.name||l.partyId||'—'}</td>
                    <td>{debitText(l.debit)}</td>
                    <td>{creditText(l.credit)}</td></tr>))}/></Panel>
            </div>
          </>}
          {tab==='journal'&&<>
            <Panel title="اسناد واقعی دفترکل" description="برگشت یک سند جداگانه ایجاد می‌کند و تاریخچه قبلی را حذف نمی‌کند.">
              <DataTable cols={['شناسه','تاریخ','منبع','بدهکار','بستانکار','وضعیت']}
                focusTarget={searchTarget?.kind==='journal'?searchTarget:null}
                empty="سند دفترکلی ثبت نشده است." rows={view.journals.map(j=><tr key={j.id}
                  data-accounting-search-kind="journal" data-accounting-search-id={j.id}>
                    <td dir="ltr">{j.id}</td><td>{displayAccountingDate(j.date)}</td><td>{humanSource(j.sourceType)}</td>
                  <td>{debitText(j.lines.reduce((s,l)=>s+l.debit,0))}</td>
                  <td>{creditText(j.lines.reduce((s,l)=>s+l.credit,0))}</td>
                  <td>{j.reversalOf?'سند برگشت':view.reversed?.[j.id]?'برگشت داده‌شده':'ثبت قطعی'}</td>
                </tr>)} /></Panel>
            {canManage&&<div className="sac-columns">
              <Panel title="ثبت سند دستی" description="دو یا چند ردیف متوازن؛ حساب‌های دریافتنی و پرداختنی با سند دستی تغییر نمی‌کنند.">
                <form onSubmit={submit(async()=>{
                  if(await execute(id=>buildStandaloneManualCommand({
                    ...forms.manual,lines:manualRows,eventId:id,accounts,today}))){
                    reset('manual');setManualRows([makeJournalLine(),makeJournalLine()]);
                  }
                })}>
                  <div className="sac-grid">
                    <Field label="تاریخ">{dateInput('manual','postingDate')}</Field>
                    <Field label="شرح سند">{textInput('manual','note','',1000)}</Field></div>
                  {manualRows.map((r,i)=><div className="sac-journal-row" key={i}>
                    <select aria-label={'سرفصل حساب ردیف '+(i+1)} required
                      disabled={busy||pendingRetry} value={r.accountId} onChange={e=>manualUpdate(i,'accountId',e.target.value)}>
                      {options(sortMap(accounts).filter(a=>!['1200','2000'].includes(a.id)),'سرفصل حساب')}</select>
                    <input aria-label={'بدهکار ردیف '+(i+1)} dir="ltr" inputMode="numeric"
                      readOnly={busy||pendingRetry} value={r.debit} placeholder="بدهکار"
                      onChange={e=>manualUpdate(i,'debit',e.target.value)}/>
                    <input aria-label={'بستانکار ردیف '+(i+1)} dir="ltr" inputMode="numeric"
                      readOnly={busy||pendingRetry} value={r.credit} placeholder="بستانکار"
                      onChange={e=>manualUpdate(i,'credit',e.target.value)}/>
                    <button type="button" disabled={busy||pendingRetry||manualRows.length===2}
                      onClick={()=>updateManualRows(p=>p.filter((_,index)=>index!==i))}>×</button>
                  </div>)}
                  <div className="sac-form-actions"><button type="button" disabled={busy||pendingRetry||manualRows.length>=100}
                    onClick={()=>updateManualRows(p=>[...p,makeJournalLine()])}>+ ردیف</button>
                    <Action disabled={blocked}>ثبت سند دستی</Action></div>
                </form></Panel>
              <Panel title="برگشت سند" description="برگشت فاکتور دارای تسویه ابتدا نیازمند برگشت دریافت یا پرداخت مرتبط است.">
                <form className="sac-grid" onSubmit={submit(async()=>{
                  const x=forms.reverse,prior=view.journals.find(j=>j.id===x.journalId);
                  if(!prior||prior.reversalOf||view.reversed?.[x.journalId]||
                    !validText(x.reason,1000)||!validPostingDate(x.postingDate)||
                    x.postingDate<prior.date){
                    setState(p=>({...p,error:'شناسه سند، علت یا تاریخ برگشت معتبر نیست.'}));return;}
                  if(await execute(id=>({command:{type:'journal.reverse',eventId:id,
                    journalId:x.journalId,postingDate:x.postingDate,reason:x.reason.trim()}})))
                    reset('reverse');
                })}>
                  <Field label="سند مبدأ"><select required value={forms.reverse.journalId}
                    onChange={e=>f('reverse','journalId',e.target.value)}>
                    {options(view.journals.filter(j=>!j.reversalOf&&!view.reversed?.[j.id]&&
                      ['invoice.issue','bill.issue','receipt.record','payment.record',
                        'funds.deposit','funds.transfer','journal.manual'].includes(j.sourceType))
                      .map(j=>({id:j.id,name:j.date+' · '+j.sourceType})),'انتخاب سند')}</select></Field>
                  <Field label="تاریخ برگشت">{dateInput('reverse','postingDate')}</Field>
                  <Field label="دلیل برگشت">{textInput('reverse','reason','',1000)}</Field>
                  <div className="sac-form-actions"><Action disabled={blocked}>ثبت برگشت</Action></div>
                </form></Panel>
            </div>}
          </>}
          {tab==='reports'&&<>
            {!view.financialReports?<div role="alert" className="sac-alert error">
              این میزبان گزارش ترازسنجی‌شده ارائه نمی‌کند. گزارش ساختگی نمایش داده نمی‌شود.
            </div>:<>
              <Panel title="گزارش گردش حساب در بازه دلخواه"
                description="مانده افتتاحیه قبل از شروع بازه، گردش بین دو تاریخ و مانده قطعی پایان بازه از تک‌تک سطرهای دفترکل محاسبه می‌شوند.">
                <div className="sac-grid">
                  <Field label="از تاریخ شمسی"><AccountingJalaliField max={today}
                    value={reportFrom} onChange={setReportFrom}/></Field>
                  <Field label="تا تاریخ شمسی"><AccountingJalaliField max={today}
                    value={reportTo} onChange={setReportTo}/></Field>
                  <Field label="انتخاب حساب"><select value={reportAccount}
                    onChange={e=>setReportAccount(e.target.value)}>
                    {options(sortMap(accounts),'همه حساب‌ها')}</select></Field>
                </div>
                {periodReport?.error?<p role="alert" className="sac-alert error">
                  {periodReport.error}</p>:<>
                  <div className="sac-form-actions">
                    <button type="button" onClick={exportMovements}>CSV ریزگردش</button>
                    <button type="button" onClick={exportPeriodSummary}>CSV مانده اول و پایان دوره</button>
                    <button type="button" onClick={()=>globalThis.print?.()}>چاپ گزارش</button>
                    <span>{(periodReport?.journalCount||0).toLocaleString('fa-IR')} سند در بازه انتخابی</span>
                  </div>
                  <DataTable cols={['کد حساب','عنوان','اول دوره بدهکار','اول دوره بستانکار',
                    'گردش بدهکار','گردش بستانکار','پایان دوره بدهکار','پایان دوره بستانکار']}
                    empty="مانده یا گردشی در این بازه یا حساب یافت نشد."
                    rows={(periodReport?.rows||[]).map(a=><tr key={a.accountId}>
                        <td dir="ltr">{a.accountId}</td><td>{a.name}</td>
                        <td>{debitText(a.openingDebit)}</td><td>{creditText(a.openingCredit)}</td>
                        <td>{debitText(a.debitMovement)}</td><td>{creditText(a.creditMovement)}</td>
                        <td>{debitText(a.closingDebit)}</td><td>{creditText(a.closingCredit)}</td>
                      </tr>)}/>
                </>}
              </Panel>
              <Panel title="تراز آزمایشی دوطرفه" description="گزارش تمام دوره‌های ثبت‌شده؛ بر اساس دفترکل واقعی و با کنترل توازن بدهکار و بستانکار.">
                <div className="sac-metrics">
                  <div className="sac-metric"><span>جمع بدهکار</span><strong>{debitText(view.financialReports.trialBalance.totalDebit)}</strong></div>
                  <div className="sac-metric"><span>جمع بستانکار</span><strong>{creditText(view.financialReports.trialBalance.totalCredit)}</strong></div>
                  <div className="sac-metric"><span>تطبیق دفتر</span><strong>{view.financialReports.reconciled?'تراز است':'تأیید نشده'}</strong></div>
                </div>
                <DataTable cols={['کد حساب','عنوان','ماهیت','مانده بدهکار','مانده بستانکار','گردش بدهکار','گردش بستانکار']}
                  empty="سرفصلی وجود ندارد." rows={view.financialReports.trialBalance.rows.map(a=><tr key={a.accountId}>
                    <td dir="ltr">{a.accountId}</td><td>{a.name}</td><td>{KINDS[a.kind]||a.kind}</td>
                    <td>{debitText(a.debit)}</td><td>{creditText(a.credit)}</td>
                    <td>{debitText(a.debitMovement)}</td><td>{creditText(a.creditMovement)}</td>
                  </tr>)}/>
              </Panel>
              <div className="sac-columns">
                <Panel title="صورت سود و زیان" description="درآمد و هزینه‌های ثبت‌شده؛ سندهای پیش‌نویس در محاسبه نیستند.">
                  {view.financialReports.profitLossComplete===false&&<div className="sac-audit-notice" role="status">
                    سود/زیان فعلاً قطعی نیست: حواله خروج و بهای تمام‌شدهٔ بعضی کالاهای فروخته‌شده ثبت نشده است.
                    تعداد ردیف‌های نیازمند رسیدگی: {(view.financialReports.unpostedGoodsIssues||[]).length.toLocaleString('fa-IR')}.
                    {canManage&&<button type="button" onClick={()=>setTab('items')}>بررسی حواله‌های انبار</button>}
                  </div>}
                  <DataTable cols={['عنوان','مبلغ']} empty="گزارش در دسترس نیست." rows={[
                    ['درآمد',view.financialReports.profitLoss.revenue],
                    ['هزینه',view.financialReports.profitLoss.expense],
                    [view.financialReports.profitLossComplete===false?'سود / زیان موقت (بهای تمام‌شده ناقص)':'سود / زیان',view.financialReports.profitLoss.net],
                  ].map(([title,value])=><tr key={title}><td>{title}</td><td>{moneyText(value)}</td></tr>)}/>
                </Panel>
                <Panel title="ترازنامه" description="دارایی‌ها برابر با بدهی، سرمایه و نتیجه انباشته کنترل می‌شود.">
                  <DataTable cols={['عنوان','مبلغ']} empty="گزارش در دسترس نیست." rows={[
                    ['دارایی',view.financialReports.balanceSheet.assets],
                    ['بدهی',view.financialReports.balanceSheet.liabilities],
                    ['سرمایه',view.financialReports.balanceSheet.capital],
                    ['سود/زیان بسته‌نشده',view.financialReports.balanceSheet.unclosedProfitLoss],
                    ['جمع بدهی و حقوق مالکانه',view.financialReports.balanceSheet.liabilitiesAndEquity],
                  ].map(([title,value])=><tr key={title}><td>{title}</td><td>{moneyText(value)}</td></tr>)}/>
                </Panel>
              </div>
              <Panel title="مانده اشخاص و تطبیق حساب کنترل" description="مانده هر طرف‌حساب با حساب‌های دریافتنی ۱۲۰۰ و پرداختنی ۲۰۰۰ تطبیق داده می‌شود.">
                <DataTable cols={['شخص','دریافتنی','پرداختنی','خالص دریافتنی']}
                  empty="طرف‌حسابی ثبت نشده است." rows={view.financialReports.counterpartyBalances.map(p=><tr key={p.partyId}>
                    <td>{p.name} ({p.partyId})</td><td>{debitText(p.receivable)}</td>
                    <td>{creditText(p.payable)}</td><td>{signedText(p.netReceivable)}</td>
                  </tr>)}/>
              </Panel>
              <Panel title="گزارش سنی مطالبات و بدهی‌ها"
                description="مبنای مانده، فاکتور قطعیِ تسویه‌نشده است؛ روزهای تأخیر از سررسید ذخیره‌شده شمسی‌شده نمایش داده می‌شوند. فاکتور فاقد سررسید جدا مشخص است.">
                <DataTable cols={['نوع','فاکتور','طرف حساب','سررسید شمسی','مانده','روز تأخیر','گروه سنی']}
                  empty="فاکتور قطعی با مانده مثبت ثبت نشده است."
                  rows={[
                    ...sortMap(view.invoices).map(d=>({...d,category:'دریافتنی'})),
                    ...sortMap(view.bills).map(d=>({...d,category:'پرداختنی'})),
                  ].filter(d=>d.status==='issued'&&
                    d.total>d.allocated+(d.returnedAmount||0)).map(d=>{
                    const age=daysSinceDue(d.dueDate,today);
                    const band=age===null?'بدون سررسید':age<=0?'سررسید نشده':
                      age<=30?'۱ تا ۳۰ روز':age<=60?'۳۱ تا ۶۰ روز':
                      age<=90?'۶۱ تا ۹۰ روز':'بیش از ۹۰ روز';
                    return <tr key={d.category+':'+d.id}>
                      <td>{d.category}</td><td dir="ltr">{d.id}</td>
                      <td>{parties[d.partyId]?.name||d.partyId}</td>
                      <td>{d.dueDate?displayAccountingDate(d.dueDate):'—'}</td>
                      <td>{d.category==='دریافتنی'?
                        debitText(d.total-d.allocated-(d.returnedAmount||0)):
                        creditText(d.total-d.allocated-(d.returnedAmount||0))}</td>
                      <td>{age===null?'—':Math.max(0,age).toLocaleString('fa-IR')}</td>
                      <td>{band}</td>
                    </tr>;
                  })}/>
              </Panel>
              <Panel title="مانده بانک و صندوق" description="مانده ثبت‌شده در دفتر، نه تأییدیه بانکی یا صورت مغایرت واردشده.">
                <DataTable cols={['حساب','مانده']} empty="حساب نقدی وجود ندارد."
                  rows={view.financialReports.cashBankBalances.map(a=><tr key={a.accountId}>
                    <td>{a.name} ({a.accountId})</td><td>{moneyText(a.balance)}</td>
                  </tr>)}/>
              </Panel>
            </>}
          </>}
          {tab==='company'&&<>
            <PersonalParsianCompany api={api} fiscalYear={fiscalYear} existingProfile={view?.companyProfile}/>
            <CompanyProfile view={view} canManage={canAdmin}
              legacyCompany={legacyCompanySource}
              disabled={blocked} execute={execute} onDraftChange={reportChildDraft}/>
          </>}
          {tab==='payroll'&&<PersonalParsianExtended api={api} fiscalYear={fiscalYear} onFiscalYearChange={setFiscalYear} section="payroll"/>}
          {tab==='payroll'&&<PayrollAndTax view={view} canManage={canManage} canSetTax={canAdmin}
            disabled={blocked} execute={execute} today={today} unit={unitLabel}
            onDraftChange={reportChildDraft}/>}
          {tab==='period'&&<>
            <FiscalYearClose view={view} canManage={canAdmin}
              disabled={blocked} execute={execute} today={today}
              onDraftChange={reportChildDraft}/>
            <Panel title="بستن دوره حسابداری"
              description="قفل تاریخ حسابداری مانع ثبت سند عقب‌تر از مرز بسته‌شده می‌شود. این عملیات جایگزین سند اختتامیه سال مالی نیست.">
            <div className="sac-period"><span>مرز بسته‌شدن فعلی:</span>
              <strong>{view.closedThrough?displayAccountingDate(view.closedThrough):'هنوز دوره‌ای بسته نشده است'}</strong></div>
            {canAdmin&&<form className="sac-grid" onSubmit={submit(async()=>{
              const day=forms.close.throughDate;
              if(!validStandaloneDate(day,today)||(view.closedThrough&&day<=view.closedThrough)){
                setState(p=>({...p,error:'تاریخ بستن دوره باید بعد از مرز قبلی و غیرآینده باشد.'}));return;}
              if(!globalThis.confirm?.('پس از بستن دوره، ثبت تاریخ‌های قبل مجاز نیست. تأیید می‌کنید؟'))return;
              if(await execute(id=>({command:{type:'period.close',eventId:id,throughDate:day}})))
                reset('close');
            })}>
              <Field label="بستن دوره تا تاریخ">{dateInput('close','throughDate')}</Field>
              <div className="sac-form-actions"><Action disabled={blocked}>ثبت بستن دوره</Action></div>
            </form>}</Panel>
          </>}
        </>}
      </div>
      <TarazIntegrationPanel api={api}/>
      <footer className="sac-footer"><span>تراز · حسابداری مستقل مبتنی بر {unitLabel}</span>
        <span>نسخه داده میزبان: <code dir="ltr">{snapshot?.revision??'خوانده نشده'}</code></span></footer>
    </div>
  </div>;
}
export default StandaloneAccountingWorkspace;
