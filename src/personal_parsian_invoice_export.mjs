/** Read-only, standalone printable reconstruction. Never posts a financial event. */
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,character=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[character]));
const number=value=>{
  const n=Number(value);
  return Number.isFinite(n)?n.toLocaleString('fa-IR',{maximumFractionDigits:3}):escapeHtml(value);
};
export function legacyInvoiceFilename(invoice){
  const year=String(invoice?.year||'unknown').replace(/[^0-9]/g,'').slice(0,4);
  const key=String(invoice?.key||'unknown').replace(/[^a-zA-Z0-9_.-]/g,'-').slice(0,90);
  return 'madar-parsian-history-'+year+'-'+key+'.html';
}
export function buildParsianLegacyInvoiceHtml(invoice,sourceLines){
  if(!invoice||typeof invoice!=='object'||!Array.isArray(sourceLines)||!invoice.key){
    throw Error('Invalid archived invoice');
  }
  const lines=sourceLines.filter(line=>line?.invoice_key===invoice.key);
  const cells=lines.map((line,index)=>`<tr><td>${index+1}</td>
    <td>${escapeHtml(line.good_name)}</td><td dir="ltr">${escapeHtml(line.good_code)}</td>
    <td>${number(line.quantity)}</td><td>${escapeHtml(line.unit)}</td>
    <td>${number(line.unit_price_rial)}</td><td>${number(line.discount_rial)}</td>
    <td>${number(line.line_net_rial)}</td></tr>`).join('');
  const status=invoice.status==='matched'?'\u062a\u0637\u0628\u06cc\u0642 \u0645\u0627\u0644\u06cc \u0628\u0627 \u062f\u0641\u062a\u0631 \u06a9\u0644':
    invoice.status==='inventory_only'?'\u0639\u0645\u0644\u06cc\u0627\u062a \u0627\u0646\u0628\u0627\u0631 \u0628\u062f\u0648\u0646 \u0633\u0646\u062f \u0645\u0627\u0644\u06cc':escapeHtml(invoice.status||'\u0646\u0627\u0645\u0634\u062e\u0635');
  const fields=[
    ['\u0633\u0627\u0644 \u0645\u0627\u0644\u06cc \u0645\u0646\u0628\u0639',invoice.year],['\u0634\u0645\u0627\u0631\u0647 \u0641\u0627\u06a9\u062a\u0648\u0631',invoice.number],['\u062a\u0627\u0631\u06cc\u062e \u0634\u0645\u0633\u06cc',invoice.date],
    ['\u0637\u0631\u0641 \u062d\u0633\u0627\u0628',invoice.party_name],['\u0634\u0646\u0627\u0633\u0647 \u06cc\u06a9\u062a\u0627\u06cc \u0645\u0646\u0628\u0639',invoice.key],
    ['\u0634\u0645\u0627\u0631\u0647 \u0633\u0646\u062f \u0645\u0631\u062a\u0628\u0637 \u062f\u0631 \u0645\u0646\u0628\u0639',invoice.source_sanad],['\u0627\u0631\u062c\u0627\u0639 \u062f\u0641\u062a\u0631 \u06a9\u0644',invoice.document_link],
    ['\u062a\u0637\u0628\u06cc\u0642 \u0633\u0646\u062f',status],['\u0648\u0636\u0639\u06cc\u062a \u062a\u0633\u0648\u06cc\u0647','\u0646\u0627\u0645\u0634\u062e\u0635\u061b \u0627\u0631\u062a\u0628\u0627\u0637 \u067e\u0631\u062f\u0627\u062e\u062a\u200c\u0647\u0627 \u0628\u0627 \u0627\u06cc\u0646 \u0641\u0627\u06a9\u062a\u0648\u0631 \u0627\u062b\u0628\u0627\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a']
  ];
  const fieldHtml=fields.map(([name,value])=>`<div class="field"><b>${name}</b><span>${escapeHtml(value)}</span></div>`).join('');
  return `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>\u0631\u0648\u0646\u0648\u0634\u062a \u0642\u0627\u0628\u0644 \u0686\u0627\u067e \u0641\u0627\u06a9\u062a\u0648\u0631 \u062a\u0627\u0631\u06cc\u062e\u06cc \u067e\u0627\u0631\u0633\u06cc\u0627\u0646</title>
  <style>body{font:14px Tahoma,Arial,sans-serif;direction:rtl;color:#172e31;margin:28px;line-height:1.8}
  h1{font-size:23px} .note{background:#fff4dc;border:1px solid #ead29b;padding:12px;margin:12px 0}
  .fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .field{border:1px solid #cddbd7;padding:8px;display:flex;flex-direction:column;overflow-wrap:anywhere}
  table{border-collapse:collapse;width:100%;margin-top:16px}td,th{border:1px solid #b9ccca;padding:8px;text-align:right}
  th{background:#e9f4f1}.total{margin-top:16px;font-weight:bold}
  @media print{button{display:none}body{margin:8mm}}@media(max-width:650px){.fields{grid-template-columns:1fr}}
  </style></head><body>
  <button type="button" onclick="window.print()">\u0686\u0627\u067e \u0627\u06cc\u0646 \u0628\u0631\u06af\u0647</button>
  <h1>\u0631\u0648\u0646\u0648\u0634\u062a \u0642\u0627\u0628\u0644 \u0686\u0627\u067e \u0641\u0627\u06a9\u062a\u0648\u0631 \u062a\u0627\u0631\u06cc\u062e\u06cc \u067e\u0627\u0631\u0633\u06cc\u0627\u0646</h1><p class="note">\u0627\u06cc\u0646 \u0628\u0631\u06af\u0647 \u0635\u0631\u0641\u0627\u064b \u0628\u0627\u0632\u0646\u0645\u0627\u06cc\u06cc \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u062b\u0628\u062a\u200c\u0634\u062f\u0647 \u062f\u0631 \u0645\u0646\u0628\u0639 \u0627\u0633\u062a\u061b \u0633\u0646\u062f \u0645\u0627\u0644\u06cc \u062c\u062f\u06cc\u062f\u060c \u0641\u0627\u06a9\u062a\u0648\u0631 \u0631\u0633\u0645\u06cc \u06cc\u0627 \u06af\u0648\u0627\u0647 \u062a\u0633\u0648\u06cc\u0647 \u0646\u06cc\u0633\u062a.</p>
  <p class="note">\u0646\u0627\u0645 \u062d\u0642\u0648\u0642\u06cc \u0635\u0627\u062f\u0631\u06a9\u0646\u0646\u062f\u0647 \u0627\u0632 \u0645\u0646\u0628\u0639 \u0642\u0627\u0628\u0644 \u062a\u0623\u06cc\u06cc\u062f \u0646\u06cc\u0633\u062a\u061b \u0628\u0646\u0627\u0628\u0631\u0627\u06cc\u0646 \u0639\u0645\u062f\u0627\u064b \u062f\u0631 \u0627\u06cc\u0646 \u0628\u0631\u06af\u0647 \u062f\u0631\u062c \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.</p><section class="fields">${fieldHtml}</section>
  <table><thead><tr><th>\u0631\u062f\u06cc\u0641</th><th>\u0634\u0631\u062d \u06a9\u0627\u0644\u0627 / \u062e\u062f\u0645\u062a</th><th>\u06a9\u062f \u06a9\u0627\u0644\u0627</th><th>\u062a\u0639\u062f\u0627\u062f</th>
  <th>\u0648\u0627\u062d\u062f</th><th>\u0642\u06cc\u0645\u062a \u0648\u0627\u062d\u062f (\u0631\u06cc\u0627\u0644)</th><th>\u062a\u062e\u0641\u06cc\u0641 (\u0631\u06cc\u0627\u0644)</th><th>\u062e\u0627\u0644\u0635 \u0631\u062f\u06cc\u0641 (\u0631\u06cc\u0627\u0644)</th></tr></thead>
  <tbody>${cells}</tbody></table><p class="total">\u062c\u0645\u0639 \u0631\u062f\u06cc\u0641\u200c\u0647\u0627\u06cc \u0645\u0646\u0628\u0639 (\u0631\u06cc\u0627\u0644): ${number(invoice.computed_rial)}</p>
  </body></html>`;
}
