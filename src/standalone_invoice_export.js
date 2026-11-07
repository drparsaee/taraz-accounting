/** Offline Persian invoice rendering. No remote service or operational task data.
 * PNG and PDF render from the same browser-shaped canvas. PDF is raster-based.
 */
import {formatAccountingJalali} from './accounting_jalali_dates.js';
const ENCODER=new TextEncoder();
const ascii=s=>ENCODER.encode(s);
const concat=(...parts)=>{
  const n=parts.reduce((sum,x)=>sum+x.length,0),result=new Uint8Array(n);
  let offset=0;for(const part of parts){result.set(part,offset);offset+=part.length;}
  return result;
};

export function safeInvoiceFilename(pattern,{kind,id,date,number}){
  if(typeof pattern!=='string'||pattern.length>150||!pattern.trim())throw Error('الگوی نام فایل معتبر نیست.');
  if(!['invoice','bill','proforma'].includes(kind)||typeof id!=='string'||
     !id.trim()||typeof date!=='string'||!date.trim())
    throw Error('مشخصات سند برای نام خروجی نامعتبر است.');
  const values={kind,id,date,number:String(number||'draft')};
  const named=pattern.replace(/\{(kind|id|date|number)\}/g,(_,key)=>values[key]);
  if(/[{}]/.test(named))throw Error('متغیر ناشناخته در الگوی نام فایل.');
  let clean=named.normalize('NFKC').replace(/[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]/gi,'-')
    .replace(/[.\s-]+$/g,'').trim().replace(/^\.+/,'');
  if(!clean||clean==='.'||clean==='..'||clean.length>180||
     /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i.test(clean))
    throw Error('نام خروجی خالی یا نامعتبر است.');
  return clean;
}

export function jpegPagesToPdf(pages){
  if(!Array.isArray(pages)||!pages.length||pages.length>100)
    throw Error('PDF requires 1..100 image pages');
  const objects=new Map(),kids=[];
  objects.set(1,ascii('<< /Type /Catalog /Pages 2 0 R >>'));
  for(let i=0;i<pages.length;i++){
    const p=pages[i],page=3+i*3,image=page+1,contents=page+2;
    if(!Number.isSafeInteger(p.width)||!Number.isSafeInteger(p.height)||
       p.width<=0||p.height<=0||!(p.jpeg instanceof Uint8Array)||
       p.jpeg.length<4||p.jpeg[0]!==255||p.jpeg[1]!==216)
      throw Error('Invalid JPEG page');
    kids.push(page+' 0 R');
    const pointW=Number.isFinite(p.pointsWidth)&&p.pointsWidth>0&&p.pointsWidth<2000?p.pointsWidth:595.28;
    const pointH=Number.isFinite(p.pointsHeight)&&p.pointsHeight>0&&p.pointsHeight<2000?p.pointsHeight:841.89;
    objects.set(page,ascii('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 '+pointW+' '+pointH+'] '+
      '/Resources << /XObject << /Im0 '+image+' 0 R >> >> /Contents '+
      contents+' 0 R >>'));
    objects.set(image,concat(ascii('<< /Type /XObject /Subtype /Image /Width '+p.width+
      ' /Height '+p.height+' /ColorSpace /DeviceRGB /BitsPerComponent 8 '+
      '/Filter /DCTDecode /Length '+p.jpeg.length+' >>\nstream\n'),p.jpeg,ascii('\nendstream')));
    const commands=ascii('q '+pointW+' 0 0 '+pointH+' 0 0 cm /Im0 Do Q\n');
    objects.set(contents,concat(ascii('<< /Length '+commands.length+' >>\nstream\n'),
      commands,ascii('endstream')));
  }
  objects.set(2,ascii('<< /Type /Pages /Kids ['+kids.join(' ')+'] /Count '+pages.length+' >>'));
  const chunks=[ascii('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')],offsets=[0];
  let cursor=chunks[0].length;
  for(let id=1;id<=2+pages.length*3;id++){
    offsets[id]=cursor;
    const chunk=concat(ascii(id+' 0 obj\n'),objects.get(id),ascii('\nendobj\n'));
    chunks.push(chunk);cursor+=chunk.length;
  }
  const xref=cursor;
  chunks.push(ascii('xref\n0 '+(offsets.length)+'\n0000000000 65535 f \n'+
    offsets.slice(1).map(o=>String(o).padStart(10,'0')+' 00000 n \n').join('')+
    'trailer\n<< /Size '+offsets.length+' /Root 1 0 R >>\nstartxref\n'+xref+
    '\n%%EOF\n'));
  return new Blob(chunks,{type:'application/pdf'});
}

