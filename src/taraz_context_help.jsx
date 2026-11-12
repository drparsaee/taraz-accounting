import React,{useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {CircleHelp,X} from 'lucide-react';
import {resolveTarazContextHelp} from './taraz_context_help_data.js';
import './taraz_context_help.css';

/**
 * Read-only contextual help control.
 * Integration: render beside current authorized section title, passing the
 * same visible sections, authenticated role, and restrictive sectionAccess as
 * the host-scoped navigation. Action capabilities must reflect visible UI.
 * Never mounts routes or reads, modifies or creates finance records.
 */
export default function TarazContextHelp({
  tab,context=null,sections=[],role='viewer',
  sectionAccess=null,capabilities={},disabled=false,
  className=''
}){
  const help=resolveTarazContextHelp({
    tab,context,sections,role,sectionAccess,capabilities
  });
  const [open,setOpen]=useState(false);
  const opener=useRef(null);
  const closeRef=useRef(null);
  const id=useId();
  const titleId=id+'-title';
  const descId=id+'-details';
  const dialogId=id+'-panel';
  const activeKey=help?.id??'';

  // Navigation or loss of permission closes the former guide.
  useEffect(()=>{setOpen(false);},[tab,activeKey,role,disabled]);
  useEffect(()=>{
    if(!open||!help||disabled)return;
    closeRef.current?.focus();
    const onKeyDown=event=>{
      if(event.key==='Escape'){
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }else if(event.key==='Tab'){
        // Keep focus on the only interactive control inside the dialog.
        event.preventDefault();
        closeRef.current?.focus();
      }
    };
    document.addEventListener('keydown',onKeyDown,true);
    return ()=>{
      document.removeEventListener('keydown',onKeyDown,true);
      if(opener.current?.isConnected)opener.current.focus();
    };
  },[open,activeKey,disabled]);

  if(!help||disabled)return null;
  return <span className={'taraz-context-help '+className} dir="rtl">
    <button ref={opener} type="button"
      className="taraz-context-help-trigger"
      aria-label={'راهنمای '+help.label}
      title={'راهنمای '+help.label}
      aria-haspopup="dialog" aria-expanded={open}
      aria-controls={open?dialogId:undefined}
      onClick={()=>setOpen(value=>!value)}>
      <CircleHelp size={18} aria-hidden="true"/>
      <span>راهنما</span>
    </button>
    {open&&help&&createPortal(<div className="taraz-context-help-layer"
      data-taraz-context-help-portal="true">
      <button type="button" className="taraz-context-help-backdrop"
        tabIndex={-1} aria-hidden="true"
        onClick={()=>setOpen(false)}/>
      <section id={dialogId} role="dialog" aria-modal="true"
        aria-labelledby={titleId} aria-describedby={descId}
        className="taraz-context-help-dialog" dir="rtl">
        <div className="taraz-context-help-heading">
          <h2 id={titleId}>راهنمای {help.label}</h2>
          <button ref={closeRef} type="button"
            className="taraz-context-help-close"
            aria-label="بستن راهنما" onClick={()=>setOpen(false)}>
            <X size={19} aria-hidden="true"/>
          </button>
        </div>
        <div id={descId} className="taraz-context-help-details">
          <ol>{help.steps.map((step,index)=><li key={index}>{step}</li>)}</ol>
          {help.caution&&<p className="taraz-context-help-caution">{help.caution}</p>}
        </div>
      </section>
    </div>,document.body)}
  </span>;
}
