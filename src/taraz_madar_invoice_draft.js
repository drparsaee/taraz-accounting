/**
 * An untrusted local Madar proposal can suggest an IN-MEMORY invoice row only.
 * It cannot select an official party, item, ledger account, tax policy, amount,
 * approval or financial status, and never calls the accounting command API.
 */
const REQUEST_ID=/^[0-9a-f]{32}$/;

export function madarProposalInvoiceSuggestion(item){
  if(!item||typeof item!=='object'||Array.isArray(item)||
     item.schema!==1||item.source!=='madar'||
     typeof item.id!=='string'||!REQUEST_ID.test(item.id)||
     typeof item.taskId!=='string'||!item.taskId.trim()||item.taskId.length>180||
     typeof item.projectId!=='string'||!item.projectId.trim()||item.projectId.length>180||
     typeof item.title!=='string'||!item.title.trim()||item.title.length>300||
     /[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]/.test(item.title)){
    throw Error('ارجاع مدار برای پیشنهاد پیش‌نویس معتبر نیست.');
  }
  return Object.freeze({
    sourceId:item.id,
    row:Object.freeze({description:item.title.trim(),quantity:'1',
      unitPrice:'',accountId:'',itemId:''}),
    note:'پیشنهاد محلی مدار (منبع مالی تأییدنشده؛ ثبت رسمی نیست)، شناسه: '+item.id,
  });
}
