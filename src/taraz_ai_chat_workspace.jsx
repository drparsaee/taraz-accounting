import React,{useCallback,useEffect,useRef,useState} from 'react';
import {MessageSquarePlus,Search,ShieldCheck,Send,Download,Trash2,RefreshCw} from 'lucide-react';
import './taraz_ai_chat_workspace.css';

const ACTION_STATES={
  proposed:'در انتظار بررسی',
  executed:'پیش‌نویس ذخیره‌شده',
  rejected:'ردشده',
  uncertain:'نیازمند بررسی نتیجه',
};
const APPROVAL_STATES={pending:'تأییدنشده',approved:'تأییدشده',rejected:'ردشده'};
const formatAmount=value=>Number.isSafeInteger(value)?
  value.toLocaleString('fa-IR'):String(value??'نامشخص');
const currencyName=value=>value==='RIAL'?'ریال':value==='TOMAN'?'تومان':String(value||'');

function newClientRequestId(){
  // An unpredictable 128-bit ID is required for durable replay protection.
  // Never fall back to Math.random or a timestamp if WebCrypto is unavailable.
  if(typeof globalThis.crypto?.getRandomValues!=='function'){
    throw new Error('Cryptographic request IDs are unavailable');
  }
  const bytes=new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
}

/** The native bridge owns the authenticated user/company boundary.
 * This UI never keeps chat content in localStorage or a browser cache. */
