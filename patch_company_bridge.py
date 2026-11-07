from pathlib import Path
import os
p=Path(os.environ['LOCALAPPDATA'])/'MadarDesk-Private'/'Parsian-Migration-20261107'/'personal-app-build'
b=p/'personal_parsian_bridge.py'
s=b.read_text('utf-8')
block=r'''

def _source_rows(year, table):
    """Read validated typed source rows, preserving provenance and excluding secrets."""
    root=private_root()
    if year not in ("1404","1405") or table not in ("tbl_CoSpec","tbl_Company","tbl_Tafsili","tbl_Telephone"):
        raise PersonalHistoryError("Invalid personal source selector")
    db=safe_file(root,"archive/parsian-"+year+".sqlite3")
    conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        records=conn.execute(
            "SELECT ordinal,typed_raw_json,row_sha256 FROM archived_rows WHERE source_table=? ORDER BY ordinal",
            (table,)).fetchall()
    finally:
        conn.close()
    data=[]
    for ordinal,raw,digest in records:
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise PersonalHistoryError("Archive source record digest mismatch")
        fields=json.loads(raw)["fields"]
        decoded={}
        for key,item in fields.items():
            if item.get("t") in ("null","binary"):
                decoded[key]=None
            else:
                decoded[key]=item.get("value",item.get("text"))
        data.append(decoded)
    return data

def read_personal_company():
    """The legacy company label is opaque, never invent or expose an inferred legal name."""
    results=[]
    for year in ("1404","1405"):
        company=_source_rows(year,"tbl_Company")
        spec=_source_rows(year,"tbl_CoSpec")
        if len(company)!=1 or len(spec)!=1:
            raise PersonalHistoryError("Incomplete source company record")
        c=company[0]
        raw_name=str(c.get("CName") or "")
        plausible_name=bool(raw_name and (any('\u0600'<=ch<='\u06ff' for ch in raw_name)
                                  or (' ' in raw_name and len(raw_name)>4)))
        if raw_name and not plausible_name:
            name=None
            state="OBFUSCATED_UNREADABLE"
        else:
            name=raw_name or None
            state="VERIFIED_PLAINTEXT" if name else "NOT_PRESENT"
        ss=spec[0]
        results.append({
            "year":year,"legalName":name,"legalNameState":state,
            "economicCode":str(ss.get("ECOcode") or ""),
            "postalCode":str(ss.get("PostalCode") or ""),
            "sourceRegistrationCode":str(ss.get("Code") or ""),
            "address":str(ss.get("Address") or ""),
            "phone":str(ss.get("Tel") or ""),
            "province":str(ss.get("Estate") or ""),
            "city":str(ss.get("City") or ""),
            "mobile":str(ss.get("Mobile") or ""),
            "sourceTables":["tbl_CoSpec","tbl_Company"],
        })
    fields=("economicCode","postalCode","sourceRegistrationCode",
            "address","phone","province","city","mobile")
    stable={k:results[0][k]==results[1][k] for k in fields}
    return {"latest":results[1],"prior":results[0],
            "unchangedAcrossYears":stable,
            "verifiedFromSource":True,
            "postingToNativeCompanyProfile":False,
            "note":"Native legalName cannot be fabricated; original CName is encoded."}
'''
assert 'def read_personal_company(' not in s
s+='\n'+block
b.write_text(s,'utf-8')
a=p/'native_app.py'
s=a.read_text('utf-8')
anchor="    def standaloneAccountingParsianArchiveIndex(self):"
assert s.count(anchor)==1
s=s.replace(anchor,"""    def standaloneAccountingParsianCompany(self):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import read_personal_company
            return read_personal_company()

"""+anchor)
old="'standaloneAccountingParsianHistory'"
assert s.count(old)>=3
s=s.replace(old,old+",'standaloneAccountingParsianCompany'")
a.write_text(s,'utf-8')
print('PERSONAL_COMPANY_SOURCE_BRIDGE_ADDED',s.count("'standaloneAccountingParsianCompany'"))
