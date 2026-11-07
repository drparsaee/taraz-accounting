import React,{useEffect,useRef} from 'react';

// Keep native details disclosures keyboard-accessible, while allowing the
// spectrum and form fields inside them to remain interactive.
export function useColorDisclosure(){
  const ref=useRef(null);
  useEffect(()=>{
    const disclosure=ref.current;
    if(!disclosure)return;
    const dismissOutside=event=>{
      if(disclosure.open&&!disclosure.contains(event.target))disclosure.open=false;
    };
    const dismissEscape=event=>{
      if(event.key!=='Escape'||event.defaultPrevented||!disclosure.open)return;
      // A nested color disclosure gets the first Escape; the next closes its parent.
      if(disclosure.querySelector('details[open]'))return;
      disclosure.open=false;
      event.preventDefault();
      // Parent editors may also use Escape to leave the entire form.
      event.stopPropagation();
      disclosure.querySelector(':scope > summary')?.focus();
    };
    document.addEventListener('pointerdown',dismissOutside,true);
    document.addEventListener('keydown',dismissEscape,true);
    return ()=>{
      document.removeEventListener('pointerdown',dismissOutside,true);
      document.removeEventListener('keydown',dismissEscape,true);
    };
  },[]);
  return ref;
}

// Both the standalone picker and disclosure picker use these same presets.
export const COMMON_COLORS=Object.freeze([
  ['#22C55E','سبز'],['#EAB308','زرد'],['#F97316','نارنجی'],['#EF4444','قرمز'],
  ['#8B5CF6','بنفش'],['#3B82F6','آبی'],['#14B8A6','فیروزه‌ای'],['#EC4899','صورتی'],
  ['#F59E0B','کهربایی'],['#06B6D4','آبی فیروزه‌ای'],['#6366F1','نیلی'],
  ['#D946EF','ارغوانی'],['#92400E','قهوه‌ای'],['#64748B','خاکستری'],
  ['#FFFFFF','سفید'],['#000000','مشکی'],
]);

const markColor=hex=>{
  const [r,g,b]=[1,3,5].map(index=>parseInt(hex.slice(index,index+2),16)/255);
  const light=[r,g,b].map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
  return .2126*light[0]+.7152*light[1]+.0722*light[2]>.32?'#111827':'#FFFFFF';
};

export function CommonColorPalette({value,onChange,disabled=false,label='رنگ'}) {
  return <div className="madar-common-colors" role="group" aria-label={'رنگ‌های مرسوم '+label}>
    {COMMON_COLORS.map(([hex,name])=><button key={hex} type="button" disabled={disabled}
      aria-label={'انتخاب '+name+' برای '+label} aria-pressed={value?.toUpperCase()===hex}
      title={name+' '+hex} className="madar-common-colors__swatch"
      style={{backgroundColor:hex,color:markColor(hex)}} onClick={()=>onChange(hex)}>
      {value?.toUpperCase()===hex&&<span aria-hidden="true" className="madar-common-colors__mark">✓</span>}
    </button>)}
  </div>;
}
