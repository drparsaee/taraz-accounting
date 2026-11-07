import React,{useState} from 'react';
import './provider_csv_migration.css';

export const CSV_GROUPS={
  parties:{label:'اشخاص',fields:{id:'شناسه شخص',name:'نام شخص',kind:'نوع شخص'}},
  invoices:{label:'اسناد خرید و فروش',fields:{id:'شناسه سند',partyId:'شناسه شخص',
    kind:'نوع سند',date:'تاریخ میلادی',status:'وضعیت سند',total:'جمع مبلغ'}},
  transactions:{label:'دریافت و پرداخت',fields:{id:'شناسه تراکنش',partyId:'شناسه شخص',
    documentId:'شناسه سند',kind:'نوع تراکنش',date:'تاریخ میلادی',amount:'مبلغ'}},
};
const groups=Object.keys(CSV_GROUPS);
const TOTALS={invoice:'جمع فروش',bill:'جمع خرید',receipt:'جمع دریافت',payment:'جمع پرداخت'};
const validAmount=value=>!value||/^[0-9]+$/.test(value);

/** This builds only a strict read-only preview request; the host enforces selection. */
export function buildProviderCsvRequest({provider,currency,files,mappings,ignored,
  valueMaps,counts,totals}){
  const datasets={};
  for(const group of groups){
    const file=files[group];
    if(!file?.path||!Array.isArray(file.columns))throw new Error('انتخاب هر سه فایل CSV الزامی است.');
    const fields=Object.keys(CSV_GROUPS[group].fields);
    const mapping=Object.fromEntries(fields.map(field=>[field,mappings[group]?.[field]||'']));
    if(Object.values(mapping).some(value=>!file.columns.includes(value))){
      throw new Error('نگاشت همه ستون‌های '+CSV_GROUPS[group].label+' الزامی است.');
    }
    const ignoredColumns=file.columns.filter(col=>ignored[group]?.includes(col));
    if(file.columns.some(col=>!Object.values(mapping).includes(col)&&!ignoredColumns.includes(col))){
      throw new Error('ستون‌های اضافه باید صریحاً نادیده گرفته شوند: '+CSV_GROUPS[group].label);
    }
    let enumMapping={};
    try {enumMapping=JSON.parse(valueMaps[group]||'{}');}
    catch {throw new Error('نگاشت مقادیر باید JSON معتبر باشد: '+CSV_GROUPS[group].label);}
    datasets[group]={path:file.path,format:'csv',encoding:file.encoding,
      delimiter:file.delimiter,mapping,ignoreColumns:ignoredColumns,valueMaps:enumMapping};
  }
  if(!provider.trim())throw new Error('نام نرم‌افزار مبدأ الزامی است.');
  if(currency!=='RIAL')throw new Error('واحد پول مبدأ باید ریال و مستقل از حدس تأیید شده باشد.');
  const expectations={counts:{},totals:{}};
  for(const [group,value] of Object.entries(counts)){
    if(!validAmount(value))throw new Error('تعداد مورد انتظار فقط عدد صحیح است.');
    if(value!=='')expectations.counts[group]=Number(value);
  }
  for(const [kind,value] of Object.entries(totals)){
    if(!validAmount(value))throw new Error('مبلغ مورد انتظار فقط عدد صحیح است.');
    if(value!=='')expectations.totals[kind]=Number(value);
  }
  if([...Object.values(expectations.counts),...Object.values(expectations.totals)]
    .some(n=>!Number.isSafeInteger(n)))throw new Error('مقدار مورد انتظار خارج از محدوده امن است.');
  return {schemaVersion:1,provider:provider.trim(),currency,datasets,expectations};
}

