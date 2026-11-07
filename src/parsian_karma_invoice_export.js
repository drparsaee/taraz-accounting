/** Parsian / Karma FastReport geometry-derived A4 invoice renderer.
 *
 * Non-sensitive physical positions and static labels were extracted from
 * "000- Karma Sale Factor.fr3"; this is NOT an execution engine for .fr3
 * PascalScript/datasets. All monetary data come from the verified R5 book,
 * never the old Parsian database. No bank/personal numbers are bundled.
 */
import layout from './parsian_karma_layout.json';
import logoUrl from './assets/parsian_karma_template_logo.jpg';
import {formatAccountingJalali} from './accounting_jalali_dates.js';
import {jpegPagesToPdf,safeInvoiceFilename} from './standalone_invoice_export.js';

const PAPER_W=1240;
const PAPER_H=1754;
const UNIT=(PAPER_W/(layout.paperMm[0]*96/25.4));
const MARGIN=layout.marginMm[0]*96/25.4*UNIT;
const CONTENT_W=layout.bandWidth*UNIT;
const MIN_PAGE_FOOTER=40*UNIT;
const hexRgb=(n)=>'#'+[n&255,(n>>>8)&255,(n>>>16)&255].map(v=>v.toString(16).padStart(2,'0')).join('');
const money=n=>Number(n||0).toLocaleString('fa-IR');
const isInteger=n=>Number.isSafeInteger(n)&&n>=0;
const digits=n=>String(n).replace(/\d/g,c=>'۰۱۲۳۴۵۶۷۸۹'[Number(c)]);
const words0=['','یک','دو','سه','چهار','پنج','شش','هفت','هشت','نه','ده','یازده','دوازده','سیزده','چهارده','پانزده','شانزده','هفده','هجده','نوزده'];
const tens=['','','بیست','سی','چهل','پنجاه','شصت','هفتاد','هشتاد','نود'];
const hundreds=['','صد','دویست','سیصد','چهارصد','پانصد','ششصد','هفتصد','هشتصد','نهصد'];
function underThousand(n){
  const bits=[];
  if(n>=100){bits.push(hundreds[Math.floor(n/100)]);n%=100;}
  if(n>=20){bits.push(tens[Math.floor(n/10)]);n%=10;}
  if(n>0)bits.push(words0[n]);
  return bits.join(' و ');
}
export function rialInPersianWords(value){
  if(!isInteger(value))throw Error('مبلغ به حروف نامعتبر است.');
  if(value===0)return 'صفر';
  const scale=['','هزار','میلیون','میلیارد','تریلیون'];
  let i=0,n=value;
  const parts=[];
  while(n>0){
    const group=n%1000;
    if(group)parts.unshift([underThousand(group),scale[i]].filter(Boolean).join(' '));
    n=Math.floor(n/1000);i++;
  }
  return parts.join(' و ');
}

function fileCanvas(){
  const canvas=document.createElement('canvas');
  canvas.width=PAPER_W;canvas.height=PAPER_H;
  const ctx=canvas.getContext('2d');
  if(!ctx)throw Error('امکان رسم فاکتور پارسیان وجود ندارد.');
  ctx.fillStyle='#fff';ctx.fillRect(0,0,PAPER_W,PAPER_H);
  return {canvas,ctx};
}
function drawShape(ctx,o,y){
  const x=MARGIN+o.x*UNIT, top=y+o.y*UNIT, w=o.w*UNIT,h=o.h*UNIT;
  if(o.type==='rect'){
    ctx.beginPath();
    if(o.round&&ctx.roundRect)ctx.roundRect(x,top,w,h,6);
    else ctx.rect(x,top,w,h);
    // Two branded vertical name tabs in the original template.
    const colored=o.name==='Shape10'||o.name==='Shape12';
    const heading=o.name==='Shape2';
    ctx.fillStyle=colored?'#243f82':heading?'#ececec':'#fff';
    ctx.fill();
    ctx.lineWidth=Math.max(.7,o.strokeWidth*UNIT*.50);
    ctx.strokeStyle='#484d55';ctx.stroke();
  }else if(o.type==='line'){
    ctx.strokeStyle='#444a51';ctx.lineWidth=Math.max(.7,o.strokeWidth*UNIT*.55);
    ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x+w,top+h);ctx.stroke();
  }
}
function drawMemo(ctx,o,y,text){
  if(!text||!o.visible)return;
  const x=MARGIN+o.x*UNIT,top=y+o.y*UNIT,w=o.w*UNIT,h=o.h*UNIT;
  const size=Math.max(12,Number(o.fontHeight||13)*UNIT*.91);
  const bold=/Bold|DemiBold/i.test(o.font)||['Memo25','Memo23'].includes(o.name);
  const fam=/Benyamin/.test(o.font)?'Benyamin':/Melody/.test(o.font)?'Melody':'DanaFaNum';
  ctx.font=`${bold?'bold ':''}${Math.min(size,35)}px "${fam}", "Tahoma", sans-serif`;
  ctx.fillStyle=['Memo28','Memo66'].includes(o.name)?'#fff':'#252a30';
  ctx.direction='rtl';
  ctx.textBaseline='middle';
  ctx.textAlign=o.hAlign==='haCenter'?'center':'right';
  // Render the rotated blue seller/buyer strips just like the FastReport.
  if(['Memo28','Memo66'].includes(o.name)){
    ctx.save();ctx.translate(x+w/2,top+h/2);ctx.rotate(-Math.PI/2);
    ctx.textAlign='center';ctx.fillText(text,0,0,h-10);ctx.restore();return;
  }
  const start=o.hAlign==='haCenter'?x+w/2:x+w-3;
  const mid=top+(o.vAlign==='vaTop'?.5:.5)*h;
  // Canvas maxWidth compresses only long descriptions, preserving borders.
  ctx.fillText(String(text),start,mid,Math.max(8,w-6));
}
function drawBand(ctx,bandName,y,fields){
  const objects=layout.bands[bandName]?.objects||[];
  for(const o of objects.filter(o=>o.type!=='text'))drawShape(ctx,o,y);
  for(const o of objects.filter(o=>o.type==='text')){
    const value=Object.hasOwn(fields,o.name)?fields[o.name]:o.text;
    drawMemo(ctx,o,y,value);
  }
}

