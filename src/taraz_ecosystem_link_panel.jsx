import React,{useCallback,useEffect,useState} from 'react';
import './taraz_ecosystem_link_panel.css';

/** Native-admin-only, manually approved pinned-local-peer connection. */
export default function TarazEcosystemLinkPanel({api,canAdmin=false}){
  const [endpoint,setEndpoint]=useState('');
  const [fingerprint,setFingerprint]=useState('');
  const [code,setCode]=useState('');
  const [consent,setConsent]=useState(false);
  const [connections,setConnections]=useState([]);
  const [cards,setCards]=useState(null);
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [open,setOpen]=useState(false);
  const supported=canAdmin&&
    ['tarazEcosystemConnections','tarazEcosystemPair','tarazEcosystemCards',
      'tarazEcosystemForget'].every(name=>typeof api?.[name]==='function');
  const refresh=useCallback(async()=>{
    const result=await api.tarazEcosystemConnections();
    if(result?.financialEventCreated!==false||!Array.isArray(result.connections))
      throw Error('Invalid integration status');
    setConnections(result.connections);
  },[api]);
  useEffect(()=>{
    if(!supported||!open)return;
    let active=true;
    void api.tarazEcosystemConnections().then(result=>{
      if(active&&result?.financialEventCreated===false&&Array.isArray(result.connections))
        setConnections(result.connections);
    }).catch(()=>{if(active)setError('وضعیت اتصالات قابل تأیید نبود.');});
    return()=>{active=false;};
  },[api,supported,open]);
  const action=async(name,operation)=>{
    setError('');setNotice('');setBusy(name);
    try{await operation();}
    catch(_error){setError('درخواست معتبر انجام نشد؛ دسترسی مدیر، کد یک‌بارمصرف و هویت TLS میزبان را بررسی کنید.');}
    finally{setBusy('');}
  };
  const pair=()=>action('pair',async()=>{
    if(!consent)throw Error('Consent required');
    const result=await api.tarazEcosystemPair({
      endpoint:endpoint.trim(),certSha256:fingerprint.trim().toLowerCase(),
      code:code.trim().toUpperCase(),manualConsent:true,
    });
    if(result?.connected!==true||result?.readOnly!==true||
       result?.financialEventCreated!==false)throw Error('Invalid linked peer');
    setCode('');setConsent(false);setCards(null);
    await refresh();
    setNotice('اتصال خواندنی مدار با هویت و گواهی مشخص ثبت شد. هیچ سند مالی ایجاد نشد.');
  });
  const readCards=workspace=>action('cards',async()=>{
    setCards(null);
    const result=await api.tarazEcosystemCards({workspaceId:workspace,limit:25});
    if(result?.source!=='MADAR'||result?.readOnly!==true||
       result?.financialEventCreated!==false||!Array.isArray(result.cards))
      throw Error('Invalid ACL card page');
    setCards(result);
  });
  const forget=workspace=>action('forget',async()=>{
    if(!window.confirm('فقط اعتبارنامه تراز لغو می‌شود. برای لغو سمت مدار نیز از تنظیمات مدار اقدام کنید. ادامه؟'))return;
    const result=await api.tarazEcosystemForget({workspaceId:workspace});
    if(result?.revokedLocally!==true||result?.financialEventCreated!==false)
      throw Error('Untrusted local revoke');
    setCards(null);await refresh();
    setNotice('اعتبارنامه محلی باطل شد؛ لغو در میزبان مدار هنوز جداگانه لازم است.');
  });
  return <details className="taraz-ecosystem-panel" open={open}
    onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>اتصال نرم‌افزارها · مدار</summary>
    <p>برای اتصال به مدار، ابتدا روی میزبان HTTPS مدار از بخش «اتصال نرم‌افزارها» یک کد موقت بگیرید. اثرانگشت گواهی را از راه مستقل با مدیر میزبان تطبیق دهید. این مسیر فقط کارت‌های مجاز را می‌خواند و به دفترکل دسترسی ندارد.</p>
    {!supported&&<p role="alert">این نسخه یا نشست فعلی، اتصال امن دو برنامه را پشتیبانی نمی‌کند.</p>}
    {supported&&<>
      <div className="taraz-ecosystem-fields">
        <label>نشانی میزبان مدار (HTTPS و IP خصوصی)
          <input dir="ltr" value={endpoint} onChange={e=>setEndpoint(e.target.value)}
            placeholder="https://127.0.0.1:48370" maxLength={160} disabled={!!busy}/>
        </label>
        <label>SHA-256 گواهی TLS مدار (تأییدشده از راه مستقل)
          <input dir="ltr" value={fingerprint} onChange={e=>setFingerprint(e.target.value)}
            placeholder="64 hex characters" maxLength={64} disabled={!!busy}/>
        </label>
        <label>کد اتصال یک‌بارمصرف
          <input dir="ltr" value={code} onChange={e=>setCode(e.target.value)}
            maxLength={13} autoComplete="off" disabled={!!busy}/>
        </label>
        <label><input type="checkbox" checked={consent} disabled={!!busy}
          onChange={e=>setConsent(e.target.checked)}/>
          اتصال این میزبان و خواندن کارت‌های مجاز را تأیید می‌کنم.</label>
      </div>
      <div className="taraz-ecosystem-actions">
        <button type="button" disabled={!!busy||!consent||!code||!endpoint||!fingerprint}
          onClick={pair}>{busy==='pair'?'در حال اتصال...':'اتصال با کد یک‌بارمصرف'}</button>
        <button type="button" disabled={!!busy} onClick={()=>action('refresh',refresh)}>تازه‌سازی اتصال‌ها</button>
      </div>
      <div className="taraz-ecosystem-connections">
        {connections.filter(item=>item.peerId==='MADAR').map(item=><div key={item.workspaceId}>
          <strong>مدار · {item.revoked?'لغوشده':'اتصال ذخیره‌شده'}</strong>
          <small dir="ltr">{item.workspaceId}</small>
          {!item.revoked&&<><button type="button" disabled={!!busy}
            onClick={()=>readCards(item.workspaceId)}>خواندن کارت‌های مجاز</button>
          <button type="button" disabled={!!busy}
            onClick={()=>forget(item.workspaceId)}>قطع اتصال محلی</button></>}
        </div>)}
      </div>
      {cards&&<div className="taraz-ecosystem-cards" role="status">
        <strong>کارت‌های خوانده‌شده: {cards.cards.length}</strong>
        <span>{cards.hasMore?'فهرست ناقص است و صفحه‌های بعدی خوانده نشده‌اند.':'پاسخ در محدودهٔ صفحه کامل است.'}</span>
        {cards.cards.map(card=><div key={card.id}>
          <span>{card.title}</span><small dir="ltr">{card.id}</small>
        </div>)}
      </div>}
    </>}
    {error&&<p role="alert" className="taraz-ecosystem-error">{error}</p>}
    {notice&&<p role="status" className="taraz-ecosystem-success">{notice}</p>}
  </details>;
}
