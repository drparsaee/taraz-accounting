import React from 'react';
import './accounting_invoice_wizard.css';

export const INVOICE_WIZARD_STEPS=[
  {id:'document',title:'مشتری و سند',hint:'شماره، مشتری و تاریخ'},
  {id:'lines',title:'اقلام فاکتور',hint:'شرح، تعداد و قیمت'},
  {id:'tax',title:'تخفیف و مالیات',hint:'محاسبه مبلغ نهایی'},
  {id:'due',title:'پرداخت و موعد',hint:'سررسید و توضیحات'},
  {id:'review',title:'مرور و ذخیره',hint:'بازبینی پیش‌نویس'},
];

export function InvoiceWizardNavigation({step,mode,onModeChange,onStepChange,
  disabled=false,hasUnsavedChanges=false}){
  const guided=mode==='guided';
  const beginner=mode==='beginner';
  return <div className="sac-wizard-heading">
    <div className="sac-wizard-heading-top">
      <div>
        <strong>ثبت فاکتور فروش</strong>
        <span>وضعیت: پیش‌نویس {hasUnsavedChanges?'· تغییرات ذخیره‌نشده':'· هنوز ثبت نشده'}</span>
      </div>
      <div className="sac-wizard-view" role="group" aria-label="نوع نمایش فرم فاکتور">
        <button type="button" aria-pressed={beginner} disabled={disabled}
          onClick={()=>onModeChange('beginner')}>ساده و سریع</button>
        <button type="button" aria-pressed={guided} disabled={disabled}
          onClick={()=>onModeChange('guided')}>راهنمای مرحله‌ای</button>
        <button type="button" aria-pressed={mode==='advanced'} disabled={disabled}
          onClick={()=>onModeChange('advanced')}>حالت حرفه‌ای</button>
      </div>
    </div>
    {guided&&<nav className="sac-wizard-step-nav" aria-label="مراحل ثبت فاکتور فروش">
      {INVOICE_WIZARD_STEPS.map((item,index)=><button key={item.id}
        type="button" aria-current={step===index?'step':undefined}
        aria-controls={'sac-wizard-panel-'+item.id}
        disabled={disabled}
        onClick={()=>onStepChange(index)}
        className={step===index?'active':''}>
        <b>{Number(index+1).toLocaleString('fa-IR')}</b>
        <span>{item.title}</span>
      </button>)}
    </nav>}
    {guided&&<p className="sac-wizard-step-hint" aria-live="polite">
      مرحله {Number(step+1).toLocaleString('fa-IR')} از ۵: {INVOICE_WIZARD_STEPS[step].hint}.
      اطلاعات شما هنگام رفت‌وبرگشت بین مراحل حفظ می‌شود.
    </p>}
  </div>;
}

// Pure UI feedback only. The existing buildStandaloneInvoiceCommand and host
// remain the authoritative validators; never call any finance API here.
const AMOUNT=/^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$/;
const MAX=1000000000000000n;
function nonnegative(value){
  const text=String(value??'').trim()
    .replace(/[۰-۹]/g,d=>String(d.charCodeAt(0)-1776))
    .replace(/[٠-٩]/g,d=>String(d.charCodeAt(0)-1632))
    .replace(/\u066c/g,',');
  if(!AMOUNT.test(text))return null;
  try{const number=BigInt(text.replace(/,/g,''));return number<=MAX?number:null;}
  catch{return null;}
}

// Suggestions never alter an invoice line until the operator explicitly accepts.
const normalizeItemText=value=>String(value||'').trim().toLocaleLowerCase('fa-IR')
  .replace(/[يى]/g,'ی').replace(/ك/g,'ک').replace(/\s+/g,' ');