function pageFields(doc,party,company,sourceNumber){
  const date=digits(formatAccountingJalali(doc.documentDate,{digits:'ascii'}));
  const seller=company?.legalName||'چاپ و تبلیغات کارما';
  return {
    frxDBDatasetFactorFactor_Date:date,
    frxDBDatasetFactorFactor_Num:sourceNumber,
    Memo25:seller,
    Memo35:seller,
    Memo55:company?.phone||'',
    frxDBDatasetAddTelMobile:company?.mobile||'',
    Memo63:company?.address||'',
    mmoaccname:party,
    mmoacctel:'',
    mmoaccaddress:'',
    Memo64:'',Memo74:'',Memo75:'',Memo76:'',
    Memo29:'نام شخص حقیقی/حقوقی:',
    Memo67:'نام شخص حقیقی/حقوقی:',
  };
}
function rowFields(row,i){
  return {Memo14:digits(i+1),mmoCode:row.itemId||row.code||'—',
    mmoGoods:row.description,Memo16:money(row.quantity),
    Memo17:money(row.unitPrice),Memo18:money(row.total)};
}
function summaryFields(doc,rows,party){
  const sumQty=rows.reduce((n,row)=>n+row.quantity,0);
  return {
    Memo19:money(doc.subtotal),
    Memo20:money(doc.discount),
    Memo23:money(doc.total),
    Memo54:money(sumQty),
    frxDBDatasetParamHorof:rialInPersianWords(doc.total)+' ریال',
    Memo10:'',Memo22:'',Memo33:'',Memo40:'',Memo5:'',
    Memo24:'',Memo1:'',mmoUser:'',mmoPayam:'',
    Memo42:'امضا خریدار:',Memo43:'مهر و امضا فروشنده:',
    Memo38:'',Memo39:'',mmoPercent:'',
    // No fictitious previous-balance, bank, or payment information.
  };
}
function drawDraft(ctx,doc,sourceNumber,page,pageCount){
  ctx.save();
  ctx.textAlign='right';ctx.textBaseline='middle';ctx.direction='rtl';
  ctx.fillStyle='#9a3d3d';ctx.font='bold 18px DanaFaNum, Tahoma, sans-serif';
  ctx.fillText('رونوشت آزمایشی پارسیان | پیش‌نویس مدار | ثبت قطعی نشده',
    PAPER_W-MARGIN,PAPER_H-MARGIN+12,PAPER_W-2*MARGIN);
  ctx.textAlign='left';ctx.fillStyle='#525e69';
  ctx.font='18px DanaFaNum, Tahoma, sans-serif';
  ctx.fillText(`PS1405-INV68-TEST / ${digits(page)} از ${digits(pageCount)}`,
    MARGIN,PAPER_H-MARGIN+12);
  ctx.restore();
}
async function logoImage(){
  const image=new Image();image.src=logoUrl;
  if(image.decode)await image.decode();
  else await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;});
  return image;
}
const imgToJpeg=canvas=>{
  const b64=canvas.toDataURL('image/jpeg',.94).split(',')[1];
  const binary=atob(b64);
  return Uint8Array.from(binary,byte=>byte.charCodeAt(0));
};