export function useProviderCsvPreview(api){
  const [files,setFiles]=useState({});
  const [mapping,setMapping]=useState({});
  const [ignored,setIgnored]=useState({});
  const [valueMaps,setValueMaps]=useState({});
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [result,setResult]=useState(null);
  const changeFile=async(group,encoding,delimiter)=>{
    setResult(null);setError('');setBusy(true);
    setFiles(old=>({...old,[group]:null}));
    try{
      if(typeof api?.standaloneAccountingCsvChooseFile!=='function')
        throw new Error('انتخاب فایل در نسخه میزبان فعال نیست.');
      const selected=await api.standaloneAccountingCsvChooseFile(group,encoding,delimiter);
      if(!selected?.canceled){
        setFiles(old=>({...old,[group]:selected}));
        setMapping(old=>({...old,[group]:{}}));
        setIgnored(old=>({...old,[group]:[]}));
      }
    }catch(exc){setError(exc?.message||'انتخاب فایل ناموفق بود.');}
    finally{setBusy(false);}
  };
  const preview=async(config)=>{
    setResult(null);setError('');setBusy(true);
    try{
      const request=buildProviderCsvRequest({...config,files,mappings:mapping,ignored,valueMaps});
      if(typeof api?.standaloneAccountingCsvPreview!=='function')
        throw new Error('پیش‌نمایش در نسخه میزبان فعال نیست.');
      setResult(await api.standaloneAccountingCsvPreview(request));
    }catch(exc){setError(exc?.message||'اعتبارسنجی CSV ناموفق بود.');}
    finally{setBusy(false);}
  };
  return {files,mapping,setMapping,ignored,setIgnored,valueMaps,setValueMaps,
    busy,error,result,setResult,changeFile,preview};
}