export function suggestedInvoiceCatalogItem(description,items={}){
  const needle=normalizeItemText(description);
  if(needle.length<3)return null;
  const candidates=Object.values(items).filter(item=>item?.active===true&&
    item.id&&normalizeItemText(item.name));
  const exact=candidates.filter(item=>normalizeItemText(item.name)===needle||
    normalizeItemText(item.sku)===needle);
  if(exact.length===1)return exact[0];
  if(exact.length>1)return null;
  const matches=candidates.filter(item=>{
    const name=normalizeItemText(item.name);
    return needle.length>=5&&(name.includes(needle)||needle.includes(name));
  });
  return matches.length===1?matches[0]:null;
}
export function invoiceRowsForSubmission(rows=[]){
  const kept=[...rows];
  // The auto-appended last line is a UI affordance, not an empty ledger line.
  while(kept.length>1){
    const row=kept[kept.length-1];
    if(String(row.description||'').trim()||String(row.unitPrice||'').trim()||
      row.itemId||row.accountId||String(row.quantity??'1')!=='1')break;
    kept.pop();
  }
  return kept;
}
export const EXTRA_NOTE_MARKER=' | توضیح تکمیلی تراز: ';
export function splitInvoiceExplanation(note=''){
  if(String(note).startsWith('توضیح تکمیلی تراز: '))return {
    note:'',extraExplanation:String(note).slice('توضیح تکمیلی تراز: '.length)};
  const position=String(note).lastIndexOf(EXTRA_NOTE_MARKER);
  return position<0?{note:String(note),extraExplanation:''}:{
    note:String(note).slice(0,position),extraExplanation:String(note).slice(position+EXTRA_NOTE_MARKER.length)};
}
export function composeInvoiceExplanation(note='',extraExplanation=''){
  const base=String(note).trim().replace(/\s+/g,' '),
    extra=String(extraExplanation).trim().replace(/\s+/g,' ');
  return base+(extra?(base?EXTRA_NOTE_MARKER:'توضیح تکمیلی تراز: ')+extra:'');
}
export function existingWalkInCustomer(customers=[]){
  const matches=customers.filter(customer=>/^(مشتری حضوری|مشتری متفرقه)$/.test(
    String(customer.name||'').trim()));
  return matches.length===1?matches[0]:null;
}

export function beginnerInvoiceReadiness({document={},rows=[],accounts={},items={},tax='0'}){
  const issues=[];
  if(!document.partyId)issues.push('یک مشتری را از فهرست انتخاب کنید.');
  if(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/.test(document.documentId||''))
    issues.push('شماره داخلی فاکتور معتبر نیست؛ آن را در حالت حرفه‌ای بررسی کنید.');
  if(!/^\d{4}-\d{2}-\d{2}$/.test(document.documentDate||''))
    issues.push('تاریخ فاکتور معتبر نیست.');
  if(!rows.length||rows.length>1000)issues.push('حداقل یک ردیف و حداکثر هزار ردیف وارد کنید.');
  let subtotal=0n;
  rows.forEach((row,index)=>{
    const line=index+1;
    if(!row?.description?.trim())issues.push(`شرح ردیف ${line} را بنویسید.`);
    else if(row.description.trim().length>300)issues.push(`شرح ردیف ${line} بیش از حد طولانی است.`);
    const qty=nonnegative(row?.quantity),price=nonnegative(row?.unitPrice);
    if(qty===null||qty===0n||qty>1000000n)
      issues.push(`تعداد ردیف ${line} باید عدد صحیح و بزرگ‌تر از صفر باشد.`);
    if(price===null)issues.push(`قیمت واحد ردیف ${line} معتبر نیست.`);
    const account=row?.accountId||'4000';
    if(accounts[account]?.kind!=='revenue')
      issues.push(`سرفصل درآمد ردیف ${line} معتبر نیست؛ از جزئیات ردیف آن را انتخاب کنید.`);
    if(row?.itemId&&items[row.itemId]?.active!==true)
      issues.push(`قلم کاتالوگ ردیف ${line} فعال نیست؛ در حالت حرفه‌ای اصلاح کنید.`);
    if(qty!==null&&price!==null){subtotal+=qty*price;
      if(subtotal>MAX)issues.push('جمع ردیف‌ها از سقف حسابداری بیشتر است.');}
  });
  const discount=nonnegative(document.discount),taxAmount=nonnegative(tax);
  if(discount===null||taxAmount===null||discount>subtotal)
    issues.push('تخفیف یا مالیات معتبر نیست؛ جزئیات مالی را در حالت حرفه‌ای بررسی کنید.');
  const total=discount!==null&&taxAmount!==null?subtotal-discount+taxAmount:null;
  if(total!==null&&(total<=0n||total>MAX))
    issues.push('مبلغ نهایی فاکتور باید مثبت و در محدوده مجاز باشد.');
  return {issues,ready:issues.length===0,
    subtotal:subtotal<=MAX?Number(subtotal):null,
    total:total!==null&&total>=0n&&total<=MAX?Number(total):null};
}

