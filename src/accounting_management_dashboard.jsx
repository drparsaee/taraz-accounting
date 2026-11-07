import React,{useEffect,useMemo,useState} from 'react';
import {Activity,ArrowLeft,ArrowUpLeft,CalendarClock,CalendarDays,
  ChartNoAxesCombined,Check,ChevronLeft,Clock3,FileBarChart2,Landmark,
  SlidersHorizontal,Wallet,X} from 'lucide-react';
import {buildManagementAnalytics} from './accounting_management_analytics.js';
import {formatAccountingJalali,parseAccountingJalali} from './accounting_jalali_dates.js';
import AccountingJalaliField from './accounting_jalali_field.jsx';
import './accounting_management_dashboard.css';

const PERSIAN=new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2});
const PERSIAN_DATE=new Intl.DateTimeFormat('fa-IR-u-ca-persian',{weekday:'long',
  day:'numeric',month:'long',year:'numeric'});
const PERSIAN_TIME=new Intl.DateTimeFormat('fa-IR',{hour:'2-digit',minute:'2-digit',
  hour12:false});
const PERSIAN_WEEKDAY=new Intl.DateTimeFormat('fa-IR',{weekday:'long'});
const MAX_CHART_POINTS=60;
const CHEQUE_ACTIVE=new Set(['received','deposited','issued','endorsed','returned']);
const PALETTE=['#0b8c81','#5982c5','#cf9456','#9170bb'];
const MONEY_TABS={sales:'invoice',invoices:'invoice',revenue:'invoice',
  purchases:'bill',bills:'bill',expense:'bill',expenses:'bill',
  receivable:'invoice',payable:'bill',cheques:'cheques',cheque:'cheques',
  balances:'accounts',cash:'cash',treasury:'cheques',journals:'journal',
  profit:'reports',ledger:'accounts',report:'reports',reports:'reports',
  monthlySales:'invoice',ledgerPerformance:'reports',topProducts:'items',
  dueCheques:'cheques',net:'reports'};

