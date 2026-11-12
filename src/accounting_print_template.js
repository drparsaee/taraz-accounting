/** Offline print layout data and renderer. Never executes template content. */
import {jpegPagesToPdf,safeInvoiceFilename} from './standalone_invoice_export.js';
import {formatAccountingJalali} from './accounting_jalali_dates.js';

const FORMAT='madar-print-layout-v1';
export const PRINT_FIELDS=[
  ['title','عنوان سند'],['seller','نام صادرکننده'],['buyer','طرف حساب'],
  ['number','شماره سند'],['date','تاریخ سند'],['note','توضیحات']
];
// Available line data is intentionally limited to values on native invoice rows.
// Row number is computed from pagination; no inventory or financial lookup occurs.
export const PRINT_COLUMNS=[
  ['rowNumber','ردیف'],['description','شرح کالا یا خدمات'],
  ['itemId','شناسه کالا یا خدمت'],['accountId','شناسه حساب'],
  ['quantity','تعداد'],['unit','واحد'],['price','قیمت واحد'],['total','مبلغ ردیف']
];
// User-defined column labels may bind ONLY to these existing invoice-row
// values. No arbitrary formulas, JS expressions or private host lookups.
export const PRINT_CUSTOM_SOURCES=[
  ['description','شرح ثبت‌شده'],['itemId','شناسه کالا یا خدمت'],
  ['accountId','شناسه حساب'],['quantity','تعداد'],['unit','واحد واقعی کالا'],
  ['price','قیمت واحد'],['total','مبلغ ردیف']
];
const COLUMN_IDS=PRINT_COLUMNS.map(([id])=>id);
const CUSTOM_SOURCES=PRINT_CUSTOM_SOURCES.map(([id])=>id);
const CUSTOM_COLUMN_ID=/^custom_[1-4]$/;
export const PRINT_LAYOUT_PRESETS=[
  {id:'classic',label:'کلاسیک',description:'سربرگ رسمی و جدول کامل'},
  {id:'modern',label:'مدرن',description:'عنوان برجسته و فضای سفید بیشتر'},
  {id:'compact',label:'جمع‌وجور A5',description:'مناسب فاکتورهای کوتاه'}
];
export const DEFAULT_PRINT_TEMPLATE={
  format:FORMAT,version:1,title:'قالب اختصاصی مدار',page:'A4',orientation:'portrait',
  margin:10,font:'Vazirmatn',color:'#203239',logo:'',
  logoLayout:{x:12,y:12,width:36,height:23},
  companyHeader:'',companySubtitle:'',footerText:'',
  fields:[
    {id:'title',label:'فاکتور فروش',visible:true,x:200,y:21,size:17},
    {id:'seller',label:'صادرکننده',visible:true,x:200,y:35,size:11},
    {id:'buyer',label:'خریدار',visible:true,x:200,y:49,size:10},
    {id:'number',label:'شماره',visible:true,x:200,y:62,size:10},
    {id:'date',label:'تاریخ',visible:true,x:100,y:62,size:10},
    {id:'note',label:'توضیحات',visible:true,x:200,y:83,size:9}
  ],
  table:{y:96,showQuantity:true,showPrice:true,showTotal:true,rowHeight:8.5,
    labels:{rowNumber:'ردیف',description:'شرح',itemId:'شناسه کالا',accountId:'شناسه حساب',
      quantity:'تعداد',unit:'واحد',price:'فی',total:'مبلغ'}},
  totalsY:273,signature:'مهر و امضا'
};
const PAGE={A4:[210,297],A5:[148,210]};
const cleanText=(value,max=250)=>String(value??'').replace(/[\x00-\x1f\x7f]/g,' ').slice(0,max);
const bounded=(n,min,max)=>typeof n==='number'&&Number.isFinite(n)&&n>=min&&n<=max;
export function invoiceLineUnit(row,items={}){
  if(!row?.itemId)return 'عدد';
  const item=items?.[row.itemId];
  return typeof item?.unit==='string'&&item.unit.trim()?
    cleanText(item.unit.trim(),32):'—';
}
export function printColumns(table){
  if(Array.isArray(table?.columns))return [...table.columns];
  return ['description',...(table?.showQuantity?['quantity']:[]),
    ...(table?.showPrice?['price']:[]),...(table?.showTotal?['total']:[])];
}
export function applyPrintLayoutPreset(template,presetId){
  if(!PRINT_LAYOUT_PRESETS.some(x=>x.id===presetId))throw Error('چیدمان انتخابی وجود ندارد.');
  const current=validatePrintTemplate(template),base=DEFAULT_PRINT_TEMPLATE;
  const config={
    classic:{page:'A4',orientation:'portrait',margin:10,tableY:96,totalsY:273,
      positions:[[200,21],[200,35],[200,49],[200,62],[100,62],[200,83]],
      logoLayout:{x:12,y:12,width:36,height:23}},
    modern:{page:'A4',orientation:'portrait',margin:12,tableY:108,totalsY:271,
      positions:[[197,29],[197,46],[197,59],[197,72],[100,72],[197,94]],
      logoLayout:{x:13,y:19,width:38,height:24}},
    compact:{page:'A5',orientation:'portrait',margin:7,tableY:73,totalsY:260,
      positions:[[138,16],[138,27],[138,38],[138,49],[70,49],[138,64]],
      logoLayout:{x:8,y:8,width:26,height:17}}
  }[presetId];
  return validatePrintTemplate({...current,page:config.page,orientation:config.orientation,
    margin:config.margin,totalsY:config.totalsY,logoLayout:config.logoLayout,
    fields:base.fields.map((f,i)=>({...current.fields.find(x=>x.id===f.id),
      x:config.positions[i][0],y:config.positions[i][1]})),
    table:{...current.table,y:config.tableY}});
}

