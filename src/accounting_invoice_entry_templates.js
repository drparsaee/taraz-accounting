/** Portable, operator-selected invoice line templates.
 * Templates are not ledger events and are never posted automatically.
 * Keeping the JSON file user-owned avoids leaking one company into another.
 */
const ID=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const MAX=1000000000000000n;
export const ENTRY_TEMPLATE_FORMAT='madar-invoice-lines-v1';
const toAscii=value=>String(value).trim()
  .replace(/[۰-۹]/g,x=>String(x.charCodeAt(0)-1776))
  .replace(/[٠-٩]/g,x=>String(x.charCodeAt(0)-1632))
  .replace(/\u066c/g,',');
const number=(value,zero=false)=>{
  if(!(typeof value==='string'||typeof value==='number'))return null;
  const valueString=toAscii(value);
  if(valueString.length>32||!/^(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)$/.test(valueString))return null;
  const amount=BigInt(valueString.replace(/,/g,''));
  if(amount>MAX||(!zero&&amount===0n))return null;
  return Number(amount);
};
const id=v=>typeof v==='string'&&(!v||ID.test(v));
const description=v=>typeof v==='string'&&v.trim().length>0&&v.trim().length<=300&&
  !/[\x00-\x1f\x7f]/.test(v);
function validateLines(rows){
  if(!Array.isArray(rows)||!rows.length||rows.length>1000)
    throw new Error('قالب باید بین یک تا هزار ردیف داشته باشد.');
  const output=[];
  let subtotal=0n;
  for(const row of rows){
    if(!row||typeof row!=='object'||Array.isArray(row)||
       !description(row.description)||!id(row.accountId??'')||!id(row.itemId??''))
      throw new Error('شرح یا شناسه‌های یکی از ردیف‌های قالب معتبر نیست.');
    const qty=number(row.quantity);
    const price=number(row.unitPrice,true);
    if(qty===null||qty>1000000||price===null)
      throw new Error('قیمت یا تعداد یکی از ردیف‌های قالب نامعتبر است.');
    subtotal+=BigInt(qty)*BigInt(price);
    if(subtotal>MAX)throw new Error('جمع اقلام از سقف مجاز حسابداری بیشتر است.');
    output.push({description:row.description.trim(),quantity:String(qty),
      unitPrice:String(price),accountId:row.accountId||'',
      itemId:row.itemId||''});
  }
  return output;
}

export function buildAccountingInvoiceEntryTemplate(rows,{currency='RIAL',title='قالب فاکتور'}={}){
  if(!['RIAL','TOMAN'].includes(currency))throw Error('واحد پول قالب نامعتبر است.');
  if(typeof title!=='string'||title.length>100||!title.trim())
    throw Error('عنوان قالب نامعتبر است.');
  return {format:ENTRY_TEMPLATE_FORMAT,version:1,title:title.trim(),
    currency,lines:validateLines(rows)};
}
export function parseAccountingInvoiceEntryTemplate(serialized,{currency='RIAL'}={}){
  if(typeof serialized!=='string'||serialized.length>1048576)
    throw Error('فایل قالب باید JSON کوچک‌تر از یک مگابایت باشد.');
  let payload;
  try{payload=JSON.parse(serialized);}catch(_e){throw Error('فایل قالب JSON معتبر نیست.');}
  if(!payload||typeof payload!=='object'||Array.isArray(payload)||
     payload.format!==ENTRY_TEMPLATE_FORMAT||payload.version!==1||
     typeof payload.title!=='string'||!payload.title.trim()||payload.title.length>100||
     !['RIAL','TOMAN'].includes(currency)||payload.currency!==currency)
    throw Error('ساختار یا واحد پول قالب با دفتر حسابداری مطابقت ندارد.');
  return {...payload,lines:validateLines(payload.lines)};
}
