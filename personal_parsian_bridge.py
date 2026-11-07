"""Taraz-only verified read-only Parsian history; isolated from Madar task data.

Works exclusively on the current user's private %LOCALAPPDATA% migration folder.
This is NOT a financial event writer and never returns credentials/binary payloads.
"""
from pathlib import Path
import hashlib
import json
import os
import sqlite3

class PersonalHistoryError(ValueError):
    pass

def private_root():
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise PersonalHistoryError("No local private data root")
    path = Path(root) / "Taraz" / "Parsian-Migration-20261107"
    if not path.is_dir() or path.is_symlink():
        raise PersonalHistoryError("Private Parsian migration directory unavailable")
    return path

def safe_file(root, relative):
    path=root / relative
    if not path.is_file() or path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise PersonalHistoryError("Missing or unsafe private history file")
    return path

def _read_embedded(key):
    """Validated source snapshot stored INSIDE the native Madar accounting SQLite."""
    if key not in ("history","company","extended"):
        raise PersonalHistoryError("Unsupported embedded source")
    root=os.environ.get("APPDATA")
    if not root:
        return None
    db=Path(os.environ.get("TARAZ_DATA_DIR") or (Path(root)/"Taraz"))/"parsian-legacy-source.sqlite3"
    if not db.is_file() or db.is_symlink():
        return None
    conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        exists=conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parsian_legacy_data'").fetchone()
        if not exists:
            return None
        row=conn.execute("SELECT content_json,content_sha256 FROM parsian_legacy_data WHERE key=?",(key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    raw,stored=row
    encoded=raw.encode("utf-8")
    if len(encoded)>7_000_000 or hashlib.sha256(encoded).hexdigest()!=stored:
        raise PersonalHistoryError("Embedded Parsian source checksum failure")
    return json.loads(raw)


def read_verified_history():
    embedded=_read_embedded("history")
    if embedded is not None:
        summary=embedded.get("summary",{})
        if (summary.get("currency")!="RIAL" or
                summary.get("invoices")!=195 or
                summary.get("matchedInvoices")!=194 or
                summary.get("sourceFinancialJournalCount")!=386 or
                len(embedded.get("invoiceLines",[]))!=474 or
                len(embedded.get("invoices",[]))!=195 or
                len(embedded.get("parties",[]))!=84):
            raise PersonalHistoryError("Embedded Parsian history schema mismatch")
        return embedded
    root=private_root()
    report=json.loads(safe_file(root,"reports/parsian-historical-invoice-archive.json").read_text(encoding="utf-8"))
    path=safe_file(root,"viewer/parsian-history-index.json")
    raw=path.read_bytes()
    if len(raw)>8_000_000 or hashlib.sha256(raw).hexdigest().lower()!=str(report.get("normalizedIndexSha256","")).lower():
        raise PersonalHistoryError("Personal history checksum mismatch")
    obj=json.loads(raw.decode("utf-8"))
    summary=obj.get("summary",{})
    if summary.get("currency")!="RIAL" or summary.get("invoices")!=195 or summary.get("sourceFinancialJournalCount")!=386:
        raise PersonalHistoryError("Unexpected personal history provenance")
    if len(obj.get("invoiceLines",[]))!=474 or len(obj.get("invoices",[]))!=195:
        raise PersonalHistoryError("Missing historical invoice records")
    return obj

def list_archives():
    root=private_root()
    result=[]
    for year in ("1405","1404"):
        manifest=json.loads(safe_file(root,"archive/parsian-"+year+"-manifest.json").read_text(encoding="utf-8-sig"))
        db=safe_file(root,"archive/parsian-"+year+".sqlite3")
        conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                raise PersonalHistoryError("Corrupted Parsian archive")
            tables=sorted(({"name":str(name),"rows":int(count)} for name,count in manifest["tableCounts"].items()
                           if not any(term in name.lower() for term in
                           ("user","security","license","support","password","ini","setting","role","token"))),
                          key=lambda x:x["name"].lower())
            result.append({"year":year,"tableCount":manifest["vendorTableCount"],
                           "rowCount":manifest["vendorRowCount"],"tables":tables,
                           "currencyVerified":True})
        finally:conn.close()
    return result

def read_archive_rows(year, table, offset=0):
    if year not in ("1404","1405") or type(table) is not str or not table.startswith("tbl_") or len(table)>90:
        raise PersonalHistoryError("Invalid source archive selector")
    if any(term in table.lower() for term in
           ("user","security","license","support","password","ini","setting","role","token")):
        raise PermissionError("Security and credentials are not exposed in the archive UI")
    if type(offset) is not int or offset<0 or offset>150000:
        raise PersonalHistoryError("Invalid archive page")
    root=private_root()
    manifest=json.loads(safe_file(root,"archive/parsian-"+year+"-manifest.json").read_text(encoding="utf-8-sig"))
    if table not in manifest["tableCounts"]:
        raise PersonalHistoryError("Unknown source table")
    db=safe_file(root,"archive/parsian-"+year+".sqlite3")
    conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        source_rows=conn.execute(
            "select ordinal,typed_raw_json,row_sha256 from archived_rows where source_table=? order by ordinal limit 40 offset ?",
            (table,offset)).fetchall()
    finally:conn.close()
    rows=[]
    for ordinal,raw,digest in source_rows:
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise PersonalHistoryError("Source archive row integrity failed")
        obj=json.loads(raw)
        fields={}
        for key,val in obj.get("fields",{}).items():
            if any(term in key.lower() for term in ("password","hash","license","secret","token","salt")):
                fields[key]="(حذف از نمایش امنیتی)"
            elif val["t"]=="binary":fields[key]="(داده دودویی)"
            elif val["t"]=="null":fields[key]=""
            else:fields[key]=str(val.get("value",val.get("text","")))
        rows.append({"ordinal":ordinal,"fields":fields})
    return {"total":int(manifest["tableCounts"][table]),"rows":rows}



def _source_rows(year, table):
    """Read validated typed source rows, preserving provenance and excluding secrets."""
    root=private_root()
    permitted={"tbl_CoSpec","tbl_Company","tbl_Tafsili","tbl_Telephone",
      "tbl_Goods","tbl_GoodsGroup","tbl_Storehouse","tbl_FactorKind",
      "tbl_VATSetting","tbl_AccSetting","tbl_FactNum","tbl_TopCheck",
      "tbl_Moeen","tbl_Kol","tbl_WPersonel"}
    if year not in ("1404","1405") or table not in permitted:
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
    """The source company label is opaque. Do not substitute an assumed legal name."""
    embedded=_read_embedded("company")
    if embedded is not None:
        if not embedded.get("verifiedFromSource") or embedded.get("latest",{}).get("year")!="1405":
            raise PersonalHistoryError("Embedded company metadata invalid")
        return embedded
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

def read_personal_extended():
    obj=_read_embedded("extended")
    if obj is None:
        raise PersonalHistoryError("Native Parsian extended data has not been embedded")
    years=obj.get("sourceYears",{})
    if not (obj.get("sourceCurrency")=="RIAL" and
            len(years.get("1405",{}).get("tbl_Goods",[]))==95 and
            len(years.get("1405",{}).get("tbl_Tafsili",[]))==52):
        raise PersonalHistoryError("Embedded Parsian data has incomplete source coverage")
    return obj
