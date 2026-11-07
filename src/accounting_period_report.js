/**
 * Reproducible read-only account turnover. No implicit journal posting.
 * Dates are canonical ISO calendar dates; Persian conversion belongs at UI edge.
 * Balances use debit minus credit; negative means a credit balance.
 */
const canonicalDate=value=>{
  if(value===''||value===null||value===undefined)return '';
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
  const d=new Date(value+'T00:00:00Z');
  return !Number.isNaN(d.getTime())&&d.toISOString().slice(0,10)===value?value:null;
};
const exactNumber=value=>{
  if(!Number.isSafeInteger(value)||value<0)throw Error('Invalid journal amount');
  return BigInt(value);
};
const asSafeNumber=n=>{
  if(n>BigInt(Number.MAX_SAFE_INTEGER)||n< -BigInt(Number.MAX_SAFE_INTEGER))
    throw Error('Account balance exceeds exact safe integer');
  return Number(n);
};

export function accountingPeriodRows(view,{fromDate='',toDate='',accountId=''}={}){
  const start=canonicalDate(fromDate),end=canonicalDate(toDate);
  if(start===null||end===null||(start&&end&&start>end))
    return {error:'بازه تاریخ گزارش معتبر نیست.'};
  if(!view||!view.accounts||!Array.isArray(view.journals))
    return {error:'اطلاعات قابل اتکایی از دفترکل در دسترس نیست.'};
  if(accountId&&!Object.prototype.hasOwnProperty.call(view.accounts,accountId))
    return {error:'کد حساب انتخاب‌شده معتبر نیست.'};
  try{
    const map=new Map(Object.entries(view.accounts).filter(([id])=>
      !accountId||id===accountId).map(([id,a])=>[id,{
        accountId:id,name:a.name,kind:a.kind,opening:0n,
        debit:0n,credit:0n,
      }]));
    let journalCount=0;
    const ordered=[...view.journals].map((j,i)=>({j,i})).sort((a,b)=>
      a.j.date.localeCompare(b.j.date)||a.i-b.i);
    for(const {j} of ordered){
      const day=canonicalDate(j?.date);
      if(!day||!Array.isArray(j.lines))throw Error('Invalid historical journal');
      if(end&&day>end)continue;
      let included=false;
      for(const line of j.lines){
        const a=map.get(line.accountId);
        if(!a)continue;
        included=true;
        const dr=exactNumber(line.debit),cr=exactNumber(line.credit);
        if(start&&day<start)a.opening+=dr-cr;
        else{a.debit+=dr;a.credit+=cr;}
      }
      if(included&&(!start||day>=start))journalCount++;
    }
    const rows=[...map.values()].map(a=>{
      const close=a.opening+a.debit-a.credit;
      return {accountId:a.accountId,name:a.name,kind:a.kind,
        openingSigned:asSafeNumber(a.opening),
        openingDebit:asSafeNumber(a.opening>0n?a.opening:0n),
        openingCredit:asSafeNumber(a.opening<0n?-a.opening:0n),
        debitMovement:asSafeNumber(a.debit),creditMovement:asSafeNumber(a.credit),
        closingSigned:asSafeNumber(close),
        closingDebit:asSafeNumber(close>0n?close:0n),
        closingCredit:asSafeNumber(close<0n?-close:0n)};
    }).filter(a=>a.openingSigned||a.debitMovement||a.creditMovement||a.closingSigned);
    return {error:'',fromDate:start,throughDate:end,accountId,
      journalCount,rows,
      periodDebit:asSafeNumber(rows.reduce((a,r)=>a+BigInt(r.debitMovement),0n)),
      periodCredit:asSafeNumber(rows.reduce((a,r)=>a+BigInt(r.creditMovement),0n))};
  }catch(_e){
    return {error:'گزارش قابل اتکا نیست؛ یکی از اسناد یا مبالغ دفترکل نامعتبر است.'};
  }
}
