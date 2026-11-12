import React from 'react';
import {BookOpen,ClipboardList,FileText,Landmark,Layers3,Settings2,Users,Wallet} from 'lucide-react';
import AccountingNavigationShell from './accounting_navigation_shell.jsx';
import './accounting_top_ribbon.css';
import './taraz_madar_dashboard.css';

/** The original Ribbon grouping is available to professional users. */
export const ACCOUNTING_RIBBON_GROUPS=[
  {id:'general',title:'عمومی',icon:Landmark,items:['overview','madar','orders','invoice','proforma']},
  {id:'documents',title:'فاکتورها و سفارش‌ها',icon:FileText,items:['orders','invoice','invoiceDesign','proforma','bill','contractors']},
  {id:'records',title:'اشخاص و کالا',icon:Users,items:['parties','items','company']},
  {id:'treasury',title:'خزانه و پرداخت',icon:Wallet,items:['settlements','cash','cheques']},
  {id:'ledger',title:'حسابداری',icon:BookOpen,items:['accounts','journal','period']},
  {id:'reports',title:'گزارش‌ها و سوابق',icon:Layers3,items:['reports','migration']},
  {id:'settings',title:'تنظیمات و مدیریت',icon:Settings2,items:['settings','company','payroll','period']},
];
export const accountingRibbonGroupFor=tab=>{
  if(tab==='overview')return 'general';
  if(tab==='settings')return 'settings';
  if(['orders','invoice','invoiceDesign','proforma','bill','contractors'].includes(tab))return 'documents';
  return ACCOUNTING_RIBBON_GROUPS.find(group=>group.items.includes(tab))?.id||'general';
};

export default function AccountingTopRibbon(props){
  return <>
    <AccountingNavigationShell {...props} groups={ACCOUNTING_RIBBON_GROUPS}
      groupFor={accountingRibbonGroupFor}/>
    <nav className="taraz-madar-quick-nav" aria-label="دسترسی مستقیم به اطلاعات مدار">
      <button type="button" data-accounting-tab="madar" aria-current={props.tab==='madar'?'page':undefined}
        disabled={props.disabled} onClick={()=>props.onNavigate?.('madar')}>
        <ClipboardList size={18} aria-hidden="true"/> اطلاعات مدار
      </button>
    </nav>
  </>;
}