export default function ProviderCsvMigration({api,canAdmin=false}){
  const [provider,setProvider]=useState('');
  const [currency,setCurrency]=useState('');
  const [encoding,setEncoding]=useState('utf-8-sig');
  const [delimiter,setDelimiter]=useState(',');
  const [counts,setCounts]=useState({parties:'',invoices:'',transactions:''});
  const [totals,setTotals]=useState({invoice:'',bill:'',receipt:'',payment:''});
  const {files,mapping,setMapping,ignored,setIgnored,valueMaps,setValueMaps,
    busy,error,result,setResult,changeFile,preview}=useProviderCsvPreview(api);
  if(!canAdmin)return null;
  const resetPreview=()=>setResult(null);
  return <section className="pcsv-panel" aria-label="پیش‌نمایش ورود CSV از نرم‌افزارهای دیگر">
    <header><h3>پیش‌نمایش CSV سایر نرم‌افزارهای حسابداری</h3>
      <p>فایل‌ها فقط خوانده می‌شوند. هیچ سندی صادر یا در دفتر مدار ثبت نمی‌شود.</p></header>
    <div className="pcsv-config">
      <label>نام نرم‌افزار مبدأ<input aria-label="نام نرم‌افزار مبدأ" value={provider}
        maxLength={100} onChange={e=>{setProvider(e.target.value);resetPreview();}}
        placeholder="نام نرم‌افزار مبدأ را وارد کنید"/></label>
      <label>واحد واقعی مبالغ
        <select aria-label="واحد مالی CSV" value={currency}
          onChange={e=>{setCurrency(e.target.value);resetPreview();}}>
          <option value="">انتخاب الزامی است</option><option value="RIAL">ریال (RIAL)</option>
          <option value="TOMAN">تومان (پشتیبانی‌نشده)</option>
        </select></label>
      <label>کدگذاری متن<select value={encoding} onChange={e=>setEncoding(e.target.value)}>
        <option value="utf-8-sig">UTF-8 با/بدون BOM</option>
        <option value="utf-8">UTF-8 بدون BOM</option><option value="cp1256">Windows-1256</option>
      </select></label>
      <label>جداکننده<select value={delimiter} onChange={e=>setDelimiter(e.target.value)}>
        <option value=",">ویرگول</option><option value=";">نقطه‌ویرگول</option>
        <option value={'\t'}>Tab</option></select></label>
    </div>
    {groups.map(group=>{
      const file=files[group],selected=new Set(Object.values(mapping[group]||{}));
      const ignoredCols=ignored[group]||[];
      return <fieldset className="pcsv-dataset" key={group} disabled={busy}>
        <legend>{CSV_GROUPS[group].label}</legend>
        <div className="pcsv-file"><button type="button"
          onClick={()=>changeFile(group,encoding,delimiter)}>انتخاب CSV</button>
          <span dir="auto">{file?.filename||'فایلی انتخاب نشده است'}</span></div>
        {file&&<>
          <div className="pcsv-columns">
            {Object.entries(CSV_GROUPS[group].fields).map(([field,label])=><label key={field}>
              {label}<select value={mapping[group]?.[field]||''}
                aria-label={label+' در '+CSV_GROUPS[group].label}
                onChange={e=>{setMapping(old=>({...old,[group]:{...old[group],
                  [field]:e.target.value}}));resetPreview();}}>
                <option value="">انتخاب ستون مبدأ</option>
                {file.columns.map(col=><option key={col} value={col}>{col}</option>)}
              </select></label>)}
          </div>
          <div className="pcsv-extras"><strong>ستون‌های استفاده‌نشده</strong>
            {file.columns.filter(col=>!selected.has(col)).map(col=><label key={col}>
              <input type="checkbox" checked={ignoredCols.includes(col)} onChange={e=>{
                setIgnored(old=>({...old,[group]:e.target.checked?
                  [...(old[group]||[]),col]:(old[group]||[]).filter(x=>x!==col)}));resetPreview();
              }}/>{col} را آگاهانه نادیده بگیر</label>)}
          </div>
          <label>تبدیل صریح مقادیر دسته‌بندی (JSON اختیاری)
            <textarea dir="ltr" rows={2} spellCheck={false}
              value={valueMaps[group]||''} placeholder='{"kind":{"خریدار":"customer"}}'
              onChange={e=>{setValueMaps(old=>({...old,[group]:e.target.value}));resetPreview();}}/>
          </label>
        </>}
        <label>تعداد سطر مورد انتظار (اختیاری)
          <input dir="ltr" inputMode="numeric" value={counts[group]}
            onChange={e=>{setCounts(old=>({...old,[group]:e.target.value}));resetPreview();}}
            placeholder="از گزارش سیستم مبدأ"/></label>
      </fieldset>;
    })}
    <details className="pcsv-expectations"><summary>تطبیق جمع مبالغ با گزارش مبدأ (اختیاری)</summary>
      <div className="pcsv-config">{Object.entries(TOTALS).map(([kind,label])=><label key={kind}>
        {label} (ریال)<input dir="ltr" inputMode="numeric" value={totals[kind]}
          placeholder="جمع رسمی مبدأ" onChange={e=>{setTotals(old=>({...old,[kind]:e.target.value}));resetPreview();}}/>
      </label>)}</div>
    </details>
    <div className="pcsv-actions"><button type="button" disabled={busy||currency!=='RIAL'}
      onClick={()=>preview({provider,currency,counts,totals})}>
      {busy?'در حال بررسی...':'اجرای پیش‌نمایش فقط‌خواندنی'}</button>
      <small>تومان، واحد نامشخص و نگاشت ناقص رد می‌شوند.</small></div>
    {error&&<p role="alert" className="pcsv-error">{error}</p>}
    {result&&<div className="pcsv-result" role="status">
      <h4>{result.structuralChecksPassed?'بررسی ساختاری بدون مغایرت گزارش‌شده':'مغایرت در داده‌های مبدأ'}</h4>
      <p>وضعیت: فقط پیش‌نمایش؛ انتقال به دفتر حسابداری غیرفعال است.</p>
      <div className="pcsv-stats">{groups.map(group=><span key={group}>
        {CSV_GROUPS[group].label}: <b>{result.counts?.[group]?.toLocaleString('fa-IR')}</b></span>)}</div>
      <div className="pcsv-stats">{Object.entries(TOTALS).map(([kind,label])=><span key={kind}>
        {label}: <b>{result.totalsRial?.[kind]?.toLocaleString('fa-IR')} ریال</b></span>)}</div>
      {groups.map(group=><details key={group} className="pcsv-samples">
        <summary>نمونهٔ سه ردیف {CSV_GROUPS[group].label} (بدون ثبت)</summary>
        {(result.previewRows?.[group]||[]).map((row,index)=><dl key={index}>
          {Object.entries(row).map(([field,value])=><React.Fragment key={field}>
            <dt>{field}</dt><dd dir="auto">{String(value)}</dd>
          </React.Fragment>)}
        </dl>)}
      </details>)}
      <ul>{(result.discrepancies||[]).map((issue,index)=><li key={index} dir="auto">
        {issue.type} · {issue.group||issue.documentFingerprint||''} ·
        {issue.expected!==undefined?' مقدار مورد انتظار: '+issue.expected:''}
        {issue.actual!==undefined?' مقدار واقعی: '+issue.actual:''}
      </li>)}</ul>
      <p>هش فایل‌ها برای بررسی تکرار محاسبه شده‌اند. این بررسی، تطبیق دفترکل یا تأیید انتقال مالی نیست.</p>
    </div>}
  </section>;
}
