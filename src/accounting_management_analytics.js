/**
 * Read-only management analytics for accounting_view() from accounting_core.py.
 *
 * Dates and money are never inferred from the user's locale. Monetary values
 * remain in view.currency (RIAL or TOMAN); no implicit conversion, forecasts,
 * estimates of product costs, or mutations. Journal amounts are summed with
 * BigInt, then checked before exposing chart-safe JavaScript numbers.
 *
 * Sales: currently issued invoices, at their posting date, net of the partial
 * credits recorded on each invoice. A return changes the original issue
 * month's net amount, not the month in which the credit note was posted.
 * GL turnover is a separate posting-date measure and may differ from sales.
 */

const LIMIT=BigInt(Number.MAX_SAFE_INTEGER);
const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const money=(value,field)=>{
  if(!Number.isSafeInteger(value)||value<0)
    throw new Error('مبلغ نامعتبر در '+field);
  return BigInt(value);
};
const quantity=(value,field)=>{
  if(!Number.isSafeInteger(value)||value<0)
    throw new Error('تعداد نامعتبر در '+field);
  return BigInt(value);
};
const asNumber=(value)=>{
  if(value>LIMIT||value< -LIMIT)
    throw new Error('مجموع مبالغ از دقت مجاز گزارش بیشتر است.');
  return Number(value);
};
const date=value=>{
  if(value===''||value===null||value===undefined)return '';
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))
    return null;
  const stamp=new Date(value+'T00:00:00Z');
  return !Number.isNaN(stamp.valueOf())&&stamp.toISOString().slice(0,10)===value?
    value:null;
};
const monthOf=day=>day.slice(0,7);
const monthIndex=month=>Number(month.slice(0,4))*12+Number(month.slice(5,7))-1;
const monthAt=index=>String(Math.floor(index/12)).padStart(4,'0')+'-'+
  String(index%12+1).padStart(2,'0');
const entries=value=>Object.entries(record(value)?value:{});
const daysFrom=day=>Math.floor(new Date(day+'T00:00:00Z').valueOf()/86400000);
const validPostingDate=(value,field)=>{
  const parsed=date(value);
  if(!parsed)throw new Error('تاریخ ثبت نامعتبر در '+field);
  return parsed;
};
const byAmountThenName=(a,b)=>b.amount>a.amount?1:b.amount<a.amount?-1:
  a.name.localeCompare(b.name,'fa')||a.key.localeCompare(b.key);
const normalizedDescription=value=>typeof value==='string'?
  value.normalize('NFKC').trim().replace(/\s+/gu,' ').toLocaleLowerCase('fa'):'';

/**
 * @param {object} view Accounting materialized projection, not its event store.
 * @param {{from?:string,to?:string,fromDate?:string,toDate?:string,
 *   today?:string,currency?:'RIAL'|'TOMAN'}} options ISO Gregorian days.
 * @returns {{error:string,currency:string,unit:string,range:object,
 *   kpis:Array,charts:Array,reminders:Array,topProducts:Array,
 *   costData:object,warnings:Array}}
 */
