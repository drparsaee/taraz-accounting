/**
 * Read-only exposure report over an authenticated accounting_view() projection.
 *
 * All outstanding amounts are CURRENT (the projection holds cumulative
 * allocations/returns). referenceDate affects only ageing of those current
 * amounts; it does not reconstruct historical balances at that date.
 * Operational cheques are commitments until cleared, not cash or settlements.
 * Imported Parsian balances are deliberately outside these native documents.
 */
const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const rows = (value, field) => {
  if (!isRecord(value)) throw Error('Invalid accounting collection: ' + field);
  return Object.entries(value);
};
const amount = (value, field) => {
  // accounting_view publishes exact integer ledger amounts, not localized text.
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw Error('Unsafe or invalid amount: ' + field);
  }
  return BigInt(value);
};
const toNumber = (value, field) => {
  if (value > MAX_SAFE || value < -MAX_SAFE) {
    throw Error('Total exceeds exact JavaScript integer range: ' + field);
  }
  return Number(value);
};
const day = (value, field) => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw Error('Invalid ISO date: ' + field);
  }
  const epoch = Date.parse(value + 'T00:00:00Z');
  if (!Number.isFinite(epoch) || new Date(epoch).toISOString().slice(0, 10) !== value) {
    throw Error('Nonexistent calendar date: ' + field);
  }
  return epoch / 86400000;
};
const AGE = ['notDue', 'days1to30', 'days31to60', 'days61to90', 'daysOver90', 'unknownDue'];
const newAmounts = () => Object.fromEntries(AGE.map(key => [key, 0n]));
const category = (due, reference) => {
  if (due === null || due === undefined) return {bucket: 'unknownDue', daysOverdue: null};
  const n = Math.max(0, reference - day(due, 'document dueDate'));
  return {bucket: n === 0 ? 'notDue' : n <= 30 ? 'days1to30' :
    n <= 60 ? 'days31to60' : n <= 90 ? 'days61to90' : 'daysOver90',
  daysOverdue: n};
};
const makeDirection = () => ({outstanding: 0n, documentCount: 0, parties: new Map(),
  ageing: newAmounts()});
const directionReport = (source, label) => ({
  outstanding: toNumber(source.outstanding, label),
  documentCount: source.documentCount,
  partyCount: source.parties.size,
  ageing: Object.fromEntries(AGE.map(key => [key, toNumber(source.ageing[key], label + ' ageing')])),
});

/**
 * @param {object} view Authenticated, materialized accounting_view() result.
 * @param {{referenceDate:string}} options Gregorian ISO YYYY-MM-DD, not Jalali.
 * @returns {object} Native current unpaid documents, ageing, period of issue,
 *                    and separate cheque commitments; no mutation.
 */