export function validatePrintTemplate(template){
  if(!template||typeof template!=='object'||Array.isArray(template)||
    template.format!==FORMAT||template.version!==1||
    typeof template.title!=='string'||!template.title.trim()||template.title.length>100||
    !PAGE[template.page]||!['portrait','landscape'].includes(template.orientation)||
    !bounded(template.margin,3,30)||!['Vazirmatn','Tahoma','Arial'].includes(template.font)||
    typeof template.color!=='string'||!/^#[0-9a-fA-F]{6}$/.test(template.color)||
    typeof template.signature!=='string'||template.signature.length>100||
    ['companyHeader','companySubtitle','footerText'].some(key=>
      template[key]!==undefined&&(typeof template[key]!=='string'||
      template[key].length>(key==='footerText'?70:120)))||
    typeof template.logo!=='string'||template.logo.length>300000||
    (template.logo&&!/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(template.logo)))
    throw Error('ساختار قالب چاپ معتبر نیست.');
  const [pageWidth,pageHeight]=templatePageSize(template);
  const logo=template.logoLayout??DEFAULT_PRINT_TEMPLATE.logoLayout;
  if(!logo||!bounded(logo.x,0,pageWidth)||!bounded(logo.y,0,pageHeight)||
     !bounded(logo.width,8,100)||!bounded(logo.height,6,75)||
     logo.x+logo.width>pageWidth||logo.y+logo.height>pageHeight)
    throw Error('موقعیت یا اندازه لوگو خارج از صفحه است.');
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
  const columns=printColumns(t);
  const custom=t?.customColumns??[];
  if(!Array.isArray(custom)||custom.length>4||
    custom.some(col=>!col||typeof col!=='object'||Array.isArray(col)||
      Object.keys(col).sort().join(',')!=='id,label,source'||
      typeof col.id!=='string'||!CUSTOM_COLUMN_ID.test(col.id)||
      typeof col.label!=='string'||!col.label.trim()||col.label.length>25||
      !CUSTOM_SOURCES.includes(col.source))||
    new Set(custom.map(col=>col.id)).size!==custom.length)
    throw Error('ستون سفارشی نامعتبر است.');
  const allowedColumns=[...COLUMN_IDS,...custom.map(col=>col.id)];
  if(!t||!bounded(t.y,30,250)||
    ['showQuantity','showPrice','showTotal'].some(key=>typeof t[key]!=='boolean')||
    (t.columns!==undefined&&(!Array.isArray(t.columns)||
      t.columns.length<1||t.columns.length>allowedColumns.length||
      new Set(t.columns).size!==t.columns.length||
      t.columns.some(id=>!allowedColumns.includes(id))))||
    !columns.includes('description')||
    (t.rowHeight!==undefined&&!bounded(t.rowHeight,6,14))||
    (t.labels!==undefined&&(!t.labels||typeof t.labels!=='object'||
      Object.entries(t.labels).some(([key,value])=>!COLUMN_IDS.includes(key)||
        typeof value!=='string'||!value.trim()||value.length>25)||
      ['description','quantity','price','total'].some(key=>
        typeof t.labels[key]!=='string'||!t.labels[key].trim())))||
    !bounded(template.totalsY,75,290))throw Error('موقعیت جدول یا جمع سند معتبر نیست.');
  // The page always needs space for at least one actual line. Math.max(1) in
  // the renderer must not make an entirely off-paper table appear valid.
  if(t.y>maxPrintTableStart(template))
    throw Error('محل شروع جدول برای اندازه کاغذ انتخابی خارج از فضای چاپ است.');
  return JSON.parse(JSON.stringify({...template,
    companyHeader:template.companyHeader??'',companySubtitle:template.companySubtitle??'',
    footerText:template.footerText??'',logoLayout:{...logo},
    table:{...t,rowHeight:t.rowHeight??8.5,columns,
      labels:{...DEFAULT_PRINT_TEMPLATE.table.labels,...(t.labels||{})}}}));
}

