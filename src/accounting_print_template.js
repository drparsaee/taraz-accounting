/** Offline print layout data and renderer. Never executes template content. */
import {jpegPagesToPdf,safeInvoiceFilename} from './standalone_invoice_export.js';
import {formatAccountingJalali} from './accounting_jalali_dates.js';

const FORMAT='madar-print-layout-v1';
export const PRINT_FIELDS=[
  ['title','عنوان سند'],['seller','نام صادرکننده'],['buyer','طرف حساب'],
  ['number','شماره سند'],['date','تاریخ سند'],['note','توضیحات']
];
export const DEFAULT_PRINT_TEMPLATE={
  format:FORMAT,version:1,title:'قالب اختصاصی مدار',page:'A4',orientation:'portrait',
  margin:10,font:'Vazirmatn',color:'#203239',logo:'',
  fields:[
    {id:'title',label:'فاکتور فروش',visible:true,x:200,y:21,size:17},
    {id:'seller',label:'صادرکننده',visible:true,x:200,y:35,size:11},
    {id:'buyer',label:'خریدار',visible:true,x:200,y:49,size:10},
    {id:'number',label:'شماره',visible:true,x:200,y:62,size:10},
    {id:'date',label:'تاریخ',visible:true,x:100,y:62,size:10},
    {id:'note',label:'توضیحات',visible:true,x:200,y:83,size:9}
  ],
  table:{y:96,showQuantity:true,showPrice:true,showTotal:true},
  totalsY:273,signature:'مهر و امضا'
};
const PAGE={A4:[210,297],A5:[148,210]};
const cleanText=(value,max=250)=>String(value??'').replace(/[\x00-\x1f\x7f]/g,' ').slice(0,max);
const bounded=(n,min,max)=>typeof n==='number'&&Number.isFinite(n)&&n>=min&&n<=max;

export function validatePrintTemplate(template){
  if(!template||typeof template!=='object'||Array.isArray(template)||
    template.format!==FORMAT||template.version!==1||
    typeof template.title!=='string'||!template.title.trim()||template.title.length>100||
    !PAGE[template.page]||!['portrait','landscape'].includes(template.orientation)||
    !bounded(template.margin,3,30)||!['Vazirmatn','Tahoma','Arial'].includes(template.font)||
    typeof template.color!=='string'||!/^#[0-9a-fA-F]{6}$/.test(template.color)||
    typeof template.signature!=='string'||template.signature.length>100||
    typeof template.logo!=='string'||template.logo.length>300000||
    (template.logo&&!/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(template.logo)))
    throw Error('ساختار قالب چاپ معتبر نیست.');
  if(!Array.isArray(template.fields)||template.fields.length!==PRINT_FIELDS.length||
     new Set(template.fields.map(x=>x.id)).size!==PRINT_FIELDS.length)
    throw Error('فیلدهای قالب باید مشخص و بدون تکرار باشند.');
  for(const f of template.fields){
    if(!PRINT_FIELDS.some(x=>x[0]===f.id)||typeof f.visible!=='boolean'||
       typeof f.label!=='string'||f.label.length>60||
       !bounded(f.x,0,297)||!bounded(f.y,0,297)||!bounded(f.size,7,22))
      throw Error('یکی از فیلدهای قالب چاپ معتبر نیست.');
  }
  const t=template.table;
  if(!t||!bounded(t.y,30,250)||
    ['showQuantity','showPrice','showTotal'].some(key=>typeof t[key]!=='boolean')||
    !bounded(template.totalsY,75,290))throw Error('موقعیت جدول یا جمع سند معتبر نیست.');
  return JSON.parse(JSON.stringify(template));
}

export function templatePageSize(template){
  const [w,h]=PAGE[template.page];
  return template.orientation==='landscape'?[h,w]:[w,h];
}