export function summarizeFinancialExposure(view, options = {}) {
  if (!isRecord(view) || !['RIAL', 'TOMAN'].includes(view.currency) ||
      !isRecord(options) || !Array.isArray(view.fiscalYears)) {
    throw Error('Invalid authenticated accounting_view projection');
  }
  const refDay = day(options.referenceDate, 'referenceDate');
  const parties = new Map(rows(view.parties, 'parties'));
  const accounts = new Map(rows(view.accounts, 'accounts'));
  const summary = {receipt: makeDirection(), payment: makeDirection()};
  const byParty = new Map();
  for (const [id, person] of parties) {
    if (!isRecord(person) || typeof person.name !== 'string') {
      throw Error('Invalid party record: ' + id);
    }
    byParty.set(id, {partyId: id, name: person.name, receivable: 0n, payable: 0n});
  }

  const fiscal = view.fiscalYears.map((row, i) => {
    if (!isRecord(row) || typeof row.periodId !== 'string' || !row.periodId ||
        day(row.startDate, 'fiscal start') > day(row.throughDate, 'fiscal close')) {
      throw Error('Invalid closed fiscal period: ' + i);
    }
    return {periodId: row.periodId, startDate: row.startDate, throughDate: row.throughDate,
      receivable: 0n, payable: 0n};
  }).sort((a, b) => a.startDate.localeCompare(b.startDate));
  if (new Set(fiscal.map(row => row.periodId)).size !== fiscal.length) {
    throw Error('Duplicate fiscal period identifier');
  }
  for (let i = 1; i < fiscal.length; i++) {
    if (fiscal[i].startDate <= fiscal[i - 1].throughDate) {
      throw Error('Overlapping fiscal periods');
    }
  }
  const openPeriod = {periodId: null, receivable: 0n, payable: 0n};
  const documents = [];
  for (const [collectionName, type, key] of [
    ['invoices', 'receipt', 'receivable'], ['bills', 'payment', 'payable'],
  ]) {
    const direction = summary[type];
    for (const [id, invoice] of rows(view[collectionName], collectionName)) {
      if (!isRecord(invoice)) throw Error('Invalid document: ' + id);
      if (invoice.status !== 'issued') continue;
      if (typeof invoice.partyId !== 'string' || !byParty.has(invoice.partyId)) {
        throw Error('Unknown document party: ' + id);
      }
      const total = amount(invoice.total, id + ' total');
      const allocated = amount(invoice.allocated, id + ' allocated');
      const returned = amount(invoice.returnedAmount ?? 0, id + ' returned');
      if (allocated + returned > total) throw Error('Document overallocated: ' + id);
      day(invoice.postingDate, id + ' postingDate');
      const unpaid = total - allocated - returned;
      if (!unpaid) continue;
      const {bucket, daysOverdue} = category(invoice.dueDate, refDay);
      const person = byParty.get(invoice.partyId);
      const period = fiscal.find(row => row.startDate <= invoice.postingDate &&
        invoice.postingDate <= row.throughDate) || openPeriod;
      const d = {documentId: id, direction: type, partyId: invoice.partyId,
        partyName: person.name, postingDate: invoice.postingDate,
        dueDate: invoice.dueDate ?? null, daysOverdue, ageBucket: bucket,
        outstanding: toNumber(unpaid, id), fiscalPeriodId: period.periodId};
      documents.push(d);
      direction.documentCount++;
      direction.parties.set(invoice.partyId, true);
      direction.outstanding += unpaid;
      direction.ageing[bucket] += unpaid;
      person[key] += unpaid;
      period[key] += unpaid;
    }
  }
  // Detect an aggregate outside JS's exact range before comparing against the
  // projection controls (which necessarily use safe machine numbers).
  toNumber(summary.receipt.outstanding, 'native receivable total');
  toNumber(summary.payment.outstanding, 'native payable total');
  for (const [id, person] of byParty) {
    const source = parties.get(id);
    if (person.receivable !== amount(source.receivable, id + ' receivable') ||
        person.payable !== amount(source.payable, id + ' payable')) {
      throw Error('Native document and party balance mismatch: ' + id);
    }
  }
  // Cross-check only the native AR/AP controls, not imported account balances.
  for (const [id, type, sign] of [['1200', 'receipt', 1n], ['2000', 'payment', -1n]]) {
    const account = accounts.get(id);
    if (!isRecord(account) || !Number.isSafeInteger(account.debitMinusCredit) ||
        BigInt(account.debitMinusCredit) * sign !== summary[type].outstanding) {
      throw Error('Native document and AR/AP control mismatch: ' + id);
    }
  }
  documents.sort((a, b) => (b.daysOverdue ?? -1) - (a.daysOverdue ?? -1) ||
    b.outstanding - a.outstanding || a.documentId.localeCompare(b.documentId));

  // A pending or returned cheque is a commitment/risk item, not a receipt or
  // payment. It must never be deducted from the open invoice or bill amount.
  const cheques = {receipt: {count: 0, amount: 0n},
    payment: {count: 0, amount: 0n}, returnedCount: 0, returnedAmount: 0n};
  for (const [id, cheque] of rows(view.cheques, 'cheques')) {
    if (!isRecord(cheque) || !['received', 'issued', 'deposited', 'endorsed', 'returned']
      .includes(cheque.status)) continue;
    if (!['receipt', 'payment'].includes(cheque.direction)) {
      throw Error('Invalid cheque direction: ' + id);
    }
    day(cheque.dueDate, id + ' cheque dueDate');
    const cash = amount(cheque.amount, id + ' cheque amount');
    cheques[cheque.direction].count++;
    cheques[cheque.direction].amount += cash;
    if (cheque.status === 'returned') {
      cheques.returnedCount++;
      cheques.returnedAmount += cash;
    }
  }
  return {
    currency: view.currency, referenceDate: options.referenceDate,
    scope: 'current-native-issued-documents',
    receivables: directionReport(summary.receipt, 'receivables'),
    payables: directionReport(summary.payment, 'payables'),
    counterparties: [...byParty.values()].filter(person =>
      person.receivable !== 0n || person.payable !== 0n).map(person => ({
      partyId: person.partyId, name: person.name,
      receivable: toNumber(person.receivable, 'party receivable'),
      payable: toNumber(person.payable, 'party payable'),
      netReceivable: toNumber(person.receivable - person.payable, 'party net'),
    })).sort((a, b) => b.receivable + b.payable - a.receivable - a.payable),
    documents,
    closedFiscalPeriods: fiscal.map(row => ({
      periodId: row.periodId, startDate: row.startDate, throughDate: row.throughDate,
      currentReceivable: toNumber(row.receivable, 'closed-period receivable'),
      currentPayable: toNumber(row.payable, 'closed-period payable'),
    })),
    outsideClosedPeriods: {
      currentReceivable: toNumber(openPeriod.receivable, 'open-period receivable'),
      currentPayable: toNumber(openPeriod.payable, 'open-period payable'),
    },
    chequeCommitments: {
      receivableCount: cheques.receipt.count,
      receivableAmount: toNumber(cheques.receipt.amount, 'receivable cheques'),
      payableCount: cheques.payment.count,
      payableAmount: toNumber(cheques.payment.amount, 'payable cheques'),
      returnedCount: cheques.returnedCount,
      returnedAmount: toNumber(cheques.returnedAmount, 'returned cheques'),
    },
    warnings: [
      'Amounts are current unpaid native invoices/bills, not balances at the reference date.',
      'Ageing uses document dueDate; missing due dates remain unknown rather than inferred.',
      'Closed-period grouping uses original posting dates but current remaining amounts.',
      'Operational uncleared cheques do not settle or reduce outstanding documents.',
      'Imported Parsian historical counterparty balances are excluded.',
      'Active instalment schedules and their instalment-level due dates are not represented.',
    ],
  };
}