export function templatePageSize(template){
  const [w,h]=PAGE[template.page];
  return template.orientation==='landscape'?[h,w]:[w,h];
}

export function maxPrintTableStart(template){
  const [,height]=templatePageSize(template);
  const rowHeight=template.table?.rowHeight??8.5;
  return Math.min(250,Math.floor(height-template.margin-61-rowHeight));
}

const fmt=value=>Number.isSafeInteger(value)?value.toLocaleString('fa-IR'):'—';
const dataFor=(kind,doc,party,company)=>({
  title:kind==='proforma'?'پیش‌فاکتور':kind==='bill'?'صورتحساب خرید':'فاکتور فروش',
  seller:company?.legalName||'صادرکننده',buyer:party||'طرف حساب',
  number:doc?.number||doc?.id||'پیش‌نمایش',
  date:doc?.documentDate?formatAccountingJalali(doc.documentDate):'—',
  note:doc?.note||''
});

function makeCanvas(template,kind,doc,party,company,currency,items,pageIndex,pageCount,logoImage,scale){
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
    const frame=template.logoLayout;
    const aspect=logoImage.naturalWidth/logoImage.naturalHeight;
    const width=Number.isFinite(aspect)&&aspect>0?
      Math.min(frame.width,frame.height*aspect):frame.width;
    const height=Number.isFinite(aspect)&&aspect>0?
      Math.min(frame.height,frame.width/aspect):frame.height;
    c.drawImage(logoImage,X(frame.x+(frame.width-width)/2),
      X(frame.y+(frame.height-height)/2),X(width),X(height));
  }
  const values=dataFor(kind,doc,party,company);
  values.seller=template.companyHeader.trim()||values.seller;
  if(pageIndex===0){
    template.fields.forEach(f=>{if(f.visible){
      const label=f.id==='title'?cleanText(f.label):cleanText(f.label)+' : '+values[f.id];
      write(label,Math.min(w-template.margin,f.x),f.y,f.size,f.id==='title');
    }});
    if(template.companySubtitle.trim()){
      const seller=template.fields.find(f=>f.id==='seller');
      if(seller?.visible)write(template.companySubtitle,Math.min(w-template.margin,seller.x),
        seller.y+6,8,false,w-2*template.margin);
    }
  }else write(values.title+' | '+values.number,w-template.margin,template.margin+10,11,true);
  const unit=currency==='TOMAN'?'تومان':'ریال';
  // Use one stable pagination grid on EVERY page: changing it mid-document
  // silently skips or duplicates lines after the first page.
  const tableStart=template.table.y;
  const xRight=w-template.margin-4;
  c.fillStyle='#e9f3f4';c.fillRect(X(template.margin+1),X(tableStart),X(w-template.margin*2-2),X(11));
  const headings=template.table.labels;
  const selected=printColumns(template.table);
  const widths=selected.map(key=>key==='description'?3.2:
    key==='price'||key==='total'?1.65:key==='itemId'||key==='accountId'?1.25:1);
  const unitWidth=(w-2*template.margin-8)/widths.reduce((a,b)=>a+b,0);
  let cursor=xRight;
  const columns=selected.map((key,i)=>{
    const width=widths[i]*unitWidth;
    const custom=template.table.customColumns?.find(def=>def.id===key);
    const col={key,source:custom?.source||null,x:cursor,
      label:(custom?.label||headings[key])+(['price','total'].includes(key)?' ('+unit+')':''),
      width:Math.max(8,width-2)};
    cursor-=width;
    return col;
  });
  columns.forEach(col=>write(col.label,col.x,tableStart+7.5,8,true,col.width));
  const rowHeight=template.table.rowHeight;
  const maxRows=Math.max(1,Math.floor((h-template.margin-47-(tableStart+14))/rowHeight));
  const allLines=Array.isArray(doc?.lines)?doc.lines:[];
  const start=pageIndex*maxRows;
  const pageLines=allLines.slice(start,start+maxRows);
  pageLines.forEach((row,i)=>{
    const y=tableStart+17+i*rowHeight;
    if(i%2===1){c.fillStyle='#f6faf9';c.fillRect(X(template.margin+1),X(y-6.4),X(w-template.margin*2-2),X(rowHeight));}
    columns.forEach(col=>{
      const source=col.source||col.key;
      const displayed=source==='rowNumber'?(start+i+1).toLocaleString('fa-IR'):
        source==='description'?cleanText(row.description):
        source==='unit'?invoiceLineUnit(row,items):
        source==='price'?fmt(row.unitPrice):
        source==='itemId'||source==='accountId'?cleanText(row[source]||'—',80):
        fmt(row[source]);
      write(displayed,col.x,y,8,false,col.width);
    });
  });
  if(pageIndex===pageCount-1){
    const y=Math.min(h-template.margin-16,Math.max(tableStart+30+pageLines.length*rowHeight,template.totalsY*(h/297)));
    write('جمع اقلام: '+fmt(doc?.subtotal)+' '+unit,w-template.margin,y-19,9);
    write('تخفیف: '+fmt(doc?.discount)+'  |  مالیات: '+fmt(doc?.tax),w-template.margin,y-10,9);
    write('مبلغ نهایی: '+fmt(doc?.total)+' '+unit,w-template.margin,y,12,true);
    write(template.signature,w-template.margin,y+10,9);
  }
  write('صفحه '+(pageIndex+1)+' از '+pageCount,template.margin+36,h-template.margin-3,8);
  if(pageIndex===pageCount-1&&template.footerText.trim()){
    c.fillStyle=template.color;c.textAlign='center';c.direction='rtl';
    c.font=`${8*scale*.37}px ${template.font}, Tahoma, sans-serif`;
    c.fillText(cleanText(template.footerText),X(w/2),X(h-template.margin-3),X(w*.42));
  }
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
    context.company||{},context.currency||'RIAL',context.items||{}];
  const [,h]=templatePageSize(safe);
  const rowsPerPage=Math.max(1,Math.floor((h-safe.margin-47-(safe.table.y+14))/safe.table.rowHeight));
  const count=Math.ceil((doc.lines?.length||1)/rowsPerPage)||1;
  if(count>100)throw Error('فاکتور بیشتر از ۱۰۰ صفحه است.');
  return Array.from({length:preview?1:count},(_,i)=>makeCanvas(...args,i,count,logo,scale).canvas);
}