const fmt=value=>Number.isSafeInteger(value)?value.toLocaleString('fa-IR'):'—';
const dataFor=(kind,doc,party,company)=>({
  title:kind==='proforma'?'پیش‌فاکتور':kind==='bill'?'صورتحساب خرید':'فاکتور فروش',
  seller:company?.legalName||'صادرکننده',buyer:party||'طرف حساب',
  number:doc?.number||doc?.id||'پیش‌نمایش',
  date:doc?.documentDate?formatAccountingJalali(doc.documentDate):'—',
  note:doc?.note||''
});

function makeCanvas(template,kind,doc,party,company,currency,pageIndex,pageCount,logoImage,scale){
  const [w,h]=templatePageSize(template),canvas=document.createElement('canvas');
  canvas.width=Math.round(w*scale);canvas.height=Math.round(h*scale);
  const c=canvas.getContext('2d');
  if(!c)throw Error('Canvas unavailable');
  const X=n=>n*scale, write=(text,x,y,pt=10,bold=false,max=w-2*template.margin)=>{
    c.fillStyle=template.color;c.textAlign='right';c.direction='rtl';
    c.font=`${bold?'bold ':''}${pt*scale*.37}px ${template.font}, Tahoma, sans-serif`;
    c.fillText(cleanText(text),X(x),X(y),X(max));
  };
  c.fillStyle='#fff';c.fillRect(0,0,canvas.width,canvas.height);
  c.strokeStyle='#d0dade';c.lineWidth=Math.max(1,scale*.2);
  c.strokeRect(X(template.margin),X(template.margin),X(w-2*template.margin),X(h-2*template.margin));
  if(logoImage){
    const maxWidth=Math.min(36,w*.25),maxHeight=23;
    c.drawImage(logoImage,X(template.margin+2),X(template.margin+2),X(maxWidth),X(maxHeight));
  }
  const values=dataFor(kind,doc,party,company);
  if(pageIndex===0){
    template.fields.forEach(f=>{if(f.visible){
      const label=f.id==='title'?values.title:cleanText(f.label)+' : '+values[f.id];
      write(label,Math.min(w-template.margin,f.x),f.y,f.size,f.id==='title');
    }});
  }else write(values.title+' | '+values.number,w-template.margin,template.margin+10,11,true);
  const unit=currency==='TOMAN'?'تومان':'ریال';
  // Use one stable pagination grid on EVERY page: changing it mid-document
  // silently skips or duplicates lines after the first page.
  const tableStart=template.table.y;
  const xRight=w-template.margin-4,xLeft=template.margin+4;
  c.fillStyle='#e9f3f4';c.fillRect(X(template.margin+1),X(tableStart),X(w-template.margin*2-2),X(11));
  const columns=[{key:'description',label:'شرح',x:xRight}];
  if(template.table.showQuantity)columns.push({key:'quantity',label:'تعداد',x:xLeft+(w-2*template.margin)*.45});
  if(template.table.showPrice)columns.push({key:'unitPrice',label:'فی ('+unit+')',x:xLeft+(w-2*template.margin)*.27});
  if(template.table.showTotal)columns.push({key:'total',label:'مبلغ ('+unit+')',x:xLeft+(w-2*template.margin)*.04});
  columns.forEach(col=>write(col.label,col.x,tableStart+7.5,8,true));
  const rowHeight=8.5;
  const maxRows=Math.max(1,Math.floor((h-template.margin-47-(tableStart+14))/rowHeight));
  const allLines=Array.isArray(doc?.lines)?doc.lines:[];
  const start=pageIndex*maxRows;
  const pageLines=allLines.slice(start,start+maxRows);
  pageLines.forEach((row,i)=>{
    const y=tableStart+17+i*rowHeight;
    if(i%2===1){c.fillStyle='#f6faf9';c.fillRect(X(template.margin+1),X(y-6.4),X(w-template.margin*2-2),X(rowHeight));}
    columns.forEach(col=>write(col.key==='description'?row.description:fmt(row[col.key]),col.x,y,8,false,
      col.key==='description'?Math.max(24,(w-2*template.margin)*.48):
      Math.max(18,(w-2*template.margin)*.19)));
  });
  if(pageIndex===pageCount-1){
    const y=Math.min(h-template.margin-16,Math.max(tableStart+30+pageLines.length*rowHeight,template.totalsY*(h/297)));
    write('جمع اقلام: '+fmt(doc?.subtotal)+' '+unit,w-template.margin,y-19,9);
    write('تخفیف: '+fmt(doc?.discount)+'  |  مالیات: '+fmt(doc?.tax),w-template.margin,y-10,9);
    write('مبلغ نهایی: '+fmt(doc?.total)+' '+unit,w-template.margin,y,12,true);
    write(template.signature,w-template.margin,y+10,9);
  }
  write('صفحه '+(pageIndex+1)+' از '+pageCount,template.margin+36,h-template.margin-3,8);
  if(doc?.status&&doc.status!=='issued'&&doc.status!=='accepted')
    write('وضعیت: '+cleanText(doc.status),w-template.margin,h-template.margin-3,8);
  return {canvas,maxRows};
}

