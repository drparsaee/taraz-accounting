import React from 'react';
import {ArrowRight,Building2,FilePlus2,Landmark,Menu,Printer,
  RefreshCw,Search,Settings2,ShieldCheck,Users,Wallet,FileText,Layers3,
  Sun,Moon,X,CheckCircle2,ChevronLeft,BookOpen,ReceiptText} from 'lucide-react';
import AccountingGlobalSearch from './accounting_global_search.jsx';
import {readTarazSettings,saveTarazSettings,applyTarazSettings}
  from './taraz_settings_preferences.js';
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
  const [moreOpen,setMoreOpen]=React.useState(false);
  const [theme,setTheme]=React.useState(()=>document.documentElement.dataset.theme==='light'?'light':'dark');
  const [searchOpen,setSearchOpen]=React.useState(false);
  const moreRef=React.useRef(null);
  const menuButtonRef=React.useRef(null);
  const searchButtonRef=React.useRef(null);
  const visible=React.useMemo(()=>accountingVisibleSections(sections,role,sectionAccess),
    [sections,role,sectionAccess]);
  React.useEffect(()=>{
    const sync=()=>{
      const settings=readTarazSettings();
      applyTarazSettings(settings);
      setTheme(document.documentElement.dataset.theme==='light'?'light':'dark');
    };
    sync();
    const media=globalThis.matchMedia?.('(prefers-color-scheme: dark)');
    media?.addEventListener?.('change',sync);
    globalThis.addEventListener?.('taraz-settings-change',sync);
    globalThis.addEventListener?.('storage',sync);
    return()=>{
      media?.removeEventListener?.('change',sync);
      globalThis.removeEventListener?.('taraz-settings-change',sync);
      globalThis.removeEventListener?.('storage',sync);
    };
  },[]);
  const labels=React.useMemo(()=>new Map(visible),[visible]);
  const index=React.useMemo(()=>buildAccountingSearchIndex({
    sections:visible,view:typeof onSearchSelect==='function'?searchView:null,
    role,recordAccess,sectionAccess
  }),[visible,searchView,onSearchSelect,role,recordAccess,sectionAccess]);
  const primary=ACCOUNTING_PRIMARY_SECTIONS.filter(key=>labels.has(key));
  React.useEffect(()=>{setMoreOpen(false);},[tab]);
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
  const toggleTheme=()=>{
    const next=theme==='dark'?'light':'dark';
    saveTarazSettings({...readTarazSettings(),theme:next});
    setTheme(next);
  };
  const closeMenu=()=>{setMoreOpen(false);menuButtonRef.current?.focus();};
  React.useEffect(()=>{
    if(!moreOpen)return;
    const root=moreRef.current;
    if(!root)return;
    const first=root.querySelector('button:not(:disabled)');
    first?.focus();
    const trap=event=>{
      if(event.key!=='Tab')return;
      const items=[...root.querySelectorAll('button:not(:disabled),[href],input:not(:disabled)')];
      if(!items.length)return;
      const start=items[0],end=items[items.length-1];
      if(event.shiftKey&&document.activeElement===start){event.preventDefault();end.focus();}
      else if(!event.shiftKey&&document.activeElement===end){event.preventDefault();start.focus();}
    };
    root.addEventListener('keydown',trap);
    return ()=>root.removeEventListener('keydown',trap);
  },[moreOpen]);
  const actionDisabled=disabled;
  const fullNavIcon={
    overview:Landmark,invoice:FileText,bill:Layers3,proforma:ReceiptText,
    parties:Users,company:Building2,settlements:Wallet,cash:Wallet,
    cheques:ReceiptText,accounts:BookOpen,journal:BookOpen,
    reports:Layers3,settings:Settings2,items:Layers3,
    migration:BookOpen,period:CheckCircle2
  };
  return <div className="sac-ribbon-shell sac-ux-shell taraz-vt-shell">
    <div className="taraz-vt-topline">
      <button type="button" className="taraz-vt-brand" onClick={()=>navigate('overview')}
        style={theme==='light'?{background:'#f8fbff',color:'#172538',borderColor:'#c2cbd8'}:undefined}
        disabled={disabled} title="خانه تراز">
        <img src="./taraz-icon.svg" width="36" height="36" alt="" />
        <span><strong>تراز</strong><small>حسابداری مستقل</small></span>
      </button>
      <nav className="sac-simple-nav taraz-vt-primary" aria-label="صفحه‌های اصلی تراز">
        {primary.map(key=>{
          const Icon=NAV_ICONS[key]||Landmark;
          return <button type="button" key={key} data-accounting-tab={key}
            aria-current={tab===key?'page':undefined} onClick={()=>navigate(key)}
            disabled={disabled}>
            <Icon size={17} aria-hidden="true"/><span>{SHORT_LABELS[key]||labels.get(key)}</span>
          </button>;
        })}
      </nav>
      <div className="taraz-vt-top-actions">
        {currentUser?.username&&<span className="taraz-vt-user" title={currentUser.username}>
          <Users size={16}/><span>{currentUser.username}</span></span>}
        <span className="taraz-vt-currency" title="واحد دفتر حسابداری">{currency}</span>
        <button type="button" className="taraz-vt-search-trigger"
          ref={searchButtonRef} data-accounting-action="search"
          disabled={actionDisabled} aria-keyshortcuts="Control+K Meta+K"
          title="جست‌وجو (Ctrl+K)" aria-label="جست‌وجو در تراز"
          onClick={()=>{setMoreOpen(false);setSearchOpen(true);}}>
          <Search size={18}/><span>جست‌وجو</span><kbd>Ctrl+K</kbd>
        </button>
      </div>
    </div>
    <div className="taraz-vt-dock" role="toolbar" aria-label="میان‌برهای تراز">
      <button ref={menuButtonRef} type="button" className="sac-nav-more-trigger"
        data-accounting-action="more" disabled={disabled}
        aria-label="بازکردن فهرست بخش‌های تراز" title="فهرست بخش‌ها"
        aria-controls="taraz-vt-drawer" aria-expanded={moreOpen}
        onClick={()=>setMoreOpen(open=>!open)}><Menu size={21}/></button>
      <span className="taraz-vt-dock-divider"/>
      {permittedDraft&&<button type="button" className="taraz-vt-create" disabled={disabled}
        data-accounting-action="invoice" onClick={()=>quick('invoice')}
        title="فاکتور فروش جدید" aria-label="فاکتور فروش جدید"><FilePlus2 size={21}/></button>}
      {permittedManage&&<button type="button" disabled={disabled}
        data-accounting-action="payment" title="دریافت و پرداخت" aria-label="دریافت و پرداخت"
        onClick={()=>quick('payment')}><Wallet size={20}/></button>}
      <button type="button" disabled={disabled} data-accounting-action="reports"
        title="گزارش‌های مالی" aria-label="گزارش‌های مالی" onClick={()=>quick('reports')}>
        <Layers3 size={20}/></button>
      <span className="taraz-vt-dock-divider"/>
      <button type="button" disabled={disabled} onClick={()=>void onRefresh()}
        title="بازخوانی اطلاعات مالی" aria-label="بازخوانی اطلاعات مالی"><RefreshCw size={20}/></button>
      <button type="button" data-accounting-action="theme" title={theme==='dark'?'تم روشن':'تم تیره'}
        aria-label={theme==='dark'?'تغییر به تم روشن':'تغییر به تم تیره'}
        onClick={toggleTheme}>{theme==='dark'?<Sun size={20}/>:<Moon size={20}/>}</button>
      <button type="button" disabled={disabled} data-accounting-tab="settings"
        title="تنظیمات" aria-label="تنظیمات" onClick={()=>navigate('settings')}>
        <Settings2 size={20}/></button>
      <button type="button" title="جست‌وجو" aria-label="بازکردن جست‌وجو" disabled={disabled}
        onClick={()=>setSearchOpen(true)}><Search size={20}/></button>
    </div>
    {moreOpen&&<>
      <button type="button" className="taraz-vt-backdrop" onClick={closeMenu}
        aria-label="بستن منوی تراز"/>
      <aside ref={moreRef} id="taraz-vt-drawer" className="sac-nav-more-menu taraz-vt-drawer"
        role="dialog" aria-modal="true" aria-label="فهرست بخش‌های تراز">
        <header className="taraz-vt-drawer-heading">
          <span><strong>فضای کار تراز</strong><small>{companyName||'دفتر حسابداری'} · {currency}</small></span>
          <button type="button" onClick={closeMenu} aria-label="بستن فهرست"><X size={20}/></button>
        </header>
        <div className="taraz-vt-drawer-content">
          {groups.map(group=>{
            const entries=group.items.filter(key=>labels.has(key));
            if(!entries.length)return null;
            const Icon=group.icon;
            return <section className="taraz-vt-nav-group" key={group.id}>
              <h3><Icon size={16} aria-hidden="true"/>{group.title}</h3>
              <nav aria-label={group.title}>
                {entries.map(key=>{
                  const ItemIcon=fullNavIcon[key]||ChevronLeft;
                  return <button type="button" key={key} data-accounting-tab={key}
                    aria-current={tab===key?'page':undefined} disabled={disabled}
                    onClick={()=>navigate(key)}>
                    <ItemIcon size={17} aria-hidden="true"/><span>{labels.get(key)}</span>
                    {tab===key&&<span className="taraz-vt-active-indicator" aria-hidden="true"/>}
                  </button>;
                })}
              </nav>
            </section>;
          })}
        </div>
        <div className="taraz-vt-drawer-actions">
          <strong>عملیات دفتر</strong>
          <div>
            {permittedDraft&&<button type="button" onClick={()=>quick('invoice')} disabled={disabled}>
              <FilePlus2 size={17}/> فاکتور جدید</button>}
            {permittedManage&&<button type="button" onClick={()=>quick('payment')} disabled={disabled}>
              <Wallet size={17}/> ثبت پرداخت</button>}
            {permittedManage&&<button type="button" onClick={onPrint}
              disabled={disabled||!hasPrintableInvoice}><Printer size={16}/> PDF فاکتور</button>}
            {permittedAdmin&&onManageUsers&&<button type="button" onClick={onManageUsers}
              disabled={disabled}><Users size={17}/> کاربران</button>}
            {onSwitchCompany&&<button type="button" onClick={onSwitchCompany} disabled={disabled}>
              <Building2 size={17}/> تغییر شرکت</button>}
            <button type="button" onClick={()=>void onRefresh()} disabled={disabled}>
              <RefreshCw size={17}/> بازخوانی</button>
            <button type="button" onClick={onExit}><ArrowRight size={17}/> خروج</button>
          </div>
          <p><ShieldCheck size={15}/> تراز از اطلاعات تسک‌منیجر مدار مستقل است.</p>
        </div>
      </aside>
    </>}
    <AccountingGlobalSearch open={searchOpen} index={index} disabled={disabled}
      onClose={closeSearch} onSelect={searchSelect}/>
  </div>;
}
