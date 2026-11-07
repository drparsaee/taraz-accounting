const test = require('node:test');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');

const uri = pathToFileURL(path.join(__dirname, '..', 'src', 'taraz_financial_insights.js')).href;
const insights = import(uri).then(mod => mod.summarizeFinancialExposure);

const base = () => ({
  currency: 'RIAL',
  parties: {
    client: {name: 'Customer', receivable: 900, payable: 0},
    vendor: {name: 'Supplier', receivable: 0, payable: 400},
  },
  accounts: {'1200': {debitMinusCredit: 900}, '2000': {debitMinusCredit: -400}},
  invoices: {
    inv: {status: 'issued', partyId: 'client', postingDate: '2026-01-01',
      documentDate: '2026-01-01', dueDate: '2026-01-31',
      total: 1200, allocated: 200, returnedAmount: 100},
    draft: {status: 'draft', partyId: 'client', total: 999999},
  },
  bills: {
    bill: {status: 'issued', partyId: 'vendor', postingDate: '2026-03-01',
      dueDate: null, total: 400, allocated: 0},
  },
  cheques: {
    pending: {status: 'deposited', direction: 'receipt', dueDate: '2026-04-01', amount: 300},
    done: {status: 'cleared', direction: 'payment', dueDate: '2026-04-01', amount: 500},
    bounced: {status: 'returned', direction: 'payment', dueDate: '2026-04-01', amount: 200},
  },
  fiscalYears: [{periodId: 'FY-A', startDate: '2026-01-01', throughDate: '2026-02-28'}],
});

test('correct native balances, unknown maturity, fiscal placement and cheque commitments', async () => {
  const calculate = await insights;
  const view = base();
  const unchanged = structuredClone(view);
  const result = calculate(view, {referenceDate: '2026-03-17'});
  assert.deepEqual(view, unchanged, 'helper must not mutate the authorized view');
  assert.equal(result.currency, 'RIAL');
  assert.equal(result.scope, 'current-native-issued-documents');
  assert.equal(result.receivables.outstanding, 900);
  assert.equal(result.payables.outstanding, 400);
  assert.equal(result.receivables.ageing.days31to60, 900);
  assert.equal(result.payables.ageing.unknownDue, 400);
  assert.equal(result.documents.length, 2);
  assert.equal(result.documents.find(d => d.documentId === 'inv').daysOverdue, 45);
  assert.equal(result.closedFiscalPeriods[0].currentReceivable, 900);
  assert.equal(result.outsideClosedPeriods.currentPayable, 400);
  assert.equal(result.chequeCommitments.receivableAmount, 300);
  assert.equal(result.chequeCommitments.payableAmount, 200);
  assert.equal(result.chequeCommitments.returnedCount, 1);
  assert.equal(result.chequeCommitments.returnedAmount, 200);
  assert.equal(result.counterparties.find(p => p.partyId === 'client').netReceivable, 900);
});

test('day boundaries classify overdue exactly and due today stays not due', async () => {
  const calculate = await insights;
  const cases = [
    ['2026-01-31', 'notDue'], ['2026-02-01', 'days1to30'],
    ['2026-03-02', 'days1to30'], ['2026-03-03', 'days31to60'],
    ['2026-04-01', 'days31to60'], ['2026-04-02', 'days61to90'],
    ['2026-05-01', 'days61to90'], ['2026-05-02', 'daysOver90'],
  ];
  for (const [referenceDate, expected] of cases) {
    const view = base();
    const result = calculate(view, {referenceDate});
    assert.equal(result.documents.find(d => d.documentId === 'inv').ageBucket,
      expected, referenceDate);
  }
});

test('reference date never rewinds payments and returns', async () => {
  const calculate = await insights;
  const result = calculate(base(), {referenceDate: '2026-01-02'});
  assert.equal(result.receivables.outstanding, 900);
  assert.equal(result.receivables.ageing.notDue, 900);
  assert.ok(result.warnings.some(w => w.includes('not balances at')));
});

test('rejects invalid ledger, unsafe floating amounts, over-allocation, and bad dates', async () => {
  const calculate = await insights;
  const invalid = [
    view => { view.invoices.inv.total = 100.2; },
    view => { view.invoices.inv.allocated = 1201; },
    view => { view.invoices.inv.allocated = '200'; },
    view => { view.parties.client.receivable = 123; },
    view => { view.accounts['1200'].debitMinusCredit = 123; },
    view => { view.invoices.inv.dueDate = '2026-02-30'; },
    view => { view.fiscalYears.push({periodId: 'other',
      startDate: '2026-02-01', throughDate: '2026-02-28'}); },
  ];
  for (const change of invalid) {
    const view = base();
    change(view);
    assert.throws(() => calculate(view, {referenceDate: '2026-03-17'}));
  }
  assert.throws(() => calculate(base(), {referenceDate: '۱۴۰۵/۰۱/۰۱'}));
});

test('does not return rounded totals when a sum exceeds Number.MAX_SAFE_INTEGER', async () => {
  const calculate = await insights;
  const max = Number.MAX_SAFE_INTEGER;
  const view = base();
  view.parties.client.receivable = max;
  view.accounts['1200'].debitMinusCredit = max;
  view.invoices.inv.total = max;
  view.invoices.inv.allocated = 0;
  view.invoices.inv.returnedAmount = 0;
  view.invoices.second = {...view.invoices.inv, total: 1,
    allocated: 0, returnedAmount: 0};
  // Each line is exact; their total is not representable as a JS number.
  assert.throws(() => calculate(view, {referenceDate: '2026-03-17'}), /exact JavaScript/);
});