async function loadLogo(src){
  if(!src)return null;
  return await new Promise((resolve,reject)=>{
    const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(Error('تصویر لوگو خوانده نشد'));
    img.src=src;
  });
}

export async function renderPrintTemplatePages(template,context,{scale=4,preview=false}={}){
  const safe=validatePrintTemplate(template),logo=await loadLogo(safe.logo);
  const doc=context.doc||{id:'PREVIEW',documentDate:'2026-01-01',status:'draft',
    lines:[{description:'نمونه کالا یا خدمات',quantity:2,unitPrice:500000,total:1000000}],
    subtotal:1000000,discount:0,tax:0,total:1000000};
  const args=[safe,context.kind||'invoice',doc,context.party||'طرف‌حساب نمونه',
    context.company||{},context.currency||'RIAL'];
  const [,h]=templatePageSize(safe);
  const rowsPerPage=Math.max(1,Math.floor((h-safe.margin-47-(safe.table.y+14))/8.5));
  const count=Math.ceil((doc.lines?.length||1)/rowsPerPage)||1;
  if(count>100)throw Error('فاکتور بیشتر از ۱۰۰ صفحه است.');
  return Array.from({length:preview?1:count},(_,i)=>makeCanvas(...args,i,count,logo,scale).canvas);
}

const jpegBytes=canvas=>{
  const bin=atob(canvas.toDataURL('image/jpeg',.94).split(',')[1]);
  return Uint8Array.from(bin,ch=>ch.charCodeAt(0));
};
export async function buildCustomPrintExport({template,kind,doc,party,company,currency,format,pattern}){
  if(!['pdf','png'].includes(format))throw Error('فرمت خروجی پشتیبانی نمی‌شود.');
  if(!doc||typeof doc.id!=='string')throw Error('فاکتور انتخاب نشده است.');
  const pages=await renderPrintTemplatePages(template,{kind,doc,party,company,currency},{scale:5});
  if(format==='png'&&pages.length>1)throw Error('فاکتور چندصفحه‌ای است؛ برای حفظ تمام ردیف‌ها PDF بگیرید.');
  const name=safeInvoiceFilename(pattern||'madar-{kind}-{id}-{date}',{
    kind,id:doc.id,date:doc.documentDate||'draft',number:doc.number||''});
  const [w,h]=templatePageSize(template),filename=name+'.'+format;
  if(format==='png')return {filename,blob:await new Promise(resolve=>pages[0].toBlob(resolve,'image/png'))};
  const output=pages.map(canvas=>({width:canvas.width,height:canvas.height,jpeg:jpegBytes(canvas),
    pointsWidth:Number((w*72/25.4).toFixed(2)),pointsHeight:Number((h*72/25.4).toFixed(2))}));
  return {filename,blob:jpegPagesToPdf(output)};
}
