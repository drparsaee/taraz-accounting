from pathlib import Path
import os
p=Path(os.environ['LOCALAPPDATA'])/'MadarDesk-Private'/'Parsian-Migration-20261107'/'personal-app-build'/'src'/'personal_parsian_invoices.jsx'
s=p.read_text('utf-8')
assert s.count("useState('all')")==2
s=s.replace("const [year,setYear]=useState('all');","const [year,setYear]=useState(section==='parties'?'1405':'all');")
anchor="  const [selected,setSelected]=useState('');"
assert s.count(anchor)==1
s=s.replace(anchor,anchor+"""
  const [rawContacts,setRawContacts]=useState([]);
  useEffect(()=>{
    if(section!=='parties'||typeof api?.standaloneAccountingParsianArchiveRows!=='function')return;
    let alive=true;
    Promise.all(['1404','1405'].map(year=>
      api.standaloneAccountingParsianArchiveRows(year,'tbl_Telephone',0)
        .then(res=>({year,rows:res?.rows||[]}))))
      .then(data=>{if(alive)setRawContacts(data.flatMap(x=>
        x.rows.map(r=>({...r.fields,sourceYear:x.year,sourceOrdinal:r.ordinal}))))})
      .catch(()=>{if(alive)setRawContacts([])});
    return()=>{alive=false};
  },[api,section]);""")
anchor="  const factorList=useMemo(()=>{"
assert s.count(anchor)==1
block="""  const sourceJournalByParty=useMemo(()=>{
    const map=new Map();
    for(const line of source?.journalLines||[]){
      const account=String(line.account_id||'');
      if(!account.startsWith('ps.parsian.account.t.12.2.'))continue;
      const code=account.replace('ps.parsian.account.t.','');
      const key=line.year+':'+code;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(line);
    }
    return map;
  },[source]);
  const sourceInvoicesByParty=useMemo(()=>{
    const map=new Map();
    for(const invoice of source?.invoices||[]){
      const key=invoice.year+':'+invoice.party_key;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(invoice);
    }
    return map;
  },[source]);
  const fullContacts=useMemo(()=>{
    const map=new Map();
    for(const c of rawContacts){
      const code=[c.KolCode,c.MoeenCode,c.TafsiliCode].map(String).join('.');
      const key=c.sourceYear+':'+code;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(c);
    }
    return map;
  },[rawContacts]);
"""
s=s.replace(anchor,block+anchor)
s=s.replace("""      ].some(item=>String(item||'').toLocaleLowerCase('fa-IR').includes(value))));
  },[source,term,year,contactsByParty]);""","""      ].some(item=>String(item||'').toLocaleLowerCase('fa-IR').includes(value))))
      .sort((a,b)=>Math.abs(Number(b.balance_signed_rial||0))-
        Math.abs(Number(a.balance_signed_rial||0)));
  },[source,term,year,contactsByParty]);""")
# make source person link and financial status visible.
s=s.replace("""<td dir="ltr" className="ppi-amount">{financial(item.balance_signed_rial)}</td>""","""<td dir="ltr" className="ppi-amount">{financial(item.balance_signed_rial)} <span className="ppi-balance-side">{item.balance_signed_rial>0?'بدهکار':item.balance_signed_rial<0?'بستانکار':'مانده صفر'}</span></td>""")
s=s.replace("""{open?'بستن':'تماس و اطلاعات'}""","""{open?'بستن':'ریزگردش، فاکتور و تماس'}""")
anchor="""                  </div>
                </div>:<div>"""
assert s.count(anchor)==1
block="""                  </div>
                  {(()=>{
                    const key=item.year+':'+item.code;
                    const rows=sourceJournalByParty.get(key)||[];
                    const factors=sourceInvoicesByParty.get(key)||[];
                    const debit=rows.reduce((a,r)=>a+Number(r.debit_rial||0),0);
                    const credit=rows.reduce((a,r)=>a+Number(r.credit_rial||0),0);
                    return <div className="ppi-history">
                      <h4>ریزگردش دفتر کل در سال {item.year}</h4>
                      <p><strong>{financial(rows.length)}</strong> ردیف سند؛ بدهکار <strong>{financial(debit)}</strong> ریال؛ بستانکار <strong>{financial(credit)}</strong> ریال</p>
                      <p>خالص ریزگردش: <strong>{financial(debit-credit)}</strong> ریال؛ مانده منبع: <strong>{financial(item.balance_signed_rial)}</strong> ریال</p>
                      {rows.length>0&&<div className="ppi-ledger-scroll"><table className="ppi-table ppi-subtable"><thead><tr>
                        <th>تاریخ شمسی</th><th>شماره سند</th><th>بدهکار</th><th>بستانکار</th><th>شرح ثبت‌شده</th>
                      </tr></thead><tbody>{rows.slice(0,60).map((r,i)=><tr key={item.year+':'+r.number+':'+r.source_row_id+':'+i}>
                        <td dir="ltr">{r.date}</td><td>{r.number}</td>
                        <td dir="ltr">{financial(r.debit_rial)}</td><td dir="ltr">{financial(r.credit_rial)}</td><td>{r.note||'بدون شرح'}</td>
                      </tr>)}</tbody></table></div>}
                      {rows.length>60&&<p>۶۰ ردیف اول نمایش داده شد؛ کل اسناد در بخش دفتر کل محفوظ‌اند.</p>}
                      <h4>فاکتورهای مربوط به این شخص در همین سال: {financial(factors.length)}</h4>
                      {factors.length>0&&<div className="ppi-ledger-scroll"><table className="ppi-table ppi-subtable"><thead><tr>
                        <th>شماره</th><th>تاریخ شمسی</th><th>مبلغ</th><th>سند مرتبط</th>
                      </tr></thead><tbody>{factors.slice(0,40).map(f=><tr key={f.key}>
                        <td>{f.number}</td><td>{f.date}</td><td dir="ltr">{financial(f.computed_rial)}</td><td dir="ltr">{f.source_sanad}</td>
                      </tr>)}</tbody></table></div>}
                      {factors.length>40&&<p>۴۰ فاکتور اول نمایش داده شد؛ تمامی فاکتورها در بخش فاکتور فروش هستند.</p>}
                      {fullContacts.get(key)?.map((c,i)=><div className="ppi-mini" key={key+':contact:'+i}>
                        <strong>اطلاعات تماس تکمیلی از منبع:</strong>
                        {[
                          ['کد ملی',c.CodeNat],['کد اقتصادی',c.CodeEco],['کد پستی',c.CodePost],
                          ['ایمیل',c.Email],['موبایل دوم',c.Mobile1],['موبایل سوم',c.Mobile2],
                          ['تلفن دیگر',c.Tel1],['نشانی دوم',c.Address1],['توضیحات',c.Other]
                        ].filter(x=>x[1]&&x[1]!=='None').map(([label,value])=>
                          <span className="ppi-detail-contact" key={label}><b>{label}:</b> {value}</span>)}
                      </div>)}
                      <p className="ppi-subtle">مانده تاریخی صرفاً خالص حساب تفصیلی است و تسویه تک‌تک فاکتورها از آن استنباط نشده است.</p>
                    </div>;
                  })()}
                </div>:<div>"""
s=s.replace(anchor,block)
p.write_text(s,'utf-8')
print('PERSON_DETAIL_FINANCIAL_HISTORY_CONNECTED')