const jpegBytes=canvas=>{
  const bin=atob(canvas.toDataURL('image/jpeg',.94).split(',')[1]);
  return Uint8Array.from(bin,ch=>ch.charCodeAt(0));
};
export async function buildCustomPrintExport({template,kind,doc,party,company,currency,items,format,pattern}){
  if(!['pdf','png'].includes(format))throw Error('فرمت خروجی پشتیبانی نمی‌شود.');
  if(!doc||typeof doc.id!=='string')throw Error('فاکتور انتخاب نشده است.');
  const pages=await renderPrintTemplatePages(template,{kind,doc,party,company,currency,items},{scale:5});
  if(format==='png'&&pages.length>1)throw Error('فاکتور چندصفحه‌ای است؛ برای حفظ تمام ردیف‌ها PDF بگیرید.');
  const name=safeInvoiceFilename(pattern||'madar-{kind}-{id}-{date}',{
    kind,id:doc.id,date:doc.documentDate||'draft',number:doc.number||''});
  const [w,h]=templatePageSize(template),filename=name+'.'+format;
  if(format==='png')return {filename,blob:await new Promise(resolve=>pages[0].toBlob(resolve,'image/png'))};
  const output=pages.map(canvas=>({width:canvas.width,height:canvas.height,jpeg:jpegBytes(canvas),
    pointsWidth:Number((w*72/25.4).toFixed(2)),pointsHeight:Number((h*72/25.4).toFixed(2))}));
  return {filename,blob:jpegPagesToPdf(output)};
}
