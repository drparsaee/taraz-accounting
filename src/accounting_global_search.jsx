import React from 'react';
import {ArrowLeft,Search,X} from 'lucide-react';
import {searchAccountingIndex} from './accounting_nav_search.js';
import './accounting_global_search.css';

/** No host calls: the caller passes an already authorized, company-scoped index. */
export default function AccountingGlobalSearch({open,index=[],onSelect,onClose,disabled=false}){
  const [query,setQuery]=React.useState('');
  const [selected,setSelected]=React.useState(0);
  const inputRef=React.useRef(null);
  const dialogRef=React.useRef(null);
  const matches=React.useMemo(()=>searchAccountingIndex(index,query),[index,query]);
  React.useEffect(()=>{
    if(!open){setQuery('');setSelected(0);return;}
    inputRef.current?.focus();
  },[open]);
  React.useEffect(()=>setSelected(0),[query,index]);
  React.useEffect(()=>{
    if(!open)return;
    const focusExistingSearch=event=>{
      if((event.ctrlKey||event.metaKey)&&!event.altKey&&!event.isComposing&&
         event.key.toLocaleLowerCase('en-US')==='k'){
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown',focusExistingSearch,true);
    return()=>document.removeEventListener('keydown',focusExistingSearch,true);
  },[open]);
  const activate=match=>{
    if(disabled||!match)return;
    // A draft-discard confirmation may veto navigation. Preserve query then.
    if(onSelect(match)!==false)onClose();
  };
  const keyDown=event=>{
    if(event.key==='Escape'){
      event.preventDefault();event.stopPropagation();onClose();return;
    }
    if(event.key==='Tab'){
      const focusable=[...dialogRef.current.querySelectorAll(
        'button:not(:disabled),input:not(:disabled)')].filter(el=>el.getClientRects().length);
      if(!focusable.length)return;
      const first=focusable[0],last=focusable[focusable.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      return;
    }
    if(event.target===inputRef.current&&
        (event.key==='ArrowDown'||event.key==='ArrowUp')){
      if(!matches.length)return;
      event.preventDefault();setSelected(current=>
        (current+(event.key==='ArrowDown'?1:-1)+matches.length)%matches.length);
    }else if(event.key==='Enter'&&event.target===inputRef.current&&matches.length){
      // Enter on a focused Close/result button belongs to that button.
      // Never redirect it to the currently highlighted search result.
      event.preventDefault();activate(matches[Math.min(selected,matches.length-1)]);
    }
  };
  if(!open)return null;
  return <div className="sac-global-search-layer" dir="rtl">
    <div className="sac-global-search-backdrop" aria-hidden="true"
      onMouseDown={onClose}/>
    <section className="sac-global-search-dialog" role="dialog" aria-modal="true"
      aria-labelledby="sac-global-search-heading" ref={dialogRef} onKeyDown={keyDown}>
      <header className="sac-global-search-head">
        <div><h2 id="sac-global-search-heading">جست‌وجوی حسابداری</h2>
          <p>جست‌وجوی بخش‌ها و سوابق قابل مشاهدهٔ دفتر فعلی</p></div>
        <button type="button" className="sac-global-search-close" onClick={onClose}
          aria-label="بستن جست‌وجو"><X size={19}/></button>
      </header>
      <label className="sac-global-search-field">
        <Search size={20} aria-hidden="true"/>
        <span className="sac-global-search-sr-only">عنوان، شماره فاکتور، مشتری یا حساب</span>
        <input ref={inputRef} type="search" autoComplete="off" spellCheck={false}
          role="combobox" aria-expanded={matches.length>0} aria-controls="sac-global-search-results"
          aria-autocomplete="list" aria-activedescendant={matches.length?
            'sac-global-search-result-'+Math.min(selected,matches.length-1):undefined}
          aria-label="جست‌وجوی بخش، شماره فاکتور، مشتری یا حساب"
          value={query} onChange={event=>setQuery(event.target.value)}
          placeholder="شماره فاکتور، نام مشتری، حساب…"/>
        <kbd>Ctrl+K</kbd>
      </label>
      <div id="sac-global-search-results" className="sac-global-search-results" role="listbox"
        aria-label="نتایج جست‌وجوی حسابداری">
        {!query.trim()&&<p className="sac-global-search-empty">
          برای دیدن بخش‌ها یا رکوردهای دفتر مجاز، عبارت را وارد کنید.</p>}
        {query.trim()&&!matches.length&&<p className="sac-global-search-empty">
          نتیجه‌ای در اطلاعات قابل مشاهدهٔ این دفتر پیدا نشد.</p>}
        {matches.map((match,i)=><button type="button" role="option"
          id={'sac-global-search-result-'+i} key={match.key} aria-selected={i===selected}
          className={'sac-global-search-result'+(i===selected?' active':'')}
          onMouseEnter={()=>setSelected(i)} onFocus={()=>setSelected(i)}
          onClick={()=>activate(match)}>
          <span><strong dir="auto">{match.title}</strong><small>{match.subtitle}</small></span>
          <ArrowLeft size={16} aria-hidden="true"/>
        </button>)}
      </div>
      <footer className="sac-global-search-footer">
        <span>↑ ↓ انتخاب · Enter بازکردن · Esc بستن</span>
        <span role="status" aria-live="polite">{query.trim()?
          matches.length.toLocaleString('fa-IR')+' نتیجهٔ نمایشی':''}</span>
      </footer>
    </section>
  </div>;
}
