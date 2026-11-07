/** Offline, structured invoice exports for Madar's standalone accounting book.
 * XLSX uses an uncompressed, standards-compliant OOXML ZIP container and RTF
 * uses escaped UTF-16 code units. Neither format needs an external service.
 * Monetary amounts are written in the ledger's original currency, unchanged.
 */
import {formatAccountingJalali} from './accounting_jalali_dates.js';
import {safeInvoiceFilename} from './standalone_invoice_export.js';

const ENCODER=new TextEncoder();
const MAX_AMOUNT=1000000000000000n;
const MAX_LINES=2000;
const LABELS={invoice:'فاکتور فروش',bill:'صورتحساب خرید',
  proforma:'پیش‌فاکتور فروش'};
const STATUSES={draft:'پیش‌نویس',approved:'تأییدشده',issued:'صادرشده',
  sent:'ارسال‌شده',accepted:'پذیرفته‌شده',rejected:'ردشده',
  converted:'تبدیل‌شده',cancelled:'لغوشده',reversed:'برگشت‌شده'};

function checkedText(value,label,max=300,required=false){
  if(typeof value!=='string'||value.length>max||(required&&!value.trim()))
    throw Error(label+' معتبر نیست.');
  // XML 1.0 allows TAB/CR/LF, but accepting controls in invoice fields would
  // also create ambiguous spreadsheet and RTF output. Require printable text.
  for(let i=0;i<value.length;i++){
    const point=value.codePointAt(i);
    if(point<32||point===127||point===0xfffe||point===0xffff||
       (point>=0xd800&&point<=0xdfff))
      throw Error(label+' دارای نویسه نامعتبر است.');
    if(point>0xffff)i++;
  }
  return value;
}
function optionalText(value,label,max=300){
  return value==null?'':checkedText(String(value),label,max);
}
function checkedAmount(value,label,positive=false){
  if(!Number.isSafeInteger(value)||value<0||
     BigInt(value)>MAX_AMOUNT||(positive&&value===0))
    throw Error(label+' معتبر نیست.');
  return value;
}
function partyName(party){
  if(typeof party==='string')return checkedText(party,'نام طرف‌حساب',300,true);
  if(party&&typeof party==='object'&&!Array.isArray(party))
    return checkedText(party.name,'نام طرف‌حساب',300,true);
  throw Error('نام طرف‌حساب معتبر نیست.');
}
function checkedCompany(company){
  if(company==null)return {};
  if(typeof company!=='object'||Array.isArray(company))
    throw Error('مشخصات شرکت معتبر نیست.');
  const result={};
  for(const [key,max] of Object.entries({legalName:300,nationalId:60,
    economicCode:60,postalCode:32,phone:100,address:1000,mobile:100})){
    result[key]=optionalText(company[key],key,max);
  }
  return result;
}
function checkedDocument({kind,doc,party,company,currency,format,pattern}){
  if(!Object.hasOwn(LABELS,kind)||!['xlsx','rtf'].includes(format)||
     !['RIAL','TOMAN'].includes(currency))
    throw Error('نوع سند، قالب خروجی یا واحد پول معتبر نیست.');
  if(!doc||typeof doc!=='object'||Array.isArray(doc)||
     !Array.isArray(doc.lines)||!doc.lines.length||doc.lines.length>MAX_LINES)
    throw Error('اقلام سند باید بین یک تا ۲۰۰۰ ردیف باشند.');
  const id=checkedText(doc.id,'شناسه سند',120,true);
  const solar=formatAccountingJalali(doc.documentDate,{digits:'ascii'});
  if(!/^\d{4}\/\d{2}\/\d{2}$/.test(solar))
    throw Error('تاریخ سند معتبر نیست.');
  const status=optionalText(doc.status,'وضعیت سند',80);
  const number=doc.number==null?'':optionalText(doc.number,'شماره سند',120);
  const lines=[];
  let computed=0n;
  for(let i=0;i<doc.lines.length;i++){
    const row=doc.lines[i];
    if(!row||typeof row!=='object'||Array.isArray(row))
      throw Error('ردیف '+(i+1)+' معتبر نیست.');
    const description=checkedText(row.description,'شرح ردیف '+(i+1),300,true);
    const quantity=checkedAmount(row.quantity,'تعداد ردیف '+(i+1),true);
    const unitPrice=checkedAmount(row.unitPrice,'فی ردیف '+(i+1));
    const total=checkedAmount(row.total,'جمع ردیف '+(i+1));
    if(BigInt(quantity)*BigInt(unitPrice)!==BigInt(total))
      throw Error('حاصل‌ضرب تعداد و فی ردیف '+(i+1)+' مطابقت ندارد.');
    computed+=BigInt(total);
    if(computed>MAX_AMOUNT)throw Error('جمع اقلام از سقف مجاز بیشتر است.');
    lines.push({description,quantity,unitPrice,total,
      itemId:optionalText(row.itemId??row.code,'شناسه کالا',120),
      accountId:optionalText(row.accountId,'شناسه حساب',120)});
  }
  const subtotal=checkedAmount(doc.subtotal,'جمع اقلام');
  const discount=checkedAmount(doc.discount,'تخفیف');
  const tax=checkedAmount(doc.tax,'مالیات');
  const total=checkedAmount(doc.total,'جمع نهایی');
  if(computed!==BigInt(subtotal)||
     BigInt(subtotal)-BigInt(discount)+BigInt(tax)!==BigInt(total))
    throw Error('مبالغ سند با ردیف‌های آن مطابقت ندارند.');
  const name=partyName(party),profile=checkedCompany(company);
  const filename=safeInvoiceFilename(pattern??'madar-{kind}-{id}-{date}',
    {kind,id,date:solar.replace(/\//g,'-'),number})+'.'+format;
  return {kind,id,number,status,solar,date:doc.documentDate,
    dueDate:optionalText(doc.dueDate,'تاریخ سررسید',24),
    validUntil:optionalText(doc.validUntil,'تاریخ اعتبار',24),
    note:optionalText(doc.note,'یادداشت',2000),
    name,profile,currency,unit:currency==='RIAL'?'ریال':'تومان',
    lines,subtotal,discount,tax,total,filename};
}

const xmlEscape=text=>String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;');

// Excel formula payloads must remain inert even if exported cells are copied
// to another spreadsheet or converted to CSV. All text cells use inlineStr.
function spreadsheetText(value){
  const text=String(value);
  return /^[\s\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]*[=+@-]/u
    .test(text.normalize('NFKC'))?"'"+text:text;
}
function sheetRows(doc){
  const meta=[
    ['مدار | '+LABELS[doc.kind]],
    ['شرکت',doc.profile.legalName||'مدار | حسابداری مستقل'],
    ['شناسه ملی',doc.profile.nationalId],
    ['کد اقتصادی',doc.profile.economicCode],
    ['کد پستی',doc.profile.postalCode],
    ['تلفن شرکت',doc.profile.phone],
    ['نشانی شرکت',doc.profile.address],
    ['طرف‌حساب',doc.name],
    ['شناسه سند',doc.id],
    ['شماره سند',doc.number],
    ['تاریخ (شمسی)',doc.solar],
    ['تاریخ (میلادی)',doc.date],
    ['وضعیت',STATUSES[doc.status]||doc.status],
    ['واحد پول',doc.unit],
  ];
  if(doc.dueDate)meta.push(['سررسید',doc.dueDate]);
  if(doc.validUntil)meta.push(['اعتبار تا',doc.validUntil]);
  if(doc.note)meta.push(['یادداشت',doc.note]);
  if(doc.kind==='proforma')
    meta.push(['ماهیت سند','پیشنهاد قیمت، بدون اثر مالی تا صدور فاکتور']);
  else if(doc.status==='reversed')
    meta.push(['ماهیت سند','سند برگشت‌شده، فاقد مطالبه جدید']);
  else if(doc.status==='cancelled')
    meta.push(['ماهیت سند','سند لغوشده، قابل تسویه نیست']);
  else if(doc.status!=='issued')
    meta.push(['ماهیت سند','سند هنوز صادر نشده است']);
  meta.push([]);
  meta.push(['ردیف','شرح','تعداد','فی ('+doc.unit+')','جمع ('+doc.unit+')',
    'شناسه کالا','شناسه حساب']);
  doc.lines.forEach((line,index)=>meta.push([index+1,line.description,
    line.quantity,line.unitPrice,line.total,line.itemId,line.accountId]));
  meta.push([]);
  for(const [label,num] of [['جمع اقلام',doc.subtotal],['تخفیف',doc.discount],
    ['مالیات',doc.tax],['جمع نهایی',doc.total]])
    meta.push([label,'','','',num]);
  return meta;
}
function columnName(index){
  let value=index+1,result='';
  while(value){value--;result=String.fromCharCode(65+value%26)+result;
    value=Math.floor(value/26);}
  return result;
}
function worksheetXml(rows){
  const parts=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    '<dimension ref="A1:G'+rows.length+'"/>',
    '<sheetViews><sheetView workbookViewId="0" rightToLeft="1"/></sheetViews>',
    '<sheetFormatPr defaultRowHeight="16"/>',
    '<cols><col min="1" max="1" width="17" customWidth="1"/>',
    '<col min="2" max="2" width="54" customWidth="1"/>',
    '<col min="3" max="3" width="15" customWidth="1"/>',
    '<col min="4" max="5" width="23" customWidth="1"/>',
    '<col min="6" max="7" width="20" customWidth="1"/></cols>',
    '<sheetData>'];
  rows.forEach((row,i)=>{
    parts.push('<row r="'+(i+1)+'">');
    row.forEach((value,j)=>{
      if(value==null||value==='')return;
      const ref=columnName(j)+(i+1);
      if(typeof value==='number'){
        parts.push('<c r="'+ref+'" s="2"><v>'+value+'</v></c>');
      }else{
        const text=spreadsheetText(value);
        const preserve=/^\s|\s$/.test(text)?' xml:space="preserve"':'';
        parts.push('<c r="'+ref+'" t="inlineStr" s="'+
          (j===0?'1':'0')+'"><is><t'+preserve+'>'+xmlEscape(text)+
          '</t></is></c>');
      }
    });
    parts.push('</row>');
  });
  parts.push('</sheetData></worksheet>');
  return parts.join('');
}

const FILES={
  '[Content_Types].xml':'<?xml version="1.0" encoding="UTF-8"?>'+
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'+
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'+
    '<Default Extension="xml" ContentType="application/xml"/>'+
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'+
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+
    '</Types>',
  '_rels/.rels':'<?xml version="1.0" encoding="UTF-8"?>'+
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'+
    '</Relationships>',
  'xl/workbook.xml':'<?xml version="1.0" encoding="UTF-8"?>'+
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '+
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'+
    '<sheets><sheet name="Invoice" sheetId="1" r:id="rId1"/></sheets></workbook>',
  'xl/_rels/workbook.xml.rels':'<?xml version="1.0" encoding="UTF-8"?>'+
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'+
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'+
    '</Relationships>',
  'xl/styles.xml':'<?xml version="1.0" encoding="UTF-8"?>'+
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+
    '<fonts count="2"><font><sz val="11"/><name val="Tahoma"/></font>'+
    '<font><b/><sz val="11"/><name val="Tahoma"/></font></fonts>'+
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'+
    '<fill><patternFill patternType="gray125"/></fill></fills>'+
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'+
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'+
    '<cellXfs count="3">'+
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'+
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>'+
    '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'+
    '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'+
    '</styleSheet>',
};
const crcTable=Uint32Array.from({length:256},(_,index)=>{
  let value=index;
  for(let j=0;j<8;j++)value=value&1?0xedb88320^(value>>>1):value>>>1;
  return value>>>0;
});
function crc32(bytes){
  let value=0xffffffff;
  for(const byte of bytes)value=crcTable[(value^byte)&255]^(value>>>8);
  return (value^0xffffffff)>>>0;
}
function zipPart(size,write){
  const bytes=new Uint8Array(size);
  write(new DataView(bytes.buffer));
  return bytes;
}
function buildZip(files){
  const parts=[],central=[];
  let offset=0;
  for(const [path,source] of Object.entries(files)){
    const name=ENCODER.encode(path),body=ENCODER.encode(source);
    const crc=crc32(body);
    const local=zipPart(30,(v)=>{
      v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);
      v.setUint16(6,0x0800,true);v.setUint16(8,0,true);
      v.setUint32(14,crc,true);v.setUint32(18,body.length,true);
      v.setUint32(22,body.length,true);v.setUint16(26,name.length,true);
    });
    const index=zipPart(46,(v)=>{
      v.setUint32(0,0x02014b50,true);v.setUint16(4,20,true);
      v.setUint16(6,20,true);v.setUint16(8,0x0800,true);
      v.setUint32(16,crc,true);v.setUint32(20,body.length,true);
      v.setUint32(24,body.length,true);v.setUint16(28,name.length,true);
      v.setUint32(42,offset,true);
    });
    parts.push(local,name,body);
    central.push(index,name);
    offset+=local.length+name.length+body.length;
  }
  const directorySize=central.reduce((size,b)=>size+b.length,0);
  const count=Object.keys(files).length;
  const end=zipPart(22,(v)=>{
    v.setUint32(0,0x06054b50,true);v.setUint16(8,count,true);
    v.setUint16(10,count,true);v.setUint32(12,directorySize,true);
    v.setUint32(16,offset,true);
  });
  return new Blob([...parts,...central,end],
    {type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
}

function rtfText(text){
  let output='';
  for(let i=0;i<text.length;i++){
    const code=text.charCodeAt(i);
    if(code===92||code===123||code===125)
      output+='\\'+String.fromCharCode(code);
    else if(code>127)output+='\\u'+(code>32767?code-65536:code)+'?';
    else output+=String.fromCharCode(code);
  }
  return output;
}
function rtfParagraph(text,{bold=false}={}){
  return '\\pard\\rtlpar\\qr\\sa100'+(bold?'\\b ':' ')+
    rtfText(text)+(bold?'\\b0':'')+'\\par\n';
}
function rtfRow(cells){
  const positions=[750,4600,5800,7300,8700,9600,10400];
  let row='\\trowd\\rtlrow\\trgaph90\\trleft0'+
    positions.map(x=>'\\cellx'+x).join('')+'\n';
  for(const cell of cells){
    row+='\\pard\\intbl\\rtlpar\\qr '+
      rtfText(String(cell??''))+'\\cell\n';
  }
  return row+'\\row\n';
}
function buildRtf(doc){
  const money=n=>n.toLocaleString('fa-IR');
  const body=['{\\rtf1\\ansi\\ansicpg1252\\uc1\\deff0',
    '{\\fonttbl{\\f0\\fnil\\fcharset0 Tahoma;}}',
    '\\paperw11906\\paperh16838\\margl700\\margr700\\margt900\\margb900',
    '\\viewkind4\\f0\\fs22\n',
    rtfParagraph('مدار | '+LABELS[doc.kind],{bold:true}),
    rtfParagraph('شرکت: '+(doc.profile.legalName||'مدار | حسابداری مستقل')),
    rtfParagraph('طرف‌حساب: '+doc.name),
    rtfParagraph('شناسه سند: '+doc.id+' | شماره: '+doc.number),
    rtfParagraph('تاریخ (شمسی): '+doc.solar+' | وضعیت: '+(STATUSES[doc.status]||doc.status)),
    rtfParagraph('واحد تمامی مبالغ: '+doc.unit)];
  for(const [label,value] of [['شناسه ملی',doc.profile.nationalId],
    ['کد اقتصادی',doc.profile.economicCode],['کد پستی',doc.profile.postalCode],
    ['تلفن',doc.profile.phone],
    ['نشانی',doc.profile.address],['سررسید',doc.dueDate],
    ['اعتبار تا',doc.validUntil],['یادداشت',doc.note]])
    if(value)body.push(rtfParagraph(label+': '+value));
  if(doc.kind==='proforma')body.push(
    rtfParagraph('پیشنهاد قیمت | بدون اثر مالی تا صدور فاکتور',{bold:true}));
  else if(doc.status==='reversed'||doc.status==='cancelled')
    body.push(rtfParagraph('سند برگشت‌شده یا لغوشده | فاقد مطالبه جدید',{bold:true}));
  else if(doc.status!=='issued')
    body.push(rtfParagraph('سند هنوز صادر نشده است',{bold:true}));
  body.push(rtfRow(['ردیف','شرح','تعداد','فی ('+doc.unit+')',
    'جمع ('+doc.unit+')','شناسه کالا','شناسه حساب']));
  doc.lines.forEach((line,i)=>body.push(rtfRow([i+1,line.description,
    money(line.quantity),money(line.unitPrice),money(line.total),
    line.itemId,line.accountId])));
  for(const [label,value] of [['جمع اقلام',doc.subtotal],
    ['تخفیف',doc.discount],['مالیات',doc.tax],['جمع نهایی',doc.total]])
    body.push(rtfParagraph(label+': '+money(value)+' '+doc.unit,
      {bold:label==='جمع نهایی'}));
  body.push('}');
  return new Blob([body.join('')],{type:'application/rtf'});
}

export async function buildAccountingStructuredExport({
  kind,doc,party,company=null,currency='RIAL',format,pattern
}){
  const record=checkedDocument({kind,doc,party,company,currency,format,pattern});
  const blob=format==='xlsx'?
    buildZip({...FILES,
      'xl/workbook.xml':FILES['xl/workbook.xml'].replace('name="Invoice"',
        'name="'+xmlEscape(LABELS[record.kind])+'"'),
      'xl/worksheets/sheet1.xml':worksheetXml(sheetRows(record))}):
    buildRtf(record);
  return {filename:record.filename,blob};
}
