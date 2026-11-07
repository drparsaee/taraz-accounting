import React,{useEffect,useMemo,useState} from 'react';
import './parsian_raw_archive_explorer.css';

/** Admin-only historical source explorer, never a live finance transaction UI. */
export default function ParsianRawArchiveExplorer({api,canAdmin=false}){
  const [years,setYears]=useState([]);
  const [year,setYear]=useState('1405');
  const [table,setTable]=useState('');
  const [needle,setNeedle]=useState('');
  const [offset,setOffset]=useState(0);
  const [page,setPage]=useState(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    if(!canAdmin)return;
    let active=true;
    setLoading(true);
    Promise.resolve().then(()=>api?.standaloneAccountingParsianArchiveIndex?.())
      .then(data=>{
        if(!active)return;
        if(!Array.isArray(data))throw new Error('مرورگر آرشیو کامل در میزبان فعال نیست.');
        setYears(data);
        if(data.length&&!data.some(x=>x.year===year))setYear(data[0].year);
      }).catch(err=>{if(active)setError(err?.message||'آرشیو قابل خواندن نیست.')})
      .finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[api,canAdmin]);
  const selectedYear=years.find(x=>x.year===year);
  const tables=useMemo(()=>{
    const q=needle.trim().toLowerCase();
    return (selectedYear?.tables||[]).filter(x=>x.name.toLowerCase().includes(q));
  },[selectedYear,needle]);
  const chooseTable=name=>{setTable(name);setOffset(0);setPage(null);setError('')};
  useEffect(()=>{
    if(!canAdmin||!table||!selectedYear?.tables?.some(x=>x.name===table))return;
    let active=true;
    setLoading(true);
    Promise.resolve().then(()=>api.standaloneAccountingParsianArchiveRows(year,table,offset))
      .then(result=>{if(active){setPage(result);setError('')}})
      .catch(err=>{if(active){setPage(null);setError(err?.message||'خواندن سطرهای آرشیوی ناموفق بود.')}})
      .finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[api,canAdmin,year,table,offset,selectedYear]);
  if(!canAdmin)return <div className="pra-root" role="status">
    مرور همه جدول‌های اصلی پارسیان فقط برای مدیر سیستم همین شرکت مجاز است.
  </div>;
  return <section className="pra-root" aria-label="مرور تمام رکوردهای خام پارسیان">
    <header className="pra-head">
      <div><h3>آرشیو کامل اطلاعات پارسیان</h3>
        <p>رکوردهای بازیابی‌شده از نسخه اصلی SQL، فقط خواندنی و بدون ثبت دوباره در دفاتر مالی.</p></div>
      <label>سال مالی
        <select aria-label="سال آرشیو اصلی پارسیان" value={year} onChange={e=>{
          setYear(e.target.value);chooseTable('');setNeedle('');
        }}>
          {years.map(y=><option key={y.year} value={y.year}>{y.year} · {y.tableCount} جدول · {y.rowCount.toLocaleString('fa-IR')} سطر</option>)}
        </select>
      </label>
    </header>
    {!years.length&&!loading&&<p role="status">بسته کامل بایگانی سال‌های پارسیان در این دفتر وجود ندارد.</p>}
    {!!selectedYear&&<>
      <p className="pra-source">منبع: بکاپ SQL بازیابی‌شده سال {year} · {selectedYear.rowCount.toLocaleString('fa-IR')} رکورد اصلی ·
        {' '}{selectedYear.currencyVerified?'واحد مالی منبع اعلام‌شده ریال است':'واحد پول این سال هنوز تطبیق رسمی ندارد'}</p>
      <div className="pra-layout">
        <aside className="pra-tables" aria-label="جدول‌های آرشیوی">
          <input type="search" value={needle} onChange={e=>setNeedle(e.target.value)}
            placeholder="جست‌وجوی نام جدول" aria-label="جست‌وجوی جدول پارسیان"/>
          <div className="pra-table-list">{tables.map(t=><button key={t.name}
            type="button" className={table===t.name?'selected':''} onClick={()=>chooseTable(t.name)}>
              <span dir="ltr">{t.name}</span><small>{t.rows.toLocaleString('fa-IR')}</small>
            </button>)}</div>
        </aside>
        <div className="pra-records">
          <h4>{table||'یک جدول را برای مشاهده اطلاعات انتخاب کنید'}</h4>
          {error&&<p role="alert" className="pra-error">{error}</p>}
          {loading&&<p role="status">خواندن داده‌های آرشیوی...</p>}
          {page&&<>
            <p>نمایش {page.rows.length.toLocaleString('fa-IR')} سطر از {page.total.toLocaleString('fa-IR')} سطر،
               داده‌ها صرفاً آرشیوی‌اند.</p>
            {page.rows.map(record=><details key={record.ordinal} className="pra-record">
              <summary>ردیف اصلی {record.ordinal.toLocaleString('fa-IR')} · {Object.keys(record.fields).length} فیلد</summary>
              <dl>{Object.entries(record.fields).map(([name,value])=><React.Fragment key={name}>
                <dt dir="ltr">{name}</dt><dd dir="auto">{String(value)}</dd>
              </React.Fragment>)}</dl>
            </details>)}
            <div className="pra-pagination">
              <button type="button" disabled={loading||offset===0}
                onClick={()=>setOffset(Math.max(0,offset-40))}>صفحه قبل</button>
              <span>{Math.floor(offset/40)+1} / {Math.max(1,Math.ceil(page.total/40))}</span>
              <button type="button" disabled={loading||offset+40>=page.total}
                onClick={()=>setOffset(offset+40)}>صفحه بعد</button>
            </div>
          </>}
        </div>
      </div>
    </>}
  </section>;
}
