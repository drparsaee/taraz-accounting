"""Experimental, same-user Drive-folder peer journal for LAN outages.

The selected Drive for desktop folder is a transport, never an authorization
server. A peer must possess an independently paired high-entropy secret.
Records are authenticated, immutable and scoped to one LAN user/revision.
Conflicting edits remain visible as conflicts, not silently overwritten.
This journal is intentionally NOT a substitute for host-side ACL rechecks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets

from offline_exchange import atomic_json

_IDENTITY = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_FILE = re.compile(r"[0-9a-f]{20,64}\.json\Z")
_MAX_EVENT = 1_500_000


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def _safe_task(item):
    if item is None:
        return None
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("projectId"), str):
        raise ValueError("Invalid cloud task record")
    if "fileLinks" in item:
        raise ValueError("SMB references cannot enter the cloud journal")
    return deepcopy(item)


def without_smb(task):
    clean = deepcopy(task)
    clean.pop("fileLinks", None)
    return clean


class CloudConflict(RuntimeError):
    pass


class PeerJournal:
    """Append/replay changes from peers with the *same* account and LAN base.

    The caller must enforce the permissions and validate the final model.
    The configured secret must be paired out of band between trusted devices;
    it is never written to the synchronized folder.
    """
    def __init__(self, sync_folder, host_id, username, base_revision, secret, allowed_projects,
                 device_id):
        for field in (host_id, username, base_revision, device_id):
            if not isinstance(field, str) or not _IDENTITY.fullmatch(field):
                raise ValueError("Invalid peer identity")
        if not isinstance(secret, str) or len(secret) < 24:
            raise ValueError("A strong, paired peer code is required")
        if not isinstance(allowed_projects, (list, set, tuple)) or not allowed_projects:
            raise ValueError("Explicit project scope is required for peer exchange")
        if not all(isinstance(p, str) and _IDENTITY.fullmatch(p) for p in allowed_projects):
            raise ValueError("Invalid peer project scope")
        root = Path(sync_folder)
        if not root.is_dir() or root.is_symlink():
            raise FileNotFoundError("Cloud sync folder is unavailable")
        self.username = username
        self.host_id = host_id
        self.base_revision = base_revision
        self.device_id = device_id
        self.projects = frozenset(allowed_projects)
        context = f"{host_id}|{username}|{base_revision}"
        scope = hashlib.sha256(context.encode("utf8")).hexdigest()[:32]
        self.folder = root / "Madar-Desk-Peer-Events" / scope
        self.folder.mkdir(parents=True, exist_ok=True)
        self.key = hashlib.pbkdf2_hmac("sha256", secret.encode("utf8"),
                                     ("MadarDeskPeerV1|" + context).encode("utf8"),
                                     200_000)

    def _verify(self, record):
        if not isinstance(record, dict) or set(record) != {"body", "mac"}:
            raise ValueError("Invalid peer envelope")
        body = record["body"]
        mac = record["mac"]
        if not isinstance(mac, str) or not hmac.compare_digest(
                hmac.new(self.key, _json_bytes(body), hashlib.sha256).hexdigest(), mac):
            raise PermissionError("Unauthenticated cloud peer event")
        if (not isinstance(body, dict) or
                set(body) != {"schema", "host", "user", "revision", "device", "eventId",
                              "clock", "at", "changes"} or
                body["schema"] != 1 or body["host"] != self.host_id or
                body["user"] != self.username or body["revision"] != self.base_revision or
                not isinstance(body["clock"], int) or body["clock"] < 1 or
                not isinstance(body["changes"], list) or len(body["changes"]) > 500):
            raise ValueError("Invalid peer event body")
        if any(not isinstance(body[field], str) or not _IDENTITY.fullmatch(body[field])
               for field in ("device", "eventId")):
            raise ValueError("Invalid peer device or event")
        if not isinstance(body["at"], str) or len(body["at"]) > 40:
            raise ValueError("Invalid event timestamp")
        seen = set()
        for edit in body["changes"]:
            if not isinstance(edit, dict) or set(edit) != {"id", "before", "after"}:
                raise ValueError("Invalid peer task change")
            identifier = edit["id"]
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError("Duplicate or invalid peer task")
            seen.add(identifier)
            previous = _safe_task(edit["before"])
            updated = _safe_task(edit["after"])
            if previous is None and updated is None:
                raise ValueError("No-op peer task change")
            if any(task is not None and
                   (task["id"] != identifier or task["projectId"] not in self.projects)
                   for task in (previous, updated)):
                raise PermissionError("Cloud task is outside the paired project scope")
            if previous is not None and updated is not None and previous["projectId"] != updated["projectId"]:
                raise PermissionError("Cloud cannot move tasks across projects")
        return body

    def events(self):
        """Return authenticated event sequence; fail closed on corrupt files."""
        result = []
        for path in self.folder.glob("*.json"):
            if path.is_symlink() or not _FILE.fullmatch(path.name) or path.stat().st_size > _MAX_EVENT:
                raise ValueError("Unexpected cloud event file")
            raw = path.read_bytes()
            record = json.loads(raw.decode("utf8"))
            body = self._verify(record)
            if path.stem != hashlib.sha256(_json_bytes(record)).hexdigest():
                raise ValueError("Cloud event file hash mismatch")
            result.append(body)
        if len(result) > 5000:
            raise ValueError("Peer journal needs host reconciliation")
        result.sort(key=lambda b: (b["clock"], b["device"], b["eventId"]))
        return result

    def replay(self, base):
        """Return (merged_state, conflicts, latest_clock).

        Each entire event applies atomically. A collision leaves the event
        unapplied and explicitly reported, while other records remain safe.
        """
        state = deepcopy(base)
        indexed = {t["id"]: without_smb(t) for t in state["tasks"]}
        local_links = {t["id"]: deepcopy(t.get("fileLinks", [])) for t in state["tasks"]}
        conflicts = []
        clock = 0
        for event in self.events():
            clock = max(clock, event["clock"])
            collided = [edit["id"] for edit in event["changes"]
                        if indexed.get(edit["id"]) != edit["before"]
                        and indexed.get(edit["id"]) != edit["after"]]
            if collided:
                conflicts.append({"eventId": event["eventId"], "device": event["device"],
                                  "taskIds": collided})
                continue
            for edit in event["changes"]:
                if edit["after"] is None:
                    indexed.pop(edit["id"], None)
                    local_links.pop(edit["id"], None)
                else:
                    indexed[edit["id"]] = deepcopy(edit["after"])
        state["tasks"] = [{**task, "fileLinks": local_links.get(task_id, [])}
                          for task_id, task in indexed.items()]
        return state, conflicts, clock

    def append(self, before, after, *, anchor):
        """Durably publish locally edited card changes, then re-read peers.

        Never publishes structure or SMB links. Callers must reject attempts
        to edit cloud snapshots with stale revision or unapproved role.
        """
        b = {t["id"]: without_smb(t) for t in before["tasks"]}
        a = {t["id"]: without_smb(t) for t in after["tasks"]}
        for key in ("projects", "boards", "workspaces", "stages", "settings", "templates"):
            if before.get(key) != after.get(key):
                raise PermissionError("Peer exchange cannot change shared structure")
        changes = [{"id": i, "before": b.get(i), "after": a.get(i)}
                   for i in sorted(set(b) | set(a)) if b.get(i) != a.get(i)]
        if not changes:
            return None
        if len(changes) > 500:
            raise ValueError("Too many peer changes at once")
        for edit in changes:
            for item in (edit["before"], edit["after"]):
                if item is not None and item["projectId"] not in self.projects:
                    raise PermissionError("Cloud edit outside account project scope")
        head, conflicts, clock = self.replay(anchor)
        if conflicts:
            raise CloudConflict("CONFLICT: unresolved cloud peer edits")
        head_index = {t["id"]: without_smb(t) for t in head["tasks"]}
        stale = [edit["id"] for edit in changes
                 if head_index.get(edit["id"]) != edit["before"]]
        if stale:
            raise CloudConflict("CONFLICT: cloud peer has already edited: " + ", ".join(stale[:12]))
        body = {"schema": 1, "host": self.host_id, "user": self.username,
                "revision": self.base_revision, "device": self.device_id,
                "eventId": secrets.token_hex(16), "clock": clock + 1,
                "at": datetime.now(timezone.utc).isoformat(), "changes": changes}
        record = {"body": body, "mac": hmac.new(self.key, _json_bytes(body),
                                                 hashlib.sha256).hexdigest()}
        packed = _json_bytes(record)
        if len(packed) > _MAX_EVENT:
            raise ValueError("Cloud event too large")
        name = hashlib.sha256(packed).hexdigest() + ".json"
        path = self.folder / name
        if path.exists():
            raise FileExistsError("Duplicate cloud event")
        atomic_json(path, record)
        return {"name": name, "clock": clock + 1, "changes": len(changes)}
