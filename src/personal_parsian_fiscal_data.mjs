// Read-only fiscal snapshot. Balances are not settlement allocations.
// 1404 is the archived source-year balance; 1405 tracks native GL updates.
const integer = value => {
  if (typeof value === 'number') return Number.isSafeInteger(value) ? value : null;
  if (typeof value === 'string' && /^-?(0|[1-9][0-9]*)$/.test(value)) {
    const n = Number(value);
    return Number.isSafeInteger(n) ? n : null;
  }
  return null;
};
const add = (a, b) => Number.isSafeInteger(a + b) ? a + b : null;
export function personalFiscalPosition(view, history, year='1405') {
  if (!['1404','1405'].includes(year) ||
    history?.summary?.currency !== 'RIAL' ||
    !Array.isArray(history.parties) || !Array.isArray(history.invoices)) return null;
  const records = history.parties.filter(p => p?.year === year);
  const invoices = history.invoices.filter(i => i?.year === year);
  if (!records.length) return null;
  let receivable=0, payable=0;
  const people=[];
  for (const p of records) {
    let signed=integer(p.balance_signed_rial);
    if (year==='1405' && view?.parties) {
      const live=view.parties[p.madar_id];
      // The current-year balance comes from the same imported tafsili GL account.
      if (!live || live.sourceLedgerAccountId !== 'ps.parsian.account.t.'+p.code)
        return null;
      signed=integer(live.historicalBalanceRial);
    }
    if (signed===null) return null;
    const credit=add(payable,Math.max(0,-signed));
    const debit=add(receivable,Math.max(0,signed));
    if(credit===null||debit===null)return null;
    payable=credit;receivable=debit;
    people.push({id:p.madar_id||year+':'+p.code,code:p.code,name:p.name,
      signed,receivable:Math.max(0,signed),payable:Math.max(0,-signed)});
  }
  const net=add(receivable,-payable);
  if(net===null)return null;
  const sourceLines=Array.isArray(history.journalLines)?
    history.journalLines.filter(l=>l?.year===year):[];
  const bankFlows={cash:{debit:0,credit:0},bank:{debit:0,credit:0}};
  for(const line of sourceLines){
    const group=/^ps\.parsian\.account\.m\.(10|11)\.[0-9]+$/.exec(String(line.account_id||''));
    if(!group)continue;
    const kind=group[1]==='10'?'cash':'bank';
    const debit=integer(line.debit_rial),credit=integer(line.credit_rial);
    if(debit===null||credit===null)return null;
    const nextDebit=add(bankFlows[kind].debit,debit),nextCredit=add(bankFlows[kind].credit,credit);
    if(nextDebit===null||nextCredit===null)return null;
    bankFlows[kind]={debit:nextDebit,credit:nextCredit};
  }
  return {year,currency:'RIAL',balanceSource:year==='1405'?'native-current':'parsian-archive',
    receivable,payable,net,parties:people.length,debtors:people.filter(x=>x.signed>0).length,
    creditors:people.filter(x=>x.signed<0).length,people:people.sort((a,b)=>Math.abs(b.signed)-Math.abs(a.signed)),
    invoiceCount:invoices.length,matchedInvoices:invoices.filter(x=>x.status==='matched').length,
    inventoryOnlyInvoices:invoices.filter(x=>x.status==='inventory_only').length,
    bankFlows,sourceJournalLines:sourceLines.length};
}
