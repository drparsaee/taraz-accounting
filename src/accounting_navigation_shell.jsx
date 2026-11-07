import React from 'react';
import {ArrowRight,Building2,FilePlus2,Landmark,MoreHorizontal,Printer,
  RefreshCw,Search,Settings2,ShieldCheck,Users,Wallet,FileText,Layers3} from 'lucide-react';
import AccountingGlobalSearch from './accounting_global_search.jsx';
import {ACCOUNTING_PRIMARY_SECTIONS,accountingVisibleSections,
  buildAccountingSearchIndex} from './accounting_nav_search.js';
import './accounting_navigation_shell.css';

const SHORT_LABELS={overview:'خانه',invoice:'فروش',bill:'خرید',
  settlements:'دریافت و پرداخت',reports:'گزارش‌ها'};
const NAV_ICONS={overview:Landmark,invoice:FileText,bill:Layers3,
  settlements:Wallet,reports:FileText};

/**
 * Wiring contract (host-authorized, company-scoped data only):
 * searchView = current standaloneAccountingRead().view, never another company's
 * snapshot or raw Parsian archive; currentUser.role must be host-authenticated.
 * onSearchSelect({kind,id,tab}) opens a specific authorized record. Until it is
 * connected, search covers navigation only, rather than false deep links.
 * onQuickAction('payment'|'purchase') may select the right composer; if omitted,
 * existing settlement/purchase pages open, with no financial mutation.
 * sectionAccess and recordAccess are optional *restrictive* allowlists (false
 * hides an item). Host ACL remains the only authority to read/write money.
 */