const jpegBytes=canvas=>{
  const data=canvas.toDataURL('image/jpeg',0.93).split(',')[1];
  const bytes=atob(data),output=new Uint8Array(bytes.length);
  for(let i=0;i<bytes.length;i++)output[i]=bytes.charCodeAt(i);
  return output;
};
const fmt=x=>Number.isSafeInteger(x)?x.toLocaleString('fa-IR'):'نامعتبر';

function drawPage(kind,doc,party,lines,pageIndex,pageCount,currency,company){
  const unit=currency==='RIAL'?'ریال':'تومان';
  const canvas=document.createElement('canvas');
  canvas.width=1240;canvas.height=1754;
  const c=canvas.getContext('2d');
  if(!c)throw Error('موتور رسم سند در مرورگر فعال نیست.');
  c.fillStyle='#fff';c.fillRect(0,0,1240,1754);
  c.direction='rtl';c.textAlign='right';c.fillStyle='#203239';
  c.font='bold 46px Vazirmatn, sans-serif';
  c.fillText(kind==='proforma'?'پیش‌فاکتور فروش':kind==='invoice'?'فاکتور فروش':'صورتحساب خرید',1130,105);
  c.font='29px Vazirmatn, sans-serif';
  c.fillText(company?.legalName?'فروشنده: '+company.legalName:'مدار | حسابداری مستقل',
    1130,161,1010);
  if(company){
    c.font='18px Vazirmatn, sans-serif';
    c.fillText('شناسه ملی: '+(company.nationalId||'—')+
      ' | شناسه اقتصادی: '+(company.economicCode||'—')+
      ' | تلفن: '+(company.phone||'—'),1130,182,1010);
    if(company.address)c.fillText('نشانی: '+company.address,1130,202,1000);
  }
  c.font='26px Vazirmatn, sans-serif';
  c.fillText('طرف‌حساب: '+party,1130,225);
  c.fillText('شناسه سند: '+doc.id,1130,267);
  c.fillText('تاریخ (شمسی): '+formatAccountingJalali(doc.documentDate)+' | وضعیت: '+doc.status,1130,309);
  if(kind==='proforma'&&doc.validUntil)
    c.fillText('اعتبار تا (شمسی): '+formatAccountingJalali(doc.validUntil),1130,353);
  else if(doc.dueDate)
    c.fillText('سررسید (شمسی): '+formatAccountingJalali(doc.dueDate),1130,353);
  c.fillText('صفحه '+(pageIndex+1)+' از '+pageCount,355,353);
  c.fillStyle='#e9f3f4';c.fillRect(100,390,1040,60);
  c.fillStyle='#203239';c.font='bold 26px Vazirmatn, sans-serif';
  c.fillText('شرح',1100,429);c.fillText('تعداد',520,429);
  c.fillText('فی ('+unit+')',350,429);c.fillText('جمع ('+unit+')',185,429);
  c.font='24px Vazirmatn, sans-serif';
  lines.forEach((line,i)=>{
    const y=501+i*49;
    c.fillStyle=i%2?'#f6faf9':'#fff';c.fillRect(100,y-36,1040,48);
    c.fillStyle='#203239';
    const label=String(line.description);
    if(c.measureText(label).width>530)
      throw Error('شرح یکی از ردیف‌ها برای عرض قالب خروجی بلند است؛ کوتاه‌ترش کنید.');
    c.fillText(label,1100,y);c.fillText(fmt(line.quantity),520,y);
    c.fillText(fmt(line.unitPrice),350,y);c.fillText(fmt(line.total),185,y);
  });
  if(pageIndex===pageCount-1){
    c.font='25px Vazirmatn, sans-serif';
    c.fillText('جمع اقلام: '+fmt(doc.subtotal)+' '+unit,1130,1525);
    c.fillText('تخفیف: '+fmt(doc.discount)+' '+unit,1130,1562);
    c.fillText((doc.taxRuleId?'مالیات بر اساس سیاست ثبت‌شده: ':'مالیات صریح: ')+
      fmt(doc.tax)+' '+unit,1130,1599);
    c.font='bold 30px Vazirmatn, sans-serif';
    c.fillText('جمع نهایی: '+fmt(doc.total)+' '+unit,1130,1641);
    c.font='21px Vazirmatn, sans-serif';
    if(doc.status==='reversed'){
      c.fillStyle='#a32335';c.font='bold 26px Vazirmatn, sans-serif';
      c.fillText('سند برگشت‌شده / فاقد مطالبه معتبر جدید'+
        (doc.correctedBy?' / جایگزین: '+doc.correctedBy:''),1130,1685,1010);
    }else if(doc.status==='cancelled'){
      c.fillStyle='#a32335';c.font='bold 26px Vazirmatn, sans-serif';
      c.fillText('این سند لغو شده است و قابل تسویه نیست',1130,1685,1010);
    }else if(kind==='proforma')
      c.fillText('پیشنهاد قیمت / فاقد اثر مالی تا صدور فاکتور قطعی',1130,1685);
    else if(doc.status!=='issued')
      c.fillText('پیش‌نویس سند / ثبت قطعی نشده',1130,1685);
    else if(doc.correctionOf)
      c.fillText('فاکتور جایگزین اصلاحی / سند مبدأ: '+doc.correctionOf,1130,1685,1010);
  }
  return canvas;
}

