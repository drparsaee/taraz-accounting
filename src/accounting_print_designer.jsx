import React,{useEffect,useRef,useState} from 'react';
import {DEFAULT_PRINT_TEMPLATE,PRINT_FIELDS,PRINT_COLUMNS,PRINT_CUSTOM_SOURCES,PRINT_LAYOUT_PRESETS,
  applyPrintLayoutPreset,printColumns,templatePageSize,maxPrintTableStart,
  renderPrintTemplatePages,validatePrintTemplate} from './accounting_print_template.js';
import './accounting_print_designer.css';
import {CommonColorOptions} from './common_color_palette.jsx';

/** Controlled per-company visual editor. It never writes accounting events. */
export default function AccountingPrintDesigner({value,onChange,context={},disabled=false,onSave}){
  const canvasRef=useRef(null);
  const drag=useRef(null);
  const [selected,setSelected]=useState('title');
  const [error,setError]=useState('');
  const [previewBusy,setPreviewBusy]=useState(false);
  const [layoutChoice,setLayoutChoice]=useState('classic');
  const [aiPrompt,setAiPrompt]=useState('');
  const [aiBusy,setAiBusy]=useState(false);
  const [aiProposal,setAiProposal]=useState(null);
  const proposalCanvasRef=useRef(null);
  // The connected desktop host must expose a real, authenticated capability.
  // Without it, this feature is absent rather than pretending a model ran.
  const aiSuggest=typeof window!=='undefined'&&
    typeof window.madar?.tarazPrintSuggest==='function'?
    window.madar.tarazPrintSuggest:null;
  const template=value||DEFAULT_PRINT_TEMPLATE;
  const [w,h]=templatePageSize(template);
  const field=template.fields.find(f=>f.id===selected)||template.fields[0];
  const logoLayout=template.logoLayout||DEFAULT_PRINT_TEMPLATE.logoLayout;
  const columns=printColumns(template.table);
  const customColumns=template.table.customColumns||[];
  const columnDisplayOrder=[...columns,...PRINT_COLUMNS.map(([id])=>id)
    .concat(customColumns.map(def=>def.id))
    .filter(id=>!columns.includes(id))];
  const change=(update)=>{setAiProposal(null);onChange({...template,...update});};
  const resizePage=(page,orientation)=>{
    const [nextW,nextH]=templatePageSize({...template,page,orientation});
    const ratioX=nextW/w,ratioY=nextH/h;
    const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
    const nextLogo={...logoLayout,x:clamp(Math.round(logoLayout.x*ratioX),
      0,nextW-logoLayout.width),y:clamp(Math.round(logoLayout.y*ratioY),
      0,nextH-logoLayout.height)};
    change({page,orientation,logoLayout:nextLogo,
      fields:template.fields.map(f=>({...f,
        x:clamp(Math.round(f.x*ratioX),0,nextW-template.margin),
        y:clamp(Math.round(f.y*ratioY),0,nextH-template.margin)})),
      table:{...template.table,y:clamp(Math.round(template.table.y*ratioY),30,
        maxPrintTableStart({...template,page,orientation}))}});
  };
  const changeField=(id,changeValue)=>change({fields:template.fields.map(f=>f.id===id?{...f,...changeValue}:f)});
  const changeTable=(part)=>change({table:{...template.table,...part}});
  const changeColumns=(next)=>{
    if(!next.includes('description'))return setError('ستون شرح باید در فاکتور باقی بماند.');
    changeTable({columns:next,showQuantity:next.includes('quantity'),
      showPrice:next.includes('price'),showTotal:next.includes('total')});
    setError('');
  };
  const toggleColumn=(id,checked)=>changeColumns(checked?
    [...columns,id]:columns.filter(col=>col!==id));
  const reorderColumn=(id,direction)=>{
    const index=columns.indexOf(id),next=[...columns],target=index+direction;
    if(index<0||target<0||target>=next.length)return;
    [next[index],next[target]]=[next[target],next[index]];
    changeColumns(next);
  };
  const addCustomColumn=()=>{
    if(customColumns.length>=4)return;
    const nextId=[1,2,3,4].map(i=>'custom_'+i)
      .find(id=>!customColumns.some(def=>def.id===id));
    if(!nextId)return;
    const next={id:nextId,label:'ستون دلخواه '+nextId.split('_')[1],source:'unit'};
    changeTable({customColumns:[...customColumns,next],columns:[...columns,nextId]});
    setError('');
  };
  const editCustomColumn=(id,update)=>{
    changeTable({customColumns:customColumns.map(def=>def.id===id?{...def,...update}:def)});
  };
  const removeCustomColumn=id=>{
    changeTable({customColumns:customColumns.filter(def=>def.id!==id),
      columns:columns.filter(key=>key!==id)});
  };
  const changeLogo=(part)=>change({logoLayout:{...logoLayout,...part}});
  const tableLabels={...DEFAULT_PRINT_TEMPLATE.table.labels,...(template.table.labels||{})};

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
  useEffect(()=>{
    if(!aiProposal)return;
    let active=true;
    renderPrintTemplatePages(aiProposal.template,context,{scale:2,preview:true})
      .then(([rendered])=>{
        if(!active)return;
        const canvas=proposalCanvasRef.current;
        if(canvas){canvas.width=rendered.width;canvas.height=rendered.height;
          canvas.getContext('2d')?.drawImage(rendered,0,0);}
      }).catch(()=>{if(active)setAiProposal(null);});
    return()=>{active=false;};
  },[aiProposal,context.kind,context.doc,context.party,context.company,context.currency]);
  const requestAiSuggestion=async()=>{
    if(!aiSuggest||disabled||aiBusy)return;
    const description=aiPrompt.trim();
    if(!description||description.length>400){
      setError('توضیح طرح باید بین ۱ تا ۴۰۰ نویسه باشد.');return;
    }
    setAiBusy(true);setAiProposal(null);setError('');
    try{
      const response=await window.madar.tarazPrintSuggest(description);
      const layout=response?.layout;
      if(response?.source!=='LOCAL_OLLAMA'||response?.modelRan!==true||
         !layout||typeof layout!=='object'||Array.isArray(layout)||
         Object.keys(layout).sort().join(',')!=='color,font,orientation,page')
        throw Error('پاسخ پیشنهاددهنده، تأیید اجرای مدل و ساختار معتبر ندارد.');
      const candidate=validatePrintTemplate({...template,page:layout.page,
        orientation:layout.orientation,font:layout.font,color:layout.color});
      setAiProposal({template:candidate,layout});
    }catch(_error){
      // A native/model exception may include internal diagnostic details.
      // Never surface those details in an accounting UI error message.
      setError('مدل محلی پاسخ معتبر نداد یا در دسترس نیست؛ از چیدمان دستی استفاده کنید.');
    }
    finally{setAiBusy(false);}
  };

  const pointOnPage=e=>{
    const rect=canvasRef.current?.getBoundingClientRect();
    if(!rect?.width||!rect.height)return null;
    return {x:(e.clientX-rect.left)/rect.width*w,y:(e.clientY-rect.top)/rect.height*h};
  };
  const pointerDown=e=>{
    if(disabled)return;
    const point=pointOnPage(e);
    if(!point)return;
    const logoHit=Boolean(template.logo)&&
      point.x>=logoLayout.x&&point.x<=logoLayout.x+logoLayout.width&&
      point.y>=logoLayout.y&&point.y<=logoLayout.y+logoLayout.height;
    const nearest=template.fields.filter(f=>f.visible&&Math.abs(f.y-point.y)<6&&
      point.x>=f.x-75&&point.x<=f.x+5)
      .sort((a,b)=>Math.abs(a.y-point.y)-Math.abs(b.y-point.y))[0];
    const id=logoHit?'logo':nearest?.id||selected;
    setSelected(id);
    const start=id==='logo'?logoLayout:template.fields.find(f=>f.id===id);
    drag.current={id,dx:point.x-start.x,dy:point.y-start.y};
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const pointerMove=e=>{
    if(!drag.current||disabled||!canvasRef.current)return;
    const point=pointOnPage(e);
    if(!point)return;
    const x=Math.round(point.x-drag.current.dx),y=Math.round(point.y-drag.current.dy);
    if(!Number.isFinite(x)||!Number.isFinite(y))return;
    if(drag.current.id==='logo'){
      changeLogo({x:Math.max(0,Math.min(w-logoLayout.width,x)),
        y:Math.max(0,Math.min(h-logoLayout.height,y))});
    }else changeField(drag.current.id,{x:Math.max(template.margin,Math.min(w-template.margin,x)),
      y:Math.max(template.margin,Math.min(h-template.margin,y))});
  };
  const openPrint=async(autoPrint)=>{
    // Opening synchronously in the click event preserves browser popup permission.
    const win=window.open('','_blank','width=1050,height=900');
    if(!win){setError('مرورگر پنجره پیش‌نمایش را مسدود کرد.');return;}
    win.opener=null;
    try{
      const pages=await renderPrintTemplatePages(template,context,{scale:5});
      if(win.closed)return;
      const [pageWidth,pageHeight]=templatePageSize(template);
      const images=pages.map(canvas=>canvas.toDataURL('image/png'));
      const imagesHtml=images.map(src=>'<img class="sheet" alt="صفحه فاکتور" src="'+src+'">').join('');
      win.document.open();
      win.document.write('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'+
        '<title>پیش‌نمایش چاپ فاکتور</title><style>@page{size:'+template.page+' '+
        template.orientation+';margin:0}'+
        'body{background:#e5ebef;margin:0;display:grid;justify-items:center;gap:16px}'+
        '.sheet{display:block;max-width:100%;height:auto;background:white;box-shadow:0 3px 18px #888}'+
        '@media print{body{display:block;background:white}.sheet{width:'+pageWidth+
        'mm;height:'+pageHeight+'mm;max-width:none;'+
        'box-shadow:none;break-after:page}.sheet:last-child{break-after:auto}}</style></head><body>'+
        imagesHtml+'</body></html>');
      win.document.close();
      if(autoPrint){
        await Promise.all(Array.from(win.document.images,img=>img.complete?Promise.resolve():
          new Promise(resolve=>{img.onload=resolve;img.onerror=resolve;})));
        if(!win.closed){win.focus();win.print();}
      }
      setError('');
    }catch(e){if(!win.closed)win.close();setError(e.message||'آماده‌سازی چاپ ناموفق بود.');}
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
      <fieldset className="sac-print-options-group">
        <legend>شروع با چیدمان آماده</legend>
        <label>سبک چیدمان
          <select value={layoutChoice} disabled={disabled}
            onChange={e=>setLayoutChoice(e.target.value)}>
            {PRINT_LAYOUT_PRESETS.map(p=><option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <small>{PRINT_LAYOUT_PRESETS.find(p=>p.id===layoutChoice)?.description}</small>
        <button type="button" disabled={disabled} onClick={()=>{
          try{onChange(applyPrintLayoutPreset(template,layoutChoice));setError('');}
          catch(e){setError(e.message);}
        }}>اعمال چیدمان انتخابی</button>
      </fieldset>
      {aiSuggest&&<fieldset className="sac-print-options-group sac-print-ai">
        <legend>پیشنهاد چیدمان با مدل محلی</legend>
        <label>شرح طرح دلخواه
          <textarea maxLength={400} rows={3} value={aiPrompt} disabled={disabled||aiBusy}
            placeholder="مثلاً فاکتور رسمی، خوانا، ساده و با رنگ تیره"
            onChange={e=>setAiPrompt(e.target.value)}/>
        </label>
        <button type="button" disabled={disabled||aiBusy||!aiPrompt.trim()}
          onClick={()=>void requestAiSuggestion()}>
          {aiBusy?'در حال دریافت پیشنهاد…':'پیشنهاد طراحی'}
        </button>
        {aiProposal&&<div className="sac-print-ai-proposal">
          <strong>طرح پیشنهادی؛ هنوز اعمال نشده است</strong>
          <span>کاغذ: {aiProposal.layout.page} | جهت: {aiProposal.layout.orientation==='portrait'?'عمودی':'افقی'}</span>
          <span>فونت: {aiProposal.layout.font} | رنگ متن: {aiProposal.layout.color}</span>
          <canvas ref={proposalCanvasRef} aria-label="پیش‌نمایش پیشنهاد مدل محلی"/>
          <button type="button" disabled={disabled} onClick={()=>{
            try{onChange(validatePrintTemplate({...template,
              page:aiProposal.layout.page,orientation:aiProposal.layout.orientation,
              font:aiProposal.layout.font,color:aiProposal.layout.color}));
              setAiProposal(null);setError('');
            }catch(e){setError(e.message);}
          }}>اعمال پیشنهاد روی طرح</button>
          <button type="button" onClick={()=>setAiProposal(null)}>رد پیشنهاد</button>
        </div>}
        <small>تنها صفحه، جهت، قلم و رنگ پیشنهاد می‌شود. رنگ و سایر جزئیات را در پیش‌نمایش بررسی کنید؛ اعمال و ذخیره با انتخاب شماست.</small>
      </fieldset>}
      <label>نام قالب<input maxLength={100} value={template.title}
        disabled={disabled} onChange={e=>change({title:e.target.value})}/></label>
      <label>کاغذ<select value={template.page} disabled={disabled}
        onChange={e=>resizePage(e.target.value,template.orientation)}>
        <option value="A4">A4</option><option value="A5">A5</option></select></label>
      <label>جهت<select value={template.orientation} disabled={disabled}
        onChange={e=>resizePage(template.page,e.target.value)}>
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
      <fieldset className="sac-print-options-group">
        <legend>جایگاه و ابعاد لوگو</legend>
        <button type="button" disabled={!template.logo||disabled}
          onClick={()=>setSelected('logo')} aria-pressed={selected==='logo'}>
          {selected==='logo'?'●':'○'} انتخاب لوگو برای جابه‌جایی روی صفحه
        </button>
        {[['x','افقی',w],['y','عمودی',h],['width','عرض',Math.min(w,100)],
          ['height','ارتفاع',Math.min(h,75)]].map(([id,label,max])=><label key={id}>
          {label} لوگو (mm)
          <input type="number" min={id==='width'?8:id==='height'?6:0} max={max}
            value={logoLayout[id]} disabled={disabled}
            onChange={e=>changeLogo({[id]:Number(e.target.value)})}/>
        </label>)}
      </fieldset>
      <fieldset className="sac-print-options-group">
        <legend>سربرگ شرکت</legend>
        <label>نام چاپی شرکت
          <input value={template.companyHeader||''} maxLength={120} disabled={disabled}
            placeholder={context.company?.legalName||'نام شرکت از مشخصات صادرکننده'}
            onChange={e=>change({companyHeader:e.target.value})}/>
        </label>
        <label>سطر زیر سربرگ (نشانی، تلفن یا شناسه)
          <input value={template.companySubtitle||''} maxLength={120} disabled={disabled}
            placeholder="نشانی و تلفن شرکت"
            onChange={e=>change({companySubtitle:e.target.value})}/>
        </label>
        <small>این اطلاعات فقط روی نسخه چاپی نمایش داده می‌شوند؛ هویت ثبتی دفتر و اسناد مالی را تغییر نمی‌دهند.</small>
      </fieldset>
      <div className="sac-print-fields">
        <strong>عنوان فاکتور، فروشنده، خریدار و مشخصات سند</strong>
        <div className="sac-print-field-list">
          {PRINT_FIELDS.map(([id,name])=>{
            const f=template.fields.find(t=>t.id===id);
            return <button key={id} type="button" className={selected===id?'selected':''}
              onClick={()=>setSelected(id)} aria-pressed={selected===id}>
              {f.visible?'●':'○'} {name}</button>;
          })}
        </div>
        {selected!=='logo'&&<>
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
        </>}
      </div>
      <div className="sac-print-fields">
        <strong>ستون‌ها، ردیف‌ها و پاورقی</strong>
        <label>شروع جدول (mm)<input type="number" min="30" max={maxPrintTableStart(template)} value={template.table.y}
          disabled={disabled} onChange={e=>changeTable({y:Number(e.target.value)})}/></label>
        <div className="sac-print-column-editor">
          <strong>انتخاب و ترتیب ستون‌های فاکتور</strong>
          {columnDisplayOrder.map(id=>{
            const title=PRINT_COLUMNS.find(([key])=>key===id)?.[1]||
              customColumns.find(def=>def.id===id)?.label||id;
            const index=columns.indexOf(id),checked=index>=0;
            return <div className="sac-print-column-line" key={id}>
              <label><input type="checkbox" checked={checked}
                disabled={disabled||id==='description'}
                onChange={e=>toggleColumn(id,e.target.checked)}/>{title}</label>
              <button type="button" aria-label={'انتقال '+title+' به بالا'} disabled={disabled||index<=0}
                onClick={()=>reorderColumn(id,-1)}>↑</button>
              <button type="button" aria-label={'انتقال '+title+' به پایین'}
                disabled={disabled||index<0||index===columns.length-1}
                onClick={()=>reorderColumn(id,1)}>↓</button>
              <span>{checked?index+1:'حذف‌شده'}</span>
            </div>;
          })}
          <small>فقط مقادیر ثبت‌شده در ردیف فاکتور چاپ می‌شوند؛ شناسه‌های خالی با «—» نمایش داده می‌شوند.</small>
          <div className="sac-print-custom-columns" aria-label="ستون‌های سفارشی فاکتور">
            <button type="button" disabled={disabled||customColumns.length>=4}
              onClick={addCustomColumn}>افزودن ستون سفارشی</button>
            {customColumns.map(def=><div className="sac-print-column-line" key={def.id}>
              <label>عنوان ستون سفارشی {def.id}
                <input value={def.label} maxLength={25} disabled={disabled}
                  onChange={e=>editCustomColumn(def.id,{label:e.target.value})}/>
              </label>
              <label>متغیر ستون سفارشی {def.id}
                <select value={def.source} disabled={disabled}
                  onChange={e=>editCustomColumn(def.id,{source:e.target.value})}>
                  {PRINT_CUSTOM_SOURCES.map(([key,title])=><option key={key} value={key}>{title}</option>)}
                </select>
              </label>
              <button type="button" aria-label={'حذف ستون سفارشی '+def.id}
                disabled={disabled} onClick={()=>removeCustomColumn(def.id)}>حذف</button>
            </div>)}
            <small>ستون سفارشی فقط به متغیرهای تأییدشدهٔ ردیف فاکتور متصل می‌شود؛ فرمول یا اطلاعات ساختگی اجرا نمی‌شود.</small>
          </div>
        </div>
        {[['description','شرح ردیف'],['quantity','عنوان تعداد'],['price','عنوان قیمت واحد'],['total','عنوان مبلغ']].map(([key,title])=><label key={key}>
          {title}<input maxLength={25} value={tableLabels[key]} disabled={disabled}
            onChange={e=>changeTable({labels:{...tableLabels,[key]:e.target.value}})}/></label>)}
        <label>فاصله ردیف‌ها (mm)<input type="number" min="6" max="14" step="0.5"
          value={template.table.rowHeight??8.5} disabled={disabled}
          onChange={e=>changeTable({rowHeight:Number(e.target.value)})}/></label>
        <label>جایگاه جمع (mm)<input type="number" min="75" max="290"
          value={template.totalsY} disabled={disabled}
          onChange={e=>change({totalsY:Number(e.target.value)})}/></label>
        <label>متن امضا<input maxLength={100} value={template.signature}
          disabled={disabled} onChange={e=>change({signature:e.target.value})}/></label>
        <label>متن پاورقی چاپ
          <input maxLength={70} value={template.footerText||''} disabled={disabled}
            placeholder="سپاس از همکاری شما"
            onChange={e=>change({footerText:e.target.value})}/>
        </label>
      </div>
    </div>
    <div className="sac-print-canvas-shell">
      <div><strong>پیش‌نمایش زنده صفحه اول</strong>
        <small>متن یا لوگو را از فهرست انتخاب کنید یا روی خود برگه بگیرید و جابه‌جا کنید. پیش‌نمایشِ بدون سند با داده نمونه است.</small></div>
      <canvas ref={canvasRef} aria-label="نمای فاکتور قابل طراحی" style={{aspectRatio:`${w}/${h}`}}
        onPointerDown={pointerDown} onPointerMove={pointerMove}
        onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>
      <div className="sac-print-preview-actions">
        <button type="button" disabled={disabled||previewBusy} onClick={()=>void openPrint(false)}>پیش‌نمایش همه صفحات</button>
        <button type="button" disabled={disabled||previewBusy} onClick={()=>void openPrint(true)}>چاپ فاکتور با چیدمان فعلی</button>
        {typeof onSave==='function'&&<button type="button" disabled={disabled}
          onClick={()=>{
            try{void Promise.resolve(onSave(validatePrintTemplate(template)))
              .catch(e=>setError(e.message||'ذخیره قالب انجام نشد.'));}
            catch(e){setError(e.message||'ساختار قالب برای ذخیره معتبر نیست.');}
          }}>ذخیره قالب</button>}
      </div>
      {previewBusy&&<small role="status">به‌روزرسانی پیش‌نمایش…</small>}
      {error&&<p role="alert" className="sac-print-error">{error}</p>}
    </div>
  </div>;
}
