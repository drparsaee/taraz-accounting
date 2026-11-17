"""Validate the one-active-task Taraz delivery queue without touching user data.

Usage:
  python -B scripts/validate_taraz_phase_board.py
  python -B scripts/validate_taraz_phase_board.py path/to/board.json
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

DEFAULT = Path(__file__).resolve().parents[1] / "docs/ops/taraz-phase-board.json"
STATES = {"source_verified", "active", "queued", "blocked"}
ID = re.compile(r"^TAR-[0-9]{2}$")
SHA = re.compile(r"^commit:[a-f0-9]{40}$")


class BoardError(ValueError):
    """Invalid source-of-truth status. Fail closed instead of guessing progress."""


def validate(board: dict) -> dict:
    if not isinstance(board, dict) or board.get("schemaVersion") != 1:
        raise BoardError("Unrecognized phase board schema")
    execution = board.get("execution")
    phases = board.get("phases")
    tasks = board.get("tasks")
    if not isinstance(execution, dict) or not isinstance(phases, list) or not isinstance(tasks, list):
        raise BoardError("Missing execution, phases or tasks")
    if not tasks or not phases:
        raise BoardError("Empty phase plan")
    if execution.get("oneActiveTaskOnly") is not True:
        raise BoardError("Parallel task execution is forbidden")
    if any(execution.get(key) is not False for key in (
            "financialPostingAuthorized", "installedModificationAuthorized",
            "productionDataAuthorized", "defaultBranchMergeAuthorized")):
        raise BoardError("Unsafe authorization flag is enabled")
    phase_ids = [p.get("id") for p in phases if isinstance(p, dict)]
    if len(phase_ids) != len(phases) or len(set(phase_ids)) != len(phase_ids):
        raise BoardError("Duplicate or invalid phase")
    if any(not isinstance(p.get("title"), str) or not p["title"].strip() for p in phases):
        raise BoardError("Phase without title")
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise BoardError("Malformed task")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not ID.fullmatch(task_id) or task_id in by_id:
            raise BoardError(f"Duplicate or invalid task ID: {task_id!r}")
        if task.get("phase") not in phase_ids:
            raise BoardError(f"Unknown phase for {task_id}")
        if task.get("status") not in STATES:
            raise BoardError(f"Invalid state for {task_id}")
        if any(not isinstance(task.get(key), str) or not task[key].strip()
               for key in ("title", "scope")):
            raise BoardError(f"Missing task title/scope: {task_id}")
        if (not isinstance(task.get("acceptance"), list) or not task["acceptance"]
                or any(not isinstance(a, str) or not a.strip()
                       for a in task["acceptance"])):
            raise BoardError(f"Missing acceptance criteria: {task_id}")
        deps = task.get("dependsOn")
        evidence = task.get("evidence")
        if (not isinstance(deps, list) or any(not isinstance(d, str) for d in deps)
                or len(deps) != len(set(deps)) or task_id in deps):
            raise BoardError(f"Invalid dependencies: {task_id}")
        if not isinstance(evidence, list) or any(not isinstance(e, str) or not e.strip()
                                                 for e in evidence):
            raise BoardError(f"Invalid evidence: {task_id}")
        if task["status"] == "source_verified":
            if not any(SHA.fullmatch(e) for e in evidence):
                raise BoardError(f"Verified task has no exact commit proof: {task_id}")
            if not any("PASS" in e for e in evidence):
                raise BoardError(f"Verified task has no passing test proof: {task_id}")
        if task["status"] == "blocked" and not task.get("blocker"):
            raise BoardError(f"Blocked task lacks a blocker: {task_id}")
        by_id[task_id] = task
    active = [t for t in tasks if t["status"] == "active"]
    if len(active) != 1 or execution.get("activeTaskId") != active[0]["id"]:
        raise BoardError("Exactly one matching active task is required")

    visiting = set()
    visited = set()

    def visit(task_id: str):
        if task_id in visiting:
            raise BoardError(f"Dependency cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in by_id[task_id]["dependsOn"]:
            if dep not in by_id:
                raise BoardError(f"Unknown dependency {dep} for {task_id}")
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)
    for task in tasks:
        if task["status"] in ("source_verified", "active"):
            incomplete = [d for d in task["dependsOn"]
                          if by_id[d]["status"] != "source_verified"]
            if incomplete:
                raise BoardError(f"{task['id']} has unmet dependencies: {incomplete}")
    if execution.get("releaseStatus") != "NO-GO":
        if any(t["status"] != "source_verified" for t in tasks):
            raise BoardError("Cannot lift release gate with unresolved tasks")
        # Release authorization is deliberately out of scope for this board.
        raise BoardError("Release state requires a separate signed acceptance gate")
    return {
        "tasks": len(tasks),
        "verified": sum(t["status"] == "source_verified" for t in tasks),
        "queued": sum(t["status"] == "queued" for t in tasks),
        "blocked": sum(t["status"] == "blocked" for t in tasks),
        "active": active[0]["id"],
        "release": execution["releaseStatus"],
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("Usage: validate_taraz_phase_board.py [board.json]", file=sys.stderr)
        return 2
    path = Path(args[0]) if args else DEFAULT
    try:
        result = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, BoardError) as exc:
        print(f"INVALID BOARD: {exc}", file=sys.stderr)
        return 1
    print("BOARD VALID: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