export default function AccountingNavigationShell({tab,sections=[],groups=[],groupFor,
  onNavigate=()=>{},onNewInvoice=()=>{},onPrint=()=>{},
  canDraft=false,canManage=false,canAdmin=false,hasPrintableInvoice=false,
  currency='ریال',companyName='',currentUser=null,onRefresh=()=>{},onExit=()=>{},
  onSwitchCompany=null,onManageUsers=null,onBack=null,
  backLabel='بازگشت به صفحه اصلی',disabled=false,
  searchView=null,recordAccess=null,sectionAccess=null,
  onSearchSelect=null,onQuickAction=null}){
  const role=['viewer','editor','admin'].includes(currentUser?.role)?currentUser.role:
    canAdmin?'admin':canManage?'editor':'viewer';
  const permittedDraft=canDraft&&(role==='editor'||role==='admin');
  const permittedManage=canManage&&(role==='editor'||role==='admin');
  const permittedAdmin=canAdmin&&role==='admin';
  const [mode,setMode]=React.useState('simple');
  const [chosen,setChosen]=React.useState('');
  const [moreOpen,setMoreOpen]=React.useState(false);
  const [searchOpen,setSearchOpen]=React.useState(false);
  const moreRef=React.useRef(null);
  const searchButtonRef=React.useRef(null);
  const searchLabelId=React.useId();
  const searchShortcutId=React.useId();
  const visible=React.useMemo(()=>accountingVisibleSections(sections,role,sectionAccess),
    [sections,role,sectionAccess]);
  const labels=React.useMemo(()=>new Map(visible),[visible]);
  const index=React.useMemo(()=>buildAccountingSearchIndex({
    sections:visible,view:typeof onSearchSelect==='function'?searchView:null,
    role,recordAccess,sectionAccess
  }),[visible,searchView,onSearchSelect,role,recordAccess,sectionAccess]);
  const active=groups.find(group=>group.id===(chosen||(groupFor?.(tab)||'general')))||groups[0];
  const primary=ACCOUNTING_PRIMARY_SECTIONS.filter(key=>labels.has(key));
  const secondary=visible.filter(([key])=>!primary.includes(key));
  React.useEffect(()=>{setChosen('');setMoreOpen(false);},[tab]);
  React.useEffect(()=>{
    const keyDown=event=>{
      if(disabled||event.isComposing)return;
      if((event.ctrlKey||event.metaKey)&&!event.altKey&&
        event.key.toLocaleLowerCase('en-US')==='k'){
        event.preventDefault();setMoreOpen(false);setSearchOpen(true);
      }
      if(event.key==='Escape'&&moreOpen){
        setMoreOpen(false);
        [...document.querySelectorAll('.sac-nav-more-trigger')]
          .find(el=>el.getClientRects().length)?.focus();
      }
    };
    document.addEventListener('keydown',keyDown);
    return ()=>document.removeEventListener('keydown',keyDown);
  },[disabled,moreOpen]);
  React.useEffect(()=>{
    if(!moreOpen)return;
    const outside=event=>{
      if(!moreRef.current?.contains(event.target)&&
         !event.target.closest?.('.sac-nav-more-trigger'))setMoreOpen(false);
    };
    document.addEventListener('pointerdown',outside);
    return ()=>document.removeEventListener('pointerdown',outside);
  },[moreOpen]);
  const navigate=key=>{
    if(disabled||!labels.has(key))return false;
    const result=onNavigate(key);
    if(result!==false)setMoreOpen(false);
    return result;
  };
  const quick=action=>{
    if(disabled)return;
    if(action==='invoice'){
      if(permittedDraft&&onNewInvoice()!==false)setMoreOpen(false);
      return;
    }else if(action==='payment'){
      if(permittedManage){if(onQuickAction)onQuickAction('payment');else navigate('settlements');}
    }else if(action==='purchase'){
      if(permittedDraft){if(onQuickAction)onQuickAction('purchase');else navigate('bill');}
    }else if(action==='reports')navigate('reports');
    setMoreOpen(false);
  };
  const searchSelect=result=>{
    if(result.type==='section')return navigate(result.tab);
    if(typeof onSearchSelect==='function')return onSearchSelect({
      kind:result.type,id:result.recordId,tab:result.tab});
    return false;
  };
  const closeSearch=()=>{
    setSearchOpen(false);
    searchButtonRef.current?.focus();
  };
  const moreButton=()=> <button type="button"
    className={'sac-nav-more-trigger'+(moreOpen?' active':'')}
    data-accounting-action="more"
    aria-expanded={moreOpen} aria-controls="sac-nav-more-panel" disabled={disabled}
    onClick={()=>setMoreOpen(open=>!open)}>
    <MoreHorizontal size={16}/> بیشتر
  </button>;
  return <div className={'sac-ribbon-shell sac-ux-shell sac-ux-'+mode}>
    <div className="sac-ribbon-titlebar">
      <div className="sac-ribbon-identity"><span className="sac-ribbon-app-icon"><Landmark size={22}/></span>
        <span><strong>تراز | حسابداری مستقل</strong>
          <small>محیط کار مالی · {companyName||'دفتر مستقل'}</small></span></div>
      <div className="sac-ribbon-quick" aria-label="دسترسی سریع حسابداری">
        {currentUser?.username&&<span className="sac-ribbon-user">
          <Users size={14} aria-hidden="true"/>{currentUser.username}</span>}
        <button ref={searchButtonRef} type="button" className="sac-nav-search-trigger"
          data-accounting-action="search"
          disabled={disabled} onClick={()=>{setMoreOpen(false);setSearchOpen(true);}}
          aria-labelledby={searchLabelId+' '+searchShortcutId}
          aria-keyshortcuts="Control+K Meta+K" title="جست‌وجوی سوابق دفتر جاری (Ctrl+K)">
          <Search size={17}/> <span id={searchLabelId}>جست‌وجو</span>{' '}
          <kbd id={searchShortcutId}>Ctrl+K</kbd></button>
        <div role="group" className="sac-nav-mode" aria-label="سطح نمایش حسابداری">
          <button type="button" aria-pressed={mode==='simple'}
            disabled={disabled} onClick={()=>{setMode('simple');setMoreOpen(false);}}>ساده</button>
          <button type="button" aria-pressed={mode==='advanced'}
            disabled={disabled} onClick={()=>{setMode('advanced');setMoreOpen(false);}}>پیشرفته</button>
        </div>
        {tab!=='overview'&&onBack&&<button type="button" className="sac-ribbon-back"
          disabled={disabled} onClick={onBack} title={backLabel}>
          <ArrowRight size={16}/> <span>{backLabel}</span></button>}
        <span className="sac-ribbon-unit" title="واحد دفتر حسابداری">{currency}</span>
        <button type="button" className="sac-ribbon-exit" onClick={onExit}>خروج</button>
      </div>
    </div>
    <div className="sac-simple-navigation">
      <nav className="sac-simple-nav" aria-label="مسیرهای اصلی حسابداری">
        {primary.map(key=>{
          const Icon=NAV_ICONS[key]||Landmark;
          return <button key={key} type="button" disabled={disabled}
            data-accounting-tab={key}
            aria-current={tab===key?'page':undefined} onClick={()=>navigate(key)}>
            <Icon size={17}/><span>{SHORT_LABELS[key]||labels.get(key)}</span></button>;
        })}
        {moreButton()}
      </nav>
      <div className="sac-nav-quick-actions" role="group" aria-label="کارهای پرتکرار حسابداری">
        {permittedDraft&&<button type="button" data-accounting-action="invoice" disabled={disabled} onClick={()=>quick('invoice')}>
          <FilePlus2 size={16}/> فاکتور جدید</button>}
        {permittedManage&&<button type="button" data-accounting-action="payment" disabled={disabled} onClick={()=>quick('payment')}>
          <Wallet size={16}/> {onQuickAction?'ثبت پرداخت':'دریافت و پرداخت'}</button>}
        {permittedDraft&&<button type="button" data-accounting-action="purchase" disabled={disabled} onClick={()=>quick('purchase')}>
          <FileText size={16}/> خرید جدید</button>}
        <button type="button" data-accounting-action="reports" disabled={disabled} onClick={()=>quick('reports')}>
          <Layers3 size={16}/> گزارش‌ها</button>
      </div>
    </div>
    {mode==='advanced'&&<div className="sac-advanced-ribbon">
      <nav aria-label="دسته‌بندی‌های حسابداری" className="sac-ribbon-tabs" tabIndex={0}>
        {groups.map(group=>{const Icon=group.icon;
          return <button key={group.id} type="button" disabled={disabled}
            aria-pressed={active?.id===group.id} onClick={()=>setChosen(group.id)}
            className={active?.id===group.id?'active':''}>
            <Icon size={16}/>{group.title}</button>;
        })}
      </nav>
      <nav className="sac-ribbon-tools" aria-label="فرمان‌های گروه انتخاب‌شده" tabIndex={0}>
        {active?.items.filter(key=>labels.has(key)).map(key=><button key={key}
          type="button" data-accounting-tab={key} onClick={()=>navigate(key)} disabled={disabled}
          aria-current={tab===key?'page':undefined} className={tab===key?'selected':''}>
          {labels.get(key)}</button>)}
        {active?.id==='documents'&&permittedDraft&&<button className="sac-ribbon-highlight"
          type="button" onClick={()=>quick('invoice')} disabled={disabled}>
          <FilePlus2 size={16}/> ثبت فاکتور جدید</button>}
        {active?.id==='settings'&&<span className="sac-ribbon-hint">
          <ShieldCheck size={14}/> دفتر مالی شرکت مستقل است</span>}
        {permittedManage&&<button type="button" onClick={onPrint}
          disabled={disabled||!hasPrintableInvoice} title="دریافت PDF فاکتور انتخاب‌شده">
          <Printer size={16}/> PDF فاکتور</button>}
        <button type="button" onClick={onRefresh} disabled={disabled}>
          <RefreshCw size={16}/> بازخوانی</button>
        {permittedAdmin&&onManageUsers&&<button type="button" disabled={disabled}
          onClick={onManageUsers}><Users size={16}/> کاربران</button>}
        {onSwitchCompany&&<button type="button" disabled={disabled} onClick={onSwitchCompany}>
          <Building2 size={16}/> تغییر شرکت</button>}
        <button type="button" data-accounting-tab="settings" disabled={disabled} onClick={()=>navigate('settings')}>
          <Settings2 size={16}/> تنظیمات</button>
        <span className="sac-nav-more-advanced">{moreButton()}</span>
      </nav>
    </div>}
    {moreOpen&&<section id="sac-nav-more-panel" className="sac-nav-more-menu" ref={moreRef}
      role="region" aria-label="بخش‌های بیشتر حسابداری">
      <div className="sac-nav-more-heading"><strong>بخش‌های بیشتر</strong>
        <span>{mode==='advanced'?'همهٔ بخش‌های مجاز':'ادامهٔ امکانات حسابداری'}</span></div>
      <nav aria-label="فهرست بخش‌های دیگر">
        {(mode==='simple'?secondary:visible).map(([key,label])=><button type="button"
          key={key} data-accounting-tab={key} disabled={disabled} aria-current={tab===key?'page':undefined}
          onClick={()=>navigate(key)}>{label}</button>)}
      </nav>
      <div className="sac-nav-more-actions" role="group" aria-label="دسترسی‌های تکمیلی">
        {permittedDraft&&<button type="button" onClick={()=>quick('invoice')} disabled={disabled}>فاکتور جدید</button>}
        {permittedManage&&<button type="button" onClick={()=>quick('payment')} disabled={disabled}>{onQuickAction?'ثبت پرداخت':'دریافت و پرداخت'}</button>}
        {permittedDraft&&<button type="button" onClick={()=>quick('purchase')} disabled={disabled}>خرید جدید</button>}
        <button type="button" onClick={()=>quick('reports')} disabled={disabled}>گزارش‌ها</button>
      </div>
    </section>}
    <AccountingGlobalSearch open={searchOpen} index={index} disabled={disabled}
      onClose={closeSearch} onSelect={searchSelect}/>
  </div>;
}
