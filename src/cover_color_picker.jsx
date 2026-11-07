import React,{useEffect,useMemo,useState} from 'react';
import {Pipette} from 'lucide-react';
import {CommonColorPalette,useColorDisclosure} from './common_color_swatches.jsx';

const HEX=/^#[0-9A-F]{6}$/i;
export function hsvToHex(h,s,v){
  if(![h,s,v].every(Number.isFinite))throw new RangeError('HSV must be finite');
  const hh=((h%360)+360)%360,ss=Math.max(0,Math.min(1,s)),vv=Math.max(0,Math.min(1,v));
  const c=vv*ss,x=c*(1-Math.abs((hh/60)%2-1)),m=vv-c;
  const [r,g,b]=hh<60?[c,x,0]:hh<120?[x,c,0]:hh<180?[0,c,x]:
    hh<240?[0,x,c]:hh<300?[x,0,c]:[c,0,x];
  return '#'+[r,g,b].map(n=>Math.round((n+m)*255).toString(16).padStart(2,'0')).join('').toUpperCase();
}
export function hexToHsv(value){
  if(typeof value!=='string'||!HEX.test(value))throw new TypeError('Invalid HEX color');
  const rgb=[1,3,5].map(i=>parseInt(value.slice(i,i+2),16)/255);
  const [r,g,b]=rgb,min=Math.min(...rgb),max=Math.max(...rgb),d=max-min;
  let h=0;
  if(d){h=max===r?((g-b)/d)%6:max===g?(b-r)/d+2:(r-g)/d+4;h*=60;if(h<0)h+=360;}
  return {h,s:max===0?0:d/max,v:max};
}
const clamp=(value)=>Math.max(0,Math.min(1,value));

/**
 * Compact solid color picker. All color values applied to CSS or emitted to
 * callers are validated #RRGGBB; untrusted free-form text is never painted.
 */
export function CoverColorPicker({value='#5672CA',onChange,onCommit,disabled=false,label='کاور'}){
  const advancedRef=useColorDisclosure();
  const current=HEX.test(value)?value.toUpperCase():'#5672CA';
  const [hue,setHue]=useState(()=>Math.round(hexToHsv(current).h));
  const [draft,setDraft]=useState(current);
  const selected=useMemo(()=>hexToHsv(current),[current]);
  useEffect(()=>{
    setDraft(current);
    const incoming=hexToHsv(current);
    // Gray/white/black have no inherent hue: retain the chosen hue so the
    // spectrum does not jump to red during a pointer drag through grayscale.
    if(incoming.s>0)setHue(Math.round(incoming.h));
  },[current]);
  const commit=(color,dismiss=false)=>{
    if(disabled||!HEX.test(color))return;
    const clean=color.toUpperCase();
    setDraft(clean);
    const next=hexToHsv(clean);
    if(next.s>0)setHue(Math.round(next.h));
    onChange?.(clean);
    if(dismiss){
      if(advancedRef.current?.open){
        const focusWasInside=advancedRef.current.contains(document.activeElement);
        advancedRef.current.open=false;
        if(focusWasInside)advancedRef.current.querySelector(':scope > summary')?.focus();
      }
      onCommit?.();
    }
  };
  const fromSpectrum=(s,v)=>commit(hsvToHex(hue,clamp(s),clamp(v)));
  const movePointer=e=>{
    if(disabled)return;
    const rect=e.currentTarget.getBoundingClientRect();
    if(rect.width<=0||rect.height<=0)return;
    fromSpectrum((e.clientX-rect.left)/rect.width,1-(e.clientY-rect.top)/rect.height);
  };
  const keyboardSpectrum=e=>{
    const step=e.shiftKey?0.1:0.05;
    let {s,v}=selected;
    switch(e.key){
      case 'ArrowLeft':s=clamp(s-step);break;
      case 'ArrowRight':s=clamp(s+step);break;
      case 'ArrowUp':v=clamp(v+step);break;
      case 'ArrowDown':v=clamp(v-step);break;
      case 'Home':s=0;break;
      case 'End':s=1;break;
      default:return;
    }
    e.preventDefault();
    if(!disabled)fromSpectrum(s,v);
  };
  return <div className="cover-picker" dir="rtl">
    <CommonColorPalette value={current} onChange={color=>commit(color,true)} disabled={disabled} label={label}/>
    <details ref={advancedRef} className="cover-picker__advanced">
      <summary><Pipette size={15} aria-hidden="true"/> ساخت رنگ دلخواه <span dir="ltr">{current}</span></summary>
      <div className="cover-picker__panel">
        <div className="cover-picker__spectrum" role="slider" tabIndex={disabled?-1:0}
          aria-label={'اشباع و روشنایی رنگ '+label} aria-disabled={disabled}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(selected.s*100)}
          aria-valuetext={'اشباع '+Math.round(selected.s*100)+' درصد، روشنایی '+
            Math.round(selected.v*100)+' درصد، رنگ '+current}
          style={{'--cover-picker-hue':hsvToHex(hue,1,1)}}
          onKeyDown={keyboardSpectrum}
          onPointerDown={e=>{
            if(disabled)return;
            e.currentTarget.setPointerCapture(e.pointerId);
            movePointer(e);
          }}
          onPointerMove={e=>{
            if(e.currentTarget.hasPointerCapture(e.pointerId))movePointer(e);
          }}
          onPointerUp={e=>{
            if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
          }}
          onPointerCancel={e=>{
            if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
          }}>
          <span className="cover-picker__handle" aria-hidden="true"
            style={{left:(selected.s*100)+'%',top:((1-selected.v)*100)+'%'}}/>
        </div>
        <label className="cover-picker__hue">طیف رنگ
          <input type="range" min="0" max="359" step="1" value={hue}
            disabled={disabled} aria-label={'طیف رنگ '+label} onChange={e=>{
              const next=Number(e.target.value);
              setHue(next);
              if(selected.s>0)commit(hsvToHex(next,selected.s,selected.v));
            }}/>
        </label>
        <div className="cover-picker__custom">
          <input type="color" aria-label={'رنگ '+label} disabled={disabled}
            value={HEX.test(draft)?draft:current} onChange={e=>{
              const color=e.currentTarget.value;
              e.currentTarget.blur();
              commit(color,true);
            }}/>
          <input type="text" aria-label="کد شش رقمی رنگ" dir="ltr" maxLength={7}
            value={draft} disabled={disabled} onChange={e=>setDraft(e.target.value)} placeholder="#RRGGBB"/>
          <button type="button" disabled={disabled||!HEX.test(draft)} onClick={()=>commit(draft,true)}>
            اعمال
          </button>
        </div>
        <small>برای انتخاب روی طیف بکشید یا از کلیدهای جهت‌دار استفاده کنید.</small>
      </div>
    </details>
  </div>;
}
