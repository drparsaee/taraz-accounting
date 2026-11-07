import React,{useEffect,useMemo,useState} from 'react';
import './personal_parsian_extended.css';

const categories=[
 ['tbl_Goods','کالا و خدمات'],
 ['tbl_GoodsGroup','گروه کالا'],
 ['tbl_Tafsili','حساب‌های تفصیلی'],
 ['tbl_Telephone','اطلاعات تماس'],
 ['tbl_Storehouse','انبارهای مبدا'],
 ['tbl_FactorKind','انواع عملیات و فاکتور'],
 ['tbl_FactNum','شماره‌گذاری اسناد و فاکتورها'],
 ['tbl_Moeen','حساب‌های معین'],
 ['tbl_Kol','حساب‌های کل'],
 ['tbl_VATSetting','تنظیمات مالیاتی منبع'],
 ['tbl_AccSetting','سرفصل‌های حسابداری منبع'],
 ['tbl_TopCheck','ثبت‌های فنی سررسید منبع'],
 ['tbl_WPersonel','پرونده پرسنلی منبع'],
];
const selectors={
 tbl_Goods:['Code','CName','GroupCode','UnitName_1','UnitName_2','Price_1','Price_2','Price_3','Price_4','Price_5','VATPercent','Barcode'],
 tbl_GoodsGroup:['Code','CName','IsService'],
 tbl_Tafsili:['KolCode','MoeenCode','Code','CName','MaxCredit','FirstRemain'],
 tbl_Telephone:['CName','Tel','Mobile','Address','CodeNat','CodeEco','CodePost','Email'],
 tbl_Storehouse:['Code','CName'],
 tbl_FactorKind:['Code','CName','FactorKind','I/O','HaveDocument','Visible'],
 tbl_FactNum:['TitleCode','FactorKind','I/O','Number'],
 tbl_Moeen:['KolCode','Code','CName'],
 tbl_Kol:['Code','CName'],
 tbl_VATSetting:['CalcTax','VATPercent','AvarezPercent','VATSale_K','VATSale_M'],
 tbl_AccSetting:['Cash_K','Cash_M','Bank_K','Bank_M','Sell_K','Sell_M','Bed_K','Bed_M'],
 tbl_TopCheck:['Row','Date_Rec','ToDay','Money','Sum'],
 tbl_WPersonel:['Code','FName','LName','StartDate','EndDate','Tel','Mobile'],
};
const toText=v=>v===null||v===undefined?'':typeof v==='boolean'?(v?'بله':'خیر'):String(v);
export default function PersonalParsianExtended({api,section='all',fiscalYear='1405',onFiscalYearChange}){
 const [data,setData]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const [year,setYear]=useState(fiscalYear);
 const [table,setTable]=useState(section==='goods'?'tbl_Goods':section==='payroll'?'tbl_WPersonel':section==='due'?'tbl_TopCheck':'tbl_Tafsili');
 const [term,setTerm]=useState(''),[page,setPage]=useState(0),[expanded,setExpanded]=useState('');
 useEffect(()=>{setYear(fiscalYear);setPage(0);setExpanded('');},[fiscalYear]);
 useEffect(()=>{
   let active=true;
   if(typeof api?.standaloneAccountingParsianExtended!=='function'){
     setLoading(false);setError('داده‌های تکمیلی منبع در این نصب قابل خواندن نیستند.');return;
   }
   Promise.resolve().then(()=>api.standaloneAccountingParsianExtended())
    .then(x=>{if(active)setData(x)})
    .catch(e=>{if(active)setError(String(e?.message||e))})
    .finally(()=>{if(active)setLoading(false)});
   return()=>{active=false};
 },[api]);
 const list=data?.sourceYears?.[year]?.[table]||[];
 const filtered=useMemo(()=>{
  const search=term.trim().toLocaleLowerCase('fa-IR');
  return list.filter(item=>!search||Object.values(item).some(val=>toText(val).toLocaleLowerCase('fa-IR').includes(search)));
 },[list,term]);
 const visible=filtered.slice(page*35,(page+1)*35);
 const columns=selectors[table]||[];
 const heading=section==='due'?'\u0633\u0648\u0627\u0628\u0642 \u0633\u0631\u0631\u0633\u06cc\u062f \u0645\u0646\u0628\u0639 \u067e\u0627\u0631\u0633\u06cc\u0627\u0646 (\u0637\u0628\u0642\u0647\u200c\u0628\u0646\u062f\u06cc \u0646\u0634\u062f\u0647)':section==='goods'?'جزئیات واقعی کالاها و قیمت‌های پارسیان':
   section==='payroll'?'سوابق پرسنلی پارسیان':'اطلاعات تکمیلی منتقل‌شده از پارسیان';
 const available=section==='goods'?categories.slice(0,2):section==='payroll'?categories.filter(([k])=>k==='tbl_WPersonel'):section==='due'?categories.filter(([k])=>k==='tbl_TopCheck'):categories;
 if(loading)return <div className="ppe-root" role="status">در حال خواندن داده‌های تکمیلی از دیتابیس مدار...</div>;
 if(error)return <div className="ppe-root ppe-error" role="alert">{error}</div>;
 if(!data)return null;
 return <section className="ppe-root" aria-label={heading}>
    <div className="ppe-head"><h3>{heading}</h3><span>منبع پارسیان · داده در دیتابیس اصلی مدار</span></div>
    <p className="ppe-notice">این جدول، اطلاعات تکمیلی اصلی را بدون تبدیل حدسی نمایش می‌دهد. ثبت دفاتر کل و فاکتورها جدا انجام شده است؛ قیمت تاریخی الزاماً قیمت فروش امروز و ستون‌های انبار الزاماً موجودی فعلی نیستند.</p>
    <div className="ppe-filters">
     <select aria-label="سال منبع پارسیان" value={year} onChange={e=>{setYear(e.target.value);setPage(0);setExpanded('');onFiscalYearChange?.(e.target.value)}}><option value="1405">سال ۱۴۰۵</option><option value="1404">سال ۱۴۰۴</option></select>
     <select aria-label="نوع اطلاعات منبع" value={table} onChange={e=>{setTable(e.target.value);setPage(0);setExpanded('');setTerm('')}}>
       {available.map(([key,label])=><option key={key} value={key}>{label} ({data.sourceYears?.[year]?.[key]?.length||0})</option>)}
     </select>
     <input aria-label="جست‌وجوی داده‌های تکمیلی" type="search" value={term} onChange={e=>{setTerm(e.target.value);setPage(0);setExpanded('')}} placeholder="جست‌وجوی نام، کد یا مقدار منبع"/>
    </div>
    <p className="ppe-count">نمایش {visible.length.toLocaleString('fa-IR')} از {filtered.length.toLocaleString('fa-IR')} رکورد</p>
    <div className="ppe-scroll"><table className="ppe-table"><thead><tr>
      {columns.map(col=><th key={col}>{col}</th>)}<th>جزئیات کامل</th>
    </tr></thead><tbody>{visible.map((row,i)=>{
      const key=year+':'+table+':'+(page*35+i),opened=key===expanded;
      return <React.Fragment key={key}>
        <tr>{columns.map(col=><td key={col}>{toText(row[col])}</td>)}<td><button type="button" aria-expanded={opened} onClick={()=>setExpanded(opened?'':key)}>{opened?'بستن':'تمام فیلدها'}</button></td></tr>
        {opened&&<tr className="ppe-detail"><td colSpan={columns.length+1}>
         <dl>{Object.entries(row).map(([label,v])=><div key={label}><dt>{label}</dt><dd>{toText(v)}</dd></div>)}</dl>
        </td></tr>}
      </React.Fragment>;
    })}</tbody></table></div>
    <div className="ppe-pages"><button type="button" disabled={page===0} onClick={()=>{setPage(x=>x-1);setExpanded('')}}>قبل</button><button type="button" disabled={(page+1)*35>=filtered.length} onClick={()=>{setPage(x=>x+1);setExpanded('')}}>بعد</button></div>
 </section>;
}
