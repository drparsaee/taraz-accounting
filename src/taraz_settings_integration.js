/** Strictly the native inbox metadata bridge; these operations never call a ledger command. */
export function integrationCapabilities(api){
  return {
    canList:typeof api?.tarazIntegrationList==='function',
    canReview:typeof api?.tarazIntegrationReview==='function',
    canRecover:typeof api?.tarazIntegrationRecover==='function'
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
    pendingTruncated:result.pendingTruncated===true,
    requests:result.requests.filter(item=>item&&typeof item.id==='string'&&
      typeof item.title==='string'&&typeof item.taskId==='string'),
    recoveryInvalidCount:Number.isSafeInteger(result.recoveryInvalidCount)&&result.recoveryInvalidCount>=0?result.recoveryInvalidCount:0,
    recoveryTruncated:result.recoveryTruncated===true,
    recovery:Array.isArray(result.recovery)?result.recovery.filter(item=>item&&
      /^[0-9a-f]{32}$/.test(item.id)&&typeof item.taskId==='string'&&
      typeof item.title==='string'&&['reviewed','rejected'].includes(item.state)&&
      item.financialEventCreated===false):[]
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

export async function recoverTarazIntegration(api,id,expectedDecision){
  if(!integrationCapabilities(api).canRecover)throw Error('بازیابی تصمیم در این میزبان در دسترس نیست.');
  if(typeof id!=='string'||!/^[0-9a-f]{32}$/.test(id)||
    !['reviewed','rejected'].includes(expectedDecision))throw Error('شناسه یا تصمیم بازیابی معتبر نیست.');
  // The native side must re-read the durable intent, not accept a browser-supplied decision.
  const answer=await api.tarazIntegrationRecover(id,true);
  if(answer?.id!==id||answer?.state!==expectedDecision||answer?.financialEventCreated!==false)
    throw Error('نتیجه بازیابی با تصمیم پایدار بدون ثبت مالی سازگار نیست.');
  return answer;
}