export async function buildStandaloneDocumentExport({kind,doc,party,format,pattern,
  currency='TOMAN',company=null}){
  if(!['invoice','bill','proforma'].includes(kind)||!doc||!Array.isArray(doc.lines)||
     !['pdf','png'].includes(format)||!['RIAL','TOMAN'].includes(currency))
    throw Error('سند یا قالب خروجی معتبر نیست.');
  const filename=safeInvoiceFilename(pattern,{kind,id:doc.id,
    date:formatAccountingJalali(doc.documentDate,{digits:'ascii'}).replace(/\//g,'-'),
    number:doc.number})+'.'+format;
  if(typeof document==='undefined')throw Error('Export needs an interactive browser');
  await document.fonts?.ready;
  // Reserve a clear footer region even on a completely filled last page.
  const perPage=20,groups=[];
  for(let i=0;i<doc.lines.length;i+=perPage)groups.push(doc.lines.slice(i,i+perPage));
  if(!groups.length)throw Error('سند فاقد اقلام معتبر است.');
  if(format==='png'&&groups.length>1)
    throw Error('خروجی تصویر برای سند بیش از ۲۰ ردیف پشتیبانی نمی‌شود؛ PDF چندصفحه‌ای بگیرید.');
  if(groups.length>100)throw Error('بیش از ۱۰۰ صفحه برای خروجی مجاز نیست.');
  const canvases=groups.map((lines,index)=>
    drawPage(kind,doc,party,lines,index,groups.length,currency,company));
  if(format==='png'){
    const blob=await new Promise((resolve,reject)=>canvases[0].toBlob(
      value=>value?resolve(value):reject(Error('خطای خروجی PNG')),'image/png'));
    return {filename,blob};
  }
  return {filename,blob:jpegPagesToPdf(canvases.map(canvas=>({
    width:canvas.width,height:canvas.height,jpeg:jpegBytes(canvas)})))};
}

export function downloadStandaloneBlob({filename,blob}){
  const href=URL.createObjectURL(blob),anchor=document.createElement('a');
  anchor.href=href;anchor.download=filename;anchor.style.display='none';
  document.body.appendChild(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(href),30000);
}
