import React, {useEffect, useMemo, useState} from 'react';
import {buildParsianLegacyInvoiceHtml,legacyInvoiceFilename} from './personal_parsian_invoice_export.mjs';
import {downloadStandaloneBlob} from './standalone_invoice_export.js';
import './personal_parsian_invoices.css';

// All historical documents are read-only because their GL entries already exist.
// Never turn an old source factor into a new invoice.issue command.
export default function PersonalParsianInvoices({api, section='invoices',fiscalYear='1405',onFiscalYearChange}) {
  const [source,setSource]=useState(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [term,setTerm]=useState('');
  const [year,setYear]=useState(fiscalYear);
  const [match,setMatch]=useState('all');
  const [page,setPage]=useState(0);
  const [selected,setSelected]=useState('');
  const [rawContacts,setRawContacts]=useState([]);
  useEffect(()=>{setYear(fiscalYear);setPage(0);setSelected('');},[fiscalYear]);
  const [exportError,setExportError]=useState('');
  useEffect(()=>{
    if(section!=='parties'||typeof api?.standaloneAccountingParsianArchiveRows!=='function')return;
    let alive=true;
    Promise.all(['1404','1405'].map(year=>
      api.standaloneAccountingParsianArchiveRows(year,'tbl_Telephone',0)
        .then(res=>({year,rows:res?.rows||[]}))))
      .then(data=>{if(alive)setRawContacts(data.flatMap(x=>
        x.rows.map(r=>({...r.fields,sourceYear:x.year,sourceOrdinal:r.ordinal}))))})
      .catch(()=>{if(alive)setRawContacts([])});
    return()=>{alive=false};
  },[api,section]);
  useEffect(()=>{
    let active=true;
    if(typeof api?.standaloneAccountingParsianHistory!=='function') {
      setError('نسخه فعلی رابط بایگانی شخصی پارسیان را پشتیبانی نمی‌کند.');
      setLoading(false);
      return;
    }
    Promise.resolve().then(()=>api.standaloneAccountingParsianHistory()).then(payload=>{
      if(!active)return;
      if(!payload||!Array.isArray(payload.invoices)||payload.invoices.length!==195) {
        throw new Error('اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد.');
      }
      setSource(payload);setError('');
    }).catch(e=>{if(active)setError(String(e?.message||e))})
      .finally(()=>{if(active)setLoading(false)});
    return ()=>{active=false;};
  },[api]);
  const linesByFactor=useMemo(()=>{
    const out=new Map();
    for(const line of source?.invoiceLines||[]){
      if(!out.has(line.invoice_key))out.set(line.invoice_key,[]);
      out.get(line.invoice_key).push(line);
    }
    return out;
  },[source]);
  const exportLegacyInvoice=invoice=>{
    try{
      const html=buildParsianLegacyInvoiceHtml(invoice,linesByFactor.get(invoice.key)||[]);
      downloadStandaloneBlob({filename:legacyInvoiceFilename(invoice),
        blob:new Blob([html],{type:'text/html;charset=utf-8'})});
      setExportError('');
    }catch(e){setExportError(String(e?.message||e));}
  };
  const contactsByParty=useMemo(()=>{
    const out=new Map();
    for(const p of source?.contacts||[]){
      const key=p.year+':'+p.party_key;
      if(!out.has(key))out.set(key,[]);
      out.get(key).push(p);
    }
    return out;
  },[source]);
  const sourceJournalByParty=useMemo(()=>{
    const map=new Map();
    for(const line of source?.journalLines||[]){
      const account=String(line.account_id||'');
      if(!account.startsWith('ps.parsian.account.t.12.2.'))continue;
      const code=account.replace('ps.parsian.account.t.','');
      const key=line.year+':'+code;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(line);
    }
    return map;
  },[source]);
  const sourceInvoicesByParty=useMemo(()=>{
    const map=new Map();
    for(const invoice of source?.invoices||[]){
      const key=invoice.year+':'+invoice.party_key;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(invoice);
    }
    return map;
  },[source]);
  const fullContacts=useMemo(()=>{
    const map=new Map();
    for(const c of rawContacts){
      const code=[c.KolCode,c.MoeenCode,c.TafsiliCode].map(String).join('.');
      const key=c.sourceYear+':'+code;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(c);
    }
    return map;
  },[rawContacts]);
  const factorList=useMemo(()=>{
    const value=term.trim().toLocaleLowerCase('fa-IR');
    return (source?.invoices||[]).filter(x=>
      (year==='all'||x.year===year)&&
      (match==='all'||x.status===match)&&
      (!value||[
        x.number,x.date,x.party_name,x.party_key,x.key,x.document_link,x.notes,
        ...(linesByFactor.get(x.key)||[]).map(line=>line.good_name)
      ].some(item=>String(item||'').toLocaleLowerCase('fa-IR').includes(value))));
  },[source,term,year,match,linesByFactor]);
  const parties=useMemo(()=>{
    const value=term.trim().toLocaleLowerCase('fa-IR');
    return (source?.parties||[]).filter(x=>
      (year==='all'||x.year===year)&&
      (!value||[
        x.name,x.code,x.madar_id,
        ...(contactsByParty.get(x.year+':'+x.code)||[]).flatMap(c=>[c.tel,c.mobile,c.name,c.address])
      ].some(item=>String(item||'').toLocaleLowerCase('fa-IR').includes(value))))
      .sort((a,b)=>Math.abs(Number(b.balance_signed_rial||0))-
        Math.abs(Number(a.balance_signed_rial||0)));
  },[source,term,year,contactsByParty]);
  const records=section==='parties'?parties:factorList;
  const visible=records.slice(page*35,(page+1)*35);
  const selectedRecord=records.find(x=>(section==='parties'?x.year+':'+x.code:x.key)===selected);
  const financial=x=> {
    const val=Number(x);
    return Number.isFinite(val)?val.toLocaleString('fa-IR',{maximumFractionDigits:3}):String(x??'');
  };
  const status=(status)=>({
    matched:'سند و مبلغ منطبق',
    amount_review:'نیازمند بررسی مبلغ',
    inventory_only:'عملیات انبار، بدون سند',
    unlinked:'سند مرتبط یافت نشده',
  }[status]||status);
  if(loading)return <div className="ppi-root" role="status">در حال خواندن اسناد تاریخی از آرشیو خصوصی...</div>;
  if(error)return <div className="ppi-root ppi-error" role="alert">آرشیو پارسیان در این نصب قابل خواندن نیست: {error}</div>;
  if(!source)return null;
  return <section className="ppi-root" aria-label={section==='parties'?'اشخاص تاریخی پارسیان':'فاکتورهای تاریخی پارسیان'}>
    <div className="ppi-heading">
      <div>
        <h3>{section==='parties'?'طرف‌حساب‌های تاریخی پارسیان':'فاکتورهای منتقل‌شده از پارسیان'}</h3>
        <p>اطلاعات واقعی سال‌های ۱۴۰۴ و ۱۴۰۵، در همین حسابداری مدار · واحد مبلغ: ریال</p>
      </div>
      <span className="ppi-counter">{financial(records.length)} مورد</span>
    </div>
    <div className="ppi-note" role="note">
      {section==='parties'?
        'مانده‌های دفتر کل با بکاپ ۱۴۰۵ تطبیق شده‌اند. مانده هر شخص به معنی تسویه تک‌تک فاکتورها نیست.':
        'این فاکتورها به اسناد اصلی دفتر کل وصل‌اند. گردش مالی آن‌ها قبلاً ثبت شده است، بنابراین با نمایش این فاکتورها، هیچ ثبت دوباره یا بدهی تازه‌ای ایجاد نمی‌شود.'}
    </div>
    <div className="ppi-controls">
      <input type="search" value={term} aria-label="جست‌وجوی سوابق پارسیان" placeholder={section==='parties'?'جست‌وجوی نام، کد و تلفن':'جست‌وجوی شماره، شخص، کالا و تاریخ'}
        onChange={e=>{setTerm(e.target.value);setPage(0);setSelected('')}}/>
      <select aria-label="انتخاب سال مالی" value={year} onChange={e=>{setYear(e.target.value);setPage(0);setSelected('');if(e.target.value!=='all')onFiscalYearChange?.(e.target.value)}}>
        <option value="all">هر دو سال</option><option value="1405">سال ۱۴۰۵</option><option value="1404">سال ۱۴۰۴</option>
      </select>
      {section==='invoices'&&<select aria-label="فیلتر تطبیق تاریخی" value={match} onChange={e=>{setMatch(e.target.value);setPage(0);setSelected('')}}>
        <option value="all">همه وضعیت‌ها</option><option value="matched">تطبیق کامل</option>
        <option value="amount_review">اختلاف مبلغ</option><option value="inventory_only">عملیات انبار (۱)</option>
      </select>}
    </div>
    <p className="ppi-subtle" aria-live="polite">{financial(records.length)} مورد یافت شد؛ صفحه {financial(page+1)} از {financial(Math.max(1,Math.ceil(records.length/35)))}</p>
    <div className="ppi-table-wrap">
      <table className="ppi-table">
        <thead><tr>{section==='parties'?<>
          <th>شخص</th><th>سال</th><th>کد اصلی</th><th>مانده حساب (ریال)</th><th>جزئیات</th>
        </>:<>
          <th>شماره</th><th>تاریخ شمسی</th><th>شخص</th><th>مبلغ ردیف‌ها (ریال)</th><th>وضعیت</th><th>جزئیات</th>
        </>}</tr></thead>
        <tbody>
          {visible.map(item=>{
            const id=section==='parties'?item.year+':'+item.code:item.key;
            const open=id===selected;
            return <React.Fragment key={id}>
              {section==='parties'?<tr>
                <td>{item.name}</td><td>{item.year}</td><td dir="ltr">{item.code}</td>
                <td dir="ltr" className="ppi-amount">{financial(item.balance_signed_rial)} <span className="ppi-balance-side">{item.balance_signed_rial>0?'بدهکار':item.balance_signed_rial<0?'بستانکار':'مانده صفر'}</span></td>
                <td><button type="button" onClick={()=>setSelected(open?'':id)} aria-expanded={open}> {open?'بستن':'ریزگردش، فاکتور و تماس'}</button></td>
              </tr>:<tr>
                <td>{item.number}</td><td dir="ltr">{item.date}</td><td>{item.party_name}</td>
                <td dir="ltr" className="ppi-amount">{financial(item.computed_rial)}</td>
                <td><span className={'ppi-pill '+(item.status==='matched'?'ppi-good':'ppi-review')}>{status(item.status)}</span></td>
                <td><button type="button" onClick={()=>setSelected(open?'':id)} aria-expanded={open}>{open?'بستن':'مشاهده ردیف‌ها'}</button></td>
              </tr>}
              {open&&<tr className="ppi-detail"><td colSpan={section==='parties'?5:6}>
                {section==='parties'?<div>
                  <strong>نام در پارسیان:</strong> {item.name} · <strong>شناسه مدار:</strong> <span dir="ltr">{item.madar_id||'آرشیوی'}</span>
                  <div className="ppi-contacts">{(contactsByParty.get(item.year+':'+item.code)||[]).map(c=>
                    <div key={c.source_id} className="ppi-mini">{c.name} · {c.tel} · {c.mobile} · {c.address}</div>)}
                  </div>
                  {(()=>{
                    const key=item.year+':'+item.code;
                    const rows=sourceJournalByParty.get(key)||[];
                    const factors=sourceInvoicesByParty.get(key)||[];
                    const debit=rows.reduce((a,r)=>a+Number(r.debit_rial||0),0);
                    const credit=rows.reduce((a,r)=>a+Number(r.credit_rial||0),0);
                    return <div className="ppi-history">
                      <h4>ریزگردش دفتر کل در سال {item.year}</h4>
                      <p><strong>{financial(rows.length)}</strong> ردیف سند؛ بدهکار <strong>{financial(debit)}</strong> ریال؛ بستانکار <strong>{financial(credit)}</strong> ریال</p>
                      <p>خالص ریزگردش: <strong>{financial(debit-credit)}</strong> ریال؛ مانده منبع: <strong>{financial(item.balance_signed_rial)}</strong> ریال</p>
                      {rows.length>0&&<div className="ppi-ledger-scroll"><table className="ppi-table ppi-subtable"><thead><tr>
                        <th>تاریخ شمسی</th><th>شماره سند</th><th>بدهکار</th><th>بستانکار</th><th>شرح ثبت‌شده</th>
                      </tr></thead><tbody>{rows.slice(0,60).map((r,i)=><tr key={item.year+':'+r.number+':'+r.source_row_id+':'+i}>
                        <td dir="ltr">{r.date}</td><td>{r.number}</td>
                        <td dir="ltr">{financial(r.debit_rial)}</td><td dir="ltr">{financial(r.credit_rial)}</td><td>{r.note||'بدون شرح'}</td>
                      </tr>)}</tbody></table></div>}
                      {rows.length>60&&<p>۶۰ ردیف اول نمایش داده شد؛ کل اسناد در بخش دفتر کل محفوظ‌اند.</p>}
                      <h4>فاکتورهای مربوط به این شخص در همین سال: {financial(factors.length)}</h4>
                      {factors.length>0&&<div className="ppi-ledger-scroll"><table className="ppi-table ppi-subtable"><thead><tr>
                        <th>شماره</th><th>تاریخ شمسی</th><th>مبلغ</th><th>سند مرتبط</th>
                      </tr></thead><tbody>{factors.slice(0,40).map(f=><tr key={f.key}>
                        <td>{f.number}</td><td>{f.date}</td><td dir="ltr">{financial(f.computed_rial)}</td><td dir="ltr">{f.source_sanad}</td>
                      </tr>)}</tbody></table></div>}
                      {factors.length>40&&<p>۴۰ فاکتور اول نمایش داده شد؛ تمامی فاکتورها در بخش فاکتور فروش هستند.</p>}
                      {fullContacts.get(key)?.map((c,i)=><div className="ppi-mini" key={key+':contact:'+i}>
                        <strong>اطلاعات تماس تکمیلی از منبع:</strong>
                        {[
                          ['کد ملی',c.CodeNat],['کد اقتصادی',c.CodeEco],['کد پستی',c.CodePost],
                          ['ایمیل',c.Email],['موبایل دوم',c.Mobile1],['موبایل سوم',c.Mobile2],
                          ['تلفن دیگر',c.Tel1],['نشانی دوم',c.Address1],['توضیحات',c.Other]
                        ].filter(x=>x[1]&&x[1]!=='None').map(([label,value])=>
                          <span className="ppi-detail-contact" key={label}><b>{label}:</b> {value}</span>)}
                      </div>)}
                      <p className="ppi-subtle">مانده تاریخی صرفاً خالص حساب تفصیلی است و تسویه تک‌تک فاکتورها از آن استنباط نشده است.</p>
                    </div>;
                  })()}
                </div>:<div>
                  <p><strong>سند دفتر کل:</strong> <span dir="ltr">{item.document_link||'فاقد سند مرتبط'}</span></p>
                  <p><strong>شناسۀ طرف‌حساب:</strong> <span dir="ltr">{item.party_key}</span></p>
                  <p><strong>خالص حساب مشتری در سند:</strong> {financial(item.document_ar_signed_rial)} ریال · <strong>خالص حساب فروش:</strong> {financial(item.document_sales_signed_rial)} ریال</p>
                  <p><strong>شناسه عملیات پارسیان:</strong> Title {item.title_code} / I/O {item.io} · <strong>وضعیت تسویه فاکتور:</strong> نامشخص (تخصیص دریافت به فاکتور در منبع اثبات نشده است)</p>
                  <table className="ppi-table ppi-subtable"><thead><tr><th>کد کالا</th><th>نام</th><th>تعداد</th><th>قیمت واحد</th><th>تخفیف</th><th>خالص ردیف</th></tr></thead>
                    <tbody>{(linesByFactor.get(item.key)||[]).map(line=><tr key={line.source_id}>
                      <td dir="ltr">{line.good_code}</td><td>{line.good_name}</td>
                      <td dir="ltr">{financial(line.quantity)}</td><td dir="ltr">{financial(line.unit_price_rial)}</td>
                      <td dir="ltr">{financial(line.discount_rial)}</td><td dir="ltr">{financial(line.line_net_rial)}</td>
                    </tr>)}</tbody>
                  </table>
                  <div className="ppi-print-actions">
                    <button type="button" data-legacy-invoice-export
                      onClick={()=>exportLegacyInvoice(item)}>{'دریافت برگه قابل چاپ فاکتور تاریخی'}</button>
                    <small>{'این برگه آرشیوی است و سند مالی جدید صادر نمی‌کند.'}</small>
                  </div>
                  {!!item.notes&&<p className="ppi-subtle">{item.notes}</p>}
                </div>}
              </td></tr>}
            </React.Fragment>;
          })}
          {!visible.length&&<tr><td colSpan={section==='parties'?5:6}>موردی مطابق جست‌وجو پیدا نشد.</td></tr>}
        </tbody>
      </table>
    </div>
    {exportError&&<p role="alert" className="ppi-error">{exportError}</p>}
    <div className="ppi-pagination">
      <button type="button" disabled={page===0} onClick={()=>{setPage(p=>p-1);setSelected('')}}>صفحه قبل</button>
      <button type="button" disabled={(page+1)*35>=records.length} onClick={()=>{setPage(p=>p+1);setSelected('')}}>صفحه بعد</button>
    </div>
    {section==='invoices'&&<p className="ppi-subtle">۱۹۴ فاکتور مالی از نظر مبلغ، تخفیف و سند اصلی تطبیق کامل دارند. یک گروه مربوط به عملیات انبار است و سند مالی ندارد.</p>}
  </section>;
}
