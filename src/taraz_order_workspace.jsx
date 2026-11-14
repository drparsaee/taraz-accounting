import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {Check,ChevronDown,ClipboardList,Plus,RefreshCw,Save,Trash2} from 'lucide-react';
import {extractLocalOrderHints} from './taraz_order_intake.js';
import './taraz_order_workspace.css';

const STATUS={
  draft:'پیش‌نویس',approved:'تأییدشده',
  in_production:'در حال انجام',delivered:'تحویل‌شده',cancelled:'لغوشده',
};
const NEXT={
  draft:[['approved','تأیید سفارش'],['cancelled','لغو سفارش']],
  approved:[['in_production','شروع اجرا'],['cancelled','لغو سفارش']],
  in_production:[['delivered','ثبت تحویل'],['cancelled','لغو سفارش']],
};
const STAGES=[
  ['print','چاپ'],['bindery','صحافی'],['sewing','دوخت'],['laser','لیزر'],
  ['packaging','بسته‌بندی'],['shipping','حمل'],
  ['material','مواد اولیه'],['other','سایر خدمات'],
];
const EMPTY=()=>({
  kind:'sale',customerId:'',customerName:'',title:'',description:'',
  unit:'عدد',quantity:'',productionQuantity:'',unitPrice:'',
  actualProducedQuantity:'',scrapQuantity:'',healthySurplusQuantity:'',
  projectReference:'',scheduleStartDate:'',scheduleDueDate:'',procurementNotes:'',
  costStages:[],notes:'',
});
const ascii=s=>String(s??'').replace(/[۰-۹]/g,d=>String(d.charCodeAt(0)-1776))
  .replace(/[٠-٩]/g,d=>String(d.charCodeAt(0)-1632))
  .replace(/[٬,]/g,'').trim();
function asInt(s,{allowEmpty=false,zero=false,max=10000000}={}){
  const value=ascii(s);
  if(allowEmpty&&!value)return null;
  if(!/^(?:0|[1-9][0-9]*)$/.test(value)||value.length>18)return undefined;
  const n=Number(value);
  if(!Number.isSafeInteger(n)||n>max||n<(zero?0:1))return undefined;
  return n;
}
function clientId(){
  const c=globalThis.crypto;
  if(!c?.getRandomValues)throw Error('Secure browser randomness unavailable');
  const bytes=new Uint8Array(16);
  c.getRandomValues(bytes);
  return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}
const dateOk=value=>!value||(/^\d{4}-\d{2}-\d{2}$/.test(value)&&
  !Number.isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value);
const localToday=()=>{
  const date=new Date();
  return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),
    String(date.getDate()).padStart(2,'0')].join('-');
};
const emptyMadarCredentials=()=>({url:'',fingerprint:'',username:'',password:''});

/** Accept only an authenticated, ACL-filtered host page with actual project IDs. */
export function verifyMadarProjectPage(page,offset=0){
  if(!page||page.connected!==true||page.scope!=='projects'||
    page.offset!==offset||page.limit!==50||
    page.financialEventCreated!==false||
    !page.source||page.source.kind!=='madar-authorized-host-state-projection'||
    page.source.serverAclApplied!==true||page.source.readOnly!==true||
    !/^[a-f0-9]{64}$/.test(page.source.revision||'')||
    typeof page.source.actor!=='string'||!page.source.actor.trim()||
    !Array.isArray(page.items?.projects)||page.items.projects.length>50||
    !Number.isSafeInteger(page.counts?.projects)||page.counts.projects<offset+page.items.projects.length||
    typeof page.more?.projects!=='boolean'){
    return {error:'پاسخ پروژه‌های احراز هویت‌شده مدار معتبر نیست.'};
  }
  const found=new Set();
  const projects=[];
  for(const record of page.items.projects){
    if(!record||typeof record!=='object'||Array.isArray(record))
      return {error:'رکورد پروژه مدار معتبر نیست.'};
    const id=record.id;
    const title=typeof record.name==='string'&&record.name.trim()?record.name.trim():
      typeof record.title==='string'?record.title.trim():'';
    if(typeof id!=='string'||!id||id.length>120||/[\x00-\x1f\x7f]/.test(id)||
      !title||title.length>2048||/[\x00-\x1f\x7f]/.test(title)||found.has(id))
      return {error:'شناسه یا عنوان پروژه مدار قابل تأیید نیست.'};
    found.add(id);
    projects.push({id,name:title});
  }
  return {projects,offset,more:page.more.projects,actor:page.source.actor,
    revision:page.source.revision,readUtc:page.source.readUtc||''};
}

export function orderProductionReview(form){
  const required=asInt(form.quantity);
  const actual=asInt(form.actualProducedQuantity,{allowEmpty:true,zero:true});
  const scrap=asInt(form.scrapQuantity,{allowEmpty:true,zero:true});
  const surplus=asInt(form.healthySurplusQuantity,{allowEmpty:true,zero:true});
  if([actual,scrap,surplus].includes(undefined))
    return {state:'invalid',balance:null,message:'مقادیر تولید واقعی، ضایعات و مازاد باید عدد صحیح غیرمنفی باشند.'};
  if(actual!=null&&((scrap!=null&&scrap>actual)||
    (surplus!=null&&surplus>actual)||(scrap!=null&&surplus!=null&&scrap+surplus>actual)))
    return {state:'invalid',balance:null,message:'مجموع ضایعات و مازاد سالم نمی‌تواند از تولید واقعی بیشتر باشد.'};
  const missing=[
    ['actualProducedQuantity','تولید واقعی'],['scrapQuantity','ضایعات واقعی'],
    ['healthySurplusQuantity','مازاد سالم'],
  ].filter(([key])=>asInt(form[key],{allowEmpty:true,zero:true})===null)
    .map(([,label])=>label);
  if(missing.length)return {state:'incomplete',balance:null,missing,
    message:`برای تراز تولید، ${missing.join('، ')} را مشخص کنید. خالی با صفر تفاوت دارد.`};
  if(required===undefined)return {state:'invalid',balance:null,message:'ابتدا تعداد سفارش را وارد کنید.'};
  const balance=actual-scrap-surplus-required;
  if(balance<0)return {state:'shortfall',balance,
    message:`${Math.abs(balance).toLocaleString('fa-IR')} واحد سالم از تعهد سفارش هنوز تأمین نشده است.`};
  if(balance>0)return {state:'unallocated',balance,
    message:`${balance.toLocaleString('fa-IR')} واحد تولیدشده هنوز بین سفارش، ضایعات و مازاد سالم تعیین تکلیف نشده است.`};
  return {state:'balanced',balance:0,
    message:'تراز برقرار است: تولید واقعی = سفارش + ضایعات + مازاد سالم.'};
}
export function prepareTarazOrderDraft(form,currency='RIAL'){
  if(!['RIAL','TOMAN'].includes(currency))return {error:'واحد پول دفتر نامعتبر است.'};
  const quantity=asInt(form.quantity);
  const production=asInt(form.productionQuantity);
  if(!form.title?.trim()||form.title.trim().length>200)
    return {error:'شرح سفارش را وارد کنید.'};
  if(!form.customerName?.trim()&&!form.customerId?.trim())
    return {error:'نام مشتری یا تأمین‌کننده را وارد کنید.'};
  if(!form.unit?.trim())return {error:'واحد کالا یا خدمت را وارد کنید.'};
  if(quantity===undefined||production===undefined)
    return {error:'تعداد سفارش و تعداد برنامه‌ریزی تولید باید عدد صحیح مثبت باشند.'};
  if(form.kind==='sale'&&production<quantity)
    return {error:'تعداد تولید نمی‌تواند از تعداد فروش کمتر باشد.'};
  const actualProducedQuantity=asInt(form.actualProducedQuantity,{allowEmpty:true,zero:true});
  const scrapQuantity=asInt(form.scrapQuantity,{allowEmpty:true,zero:true});
  const healthySurplusQuantity=asInt(form.healthySurplusQuantity,{allowEmpty:true,zero:true});
  const review=orderProductionReview(form);
  if(review.state==='invalid')return {error:review.message};
  if(!dateOk(form.scheduleStartDate)||!dateOk(form.scheduleDueDate)||
    (form.scheduleStartDate&&form.scheduleDueDate&&form.scheduleStartDate>form.scheduleDueDate))
    return {error:'بازه زمان‌بندی پروژه نامعتبر است.'};
  if(String(form.projectReference||'').length>120||String(form.procurementNotes||'').length>2000)
    return {error:'ارجاع پروژه یا جزئیات تأمین بیش از حد مجاز است.'};
  const unitPrice=asInt(form.unitPrice,{allowEmpty:true,zero:true,max:1e15});
  if(unitPrice===undefined)return {error:'قیمت واحد نامعتبر است. برای قیمت نامشخص، آن را خالی بگذارید.'};
  if(unitPrice!=null&&unitPrice*quantity>1e15)
    return {error:'جمع قیمت پیشنهادی از سقف معتبر بیشتر است.'};
  if(!['sale','purchase'].includes(form.kind))return {error:'نوع سفارش معتبر نیست.'};
  const stages=[];
  if(form.costStages.length>24)return {error:'حداکثر ۲۴ مرحله هزینه مجاز است.'};
  for(const stage of form.costStages){
    if(!STAGES.some(([k])=>k===stage.kind))
      return {error:'نوع یکی از مراحل تولید معتبر نیست.'};
    const estimatedCost=asInt(stage.estimatedCost,{allowEmpty:true,zero:true,max:1e15});
    if(estimatedCost===undefined)return {error:'هزینه تخمینی یکی از مراحل نامعتبر است.'};
    stages.push({kind:stage.kind,supplier:String(stage.supplier||'').trim(),
      description:String(stage.description||'').trim(),estimatedCost});
  }
  return {data:{
    kind:form.kind,customerId:String(form.customerId||'').trim(),
    customerName:String(form.customerName||'').trim(),
    title:form.title.trim(),description:String(form.description||'').trim(),
    unit:String(form.unit).trim(),quantity,productionQuantity:production,
    actualProducedQuantity,scrapQuantity,healthySurplusQuantity,
    unitPrice,currency,costStages:stages,notes:String(form.notes||'').trim(),
    projectReference:String(form.projectReference||'').trim(),
    scheduleStartDate:String(form.scheduleStartDate||''),
    scheduleDueDate:String(form.scheduleDueDate||''),
    procurementNotes:String(form.procurementNotes||'').trim(),
  }};
}
export function orderCompleteness(form){
  const fields=[];
  if(!form.title?.trim())fields.push('شرح سفارش');
  if(!form.customerName?.trim()&&!form.customerId?.trim())fields.push('طرف حساب');
  if(asInt(form.quantity)===undefined)fields.push('تعداد سفارش');
  if(asInt(form.productionQuantity)===undefined)fields.push('تعداد تولید');
  return fields;
}
const formatAmount=n=>n==null?'هنوز تعیین نشده':Number(n).toLocaleString('fa-IR');
const emptyStage=()=>({kind:'print',supplier:'',description:'',estimatedCost:''});
const paymentSeed=kind=>({
  direction:kind==='purchase'?'outgoing':'incoming',amount:'',
  paymentDate:new Date().toISOString().slice(0,10),party:'',
  method:'',transactionReference:'',status:'recorded',
});
const financialDisplay=value=>value==null?'نامشخص':Number(value).toLocaleString('fa-IR');
const AGENT_ACTIONS={
  request_measured_quantities:'تولید واقعی، پرت واقعی و مازاد سالم را اندازه‌گیری و ثبت کنید.',
  review_actual_costs:'هزینه واقعی تمام مراحل را با مستندات بررسی و تأیید کنید.',
  verify_agreed_amount:'مبلغ توافق‌شده هنوز نامشخص است؛ آن را از طرف حساب بپرسید.',
  review_remaining_settlement:'مانده تسویه‌شده کمتر از مبلغ توافق‌شده است؛ وضعیت پرداخت‌ها را بررسی کنید.',
};

