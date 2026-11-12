"""Fail-closed OFFLINE E2 epoch evidence preparation, NOT epoch activation.

The existing TarazPeerRegistry checks query IDs only in its own 10k-row
SQLite table. It has no prior-epoch replay index, atomic cutover journal, or
epoch-aware wire/HMAC verification. A new empty registry is therefore UNSAFE.

This host-only preparation exports and verifies ALL existing replay bindings
and audit evidence into a create-only archive plus a create-only receipt.
Neither function here modifies the live registry or authorizes a new epoch.
The activation gate is deliberately denied until an independently reviewed
runtime path verifies every prior epoch before admitting a new query ID.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry


_APPROVAL_DOMAIN = b"taraz.mtr.epoch.prepare.v1\x00"
_HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
_HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR_ROLES = frozenset(("admin", "editor", "finance_submitter"))
_MAX_QUERIES = 10000


class EpochRolloverBlocked(PermissionError):
    """No authenticated, replay-preserving, epoch-aware activation path."""


class EpochEvidenceInvalid(ValueError):
    """Offline archive or signing intent is not trustworthy enough to stage."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_private_target(path: Path, *, suffix: str) -> None:
    if (not isinstance(path, Path) or not path.is_absolute() or
            path.suffix != suffix or path.is_symlink() or
            getattr(path, "is_junction", lambda: False)()):
        raise EpochEvidenceInvalid("trusted absolute private evidence path required")
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise EpochEvidenceInvalid("unsafe private evidence directory")
        try:
            info = parent.lstat()
        except OSError as exc:
            raise EpochEvidenceInvalid("private evidence directory missing") from exc
        if (not stat.S_ISDIR(info.st_mode) or
                getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise EpochEvidenceInvalid("private evidence directory alias")
    if path.exists():
        raise FileExistsError("offline evidence destination already exists")


def _validate_config(
    registry: TarazPeerRegistry, host_config: PeerConfig,
    proposed_config: PeerConfig,
) -> None:
    if type(registry) is not TarazPeerRegistry:
        raise EpochRolloverBlocked("real trusted TarazPeerRegistry required")
    if type(host_config) is not PeerConfig or host_config is not registry.config:
        raise EpochRolloverBlocked("exact live host-owned config object required")
    if type(proposed_config) is not PeerConfig:
        raise EpochRolloverBlocked("trusted next-epoch PeerConfig required")
    if (host_config.organization_id != proposed_config.organization_id or
            host_config.madar_sender_id != proposed_config.madar_sender_id or
            host_config.taraz_sender_id != proposed_config.taraz_sender_id):
        raise EpochRolloverBlocked("next epoch cannot change org or sender identity")
    if (host_config.madar_key_id == proposed_config.madar_key_id or
            host_config.taraz_key_id == proposed_config.taraz_key_id):
        raise EpochRolloverBlocked("next epoch needs distinct directional key IDs")
    secrets = (
        host_config.madar_secret, host_config.taraz_secret,
        proposed_config.madar_secret, proposed_config.taraz_secret,
    )
    if any(hmac.compare_digest(a, b) for i, a in enumerate(secrets)
           for b in secrets[i + 1:]):
        raise EpochRolloverBlocked("next epoch must rotate both directional secrets")


def _approval_payload(
    registry: TarazPeerRegistry, proposed_config: PeerConfig,
    archive_path: Path, receipt_path: Path,
) -> bytes:
    current = registry.config
    intent = {
        "purpose": "offline-evidence-only-NOT-activation",
        "source": str(registry.path),
        "archive": str(archive_path),
        "receipt": str(receipt_path),
        "org": current.organization_id,
        "madarSender": current.madar_sender_id,
        "tarazSender": current.taraz_sender_id,
        "oldMadarKey": current.madar_key_id,
        "oldTarazKey": current.taraz_key_id,
        "nextMadarKey": proposed_config.madar_key_id,
        "nextTarazKey": proposed_config.taraz_key_id,
        # Bind independently provisioned future secret values without ever
        # serializing or echoing their raw material in the archival receipt.
        "nextSecretsSha256": [
            hashlib.sha256(proposed_config.madar_secret).hexdigest(),
            hashlib.sha256(proposed_config.taraz_secret).hexdigest(),
        ],
    }
    return _APPROVAL_DOMAIN + json.dumps(
        intent, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
    ).encode("utf-8")


def verify_host_offline_approval(
    registry: TarazPeerRegistry, *, host_config: PeerConfig,
    proposed_config: PeerConfig, archive_path: Path,
    receipt_path: Path, approval_mac: bytes,
) -> None:
    """Authenticate a domain-separated staging intent using the existing host key.

    This is NOT user/admin authorization. The caller must independently secure
    the host's private config, old Taraz-direction key and offline execution.
    """
    _validate_config(registry, host_config, proposed_config)
    if type(approval_mac) is not bytes or len(approval_mac) != 32:
        raise EpochRolloverBlocked("trusted 32-byte offline host approval required")
    digest = hmac.new(
        host_config.taraz_secret,
        _approval_payload(registry, proposed_config, archive_path, receipt_path),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(digest, approval_mac):
        raise EpochRolloverBlocked("offline host approval MAC mismatch")


def _verify_archive(
    archive_path: Path, *, host_config: PeerConfig,
    expected_sha256: str, expected_counts: dict,
) -> dict:
    """Verify every archived query binding, source evidence and exact SHA."""
    if (archive_path.is_symlink() or not archive_path.is_file() or
            getattr(archive_path, "is_junction", lambda: False)()):
        raise EpochEvidenceInvalid("offline archive alias or missing")
    info = archive_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise EpochEvidenceInvalid("offline archive must be an unlinked private file")
    if _file_sha256(archive_path) != expected_sha256:
        raise EpochEvidenceInvalid("archived evidence SHA-256 mismatch")
    try:
        with closing(sqlite3.connect(
            f"{archive_path.as_uri()}?mode=ro", uri=True, timeout=2,
        )) as connection:
            connection.execute("PRAGMA query_only=ON")
            if (connection.execute("PRAGMA user_version").fetchone()[0] != 1
                    or connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok"):
                raise EpochEvidenceInvalid("archive integrity/schema mismatch")
            counts = {
                name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("requests", "queries", "audit")
            }
            if (counts["queries"] > _MAX_QUERIES or
                    counts != {
                        "requests": expected_counts["requests"],
                        "queries": expected_counts["queries"],
                        "audit": expected_counts["auditEvents"],
                    }):
                raise EpochEvidenceInvalid("archived evidence counts mismatch")
            for table in ("requests", "queries", "audit"):
                for operation in ("update", "delete"):
                    if connection.execute(
                        "SELECT type FROM sqlite_master WHERE name=?",
                        (f"deny_{table}_{operation}",),
                    ).fetchone() != ("trigger",):
                        raise EpochEvidenceInvalid("archived immutability trigger absent")
            ledger = hashlib.sha256()
            seen = set()
            for row in connection.execute(
                "SELECT query_id,org,original_id,original_sha,query_sha,actor_role "
                "FROM queries ORDER BY query_id"
            ):
                query_id, org, original_id, original_sha, query_sha, role = row
                if (type(query_id) is not str or
                        _HEX_ID.fullmatch(query_id) is None or query_id in seen or
                        org != host_config.organization_id or
                        type(original_id) is not str or
                        _HEX_ID.fullmatch(original_id) is None or
                        type(original_sha) is not str or
                        _HEX_SHA.fullmatch(original_sha) is None or
                        type(query_sha) is not str or
                        _HEX_SHA.fullmatch(query_sha) is None or
                        role not in _ACTOR_ROLES):
                    raise EpochEvidenceInvalid("invalid historical query binding")
                seen.add(query_id)
                ledger.update(json.dumps(
                    row, separators=(",", ":"), ensure_ascii=True,
                ).encode("utf-8") + b"\n")
            if len(seen) != counts["queries"]:
                raise EpochEvidenceInvalid("historical replay index incomplete")
            for req in connection.execute(
                "SELECT org,sender,key_id,actor_role,payload_sha FROM requests"
            ):
                if (req[0] != host_config.organization_id or
                        req[1] != host_config.madar_sender_id or
                        req[2] != host_config.madar_key_id or
                        req[3] not in _ACTOR_ROLES or
                        type(req[4]) is not str or
                        _HEX_SHA.fullmatch(req[4]) is None):
                    raise EpochEvidenceInvalid("archived request identity mismatch")
    except sqlite3.DatabaseError as exc:
        raise EpochEvidenceInvalid("archived SQLite evidence unreadable") from exc
    if _file_sha256(archive_path) != expected_sha256:
        raise EpochEvidenceInvalid("archived evidence changed during readback")
    return {"queryBindingsSha256": ledger.hexdigest(), "counts": counts}


def _publish_create_only_json(path: Path, document: dict) -> str:
    """Write a bounded operator receipt; no names or secret key material."""
    payload = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    if len(payload) > 8192:
        raise EpochEvidenceInvalid("offline evidence receipt too large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    if (path.is_symlink() or not path.is_file() or
            path.read_bytes() != payload):
        raise EpochEvidenceInvalid("offline receipt readback failed")
    return hashlib.sha256(payload).hexdigest()


def prepare_offline_epoch_evidence(
    registry: TarazPeerRegistry, *, host_config: PeerConfig,
    proposed_config: PeerConfig, archive_path: Path,
    receipt_path: Path, approval_mac: bytes,
) -> dict:
    """Evidence-only operator preparation, always leaves epoch unchanged.

    Requires private Python host-owned live config and separately provisioned
    new key pair, plus old-host-key HMAC of the exact intent. Does NOT give
    the caller an epoch-enabled registry, authority to reset capacity, or a
    client-exposed endpoint. Incomplete exports are left for manual review.
    """
    verify_host_offline_approval(
        registry, host_config=host_config, proposed_config=proposed_config,
        archive_path=archive_path, receipt_path=receipt_path,
        approval_mac=approval_mac,
    )
    _checked_private_target(archive_path, suffix=".sqlite3")
    _checked_private_target(receipt_path, suffix=".json")
    if (archive_path.parent != receipt_path.parent or
            archive_path.parent == registry.path.parent and
            (archive_path.name == registry.path.name or
             receipt_path.name == registry.path.name)):
        raise EpochEvidenceInvalid("distinct private archive and receipt required")
    # Never touch/initialize the prospective epoch's registry file.
    before = registry.query_capacity_status()
    snapshot = registry.archive_to(archive_path)
    verified = _verify_archive(
        archive_path, host_config=host_config,
        expected_sha256=snapshot["archiveSha256"],
        expected_counts=snapshot,
    )
    after = registry.query_capacity_status()
    if before["used"] != after["used"] or after["used"] != snapshot["queries"]:
        raise EpochRolloverBlocked(
            "offline source replay set changed during export; do not activate"
        )
    receipt = {
        "schema": 1,
        "purpose": "taraz-mtr-offline-epoch-evidence-only",
        "status": "BLOCKED_PENDING_EPOCH_AWARE_REGISTRY",
        "activationAuthorized": False,
        "registryUnmodifiedByThisPrimitive": True,
        "archiveContainsHistoricalReplayBindingsAtSnapshot": True,
        "historicalQueryCount": snapshot["queries"],
        "historicalRequestCount": snapshot["requests"],
        "historicalAuditCount": snapshot["auditEvents"],
        "archiveSha256": snapshot["archiveSha256"],
        "queryBindingsSha256": verified["queryBindingsSha256"],
        "organizationId": host_config.organization_id,
        "originalMadarKeyId": host_config.madar_key_id,
        "candidateMadarKeyId": proposed_config.madar_key_id,
        "originalTarazKeyId": host_config.taraz_key_id,
        "candidateTarazKeyId": proposed_config.taraz_key_id,
        "noAutoResend": True,
        "liveQueryCapacityReleased": False,
        "requiresHistoricalReplayIndexAtEveryIntake": True,
    }
    receipt_sha = _publish_create_only_json(receipt_path, receipt)
    if _file_sha256(archive_path) != snapshot["archiveSha256"]:
        raise EpochEvidenceInvalid("archive changed after receipt publication")
    return {
        "status": receipt["status"],
        "activationAuthorized": False,
        "archiveSha256": snapshot["archiveSha256"],
        "receiptSha256": receipt_sha,
        "queryBindingsSha256": verified["queryBindingsSha256"],
        "historicalQueryCount": snapshot["queries"],
        "liveQueryCapacityReleased": False,
    }


def activate_epoch(*_args, **_kwargs) -> None:
    """Hard prohibition: current registry has no cross-epoch replay check."""
    raise EpochRolloverBlocked(
        "epoch activation unavailable: TarazPeerRegistry.query_receipt checks "
        "only local queries; implement audited cross-epoch replay binding, "
        "epoch-aware HMAC, authenticated cutover and crash recovery first"
    )


__all__ = [
    "EpochRolloverBlocked", "EpochEvidenceInvalid",
    "prepare_offline_epoch_evidence", "verify_host_offline_approval",
    "activate_epoch",
]
