import React from 'react';

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
  return <div className="sac-wizard-heading">
    <div className="sac-wizard-heading-top">
      <div>
        <strong>ثبت فاکتور فروش</strong>
        <span>وضعیت: پیش‌نویس {hasUnsavedChanges?'· تغییرات ذخیره‌نشده':'· هنوز ثبت نشده'}</span>
      </div>
      <div className="sac-wizard-view" role="group" aria-label="نوع نمایش فرم فاکتور">
        <button type="button" aria-pressed={guided} disabled={disabled}
          onClick={()=>onModeChange('guided')}>راهنمای مرحله‌ای</button>
        <button type="button" aria-pressed={!guided} disabled={disabled}
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
