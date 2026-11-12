/** Offline explicit-text hints. Deterministic rules; never an LLM or an order submission. */
const digits=s=>String(s).replace(/[۰-۹]/g,d=>String(d.charCodeAt(0)-1776))
  .replace(/[٠-٩]/g,d=>String(d.charCodeAt(0)-1632));
const QUANTITY_MAX=10000000;
const quote=(s,max=180)=>String(s||'').trim().slice(0,max);
const quantity=s=>{
  const raw=String(s||'').trim().replace(/[٬,]/g,'');
  if(!/^(?:0|[1-9][0-9]{0,7})$/.test(raw))return '';
  const value=Number(raw);
  return Number.isSafeInteger(value)&&value<=QUANTITY_MAX?String(value):'';
};
const captured=(text,pattern,max=180)=>quote(text.match(pattern)?.[1],max);
const count=(text,pattern)=>quantity(text.match(pattern)?.[1]);
const labels={customerName:'نام مشتری',title:'شرح سفارش',
  quantity:'تعداد سفارش',productionQuantity:'تولید برنامه‌ای',
  actualProducedQuantity:'تولید واقعی',scrapQuantity:'ضایعات',
  healthySurplusQuantity:'مازاد سالم'};

export function extractLocalOrderHints(text){
  if(typeof text!=='string'||text.length>4000)return {
    error:'متن درخواست باید کوتاه‌تر از ۴۰۰۰ نویسه باشد.',
  };
  const normalized=digits(text).replace(/\u200c/g,' ');
  if(!normalized.trim())return {error:'متن درخواست مشتری را وارد کنید.'};
  const customerName=captured(normalized,
    /(?:^|\n)\s*(?:مشتری|طرف\s*حساب|تامین\s*کننده|تأمین\s*کننده)\s*[:：]\s*([^\r\n]+)/i,120);
  const title=captured(normalized,
    /(?:^|\n)\s*(?:شرح(?:\s+سفارش)?|موضوع|کار)\s*[:：]\s*([^\r\n]+)/i,200);
  const sale=count(normalized,
    /(?:تعداد\s*(?:سفارش|فروش)|مقدار\s*سفارش|تیراژ\s*سفارش)\s*[:：]?\s*([0-9٬,]{1,12})/i);
  // The free-form quantity is only a hint if it is not attached to production.
  const unitMatch=normalized.match(/(?:^|[^0-9])([0-9]{1,8})\s*(متر\s*مربع|کیلوگرم|عدد|برگ|نسخه|متر)(?=$|[\s،,؛؛.])/i);
  const productionContext=unitMatch&&/(?:^|\s|[,:])(?:تولید|پرت|مازاد|ضایعات)\s*[:：]?\s*$/.test(
    normalized.slice(0,unitMatch.index));
  const quantityValue=sale||(!productionContext?quantity(unitMatch?.[1]):'');
  const productionQuantity=count(normalized,
    /(?:تعداد\s*)?(?:تولید\s*(?:برنامه\s*ای|برنامه\s*ریزی\s*شده)|تیراژ\s*تولید|برنامه\s*تولید|تولید(?!\s*(?:واقعی|انجام\s*شده|شده)))\s*[:：]?\s*([0-9٬,]{1,12})/i)
    ||(quantityValue&&/بدون\s*پرت\s*برنامه\s*ریزی\s*شده/.test(normalized)?quantityValue:'');
  const actualProducedQuantity=count(normalized,
    /(?:تولید\s*(?:واقعی|انجام\s*شده|شده)|تعداد\s*تولید\s*شده)\s*[:：]?\s*([0-9٬,]{1,12})/i);
  const scrapQuantity=count(normalized,
    /(?:ضایعات|پرت\s*واقعی|باطله)\s*[:：]?\s*([0-9٬,]{1,12})/i);
  const healthySurplusQuantity=count(normalized,
    /(?:مازاد\s*سالم|اضافی\s*سالم)\s*[:：]?\s*([0-9٬,]{1,12})/i);
  const scheduleStartDate=captured(normalized,
    /(?:^|\n)\s*(?:شروع\s*تولید|تاریخ\s*شروع)\s*[:：]\s*(\d{4}-\d{2}-\d{2})/i,10);
  const scheduleDueDate=captured(normalized,
    /(?:^|\n)\s*(?:موعد\s*تحویل|تاریخ\s*تحویل|سررسید)\s*[:：]\s*(\d{4}-\d{2}-\d{2})/i,10);
  const fields={
    customerName,title,quantity:quantityValue,productionQuantity,
    actualProducedQuantity,scrapQuantity,healthySurplusQuantity,
    unit:quote(unitMatch?.[2],32),
    projectReference:captured(normalized,
      /(?:^|\n)\s*(?:ارجاع\s*پروژه|کد\s*پروژه|پروژه)\s*[:：]\s*([^\r\n]+)/i,120),
    scheduleStartDate,scheduleDueDate,
    procurementNotes:captured(normalized,
      /(?:^|\n)\s*(?:جزئیات\s*تامین|جزئیات\s*تأمین|تدارکات)\s*[:：]\s*([^\r\n]+)/i,2000),
  };
  const terms=[
    ['print',/چاپ|افست|دیجیتال/],
    ['bindery',/صحافی|دوخت|منگنه/],
    ['laser',/لیزر|برش لیزری/],
    ['packaging',/بسته\s*بندی/],
    ['shipping',/حمل|ارسال|پست/],
    ['material',/مواد\s*اولیه|مقوا|کاغذ/],
  ];
  const suggestedStages=terms.filter(([,pattern])=>pattern.test(normalized))
    .map(([kind])=>kind);
  const missing=['customerName','title','quantity','productionQuantity']
    .filter(key=>!fields[key]).map(key=>labels[key]);
  const warnings=[];
  if(quantityValue&&productionQuantity&&Number(productionQuantity)<Number(quantityValue))
    warnings.push('برنامه تولید از تعداد فروش کمتر است؛ مقدارها را بررسی کنید.');
  if(actualProducedQuantity&&scrapQuantity&&healthySurplusQuantity&&
    Number(scrapQuantity)+Number(healthySurplusQuantity)>Number(actualProducedQuantity))
    warnings.push('ضایعات و مازاد سالم از تعداد تولید واقعی بیشتر است.');
  const needsMeasurements=!!(actualProducedQuantity||scrapQuantity||healthySurplusQuantity);
  const suggestedActions=[
    ...missing.map(name=>`مقدار «${name}» را از مشتری بپرسید.`),
    ...(needsMeasurements?['برای تراز واقعی، هر سه مقدار تولیدشده، ضایعات و مازاد سالم را تأیید کنید.']:[]),
    'در صورت نامشخص بودن قیمت یا هزینه مرحله، مقدار را خالی بگذارید.',
  ];
  return {fields,suggestedStages,missing,warnings,suggestedActions,
    source:'LOCAL_RULES_ONLY',manualReviewRequired:true,
    externalModelCalled:false,financialEventCreated:false};
}