export async function buildParsianKarmaDocumentExport({
  kind,doc,party,format,company=null,sourceNumber=''
}){
  if(kind!=='invoice'||!doc||!Array.isArray(doc.lines)||doc.lines.length===0||
      !['pdf','png'].includes(format))
    throw Error('خروجی پارسیان فقط برای فاکتور فروش معتبر است.');
  if(!doc.lines.every(row=>typeof row.description==='string'&&
      isInteger(row.quantity)&&isInteger(row.unitPrice)&&
      isInteger(row.total)&&row.quantity*row.unitPrice===row.total)||
      !isInteger(doc.subtotal)||!isInteger(doc.total)||!isInteger(doc.discount)||
      !isInteger(doc.tax)||doc.lines.reduce((v,l)=>v+l.total,0)!==doc.subtotal||
      doc.subtotal-doc.discount+doc.tax!==doc.total)
    throw Error('مبالغ فاکتور با اقلام ثبت‌شده مطابقت ندارند.');
  if(typeof document==='undefined')throw Error('چاپ پارسیان نیازمند محیط نمایش اسناد است.');
  await document.fonts?.ready;
  const img=await logoImage();
  const titleH=layout.bands.ReportTitle.height*UNIT;
  const headerH=layout.bands.Header.height*UNIT;
  const lineH=layout.bands.MasterData.height*UNIT;
  const summaryH=layout.bands.ReportSummary.height*UNIT;
  const available=PAPER_H-2*MARGIN-MIN_PAGE_FOOTER;
  // Fit the first page's title (318), six item rows, and report summary
  // (327) on A4; extra item pages carry the header and then the summary.
  const pages=[];
  let next=0;
  const MAX_PAGES=100;
  const source=String(sourceNumber||doc.number||doc.id).replace(/[^\w\d\s-]/g,'');
  while(next<doc.lines.length){
    if(pages.length>=MAX_PAGES)throw Error('سند بیش از ۱۰۰ صفحه است.');
    const {canvas,ctx}=fileCanvas();
    const first=pages.length===0;
    let y=MARGIN;
    const titleFields=pageFields(doc,party,company,source);
    if(first){
      const titleFrame=layout.titleFrame[0];
      if(titleFrame?.type==='rect')drawShape(ctx,titleFrame,y);
      drawBand(ctx,'ReportTitle',y,titleFields);
      const rect=layout.logoRect;
      ctx.drawImage(img,MARGIN+rect.x*UNIT,y+rect.y*UNIT,rect.w*UNIT,rect.h*UNIT);
      y+=titleH+6*UNIT;
    }else{
      drawBand(ctx,'PageHeader',y,{
        Memo37:source,Memo48:digits(formatAccountingJalali(doc.documentDate)),
        Memo49:'صفحه '+digits(pages.length+1),Memo51:'',Memo44:'',
        Memo41:source,frxDBDatasetFactorFactor_Date1:'',Mmofactor:'فاکتور فروش'});
      y+=layout.bands.PageHeader.height*UNIT;
    }
    drawBand(ctx,'Header',y,{});
    y+=headerH;
    const availableForRows=available-y;
    const shouldFitSummary=next+Math.floor(availableForRows/lineH)>=doc.lines.length;
    const reserve=shouldFitSummary?summaryH:0;
    const capacity=Math.floor((available-y-reserve)/lineH);
    if(capacity<1)throw Error('ارتفاع چیدمان پارسیان برای ردیف‌ها کافی نیست.');
    const count=Math.min(capacity,doc.lines.length-next);
    const actualRows=doc.lines.slice(next,next+count);
    actualRows.forEach((line,idx)=>{
      drawBand(ctx,'MasterData',y+idx*lineH,rowFields(line,next+idx));
      // FastReport row grid has open horizontal segments, close them.
      ctx.strokeStyle='#52565a';ctx.lineWidth=.8;
      ctx.beginPath();
      const bottom=y+(idx+1)*lineH;
      ctx.moveTo(MARGIN,bottom);ctx.lineTo(MARGIN+CONTENT_W,bottom);ctx.stroke();
    });
    y+=count*lineH;
    next+=count;
    if(next===doc.lines.length)drawBand(ctx,'ReportSummary',y+4*UNIT,summaryFields(doc,doc.lines,party));
    pages.push(canvas);
  }
  const pageCount=pages.length;
  pages.forEach((canvas,i)=>drawDraft(canvas.getContext('2d'),doc,source,i+1,pageCount));
  const date=formatAccountingJalali(doc.documentDate,{digits:'ascii'}).replace(/\//g,'-');
  const filename=safeInvoiceFilename(
    'parsian-karma-{kind}-{id}-{date}-DRAFT',
    {kind,id:doc.id,date,number:doc.number})+'.'+format;
  if(format==='png'){
    if(pageCount!==1)throw Error('برای فاکتور چندصفحه‌ای PDF دریافت کنید.');
    const blob=await new Promise((resolve,reject)=>pages[0].toBlob(
      result=>result?resolve(result):reject(Error('تبدیل تصویر ناموفق بود.')),'image/png'));
    return {filename,blob};
  }
  return {filename,blob:jpegPagesToPdf(pages.map(canvas=>({
    width:canvas.width,height:canvas.height,jpeg:imgToJpeg(canvas)})))};
}
