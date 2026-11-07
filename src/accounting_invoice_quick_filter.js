/** Presentation-only invoice filtering; never changes financial records. */
export function filterInvoiceRows(records, parties, search = '', status = 'all') {
  const query = String(search ?? '').trim().toLocaleLowerCase('fa-IR')
    .replace(/[ي]/g, 'ی').replace(/[ك]/g, 'ک');
  const result = Object.values(records || {}).filter(invoice => {
    if (!invoice || typeof invoice !== 'object') return false;
    if (status !== 'all' && invoice.status !== status) return false;
    if (!query) return true;
    const values = [invoice.id, invoice.number, invoice.documentDate,
      parties?.[invoice.partyId]?.name, invoice.partyId];
    return values.some(value => String(value ?? '').toLocaleLowerCase('fa-IR')
      .replace(/[ي]/g, 'ی').replace(/[ك]/g, 'ک').includes(query));
  });
  return result.sort((a, b) => String(b.documentDate ?? '').localeCompare(
    String(a.documentDate ?? '')) || String(b.id).localeCompare(String(a.id)));
}

export function invoiceStatusCounts(records) {
  const result = { all: 0, draft: 0, approved: 0, issued: 0 };
  for (const invoice of Object.values(records || {})) {
    if (!invoice || typeof invoice !== 'object') continue;
    result.all++;
    if (Object.hasOwn(result, invoice.status)) result[invoice.status]++;
  }
  return result;
}
