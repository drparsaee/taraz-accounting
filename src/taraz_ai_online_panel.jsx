import React,{useEffect,useState} from 'react';
import './taraz_ai_online_panel.css';

const ENDPOINTS={
  openai:'https://api.openai.com/v1/chat/completions',
  anthropic:'https://api.anthropic.com/v1/messages',
};
const METHODS=['tarazAiOnlineStatus','tarazAiOnlineConfigure',
  'tarazAiOnlineClear','tarazAiOnlineHealth','tarazAiOnlineGenerate'];

/** Online text is isolated: never forward chat, company or accounting state. */
export default function TarazAiOnlinePanel({api,canEdit=false}){
  const supported=METHODS.every(name=>typeof api?.[name]==='function');
  const [status,setStatus]=useState(null);
  const [provider,setProvider]=useState('openai');
  const [endpoint,setEndpoint]=useState(ENDPOINTS.openai);
  const [model,setModel]=useState('');
  const [apiKey,setApiKey]=useState('');
  const [inputPrice,setInputPrice]=useState('2');
  const [outputPrice,setOutputPrice]=useState('4');
  const [text,setText]=useState('');
  const [maxCost,setMaxCost]=useState('0.02');
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [answer,setAnswer]=useState(null);
  const [tls,setTls]=useState(null);

  const applyStatus=found=>{
    setStatus(found);
    if(found?.configured===true){
      setProvider(found.provider);
      setEndpoint(found.endpoint);
      setModel(found.model);
      setInputPrice(found.inputUsdPerMillion);
      setOutputPrice(found.outputUsdPerMillion);
    }
  };
  useEffect(()=>{
    let active=true;
    if(!supported)return;
    api.tarazAiOnlineStatus().then(found=>{if(active)applyStatus(found);})
      .catch(()=>{if(active)setError('وضعیت آنلاین قابل خواندن نیست؛ احراز هویت یا مجوز شرکت را بررسی کنید.');});
    return ()=>{active=false;};
  },[api,supported]);
  const showError=err=>{
    // Never echo raw provider error messages, which may carry private data.
    const kind=String(err?.name||'')+' '+String(err?.message||'');
    setError(/PermissionError|authenticated|administrator|session|مجوز|احراز/.test(kind)?
      'نشست معتبر یا مجوز لازم وجود ندارد؛ مدیر شرکت باید در تراز وارد شود.':
      'عملیات تأیید نشد. تنظیمات، سقف هزینه یا ارتباط امن را بررسی کنید.');
  };
  const perform=async operation=>{
    if(!supported||busy)return;
    setBusy(true);setError('');setNotice('');
    try{await operation();}catch(err){showError(err);}
    finally{setBusy(false);setConsent(false);}
  };
  const configure=event=>{
    event.preventDefault();
    if(!canEdit||!consent||!apiKey||!model.trim())return;
    void perform(async()=>{
      const result=await api.tarazAiOnlineConfigure({
        provider,endpoint,model,apiKey,
        inputUsdPerMillion:inputPrice,outputUsdPerMillion:outputPrice,
        manualConsent:true,
      });
      setApiKey('');setTls(null);setAnswer(null);applyStatus(result);
      setNotice('تنظیمات فقط در خزانهٔ ویندوز ذخیره شد. اعتبار کلید و اتصال واقعی تأیید نشده‌اند.');
    });
  };
  const clear=()=>{
    if(!canEdit||!consent)return;
    if(typeof window.confirm==='function'&&
       !window.confirm('کلید فقط از این رایانه حذف شود؟ ابطال کلید نزد ارائه‌دهنده جداست.'))return;
    void perform(async()=>{
      const result=await api.tarazAiOnlineClear({manualConsent:true});
      if(result?.clearedLocally!==true)throw Error('Unverified clear');
      setApiKey('');setTls(null);setAnswer(null);
      applyStatus(await api.tarazAiOnlineStatus());
      setNotice('کلید محلی حذف شد؛ ابطال آن نزد ارائه‌دهنده تأیید نشده است.');
    });
  };
  const health=()=>{
    if(!canEdit||!consent||status?.configured!==true)return;
    void perform(async()=>{
      const result=await api.tarazAiOnlineHealth({manualConsent:true});
      if(result?.tlsReachable!==true||result.credentialsVerified!==false)
        throw Error('Unverified TLS probe');
      setTls(result);
      setNotice('فقط TLS آزموده شد؛ اعتبار کلید و امکان پاسخ مدل تأیید نشده‌اند.');
    });
  };
  const ask=event=>{
    event.preventDefault();
    if(!canEdit||!consent||!text.trim()||status?.configured!==true)return;
    void perform(async()=>{
      setAnswer(null);
      // Only the text manually typed in this field is transmitted.
      const result=await api.tarazAiOnlineGenerate({
        text:text.trim(),manualConsent:true,maxEstimatedUsd:maxCost,
      });
      if(result?.modelRan!==true||result.externalTransmission!==true||
         result.financialActionsEnabled!==false||result.journalPosted!==false||
         typeof result.response!=='string')throw Error('Unverified provider response');
      setAnswer(result);setText('');
    });
  };
  const available=status?.configured===true;
  const canTransmit=status?.externalTransmissionEnabled===true;
  return <details className="taraz-online-ai-panel" data-testid="taraz-online-ai-panel">
    <summary>هوش مصنوعی آنلاین (فقط متن غیرمالی با رضایت جداگانه)</summary>
    <p className="taraz-online-ai-warning">این بخش از گفتگوها، فاکتورها و دفترکل مستقل است.
      هیچ اطلاعات شرکتی خودکار ارسال نمی‌شود. درخواست اینترنتی ممکن است هزینه و
      پیامد حریم خصوصی داشته باشد؛ مدل آنلاین اجازهٔ تصمیم یا اقدام مالی ندارد.</p>
    {!supported?<p role="alert">این میزبان از API آنلاین پشتیبانی نمی‌کند؛ هیچ ارسال آنلاینی فعال نیست.</p>:<>
      <p role="status" data-testid="taraz-online-status">{status===null?
        'وضعیت محلی هنوز تأیید نشده است.':available?
          'تنظیمات ذخیره شده‌اند: '+status.provider+' / '+status.model+
          '. اعتبار کلید و اتصال زنده بررسی نشده‌اند.':
          'هیچ ارائه‌دهندهٔ آنلاینی در این شرکت تنظیم نشده است.'}</p>
      <p className="taraz-online-ai-error" role="status"
        data-testid="taraz-online-transmission-disabled">
        ارسال آنلاین و بررسی TLS فعلاً در میزبان غیرفعال‌اند. رضایت واقعی بومی و
        محدودیت هزینهٔ تجمعی هنوز تأیید نشده‌اند. ذخیرهٔ محلی کلید به معنی فعال‌شدن سرویس نیست.
      </p>
      <button type="button" disabled={busy} onClick={()=>void perform(async()=>{
        applyStatus(await api.tarazAiOnlineStatus());
        setNotice('فقط وضعیت محلی بازخوانی شد؛ درخواست اینترنتی ارسال نشد.');
      })}>بازخوانی تنظیمات محلی</button>
      <form onSubmit={configure} className="taraz-online-ai-form" autoComplete="off">
        <h3>تنظیم ارائه‌دهنده، فقط مدیر شرکت</h3>
        <div className="taraz-online-ai-grid">
          <label>ارائه‌دهنده
            <select value={provider} disabled={busy||!canEdit}
              onChange={e=>{setProvider(e.target.value);setEndpoint(ENDPOINTS[e.target.value]);}}>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label>مدل انتخابی
            <input value={model} onChange={e=>setModel(e.target.value)} maxLength={100}
              disabled={busy||!canEdit} autoComplete="off" placeholder="نام دقیق مدل"/>
          </label>
          <label className="taraz-online-ai-wide">نشانی دقیق HTTPS
            <input dir="ltr" value={endpoint} onChange={e=>setEndpoint(e.target.value)}
              disabled={busy||!canEdit} maxLength={160} autoComplete="off"/>
          </label>
          <label className="taraz-online-ai-wide">کلید API
            <input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)}
              disabled={busy||!canEdit} maxLength={512} autoComplete="new-password"
              placeholder="کلید فقط هنگام ذخیره به میزبان بومی می‌رود"/>
          </label>
          <label>تعرفهٔ ورودی (دلار برای یک میلیون توکن)
            <input type="text" dir="ltr" value={inputPrice}
              onChange={e=>setInputPrice(e.target.value)} disabled={busy||!canEdit}/>
          </label>
          <label>تعرفهٔ خروجی (دلار برای یک میلیون توکن)
            <input type="text" dir="ltr" value={outputPrice}
              onChange={e=>setOutputPrice(e.target.value)} disabled={busy||!canEdit}/>
          </label>
        </div>
        <p>فقط دو endpoint رسمی پذیرفته می‌شوند. مدل و قیمت را شما تعیین می‌کنید؛
          صحت تعرفه یا اعتبار کلید به‌صورت خودکار تأیید نمی‌شود.</p>
        <label className="taraz-online-ai-consent">
          <input type="checkbox" checked={consent} disabled={busy||!canEdit}
            onChange={e=>setConsent(e.target.checked)}/>
          این اقدام را خودم درخواست کرده‌ام و پیامد ذخیره، حذف یا ارتباط آنلاین را می‌دانم.
        </label>
        <div className="taraz-online-ai-actions">
          <button type="submit" disabled={busy||!canEdit||!consent||!model.trim()||!apiKey}>
            ذخیرهٔ امن تنظیمات</button>
          <button type="button" disabled={busy||!canEdit||!consent||!available}
            onClick={clear}>حذف کلید محلی</button>
          <button type="button" disabled={busy||!canEdit||!consent||!available||!canTransmit}
            onClick={health}>بررسی TLS بدون کلید</button>
        </div>
      </form>
      <form onSubmit={ask} className="taraz-online-ai-form" autoComplete="off">
        <h3>درخواست مستقل متن غیرمالی</h3>
        <label>متن فقط به انتخاب شما
          <textarea value={text} rows={3} maxLength={1000} disabled={busy||!canEdit||!canTransmit}
            onChange={e=>setText(e.target.value)}
            placeholder="برای خوشامدگویی عمومی سه جملهٔ کوتاه بنویس."/>
        </label>
        <label>سقف هزینهٔ برآوردی دلار (حداکثر 0.02)
          <input type="text" dir="ltr" value={maxCost}
            onChange={e=>setMaxCost(e.target.value)} disabled={busy||!canEdit||!canTransmit}/>
        </label>
        <button type="submit" disabled={busy||!canEdit||!available||!canTransmit||!consent||!text.trim()}>
          {busy?'در حال دریافت…':'ارسال همین متن با رضایت صریح'}</button>
      </form>
      {tls?.tlsReachable===true&&<p role="status">
        TLS در آخرین بررسی پاسخ داد؛ اعتبار کلید هنوز نامشخص است.</p>}
      {answer&&<section className="taraz-online-ai-answer" aria-label="پاسخ متنی آنلاین">
        <strong>پاسخ {answer.provider}؛ نیازمند بررسی انسانی</strong>
        <p>{answer.response}</p>
        <small>هزینهٔ تخمینی: {answer.estimatedCostUsd} دلار؛ سقف واقعی صورتحساب تضمین نمی‌شود.</small>
      </section>}
      {error&&<p role="alert" className="taraz-online-ai-error">{error}</p>}
      {notice&&<p role="status">{notice}</p>}
      <small>ذخیرهٔ تنظیمات به معنای اتصال زنده یا صلاحیت مدل برای کار مالی نیست.
        متن هر درخواست فقط با دکمهٔ ارسال و رضایت جداگانه منتقل می‌شود.</small>
    </>}
  </details>;
}
