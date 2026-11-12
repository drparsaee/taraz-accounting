import React from 'react';
import {Toaster,sileo} from 'sileo';
import './taraz_sileo_feedback.css';

// Toasts are ephemeral UI feedback only. Never convert one into an accounting
// receipt, source attestation, journal confirmation, or application state.
// In particular never render backend error text, financial amounts, IDs,
// invoice titles, contacts, company names, tokens or arbitrary payloads.
const RECEIPT_LIMIT='اعلان نمایشی است؛ رسید رسمی اتصال مدار و تراز نیست.';
const COMMAND_LABELS=Object.freeze({
  'invoice.create':'پیش‌نویس فاکتور در دفتر میزبان ثبت شد.',
  'invoice.update':'ویرایش پیش‌نویس فاکتور ثبت شد.',
  'invoice.approve':'تأیید فاکتور در دفتر میزبان ثبت شد.',
  'invoice.issue':'ثبت میزبان: صدور فاکتور (نه رسید اتصال)',
  'invoice.cancel':'لغو فاکتور در دفتر میزبان ثبت شد.',
  'invoice.return':'برگشت فاکتور در دفتر میزبان ثبت شد.',
  'invoice.correct':'اصلاح فاکتور در دفتر میزبان ثبت شد.',
  'bill.create':'پیش‌نویس صورتحساب خرید ثبت شد.',
  'bill.update':'ویرایش صورتحساب خرید در دفتر میزبان ثبت شد.',
  'bill.approve':'تأیید صورتحساب خرید در دفتر میزبان ثبت شد.',
  'bill.issue':'ثبت میزبان: صدور صورتحساب خرید',
  'bill.cancel':'لغو صورتحساب خرید در دفتر میزبان ثبت شد.',
  'receipt.record':'ثبت میزبان: دریافت مالی',
  'payment.record':'ثبت میزبان: پرداخت مالی',
  'receipt.allocate':'تخصیص دریافت در دفتر میزبان ثبت شد.',
  'payment.allocate':'تخصیص پرداخت در دفتر میزبان ثبت شد.',
  'funds.deposit':'واریز در دفتر میزبان ثبت شد.',
  'funds.transfer':'انتقال وجه در دفتر میزبان ثبت شد.',
  'party.register':'طرف‌حساب در دفتر میزبان ثبت شد.',
  'party.update':'اصلاح طرف‌حساب در دفتر میزبان ثبت شد.',
  'company.update':'تغییرات شرکت در دفتر میزبان ثبت شد.',
  'company.profile.update':'تغییرات مشخصات شرکت در دفتر میزبان ثبت شد.',
  'proforma.create':'پیش‌فاکتور در دفتر میزبان ذخیره شد؛ سند مالی نیست.',
  'proforma.update':'ویرایش پیش‌فاکتور در دفتر میزبان ذخیره شد.',
});
const GROUPS=Object.freeze({
  invoice:'فاکتور فروش',bill:'صورتحساب خرید',settlements:'دریافت و پرداخت',
  cash:'خزانه',company:'شرکت',reports:'گزارش‌ها',
  settings:'اتصال مدار و تراز',
});
const ACTIONS=Object.freeze({
  failed:'عملیات تأیید نشد. وضعیت و پیام داخل صفحه را بررسی کنید.',
  uncertain:'نتیجه عملیات نامشخص است؛ پیش از تکرار همان شناسه را بازیابی کنید.',
  conflict:'دادهٔ دفتر تغییر کرده است؛ فرم را بررسی و با میزبان همگام کنید.',
  invalid:'اطلاعات فرم معتبر نیست؛ موارد مشخص‌شده را اصلاح کنید.',
  requested:'درخواست دریافت فایل به مرورگر ارسال شد؛ ذخیره نهایی تأیید نشده است.',
  exportError:'تهیه خروجی انجام نشد. وضعیت داخل صفحه را بررسی کنید.',
  template:'تغییرات قالب در میزبان ذخیره شد؛ سند مالی ایجاد نشده است.',
  review:'وضعیت ارجاع در صندوق محلی ثبت شد؛ سند مالی ایجاد نشده است.',
  recover:'تصمیم پیشین در صندوق محلی بازیابی شد؛ سند مالی ایجاد نشده است.',
  reviewError:'تأیید وضعیت ارجاع ممکن نشد. صفحه اتصال را بررسی کنید.',
  draft:'شرح پیشنهاد وارد فرم شد؛ هیچ سند مالی ثبت نشده است.',
  draftError:'آماده‌سازی فرم پیشنهاد انجام نشد.',
  companyRequest:'درخواست تغییر شرکت ارسال شد؛ پایان تغییر هنوز تأیید نشده است.',
});

