"""Premium local credential gate, before loading WebView or the financial DB.

Native Tk only; secrets stay outside the JavaScript DOM and HTTP server.
It intentionally does not pretend to provide remote/LAN authentication.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox,ttk,font as tkfont
from standalone_accounting_identity import IdentityError

NIGHT='#0b1728'
INK='#14263a'
SEA='#08afa5'
PAPER='#f4f7fa'
WHITE='#ffffff'
MUTED='#637c90'
PERSIAN_FACE='Tahoma'


def _use_installed_persian_font(root):
    try:
        available={name.casefold():name for name in tkfont.families(root)}
        face=next((available[name.casefold()]
                   for name in ('Estedad','Vazirmatn','Dana','Tahoma')
                   if name.casefold() in available),'Tahoma')
        for name in ('TkDefaultFont','TkTextFont','TkHeadingFont','TkMenuFont'):
            tkfont.nametofont(name,root=root).configure(family=face)
        return face
    except (tk.TclError,AttributeError,TypeError):
        return 'Tahoma'


class PremiumAccountingLogin:
    def __init__(self,identity,*,root=None):
        global PERSIAN_FACE
        self.identity=identity
        self.setup=not identity.initialized()
        self.root=root or tk.Tk()
        PERSIAN_FACE=_use_installed_persian_font(self.root)
        self.root.title('مدار | ورود امن حسابداری')
        self.root.geometry('780x585' if self.setup else '780x530')
        self.root.minsize(650,545 if self.setup else 470)
        self.root.configure(bg=PAPER)
        self.root.protocol('WM_DELETE_WINDOW',self.cancel)
        self.username=tk.StringVar()
        self.password=tk.StringVar()
        self.confirm_password=tk.StringVar()
        self.job_title=tk.StringVar(value='مدیر ارشد')
        self.status=tk.StringVar(value='رمزها فقط در رایانه محلی بررسی می‌شوند.')
        self.attempts=0
        self.result=None
        shell=tk.Frame(self.root,bg=PAPER)
        shell.pack(fill='both',expand=True)
        left=tk.Frame(shell,width=240,bg=NIGHT)
        left.pack(side='left',fill='y')
        left.pack_propagate(False)
        tk.Label(left,text='M',font=('Segoe UI',38,'bold'),bg=SEA,fg=NIGHT,
                 width=3).pack(anchor='w',padx=24,pady=(42,38))
        tk.Label(left,text='MADAR / SECURE',font=('Segoe UI',10,'bold'),bg=NIGHT,
                 fg='#55d5cc').pack(anchor='e',padx=24)
        tk.Label(left,text='دفتر امن\nبرای هر شرکت',font=(PERSIAN_FACE,19,'bold'),
                 bg=NIGHT,fg=WHITE,justify='right').pack(anchor='e',padx=24,pady=22)
        tk.Label(left,text='هویت این شرکت مستقل\nاز شرکت‌های دیگر است.',
                 font=(PERSIAN_FACE,9),bg=NIGHT,fg='#bacad4',
                 justify='right').pack(anchor='e',padx=24)
        tk.Label(left,text='WINDOWS  •  LOCAL  •  PRIVATE',font=('Segoe UI',8),
                 bg=NIGHT,fg='#7b9aae').pack(side='bottom',pady=26)
        right=tk.Frame(shell,bg=PAPER)
        right.pack(side='right',fill='both',expand=True,padx=36)
        tk.Label(right,text='راه‌اندازی حساب مدیر' if self.setup else 'ورود به حسابداری',
                 font=(PERSIAN_FACE,19,'bold'),bg=PAPER,fg=INK,
                 anchor='e').pack(fill='x',pady=(32 if self.setup else 58,8))
        tk.Label(right,text=('برای این دفتر نام کاربری و رمز مدیر را ثبت کنید.'
                 if self.setup else 'نام کاربری و رمز عبور شرکت انتخاب‌شده را وارد کنید.'),
                 font=(PERSIAN_FACE,9),bg=PAPER,fg=MUTED,anchor='e'
                 ).pack(fill='x',pady=(0,12 if self.setup else 30))
        self.inputs=[]
        if self.setup:
            tk.Label(right,text='عنوان شغلی (قابل تغییر)',font=(PERSIAN_FACE,9,'bold'),bg=PAPER,
                     fg=INK,anchor='e').pack(fill='x',pady=(0,4))
            ttk.Combobox(right,textvariable=self.job_title,
                values=('مدیر ارشد','مدیر مالی','حسابدار','کارمند'),
                state='normal',justify='right').pack(fill='x',ipady=4,pady=(0,9))
        for label,variable,secret in [
            ('نام کاربری',self.username,False),
            ('رمز عبور (حداقل ۴ نویسه، رمز ۴ رقمی مجاز)',self.password,True),
            *(([('تکرار رمز عبور',self.confirm_password,True)]) if self.setup else [])]:
            tk.Label(right,text=label,font=(PERSIAN_FACE,9,'bold'),bg=PAPER,
                     fg=INK,anchor='e').pack(fill='x',pady=(9,4))
            entry=tk.Entry(right,textvariable=variable,
                           show='*' if secret else '',justify='left',font=('Segoe UI',12),
                           bg=WHITE,fg=INK,insertbackground=SEA,
                           relief='solid',bd=1)
            entry.pack(fill='x',ipady=9)
            entry.bind('<Return>',lambda _:self.submit())
            self.inputs.append(entry)
        tk.Label(right,textvariable=self.status,font=(PERSIAN_FACE,8),
                 bg=PAPER,fg=MUTED,anchor='e',wraplength=420
                 ).pack(fill='x',pady=(16,0))
        actions=tk.Frame(right,bg=PAPER)
        actions.pack(side='bottom',fill='x',pady=(20,34))
        tk.Button(actions,text='ایجاد مدیر و ورود' if self.setup else 'ورود امن',
                  command=self.submit,font=(PERSIAN_FACE,10,'bold'),bg=SEA,
                  fg=NIGHT,activebackground='#91e3db',relief='flat',
                  padx=18,pady=12).pack(side='right')
        tk.Button(actions,text='انصراف',command=self.cancel,font=(PERSIAN_FACE,10),
                  bg=WHITE,fg=INK,relief='flat',padx=16,pady=12
                  ).pack(side='left')
        self.root.after(100,self.inputs[0].focus_set)

    def submit(self):
        user=self.username.get().strip()
        password=self.password.get()
        if self.setup:
            if password!=self.confirm_password.get():
                self.status.set('رمز و تکرار آن یکسان نیستند.')
                self.password.set('');self.confirm_password.set('')
                return
            try:
                self.identity.add_user(user,password,'admin',job_title=self.job_title.get())
                token=self.identity.login(user,password)
                self.result=self.identity.require_session(token),token
            except Exception as exc:
                self.status.set('ساخت مدیر انجام نشد: '+str(exc))
                self.password.set('');self.confirm_password.set('')
                return
        else:
            try:
                token=self.identity.login(user,password)
                self.result=self.identity.require_session(token),token
            except Exception:
                self.attempts+=1
                self.status.set('ورود ناموفق یا موقتاً محدود شده است؛ اطلاعات را بررسی کنید.')
                self.password.set('')
                if self.attempts>=3:
                    self.status.set('تعداد تلاش در این پنجره به پایان رسید.')
                    self.root.after(500,self.cancel)
                return
        self.password.set('');self.confirm_password.set('')
        self.root.quit()

    def cancel(self):
        self.result=None
        self.password.set('');self.confirm_password.set('')
        self.root.quit()

    def run(self):
        try:
            self.root.mainloop()
            return self.result
        finally:
            self.root.destroy()


def prompt_premium_accounting_login(identity):
    return PremiumAccountingLogin(identity).run()
