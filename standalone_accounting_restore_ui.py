"""Explicit, OFFLINE graphical restore assistant for the separate accounting app.

This launcher is opt-in (--restore-ui). It MUST run before starting the accounting
desktop. It NEVER discovers APPDATA, overwrites a database, or restores in place.
All verification/publication is delegated to standalone_accounting_restore.
"""
from __future__ import annotations

from pathlib import Path

from standalone_accounting_backup import SOURCE_FILENAME, _absolute_path
from standalone_accounting_restore import (
    _check_input, _check_new_destination, restore_standalone_accounting,
    preview_template_companion,
)


def preview_restore_candidate(backup: Path, destination_folder: Path) -> dict:
    """Check selected backup and new output without creating any file."""
    source = _absolute_path(Path(backup), "restore source")
    folder = _absolute_path(Path(destination_folder), "restore folder")
    destination = folder / SOURCE_FILENAME
    _check_new_destination(source, destination)
    revision, digest = _check_input(source)
    companion = preview_template_companion(source, destination)
    return {
        "source": source, "destination": destination,
        "revision": revision, "digest": digest,
        "plaintext": True, "overwrites": False,
        "template_count": companion['count'], "has_template_companion": companion['present'],
    }


def run_restore_wizard() -> int:
    """Run before booting any accounting DB or LAN server. Cancel => no changes."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        source = filedialog.askopenfilename(
            parent=root, title="انتخاب نسخه پشتیبان حسابداری مستقل",
            filetypes=(("SQLite backups", "*.sqlite3"), ("All files", "*.*")))
        if not source:
            return 0
        folder = filedialog.askdirectory(
            parent=root, title="پوشه مقصد جدید و فاقد پایگاه داده را انتخاب کنید",
            mustexist=True)
        if not folder:
            return 0
        try:
            preview = preview_restore_candidate(Path(source), Path(folder))
        except Exception as exc:
            messagebox.showerror(
                "بازیابی رد شد", "نسخه پشتیبان یا مسیر مقصد معتبر نیست:\n" +
                str(exc), parent=root)
            return 1
        if not messagebox.askyesno(
            "بررسی نسخه پشتیبان",
            f"نسخه انتخابی معتبر و قابل بازپخش است.\n"
            f"تعداد رویدادها: {preview['revision']}\n"
            f"کتابخانه قالب‌های همراه: " +
            (f"{preview['template_count']} مورد\n" if preview['has_template_companion'] else "ندارد (بکاپ قدیمی)\n") +
            f"مقصد جدید: {preview['destination']}\n\n"
            "هیچ فایل فعلی جایگزین نمی‌شود. ادامه دهید؟",
            parent=root):
            return 0
        offline = simpledialog.askstring(
            "تأیید آفلاین",
            "همه نمونه‌های مدار و سرور شبکه باید واقعاً بسته باشند.\n"
            "پس از بستن آن‌ها، عبارت OFFLINE را دقیق وارد کنید:",
            parent=root)
        if offline != "OFFLINE":
            return 0
        plaintext = simpledialog.askstring(
            "تأیید اطلاعات مالی رمزنگاری‌نشده",
            "بازیابی اطلاعات مالی را به‌صورت فایل SQLite رمزنگاری‌نشده "
            "در مسیر جدید ذخیره می‌کند.\n"
            "برای پذیرش آگاهانه عبارت PLAINTEXT را دقیق وارد کنید:",
            parent=root)
        if plaintext != "PLAINTEXT":
            return 0
        try:
            published = restore_standalone_accounting(
                preview["source"], preview["destination"],
                offline_acknowledged=True, plaintext_acknowledged=True)
        except Exception as exc:
            messagebox.showerror(
                "بازیابی انجام نشد",
                "بازیابی رد شد و هیچ مقصد قبلی بازنویسی نشده است:\n" +
                str(exc), parent=root)
            return 1
        messagebox.showinfo(
            "بازیابی انجام شد",
            "نسخه معتبر در مسیر جدید ساخته شد. برای استفاده از آن در "
            "حسابداری مستقل، پوشه والد فایل زیر را انتخاب کنید.\n"
            "در صورت وجود، قالب‌ها نیز کنار بانک بازیابی شده‌اند.\n" +
            str(published), parent=root)
        return 0
    finally:
        root.destroy()
