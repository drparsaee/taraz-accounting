import React,{useEffect,useRef,useState} from 'react';
import {DEFAULT_PRINT_TEMPLATE,PRINT_FIELDS,templatePageSize,
  renderPrintTemplatePages,validatePrintTemplate} from './accounting_print_template.js';
import './accounting_print_designer.css';
import {CommonColorOptions} from './common_color_palette.jsx';

/** Controlled per-company visual editor. It never writes accounting events. */
export default function AccountingPrintDesigner({value,onChange,context,disabled=false}){
  const canvasRef=useRef(null);
  const drag=useRef(false);
  const [selected,setSelected]=useState('title');
  const [error,setError]=useState('');
  const [previewBusy,setPreviewBusy]=useState(false);
  const template=value||DEFAULT_PRINT_TEMPLATE;
  const [w,h]=templatePageSize(template);
  const field=template.fields.find(f=>f.id===selected)||template.fields[0];
  const change=(update)=>onChange({...template,...update});
  const changeField=(id,changeValue)=>change({fields:template.fields.map(f=>f.id===id?{...f,...changeValue}:f)});
  const changeTable=(part)=>change({table:{...template.table,...part}});

  useEffect(()=>{
    let active=true;
    setPreviewBusy(true);
    Promise.resolve().then(async()=>{
      const [rendered]=await renderPrintTemplatePages(template,context,{scale:3,preview:true});
      if(!active)return;
      const canvas=canvasRef.current;
      if(canvas){canvas.width=rendered.width;canvas.height=rendered.height;
        canvas.getContext('2d')?.drawImage(rendered,0,0);}
      setError('');
    }).catch(e=>{if(active)setError(e.message||'پیش‌نمایش ناموفق بود.');})
      .finally(()=>{if(active)setPreviewBusy(false);});
    return()=>{active=false;};
  },[template,context.kind,context.doc,context.party,context.company,context.currency]);

  const pointerMove=e=>{
    if(!drag.current||disabled||!canvasRef.current)return;
    const rect=canvasRef.current.getBoundingClientRect();
    const x=Math.round((e.clientX-rect.left)/rect.width*w);
    const y=Math.round((e.clientY-rect.top)/rect.height*h);
    if(Number.isFinite(x)&&Number.isFinite(y))
      changeField(selected,{x:Math.max(template.margin,Math.min(w-template.margin,x)),
        y:Math.max(template.margin,Math.min(h-template.margin,y))});
  };
  const imageSelected=async(file)=>{
    if(!file)return;
    if(file.size>180000||!['image/jpeg','image/png'].includes(file.type)){
      setError('فقط لوگوی PNG/JPEG کوچک‌تر از ۱۸۰ کیلوبایت مجاز است.');return;
    }
    const reader=new FileReader();
    reader.onerror=()=>setError('خواندن لوگو ناموفق بود.');
    reader.onload=()=>{
      const next={...template,logo:String(reader.result)};
      try{validatePrintTemplate(next);change({logo:next.logo});setError('');}
      catch(e){setError(e.message);}
    };
    reader.readAsDataURL(file);
  };
  return <div className="sac-print-designer" aria-label="طراح قالب چاپ فاکتور">
    <div className="sac-print-controls">
      <label>نام قالب<input maxLength={100} value={template.title}
        disabled={disabled} onChange={e=>change({title:e.target.value})}/></label>
      <label>کاغذ<select value={template.page} disabled={disabled}
        onChange={e=>change({page:e.target.value})}>
        <option value="A4">A4</option><option value="A5">A5</option></select></label>
      <label>جهت<select value={template.orientation} disabled={disabled}
        onChange={e=>change({orientation:e.target.value})}>
        <option value="portrait">عمودی</option><option value="landscape">افقی</option></select></label>
      <label>حاشیه (میلی‌متر)<input type="number" min="3" max="30" value={template.margin}
        disabled={disabled} onChange={e=>change({margin:Number(e.target.value)})}/></label>
      <label>فونت<select value={template.font} disabled={disabled}
        onChange={e=>change({font:e.target.value})}>
        <option>Vazirmatn</option><option>Tahoma</option><option>Arial</option></select></label>
      <CommonColorOptions value={template.color} disabled={disabled} label="متن فاکتور" onChange={color=>change({color})}/>
      <label>لوگوی صادرکننده<input type="file" accept="image/png,image/jpeg" disabled={disabled}
        onChange={e=>{void imageSelected(e.target.files?.[0]);e.target.value='';}}/></label>
      {template.logo&&<button type="button" disabled={disabled} onClick={()=>change({logo:''})}>حذف لوگو</button>}
      <div className="sac-print-fields">
        <strong>فیلدهای قابل جابه‌جایی</strong>
        <div className="sac-print-field-list">
          {PRINT_FIELDS.map(([id,name])=>{
            const f=template.fields.find(t=>t.id===id);
            return <button key={id} type="button" className={selected===id?'selected':''}
              onClick={()=>setSelected(id)} aria-pressed={selected===id}>
              {f.visible?'●':'○'} {name}</button>;
          })}
        </div>
        <label>نمایش فیلد<input type="checkbox" checked={field.visible} disabled={disabled}
          onChange={e=>changeField(selected,{visible:e.target.checked})}/></label>
        <label>عنوان فیلد<input maxLength={60} value={field.label} disabled={disabled}
          onChange={e=>changeField(selected,{label:e.target.value})}/></label>
        <label>موقعیت افقی (mm)<input type="number" min="0" max={w} value={field.x}
          disabled={disabled} onChange={e=>changeField(selected,{x:Number(e.target.value)})}/></label>
        <label>موقعیت عمودی (mm)<input type="number" min="0" max={h} value={field.y}
          disabled={disabled} onChange={e=>changeField(selected,{y:Number(e.target.value)})}/></label>
        <label>اندازه قلم<input type="number" min="7" max="22" value={field.size}
          disabled={disabled} onChange={e=>changeField(selected,{size:Number(e.target.value)})}/></label>
      </div>
      <div className="sac-print-fields">
        <strong>جدول اقلام و امضا</strong>
        <label>شروع جدول (mm)<input type="number" min="30" max="250" value={template.table.y}
          disabled={disabled} onChange={e=>changeTable({y:Number(e.target.value)})}/></label>
        {[['showQuantity','تعداد'],['showPrice','قیمت واحد'],['showTotal','جمع ردیف']].map(([key,title])=><label key={key}>
          {title}<input type="checkbox" checked={template.table[key]} disabled={disabled}
          onChange={e=>changeTable({[key]:e.target.checked})}/></label>)}
        <label>جایگاه جمع (mm)<input type="number" min="75" max="290"
          value={template.totalsY} disabled={disabled}
          onChange={e=>change({totalsY:Number(e.target.value)})}/></label>
        <label>متن امضا<input maxLength={100} value={template.signature}
          disabled={disabled} onChange={e=>change({signature:e.target.value})}/></label>
      </div>
    </div>
    <div className="sac-print-canvas-shell">
      <div><strong>پیش‌نمایش زنده صفحه اول</strong>
        <small>برای جابه‌جایی، فیلد را انتخاب کنید و روی برگه بکشید. پیش‌نمایشِ بدون سند با داده نمونه است.</small></div>
      <canvas ref={canvasRef} aria-label="نمای فاکتور قابل طراحی" style={{aspectRatio:`${w}/${h}`}}
        onPointerDown={e=>{if(!disabled){drag.current=true;e.currentTarget.setPointerCapture?.(e.pointerId);pointerMove(e);}}}
        onPointerMove={pointerMove} onPointerUp={()=>{drag.current=false;}}
        onPointerCancel={()=>{drag.current=false;}}/>
      {previewBusy&&<small role="status">به‌روزرسانی پیش‌نمایش…</small>}
      {error&&<p role="alert" className="sac-print-error">{error}</p>}
    </div>
  </div>;
}