export function buildManagementAnalytics(view,options={}){
  const empty={error:'',currency:'',unit:'',range:{from:'',to:'',today:''},
    kpis:[],charts:[],reminders:[],topProducts:[],
    costData:{available:false,reason:'بهای تمام‌شدهٔ تأییدشدهٔ همهٔ اقلام در دفتر در دسترس نیست.'},
    warnings:[]};
  try{
    if(!record(view)||!record(options)||!record(view.accounts)||
       !record(view.invoices)||!Array.isArray(view.journals))
      throw new Error('ساختار دفتر حسابداری برای داشبورد کامل نیست.');
    if(!['RIAL','TOMAN'].includes(view.currency))
      throw new Error('واحد پولی دفتر حسابداری نامعتبر است.');
    if(options.currency!==undefined&&options.currency!==view.currency)
      throw new Error('واحد درخواست با واحد دفتر حسابداری مغایرت دارد.');
    const from=date(options.from??options.fromDate??'');
    const to=date(options.to??options.toDate??'');
    const today=date(options.today??'');
    if(from===null||to===null||today===null||(from&&to&&from>to))
      throw new Error('بازه یا تاریخ امروز برای داشبورد نامعتبر است.');
    const currency=view.currency,unit=currency==='RIAL'?'ریال':'تومان';
    const inside=day=>(!from||day>=from)&&(!to||day<=to);

    const monthly=new Map();
    const goods=new Map();
    let sales=0n,salesCount=0;
    for(const [id,invoice] of entries(view.invoices)){
      if(!record(invoice)||invoice.status!=='issued')continue;
      const issued=validPostingDate(invoice.postingDate,'فاکتور '+id);
      if(!inside(issued))continue;
      if(!Array.isArray(invoice.lines))throw new Error('ردیف فاکتور نامعتبر است.');
      const gross=money(invoice.total,'فاکتور '+id);
      const returned=money(invoice.returnedAmount??0,'برگشت فاکتور '+id);
      if(returned>gross)throw new Error('برگشت بیشتر از مبلغ فاکتور است.');
      const net=gross-returned;
      sales+=net;
      salesCount++;
      const month=monthOf(issued);
      monthly.set(month,(monthly.get(month)||0n)+net);

      // The core stores cumulative per-line return quantities, if any.
      // Fall back to actual posted partial-return rows for old projections.
      const stored=invoice.returnedQuantities;
      if(stored!==undefined&&(!Array.isArray(stored)||stored.length!==invoice.lines.length))
        throw new Error('تعداد برگشتی فاکتور با ردیف‌ها سازگار نیست.');
      const derived=new Map();
      if(stored===undefined){
        for(const [returnId,ret] of entries(view.returns)){
          if(!record(ret)||ret.kind!=='partial'||ret.direction!=='sale'||
             ret.documentId!==invoice.id)continue;
          if(!Array.isArray(ret.lines))throw new Error('ردیف برگشت فروش نامعتبر است.');
          for(const row of ret.lines){
            if(!Number.isInteger(row.lineIndex)||row.lineIndex<0||
               row.lineIndex>=invoice.lines.length)
              throw new Error('شاخص ردیف برگشت فروش نامعتبر است.');
            derived.set(row.lineIndex,(derived.get(row.lineIndex)||0n)+
              quantity(row.quantity,'تعداد برگشتی '+returnId));
          }
        }
      }
      invoice.lines.forEach((line,index)=>{
        if(!record(line))throw new Error('ردیف فاکتور نامعتبر است.');
        const count=quantity(line.quantity,'تعداد فاکتور '+id);
        const ret=stored===undefined?(derived.get(index)||0n):
          quantity(stored[index],'تعداد برگشتی '+id);
        if(ret>count)throw new Error('تعداد برگشتی بیش از فروش است.');
        const balance=count-ret;
        if(balance===0n)return;
        const price=money(line.unitPrice,'بهای فروش ردیف '+id);
        const item=line.itemId?view.items?.[line.itemId]:null;
        const description=normalizedDescription(line.description);
        // Lines with no catalog itemId are still actual posted services/sales.
        // Keep them distinct from catalog items and from other descriptions;
        // never invent catalog identifiers or aggregate unlike descriptions.
        if(!line.itemId&&!description)return;
        const key=line.itemId?'item:'+line.itemId:'description:'+description;
        const name=record(item)?item.name:
          (line.itemId?'قلم بدون کاتالوگ: '+(line.description||line.itemId):
            'خدمت/قلم بدون کاتالوگ: '+line.description.trim());
        const prior=goods.get(key)||{
          key,itemId:line.itemId||null,name,
          kind:record(item)?item.kind:'uncatalogued',
          unit:record(item)?item.unit:'واحد',
          amount:0n,quantity:0n};
        prior.amount+=balance*price;
        prior.quantity+=balance;
        goods.set(key,prior);
      });
    }

    // Journal-based GL movement, not a sum of invoice faces. Settlements,
    // reversals and credits affect the proper accounts automatically.
    // Fiscal close journals only transfer accumulated P&L to equity and must
    // not erase operational revenue/expense turnover.
    let revenue=0n,expenses=0n;
    for(const journal of view.journals){
      if(!record(journal)||!Array.isArray(journal.lines))
        throw new Error('ساختار سند دفترکل نامعتبر است.');
      const posted=validPostingDate(journal.date,'دفترکل');
      if(!inside(posted)||journal.sourceType==='fiscal.year.close')continue;
      for(const line of journal.lines){
        if(!record(line))throw new Error('سطر سند دفترکل نامعتبر است.');
        const account=view.accounts[line.accountId];
        if(!record(account))throw new Error('سرفصل سند دفترکل یافت نشد.');
        const dr=money(line.debit,'بدهکار دفترکل'),cr=money(line.credit,'بستانکار دفترکل');
        if(account.kind==='revenue')revenue+=cr-dr;
        if(account.kind==='expense')expenses+=dr-cr;
      }
    }
    const net=revenue-expenses;
    const ranked=[...goods.values()].sort(byAmountThenName).slice(0,8).map(item=>({
      key:item.key,itemId:item.itemId,name:item.name,kind:item.kind,
      quantity:asNumber(item.quantity),
      unit:item.unit,salesAmount:asNumber(item.amount)}));

    // Only new operational cheques are guaranteed by the accounting core.
    // Parsian archival/imported cheque tables are deliberately NOT read.
    const reminders=[];
    if(today){
      const base=daysFrom(today);
      for(const [id,cheque] of entries(view.cheques)){
        if(!record(cheque)||!['issued','received','deposited','endorsed','returned']
          .includes(cheque.status))continue;
        const due=validPostingDate(cheque.dueDate,'چک '+id);
        const distance=daysFrom(due)-base;
        if(distance>7&&cheque.status!=='returned')continue;
        const status=cheque.status==='returned'?'returned':
          distance<0?'overdue':distance===0?'today':'upcoming';
        reminders.push({id:'cheque:'+id,
          title:(cheque.direction==='payment'?'چک پرداختنی':'چک دریافتنی')+
            ' '+(cheque.reference||id),
          subtitle:(cheque.direction==='payment'?'پرداخت':'دریافت')+
            ' | '+unit+' '+asNumber(money(cheque.amount,'چک '+id)).toLocaleString('fa-IR')+
            (cheque.status==='returned'?' | برگشتی':''),
          date:due,status,navigate:'cheques'});
      }
      const priority={returned:0,overdue:1,today:2,upcoming:3};
      reminders.sort((a,b)=>priority[a.status]-priority[b.status]||
        a.date.localeCompare(b.date)||a.id.localeCompare(b.id));
    }

    const minMonth=from?monthOf(from):null,maxMonth=to?monthOf(to):null;
    let first=minMonth?monthIndex(minMonth):null;
    let last=maxMonth?monthIndex(maxMonth):null;
    for(const key of monthly.keys()){
      const n=monthIndex(key);
      first=first===null?n:Math.min(first,n);
      last=last===null?n:Math.max(last,n);
    }
    // No artificial sales are made when a period contains no invoices.
    if(first===null&&last!==null)first=last;
    if(last===null&&first!==null)last=first;
    if(first!==null&&last-first>=120)
      throw new Error('بازه نمودار ماهانه باید حداکثر ۱۲۰ ماه باشد.');
    const monthData=[];
    if(first!==null)for(let index=first;index<=last;index++){
      const label=monthAt(index);
      monthData.push({label,value:asNumber(monthly.get(label)||0n)});
    }
    const numbers={
      sales:asNumber(sales),revenue:asNumber(revenue),
      expenses:asNumber(expenses),net:asNumber(net)};
    const warnings=[
      'فروش، خالص فاکتورهای دارای وضعیت صادرشده است؛ برگشت جزئی به ماه صدور اصلی اعمال می‌شود.',
      'گردش درآمد و هزینه از دفترکل و تاریخ ثبت سند محاسبه می‌شود و لزوماً با جمع فاکتورها برابر نیست.',
      'فروش کالا و خدمت از مبالغ ناخالص ردیف‌های فاکتور است؛ مالیات و تخفیف تسهیم نشده‌اند.',
      'بدون تأیید کامل بهای تمام‌شده نمی‌توان سود عملیاتی قطعی را گزارش کرد.',
    ];
    if(!today)warnings.push('تاریخ امروز ارائه نشده است؛ یادآور چک محاسبه نشد.');
    return {error:'',currency,unit,range:{from,to,today},
      kpis:[
        {id:'sales',label:'فروش صادرشده خالص',value:numbers.sales,unit,navigate:'invoices'},
        {id:'revenue',label:'درآمد ثبت‌شده دفترکل',value:numbers.revenue,unit,navigate:'reports'},
        {id:'expenses',label:'هزینه ثبت‌شده دفترکل',value:numbers.expenses,unit,navigate:'reports'},
        {id:'net',label:'تراز درآمد و هزینه ثبت‌شده (غیرقطعی)',value:numbers.net,
          unit,navigate:'reports'},
        {id:'dueCheques',label:'چک‌های نیازمند توجه',value:reminders.length,
          unit:'فقره',navigate:'cheques'},
      ],
      charts:[
        {id:'monthlySales',title:'فروش خالص صادرشده به تفکیک ماه',
          type:'line',data:monthData,unit,navigate:'invoices'},
        {id:'ledgerPerformance',title:'درآمد و هزینه ثبت‌شده در دفترکل',
          type:'bar',data:[
            {label:'درآمد',value:numbers.revenue},
            {label:'هزینه',value:numbers.expenses},
            {label:'تراز',value:numbers.net}],unit,navigate:'reports'},
        {id:'topProducts',title:'کالاها و خدمات پرفروش (ناخالص سطری)',
          type:'bar',data:ranked.map(x=>({label:x.name,value:x.salesAmount})),
          unit,navigate:'items'},
      ],reminders,topProducts:ranked,
      salesDocumentCount:salesCount,
      costData:{available:false,
        reason:'داده بهای تمام‌شدهٔ همه فروش‌ها کامل و تأییدشده نیست؛ نتیجه دفترکل معادل سود قطعی نیست.'},
      warnings};
  }catch(error){
    return {...empty,error:error instanceof Error?error.message:
      'داده حسابداری برای تحلیل معتبر نیست.'};
  }
}