export default function TarazOrderWorkspace({api,canEdit=false,canAdmin=false,currency='RIAL'}){
  const [items,setItems]=useState([]);
  const [form,setForm]=useState(EMPTY);
  const [active,setActive]=useState(null);
  const [mode,setMode]=useState('simple');
  const [costDrafts,setCostDrafts]=useState({});
  const [paymentDraft,setPaymentDraft]=useState(()=>paymentSeed('sale'));
  const [paymentMethods,setPaymentMethods]=useState({});
  const [settlementRefs,setSettlementRefs]=useState({});
  const [financeDocumentDate,setFinanceDocumentDate]=useState(
    ()=>new Date().toISOString().slice(0,10));
  const [financeDraftOutcome,setFinanceDraftOutcome]=useState(null);
  const [agentReview,setAgentReview]=useState(null);
  const [agentMemory,setAgentMemory]=useState(null);
  const [agentDraft,setAgentDraft]=useState('');
  const [agentQuery,setAgentQuery]=useState('');
  const [agentNatural,setAgentNatural]=useState(null);
  const [agentBusy,setAgentBusy]=useState(false);
  const [agentError,setAgentError]=useState('');
  const [agentNotice,setAgentNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [ecosystemStatus,setEcosystemStatus]=useState(null);
  const [ecosystemBusy,setEcosystemBusy]=useState(false);
  const [ecosystemError,setEcosystemError]=useState('');
  const [dirty,setDirty]=useState(false);
  const [filter,setFilter]=useState('all');
  const [requestText,setRequestText]=useState('');
  const [requestHints,setRequestHints]=useState(null);
  const [suggestionBusy,setSuggestionBusy]=useState(false);
  const [madarConsent,setMadarConsent]=useState(false);
  const [madarCredentials,setMadarCredentials]=useState(emptyMadarCredentials);
  const [madarPage,setMadarPage]=useState(null);
  const [madarSelectedId,setMadarSelectedId]=useState('');
  const [madarBound,setMadarBound]=useState(null);
  const [madarLinkStatus,setMadarLinkStatus]=useState(null);
  const [madarLinkBusy,setMadarLinkBusy]=useState(false);
  const [madarLinkError,setMadarLinkError]=useState('');
  const [madarSyncPreview,setMadarSyncPreview]=useState(null);
  const [madarProgress,setMadarProgress]=useState(null);
  const [madarSyncHistory,setMadarSyncHistory]=useState(null);
  const [madarSyncBusy,setMadarSyncBusy]=useState(false);
  const [madarSyncNotice,setMadarSyncNotice]=useState('');
  const [madarSyncError,setMadarSyncError]=useState('');
  const [madarError,setMadarError]=useState('');
  const [madarBusy,setMadarBusy]=useState(false);
  const madarGeneration=useRef(0);
  const opRef=useRef(null);
  const live=useRef(true);
  const ready=typeof api?.tarazOrderList==='function'&&
    typeof api?.tarazOrderCommand==='function';
  const money=currency==='TOMAN'?'تومان':'ریال';
  useEffect(()=>{live.current=true;return()=>{live.current=false;madarGeneration.current++;};},[]);
  const refresh=useCallback(async()=>{
    if(!ready){setLoading(false);return false;}
    setLoading(true);
    try{
      const output=await api.tarazOrderList(0,100);
      if(!live.current)return false;
      if(!output||!Array.isArray(output.orders)||output.financialEventCreated!==false)
        throw Error('Untrusted order result');
      setItems(output.orders.map(order=>({...order})));
      setError('');
      return true;
    }catch(_error){
      if(live.current)setError('بازخوانی سفارش‌ها ناموفق بود. وضعیت دفتر را بررسی کنید.');
      return false;
    }finally{if(live.current)setLoading(false);}
  },[api,ready]);
  useEffect(()=>{void refresh();},[refresh]);
  const inspectEcosystem=async()=>{
    if(ecosystemBusy||typeof api?.tarazEcosystemStatus!=='function'||
      typeof api?.tarazAiProviderStatus!=='function')return;
    setEcosystemBusy(true);setEcosystemError('');
    try{
      const [system,ai]=await Promise.all([
        api.tarazEcosystemStatus(),api.tarazAiProviderStatus(),
      ]);
      if(system?.schemaVersion!==1||system.product!=='TARAZ'||
        system.readOnly!==true||system.financialEventCreated!==false||
        system.source!=='LOCAL_AUTHENTICATED_TARAZ'||
        system.outbox?.remoteSenderAvailable!==false||
        ai?.modelRan!==false||ai.enabledForActions!==false||
        ai.coreCommercialFeaturesAvailable!==true)
        throw Error('Untrusted ecosystem capability response');
      if(live.current)setEcosystemStatus({system,ai});
    }catch(_error){
      if(live.current){setEcosystemStatus(null);
        setEcosystemError('وضعیت اتصال یا AI به شکل معتبر قابل خواندن نبود.');}
    }finally{if(live.current)setEcosystemBusy(false);}
  };
  const update=(field,value)=>{
    setForm(prev=>({...prev,[field]:value}));setDirty(true);
    setMadarSyncPreview(null);
    setMadarProgress(null);
    setMadarSyncHistory(null);
    if(field==='projectReference'){
      setMadarBound(null);setMadarLinkStatus(null);setMadarSyncPreview(null);
    }
    opRef.current=null;setError('');setNotice('');
  };
  const clearMadarPage=()=>{
    madarGeneration.current++;
    setMadarPage(null);setMadarSelectedId('');setMadarError('');setMadarBusy(false);
    setMadarSyncPreview(null);setMadarSyncError('');
    setMadarProgress(null);
    setMadarSyncHistory(null);
  };
  const readMadarProjects=async(offset=0)=>{
    if(!madarConsent||madarBusy||!canEdit||!canAdmin||
      typeof api?.tarazMadarDataRead!=='function')return;
    const request=++madarGeneration.current;
    setMadarBusy(true);setMadarError('');setMadarPage(null);setMadarSelectedId('');
    setMadarSyncPreview(null);setMadarSyncError('');
    try{
      const page=await api.tarazMadarDataRead('projects',offset,50,true,
        {...madarCredentials},'host');
      const verified=verifyMadarProjectPage(page,offset);
      if(verified.error)throw Error('Invalid authenticated project page');
      if(live.current&&request===madarGeneration.current)setMadarPage(verified);
    }catch(_error){
      if(live.current&&request===madarGeneration.current)
        setMadarError('خواندن پروژه‌های مدار انجام نشد؛ مجوز مدیر تراز، اطلاعات ورود مدار و گواهی HTTPS را بررسی کنید.');
    }finally{
      if(live.current&&request===madarGeneration.current)setMadarBusy(false);
    }
  };
  const applyMadarProject=()=>{
    if(!madarConsent||!canEdit||!canAdmin||busy||
      !madarPage)return;
    const selected=madarPage.projects.find(project=>project.id===madarSelectedId);
    if(!selected){setMadarError('ابتدا پروژه‌ای از فهرست تأییدشده انتخاب کنید.');return;}
    if(active&&active.status!=='draft'&&active.projectReference!==selected.id){
      setMadarError('ارجاع پروژه سفارش قطعی را نمی‌توان بدون اصلاح مجاز تغییر داد.');
      return;
    }
    if(active&&active.projectReference===selected.id&&
      form.projectReference===selected.id){
      // Refreshing an established reference is not an order mutation.
      // Crucial for post-delivery re-attestation against current Madar state.
      setMadarBound({...selected,actor:madarPage.actor,revision:madarPage.revision});
      setMadarSyncPreview(null);setMadarLinkError('');setMadarLinkStatus(null);
      setNotice('ارجاع موجود از میزبان مجاز بازخوانی شد؛ سفارش یا دفتر مالی تغییر نکرد.');
      return;
    }
    setForm(prev=>({...prev,projectReference:selected.id}));
    setMadarBound({...selected,actor:madarPage.actor,revision:madarPage.revision});
    setMadarLinkStatus(null);setMadarLinkError('');setMadarSyncPreview(null);
    setDirty(true);opRef.current=null;setError('');
    setNotice('شناسه واقعی پروژه از پاسخ احراز هویت‌شده مدار در فرم قرار گرفت؛ ذخیره سفارش جداگانه است.');
  };
  const readMadarOrderLink=async()=>{
    if(!active||madarLinkBusy||!canAdmin||
      typeof api?.tarazOrderMadarLinkRead!=='function')return null;
    setMadarLinkBusy(true);setMadarLinkError('');
    try{
      const data=await api.tarazOrderMadarLinkRead(active.id);
      if(!data||data.readOnly!==true||data.hostMembershipRechecked!==false)
        throw Error('Untrusted stored Madar link');
      setMadarLinkStatus(data);
      return data;
    }catch(_error){
      setMadarLinkStatus(null);
      setMadarLinkError('اطلاعات پیوند محلی بازخوانی نشد؛ از وجود پیوند نتیجه نگیرید.');
      return null;
    }finally{if(live.current)setMadarLinkBusy(false);}
  };
  const verifyAndBindMadar=async()=>{
    const selected=madarPage?.projects?.find(project=>project.id===madarBound?.id);
    if(!active||dirty||busy||!canAdmin||!madarConsent||madarLinkBusy||
      !selected||active.projectReference!==selected.id||
      typeof api?.tarazOrderMadarLink!=='function'||
      typeof api?.tarazOrderMadarLinkRead!=='function')return;
    setMadarLinkBusy(true);setMadarLinkError('');
    try{
      const prior=await api.tarazOrderMadarLinkRead(active.id);
      if(!prior||prior.readOnly!==true)throw Error('Cannot read link CAS');
      const prompt='تأیید پیوند خواندنی پروژه «'+selected.name+
        '» با سفارش '+active.id+'؟ تراز هویت و عضویت پروژه را دوباره از HTTPS مدار'+
        ' بررسی می‌کند؛ هیچ داده‌ای روی مدار نوشته نمی‌شود.';
      if(!globalThis.confirm(prompt))return;
      const result=await api.tarazOrderMadarLink({
        orderId:active.id,expectedOrderRevision:active.revision,
        projectId:selected.id,pageOffset:madarPage.offset,
        expectedLinkRevision:prior.link?.revision||0,
        connection:{...madarCredentials},explicitConsent:true,
        idempotencyKey:clientId(),
      });
      if(result?.status!=='VERIFIED_READ_ONLY_MADAR_LINK'||
        result.orderId!==active.id||result.projectId!==selected.id||
        result.orderRevision!==active.revision||
        result.serverAclApplied!==true||result.hostAuthenticated!==true||
        result.madarWritePerformed!==false||result.financialEventCreated!==false)
        throw Error('Madar verified link result unavailable');
      const persisted=await api.tarazOrderMadarLinkRead(active.id);
      if(persisted?.currentOrderMatches!==true||
        persisted?.link?.revision!==result.linkRevision||
        persisted.link.project_id!==selected.id||
        persisted.link.host_state_revision!==result.sourceRevision)
        throw Error('Madar link readback mismatch');
      setMadarLinkStatus(persisted);
      setMadarSyncPreview(null);setMadarSyncNotice('');
      setNotice('پیوند دارای منشأ مدار در تراز ذخیره شد؛ مدار تغییر نکرده است.');
    }catch(_error){
      setMadarLinkError('پیوند تأیید نشد. هویت HTTPS، مجوز پروژه و Revision را مجدداً بررسی کنید.');
      setMadarLinkStatus(null);
    }finally{if(live.current)setMadarLinkBusy(false);}
  };
  const previewMadarOrderSync=async()=>{
    if(!active||dirty||busy||madarSyncBusy||madarLinkBusy||!canAdmin||
      !madarConsent||
      madarLinkStatus?.link?.project_id!==active.projectReference||
      typeof api?.tarazMadarOrderPreview!=='function')return;
    setMadarSyncBusy(true);setMadarSyncError('');setMadarSyncNotice('');
    setMadarSyncPreview(null);
    try{
      const result=await api.tarazMadarOrderPreview(
        active.id,active.projectReference,{...madarCredentials},true);
      if(result?.status==='ALREADY_SYNCED'&&
        result.taskId==='taraz-order-'+active.id&&
        result.wroteMadarState===false&&result.financialEventCreated===false){
        setMadarSyncNotice('این سفارش با همین Revision قبلاً در مدار ثبت شده است. عملیات تازه‌ای انجام نشد.');
        return;
      }
      if(result?.status!=='PREVIEW_ONLY'||
        result.taskId!=='taraz-order-'+active.id||
        !/^[a-f0-9]{64}$/.test(result.previewDigest||'')||
        !/^[a-f0-9]{64}$/.test(result.sourceRevision||'')||
        result.taskPreview?.projectId!==active.projectReference||
        result.taskPreview?.tarazOrderSourceId!==active.id||
        result.taskPreview?.tarazOrderSourceRevision!==active.revision||
        result.wroteMadarState!==false||
        result.financialEventCreated!==false)
        throw Error('Madar preview evidence invalid');
      setMadarSyncPreview({...result,orderRevision:active.revision,
        projectId:active.projectReference});
      setMadarSyncNotice('فقط پیش‌نمایش تهیه شد؛ هیچ وظیفه‌ای در مدار ایجاد نشده است.');
    }catch(_error){
      setMadarSyncError('پیش‌نمایش معتبر از مدار دریافت نشد. مجوز و اطلاعات میزبان را بررسی کنید.');
      setMadarSyncPreview(null);
    }finally{if(live.current)setMadarSyncBusy(false);}
  };
  const readMadarStageProgress=async()=>{
    if(!active||dirty||busy||madarSyncBusy||madarLinkBusy||!canAdmin||
      !madarConsent||madarLinkStatus?.link?.project_id!==active.projectReference||
      typeof api?.tarazMadarOrderProgress!=='function')return;
    setMadarSyncBusy(true);setMadarSyncError('');setMadarProgress(null);
    try{
      const progress=await api.tarazMadarOrderProgress(
        active.id,active.projectReference,{...madarCredentials},true);
      if(progress?.source!=='MADAR_AUTHENTICATED_HOST_READ'||
        progress.orderId!==active.id||progress.orderRevision!==active.revision||
        progress.projectId!==active.projectReference||
        progress.readOnly!==true||progress.hostWriteAttempted!==false||
        progress.financialEventCreated!==false||
        !['CURRENT_SOURCE','SOURCE_CHANGED','NOT_SYNCED'].includes(progress.status)||
        !Array.isArray(progress.stages)||
        (progress.status!=='NOT_SYNCED'&&progress.stages.length!==active.costStages.length))
        throw Error('Invalid Madar progress evidence');
      setMadarProgress(progress);
      setMadarSyncNotice('وضعیت مراحل از میزبان احراز هویت‌شده خوانده شد؛ سفارش و مدار تغییر نکردند.');
    }catch(_error){
      setMadarProgress(null);
      setMadarSyncError('وضعیت قابل‌اعتماد مراحل دریافت نشد؛ مجوز، اتصال و پیوند را بررسی کنید.');
    }finally{if(live.current)setMadarSyncBusy(false);}
  };
  const loadMadarSyncHistory=async()=>{
    if(!active||!canAdmin||
      typeof api?.tarazMadarOrderSyncHistory!=='function')return;
    try{
      const result=await api.tarazMadarOrderSyncHistory(active.id);
      if(result?.orderId!==active.id||result.readOnly!==true||
        result.financialEventCreated!==false||
        !Array.isArray(result.entries)||result.entries.length>30)
        throw Error('Untrusted Madar local sync history');
      if(live.current)setMadarSyncHistory(result);
    }catch(_error){
      if(live.current)setMadarSyncHistory(null);
    }
  };
  const recoverMadarSync=async()=>{
    if(!active||busy||dirty||madarSyncBusy||!madarConsent||
      !canAdmin||madarLinkStatus?.link?.project_id!==active.projectReference||
      typeof api?.tarazMadarOrderRecover!=='function')return;
    setMadarSyncBusy(true);setMadarSyncError('');setMadarSyncNotice('');
    setMadarSyncPreview(null);setMadarProgress(null);
    try{
      const result=await api.tarazMadarOrderRecover(
        active.id,active.projectReference,{...madarCredentials},true);
      if(result?.orderId!==active.id||
        result.orderRevision!==active.revision||
        result.wroteMadarState!==false||
        result.financialEventCreated!==false||
        !['RECOVERED_CONFIRMED','REVIEW_REQUIRED'].includes(result.status))
        throw Error('Untrusted sync recovery result');
      setMadarSyncNotice(result.status==='RECOVERED_CONFIRMED'?
        'وظیفهٔ همان نسخهٔ سفارش در مدار مشاهده شد؛ بدون ارسال مجدد، نتیجهٔ نامشخص بازیابی شد.':
        'وظیفه در مدار یافت نشد. هیچ ارسال خودکاری انجام نمی‌شود؛ پیش‌نمایش جدید و تأیید مستقل لازم است.');
    }catch(_error){
      setMadarSyncError('بازیابی وضعیت تأیید نشد. اتصال و گواهی میزبان را بررسی کنید؛ نوشتن دوباره خودکار ممنوع است.');
    }finally{
      if(live.current)setMadarSyncBusy(false);
      void loadMadarSyncHistory();
    }
  };
  const commitMadarOrderSync=async()=>{
    const candidate=madarSyncPreview;
    if(!candidate||!active||busy||dirty||madarSyncBusy||madarLinkBusy||
      !canAdmin||!madarConsent||
      madarLinkStatus?.link?.project_id!==active.projectReference||
      candidate.orderRevision!==active.revision||
      candidate.projectId!==active.projectReference||
      typeof api?.tarazMadarOrderCommit!=='function')return;
    const message='آیا ایجاد یک وظیفه عملیاتی جدید در میزبان واقعی مدار را تأیید می‌کنید؟\n'+
      'سفارش: '+active.id+' | Revision: '+active.revision+'\n'+
      'پروژه: '+candidate.projectId+'\n'+
      'وظیفه: '+candidate.taskPreview.title+'\n'+
      'این عملیات دادهٔ مدار را تغییر می‌دهد؛ تراکنش بانکی یا سند قطعی مالی ایجاد نمی‌کند.';
    if(!globalThis.confirm(message))return;
    setMadarSyncBusy(true);setMadarSyncError('');setMadarSyncNotice('');
    try{
      const result=await api.tarazMadarOrderCommit({
        orderId:active.id,expectedOrderRevision:active.revision,
        projectId:active.projectReference,
        expectedMadarRevision:candidate.sourceRevision,
        previewDigest:candidate.previewDigest,
        explicitConsent:true,manualConfirmation:true,
      },{...madarCredentials});
      if(!['SYNCHRONIZED','ALREADY_SYNCED'].includes(result?.status)||
        result.taskId!==candidate.taskId||
        result.financialEventCreated!==false||
        result.wroteMadarState!==(result.status==='SYNCHRONIZED'))
        throw Error('Madar sync acknowledgement untrusted');
      setMadarSyncPreview(null);
      setMadarSyncNotice(result.status==='SYNCHRONIZED'?
        'میزبان مدار ایجاد وظیفه را تأیید کرد؛ مرجع مالی در تراز باقی ماند.':
        'میزبان مدار پیش‌تر همین وظیفه را داشت؛ ثبت تکراری انجام نشد.');
    }catch(_error){
      setMadarSyncPreview(null);
      setMadarSyncError('نتیجه نوشتن در مدار ممکن است نامشخص باشد. پیش از هر تکرار، وضعیت میزبان را دوباره بخوانید.');
    }finally{
      if(live.current)setMadarSyncBusy(false);
      void loadMadarSyncHistory();
    }
  };
  const stageUpdate=(index,field,value)=>{
    setForm(prev=>({...prev,costStages:prev.costStages.map((s,i)=>
      i===index?{...s,[field]:value}:s)}));
    setDirty(true);opRef.current=null;setMadarSyncPreview(null);
  };
  const applyRequestHints=()=>{
    if(!requestHints?.fields)return;
    setMadarBound(null);
    setMadarSyncHistory(null);
    setMadarLinkStatus(null);setMadarLinkError('');
    setMadarSyncPreview(null);setMadarSyncNotice('');setMadarSyncError('');
    setForm(prev=>{
      const result={...prev};
      for(const key of ['customerName','title','quantity','productionQuantity',
        'actualProducedQuantity','scrapQuantity','healthySurplusQuantity',
        'projectReference','scheduleStartDate','scheduleDueDate','procurementNotes']){
        if(!result[key]&&requestHints.fields[key])result[key]=requestHints.fields[key];
      }
      if(requestHints.fields.unit&&(!result.unit||result.unit==='عدد'))
        result.unit=requestHints.fields.unit;
      const existing=new Set(result.costStages.map(stage=>stage.kind));
      result.costStages=[
        ...result.costStages,
        ...(requestHints.suggestedStages||[]).filter(kind=>!existing.has(kind))
          .slice(0,Math.max(0,24-result.costStages.length))
          .map(kind=>({...emptyStage(),kind})),
      ];
      return result;
    });
    setDirty(true);opRef.current=null;
    setNotice('پیشنهاد محلی فقط در فرم قرار گرفت؛ هنوز سفارشی ذخیره نشده است.');
    setRequestHints(null);
  };
  const suggestWithLocalModel=async()=>{
    if(!requestText.trim()||suggestionBusy||typeof api?.tarazOrderSuggest!=='function')return;
    setSuggestionBusy(true);setRequestHints(null);setError('');
    try{
      const result=await api.tarazOrderSuggest(requestText);
      if(!result||result.source!=='LOCAL_OLLAMA'||result.modelRan!==true||
        result.externalModelCalled!==false||result.financialEventCreated!==false||
        !result.fields||typeof result.fields!=='object'||Array.isArray(result.fields))
        throw Error('Model result without trusted provenance');
      const fields={};
      const allowed={customerName:120,title:200,unit:32,quantity:18,
        productionQuantity:18,actualProducedQuantity:18,scrapQuantity:18,
        healthySurplusQuantity:18,projectReference:120,
        scheduleStartDate:10,scheduleDueDate:10,procurementNotes:2000};
      for(const [key,max] of Object.entries(allowed)){
        const value=result.fields[key];
        if(typeof value==='string'&&value.length<=max)fields[key]=value.trim();
        else if((key.includes('Quantity')||key==='quantity')&&
          Number.isSafeInteger(value)&&value>=0&&value<=10000000)
          fields[key]=String(value);
      }
      for(const key of ['quantity','productionQuantity','actualProducedQuantity',
        'scrapQuantity','healthySurplusQuantity']){
        if(fields[key]&&asInt(fields[key],{allowEmpty:true,zero:key!=='quantity'&&key!=='productionQuantity'})===undefined)
          delete fields[key];
      }
      if(fields.scheduleStartDate&&!dateOk(fields.scheduleStartDate))delete fields.scheduleStartDate;
      if(fields.scheduleDueDate&&!dateOk(fields.scheduleDueDate))delete fields.scheduleDueDate;
      const suggestedStages=Array.isArray(result.suggestedStages)?
        result.suggestedStages.filter(kind=>STAGES.some(([key])=>key===kind)).slice(0,24):[];
      const missing=['customerName','title','quantity','productionQuantity']
        .filter(key=>!fields[key]).map(key=>({customerName:'نام مشتری',
          title:'شرح سفارش',quantity:'تعداد سفارش',productionQuantity:'تعداد تولید برنامه‌ای'})[key]);
      setRequestHints({fields,suggestedStages,missing,source:'LOCAL_OLLAMA',
        warnings:Array.isArray(result.warnings)?result.warnings.filter(x=>typeof x==='string').slice(0,5):[]});
    }catch(_error){
      setError('پیشنهاد مدل محلی دریافت یا اعتبارسنجی نشد. از استخراج آفلاین قانون‌محور استفاده کنید.');
    }finally{if(live.current)setSuggestionBusy(false);}
  };
  const discard=()=>{
    if(dirty&&!globalThis.confirm('تغییرات ذخیره‌نشده کنار گذاشته شوند؟'))return;
    setActive(null);setForm(EMPTY());setDirty(false);
    setMadarBound(null);
    setMadarLinkStatus(null);setMadarLinkError('');
    setMadarSyncPreview(null);setMadarSyncNotice('');setMadarSyncError('');
    setCostDrafts({});setPaymentDraft(paymentSeed('sale'));
    setPaymentMethods({});setSettlementRefs({});
    setFinanceDraftOutcome(null);
    setAgentReview(null);setAgentMemory(null);setAgentDraft('');
    setAgentQuery('');setAgentNatural(null);
    setAgentError('');setAgentNotice('');
    setError('');setNotice('');opRef.current=null;
  };
  const edit=order=>{
    if(dirty&&!globalThis.confirm('تغییرات ذخیره‌نشده کنار گذاشته شوند؟'))return;
    setActive(order);
    setPaymentDraft({...paymentSeed(order.kind),
      party:order.customerName||order.customerId||''});
    setCostDrafts({});setPaymentMethods({});setSettlementRefs({});
    setFinanceDraftOutcome(null);
    setAgentReview(null);setAgentMemory(null);setAgentDraft('');
    setAgentQuery('');setAgentNatural(null);
    setAgentError('');setAgentNotice('');
    setMadarBound(null);
    setForm({
      kind:order.kind,customerId:order.customerId,
      customerName:order.customerName,title:order.title,description:order.description,
      unit:order.unit,quantity:String(order.quantity),
      productionQuantity:String(order.productionQuantity),
      actualProducedQuantity:order.actualProducedQuantity==null?'':String(order.actualProducedQuantity),
      scrapQuantity:order.scrapQuantity==null?'':String(order.scrapQuantity),
      healthySurplusQuantity:order.healthySurplusQuantity==null?'':String(order.healthySurplusQuantity),
      projectReference:order.projectReference||'',
      scheduleStartDate:order.scheduleStartDate||'',
      scheduleDueDate:order.scheduleDueDate||'',
      procurementNotes:order.procurementNotes||'',
      unitPrice:order.unitPrice==null?'':String(order.unitPrice),
      costStages:order.costStages.map(stage=>({...stage,
        estimatedCost:stage.estimatedCost==null?'':String(stage.estimatedCost)})),
      notes:order.notes,
    });
    setDirty(false);setError('');setNotice('');opRef.current=null;
  };
  const save=async e=>{
    e.preventDefault();
    if(!ready||!canEdit||busy||active&&
      !['draft','in_production'].includes(active.status))return;
    const prepared=prepareTarazOrderDraft(form,currency);
    if(prepared.error){setError(prepared.error);return;}
    const measuring=active?.status==='in_production';
    if(measuring&&!globalThis.confirm(
      `مقادیر تولید واقعی، ضایعات و مازاد سالم سفارش «${active.title}» ثبت شوند؟`))return;
    const fingerprint=JSON.stringify([active?.id,active?.revision,prepared.data]);
    try{
      if(!opRef.current||opRef.current.fingerprint!==fingerprint)
        opRef.current={fingerprint,key:clientId()};
    }catch(_error){setError('ساخت شناسه امن درخواست ممکن نیست.');return;}
    const payload={
      action:active?'update':'create',
      idempotencyKey:opRef.current.key,orderId:active?.id||'',
      expectedRevision:active?.revision||0,data:prepared.data,
      nextStatus:null,manualConfirmation:!!measuring,
    };
    setBusy(true);setError('');setNotice('');
    try{
      const saved=await api.tarazOrderCommand(payload);
      if(!saved||!saved.id||!Number.isInteger(saved.revision)||
        saved.financialEventCreated!==false)throw Error('Unverified host response');
      const readOk=await refresh();
      if(!readOk){
        setError('پاسخ ذخیره دریافت شد، اما بازخوانی ناموفق بود. پیش از تکرار وضعیت سفارش را بررسی کنید.');
        return;
      }
      setActive(saved);setDirty(false);opRef.current=null;
      setAgentReview(null);setAgentMemory(null);
      setPaymentDraft({...paymentSeed(saved.kind),
        party:saved.customerName||saved.customerId||''});
      setNotice('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.');
    }catch(_error){
      setError('نتیجه ذخیره نامشخص است. ابتدا فهرست را بازخوانی و بعد برای تکرار تصمیم بگیرید.');
    }finally{if(live.current)setBusy(false);}
  };
  const transition=async(row,next)=>{
    if(!ready||!canEdit||busy)return;
    if(active?.id===row.id&&dirty){
      setError('پیش از تغییر وضعیت، اصلاحات ذخیره‌نشده همین سفارش را ذخیره یا لغو کنید.');
      return;
    }
    const verb=NEXT[row.status]?.find(([key])=>key===next)?.[1]||'تغییر وضعیت';
    if(!globalThis.confirm(`${verb} برای سفارش «${row.title}»؟ این کار سند مالی ایجاد نمی‌کند.`))
      return;
    setBusy(true);setError('');setNotice('');
    try{
      const saved=await api.tarazOrderCommand({
        action:'transition',idempotencyKey:clientId(),orderId:row.id,
        expectedRevision:row.revision,data:null,
        nextStatus:next,manualConfirmation:true,
      });
      if(!saved||saved.status!==next||saved.financialEventCreated!==false)
        throw Error('Unverified transition');
      if(await refresh()){
        if(active?.id===saved.id){setActive(saved);setDirty(false);}
        setAgentReview(null);setAgentMemory(null);
        setNotice('وضعیت سفارش ثبت و دوباره از میزبان خوانده شد؛ هیچ ثبت مالی انجام نشده است.');
      }else setError('بازخوانی وضعیت سفارش انجام نشد؛ پیش از تکرار آن را بررسی کنید.');
    }catch(_error){setError('وضعیت عملیات نامشخص است؛ فهرست سفارش‌ها را بازخوانی کنید.');}
    finally{if(live.current)setBusy(false);}
  };
  const financeAction=async(action,data,{privileged=false,confirmText=''}={})=>{
    const row=items.find(item=>item.id===active?.id);
    if(!ready||!canEdit||busy||!row||dirty||(privileged&&!canAdmin)){
      setError('ابتدا سفارش را ذخیره و بازخوانی کنید؛ عملیات مالی نیازمند مجوز معتبر است.');
      return false;
    }
    if(confirmText&&!globalThis.confirm(confirmText))return false;
    setBusy(true);setError('');setNotice('');
    try{
      const result=await api.tarazOrderCommand({
        action,idempotencyKey:clientId(),orderId:row.id,
        expectedRevision:row.revision,data,nextStatus:null,
        manualConfirmation:privileged,
      });
      if(!result||result.id!==row.id||result.revision!==row.revision+1||
        result.financialEventCreated!==false)throw Error('Unverified finance-control response');
      const success=await refresh();
      if(!success)throw Error('Order readback unavailable');
      setActive(result);
      setAgentReview(null);setAgentMemory(null);
      setNotice('ثبت در پرونده سفارش تأیید شد؛ هیچ عملیات بانکی یا سند حسابداری ایجاد نشد.');
      return true;
    }catch(_error){
      setError('نتیجه عملیات مشخص نیست؛ قبل از تکرار، سفارش را دوباره بازخوانی کنید.');
      return false;
    }finally{if(live.current)setBusy(false);}
  };
  const recordCost=async index=>{
    const draft=costDrafts[index]||{};
    const actualCost=asInt(draft.actualCost,{allowEmpty:true,zero:true,max:1e15});
    if(actualCost===null||actualCost===undefined||!draft.costDate||
      !dateOk(draft.costDate)||(draft.receiptReference||'').length>120){
      setError('مبلغ و تاریخ معتبر هزینه واقعی را وارد کنید. خالی به معنی صفر نیست.');
      return;
    }
    if(await financeAction('cost.record',{stageIndex:index,actualCost,
      costDate:draft.costDate,receiptReference:draft.receiptReference||''}))
      setCostDrafts(prev=>({...prev,[index]:{}}));
  };
  const recordPayment=async()=>{
    const amount=asInt(paymentDraft.amount,{zero:false,max:1e15});
    if(!amount||amount===undefined||!dateOk(paymentDraft.paymentDate)||
      !paymentDraft.paymentDate||!paymentDraft.party.trim()||
      paymentDraft.party.length>120||paymentDraft.method.length>80||
      paymentDraft.transactionReference.length>120||
      (paymentDraft.status==='recorded'&&!paymentDraft.method.trim())){
      setError('مبلغ، تاریخ، طرف‌حساب و روش پرداخت ثبت‌شده را بررسی کنید.');
      return;
    }
    if(await financeAction('payment.record',{
      ...paymentDraft,amount,party:paymentDraft.party.trim(),
      method:paymentDraft.method.trim(),
      transactionReference:paymentDraft.transactionReference.trim(),
    }))setPaymentDraft(paymentSeed(active.kind));
  };
  const makeAccountingDraft=async()=>{
    if(!canAdmin||busy||dirty||!active?.financeHandoff||
      typeof api?.tarazOrderFinanceDraft!=='function'||
      typeof api?.standaloneAccountingRead!=='function')return;
    if(!dateOk(financeDocumentDate)||!financeDocumentDate){
      setError('تاریخ سند حسابداری معتبر نیست.');return;
    }
    setBusy(true);setError('');setNotice('');
    try{
      const accounting=await api.standaloneAccountingRead();
      const row=items.find(item=>item.id===active.id);
      if(!row||row.revision!==active.revision||
        accounting.view.currency!==row.currency||
        !accounting.view.parties?.[row.customerId])
        throw Error('Stale or missing real accounting party/currency');
      const message='ایجاد پیش‌نویس حسابداری از سفارش '+row.id+
        ' با طرف حساب '+row.customerId+' و مبلغ '+
        financialDisplay(row.estimatedSalesTotal)+' '+money+
        ' در تاریخ '+financeDocumentDate+
        '؟ فقط پیش‌نویس ساخته می‌شود؛ صدور قطعی و بانک جدا هستند.';
      if(!globalThis.confirm(message))return;
      const result=await api.tarazOrderFinanceDraft({
        orderId:row.id,expectedOrderRevision:row.revision,
        expectedAccountingRevision:accounting.revision,
        previewDigest:row.financeHandoff.preview_digest,
        documentDate:financeDocumentDate,explicitConfirmation:true,
      });
      if(!['DRAFT_CREATED','ALREADY_DRAFT'].includes(result?.status)||
        result.orderId!==row.id||result.financialDocumentIssued!==false||
        result.journalCreated!==false)throw Error('Unverified accounting draft bridge');
      setFinanceDraftOutcome(result);
      setNotice('پیش‌نویس حسابداری ایجاد یا بازخوانی شد؛ هیچ سند قطعی یا ثبت بانکی انجام نشد.');
    }catch(_error){
      setError('ارجاع به حسابداری تأیید نشد. پیش‌نویس‌ها و شناسه سفارش را بررسی کنید؛ از تکرار کورکورانه خودداری کنید.');
    }finally{if(live.current)setBusy(false);}
  };
  const loadAgentReview=async()=>{
    if(!active||busy||dirty||agentBusy||
      typeof api?.tarazAgentOrderReview!=='function'||
      typeof api?.tarazAgentMemoryList!=='function')return;
    setAgentBusy(true);setAgentError('');setAgentNotice('');
    try{
      const [review,memory]=await Promise.all([
        api.tarazAgentOrderReview(active.id),
        api.tarazAgentMemoryList(active.id),
      ]);
      if(review?.source!=='REAL_SQLITE_TOOLS'||
        review?.modelRan!==false||review?.financialEventCreated!==false||
        review?.requiresHumanApproval!==true||review?.toolsReadOnly!==true||
        review?.facts?.orderId!==active.id||
        review?.facts?.revision!==active.revision||
        !/^[a-f0-9]{64}$/.test(review?.sourceDigest||'')||
        !Array.isArray(review?.toolTrace)||review.toolTrace.length!==2||
        !Array.isArray(review?.recommendations)||
        memory?.source!=='LOCAL_AUDITED_MEMORY'||
        !Number.isSafeInteger(memory?.revision)||!Array.isArray(memory?.entries))
        throw Error('Agent evidence missing or untrusted');
      setAgentReview(review);setAgentMemory(memory);
      setAgentNotice('بررسی ابزارهای محلی انجام شد. پیشنهادها هیچ عملیاتی اجرا نکرده‌اند.');
    }catch(_error){
      setAgentReview(null);setAgentMemory(null);
      setAgentError('بازخوانی شواهد عامل ممکن نشد؛ اطلاعات سفارش را تازه‌سازی کنید.');
    }finally{if(live.current)setAgentBusy(false);}
  };
  const requestAgentNatural=async()=>{
    if(!active||busy||dirty||agentBusy||!agentQuery.trim()||
      typeof api?.tarazAgentNaturalRequest!=='function'||
      typeof api?.tarazAgentOrderReview!=='function'||
      typeof api?.tarazAgentMemoryList!=='function')return;
    setAgentBusy(true);setAgentError('');setAgentNotice('');setAgentNatural(null);
    try{
      const [result,review,memory]=await Promise.all([
        api.tarazAgentNaturalRequest(active.id,agentQuery),
        api.tarazAgentOrderReview(active.id),
        api.tarazAgentMemoryList(active.id),
      ]);
      if(result?.source!=='REAL_SQLITE_TOOLS'||
        result.inference!=='RULE_BASED_FALLBACK'||result.modelRan!==false||
        result.externalModelCalled!==false||result.autoActionPerformed!==false||
        result.financialEventCreated!==false||
        result.requiresHumanApproval!==true||
        result.sourceRevision!==active.revision||
        result.sourceDigest!==review?.sourceDigest||
        result.memoryRevision!==memory?.revision||
        review?.facts?.orderId!==active.id||review.facts.revision!==active.revision||
        !Array.isArray(result.missingInformation)||
        typeof result.editableProposal!=='string'||
        result.editableProposal.length>800)
        throw Error('Unsupported or stale grounded request result');
      setAgentReview(review);setAgentMemory(memory);
      setAgentNatural(result);setAgentDraft(result.editableProposal);
      setAgentNotice(result.previouslyRejected?
        'این پیشنهاد قبلاً رد شده است و دوباره عرضه نمی‌شود.':
        'درخواست با ابزارهای واقعی بررسی شد؛ متن پیشنهادی پیش از ثبت قابل ویرایش است.');
    }catch(_error){
      setAgentNatural(null);
      setAgentError('درخواست قابل اعتبارسنجی نبود. وضعیت سفارش و دسترسی را بررسی کنید.');
    }finally{if(live.current)setAgentBusy(false);}
  };
  const changeAgentMemory=async(action,entryId=null)=>{
    if(!active||dirty||agentBusy||busy||!canEdit||
      !agentReview||agentReview.facts?.revision!==active.revision||
      !agentMemory||typeof api?.tarazAgentMemoryCommand!=='function'||
      (action!=='propose'&&!canAdmin))return;
    const text=action==='propose'?agentDraft.trim():null;
    if(action==='propose'&&(!text||text.length>800)) {
      setAgentError('متن حافظه باید ۱ تا ۸۰۰ نویسه باشد.');return;
    }
    if(action!=='propose'&&!globalThis.confirm(
      action==='accept'?'این یادداشت به حافظه تأییدشده سازمان اضافه شود؟':
        'این پیشنهاد رد شود و بدون درخواست جدید بازنگردد؟'))return;
    setAgentBusy(true);setAgentError('');setAgentNotice('');
    try{
      const result=await api.tarazAgentMemoryCommand({
        action,orderId:active.id,entryId,text,sourceRevision:active.revision,
        expectedMemoryRevision:agentMemory.revision,idempotencyKey:clientId(),
        manualConfirmation:action!=='propose',
      });
      if(!result||!Number.isSafeInteger(result.revision)||
        result.revision!==agentMemory.revision+1||
        result.financialEventCreated!==false)throw Error('Unverified memory write');
      const latest=await api.tarazAgentMemoryList(active.id);
      if(latest?.revision!==result.revision||!Array.isArray(latest.entries))
        throw Error('Memory readback failed');
      setAgentMemory(latest);
      if(action==='propose')setAgentDraft('');
      setAgentNotice('پیشنهاد حافظه با وضعیت قابل‌ردیابی ذخیره و بازخوانی شد.');
    }catch(_error){
      setAgentError('نتیجه حافظه نامشخص است؛ پیش از تلاش دوباره، شواهد را بازخوانی کنید.');
    }finally{if(live.current)setAgentBusy(false);}
  };
  const visible=useMemo(()=>items.filter(item=>filter==='all'||item.status===filter),
    [items,filter]);
  const missing=orderCompleteness(form);
  const quoted=asInt(form.quantity);
  const plan=asInt(form.productionQuantity);
  const unitPrice=asInt(form.unitPrice,{allowEmpty:true,zero:true,max:1e15});
  const total=quoted!=null&&quoted!==undefined&&unitPrice!=null&&unitPrice!==undefined?
    quoted*unitPrice:null;
  const productionReview=orderProductionReview(form);
  const canSaveOrder=!active||['draft','in_production'].includes(active.status);
  const nextInstruction=missing.length?
    `گام بعدی: ${missing[0]} را وارد کنید تا پیش‌نویس قابل ذخیره شود.`:
    active?.status==='in_production'&&productionReview.state!=='balanced'?
      'گام بعدی: مقادیر تولید واقعی، ضایعات و مازاد سالم را ثبت و تراز کنید.':
    active?.status==='in_production'?
      'گام بعدی: پس از تطبیق تحویل واقعی با سفارش، وضعیت را با تأیید خودتان ثبت کنید.':
    active?.status==='approved'?'گام بعدی: اجرای سفارش را پس از تأیید شروع کنید.':
    active?.status==='draft'?'گام بعدی: سفارش پیش‌نویس را بررسی و سپس تأیید کنید.':
    'گام بعدی: فرم را تکمیل کنید و پیش از ذخیره، پیشنهادها را بازبینی کنید.';
  return <section className="taraz-orders" dir="rtl" aria-label="مدیریت سفارش‌های تراز">
    <header className="taraz-orders-header">
      <div><span className="taraz-orders-eyebrow">TARAZ / ORDERS</span>
        <h2><ClipboardList size={24}/> سفارش‌ها</h2>
        <p>از درخواست مشتری تا تولید و تحویل؛ مستقل از سند مالی.</p></div>
      <button type="button" onClick={()=>void refresh()} disabled={busy||loading||!ready}>
        <RefreshCw size={16}/> بازخوانی
      </button>
    </header>
    <div className="taraz-orders-hint" role="group" aria-label="وضعیت اکوسیستم و AI">
      <button type="button" disabled={ecosystemBusy||
        typeof api?.tarazEcosystemStatus!=='function'||
        typeof api?.tarazAiProviderStatus!=='function'}
        onClick={()=>void inspectEcosystem()}>
        {ecosystemBusy?'در حال بررسی...':'وضعیت آفلاین، همگام‌سازی و AI'}</button>
      {ecosystemStatus&&<p role="status">
        عملیات دستی محلی: در دسترس با مجوز کاربر ·
        {' '}انتقال مرجع مالی: هنوز مصوب نشده ·
        {' '}همگام‌سازی سه‌محصولی: متصل نیست ·
        {' '}AI: {ecosystemStatus.ai.availability} ·
        {' '}RADAR: سورس/اتصال تأیید نشده
      </p>}
      {ecosystemError&&<p role="alert">{ecosystemError}</p>}
    </div>
    {!ready&&<p className="taraz-orders-alert" role="alert">
      این نسخه میزبان هنوز قابلیت ذخیره سفارش مستقل را ندارد؛ نسخه جدید را اجرا کنید.
    </p>}
    {error&&<p className="taraz-orders-alert error" role="alert">{error}</p>}
    {notice&&<p className="taraz-orders-alert success" role="status">{notice}</p>}
    <div className="taraz-orders-layout">
      <section className="taraz-orders-editor" aria-label="فرم ثبت سفارش">
        <div className="taraz-orders-editor-head">
          <h3>{active?'ویرایش سفارش':'سفارش جدید'}</h3>
          <div role="group" aria-label="سطح فرم سفارش">
            <button type="button" aria-pressed={mode==='simple'}
              onClick={()=>setMode('simple')}>ساده</button>
            <button type="button" aria-pressed={mode==='advanced'}
              onClick={()=>setMode('advanced')}>حرفه‌ای</button>
          </div>
        </div>
        <section className="taraz-orders-intake" aria-label="استخراج اولیه درخواست مشتری">
          <label>درخواست مشتری را بنویسید یا جای‌گذاری کنید
            <textarea value={requestText} maxLength={4000} rows={2}
              onChange={e=>{setRequestText(e.target.value);setRequestHints(null);}}
              placeholder={'مشتری: ...\nشرح سفارش: ...\nتعداد فروش: ۱۰۰ عدد، تولید ۱۲۰'} />
          </label>
          <div className="taraz-orders-intake-actions">
            <button type="button" disabled={busy||suggestionBusy||!requestText.trim()}
              onClick={()=>setRequestHints(extractLocalOrderHints(requestText))}>
              استخراج اطلاعات (آفلاین)
            </button>
            {typeof api?.tarazOrderSuggest==='function'&&
              <button type="button" disabled={busy||suggestionBusy||!requestText.trim()}
                onClick={()=>void suggestWithLocalModel()}>
                {suggestionBusy?'در حال تحلیل محلی...':'پیشنهاد با مدل محلی'}
              </button>}
            <small>راهنمای قانون‌محور محلی؛ بدون ارسال متن به اینترنت یا ثبت خودکار</small>
          </div>
          {requestHints?.error&&<p role="alert" className="taraz-orders-hint">{requestHints.error}</p>}
          {requestHints?.fields&&<div className="taraz-orders-hint" role="status">
            <p>{requestHints.source==='LOCAL_OLLAMA'?
              'پیشنهاد مدل محلی: همه موارد را با درخواست اصلی تطبیق دهید.':
              'اطلاعات از عبارت‌های صریح متن استخراج شده‌اند؛ بازبینی لازم است.'}</p>
            <p>اطلاعات پیشنهادی: {[
              requestHints.fields.customerName,requestHints.fields.title,
              requestHints.fields.quantity&&'تعداد '+requestHints.fields.quantity,
              requestHints.fields.productionQuantity&&'تولید '+requestHints.fields.productionQuantity,
              requestHints.fields.actualProducedQuantity&&'تولید واقعی '+requestHints.fields.actualProducedQuantity,
              requestHints.fields.scrapQuantity&&'ضایعات '+requestHints.fields.scrapQuantity,
              requestHints.fields.healthySurplusQuantity&&'مازاد سالم '+requestHints.fields.healthySurplusQuantity,
            ].filter(Boolean).join(' • ')||'مورد مشخصی استخراج نشد'}</p>
            {requestHints.missing.length>0&&
              <p>نیازمند تکمیل دستی: {requestHints.missing.join('، ')}</p>}
            {(requestHints.warnings||[]).map((warning,i)=><p key={i}>{warning}</p>)}
            {(requestHints.suggestedActions||[]).slice(0,3).map((action,i)=><p key={'a'+i}>{action}</p>)}
            <button type="button" onClick={applyRequestHints}
              disabled={busy||!canEdit||!!active&&active.status!=='draft'}>اعمال پیشنهاد به فرم</button>
          </div>}
        </section>
        <form onSubmit={save} className="taraz-orders-form">
          <fieldset disabled={!canEdit||busy||!ready||!!active&&active.status!=='draft'}>
            <legend>مشخصات سفارش</legend>
            <div className="taraz-orders-type" role="group" aria-label="نوع سفارش">
              <button type="button" aria-pressed={form.kind==='sale'}
                onClick={()=>update('kind','sale')} disabled={!!active}>فروش</button>
              <button type="button" aria-pressed={form.kind==='purchase'}
                onClick={()=>update('kind','purchase')} disabled={!!active}>خرید</button>
            </div>
            <label>نام {form.kind==='sale'?'مشتری':'تأمین‌کننده'}
              <input value={form.customerName} onChange={e=>update('customerName',e.target.value)}
                placeholder="نام یا عنوان طرف حساب" maxLength={120}/>
            </label>
            <label>شرح سفارش
              <input value={form.title} onChange={e=>update('title',e.target.value)}
                placeholder="مثلاً چاپ پاسپورت تبلیغاتی" maxLength={200}/>
            </label>
            <div className="taraz-orders-grid">
              <label>تعداد سفارش
                <input inputMode="numeric" value={form.quantity} maxLength={14}
                  onChange={e=>update('quantity',e.target.value)} placeholder="۱۰۰"/>
              </label>
              <label>تعداد برنامه‌ریزی تولید
                <input inputMode="numeric" value={form.productionQuantity} maxLength={14}
                  onChange={e=>update('productionQuantity',e.target.value)} placeholder="۱۲۰"/>
              </label>
              <label>واحد
                <input value={form.unit} onChange={e=>update('unit',e.target.value)}
                  placeholder="عدد، برگ، متر" maxLength={32}/>
              </label>
              <label>قیمت واحد (اختیاری، {money})
                <input inputMode="numeric" value={form.unitPrice} maxLength={18}
                  onChange={e=>update('unitPrice',e.target.value)} placeholder="بدون قیمت فرضی"/>
              </label>
            </div>
            <div className="taraz-orders-totals">
              <span>اختلاف برنامه با فروش (هنوز تعیین‌تکلیف‌نشده): <b>{quoted!=null&&plan!=null&&
                quoted!==undefined&&plan!==undefined?
                Math.max(0,plan-quoted).toLocaleString('fa-IR'):'نامشخص'}</b></span>
              <span>جمع قیمت پیشنهادی: <b>{formatAmount(total)} {total!=null?money:''}</b></span>
            </div>
            {mode==='simple'&&<section className="taraz-orders-simple-stages"
              aria-label="مراحل سفارش برای کاربر ساده">
              <div className="taraz-orders-stage-head">
                <strong>مراحل کار</strong>
                <button type="button" disabled={form.costStages.length>=24}
                  onClick={()=>{setForm(prev=>({...prev,costStages:[...prev.costStages,emptyStage()]}));
                    setDirty(true);opRef.current=null;}}>افزودن مرحله</button>
              </div>
              {form.costStages.map((stage,i)=><div className="taraz-orders-stage" key={i}>
                <select aria-label={'نوع مرحله '+(i+1)} value={stage.kind}
                  onChange={e=>stageUpdate(i,'kind',e.target.value)}>
                  {STAGES.map(([key,label])=><option key={key} value={key}>{label}</option>)}
                </select>
                <input aria-label={'تأمین کننده مرحله '+(i+1)} placeholder="مجری مرحله"
                  value={stage.supplier} onChange={e=>stageUpdate(i,'supplier',e.target.value)}/>
                <input aria-label={'هزینه مرحله '+(i+1)} placeholder="برآورد هزینه (اختیاری)"
                  value={stage.estimatedCost}
                  onChange={e=>stageUpdate(i,'estimatedCost',e.target.value)}/>
                <button type="button" aria-label={'حذف مرحله '+(i+1)}
                  onClick={()=>{setForm(prev=>({...prev,costStages:prev.costStages.filter((_,j)=>j!==i)}));
                    setDirty(true);opRef.current=null;}}>حذف</button>
                <input className="taraz-orders-stage-note"
                  aria-label={'شرح مرحله '+(i+1)} placeholder="شرح کار"
                  value={stage.description} onChange={e=>stageUpdate(i,'description',e.target.value)}/>
              </div>)}
            </section>}
            {mode==='advanced'&&<div className="taraz-orders-advanced">
              <label>شناسه طرف حساب موجود (اختیاری)
                <input value={form.customerId} maxLength={96}
                  onChange={e=>update('customerId',e.target.value)}/>
              </label>
              <label>توضیحات تولید و فایل‌ها
                <textarea value={form.description} maxLength={4000} rows={2}
                  onChange={e=>update('description',e.target.value)}/>
              </label>
              <label>ارجاع پروژه مرتبط (اختیاری، نیازمند تأیید دستی)
                <input value={form.projectReference} maxLength={120}
                  onChange={e=>update('projectReference',e.target.value)}
                  placeholder="کد یا نام پروژه"/>
              </label>
              {madarBound&&form.projectReference===madarBound.id&&
                <p className="taraz-orders-madar-verified" role="status">
                  شناسه انتخاب‌شده از مدار: {madarBound.name} (ID: <code dir="ltr">{madarBound.id}</code>).
                  مشاهده توسط {madarBound.actor} و با محدودیت دسترسی سرور انجام شد.
                </p>}
              {canAdmin&&<section className="taraz-orders-madar-picker" aria-label="انتخاب پروژه واقعی مدار">
                <strong>انتخاب شناسه واقعی از پروژه‌های مدار</strong>
                <p>فقط پروژه‌های میزبان مدار با احراز هویت HTTPS و دسترسی مدیر تراز خوانده می‌شوند.
                  شناسه پس از انتخاب دستی در سفارش ذخیره می‌شود؛ این ارجاع همگام‌سازی یا پیوند دوطرفه ایجاد نمی‌کند.</p>
                {typeof api?.tarazMadarDataRead!=='function'?
                  <p role="status">میزبان این نسخه امکان خواندن پروژه‌های مدار را ندارد.</p>:
                  <>
                    <label className="taraz-orders-madar-consent">
                      <input type="checkbox" checked={madarConsent} disabled={madarBusy}
                        onChange={e=>{
                          const enabled=e.target.checked;
                          setMadarConsent(enabled);clearMadarPage();
                          if(!enabled)setMadarCredentials(emptyMadarCredentials());
                        }}/>
                      با خواندن درخواستی فهرست پروژه‌های مجاز خود از میزبان مدار موافقم
                    </label>
                    {madarConsent&&<>
                      <div className="taraz-orders-grid taraz-orders-madar-fields">
                        {[
                          ['url','نشانی HTTPS میزبان مدار','url','https://192.168.1.10:48370'],
                          ['fingerprint','اثر انگشت SHA-256 گواهی','text','۶۴ رقم هگزادسیمال'],
                          ['username','نام کاربری مدار','text',''],
                          ['password','گذرواژه مدار','password',''],
                        ].map(([key,label,type,placeholder])=><label key={key}>{label}
                          <input type={type} dir="ltr" autoComplete="off"
                            value={madarCredentials[key]} placeholder={placeholder}
                            onChange={e=>{
                              setMadarCredentials(prev=>({...prev,[key]:e.target.value}));
                              clearMadarPage();
                            }}/>
                        </label>)}
                      </div>
                      <div className="taraz-orders-madar-actions">
                        <button type="button" onClick={()=>void readMadarProjects(0)}
                          disabled={madarBusy||busy}>{madarBusy?'در حال خواندن...':'خواندن پروژه‌های مجاز مدار'}</button>
                        <button type="button" onClick={()=>{
                          clearMadarPage();setMadarCredentials(emptyMadarCredentials());
                        }} disabled={madarBusy}>پاک کردن اطلاعات اتصال و فهرست</button>
                      </div>
                      {madarError&&<p className="taraz-orders-hint" role="alert">{madarError}</p>}
                      {madarPage&&<>
                        <p className="taraz-orders-madar-source" role="status">
                          فهرست از میزبان احراز هویت‌شده مدار دریافت شد. محدودیت دسترسی پروژه‌ها
                          توسط میزبان اعمال شده است. صفحه {(Math.floor(madarPage.offset/50)+1).toLocaleString('fa-IR')}
                        </p>
                        {madarPage.projects.length?
                          <label>پروژه دریافت‌شده از میزبان
                            <select aria-label="پروژه مدار" value={madarSelectedId}
                              onChange={e=>setMadarSelectedId(e.target.value)}>
                              <option value="">انتخاب کنید</option>
                              {madarPage.projects.map(project=><option key={project.id} value={project.id}>
                                {project.name} ({project.id})
                              </option>)}
                            </select>
                          </label>:<p>در این صفحه پروژه‌ای وجود ندارد.</p>}
                        <div className="taraz-orders-madar-actions">
                          <button type="button" disabled={!madarSelectedId||busy}
                            onClick={applyMadarProject}>اعمال شناسه انتخاب‌شده به سفارش</button>
                          <button type="button" disabled={madarBusy||madarPage.offset===0}
                            onClick={()=>void readMadarProjects(Math.max(0,madarPage.offset-50))}>صفحه قبل</button>
                          <button type="button" disabled={madarBusy||!madarPage.more}
                            onClick={()=>void readMadarProjects(madarPage.offset+50)}>صفحه بعد</button>
                        </div>
                      </>}
                    </>}
                  </>}
                {active?.projectReference&&
                  <div className="taraz-orders-madar-verified-link"
                    aria-label="پیوند تأییدشده پروژه مدار">
                    <button type="button"
                      disabled={madarLinkBusy||busy||
                        typeof api?.tarazOrderMadarLinkRead!=='function'}
                      onClick={()=>void readMadarOrderLink()}>
                      بررسی پیوند ذخیره‌شده در تراز</button>
                    {madarLinkStatus?.link&&<p role="status">
                      شناسه پروژه: <code dir="ltr">{madarLinkStatus.link.project_id}</code>
                      {' · '}تأیید قبلی توسط {madarLinkStatus.link.actor}
                      {' · '}Revision پیوند {madarLinkStatus.link.revision}.
                      {' '}{madarLinkStatus.currentOrderMatches?
                        'مرجع سفارش با پیوند ذخیره‌شده برابر است.':
                        'مرجع سفارش تغییر کرده و پیوند قبلی دیگر معتبر نیست.'}
                      {' '}اعتبار فعلی عضویت پروژه در میزبان مدار با این خواندن محلی بررسی نشده است.
                    </p>}
                    {madarLinkStatus&&!madarLinkStatus.link&&
                      <p role="status">برای این سفارش هنوز پیوند تأییدشده ذخیره نشده است.</p>}
                    {madarLinkError&&<p role="alert">{madarLinkError}</p>}
                  </div>}
                {active&&madarConsent&&madarBound&&madarPage&&
                  madarPage.projects.some(project=>project.id===madarBound.id)&&
                  active.projectReference===madarBound.id&&
                  typeof api?.tarazOrderMadarLink==='function'&&
                  <button type="button" disabled={busy||dirty||madarLinkBusy}
                    onClick={()=>void verifyAndBindMadar()}>
                    تأیید دوبارهٔ HTTPS و ثبت پیوند پروژه در تراز (بدون تغییر مدار)
                  </button>}
                {active&&madarLinkStatus?.currentOrderMatches&&
                  madarLinkStatus.link?.order_revision===active.revision&&
                  typeof api?.tarazMadarOrderPreview==='function'&&
                  <section className="taraz-orders-madar-sync"
                    aria-label="پیش‌نمایش و همگام‌سازی عملیاتی مدار">
                    <strong>ارسال کنترل‌شدهٔ یک وظیفه عملیاتی به مدار</strong>
                    <p>پس از بازخوانی میزبان HTTPS و بررسی پروژه، پیش‌نمایش یک وظیفه با
                      مرجع سفارش ایجاد می‌شود. تا پیش از تأیید مجدد، هیچ داده‌ای در مدار تغییر نمی‌کند.</p>
                    <button type="button" disabled={madarSyncBusy||busy||dirty||
                      !madarConsent||madarLinkBusy}
                      onClick={()=>void previewMadarOrderSync()}>
                      {madarSyncBusy?'در حال بررسی میزبان...':
                        'دریافت پیش‌نمایش وظیفه از مدار (بدون ثبت)'}</button>
                    <button type="button" disabled={madarSyncBusy||busy||dirty||
                      !madarConsent||madarLinkBusy||
                      typeof api?.tarazMadarOrderProgress!=='function'}
                      onClick={()=>void readMadarStageProgress()}>
                      بازخوانی وضعیت واقعی مراحل از مدار (فقط خواندن)</button>
                    <button type="button" disabled={madarSyncBusy||busy||
                      typeof api?.tarazMadarOrderSyncHistory!=='function'}
                      onClick={()=>void loadMadarSyncHistory()}>
                      تاریخچهٔ تلاش‌های همگام‌سازی (محلی)</button>
                    <button type="button" disabled={madarSyncBusy||busy||dirty||
                      !madarConsent||madarLinkBusy||
                      typeof api?.tarazMadarOrderRecover!=='function'}
                      onClick={()=>void recoverMadarSync()}>
                      بازیابی نتیجهٔ نامشخص از مدار (بدون ارسال مجدد)</button>
                    {madarSyncHistory?.orderId===active.id&&
                      <div className="taraz-orders-madar-sync-preview" role="status">
                        <strong>تاریخچهٔ معتبر همگام‌سازی</strong>
                        {madarSyncHistory.entries.length===0?<p>
                          برای این سفارش هنوز تلاش ثبت‌شده‌ای وجود ندارد.</p>:
                          madarSyncHistory.entries.slice(0,10).map(entry=><p
                            key={entry.attempt_id}>
                            Revision {entry.order_revision} · {entry.status}
                            {entry.remote_write_attempted?' · احتمال ارسال به میزبان':' · بدون ارسال'}
                            {entry.error_type?' · نوع خطا: '+entry.error_type:''}
                          </p>)}
                      </div>}
                    {madarProgress?.orderId===active.id&&
                      madarProgress.orderRevision===active.revision&&
                      <div className="taraz-orders-madar-sync-preview" role="status">
                        <strong>وضعیت عملیات در مدار</strong>
                        <p>{madarProgress.status==='NOT_SYNCED'?
                          'این سفارش هنوز وظیفهٔ همگام‌شده‌ای در مدار ندارد.':
                          madarProgress.status==='SOURCE_CHANGED'?
                            'Revision یا محتوای سفارش تغییر کرده است؛ وضعیت قبلی بدون تطبیق مجدد مبنای اقدام نیست.':
                            'وظیفهٔ مربوط به همین نسخهٔ سفارش شناسایی شد.'}</p>
                        {madarProgress.stages.map(stage=><p key={stage.sourceId}>
                          مرحله {stage.index+1} · {stage.kind} ·
                          {' '}{stage.state==='done'?'انجام‌شده در مدار':
                            stage.state==='pending'?'در انتظار در مدار':'وضعیت نامشخص'}
                        </p>)}
                      </div>}
                    {madarSyncError&&<p className="taraz-orders-hint"
                      role="alert">{madarSyncError}</p>}
                    {madarSyncNotice&&<p role="status">{madarSyncNotice}</p>}
                    {madarSyncPreview?.orderRevision===active.revision&&
                      <div className="taraz-orders-madar-sync-preview">
                        <h4>پیش‌نمایش عملیات روی میزبان واقعی</h4>
                        <p>پروژه: <code dir="ltr">{madarSyncPreview.projectId}</code></p>
                        <p>شناسه وظیفه: <code dir="ltr">{madarSyncPreview.taskId}</code></p>
                        <p>عنوان: {madarSyncPreview.taskPreview?.title}</p>
                        <p>خلاصهٔ مراحل و وضعیت بدون عملیات بانکی:</p>
                        <pre>{madarSyncPreview.taskPreview?.description||''}</pre>
                        <p>Revision میزبان: <code dir="ltr">
                          {madarSyncPreview.sourceRevision}</code></p>
                        <p>هش پیش‌نمایش: <code dir="ltr">
                          {madarSyncPreview.previewDigest}</code></p>
                        <button type="button"
                          disabled={madarSyncBusy||dirty||busy||
                            typeof api?.tarazMadarOrderCommit!=='function'}
                          onClick={()=>void commitMadarOrderSync()}>
                          تأیید صریح ایجاد وظیفه در مدار (تغییر واقعی میزبان)</button>
                      </div>}
                  </section>}
              </section>}
              <div className="taraz-orders-grid">
                <label>تاریخ شروع برنامه‌ریزی‌شده
                  <input type="date" value={form.scheduleStartDate}
                    onChange={e=>update('scheduleStartDate',e.target.value)}/>
                </label>
                <label>موعد تحویل برنامه‌ریزی‌شده
                  <input type="date" value={form.scheduleDueDate}
                    onChange={e=>update('scheduleDueDate',e.target.value)}/>
                </label>
              </div>
              <label>نیازهای خرید و تأمین (اختیاری)
                <textarea rows={2} value={form.procurementNotes} maxLength={2000}
                  onChange={e=>update('procurementNotes',e.target.value)}
                  placeholder="مواد مورد نیاز، وضعیت استعلام و تأمین‌کننده مورد بررسی"/>
              </label>
              <div className="taraz-orders-stage-head">
                <strong>مراحل و هزینه‌های سفارش</strong>
                <button type="button" onClick={()=>{
                  setForm(prev=>({...prev,costStages:[...prev.costStages,emptyStage()]}));
                  setDirty(true);opRef.current=null;
                }} disabled={form.costStages.length>=24}><Plus size={15}/> افزودن مرحله</button>
              </div>
              {form.costStages.map((stage,i)=><div key={i} className="taraz-orders-stage">
                <select aria-label={'نوع مرحله '+(i+1)} value={stage.kind}
                  onChange={e=>stageUpdate(i,'kind',e.target.value)}>
                  {STAGES.map(([key,label])=><option key={key} value={key}>{label}</option>)}
                </select>
                <input aria-label={'تأمین کننده مرحله '+(i+1)}
                  placeholder="پیمانکار (اختیاری)" value={stage.supplier}
                  onChange={e=>stageUpdate(i,'supplier',e.target.value)} maxLength={120}/>
                <input aria-label={'هزینه مرحله '+(i+1)}
                  placeholder={'هزینه تخمینی ('+money+')'} inputMode="numeric"
                  value={stage.estimatedCost} maxLength={18}
                  onChange={e=>stageUpdate(i,'estimatedCost',e.target.value)}/>
                <button type="button" title="حذف مرحله" aria-label={'حذف مرحله '+(i+1)}
                  onClick={()=>{
                    setForm(prev=>({...prev,costStages:prev.costStages.filter((_,j)=>j!==i)}));
                    setDirty(true);opRef.current=null;
                  }}><Trash2 size={16}/></button>
                <input aria-label={'شرح مرحله '+(i+1)}
                  className="taraz-orders-stage-note" placeholder="شرح کار"
                  value={stage.description} maxLength={300}
                  onChange={e=>stageUpdate(i,'description',e.target.value)}/>
              </div>)}
              <label>یادداشت داخلی
                <textarea value={form.notes} maxLength={4000} rows={2}
                  onChange={e=>update('notes',e.target.value)}/>
              </label>
            </div>}
          </fieldset>
          <fieldset className="taraz-orders-measure-fields"
            disabled={!canEdit||busy||!ready||!!active&&
              !['draft','in_production'].includes(active.status)}>
            <legend>کنترل نتیجه تولید</legend>
            <strong>ثبت نتیجه واقعی تولید</strong>
            <p>عدد خالی یعنی هنوز شمارش نشده؛ صفر یعنی شمارش انجام شده و مقدار صفر بوده است.</p>
            <div className="taraz-orders-grid taraz-orders-production-grid">
              <label>تولید واقعی (اختیاری)
                <input inputMode="numeric" value={form.actualProducedQuantity} maxLength={14}
                  onChange={e=>update('actualProducedQuantity',e.target.value)} placeholder="مثلاً ۱۲۰"/>
              </label>
              <label>ضایعات واقعی (اختیاری)
                <input inputMode="numeric" value={form.scrapQuantity} maxLength={14}
                  onChange={e=>update('scrapQuantity',e.target.value)} placeholder="مثلاً ۵"/>
              </label>
              <label>مازاد سالم (اختیاری)
                <input inputMode="numeric" value={form.healthySurplusQuantity} maxLength={14}
                  onChange={e=>update('healthySurplusQuantity',e.target.value)} placeholder="مثلاً ۱۵"/>
              </label>
            </div>
            <p role="status" className={'taraz-orders-reconciliation '+productionReview.state}>
              {productionReview.message}
            </p>
          </fieldset>
          <div className="taraz-orders-guided-step" role="status">{nextInstruction}</div>
            {missing.length>0&&<div className="taraz-orders-hint" role="status">
              برای تکمیل سفارش: {missing.join('، ')}
            </div>}
            <div className="taraz-orders-actions">
              <button type="submit" className="taraz-orders-primary"
                disabled={!ready||busy||!canEdit||!canSaveOrder||active?.status==='in_production'&&!dirty}>
                <Save size={16}/> {busy?'در حال بررسی...':
                  active?.status==='in_production'?'ثبت اندازه‌گیری با تأیید':
                    active?'ذخیره اصلاحات':'ذخیره سفارش'}
              </button>
              <button type="button" disabled={busy} onClick={discard}>فرم جدید / انصراف</button>
            </div>
        </form>
        {active&&<section className="taraz-orders-finance"
          aria-label="هزینه واقعی و گردش پرداخت سفارش">
          <h3>هزینه‌ها و وضعیت پول سفارش</h3>
          <p>این بخش فقط پرونده سفارش را به‌روزرسانی می‌کند. ثبت بانکی یا سند قطعی انجام نمی‌شود.</p>
          {dirty&&<p role="alert" className="taraz-orders-hint">
            ابتدا تغییرات فرم سفارش را ذخیره کنید تا اعداد جدید به پرونده درست متصل شوند.</p>}
          <div className="taraz-orders-finance-summary">
            <span>مبلغ توافق‌شده: <b>{financialDisplay(active.estimatedSalesTotal)} {money}</b></span>
            <span>کل هزینه برآوردی: <b>{financialDisplay(active.estimatedCostTotal)} {money}</b></span>
            <span>کل هزینه واقعی تأییدشده: <b>{financialDisplay(active.actualCostTotal)} {money}</b></span>
            <span>مبلغ ثبت‌شده، تأیید تسویه‌نشده: <b>{financialDisplay(active.recordedPaymentTotal)} {money}</b></span>
            <span>مبلغ تسویه‌شده با تأیید مالی: <b>{financialDisplay(active.settledPaymentTotal)} {money}</b></span>
            <span>مانده بر اساس تسویه‌های تأییدشده: <b>{financialDisplay(active.paymentBalance)} {money}</b></span>
            {mode==='advanced'&&<>
              <span>سود برآوردی: <b>{financialDisplay(active.estimatedProfit)} {money}</b></span>
              <span>سود تحقق‌یافته طبق شروط تکمیل: <b>{financialDisplay(active.realizedProfit)} {money}</b></span>
              <span>هزینه‌های واقعی ثبت‌شده، حتی تأییدنشده:
                <b>{financialDisplay(active.recordedActualCostTotal)} {money}</b></span>
            </>}
          </div>
          <h3>ثبت هزینه واقعی مراحل</h3>
          {!active.costStages.length&&<p>ابتدا یک مرحله در فرم سفارش تعریف و ذخیره کنید.</p>}
          {active.costStages.map((stage,index)=>{
            const recorded=active.costRecords?.find(row=>row.stage_index===index);
            const draft=costDrafts[index]||{};
            return <div key={index} className="taraz-orders-finance-line">
              <strong>{index+1}. {STAGES.find(([k])=>k===stage.kind)?.[1]||stage.kind}
                {stage.description?' / '+stage.description:''}</strong>
              <span>برآورد: {financialDisplay(stage.estimatedCost)} {money}
                {' · '}واقعی: {financialDisplay(recorded?.actual_cost)} {money}
                {recorded?' · '+(recorded.status==='approved'?'تأیید مالی':'در انتظار تأیید'):''}</span>
              {recorded?.approved_by&&<small>تأیید: {recorded.approved_by}
                {mode==='advanced'?' / '+recorded.approved_at:''}</small>}
              {recorded?.status!=='approved'&&<div className="taraz-orders-grid">
                <label>هزینه واقعی ({money})
                  <input aria-label={'هزینه واقعی مرحله '+(index+1)} inputMode="numeric"
                    value={draft.actualCost??''} placeholder="نامشخص، نه صفر"
                    onChange={e=>setCostDrafts(old=>({...old,
                      [index]:{...old[index],actualCost:e.target.value}}))}/>
                </label>
                <label>تاریخ هزینه
                  <input type="date" aria-label={'تاریخ هزینه مرحله '+(index+1)}
                    value={draft.costDate??''}
                    onChange={e=>setCostDrafts(old=>({...old,
                      [index]:{...old[index],costDate:e.target.value}}))}/>
                </label>
                <button type="button"
                  aria-label={'انتخاب تاریخ امروز برای هزینه مرحله '+(index+1)}
                  disabled={!canEdit||busy||dirty}
                  onClick={()=>setCostDrafts(old=>({...old,
                    [index]:{...old[index],costDate:localToday()}}))}>
                  امروز
                </button>
                <label>شناسه رسید (اختیاری)
                  <input aria-label={'رسید هزینه مرحله '+(index+1)}
                    maxLength={120} value={draft.receiptReference??''}
                    onChange={e=>setCostDrafts(old=>({...old,
                      [index]:{...old[index],receiptReference:e.target.value}}))}/>
                </label>
                <button type="button" disabled={!canEdit||busy||dirty}
                  onClick={()=>void recordCost(index)}>ثبت هزینه واقعی</button>
              </div>}
              {recorded?.status==='recorded'&&canAdmin&&
                <button type="button" disabled={busy||dirty}
                  onClick={()=>void financeAction('cost.approve',{stageIndex:index},{
                    privileged:true,confirmText:'هزینه واقعی این مرحله با شناسه و مبلغ نمایش‌داده‌شده تأیید شود؟'})}>
                  تأیید مالی هزینه</button>}
            </div>;
          })}
          <h3>ثبت دریافت یا پرداخت</h3>
          <div className="taraz-orders-grid taraz-orders-payment-inputs">
            <label>وضعیت اولیه
              <select aria-label="وضعیت پرداخت جدید" value={paymentDraft.status}
                onChange={e=>setPaymentDraft(old=>({...old,status:e.target.value}))}>
                <option value="planned">برنامه‌ریزی‌شده</option>
                <option value="recorded">ثبت‌شده، هنوز تسویه تأیید نشده</option>
              </select></label>
            <label>مبلغ ({money})
              <input aria-label="مبلغ پرداخت سفارش" inputMode="numeric"
                value={paymentDraft.amount} onChange={e=>setPaymentDraft(old=>({
                  ...old,amount:e.target.value}))}/></label>
            <label>تاریخ
              <input aria-label="تاریخ پرداخت سفارش" type="date"
                value={paymentDraft.paymentDate} onChange={e=>setPaymentDraft(old=>({
                  ...old,paymentDate:e.target.value}))}/></label>
            <label>طرف‌حساب
              <input aria-label="طرف حساب پرداخت سفارش" value={paymentDraft.party}
                onChange={e=>setPaymentDraft(old=>({...old,party:e.target.value}))}/></label>
            <label>روش پرداخت
              <input aria-label="روش پرداخت سفارش" value={paymentDraft.method}
                maxLength={80} placeholder="برای برنامه‌ریزی اختیاری"
                onChange={e=>setPaymentDraft(old=>({...old,method:e.target.value}))}/></label>
            <label>مرجع تراکنش (اختیاری؛ فعلاً ادعای تسویه نیست)
              <input aria-label="مرجع پرداخت سفارش" value={paymentDraft.transactionReference}
                maxLength={120}
                onChange={e=>setPaymentDraft(old=>({...old,transactionReference:e.target.value}))}/></label>
          </div>
          <button type="button" disabled={!canEdit||busy||dirty}
            onClick={()=>void recordPayment()}>ثبت در پرونده سفارش (نه بانک)</button>
          {(active.payments||[]).map(payment=><div className="taraz-orders-finance-line"
            key={payment.id}>
            <strong>{payment.direction==='incoming'?'دریافت':'پرداخت'}،
              {' '}{financialDisplay(payment.amount)} {money}</strong>
            <span>{payment.party} · {payment.payment_date} · {{
              planned:'برنامه‌ریزی‌شده',recorded:'ثبت‌شده، تسویه تأییدنشده',
              settled:'تسویه با تأیید مسئول مالی'}[payment.status]}</span>
            {payment.approved_by&&<small>تأییدکننده: {payment.approved_by}
              {mode==='advanced'?' / '+payment.approved_at:''}</small>}
            {payment.status==='planned'&&<div className="taraz-orders-grid">
              <input aria-label={'روش ثبت '+payment.id} placeholder="روش وقوع پرداخت"
                value={paymentMethods[payment.id]||''}
                onChange={e=>setPaymentMethods(old=>({...old,[payment.id]:e.target.value}))}/>
              <button type="button" disabled={!canEdit||busy||dirty}
                onClick={()=>void financeAction('payment.confirm',{
                  paymentId:payment.id,method:paymentMethods[payment.id]||'',
                  transactionReference:payment.transaction_reference||'',
                })}>ثبت وقوع گزارش‌شده</button>
            </div>}
            {payment.status==='recorded'&&canAdmin&&
              <div className="taraz-orders-grid">
                <input aria-label={'مرجع تسویه '+payment.id}
                  placeholder="شناسه معتبر تراکنش برای تأیید انسانی" maxLength={120}
                  value={settlementRefs[payment.id]||''}
                  onChange={e=>setSettlementRefs(old=>({...old,
                    [payment.id]:e.target.value}))}/>
                <button type="button" disabled={busy||dirty||!settlementRefs[payment.id]?.trim()}
                  onClick={()=>void financeAction('payment.settle',{
                    paymentId:payment.id,
                    transactionReference:settlementRefs[payment.id].trim(),
                  },{privileged:true,confirmText:
                    'مسئول مالی: آیا وقوع تسویه این مبلغ را مستقل از تراز بررسی و تأیید می‌کنید؟'})}>
                  تأیید دستی تسویه</button>
              </div>}
          </div>)}
          {mode==='advanced'&&<section aria-label="تاریخچه تاییدها">
            <h3>تاریخچه تغییرات و تأییدها</h3>
            {(active.auditTrail||[]).map((event,i)=><p key={i}>
              {event.action} · {event.actor} · {event.created_at} ·
              نسخه {event.new_revision}
            </p>)}
          </section>}
          {canAdmin&&active.financialPreview&&!active.financeHandoff&&
            <section className="taraz-orders-handoff" aria-label="پیش‌نمایش ارجاع مالی">
              <h3>پیش‌نمایش ارجاع به حسابداری</h3>
              <p>سفارش {active.id}، طرف حساب {active.financialPreview.customerId}،
                {' '}{financialDisplay(active.financialPreview.agreedTotal)} {money}.
                این عملیات فقط بستهٔ تأییدشدهٔ ارجاع را ثبت می‌کند و سند مالی نمی‌سازد.</p>
              <button type="button" disabled={busy||dirty}
                onClick={()=>void financeAction('handoff.prepare',{
                  previewDigest:active.financialPreview.previewDigest,
                },{privileged:true,confirmText:
                  'آماده‌سازی ارجاع مالی این سفارش با مبلغ، مشتری و Revision نشان‌داده‌شده تأیید شود؟ هیچ سند قطعی صادر نمی‌شود.'})}>
                تأیید بسته ارجاع مالی (بدون صدور سند)</button>
            </section>}
          {active.financeHandoff&&<p role="status">
            بسته ارجاع مالی توسط {active.financeHandoff.prepared_by} آماده شده است.
            صدور سند حسابداری هنوز جدا و نیازمند تأیید است.
          </p>}
          {active.financeHandoff&&canAdmin&&
            <section className="taraz-orders-handoff" aria-label="گیت ایجاد پیش‌نویس حسابداری">
              <h3>ایجاد پیش‌نویس در دفتر حسابداری</h3>
              <p>طرف حساب باید قبلاً در دفتر واقعی تراز ثبت شده باشد. واحد پول باید دقیقاً یکسان باشد.</p>
              <label>تاریخ سند
                <input type="date" aria-label="تاریخ پیش‌نویس حسابداری سفارش"
                  value={financeDocumentDate}
                  onChange={e=>setFinanceDocumentDate(e.target.value)}/>
              </label>
              <button type="button" disabled={busy||dirty||
                typeof api?.tarazOrderFinanceDraft!=='function'}
                onClick={()=>void makeAccountingDraft()}>
                بازبینی و تأیید انسانی ایجاد پیش‌نویس حسابداری</button>
              {financeDraftOutcome&&<p role="status">
                شناسه پیش‌نویس: <code dir="ltr">{financeDraftOutcome.documentId}</code>،
                وضعیت: {financeDraftOutcome.status}. بدون صدور قطعی.</p>}
            </section>}
          {typeof api?.tarazAgentOrderReview==='function'&&
            <section className="taraz-orders-agent" aria-label="دستیار سفارش و حافظه سازمانی">
              <h3>دستیار بررسی سفارش</h3>
              <p>بررسی مبتنی بر داده‌های واقعی همین سفارش است؛ فعلاً مدل زبانی اجرا نمی‌شود.
                پیشنهادها بدون اجازه، سفارش یا دفتر مالی را تغییر نمی‌دهند.</p>
              <label>درخواست فارسی درباره همین سفارش
                <textarea aria-label="درخواست طبیعی عامل سفارش" rows={2}
                  maxLength={1200} value={agentQuery}
                  onChange={e=>setAgentQuery(e.target.value)}
                  placeholder="مثلاً مانده تسویه یا هزینه‌های واقعی این سفارش را بررسی کن"/>
              </label>
              <button type="button" disabled={!canEdit||busy||dirty||agentBusy||
                !agentQuery.trim()||typeof api?.tarazAgentNaturalRequest!=='function'}
                onClick={()=>void requestAgentNatural()}>
                تحلیل مستند درخواست (بدون اقدام خودکار)</button>
              {agentNatural?.sourceRevision===active.revision&&
                <p role="status">روش: قواعد محلی قابل ردیابی؛ اجرای مدل واقعی: خیر.
                  {' '}نوع درخواست: {agentNatural.intent}.
                  {' '}موارد نیازمند بررسی: {agentNatural.missingInformation.length}.
                  {' '}هیچ اقدام یا سند مالی خودکار ایجاد نشده است.</p>}
              <button type="button" disabled={agentBusy||busy||dirty}
                onClick={()=>void loadAgentReview()}>
                {agentBusy?'در حال بازخوانی شواهد...':'بررسی سفارش با ابزارهای محلی'}
              </button>
              {agentError&&<p role="alert" className="taraz-orders-hint">{agentError}</p>}
              {agentNotice&&<p role="status">{agentNotice}</p>}
              {agentReview?.facts?.orderId===active.id&&
                agentReview.facts.revision===active.revision&&<>
                <p role="status">
                  منبع: SQLite واقعی · Revision سفارش {agentReview.facts.revision}
                  {mode==='advanced'&&<>
                    {' · '}SHA شواهد: <code dir="ltr">{agentReview.sourceDigest}</code>
                  </>}
                </p>
                {agentReview.recommendations.length===0?
                  <p>در قواعد فعلی، مورد بازبینی شناخته‌شدهٔ تازه‌ای پیدا نشد.</p>:
                  <div className="taraz-orders-agent-recommendations">
                    {agentReview.recommendations.map((hint,i)=><div key={i}>
                      <p>{AGENT_ACTIONS[hint.action]||'پیشنهاد نیازمند بازبینی تخصصی است.'}</p>
                      <button type="button" disabled={!canEdit||agentBusy}
                        onClick={()=>setAgentDraft(AGENT_ACTIONS[hint.action]||'')}>
                        انتقال به پیش‌نویس یادداشت قابل ویرایش</button>
                    </div>)}
                  </div>}
                {canEdit&&<div className="taraz-orders-agent-propose">
                  <label>یادداشت پیشنهادی سازمان (قبل از ذخیره قابل ویرایش)
                    <textarea aria-label="متن حافظه پیشنهادی سفارش" rows={2}
                      maxLength={800} value={agentDraft}
                      onChange={e=>setAgentDraft(e.target.value)}/>
                  </label>
                  <button type="button" disabled={agentBusy||!agentDraft.trim()}
                    onClick={()=>void changeAgentMemory('propose')}>
                    ثبت پیشنهاد، بدون تأیید خودکار</button>
                </div>}
                <h3>حافظه و تصمیم‌های ثبت‌شده</h3>
                {(agentMemory?.entries||[]).length===0&&
                  <p>برای این سفارش هنوز یادداشت حافظه‌ای ثبت نشده است.</p>}
                {(agentMemory?.entries||[]).map(entry=><div
                  key={entry.id} className="taraz-orders-agent-memory">
                  <p>{entry.body}</p>
                  <span>وضعیت: {{
                    proposed:'در انتظار بررسی انسان',
                    accepted:'پذیرفته‌شده',
                    rejected:'ردشده، بازگشت خودکار ممنوع'}[entry.status]||'نامشخص'}
                    {' · '}ثبت‌کننده: {entry.created_by}</span>
                  {mode==='advanced'&&<small>
                    منبع سفارش Revision {entry.source_revision}،
                    {' '}{entry.source_digest}
                    {entry.reviewed_by?' · بررسی‌کننده: '+entry.reviewed_by:''}
                  </small>}
                  {entry.status==='proposed'&&canAdmin&&
                    <div className="taraz-orders-agent-memory-actions">
                      <button type="button" disabled={agentBusy||busy}
                        onClick={()=>void changeAgentMemory('accept',entry.id)}>
                        تأیید یادداشت</button>
                      <button type="button" disabled={agentBusy||busy}
                        onClick={()=>void changeAgentMemory('reject',entry.id)}>
                        رد یادداشت</button>
                    </div>}
                </div>)}
              </>}
            </section>}
        </section>}
        <p className="taraz-orders-disclaimer">ذخیره و تأیید سفارش، فاکتور یا سند حسابداری صادر نمی‌کند.
          AI و قیمت‌گذاری خودکار تا زمان اتصال و تأیید واقعی فعال نیستند.</p>
      </section>
      <section className="taraz-orders-list" aria-label="فهرست سفارش‌ها">
        <div className="taraz-orders-list-head">
          <h3>سفارش‌های ثبت‌شده</h3>
          <select aria-label="فیلتر وضعیت سفارش" value={filter}
            onChange={e=>setFilter(e.target.value)}>
            <option value="all">همه</option>
            {Object.entries(STATUS).map(([key,label])=>
              <option key={key} value={key}>{label}</option>)}
          </select>
        </div>
        {loading?<p>در حال خواندن سفارش‌ها...</p>:
          visible.length===0?<p className="taraz-orders-empty">
            سفارشی در این فهرست وجود ندارد. ثبت اولین سفارش از فرم کنار صفحه شروع می‌شود.
          </p>:visible.map(item=><article className="taraz-orders-card" key={item.id}>
            <div className="taraz-orders-card-head">
              <strong>{item.title}</strong>
              <span>{STATUS[item.status]||'نامشخص'}</span>
            </div>
            <p>{item.customerName||item.customerId}</p>
            <div className="taraz-orders-card-details">
              <span>{item.kind==='sale'?'فروش':'خرید'} • {item.quantity.toLocaleString('fa-IR')} {item.unit}</span>
              <span>برنامه تولید: {item.productionQuantity.toLocaleString('fa-IR')}</span>
              <span>واقعی: {formatAmount(item.actualProducedQuantity)}</span>
              <span>ضایعات: {formatAmount(item.scrapQuantity)}</span>
              <span>مازاد سالم: {formatAmount(item.healthySurplusQuantity)}</span>
            </div>
            {item.projectReference&&<p>ارجاع پروژه: {item.projectReference}</p>}
            {item.scheduleDueDate&&<p>موعد برنامه‌ریزی‌شده: {item.scheduleDueDate}</p>}
            {item.status==='in_production'&&item.wasteQuantityIsLegacyEstimate===false&&
              item.productionReconciliation?.state!=='balanced'&&
              <p className="taraz-orders-reconciliation incomplete">برای ثبت تحویل، مقادیر واقعی را تراز کنید.</p>}
            <div className="taraz-orders-card-actions">
              <button type="button" disabled={busy} onClick={()=>edit(item)}>
                {item.status==='draft'?'ویرایش / مشاهده':'مشاهده جزئیات'}
              </button>
              {canEdit&&(NEXT[item.status]||[])
                .filter(([next])=>!['approved','delivered'].includes(next)||canAdmin)
                .map(([next,label])=>
                <button type="button" key={next} disabled={busy||
                  (next==='delivered'&&item.wasteQuantityIsLegacyEstimate===false&&
                    item.kind==='sale'&&item.productionReconciliation?.state!=='balanced')}
                  onClick={()=>void transition(item,next)}>
                  {next==='approved'&&<Check size={14}/>} {label}
                </button>)}
            </div>
          </article>)}
        {items.length>=100&&<p className="taraz-orders-hint">فقط ۱۰۰ سفارش آخر نمایش داده شده‌اند.</p>}
      </section>
    </div>
  </section>;
}
