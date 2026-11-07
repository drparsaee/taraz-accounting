import {parseAccountingJalali} from './accounting_jalali_dates.js';

// Only the published five-column, unquoted semicolon dialect is accepted.
// Preflight mirrors the host limits; the host remains the final authority.
const HEADER='statementId;accountId;date;amount;reference';
const IDENT=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const ISO=/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const MAX=1000000000000000n;
const SIGNED_AMOUNT=/^-?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$/;
const DIGITS=value=>String(value)
  .replace(/[۰-۹]/g,x=>String(x.charCodeAt(0)-1776))
  .replace(/[٠-٩]/g,x=>String(x.charCodeAt(0)-1632));

function validIsoDate(value,today){
  if(!ISO.test(value)||value>today)return false;
  const [y,m,d]=value.split('-').map(Number);
  if(y<1900)return false;
  const parsed=new Date(Date.UTC(y,m-1,d));
  return parsed.getUTCFullYear()===y&&parsed.getUTCMonth()===m-1&&
    parsed.getUTCDate()===d;
}

export function parseAccountingBankCSV(raw,{accounts={},existing={},today}={}){
  if(typeof raw!=='string'||new TextEncoder().encode(raw).length>1024*1024)
    throw Error('فایل CSV بیش از ۱ مگابایت است یا معتبر نیست.');
  if(!validIsoDate(today,today))throw Error('تاریخ مرجع ثبت معتبر نیست.');
  const lines=raw.replace(/^\ufeff/,'').split(/\r?\n/).filter(x=>x.trim());
  if(lines.shift()?.trim()!==HEADER)
    throw Error('عنوان ستون‌های CSV باید دقیقاً مطابق قالب اعلام‌شده باشد.');
  if(!lines.length||lines.length>500)
    throw Error('تعداد ردیف باید بین ۱ و ۵۰۰ باشد.');
  const ids=new Set(Object.keys(existing).map(x=>x.toLowerCase()));
  const refs=new Set(Object.values(existing).map(row=>
    String(row.accountId)+'\0'+String(row.reference)));
  return lines.map((line,i)=>{
    const parts=line.split(';');
    if(parts.length!==5||parts.some(p=>p.includes('"')||/[\x00-\x1f\x7f]/.test(p)))
      throw Error('قالب ردیف '+(i+2)+' معتبر نیست.');
    const [statementId,accountId,rawDate,rawAmount,reference]=parts.map(x=>x.trim());
    const date=parseAccountingJalali(rawDate)||(ISO.test(rawDate)?rawDate:null);
    if(!IDENT.test(statementId)||!IDENT.test(accountId)||
      !accounts[accountId]?.liquid||accounts[accountId]?.kind!=='asset'||
      !date||!validIsoDate(date,today))
      throw Error('شناسه، حساب بانکی یا تاریخ ردیف '+(i+2)+' معتبر نیست.');
    if(!reference||reference.length>100)
      throw Error('شناسه مرجع بانک در ردیف '+(i+2)+' معتبر نیست.');
    let amount;
    try{amount=parseAccountingBankAmount(rawAmount);}
    catch(_err){throw Error('مبلغ ردیف '+(i+2)+' باید عدد صحیح علامت‌دار باشد.');}
    const idKey=statementId.toLowerCase(),refKey=accountId+'\0'+reference;
    if(ids.has(idKey)||refs.has(refKey))
      throw Error('شناسه یا مرجع بانکی تکراری در ردیف '+(i+2)+' وجود دارد.');
    ids.add(idKey);refs.add(refKey);
    return {statementId,accountId,date,amount,reference};
  });
}

export function parseAccountingBankAmount(value){
  const normalized=DIGITS(value).replace(/٬/g,',').trim();
  if(normalized.length>40||!SIGNED_AMOUNT.test(normalized))
    throw Error('مبلغ بانک باید عدد صحیح با جداکننده هزارگان معتبر باشد.');
  const exact=BigInt(normalized.replace(/,/g,''));
  if(exact===0n||exact>MAX||exact< -MAX)
    throw Error('مبلغ بانک باید غیرصفر و در محدوده دقیق دفتر باشد.');
  return Number(exact);
}

export const accountingBankNetExact=rows=>rows.reduce((s,row)=>s+BigInt(row.amount),0n);
