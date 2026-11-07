import React,{useEffect,useRef,useState} from 'react';
import {formatAccountingJalali,parseAccountingJalali} from './accounting_jalali_dates.js';

/** View/edit in Jalali, commit only Gregorian ISO dates to the host. */
export default function AccountingJalaliField({value,onChange,min='',max='',
  required=true,ariaLabel='تاریخ شمسی'}){
  const [typed,setTyped]=useState(()=>formatAccountingJalali(value));
  const changeByTyping=useRef(null);
  useEffect(()=>{
    if(changeByTyping.current===value){
      changeByTyping.current=null;
      return;
    }
    setTyped(formatAccountingJalali(value));
  },[value]);
  const parsed=parseAccountingJalali(typed);
  const valid=Boolean(parsed&&(!min||parsed>=min)&&(!max||parsed<=max));
  const setDate=next=>{
    setTyped(next);
    const iso=parseAccountingJalali(next);
    const clean=iso&&(!min||iso>=min)&&(!max||iso<=max)?iso:'';
    changeByTyping.current=clean;
    onChange(clean);
  };
  return <span className="madar-jalali-field" style={{display:'inline-grid',gap:3}}>
    <input required={required} type="text" dir="ltr" inputMode="numeric"
      aria-label={ariaLabel} aria-invalid={typed!==''&&!valid}
      placeholder="۱۴۰۵/۰۸/۰۲" value={typed} maxLength={12}
      onChange={e=>setDate(e.target.value)}/>
    <small style={{fontSize:10,color:'#758590'}}>شمسی، سال/ماه/روز</small>
  </span>;
}
