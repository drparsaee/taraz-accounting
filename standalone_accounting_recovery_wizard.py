"""Operator-guided OFFLINE restoration to a NEW, empty accounting workspace.

This GUI is deliberately a separate startup mode; it never opens the active
Madar ledger or auto-selects a live database. It does not modify a backup.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import os
import sqlite3

from standalone_accounting_auto_backup import BACKUP_FOLDER, _NAME
from standalone_accounting_restore import (
    _check_input, _check_new_destination, _is_link_or_junction,
    restore_standalone_accounting, preview_template_companion,
)
from standalone_accounting_backup import SOURCE_FILENAME, _readonly_sqlite


def recovery_preview(source: Path, destination_directory: Path) -> dict:
    """Read-only validation, no implicit migration, no replacement or writes.

    Failure of the destination safety check is shown BEFORE confirmations.
    The actual restore repeats all checks immediately before atomic publication.
    """
    if not isinstance(source, Path) or not source.is_absolute():
        raise ValueError("Choose an absolute SQLite backup file")
    if not isinstance(destination_directory, Path) or not destination_directory.is_absolute():
        raise ValueError("Choose an absolute destination directory")
    destination = destination_directory / SOURCE_FILENAME
    _check_new_destination(source, destination)
    revision, digest = _check_input(source)
    companion = preview_template_companion(source, destination)
    with closing(_readonly_sqlite(source)) as conn:
        row = conn.execute(
            "SELECT state FROM standalone_accounting WHERE id=1").fetchone()
        if row is None:
            currency, count = "RIAL (empty database)", 0
        else:
            from standalone_accounting import _decode_checked
            stored = _decode_checked(row[0], digest)
            currency, count = stored["currency"], len(stored["events"])
    return {
        "source": source,
        "destination": destination,
        "revision": revision,
        "events": count,
        "currency": currency,
        "templates": companion['count'], "has_templates": companion['present'],
        "plaintext": True,
        "existing_destination_will_be_overwritten": False,
    }


def list_recovery_candidates(explicit_data_root: Path) -> list[dict]:
    """Inspect only recognized automatic backups under the provided directory."""
    if not isinstance(explicit_data_root, Path) or not explicit_data_root.is_absolute():
        raise ValueError("Recovery directory must be explicit and absolute")
    if any(_is_link_or_junction(part) for part in
           (explicit_data_root, *explicit_data_root.parents)):
        raise ValueError("Recovery directory cannot use links or junctions")
    root = explicit_data_root / BACKUP_FOLDER
    if not root.is_dir() or _is_link_or_junction(root):
        return []
    candidates = []
    for entry in root.iterdir():
        if not _NAME.fullmatch(entry.name):
            continue
        try:
            revision, _ = _check_input(entry)
            candidates.append({"path": entry, "revision": revision,
                               "modified_ns": entry.stat().st_mtime_ns})
        except (ValueError, OSError, sqlite3.Error, RuntimeError):
            # Never offer a corrupt backup as an apparently recoverable choice.
            continue
    return sorted(candidates, key=lambda r: (r["modified_ns"], r["path"].name),
                  reverse=True)


def run_offline_recovery_wizard(explicit_data_root: Path | None = None) -> bool:
    """Start without any API/DB writer or background backup thread.

    Two human confirmations are required. Returning True indicates a NEW
    database was created, not that it was adopted by the running app.
    """
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        suggested = None
        if explicit_data_root is not None:
            if not isinstance(explicit_data_root, Path) or not explicit_data_root.is_absolute():
                raise ValueError("Recovery data directory must be absolute")
            suggested = str(explicit_data_root / BACKUP_FOLDER)
        options = {"parent": root, "title": "انتخاب نسخه پشتیبان قابل بازیابی حسابداری",
                   "filetypes": [("SQLite backup", "*.sqlite3")]}
        if suggested and Path(suggested).is_dir():
            options["initialdir"] = suggested
        source_name = filedialog.askopenfilename(**options)
        if not source_name:
            return False
        chosen_dir = filedialog.askdirectory(
            parent=root, title="انتخاب پوشه مستقل و خالی برای بازیابی",
            mustexist=True)
        if not chosen_dir:
            return False
        preview = recovery_preview(Path(source_name), Path(chosen_dir))
        if not messagebox.askyesno(
                "بازبینی نسخه و مقصد",
                "بازیابی فقط به یک پایگاه داده تازه انجام می‌شود.\n"
                f"نسخه: {preview['revision']} | رویدادها: {preview['events']}\n"
                f"واحد دفتر: {preview['currency']}\n"
                f"کتابخانه قالب‌ها: {preview['templates']} مورد"
                + ("\n" if preview['has_templates'] else " (بکاپ قدیمی، بدون قالب)\n") +
                f"منبع: {preview['source']}\nمقصد: {preview['destination']}\n\n"
                "پشتیبان و پایگاه داده رمزگذاری نمی‌شوند. "
                "نگهداری امن داده‌های مالی را قبول می‌کنید؟",
                parent=root):
            return False
        if not messagebox.askyesno(
                "تأیید کارکرد آفلاین",
                "همه نسخه‌های باز مدار و سرویس‌های مرتبط باید بسته باشند.\n"
                "این ابزار بسته‌بودن آن‌ها را تشخیص نمی‌دهد. "
                "آیا اجرای کامل عملیات در وضعیت آفلاین را تأیید می‌کنید؟",
                parent=root):
            return False
        restored = restore_standalone_accounting(
            preview["source"], preview["destination"],
            plaintext_acknowledged=True, offline_acknowledged=True)
        messagebox.showinfo(
            "بازیابی مستقل انجام شد",
            "پایگاه داده تازه ایجاد شد و در صورت وجود، قالب‌ها نیز بازیابی شدند. دیتابیس قبلی تغییر نکرد.\n" +
            str(restored), parent=root)
        return True
    except Exception as exc:
        messagebox.showerror(
            "بازیابی متوقف شد",
            "هیچ جایگزینی روی پایگاه داده قبلی مجاز نیست.\n" +
            str(exc), parent=root)
        return False
    finally:
        root.destroy()


__all__ = ["recovery_preview", "list_recovery_candidates",
           "run_offline_recovery_wizard"]
