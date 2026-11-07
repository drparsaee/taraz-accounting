/** Strictly the native inbox metadata bridge; these operations never call a ledger command. */
export function integrationCapabilities(api){
  return {
    canList:typeof api?.tarazIntegrationList==='function',
    canReview:typeof api?.tarazIntegrationReview==='function'
  };
}
export async function listTarazIntegration(api){
  if(!integrationCapabilities(api).canList)throw Error('خواندن ارجاع‌های مدار در این میزبان در دسترس نیست.');
  const result=await api.tarazIntegrationList();
  if(!result||typeof result!=='object'||typeof result.connected!=='boolean'||
    !Array.isArray(result.requests))throw Error('پاسخ وضعیت اتصال معتبر نیست.');
  return {
    connected:result.connected,
    invalidCount:Number.isSafeInteger(result.invalidCount)&&result.invalidCount>=0?result.invalidCount:0,
    requests:result.requests.filter(item=>item&&typeof item.id==='string'&&
      typeof item.title==='string'&&typeof item.taskId==='string')
  };
}
export async function reviewTarazIntegration(api,id,decision){
  if(!integrationCapabilities(api).canReview)throw Error('بررسی ارجاع در این میزبان در دسترس نیست.');
  if(typeof id!=='string'||!id||!['reviewed','rejected'].includes(decision)){
    throw Error('شناسه یا تصمیم ارجاع معتبر نیست.');
  }
  const answer=await api.tarazIntegrationReview(id,decision);
  if(answer?.id!==id||answer?.state!==decision||answer?.financialEventCreated!==false){
    throw Error('نتیجه بررسی با قرارداد بدون ثبت مالی سازگار نیست.');
  }
  return answer;
}
