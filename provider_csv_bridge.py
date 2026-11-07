"""Native-file-selection boundary for read-only provider-neutral CSV preview.

The host keeps a volatile per-window allowlist of selected CSV paths. The web
page cannot cause a preview of an arbitrary unselected absolute path.
"""

from pathlib import Path

from provider_csv_staging import CsvStagingError, inspect_csv_headers, stage_provider_csv


GROUPS = frozenset({"parties", "invoices", "transactions"})


class ProviderCsvPreviewBridge:
    def __init__(self):
        self._selected = {}

    def select(self, group, encoding, delimiter, chosen):
        if type(group) is not str or group not in GROUPS:
            raise CsvStagingError("Unknown CSV group")
        # Replace a previous selection before validating the next one.
        self._selected.pop(group, None)
        if chosen is None or chosen == [] or chosen == ():
            return {"canceled": True}
        if isinstance(chosen, (tuple, list)):
            if len(chosen) != 1:
                raise CsvStagingError("Choose exactly one CSV file")
            chosen = chosen[0]
        if type(chosen) is not str or not Path(chosen).is_absolute():
            raise CsvStagingError("Selected file must have an absolute path")
        columns = inspect_csv_headers(chosen, encoding=encoding, delimiter=delimiter)
        selected = str(Path(chosen).resolve(strict=True))
        self._selected[group] = (selected, encoding, delimiter)
        return {"canceled": False, "group": group, "path": selected,
                "filename": Path(selected).name, "columns": columns,
                "encoding": encoding, "delimiter": delimiter}

    def preview(self, spec):
        if type(spec) is not dict or type(spec.get("datasets")) is not dict:
            raise CsvStagingError("Invalid CSV preview request")
        datasets = spec["datasets"]
        if set(datasets) != GROUPS or set(self._selected) != GROUPS:
            raise CsvStagingError("All three CSV files must be selected")
        for group in GROUPS:
            item = datasets[group]
            if type(item) is not dict:
                raise CsvStagingError("Invalid CSV source specification")
            selected, encoding, delimiter = self._selected[group]
            if (type(item.get("path")) is not str
                    or item["path"] != selected
                    or item.get("encoding") != encoding
                    or item.get("delimiter") != delimiter):
                raise CsvStagingError("CSV source must match the selected local file and format")
        return stage_provider_csv(spec)


__all__ = ["ProviderCsvPreviewBridge"]
