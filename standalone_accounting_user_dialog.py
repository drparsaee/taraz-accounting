"""Administrator-only native user manager, with independent job titles and ACL.

Passwords and session tokens remain in Python/Tk and never enter the WebView.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont


TITLES=('مدیر ارشد','مدیر مالی','حسابدار','کارمند','سرپرست','مسئول فروش','مسئول انبار')
ACCESS={'مدیر سیستم (تمام اختیارات)':'admin',
        'ثبت و ویرایش (کاربر اجرایی)':'editor',
        'فقط مشاهده':'viewer'}
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


def manage_local_users(identity_store, administrator_token):
    global PERSIAN_FACE
    identity_store.require_session(administrator_token,'admin')
    root=tk.Tk()
    PERSIAN_FACE=_use_installed_persian_font(root)
    root.title('مدار | مدیریت کاربران همین شرکت')
    root.geometry('830x510')
    root.minsize(720,430)
    root.configure(bg='#f4f7fa')
    try:
        tk.Label(root,text='کاربران و نقش‌های سازمانی',font=(PERSIAN_FACE,15,'bold'),
                 bg='#f4f7fa',fg='#14263a',anchor='e').pack(fill='x',padx=22,pady=(18,6))
        tk.Label(root,text='عنوان شغلی قابل تایپ است؛ سطح دسترسی امنیتی به‌صورت جداگانه تعیین می‌شود.',
                 bg='#f4f7fa',fg='#526579',anchor='e').pack(fill='x',padx=22,pady=(0,14))
        table=ttk.Treeview(root,columns=('user','job','role','enabled'),show='headings',height=11)
        for key,label,width in (('user','نام کاربری',170),('job','عنوان شغلی',260),
                                ('role','دسترسی سیستم',200),('enabled','فعال',75)):
            table.heading(key,text=label)
            table.column(key,width=width,anchor='center')
        table.pack(fill='both',expand=True,padx=22)

        def refresh():
            for entry in table.get_children():table.delete(entry)
            for entry in identity_store.list_users(administrator_token):
                label=next((name for name,role in ACCESS.items() if role==entry['role']),
                           entry['role'])
                table.insert('', 'end',values=(entry['username'],entry['jobTitle'],label,
                             'بله' if entry['enabled'] else 'خیر'))

        def selected():
            ident=table.selection()
            return table.item(ident[0])['values'][0] if ident else None

        def attempt(action):
            try:action();refresh()
            except Exception as exc:messagebox.showerror('تغییر انجام نشد',str(exc),parent=root)

        def editor_dialog(username=None,only_password=False):
            win=tk.Toplevel(root)
            win.title('بازنشانی رمز' if only_password else
                      'ویرایش حساب کاربری' if username else 'ثبت کاربر جدید')
            win.geometry('495x430' if not only_password else '495x260')
            win.transient(root)
            win.grab_set()
            win.resizable(False,False)
            win.configure(bg='#f4f7fa')
            existing=next((entry for entry in identity_store.list_users(administrator_token)
                           if entry['username']==username),None) if username else None
            user=tk.StringVar(value=username or '')
            job=tk.StringVar(value=(existing['jobTitle'] if existing else 'کارمند'))
            access=tk.StringVar(value=next((label for label,role in ACCESS.items()
                        if role==(existing['role'] if existing else 'viewer')),'فقط مشاهده'))
            password=tk.StringVar()
            again=tk.StringVar()
            panel=tk.Frame(win,bg='#f4f7fa')
            panel.pack(fill='both',expand=True,padx=24,pady=16)

            def field(title,variable,*,secret=False,choices=None,readonly=False):
                tk.Label(panel,text=title,font=(PERSIAN_FACE,9),bg='#f4f7fa',anchor='e').pack(fill='x',pady=(6,2))
                if choices is not None:
                    entry=ttk.Combobox(panel,textvariable=variable,values=choices,
                                       state='readonly' if readonly else 'normal')
                else:
                    entry=ttk.Entry(panel,textvariable=variable,show='*' if secret else '')
                    if readonly:entry.configure(state='disabled')
                entry.pack(fill='x',ipady=4)
                return entry

            if not only_password:
                field('نام کاربری لاتین',user,readonly=username is not None)
                field('عنوان شغلی (انتخاب یا تایپ آزاد)',job,choices=TITLES)
                field('سطح دسترسی فنی نرم‌افزار',access,
                      choices=list(ACCESS),readonly=True)
            if not existing or only_password:
                field('رمز عبور جدید (حداقل ۱۰ نویسه؛ PIN چهاررقمی ممنوع)',password,secret=True)
                field('تکرار رمز عبور',again,secret=True)

            def commit():
                try:
                    if (not existing or only_password) and password.get()!=again.get():
                        raise ValueError('رمز و تکرار رمز یکسان نیستند')
                    if only_password:
                        identity_store.reset_password(username,password.get(),administrator=administrator_token)
                    elif existing:
                        # Title and authorization are two deliberately different fields.
                        identity_store.change_job_title(username,job.get(),administrator=administrator_token)
                        identity_store.change_role(username,ACCESS[access.get()],administrator=administrator_token)
                    else:
                        identity_store.add_user(user.get().strip(),password.get(),
                            ACCESS[access.get()],administrator=administrator_token,job_title=job.get())
                except Exception as exc:
                    messagebox.showerror('ثبت ناموفق',str(exc),parent=win)
                    return
                win.destroy()
            bar=tk.Frame(panel,bg='#f4f7fa')
            bar.pack(fill='x',pady=(16,0))
            ttk.Button(bar,text='ذخیره',command=commit).pack(side='right',padx=(8,0))
            ttk.Button(bar,text='انصراف',command=win.destroy).pack(side='right')
            win.wait_window()

        def disable():
            name=selected()
            if name and messagebox.askyesno('غیرفعالسازی','حساب '+name+' غیرفعال شود؟',parent=root):
                identity_store.disable_user(name,administrator=administrator_token)

        controls=tk.Frame(root,bg='#f4f7fa')
        controls.pack(fill='x',padx=22,pady=(16,20))
        for label,action in (('افزودن کاربر',lambda:editor_dialog()),
                             ('ویرایش عنوان و دسترسی',lambda:editor_dialog(selected()) if selected() else None),
                             ('بازنشانی رمز',lambda:editor_dialog(selected(),True) if selected() else None),
                             ('غیرفعالسازی',disable)):
            ttk.Button(controls,text=label,command=lambda f=action:attempt(f)).pack(side='right',padx=4)
        ttk.Button(controls,text='بستن',command=root.destroy).pack(side='left')
        refresh()
        root.mainloop()
    finally:
        try:root.destroy()
        except tk.TclError:pass
