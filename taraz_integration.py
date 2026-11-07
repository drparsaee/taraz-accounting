"""Consent-based local Madar->Taraz metadata exchange.

Read-only until a user marks a request reviewed or rejected. This never
creates a journal, invoice, payable, party, payment, or receipt.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_BYTES = 32768

def _safe_record(file):
    if file.is_symlink() or file.stat().st_size > _MAX_BYTES:
        raise ValueError("Unsafe or oversized integration request")
    with file.open("rb") as fp:
        raw = fp.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("Oversized integration request")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict) or obj.get("schema") != 1 or obj.get("source") != "madar":
        raise ValueError("Unexpected integration source or schema")
    if not _ID.fullmatch(str(obj.get("id",""))) or file.stem != obj["id"]:
        raise ValueError("Invalid request identifier")
    for key, limit in (("taskId",180),("projectId",180),("title",300)):
        value = obj.get(key)
        if not isinstance(value,str) or not value.strip() or len(value) > limit:
            raise ValueError("Invalid request "+key)
    if obj.get("expenseId") is not None and (
        not isinstance(obj["expenseId"],str) or len(obj["expenseId"])>180
    ):
        raise ValueError("Invalid expense identifier")
    amount=obj.get("amountRial")
    if amount is not None:
        # Task app serializes exact RIAL amounts as decimal strings.
        if (type(amount) is str and 1 <= len(amount) <= 16 and amount.isascii()
                and amount.isdigit()):
            amount=int(amount)
        if type(amount) is not int or not 0 <= amount <= 9007199254740991:
            raise ValueError("Invalid optional amount")
    created = obj.get("createdUtc")
    if not isinstance(created,str) or len(created)>40 or "T" not in created:
        raise ValueError("Invalid creation timestamp")
    result={k:obj.get(k) for k in ("id","schema","source","taskId",
        "expenseId","title","projectId","createdUtc")}
    result["amountRial"]=amount
    return result

def list_requests(root:Path):
    pending = root / "pending"
    if not pending.is_dir():
        return {"connected":False,"requests":[],"invalidCount":0}
    if pending.is_symlink():
        raise PermissionError("Bridge directory cannot be a symlink")
    proposals=[]; invalid=0
    for f in sorted(pending.glob("*.json"))[:201]:
        try:
            if len(proposals)>=100:break
            proposals.append(_safe_record(f))
        except (ValueError,OSError,KeyError,TypeError,UnicodeError,PermissionError):
            invalid+=1
    proposals.sort(key=lambda p:p["createdUtc"], reverse=True)
    return {"connected":True,"requests":proposals,"invalidCount":invalid}

def review_request(root:Path, request_id:str, decision:str):
    if not isinstance(request_id,str) or not _ID.fullmatch(request_id):
        raise ValueError("Invalid request ID")
    if decision not in ("reviewed","rejected"):
        raise ValueError("Unknown integration decision")
    pending = root / "pending"
    reviewed = root / "reviewed"
    if not pending.is_dir() or pending.is_symlink():
        raise FileNotFoundError("Madar integration inbox unavailable")
    src = pending / (request_id + ".json")
    if not src.is_file() or src.is_symlink():
        raise FileNotFoundError("Request already processed or not found")
    source = _safe_record(src)
    reviewed.mkdir(exist_ok=True,parents=True)
    if reviewed.is_symlink():
        raise PermissionError("Unsafe reviewed directory")
    dest = reviewed / src.name
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Already reviewed")
    # Explicit user action, only moves the metadata exchange file.
    os.rename(src, dest)
    receipt = {
        "schema":1, "id":request_id,"source":"taraz",
        "state":decision,"reviewedUtc":datetime.now(timezone.utc).isoformat(),
        "taskId":source["taskId"],"financialEventCreated":False
    }
    marker=reviewed / (request_id + ".review.json")
    with marker.open("x",encoding="utf-8") as fp:
        json.dump(receipt,fp,ensure_ascii=False,indent=2)
    return {"id":request_id,"state":decision,"financialEventCreated":False}
