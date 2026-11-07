// Pure, source-backed financial summary for the owner's personal Parsian ledger.
// Never infer settlement, spendable liquidity, or operational invoices from GL balances.
export function personalLedgerSnapshot(view, history=null) {
  if (!view || view.currency!=='RIAL' || !view.accounts || !Array.isArray(view.journals)) return null;
  const imported=view.journals.filter(j=>typeof j?.eventId==='string' &&
    /^ps\.parsian\.journal\.14(?:04|05)\./.test(j.eventId));
  if (imported.length===0) return null;
  const totals={}, bankAccounts=[];
  for(const account of Object.values(view.accounts)) {
    const id=String(account?.id||'');
    const match=id.match(/^ps\.parsian\.account\.(?:k|m|t)\.([0-9]+)(?:\.|$)/);
    if(!match)continue;
    const code=match[1], value=account.debitMinusCredit;
    if(!Number.isSafeInteger(value))return null;
    const total=(totals[code]||0)+value;
    if(!Number.isSafeInteger(total))return null;
    totals[code]=total;
    if(code==='11' && value!==0) bankAccounts.push({id,name:account.name||id,balance:value});
  }
  const money=(code)=>totals[code]||0;
  const sales=-money('60')-money('61');
  if(!Number.isSafeInteger(sales))return null;
  const count=prefix=>imported.filter(j=>j.eventId.startsWith(prefix)).length;
  const source=history?.summary;
  const year1404=count('ps.parsian.journal.1404.');
  const year1405=count('ps.parsian.journal.1405.');
  return {
    currency:'RIAL', source:'parsian-personal-gl',
    importedJournals:imported.length, year1404,year1405,
    totalJournals:view.journals.length,
    invoices:source?.invoices ?? null,
    matchedInvoices:source?.matchedInvoices ?? null,
    goods:Object.keys(view.items||{}).filter(k=>k.startsWith('ps.parsian.')).length,
    parties:Object.keys(view.parties||{}).filter(k=>k.startsWith('ps.parsian.')).length,
    totalAccountCount:Object.keys(view.accounts).filter(k=>k.startsWith('ps.parsian.')).length,
    cash:money('10'),bank:money('11'),customerNet:money('12'),
    salesNet:sales, expense:money('50'),discounts:money('61'),
    bankAccounts:bankAccounts.sort((a,b)=>Math.abs(b.balance)-Math.abs(a.balance)),
    operationalInvoices:Object.keys(view.invoices||{}).length,
    operationalReceipts:Object.keys(view.receipts||{}).length,
    operationalPayments:Object.keys(view.payments||{}).length,
    endOfSourceYear:'1405',
  };
}