export function describeTarazFeedback({kind,commandType='',section=''}={}){
  if(kind==='commit')return {
    level:'success',
    title:COMMAND_LABELS[commandType]||'فرمان در دفتر میزبان ثبت شد.',
    description:RECEIPT_LIMIT,
  };
  if(kind==='review'||kind==='recover'||kind==='draft')return {
    level:'info',title:ACTIONS[kind],description:RECEIPT_LIMIT,
  };
  const allowed=Object.hasOwn(ACTIONS,kind)?kind:'failed';
  return {
    level:allowed==='uncertain'||allowed==='conflict'?'warning':
      allowed==='requested'||allowed==='template'||allowed==='companyRequest'?'info':'error',
    title:ACTIONS[allowed],
    description:GROUPS[section]||RECEIPT_LIMIT,
  };
}

// Only call this from an explicit operator action and *after* an actual host
// response is validated. Do not subscribe to state/error changes on render.
export function tarazToast(event){
  const entry=describeTarazFeedback(event);
  try{
    return sileo[entry.level]({
      title:entry.title,description:entry.description,duration:4300,
      position:'top-left',autopilot:false,
    });
  }catch{
    // A visual notification must NEVER convert a completed finance command
    // into a retryable accounting failure.
    return null;
  }
}

export function TarazSileoToaster(){
  const readTheme=()=>typeof document==='undefined'?'dark':
    document.documentElement?.dataset?.theme==='light'?'light':'dark';
  const [theme,setTheme]=React.useState(readTheme);
  React.useEffect(()=>{
    const root=document.documentElement;
    const refresh=()=>setTheme(readTheme());
    const observer=new MutationObserver(refresh);
    observer.observe(root,{attributes:true,attributeFilter:['data-theme']});
    window.addEventListener('storage',refresh);
    window.addEventListener('taraz-settings-change',refresh);
    return()=>{
      observer.disconnect();
      window.removeEventListener('storage',refresh);
      window.removeEventListener('taraz-settings-change',refresh);
    };
  },[]);
  return <div className="taraz-feedback-host" dir="rtl">
    <Toaster position="top-left" offset={{top:70,left:16}}
      theme={theme} options={{
        duration:4300,autopilot:false,
        fill:theme==='dark'?'#192333':'#ffffff',
      }}/>
  </div>;
}

// This view-scoped adapter deliberately doesn't change the backend auth model.
// Only an authenticated, successful *manual* metadata decision has a toast.
export function tarazIntegrationFeedbackApi(api,notify=tarazToast){
  if(!api||typeof api!=='object')return api;
  const pendingRecovery=new Map();
  return new Proxy(api,{
    get(target,name){
      if(name==='tarazIntegrationList'&&typeof target[name]==='function'){
        return async(...args)=>{
          const result=await target[name](...args);
          pendingRecovery.clear();
          for(const item of Array.isArray(result?.recovery)?result.recovery:[]){
            if(typeof item?.id==='string'&&
               ['reviewed','rejected'].includes(item?.state)&&
               item.financialEventCreated===false){
              pendingRecovery.set(item.id,item.state);
            }
          }
          return result;
        };
      }
      if(name==='tarazIntegrationReview'||name==='tarazIntegrationRecover'){
        const method=target[name];
        if(typeof method!=='function')return method;
        return async(...args)=>{
          try{
            const result=await method.apply(target,args);
            if(result?.id===args[0]&&result?.financialEventCreated===false&&
               ['reviewed','rejected'].includes(result?.state)&&
               (name==='tarazIntegrationReview'?result.state===args[1]:
                 pendingRecovery.get(args[0])===result.state)){
              notify({kind:name==='tarazIntegrationRecover'?'recover':'review',
                section:'settings'});
              if(name==='tarazIntegrationRecover')pendingRecovery.delete(args[0]);
            }
            return result;
          }catch(error){
            notify({kind:'reviewError',section:'settings'});
            throw error;
          }
        };
      }
      const result=Reflect.get(target,name,target);
      return typeof result==='function'?result.bind(target):result;
    },
  });
}
