import React,{useEffect,useMemo,useState} from 'react';
import './personal_parsian_bank_movements.css';

const fmt=value=>Number.isSafeInteger(Number(value))?Number(value).toLocaleString('fa-IR'):String(value||'');
export default function PersonalParsianBankMovements({api,view,fiscalYear='1405',onFiscalYearChange}){
 const [source,setSource]=useState(null),[error,setError]=useState(''),[year,setYear]=useState(fiscalYear),[search,setSearch]=useState(''),[page,setPage]=useState(0);
 useEffect(()=>{
   if(typeof api?.standaloneAccountingParsianHistory!=='function')return;
   let active=true;
   Promise.resolve().then(()=>api.standaloneAccountingParsianHistory())
     .then(res=>{if(active)setSource(res)})
     .catch(e=>{if(active)setError(String(e?.message||e))});
   return()=>{active=false};
 },[api]);
 useEffect(()=>{setYear(fiscalYear);setPage(0);},[fiscalYear]);
 const bankRows=useMemo(()=>{
   return (source?.journalLines||[])
    .filter(x=>x.year===year&&/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.test(x.account_id))
    .filter(x=>!search.trim()||[x.date,x.number,x.account_name,x.note,x.account_id]
      .some(v=>String(v||'').toLocaleLowerCase('fa-IR').includes(search.trim().toLocaleLowerCase('fa-IR'))))
    .sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))||
      Number(b.number||0)-Number(a.number||0));
 },[source,year,search]);
 const bankAccounts=useMemo(()=>Object.values(view?.accounts||{})
   .filter(x=>/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.test(x.id))
   .sort((a,b)=>String(a.name).localeCompare(String(b.name),'fa-IR')),[view]);
 const displayed=bankRows.slice(page*45,(page+1)*45);
 return <section className="ppbm-root" aria-label="تراکنش‌های تاریخی بانک و صندوق پارسیان">
  <div className="ppbm-head"><div><h3>دفتر تاریخی صندوق و بانک‌های پارسیان</h3><p>موجودی‌ها و ریزگردش از سندهای حسابداری اصلی، به ریال</p></div><span>منبع: دفتر کل ۱۴۰۴ و ۱۴۰۵</span></div>
  <div className="ppbm-balances">{year==='1405'?bankAccounts.map(account=><article key={account.id}>
    <strong>{account.name}</strong><span dir="ltr">{fmt(account.debitMinusCredit)} ریال</span>
    <small dir="ltr">{account.id}</small></article>):<p className="ppbm-notice">در سال ۱۴۰۴ فقط گردش همان سال نشان داده می‌شود؛ نمایش مانده بانک سال ۱۴۰۵ در اینجا گمراه‌کننده است.</p>}</div>
  <p className="ppbm-notice">مانده‌ها مطابق دفتر کل هستند؛ به معنی موجودی بانک تأییدشده یا مغایرت‌گیری‌شده نیستند. ردیف‌های سال ۱۴۰۵ ممکن است شامل سند افتتاحیه باشند و گردش بانک معادل فروش یا وصول یک فاکتور مشخص نیست.</p>
  <div className="ppbm-actions">
    <select aria-label="سال مالی گردش صندوق و بانک" value={year} onChange={e=>{setYear(e.target.value);setPage(0);onFiscalYearChange?.(e.target.value)}}>
      <option value="1405">سال ۱۴۰۵</option><option value="1404">سال ۱۴۰۴</option>
    </select>
    <input type="search" aria-label="جستجوی سند صندوق و بانک" placeholder="شماره سند، حساب، شرح یا تاریخ" value={search} onChange={e=>{setSearch(e.target.value);setPage(0)}}/>
  </div>
  {!!error&&<p role="alert" className="ppbm-notice">{error}</p>}
  {source&&<p className="ppbm-note">{fmt(bankRows.length)} ردیف گردش مستند؛ جمع بدهکار {fmt(bankRows.reduce((t,x)=>t+Number(x.debit_rial||0),0))} ریال؛ جمع بستانکار {fmt(bankRows.reduce((t,x)=>t+Number(x.credit_rial||0),0))} ریال</p>}
  <div className="ppbm-scroll"><table><thead><tr><th>تاریخ</th><th>سند</th><th>بانک/صندوق</th><th>بدهکار</th><th>بستانکار</th><th>شرح در منبع</th></tr></thead><tbody>
    {displayed.map((x,i)=><tr key={year+':'+x.number+':'+i}>
      <td dir="ltr">{x.date}</td><td>{x.number}</td><td>{x.account_name}</td>
      <td dir="ltr">{fmt(x.debit_rial)}</td><td dir="ltr">{fmt(x.credit_rial)}</td><td>{x.note}</td></tr>)}
    {!source&&<tr><td colSpan={6}>در حال خواندن سوابق...</td></tr>}
    {source&&displayed.length===0&&<tr><td colSpan={6}>برای این جست‌وجو ردیفی یافت نشد.</td></tr>}
  </tbody></table></div>
  <div className="ppbm-pages"><button type="button" disabled={page===0} onClick={()=>setPage(n=>n-1)}>صفحه قبل</button>
   <button type="button" disabled={(page+1)*45>=bankRows.length} onClick={()=>setPage(n=>n+1)}>صفحه بعد</button></div>
 </section>;
}
