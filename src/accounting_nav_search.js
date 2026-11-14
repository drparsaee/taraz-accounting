/** Navigation is a client convenience. The authenticated accounting host alone
 * determines which records the current user may read or mutate. Never fetch or
 * cache a second company, and never index raw imports, notes or ledger lines. */
// Give the two delivered workspaces a visible entry; buying/payment remain
// available in the full drawer. A tab's existence is not release acceptance.
export const ACCOUNTING_PRIMARY_SECTIONS=['overview','invoice','orders','ai','reports'];
const PRIVATE_SECTION_ROLES={migration:'admin'};
const CATEGORY_DEFS=[
  {key:'invoices',tab:'invoice',type:'invoice',label:'فاکتور فروش'},
  {key:'bills',tab:'bill',type:'bill',label:'صورتحساب خرید'},
  {key:'proformas',tab:'proforma',type:'proforma',label:'پیش‌فاکتور'},
  {key:'parties',tab:'parties',type:'party',label:'طرف‌حساب'},
  {key:'accounts',tab:'accounts',type:'account',label:'حساب'},
  {key:'journals',tab:'journal',type:'journal',label:'سند دفترکل'},
  {key:'receipts',tab:'settlements',type:'receipt',label:'دریافت'},
  {key:'payments',tab:'settlements',type:'payment',label:'پرداخت'},
];
const RECORD_TYPES=new Set(CATEGORY_DEFS.map(item=>item.key));
const VALID_ROLES=new Set(['admin','editor','viewer']);
const safeLabel=value=>{
  const text=Number.isSafeInteger(value)?String(value):
    typeof value==='string'?value:'';
  return text.replace(/[\x00-\x1f\x7f]/g,' ').trim().slice(0,140);
};
const safeId=value=>typeof value==='string'&&/^[\w.:-]{1,96}$/.test(value)?value:'';
const entries=collection=>Array.isArray(collection)?collection:
  collection&&typeof collection==='object'?Object.values(collection):[];

export const normalizeAccountingSearch=value=>String(value??'')
  .replace(/[\u064b-\u065f\u0670]/g,'')
  .replace(/[٠-٩۰-۹]/g,d=>String(d.charCodeAt(0)-(d.charCodeAt(0)>1700?1776:1632)))
  .replace(/[يى]/g,'ی').replace(/ك/g,'ک')
  .toLocaleLowerCase('fa-IR').replace(/\s+/g,' ').trim();

export function accountingVisibleSections(sections=[],role='viewer',sectionAccess=null){
  if(!VALID_ROLES.has(role))return [];
  return (Array.isArray(sections)?sections:[]).filter(item=>
    Array.isArray(item)&&typeof item[0]==='string'&&typeof item[1]==='string'&&
    (PRIVATE_SECTION_ROLES[item[0]]===undefined||role==='admin')&&
    sectionAccess?.[item[0]]!==false);
}

export function buildAccountingSearchIndex({sections=[],view=null,role='viewer',sectionAccess=null,
  recordAccess=null}={}){
  const visible=accountingVisibleSections(sections,role,sectionAccess);
  const index=visible.map(([tab,label])=>({key:'section:'+tab,type:'section',tab,
    title:label,subtitle:'بخش حسابداری',recordId:'',
    searchable:normalizeAccountingSearch(label+' '+tab)}));
  // No authenticated role or no explicitly supplied host-scoped snapshot: only sections.
  if(!VALID_ROLES.has(role)||!view||typeof view!=='object'||Array.isArray(view))return index;
  const allowedTabs=new Set(visible.map(([id])=>id));
  const parties=view.parties&&typeof view.parties==='object'?view.parties:{};
  for(const def of CATEGORY_DEFS){
    if(!RECORD_TYPES.has(def.key)||!allowedTabs.has(def.tab)||recordAccess?.[def.key]===false)
      continue;
    for(const record of entries(view[def.key])){
      if(!record||typeof record!=='object')continue;
      const id=safeId(record.id);
      if(!id)continue;
      const partyId=safeId(record.partyId);
      const partyName=safeLabel(parties[partyId]?.name);
      const name=safeLabel(record.name);
      const docNumber=safeLabel(record.number);
      const title=def.type==='party'||def.type==='account'?
        (name||id):id;
      const extra=def.type==='party'||def.type==='account'?
        id:[docNumber,partyName].filter(Boolean).join(' · ');
      // Display and match only the same field whitelist. No notes, lines, amounts,
      // account balances, hidden metadata, credentials or historical raw archives.
      const subtitle=def.label+(extra?' · '+extra:'');
      index.push({key:def.type+':'+id,type:def.type,tab:def.tab,recordId:id,
        title,subtitle,searchable:normalizeAccountingSearch(
          [id,docNumber,name,partyId,partyName,def.label].filter(Boolean).join(' '))});
    }
  }
  return index;
}

export function searchAccountingIndex(index,query,limit=12){
  const term=normalizeAccountingSearch(query);
  if(!term||term.length>140||!Array.isArray(index))return [];
  const terms=term.split(' ').filter(Boolean);
  const results=[];
  for(const item of index){
    if(!item?.searchable||!terms.every(word=>item.searchable.includes(word)))continue;
    const title=normalizeAccountingSearch(item.title);
    const rank=title===term?0:title.startsWith(term)?1:
      item.type==='section'?2:3;
    results.push({item,rank});
  }
  results.sort((a,b)=>a.rank-b.rank||a.item.title.localeCompare(b.item.title,'fa-IR'));
  return results.slice(0,Number.isInteger(limit)?Math.max(1,Math.min(limit,50)):12)
    .map(hit=>hit.item);
}
