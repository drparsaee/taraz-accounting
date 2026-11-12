import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './standalone_accounting_workspace.jsx';
import {TarazSileoToaster,tarazToast} from './taraz_sileo_feedback.jsx';
import './styles.css';
import {installFloatingLabels} from './floating_labels.js';
import './floating_labels.css';

// The accounting window can launch on its own. Default to the requested
// graphite presentation, but preserve an explicit light preference previously
// chosen in the task-manager shell. This key never carries finance data.
try {
  const choice=window.localStorage.getItem('taraz-ui-theme');
  document.documentElement.dataset.theme=choice==='light'?'light':'dark';
} catch (_error) {
  document.documentElement.dataset.theme='dark';
}

class AccountingErrorBoundary extends React.Component {
  constructor(props){super(props);this.state={failed:false};}
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(_error){console.error('Taraz accounting UI render failure (details intentionally hidden)');}
  render(){
    if(!this.state.failed)return this.props.children;
    return <main dir="rtl" role="alert" style={{fontFamily:'Tahoma,sans-serif',
      padding:32,color:'#873d2f',background:'#fff1ec',lineHeight:2}}>
      <h2>خطا در نمایش رابط حسابداری</h2>
      <p>نمایش برنامه متوقف شده است. اطلاعات ثبت‌شده حسابداری حذف یا تغییر نکرده‌اند.</p>
      <button type="button" onClick={()=>window.location.reload()}>بازکردن دوباره</button>
    </main>;
  }
}

const unavailable=async()=>{throw Error('این بخش فقط با میزبان امن برنامه ویندوز فعال است.');};
const api=window.madar || {
  standaloneAccountingRead: unavailable,
  standaloneAccountingCommand: unavailable,
};
function AuthenticatedAccounting(){
  // Rendering mutation buttons just because a JS bridge exists is not
  // authorization: financeView-only users can still have that same bridge.
  const [canManage,setCanManage]=React.useState(false);
  const [canDraft,setCanDraft]=React.useState(false);
  const [canAdmin,setCanAdmin]=React.useState(false);
  React.useEffect(()=>{
    let active=true;
    Promise.resolve().then(()=>api.standaloneAccountingRead()).then(payload=>{
      if(active){
        setCanManage(payload?.capabilities?.canManage===true);
        setCanDraft(payload?.capabilities?.canDraft===true);
        setCanAdmin(payload?.capabilities?.canAdmin===true);
      }
    }).catch(()=>{if(active){setCanManage(false);setCanDraft(false);setCanAdmin(false);}});
    return ()=>{active=false;};
  },[]);
  return <StandaloneAccountingWorkspace api={api} canManage={canManage}
    canDraft={canDraft} canAdmin={canAdmin}
    onManageUsers={canAdmin&&typeof api.standaloneAccountingManageUsers==='function'?
      async()=>{
        try{await api.standaloneAccountingManageUsers();}
        catch(_error){window.alert('مدیریت کاربران انجام نشد؛ مجوز و وضعیت میزبان را بررسی کنید.');}
      }:null}
    onSwitchCompany={typeof api.standaloneAccountingRequestCompanySwitch==='function'?
      async()=>{
        if(!window.confirm('تغییر شرکت، فرم‌های ذخیره‌نشده را کنار می‌گذارد. دفتر فعلی پس از بکاپ ایمن بسته می‌شود. ادامه دهید؟'))return;
        try{
          const acknowledged=await api.standaloneAccountingRequestCompanySwitch();
          if(acknowledged===true)tarazToast({kind:'companyRequest',section:'company'});
          // The Windows host now closes its OWN window after the mandatory
          // final backup. JavaScript window.close() may be ignored by WebView2.
        }catch(_error){window.alert('تغییر شرکت انجام نشد؛ وضعیت میزبان و پشتیبان را بررسی کنید.');}
      }:null}
    onExit={()=>{
      if(window.__madarStandaloneOnly){window.close();return;}
      window.location.assign('./index.html');
    }}/>;
}
const root=document.getElementById('root');
createRoot(root).render(
  <>
    <TarazSileoToaster/>
    <AccountingErrorBoundary>
      <AuthenticatedAccounting/>
    </AccountingErrorBoundary>
  </>
);
installFloatingLabels(document);
