"""Pure, non-authoritative duplicate-source audit for synthetic/isolated journals.

This audit cannot prove that an attacker with write access to the database
has not rewritten both the entries and their unkeyed hash chain.
"""
from __future__ import annotations

from collections import Counter


def inspect_source_uniqueness(journals: list) -> dict:
    """Find repeated (sourceType,sourceId) pairs without leaking source IDs.

    A journal may contain multiple accounting lines but must be backed by one
    identifiable business source; a second journal with the same exact source
    pair is a collision that needs review. This is a reporting tool only.
    """
    if type(journals) is not list or len(journals) > 100000:
        raise ValueError("Journal batch must be a bounded list")
    seen_entries = set()
    sources = []
    for row in journals:
        if type(row) is not dict:
            raise ValueError("Journal entry must be an object")
        required = ("id", "sourceType", "sourceId", "eventId", "lines")
        if any(key not in row for key in required):
            raise ValueError("Journal entry lacks source identifiers")
        for key in required[:-1]:
            if (type(row[key]) is not str or not row[key] or len(row[key]) > 180):
                raise ValueError("Unusable journal identifier")
        if type(row["lines"]) is not list or len(row["lines"]) < 2:
            raise ValueError("Journal lacks explicit accounting lines")
        if row["id"] in seen_entries:
            raise ValueError("Duplicate journal ID")
        seen_entries.add(row["id"])
        sources.append((row["sourceType"], row["sourceId"]))
    counts = Counter(sources)
    collisions = sum(count - 1 for count in counts.values() if count > 1)
    return {
        "status": "DUPLICATE_SOURCE_REVIEW_REQUIRED" if collisions else "STRUCTURAL_ONLY",
        "journalCount": len(journals),
        "distinctBusinessSources": len(counts),
        "duplicateSourceOccurrences": collisions,
        "blocking": collisions > 0,
        "sourceAuthenticated": False,
        "tamperProof": False,
    }