export default function TarazAiChatWorkspace({api,canEdit=false,canApprove=canEdit}){
  const [items,setItems]=useState([]);
  const [selected,setSelected]=useState('');
  const [history,setHistory]=useState(null);
  const [search,setSearch]=useState('');
  const [listReport,setListReport]=useState({query:'',truncated:false,hasMore:false});
  const [entry,setEntry]=useState('');
  const [confirmReviewed,setConfirmReviewed]=useState({});
  const [provider,setProvider]=useState(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  // Keep IDs after an ambiguous bridge/network failure, so retry is a lookup
  // of the original operation instead of creating another conversation/draft.
  const createAttempt=useRef(null);
  const sendAttempt=useRef(null);
  const listRequestSequence=useRef(0);
  const supported=['tarazAiChatList','tarazAiChatRead','tarazAiChatCommand']
    .every(name=>typeof api?.[name]==='function');
  const applyListResult=useCallback((result,query)=>{
    setItems(Array.isArray(result?.conversations)?result.conversations:[]);
    setListReport({query:query.trim(),truncated:result?.searchTruncated===true,
      hasMore:result?.hasMore===true});
  },[]);
  const refreshList=useCallback(async(query='')=>{
    if(!supported)return;
    const request=++listRequestSequence.current;
    const result=await api.tarazAiChatList(query);
    // An older, slower response must not overwrite a later search.
    if(request===listRequestSequence.current)applyListResult(result,query);
  },[api,supported,applyListResult]);
  const refreshDetail=useCallback(async id=>{
    if(!id){setHistory(null);return;}
    const result=await api.tarazAiChatRead(id);
    setHistory(result);
  },[api]);
  useEffect(()=>{
    let alive=true;
    if(!supported)return;
    const request=++listRequestSequence.current;
    Promise.all([api.tarazAiChatList(''),
      typeof api.tarazAiProviderStatus==='function'?
        api.tarazAiProviderStatus():Promise.resolve(null)])
      .then(([list,status])=>{if(alive){
        if(request===listRequestSequence.current)applyListResult(list,'');
        setProvider(status);
      }})
      .catch(()=>{if(alive)setError('خواندن تاریخچه مجاز نبود یا میزبان آماده نیست.');});
    return ()=>{alive=false;};
  },[api,supported,applyListResult]);
  const run=async task=>{
    setError('');setNotice('');setBusy(true);
    try{await task();}
    catch(_err){setError('عملیات انجام نشد. مجوز، تغییر Revision یا وضعیت میزبان را بررسی کنید؛ برای جلوگیری از تکرار مالی، درخواست را کور تکرار نکنید.');}
    finally{setBusy(false);}
  };
  const newChat=()=>run(async()=>{
    const requestId=createAttempt.current||newClientRequestId();
    createAttempt.current=requestId;
    const result=await api.tarazAiChatCommand({
      action:'create',title:'گفتگوی جدید',clientRequestId:requestId});
    createAttempt.current=null;
    setSelected(result.conversationId);setEntry('');
    await Promise.all([refreshList(search),refreshDetail(result.conversationId)]);
  });
  const selectChat=id=>run(async()=>{setSelected(id);setConfirmReviewed({});await refreshDetail(id);});
  const send=()=>run(async()=>{
    if(!canEdit||!selected||!entry.trim())return;
    const value=entry.trim();
    const payload=JSON.stringify([selected,value]);
    const requestId=sendAttempt.current?.payload===payload?
      sendAttempt.current.id:newClientRequestId();
    sendAttempt.current={payload,id:requestId};
    const result=await api.tarazAiChatCommand({
      action:'send',conversationId:selected,text:value,clientRequestId:requestId});
    sendAttempt.current=null;
    setEntry('');await Promise.all([refreshList(search),refreshDetail(selected)]);
    setNotice(result.status==='READY_FOR_REVIEW'?
      'پیشنهاد فقط آماده بررسی است و هیچ سندی ذخیره نشده.':
      'نتیجهٔ محدودیت‌ها و منابع در گفتگو ثبت شد.');
  });
  const decide=(id,approved)=>run(async()=>{
    if(!canEdit||!selected)return;
    const payload=approved?
      {action:'approve',conversationId:selected,actionId:id,manualConfirmation:true}:
      {action:'reject',conversationId:selected,actionId:id};
    const result=await api.tarazAiChatCommand(payload);
    setConfirmReviewed(p=>({...p,[id]:false}));
    await refreshDetail(selected);
    setNotice(result.status==='DRAFT_SAVED'?
      'پیش‌نویس '+result.invoiceId+' با موفقیت ذخیره شد. سند مالی صادر نشده است.':
      'پیشنهاد رد شد؛ هیچ ثبت مالی انجام نشده است.');
  });
  const reconcile=id=>run(async()=>{
    const result=await api.tarazAiChatCommand({
      action:'reconcile',conversationId:selected,actionId:id});
    await refreshDetail(selected);
    setNotice(result.status==='DRAFT_RECONCILED'?
      'پیش‌نویس قبلی در دفتر پیدا و بدون ثبت دوباره با Audit تطبیق داده شد.':
      'نتیجه هنوز نامشخص است. ثبت دوباره ممنوع و بررسی مستقل لازم است.');
  });
  const deleteChat=()=>run(async()=>{
    if(!selected||!window.confirm('گفتگوی انتخاب‌شده حذف شود؟ سوابق لازم برای ممیزی مالی جداگانه باقی می‌مانند.'))return;
    await api.tarazAiChatCommand({action:'delete',conversationId:selected});
    setSelected('');setHistory(null);await refreshList(search);
  });
  const exportChat=()=>run(async()=>{
    if(!selected)return;
    if(!window.confirm('فایل خروجی JSON بدون رمزگذاری ذخیره می‌شود و می‌تواند شامل متن گفتگو، اطلاعات شرکت و منابع فاکتور باشد. آیا از ذخیره نسخهٔ بدون رمزگذاری در رایانه اطمینان دارید؟'))return;
    const exported=await api.tarazAiChatCommand({action:'export',conversationId:selected});
    const blob=new Blob([JSON.stringify(exported.export,null,2)],{type:'application/json;charset=utf-8'});
    const url=URL.createObjectURL(blob);
    try{
      const link=document.createElement('a');link.href=url;
      link.download='taraz-ai-conversation-'+selected+'.json';
      link.click();
    } finally{setTimeout(()=>URL.revokeObjectURL(url),15000);}
    setNotice('خروجی گفتگو برای ذخیره‌سازی در اختیار شما قرار گرفت.');
  });
  const proposals=history?.executions||[];
  return <section dir="rtl" className="taraz-ai-chat" aria-label="دستیار تجاری و تاریخچه گفتگو">
    <header className="taraz-ai-head">
      <div><h2>دستیار تراز</h2>
        <p>درخواست خود را فارسی بنویسید؛ تراز ابتدا پیشنهاد می‌دهد و فقط پس از تأیید شما پیش‌نویس را ذخیره می‌کند.</p></div>
      <div className="taraz-ai-provider" role="status">
        <ShieldCheck size={17}/> پیشنهاد مبتنی بر اطلاعات همین دفتر
        <small>فعلاً گفتگوی آزاد با مدل زبانی فعال نیست؛ اطلاعات برای مدل ابری ارسال نمی‌شود.</small>
      </div>
    </header>
    {!supported?<div role="alert" className="taraz-ai-alert">
      میزبان فعلی از پایگاه داده و دستورات این نسخه پشتیبانی نمی‌کند. داده‌ای به‌طور موقت ذخیره نمی‌شود.
    </div>:<div className="taraz-ai-layout">
      <aside className="taraz-ai-conversations" aria-label="گفتگوهای پیشین">
        <button type="button" onClick={newChat} disabled={busy||!canEdit}>
          <MessageSquarePlus size={17}/> گفتگوی جدید</button>
        <label><Search size={15}/> جست‌وجوی تاریخچه
          <input value={search} onChange={e=>setSearch(e.target.value)}
            onKeyDown={e=>{if(e.key==='Enter')void run(()=>refreshList(search));}}
            placeholder="عنوان یا متن گفتگو" maxLength={150}/>
        </label>
        <button type="button" onClick={()=>run(()=>refreshList(search))} disabled={busy}>
          <RefreshCw size={15}/> جست‌وجو / بازخوانی</button>
        {listReport.truncated&&<p className="taraz-ai-alert" role="alert" data-testid="taraz-ai-search-truncated">
          جست‌وجوی تاریخچه به سقف پردازش رسید. نتایج نمایش‌داده‌شده ممکن است ناقص باشند؛ عبارت دقیق‌تری جست‌وجو کنید.
        </p>}
        {!listReport.truncated&&listReport.hasMore&&<p className="taraz-ai-notice" role="status" data-testid="taraz-ai-search-more">
          {listReport.query?
            'نتایج بیشتری ممکن است وجود داشته باشد. برای یافتن گفتگوهای دیگر عبارت دقیق‌تری جست‌وجو کنید.':
            'فقط گفتگوهای جدیدتر نمایش داده می‌شوند. برای یافتن گفتگوهای قدیمی‌تر جست‌وجو کنید.'}
        </p>}
        <div className="taraz-ai-conversation-list">
          {items.map(item=><button type="button" key={item.id}
            aria-current={selected===item.id?'page':undefined}
            onClick={()=>selectChat(item.id)} disabled={busy}>
            <span>{item.title}</span><small>{item.updated_at?.slice(0,16)}</small>
          </button>)}
          {!items.length&&<p>{listReport.truncated?
            'در بخش بررسی‌شدهٔ تاریخچه نتیجه‌ای پیدا نشد.':
            listReport.query?'نتیجه‌ای برای این جست‌وجو یافت نشد.':
              'گفتگویی در این حساب ثبت نشده است.'}</p>}
        </div>
      </aside>
      <div className="taraz-ai-thread">
        {selected?<React.Fragment>
          <div className="taraz-ai-thread-toolbar">
            <strong>{history?.conversation?.title||'گفتگو'}</strong>
            <div><button type="button" onClick={exportChat} disabled={busy}>
              <Download size={15}/> خروجی</button>
              <button type="button" onClick={deleteChat} disabled={busy||!canEdit}>
                <Trash2 size={15}/> حذف</button></div>
          </div>
          <div className="taraz-ai-messages" aria-live="polite">
            {(history?.messages||[]).map(message=><article key={message.id}
              className={'taraz-ai-message taraz-ai-'+message.role}>
              <strong>{message.role==='user'?'شما':'دستیار محلی'}</strong>
              <p>{message.content}</p><small>{message.timestamp?.slice(0,19)}</small>
            </article>)}
            {proposals.map(record=><article className="taraz-ai-proposal" key={record.id}
              aria-label="پیشنهاد قابل تأیید">
              <strong>پیشنهاد عملیات: {record.proposal?.ready?'پیش‌نویس فاکتور':'نیازمند تکمیل اطلاعات'}</strong>
              <p>وضعیت: {ACTION_STATES[record.status]||'نیازمند بررسی'} ·
                {' '}{APPROVAL_STATES[record.approval]||'در انتظار'} ·
                {' '}نسخهٔ اطلاعات مرجع: {record.sourceRevision??'نامشخص'}</p>
              {record.proposal?.ready&&<React.Fragment>
                <p data-amount={record.proposal.total}>مشتری: {record.proposal.customerName} | جمع پیشنهادی:
                  {' '}{formatAmount(record.proposal.total)} {currencyName(record.proposal.currency)}</p>
                <table><thead><tr><th>کالا / تعداد</th><th>قیمت واحد</th><th>فاکتور منبع و تاریخ</th></tr></thead>
                  <tbody>{record.proposal.lines.map((line,index)=><tr key={index}>
                    <td>{line.description} / {line.quantity} {line.unit}</td>
                    <td>{formatAmount(line.unitPrice)}</td>
                    <td>{record.proposal.sources[index]?.invoiceId} | {record.proposal.sources[index]?.invoiceDate}</td>
                  </tr>)}</tbody></table>
                <p className="taraz-ai-alert">تخفیف و مالیات پیشنهادی صفر است. این مقادیر باید بررسی شوند.
                  تأیید فقط پیش‌نویس می‌سازد و هیچ سندی صادر نمی‌کند.</p>
                {record.approval==='pending'&&<div className="taraz-ai-review">
                  <label><input type="checkbox" checked={confirmReviewed[record.id]===true}
                    onChange={e=>setConfirmReviewed(p=>({...p,[record.id]:e.target.checked}))}/>
                    مشتری، اقلام، قیمت‌های منبع، مالیات و تخفیف را بررسی کردم.</label>
                  <button type="button" disabled={busy||!canApprove||confirmReviewed[record.id]!==true}
                    onClick={()=>decide(record.id,true)}>تأیید و ذخیره پیش‌نویس</button>
                  <button type="button" disabled={busy||!canEdit}
                    onClick={()=>decide(record.id,false)}>رد پیشنهاد</button>
                </div>}
                {record.approval==='approved'&&record.status==='uncertain'&&
                  <div className="taraz-ai-review">
                    <p>نتیجه ذخیره قبلی نامشخص است؛ برای جلوگیری از ثبت تکراری فقط تطبیق خواندنی مجاز است.</p>
                    <button type="button" disabled={busy||!canApprove}
                      onClick={()=>reconcile(record.id)}>تطبیق نتیجه نامشخص بدون ثبت دوباره</button>
                  </div>}
              </React.Fragment>}
              {!!record.proposal?.missing?.length&&<p>داده‌های ناقص: {record.proposal.missing.map(x=>x.item||x).join('، ')}</p>}
            </article>)}
          </div>
          <form className="taraz-ai-compose" onSubmit={e=>{e.preventDefault();send();}}>
            <label htmlFor="taraz-ai-user-request">دستور فارسی شما</label>
            <textarea id="taraz-ai-user-request" rows={3} value={entry}
              maxLength={4000} onChange={e=>setEntry(e.target.value)}
              disabled={!canEdit||busy}
              placeholder="برای شرکت ... فاکتور فروش بساز. ۱۰۰ عدد ... اضافه کن. قیمت را از آخرین فاکتور همین مشتری بردار."/>
            <button type="submit" disabled={busy||!canEdit||!entry.trim()}>
              <Send size={16}/> ثبت درخواست و تهیه پیشنهاد</button>
          </form>
        </React.Fragment>:<div className="taraz-ai-empty">
          برای ساخت فاکتور از متن فارسی، «گفتگوی جدید» را انتخاب کنید.
          گفتگوهای قبلی هم در همین صفحه باقی می‌مانند.
        </div>}
        {error&&<p className="taraz-ai-alert" role="alert">{error}</p>}
        {notice&&<p role="status" className="taraz-ai-notice">{notice}</p>}
      </div>
    </div>}
  </section>;
}