function dayIso(date){
  return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),
    String(date.getDate()).padStart(2,'0')].join('-');
}
function minusDays(date,count){
  const current=new Date(date.getFullYear(),date.getMonth(),date.getDate());
  current.setDate(current.getDate()-count);
  return dayIso(current);
}
function startOfSolarPeriod(today,mode){
  const solar=formatAccountingJalali(today,{digits:'ascii'});
  if(!solar)return minusDays(new Date(),29);
  const year=solar.slice(0,4);
  return parseAccountingJalali(year+(mode==='year'?'/01/01':solar.slice(4,7)+'/01'))||
    today;
}
function chooseRange(mode,now){
  const end=dayIso(now);
  if(mode==='month'||mode==='year')return {
    start:startOfSolarPeriod(end,mode),end};
  return {start:minusDays(now,mode==='90d'?89:29),end};
}
function statusName(status){
  return ({received:'دریافت‌شده',deposited:'سپرده‌شده',issued:'صادرشده',
    endorsed:'واگذارشده',returned:'برگشتی'})[status]||status;
}
function dayDistance(today,target){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(target||''))return null;
  const a=Date.parse(today+'T00:00:00Z');
  const b=Date.parse(target+'T00:00:00Z');
  if(!Number.isFinite(a)||!Number.isFinite(b)||
     new Date(b).toISOString().slice(0,10)!==target)return null;
  return Math.round((b-a)/86400000);
}
function realChequeReminders(view,today){
  if(!view||typeof view!=='object')return [];
  const raw=view.cheques;
  const cheques=Array.isArray(raw)?raw:raw&&typeof raw==='object'?Object.values(raw):[];
  return cheques.filter(ch=>ch&&typeof ch==='object'&&CHEQUE_ACTIVE.has(ch.status))
    .map(ch=>({...ch,days:dayDistance(today,ch.dueDate)}))
    .filter(ch=>ch.days!==null&&(ch.days<=7||ch.status==='returned'))
    .sort((a,b)=>{
      const importance=ch=>ch.status==='returned'?0:ch.days<0?1:ch.days===0?2:3;
      return importance(a)-importance(b)||a.days-b.days;
    });
}
function chequeUrgency(ch){
  if(ch.status==='returned')return {label:'برگشتی',tone:'danger'};
  if(ch.days<0)return {label:`${PERSIAN.format(-ch.days)} روز معوق`,tone:'danger'};
  if(ch.days===0)return {label:'امروز',tone:'warning'};
  if(ch.days===1)return {label:'فردا',tone:'warning'};
  return {label:`${PERSIAN.format(ch.days)} روز دیگر`,tone:'neutral'};
}
function recordList(raw){
  if(Array.isArray(raw))return raw.filter(x=>x&&typeof x==='object');
  if(raw&&typeof raw==='object')return Object.entries(raw).map(([id,value])=>
    value&&typeof value==='object'?{id,...value}:null).filter(Boolean);
  return [];
}
function numberValue(value){
  return typeof value==='number'&&Number.isFinite(value)?value:null;
}
function humanNumber(value){
  if(typeof value==='number'&&Number.isFinite(value))return PERSIAN.format(value);
  if(typeof value==='string'&&value.trim())return value;
  return '—';
}
function moneyNumber(value,unit){return `${humanNumber(value)} ${unit}`;}
function normalizedKpis(analytics){
  const source=analytics?.kpis||analytics?.metrics;
  if(Array.isArray(source))return source.filter(x=>x&&typeof x==='object')
    .map((metric,i)=>({
      id:String(metric.id||metric.key||i),label:String(metric.label||metric.title||metric.id||'شاخص'),
      value:metric.value??null,unit:metric.unit,
      description:metric.description||metric.subtitle||metric.note||'',
      navigate:metric.navigate||metric.tab||metric.target||'',
      delta:metric.delta,}));
  if(source&&typeof source==='object')return Object.entries(source)
    .filter(([,v])=>typeof v==='number'||v&&typeof v==='object')
    .map(([id,v])=>typeof v==='number'?{id,label:id,value:v}:
      {id,label:v.label||v.title||id,value:v.value,
        unit:v.unit,description:v.description,navigate:v.navigate||v.tab});
  return [];
}
function extractPoints(series){
  const rows=Array.isArray(series)?series:[];
  return rows.slice(-MAX_CHART_POINTS).map((row,index)=>{
    if(typeof row==='number')return {label:String(index+1),value:row};
    if(!row||typeof row!=='object')return null;
    const value=numberValue(row.value??row.amount??row.y??row.total);
    return value===null?null:{label:String(row.label??row.period??row.date??row.x??index+1),
      value,details:row};
  }).filter(Boolean);
}
function normalizedCharts(analytics){
  const charts=analytics?.charts||analytics?.visuals||[];
  return recordList(charts).map((chart,index)=>{
    const points=extractPoints(chart.data||chart.points||chart.values||chart.series?.[0]?.data);
    const second=extractPoints(chart.secondary||chart.comparison||chart.series?.[1]?.data);
    return {...chart,id:String(chart.id||chart.key||index),
      title:chart.title||chart.label||'نمودار',subtitle:chart.subtitle||chart.description||'',
      type:chart.type||'bar',points,second,
      secondLabel:chart.secondaryLabel||chart.series?.[1]?.label||'',
      unit:chart.unit||'',navigate:chart.navigate||chart.tab||chart.target||''};
  });
}
function targetTab(item){
  const target=item.navigate||item.tab||item.target||item.section||item.id;
  return MONEY_TABS[target]||target;
}

