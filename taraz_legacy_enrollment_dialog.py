"""One-time native Taraz enrollment UI; no webview/JS access to passwords."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from taraz_legacy_ownership_enrollment import (
    CONSENT, approve_declaration, pending_company,
)


def prompt_pending_legacy_enrollment(root: Path) -> bool:
    """Only the human pressing the native confirmation can authorize enrollment."""
    pending = pending_company(Path(root))
    if pending is None:
        return True
    window = tk.Tk()
    window.title('تراز | تأیید یک‌باره مسئول دفتر قدیمی')
    window.geometry('720x600')
    window.minsize(610, 530)
    window.configure(bg='#f4f7fa')
    username = tk.StringVar()
    password = tk.StringVar()
    confirm = tk.StringVar()
    typed = tk.StringVar()
    agreed = tk.BooleanVar(value=False)
    status = tk.StringVar(value='')
    completed = {'value': False}
    panel = ttk.Frame(window, padding=24)
    panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='فعال‌سازی مدیریت دفتر قدیمی تراز',
              font=('Tahoma', 17, 'bold')).pack(anchor='e', pady=(0, 12))
    ttk.Label(panel, text=(
        'این دفتر از نسخهٔ ۱.۰.۴ بازیابی شده است. نام حقوقی و مالکیت شرکت '
        'از فایل‌های قدیمی قابل اثبات نیست. این مرحله صرفاً اعلام مسئولیت '
        'توسط شماست، نه تأیید مستقل مالکیت قانونی.'),
        wraplength=630, justify='right').pack(anchor='e', pady=(0, 16))
    ttk.Label(panel, text=f"رویدادهای قدیمی: {pending['ledger']['eventCount']}  |  "
              f"شناسهٔ دفتر: {pending['workspaceId'][:12]}…",
              font=('Tahoma', 9)).pack(anchor='e', pady=(0, 14))
    for label, variable, hidden in (
        ('نام کاربری مدیر جدید', username, False),
        ('رمز عبور جدید مدیر (حداقل ۸ نویسه)', password, True),
        ('تکرار رمز عبور', confirm, True),
        ('متن تأیید را دقیقاً وارد کنید:', typed, False),
    ):
        ttk.Label(panel, text=label).pack(anchor='e', pady=(6, 2))
        entry = ttk.Entry(panel, textvariable=variable, show='*' if hidden else '')
        entry.pack(fill='x')
    ttk.Label(panel, text=CONSENT, font=('Tahoma', 9, 'bold')
              ).pack(anchor='e', pady=(6, 10))
    ttk.Checkbutton(panel, text='می‌دانم این یک Declaration است، نه اثبات حقوقی مالکیت.',
                    variable=agreed).pack(anchor='e')
    ttk.Label(panel, textvariable=status, foreground='#af2536',
              wraplength=600).pack(anchor='e', pady=(10, 0))

    def confirm_action():
        if password.get() != confirm.get() or len(password.get()) < 8:
            status.set('رمز عبور و تکرار آن باید یکسان و حداقل ۸ نویسه باشند.')
            return
        try:
            approve_declaration(Path(root), company_id=pending['companyId'],
                username=username.get().strip(), password=password.get(),
                confirmation=typed.get(), consent_checked=agreed.get())
        except Exception as exc:
            # Never render exception details, paths, usernames or passwords.
            status.set('ثبت انجام نشد؛ به دلیل عدم احراز شرایط، دسترسی مدیریت فعال نشد.')
            return
        finally:
            password.set('')
            confirm.set('')
        completed['value'] = True
        window.quit()

    controls = ttk.Frame(panel)
    controls.pack(fill='x', pady=20)
    ttk.Button(controls, text='تأیید مسئولیت و ایجاد مدیر',
               command=confirm_action).pack(side='right')
    ttk.Button(controls, text='انصراف', command=window.quit).pack(side='left')
    window.protocol('WM_DELETE_WINDOW', window.quit)
    try:
        window.mainloop()
        return completed['value']
    finally:
        password.set('')
        confirm.set('')
        window.destroy()