/** An in-place view of the SAME invoice state/submit pipeline as the pro form.
 * No local autosave, issue, post, payment or invented customer creation.
 */
export function BeginnerInvoiceEditor({document={},customers=[],rows=[],accounts={},items={},
  tax='0',preview=null,unitLabel='',moneyText=String,error='',disabled=false,
  onDocumentChange,onRowChange,onAddRow,onRemoveRow,onAdvanced,onClose,
  onCompleteRow,onCatalogAccept,onRegisterCustomer,onDocumentTypeChange,
  documentType='invoice',extraExplanation='',onExtraExplanationChange,
  saveDisabled=false,dateControl}){
  const [search,setSearch]=React.useState('');
  const [customerMode,setCustomerMode]=React.useState('existing');
  const [newCustomer,setNewCustomer]=React.useState({partyId:'',name:''});
  const [creatingCustomer,setCreatingCustomer]=React.useState(false);
  const [customerError,setCustomerError]=React.useState('');
  const [dismissedItems,setDismissedItems]=React.useState({});
  const [showSuggestions,setShowSuggestions]=React.useState(()=>{
    try{return globalThis.localStorage?.getItem('taraz-invoice-item-suggestions-v1')!=='hidden';}
    catch{return true;}
  });
  const realRows=invoiceRowsForSubmission(rows);
  const review=beginnerInvoiceReadiness({document,rows:realRows,accounts,items,tax});
  const choices=customers.filter(customer=>String(customer.name||customer.id)
    .toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())).slice(0,100);
  const revenue=Object.values(accounts).filter(account=>account.kind==='revenue');
  const amount=value=>value===null||value===undefined?'نامشخص':moneyText(value);
  return <section className="sac-invoice-beginner-pane" aria-label="ثبت سریع فاکتور فروش"
    onKeyDown={event=>{
      // Pressing Enter while typing must never become an implicit finance
      // submit. Only the explicit Save Draft button triggers the host pipeline.
      if(event.key==='Enter'&&!event.isComposing&&event.target?.tagName==='INPUT')
        event.preventDefault();
    }}>
    <div className="sac-beginner-intro">
      <div><h3>{documentType==='proforma'?'پیش‌فاکتور در یک صفحه':'فاکتور در یک صفحه'}</h3>
        <p>مشتری، شرح، تعداد و قیمت را وارد کنید؛ مبلغ فوراً محاسبه می‌شود.</p></div>
      <span className="sac-beginner-status">{review.ready?'آمادهٔ ذخیره':'در حال تکمیل پیش‌نویس'}</span>
    </div>
    <fieldset className="sac-beginner-kind" disabled={disabled}>
      <legend>چه سندی می‌خواهید بسازید؟</legend>
      <label><input type="radio" name="taraz-beginner-kind" value="proforma"
        checked={documentType==='proforma'} onChange={()=>onDocumentTypeChange?.('proforma')}/>
        پیش‌فاکتور (پیشنهاد قیمت)</label>
      <label><input type="radio" name="taraz-beginner-kind" value="invoice"
        checked={documentType==='invoice'} onChange={()=>onDocumentTypeChange?.('invoice')}/>
        فاکتور فروش (ابتدا پیش‌نویس)</label>
      <small>هیچ‌کدام تا زمان صدور قطعی فاکتور به دفترکل منتقل نمی‌شوند.</small>
    </fieldset>
    <div className="sac-beginner-fields">
      <div className="sac-beginner-field sac-beginner-customer">
        <span>۱. مشتری <b aria-hidden="true">*</b></span>
        <div className="sac-beginner-customer-modes" role="group" aria-label="نوع مشتری">
          {[['existing','انتخاب مشتری'],['new','مشتری جدید'],['walkin','مشتری حضوری']]
            .map(([mode,title])=><button key={mode} type="button" disabled={disabled}
              aria-pressed={customerMode===mode} onClick={()=>{
                setCustomerMode(mode);setCustomerError('');
                if(mode==='walkin'){
                  const existing=existingWalkInCustomer(customers);
                  if(existing)onDocumentChange('partyId',existing.id);
                  else{onDocumentChange('partyId','');setNewCustomer(c=>({...c,name:'مشتری حضوری'}));}
                }
              }}>{title}</button>)}
        </div>
        {customerMode==='existing'&&<>
        <input type="search" value={search} disabled={disabled}
          onChange={event=>setSearch(event.target.value)}
          placeholder="جست‌وجوی نام یا کد مشتری" aria-label="جست‌وجوی مشتری"/>
        <select required value={document.partyId||''} disabled={disabled}
          aria-label="مشتری فاکتور" onChange={event=>onDocumentChange('partyId',event.target.value)}>
          <option value="">مشتری را انتخاب کنید</option>
          {document.partyId&&!choices.some(customer=>customer.id===document.partyId)&&
            customers.filter(c=>c.id===document.partyId).map(c=><option key={c.id} value={c.id}>
              {c.name||c.id} ({c.id})</option>)}
          {choices.map(c=><option key={c.id} value={c.id}>{c.name||c.id} ({c.id})</option>)}
        </select>
        {!customers.length&&<small role="status">هنوز مشتری ثبت نشده است؛ از بخش اشخاص یک مشتری بسازید.</small>}
        </>}
        {customerMode==='walkin'&&existingWalkInCustomer(customers)&&
          <small role="status">مشتری حضوری ثبت‌شده انتخاب شد: {existingWalkInCustomer(customers).name}</small>}
        {(customerMode==='new'||(customerMode==='walkin'&&!existingWalkInCustomer(customers)))&&<div
          className="sac-beginner-new-customer">
          <small>برای صدور سند، حتی مشتری حضوری باید شناسهٔ واقعی و ثبت‌شده داشته باشد.</small>
          <label>شناسهٔ جدید مشتری<input dir="ltr" maxLength={96} disabled={disabled||creatingCustomer}
            aria-label="شناسه مشتری جدید" placeholder="PERSON-001" value={newCustomer.partyId}
            onChange={e=>setNewCustomer(c=>({...c,partyId:e.target.value}))}/></label>
          <label>نام مشتری<input maxLength={300} disabled={disabled||creatingCustomer}
            aria-label="نام مشتری جدید" value={newCustomer.name}
            onChange={e=>setNewCustomer(c=>({...c,name:e.target.value}))}/></label>
          <button type="button" disabled={disabled||creatingCustomer} onClick={async()=>{
            if(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/.test(newCustomer.partyId)||
                !newCustomer.name.trim()||newCustomer.name.trim().length>300){
              setCustomerError('نام و شناسه معتبر مشتری را وارد کنید.');return;}
            if(!globalThis.confirm?.('مشتری «'+newCustomer.name.trim()+
              '» با شناسه '+newCustomer.partyId+' در دفتر ثبت شود؟'))return;
            setCreatingCustomer(true);setCustomerError('');
            try{
              const success=await onRegisterCustomer?.({...newCustomer,name:newCustomer.name.trim()});
              if(success){onDocumentChange('partyId',newCustomer.partyId);setCustomerMode('existing');}
              else setCustomerError('ثبت مشتری در میزبان تأیید نشد؛ اطلاعات برای تلاش بعدی حفظ شد.');
            }catch{setCustomerError('نتیجه ثبت مشتری نامشخص است؛ پیش از تکرار دفتر را بررسی کنید.');}
            finally{setCreatingCustomer(false);}
          }}>تأیید و ثبت مشتری در دفتر</button>
          {customerError&&<small role="alert">{customerError}</small>}
        </div>}
      </div>
      <div className="sac-beginner-document-meta">
        <span>شماره: <b dir="ltr">{document.documentId||'نامشخص'}</b></span>
        <label>تاریخ فاکتور {dateControl}</label>
        <button type="button" disabled={disabled} onClick={onAdvanced}>ویرایش جزئیات سند</button>
      </div>
    </div>
    <section aria-label="اقلام فاکتور" className="sac-beginner-lines">
      <div className="sac-beginner-lines-title"><h4>۲. کالا یا خدمت</h4>
        <span>{realRows.length.toLocaleString('fa-IR')} ردیف تکمیل‌شدنی</span></div>
      {showSuggestions&&<button className="sac-beginner-hide-suggestions" type="button"
        disabled={disabled} onClick={()=>{
          setShowSuggestions(false);
          try{globalThis.localStorage?.setItem('taraz-invoice-item-suggestions-v1','hidden');}
          catch{/* Browser storage unavailable: preference remains in this editor. */}
        }}>دیگر پیشنهاد کد کالا نشان داده نشود</button>}
      {rows.map((row,index)=><div className="sac-beginner-row" key={index}
        data-beginner-row={index}>
        <div className="sac-beginner-row-top"><strong>ردیف {(index+1).toLocaleString('fa-IR')}</strong>
          <button type="button" disabled={disabled||rows.length===1}
            onClick={()=>onRemoveRow(index)} aria-label={`حذف ردیف ${index+1}`}>حذف</button></div>
        <div className="sac-beginner-row-grid">
          <label className="sac-beginner-description">شرح کالا یا خدمت
            <input required maxLength={300} disabled={disabled}
              aria-label={`شرح ردیف ${index+1}`} placeholder="مثلاً طراحی بسته‌بندی"
              value={row.description||''} onChange={event=>onRowChange(index,'description',event.target.value)}/>
          </label>
          <label>تعداد<input required dir="ltr" inputMode="numeric" disabled={disabled}
            aria-label={`تعداد ردیف ${index+1}`} value={row.quantity??''}
            onChange={event=>onRowChange(index,'quantity',event.target.value)}/></label>
          <label>قیمت واحد ({unitLabel})<input required dir="ltr" inputMode="numeric" disabled={disabled}
            aria-label={`قیمت ردیف ${index+1}`} value={row.unitPrice??''} placeholder="0"
            onChange={event=>onRowChange(index,'unitPrice',event.target.value)}
            onBlur={event=>{
              if(!event.relatedTarget?.closest?.('[type="submit"]'))onCompleteRow?.(index);
            }} onKeyDown={event=>{
              if(event.key==='Enter'&&!event.isComposing){
                event.preventDefault();onCompleteRow?.(index);
              }
            }}/></label>
          <output aria-label={`جمع ردیف ${index+1}`} className="sac-beginner-row-amount">
            <span>جمع ردیف</span><b>{(()=>{
              const qty=nonnegative(row.quantity),price=nonnegative(row.unitPrice);
              const result=qty!==null&&price!==null?qty*price:null;
              return result!==null&&result<=MAX?amount(Number(result)):'—';
            })()}</b>
          </output>
        </div>
        <div className="sac-beginner-item-association">
          <span>واحد: <b>{row.itemId&&items[row.itemId]?.active===true?
            items[row.itemId].unit||'نامشخص':'عدد'}</b></span>
          {row.itemId?<span>کد انتخاب‌شده: <b dir="ltr">{items[row.itemId]?.sku||row.itemId}</b>
            <button type="button" disabled={disabled} onClick={()=>onRowChange(index,'itemId','')}>
              حذف ارتباط کاتالوگ</button></span>:<span>ردیف سفارشی بدون کد کالا</span>}
          {showSuggestions&&!row.itemId&&(()=>{
            const item=suggestedInvoiceCatalogItem(row.description,items);
            if(!item||dismissedItems[index]===row.description)return null;
            return <div className="sac-beginner-item-suggestion" role="group"
              aria-label={`پیشنهاد کاتالوگ ردیف ${index+1}`}>
              <span>کد پیشنهادی: <b>{item.sku||item.id}</b>، {item.name} (واحد: {item.unit||'نامشخص'})</span>
              <button type="button" disabled={disabled} onClick={()=>onCatalogAccept?.(index,item.id)}>
                تأیید کد پیشنهادی</button>
              <button type="button" disabled={disabled} onClick={()=>setDismissedItems(p=>({...p,
                [index]:row.description}))}>رد پیشنهاد</button>
            </div>;
          })()}
        </div>
        <details className="sac-beginner-account-details">
          <summary>سرفصل حسابداری ردیف (اختیاری برای حساب پیش‌فرض)</summary>
          <label>حساب درآمد
            <select value={row.accountId||'4000'} disabled={disabled}
              aria-label={`حساب درآمد ردیف ${index+1}`}
              onChange={event=>onRowChange(index,'accountId',event.target.value)}>
              <option value="4000">حساب پیش‌فرض ۴۰۰۰</option>
              {revenue.filter(a=>a.id!=='4000').map(a=><option key={a.id} value={a.id}>
                {a.name||a.id} ({a.id})</option>)}
            </select>
          </label>
        </details>
      </div>)}
      <button type="button" className="sac-beginner-add" disabled={disabled||rows.length>=1000}
        onClick={onAddRow}>+ افزودن کالا یا خدمت</button>
    </section>
    <label className="sac-beginner-explanation">توضیح سند (اختیاری)
      <textarea maxLength={1000} rows={2} value={document.note||''} disabled={disabled}
        aria-label="یادداشت سند" onChange={e=>onDocumentChange('note',e.target.value)}
        placeholder="مثلاً شرح ارجاع مدار، قابل ویرایش یا حذف"/>
    </label>
    <label className="sac-beginner-explanation">توضیح تکمیلی جداگانه (اختیاری)
      <textarea maxLength={500} rows={2} value={extraExplanation} disabled={disabled}
        aria-label="توضیح تکمیلی" onChange={e=>onExtraExplanationChange?.(e.target.value)}
        placeholder="توضیح آزاد که همراه با یادداشت در سند ذخیره می‌شود"/>
    </label>
    <div className="sac-beginner-bottom">
      <section className="sac-beginner-preview" aria-label="پیش‌نمایش مبلغ فاکتور">
        <h4>۳. پیش‌نمایش فاکتور</h4>
        <div><span>جمع اقلام</span><b>{amount(preview?.subtotal)}</b></div>
        <div><span>تخفیف</span><b>{amount(preview?.discount)}</b></div>
        <div><span>مالیات</span><b>{amount(preview?.tax)}</b></div>
        <div className="sac-beginner-grand-total"><span>مبلغ نهایی ({unitLabel})</span>
          <strong>{amount(preview?.total)}</strong></div>
        {(document.discount!=='0'||String(tax)!=='0'||document.taxRuleId)&&
          <button type="button" onClick={onAdvanced} disabled={disabled}>
            تنظیم تخفیف و مالیات در حالت حرفه‌ای</button>}
      </section>
      <section className="sac-beginner-check" aria-label="بررسی پیش از ذخیره">
        <strong>بررسی قبل از ذخیره</strong>
        {review.ready?<p role="status">اطلاعات اصلی تکمیل است. ذخیره فقط با دکمهٔ زیر انجام می‌شود.</p>:
          <ul aria-live="polite">{review.issues.slice(0,5).map((issue,index)=><li key={index}>{issue}</li>)}</ul>}
        {error&&<p className="sac-wizard-alert" role="alert">{error}</p>}
        <p className="sac-beginner-disclaimer">ذخیره، فقط {documentType==='proforma'?'پیش‌فاکتور':'پیش‌نویس فاکتور'} می‌سازد؛ صدور قطعی و ثبت درآمد جداگانه انجام می‌شوند.</p>
        <div className="sac-beginner-actions">
          <button type="submit" className="sac-primary sac-beginner-save" disabled={disabled||saveDisabled}>
            {documentType==='proforma'?'ذخیره پیش‌فاکتور':'ذخیره پیش‌نویس فاکتور'}</button>
          <button type="button" disabled={disabled} onClick={onClose}>بازگشت بدون ذخیره</button>
        </div>
      </section>
    </div>
  </section>;
}