function Sparkline({points,secondary=[],color=PALETTE[0],large=false}){
  const rows=points.slice(-MAX_CHART_POINTS);
  const extras=secondary.slice(-MAX_CHART_POINTS);
  const numbers=[...rows,...extras].map(x=>x.value).filter(Number.isFinite);
  if(!numbers.length)return <div className="mdash-chart-empty">داده‌ای برای نمایش نمودار موجود نیست.</div>;
  const min=Math.min(0,...numbers),max=Math.max(1,...numbers),span=max-min||1;
  const width=560,height=180,left=10,right=550,top=12,bottom=145;
  const point=(r,i,count)=>[left+(count===1?(right-left)/2:i/(count-1)*(right-left)),
    bottom-(r.value-min)/span*(bottom-top)];
  const pairs=rows.map((r,i)=>point(r,i,rows.length));
  const secondaryPairs=extras.map((r,i)=>point(r,i,extras.length));
  const path=p=>p.map(([x,y],i)=>(i?'L':'M')+x.toFixed(2)+' '+y.toFixed(2)).join(' ');
  return <div className={'mdash-chart-figure'+(large?' big':'')}>
    <svg viewBox="0 0 560 180" preserveAspectRatio="none" role="img"
      aria-label={`نمودار داده‌های ثبت‌شده با ${PERSIAN.format(rows.length)} نقطه`}>
      {[0,1,2,3].map(i=><line key={i} x1="10" y1={top+i*(bottom-top)/3}
        x2="550" y2={top+i*(bottom-top)/3} stroke="#e8eef0"
        strokeDasharray="3 7"/>)}
      {pairs.length>1&&<path d={path(pairs)+' L'+pairs.at(-1)[0]+' '+bottom+
        ' L'+pairs[0][0]+' '+bottom+' Z'} fill={color} fillOpacity=".10"/>}
      {secondaryPairs.length>1&&<path d={path(secondaryPairs)} stroke={PALETTE[2]}
        strokeWidth="2.4" fill="none" strokeLinecap="round" strokeDasharray="5 5"/>}
      {pairs.length>1&&<path d={path(pairs)} stroke={color} strokeWidth="3.3"
        strokeLinecap="round" strokeLinejoin="round" fill="none"/>}
      {pairs.map(([x,y],i)=><circle key={i} cx={x} cy={y} r={large?3.3:2.5}
        fill="#fff" stroke={color} strokeWidth="2"/>)}
    </svg>
    <div className="mdash-xlabels">
      <span>{rows[0]?.label||' '}</span><span>{rows.at(-1)?.label||' '}</span>
    </div>
  </div>;
}
function Bars({points,color=PALETTE[0],large=false}){
  const rows=points.slice(-12);
  if(!rows.length)return <div className="mdash-chart-empty">داده‌ای برای نمایش نمودار موجود نیست.</div>;
  const maxPositive=Math.max(0,...rows.map(x=>x.value));
  const maxNegative=Math.max(0,...rows.map(x=>-x.value));
  const domain=Math.max(1,maxPositive+maxNegative);
  const zero=(maxPositive||!maxNegative?maxPositive/domain*100:0);
  return <div className={'mdash-bars'+(large?' big':'')} role="img"
    aria-label={`نمودار ستونی با ${PERSIAN.format(rows.length)} مقدار`}>
    {rows.map((row,i)=><div className="mdash-bar-col" key={i}
      title={`${row.label}: ${humanNumber(row.value)}`}>
      <div className="mdash-bar-track">
        <i className="mdash-bar-zero" style={{top:`${zero}%`}}/>
        {row.value!==0&&<span style={{
          top:`${row.value>=0?zero-Math.abs(row.value)/domain*100:zero}%`,
          height:`${Math.abs(row.value)/domain*100}%`,
          background:row.value<0?'#c66465':color}}/>}
      </div>
      <small className={'mdash-bar-amount'+(row.value<0?' negative':'')}>
        {humanNumber(row.value)}</small>
      <small>{row.label}</small>
    </div>)}
  </div>;
}
function Donut({points,color=PALETTE[0],large=false}){
  const values=points.filter(p=>p.value>0).slice(0,6);
  const total=values.reduce((s,p)=>s+p.value,0);
  if(!total)return <div className="mdash-chart-empty">داده‌ای برای نمایش نمودار موجود نیست.</div>;
  let current=0;
  const arcs=values.map((r,i)=>{
    const share=r.value/total*100;
    const el=<circle key={i} cx="50" cy="50" r="36" fill="transparent"
      stroke={PALETTE[i%PALETTE.length]} strokeWidth="13"
      strokeDasharray={`${share*2.26195} ${226.195-share*2.26195}`}
      strokeDashoffset={-current*2.26195} transform="rotate(-90 50 50)"/>;
    current+=share;
    return el;
  });
  return <div className={'mdash-donut'+(large?' big':'')}>
    <svg viewBox="0 0 100 100" role="img" aria-label="نمودار ترکیب مقادیر">
      <circle cx="50" cy="50" r="36" stroke="#eaf0f0" fill="none" strokeWidth="13"/>
      {arcs}
      <text x="50" y="54" textAnchor="middle" fontSize="11" fill={color}>
        {PERSIAN.format(values.length)} بخش</text>
    </svg>
    <div className="mdash-donut-legend">{values.map((item,index)=><div key={index}>
      <i style={{background:PALETTE[index%PALETTE.length]}}/>
      <span title={item.label}>{item.label}</span><b>{PERSIAN.format(item.value/total*100)}٪</b>
    </div>)}</div>
  </div>;
}
function MiniChart({chart,color,large=false}){
  const type=String(chart.type).toLowerCase();
  return ['donut','pie','doughnut'].includes(type)?
    <Donut points={chart.points} color={color} large={large}/>:
    ['bar','column','bars'].includes(type)?
      <Bars points={chart.points} color={color} large={large}/>:
      <Sparkline points={chart.points} secondary={chart.second}
        color={color} large={large}/>;
}

