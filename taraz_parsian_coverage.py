"""Pure, summary-only coverage inspection for a Parsian migration inventory.

Does not open source files, expose rows, authenticate source digests, or import
into Taraz. A structurally complete manifest is NOT a verified migration.
"""
from __future__ import annotations

import re

_YEAR = re.compile(r"[0-9]{4}\Z")
_MODULE = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_YEARS = 100
_MAX_MODULES = 250
_MAX_ROWS = 100_000_000


def _names(values, *, kind, maximum, pattern):
    if (type(values) is not list or not 1 <= len(values) <= maximum
            or any(type(item) is not str or not pattern.fullmatch(item) for item in values)
            or len(values) != len(set(values))):
        raise ValueError(f"Expected unique explicit {kind}")
    return values


def inspect_parsian_coverage(manifest: dict) -> dict:
    """Return sanitized coverage statuses; never classify data as verified.

    expectedYears and expectedModules MUST come from separately audited
    inventory evidence; supplying these strings is not itself source proof.
    """
    fields = {"schemaVersion", "sourceSystem", "currency", "expectedYears",
              "expectedModules", "observedYears"}
    if type(manifest) is not dict or set(manifest) != fields:
        raise ValueError("Unsupported Parsian inventory manifest shape")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1:
        raise ValueError("Unsupported inventory schema version")
    if manifest["sourceSystem"] != "parsian" or type(manifest["sourceSystem"]) is not str:
        raise ValueError("Unexpected source system")
    if manifest["currency"] != "RIAL" or type(manifest["currency"]) is not str:
        raise ValueError("Explicit source currency RIAL required")
    expected_years = _names(manifest["expectedYears"], kind="fiscal years",
                            maximum=_MAX_YEARS, pattern=_YEAR)
    required_modules = _names(manifest["expectedModules"], kind="source modules",
                              maximum=_MAX_MODULES, pattern=_MODULE)
    years = manifest["observedYears"]
    if type(years) is not list or len(years) > _MAX_YEARS:
        raise ValueError("Invalid observed year list")
    observed = {}
    for entry in years:
        if type(entry) is not dict or set(entry) != {"year", "modules"}:
            raise ValueError("Observed year includes unexpected data")
        year = entry["year"]
        if type(year) is not str or not _YEAR.fullmatch(year) or year in observed:
            raise ValueError("Duplicate or invalid observed fiscal year")
        modules = entry["modules"]
        if type(modules) is not list or len(modules) > _MAX_MODULES:
            raise ValueError("Invalid observed module list")
        source_modules = {}
        for item in modules:
            if type(item) is not dict or set(item) != {"module", "rows", "sha256"}:
                raise ValueError("Module summary includes raw/private fields")
            name = item["module"]
            if (type(name) is not str or not _MODULE.fullmatch(name)
                    or name in source_modules):
                raise ValueError("Invalid or duplicated module name")
            if type(item["rows"]) is not int or not 0 <= item["rows"] <= _MAX_ROWS:
                raise ValueError("Module row count must be bounded exact integer")
            if type(item["sha256"]) is not str or not _DIGEST.fullmatch(item["sha256"]):
                raise ValueError("Invalid source module digest format")
            source_modules[name] = item["rows"]
        observed[year] = source_modules
    coverage = []
    missing = []
    for year in expected_years:
        modules = observed.get(year)
        if modules is None:
            coverage.append({"year": year, "status": "MISSING_YEAR",
                             "missingModules": list(required_modules)})
            missing.append(year + ":*")
            continue
        absent = [name for name in required_modules if name not in modules]
        coverage.append({"year": year,
                         "status": "MISSING_MODULES" if absent else "STRUCTURAL_ONLY",
                         "missingModules": absent})
        missing.extend(year + ":" + name for name in absent)
    unexpected = sorted(set(observed) - set(expected_years))
    # No amount, customer name, CSV row, source path, or authenticated claim.
    return {
        "status": "SOURCE_EVIDENCE_REQUIRED",
        "readyForMigration": False,
        "postingAllowed": False,
        "sourceAuthenticated": False,
        "currency": "RIAL",
        "coverage": coverage,
        "missing": missing,
        "unexpectedYears": unexpected,
        "structurallyComplete": not missing and not unexpected,
    }