export default function AccountingManagementDashboard({view,currency='RIAL',onNavigate}){
  const [now,setNow]=useState(()=>new Date());
  const [mode,setMode]=useState('month');
  const [range,setRange]=useState(()=>chooseRange('month',new Date()));
  const [customOpen,setCustomOpen]=useState(false);
  const [selected,setSelected]=useState(null);
  useEffect(()=>{
    const timer=setInterval(()=>setNow(new Date()),30000);
    return ()=>clearInterval(timer);
  },[]);
  const today=dayIso(now);
  const validRange=Boolean(range.start&&range.end&&range.start<=range.end&&range.end<=today);
  const unit=currency==='TOMAN'?'تومان':'ریال';
  const {analytics,error}=useMemo(()=>{
    if(!validRange)return {analytics:null,error:'بازهٔ زمانی باید معتبر و به‌ترتیب از تاریخ شروع تا پایان باشد.'};
    try{return {analytics:buildManagementAnalytics(view,{
      currency,fromDate:range.start,toDate:range.end,
      from:range.start,to:range.end,today,
      startDate:range.start,endDate:range.end}),error:''};}
    catch(err){return {analytics:null,error:err?.message||'محاسبه شاخص‌های مدیریتی ناموفق بود.'};}
  },[view,currency,range.start,range.end,validRange,today]);
  const metrics=useMemo(()=>normalizedKpis(analytics),[analytics]);
  const charts=useMemo(()=>normalizedCharts(analytics),[analytics]);
  const cheques=useMemo(()=>realChequeReminders(view,today),[view,today]);
  const visible=cheques.slice(0,5);
  const go=(item)=>{
    const tab=targetTab(item);
    if(typeof onNavigate==='function'&&tab&&['overview','invoice','proforma','bill',
      'contractors','parties','migration','cheques','items','settlements','cash',
      'accounts','journal','reports','payroll','period','company'].includes(tab))
      onNavigate(tab,{metric:item.id,fromDate:range.start,toDate:range.end});
  };
  const chooseMode=next=>{
    setMode(next);
    if(next==='custom'){setCustomOpen(true);return;}
    setRange(chooseRange(next,now));setCustomOpen(false);
  };
  return <main className="mdash madar-management-dashboard" dir="rtl"
    aria-label="داشبورد مدیریتی حسابداری">
    <div className="mdash-head">
      <div><span className="mdash-eyebrow"><Activity size={13}/> نمای مدیریتی / MADAR INSIGHTS</span>
        <h2>نبض کسب‌وکار شما</h2>
        <p>مروری بر اطلاعات ثبت‌شده در دفتر مالی جاری، با امکان بررسی جزئیات هر شاخص.</p>
      </div>
      <div className="mdash-filters" aria-label="بازه گزارش مدیریتی">
        <div className="mdash-segments" role="group" aria-label="انتخاب بازه زمانی">
          {[[ 'month','ماه جاری'],['30d','۳۰ روز'],['90d','۹۰ روز'],
            ['year','سال جاری']].map(([key,label])=><button type="button"
              key={key} aria-pressed={mode===key} className={mode===key?'active':''}
              onClick={()=>chooseMode(key)}>{label}</button>)}
        </div>
        <button type="button" className={'mdash-range-trigger'+(customOpen?' active':'')}
          aria-expanded={customOpen} aria-controls="mdash-custom-range"
          onClick={()=>{setCustomOpen(v=>!v);setMode('custom');}}>
          <SlidersHorizontal size={16}/> بازه دلخواه</button>
      </div>
    </div>
    {customOpen&&<section className="mdash-custom-range" id="mdash-custom-range"
      aria-label="فیلتر تاریخ شمسی">
      <div><b>انتخاب بازه به تقویم شمسی</b><small>گزارش با تاریخ‌های واقعی دفتر محاسبه می‌شود.</small></div>
      <label>از تاریخ<AccountingJalaliField value={range.start} max={today}
        onChange={start=>setRange(p=>({...p,start}))} ariaLabel="تاریخ شروع شمسی"/></label>
      <label>تا تاریخ<AccountingJalaliField value={range.end} max={today}
        onChange={end=>setRange(p=>({...p,end}))} ariaLabel="تاریخ پایان شمسی"/></label>
      <button type="button" className="mdash-close-range" title="بستن انتخاب بازه"
        onClick={()=>setCustomOpen(false)}><Check size={16}/> بستن</button>
    </section>}
    <div className="mdash-caption"><CalendarDays size={14}/>
      <span>{range.start&&formatAccountingJalali(range.start)||'تاریخ شروع نامعتبر'} تا{' '}
        {range.end&&formatAccountingJalali(range.end)||'تاریخ پایان نامعتبر'}</span>
      <span className="mdash-currency">تمام مبالغ به {unit}</span>
    </div>
    {(error||analytics?.error)&&<div className="mdash-error" role="alert">
      {error||analytics.error}</div>}
    <div className="mdash-layout">
      <div className="mdash-main">
        <section className="mdash-kpis" aria-label="شاخص‌های مالی">
          {metrics.length?metrics.map((metric,i)=><button type="button"
            key={metric.id} className="mdash-kpi" onClick={()=>go(metric)}
            title={metric.description||`ورود به گزارش ${metric.label}`}>
            <span className="mdash-kpi-top"><span className="mdash-kpi-icon"
              style={{'--md-kpi-color':PALETTE[i%PALETTE.length]}}>
              {i%4===0?<ChartNoAxesCombined size={17}/>:
                i%4===1?<Wallet size={17}/>:
                  i%4===2?<Landmark size={17}/>:<FileBarChart2 size={17}/>}
            </span><ArrowUpLeft size={15}/></span>
            <span className="mdash-kpi-title">{metric.label}</span>
            <strong className="mdash-kpi-value" dir="auto">{humanNumber(metric.value)}
              {metric.unit!==false&&<small>{metric.unit||unit}</small>}</strong>
            <span className="mdash-kpi-desc">{metric.description||'بر اساس داده‌های دفتر'}</span>
          </button>):<div className="mdash-data-empty">شاخص مدیریتی برای این بازه در دسترس نیست.</div>}
        </section>
        <section className="mdash-charts" aria-label="نمودارهای تحلیلی">
          {charts.length?charts.map((chart,index)=><button type="button"
            className={'mdash-chart-card madar-dashboard-chart'+(index<2?' featured':'')}
            data-chart-id={chart.id}
            key={chart.id} onClick={()=>setSelected(chart.id)}
            title={'جزئیات نمودار '+chart.title}>
            <span className="mdash-chart-head"><span><b>{chart.title}</b>
              <small>{chart.subtitle||(chart.id==='monthlySales'?
                'گروه‌بندی ماهانه میلادی، با فیلتر تاریخ شمسی':
                'بر اساس تراکنش‌های بازهٔ انتخاب‌شده')}</small></span>
              <span className="mdash-open-chart"><ArrowUpLeft size={16}/></span></span>
            <MiniChart chart={chart} color={PALETTE[index%PALETTE.length]}/>
            <span className="mdash-chart-foot"><span>{chart.second?.length&&
              chart.secondLabel?<><i/>{chart.secondLabel}</>:chart.unit||unit}</span>
              <span>مشاهده جزئیات <ChevronLeft size={14}/></span></span>
          </button>):<div className="mdash-data-empty">برای نمایش روندها هنوز دادهٔ قابل نمودار موجود نیست.</div>}
        </section>
        {analytics?.costData?.available===false&&<section className="mdash-cost-notice"
          aria-label="وضعیت تحلیل سودآوری کالاها">
          <span><FileBarChart2 size={20}/></span>
          <div><strong>پرسودترین کالا یا خدمت</strong>
            <p>اطلاعات کافی نیست. {analytics.costData.reason||'اطلاعات بهای تمام‌شده برای محاسبه سود هر کالا کامل نیست.'}</p>
          </div>
          <span className="mdash-cost-status">تحلیل ناموجود</span>
        </section>}
        {Array.isArray(analytics?.warnings)&&analytics.warnings.length>0&&
          <details className="mdash-methods">
            <summary>روش محاسبه و محدودیت شاخص‌ها</summary>
            <ul>{analytics.warnings.map((message,i)=><li key={i}>{message}</li>)}</ul>
          </details>}
      </div>
      <aside className="mdash-rail" aria-label="زمان و یادآورهای مالی">
        <section className="mdash-clock-card" aria-label="ساعت و تاریخ جاری سیستم">
          <div className="mdash-clock-label"><Clock3 size={18}/> ساعت و تاریخ امروز <span className="mdash-live-dot"/></div>
          <time className="mdash-clock-time" dateTime={now.toISOString()} dir="ltr">
            {PERSIAN_TIME.format(now)}</time>
          <div className="mdash-clock-rule"/>
          <strong>{PERSIAN_DATE.format(now)}</strong>
          <small>{PERSIAN_WEEKDAY.format(now)} · ساعت محلی دستگاه</small>
        </section>
        <section className="mdash-reminders">
          <div className="mdash-rail-heading"><div><span className="mdash-rail-icon"><CalendarClock size={19}/></span>
              <span><strong>یادآورهای مالی</strong><small>چک‌های هفت روز آینده و معوق</small></span></div>
            <span className="mdash-reminder-count">{PERSIAN.format(cheques.length)}</span>
          </div>
          {visible.length?<div className="mdash-reminder-list">
            {visible.map((ch,index)=>{
              const urgency=chequeUrgency(ch);
              const party=view?.parties?.[ch.partyId]?.name||ch.partyId||'طرف‌حساب نامشخص';
              return <button type="button" className="mdash-reminder madar-dashboard-reminder"
                key={ch.id||index}
                onClick={()=>go({id:'cheques'})} title={'مشاهده چک '+(ch.reference||ch.id||'')}>
                <span className={'mdash-reminder-mark '+urgency.tone}/>
                <span className="mdash-reminder-body"><b>{ch.direction==='receipt'?'چک دریافتی':
                  ch.direction==='payment'?'چک پرداختی':'چک ثبت‌شده'} · {ch.reference||ch.id||'بدون شماره'}</b>
                  <small>{party}</small>
                  <small>{formatAccountingJalali(ch.dueDate)} · {statusName(ch.status)}</small></span>
                <span className="mdash-reminder-end"><em className={urgency.tone}>
                  {urgency.label}</em><b>{Number.isFinite(ch.amount)?humanNumber(ch.amount):'—'}</b></span>
              </button>;
            })}</div>:<div className="mdash-reminder-empty"><span><Check size={18}/></span>
              <b>یادآور چک فعالی ثبت نشده</b>
              <small>در دفتر فعلی چک عملیاتی معوق یا سررسید هفت روز آینده موجود نیست.</small>
            </div>}
          {cheques.length>visible.length&&<p className="mdash-more-count">
            {PERSIAN.format(cheques.length-visible.length)} چک دیگر در فهرست کامل موجود است.</p>}
          <button type="button" className="mdash-rail-action" onClick={()=>go({id:'cheques'})}>
            ورود به خزانه و چک <ArrowLeft size={15}/></button>
        </section>
        <section className="mdash-rail-note"><span><Activity size={17}/></span>
          <p>اعداد این صفحه از دفتر انتخاب‌شده محاسبه می‌شوند. اسناد تاریخی تطبیق‌نشده در یادآور چک‌ها وارد نمی‌شوند.</p>
        </section>
      </aside>
    </div>
    {selected&&charts.some(c=>c.id===selected)&&(()=>{
      const chart=charts.find(c=>c.id===selected);
      const color=PALETTE[charts.indexOf(chart)%PALETTE.length];
      return <div className="mdash-detail-backdrop madar-dashboard-drilldown"
        onClick={()=>setSelected(null)}>
        <section className="mdash-detail" role="dialog" aria-modal="true"
          aria-label={'جزئیات '+chart.title} onClick={e=>e.stopPropagation()}>
          <header><div><span className="mdash-eyebrow">نمای جزئیات</span><h3>{chart.title}</h3>
            <p>{chart.subtitle||'روند واقعی در بازه انتخاب‌شده'} · {formatAccountingJalali(range.start)} تا {formatAccountingJalali(range.end)}</p></div>
            <button type="button" aria-label="بستن جزئیات" onClick={()=>setSelected(null)}>
              <X size={20}/></button></header>
          <div className="mdash-detail-range" aria-label="تغییر بازه زمانی جزئیات">
            <span><CalendarDays size={17}/> بازه گزارش</span>
            <label>از تاریخ <AccountingJalaliField value={range.start} max={today}
              onChange={start=>{setMode('custom');setRange(r=>({...r,start}));}}
              ariaLabel="تاریخ شروع جزئیات"/></label>
            <label>تا تاریخ <AccountingJalaliField value={range.end} max={today}
              onChange={end=>{setMode('custom');setRange(r=>({...r,end}));}}
              ariaLabel="تاریخ پایان جزئیات"/></label>
          </div>
          {!validRange&&<p className="mdash-error" role="alert">بازهٔ انتخاب‌شده معتبر نیست.</p>}
          <MiniChart chart={chart} color={color} large/>
          <div className="mdash-detail-table"><table><thead><tr><th>دوره / شرح</th>
            <th>مقدار ({chart.unit||unit})</th>{chart.second?.length>0&&<th>{chart.secondLabel||'سری دوم'}</th>}</tr></thead>
            <tbody>{chart.points.length?chart.points.map((p,i)=><tr key={i}>
              <td>{p.label}</td><td dir="ltr">{humanNumber(p.value)}</td>
              {chart.second?.length>0&&<td dir="ltr">{chart.second[i]?
                humanNumber(chart.second[i].value):'—'}</td>}</tr>):
              <tr><td colSpan={chart.second?.length?3:2}>ردیفی در این بازه ثبت نشده است.</td></tr>}</tbody></table></div>
          <footer><button type="button" onClick={()=>setSelected(null)}>بستن</button>
            <button type="button" className="mdash-detail-action" onClick={()=>{
              setSelected(null);go(chart);
            }}>رفتن به بخش مرتبط <ArrowLeft size={16}/></button></footer>
        </section>
      </div>;
    })()}
  </main>;
}
