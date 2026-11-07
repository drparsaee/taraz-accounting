"""Premium RTL Windows welcome/company selection for the local accounting app.

This is a company selector, NOT a password screen: local standalone uses a
single local operator identity. It never claims multi-user authentication.
Nothing in this UI opens or modifies a company ledger before confirmation.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, font as tkfont
from pathlib import Path
from standalone_accounting_company_registry import normalized_company_label


INK = '#14263A'
DEEP = '#0B1728'
MID = '#15314A'
MUTED = '#6C8090'
SEA = '#08AFA5'
SEA_LIGHT = '#E4F9F5'
WHITE = '#FFFFFF'
SURFACE = '#F4F7FA'
LINE = '#DAE4EC'
PERSIAN_FACE = 'Tahoma'


def _use_installed_persian_font(root):
    """Use a locally installed typeface, without distributing commercial fonts."""
    try:
        available = {name.casefold(): name for name in tkfont.families(root)}
        face = next((available[name.casefold()]
                     for name in ('Estedad', 'Vazirmatn', 'Dana', 'Tahoma')
                     if name.casefold() in available), 'Tahoma')
        for name in ('TkDefaultFont', 'TkTextFont', 'TkHeadingFont', 'TkMenuFont'):
            tkfont.nametofont(name, root=root).configure(family=face)
        return face
    except (tk.TclError, AttributeError, TypeError):
        return 'Tahoma'


def rounded(canvas, x1, y1, x2, y2, radius, *, fill, outline='', width=1):
    radius = max(0, min(radius, (x2-x1)/2, (y2-y1)/2))
    points = [x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,
              x2,y2-radius,x2,y2,x2-radius,y2,x1+radius,y2,
              x1,y2,x1,y2-radius,x1,y1+radius,x1,y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=12,
                                 fill=fill, outline=outline, width=width)


class ActionButton(tk.Canvas):
    """Keyboard-accessible custom pill with hover and disabled behavior."""
    def __init__(self, parent, label, action, *, primary=False, width=156,
                 height=46, disabled=False):
        super().__init__(parent, width=width, height=height, bd=0,
                         highlightthickness=2, highlightbackground=SURFACE,
                         highlightcolor=SEA, takefocus=1,
                         bg=parent.cget('bg'), cursor='hand2')
        self.label, self.action, self.primary = label, action, primary
        self.hover = False
        self.disabled = disabled
        self.bind('<Enter>', lambda e:self._hover(True))
        self.bind('<Leave>', lambda e:self._hover(False))
        self.bind('<Button-1>', lambda e:self.invoke())
        self.bind('<Return>', lambda e:self.invoke())
        self.bind('<space>', lambda e:self.invoke())
        self.draw()

    def _hover(self, value):
        self.hover=value
        self.draw()

    def set_disabled(self, value):
        self.disabled=bool(value)
        self.configure(cursor='arrow' if self.disabled else 'hand2')
        self.draw()

    def draw(self):
        self.delete('all')
        if self.primary:
            fill='#B8EDE7' if self.hover and not self.disabled else SEA
            fg=DEEP
        else:
            fill='#E9F0F5' if self.hover and not self.disabled else WHITE
            fg=INK
        if self.disabled:
            fill='#DDE5EB';fg='#8897A5'
        w=int(self.cget('width'));h=int(self.cget('height'))
        rounded(self,2,2,w-2,h-2,12,fill=fill,
                outline=LINE if not self.primary else fill)
        self.create_text(w/2,h/2,text=self.label,fill=fg,
                         font=(PERSIAN_FACE,10,'bold'))

    def invoke(self):
        if not self.disabled:
            self.action()


class PremiumCompanyChooser:
    def __init__(self, registry, *, root=None):
        global PERSIAN_FACE
        self.registry=registry
        self.root=root or tk.Tk()
        PERSIAN_FACE = _use_installed_persian_font(self.root)
        self.root.title('مدار | انتخاب شرکت و ورود به دفتر')
        self.root.geometry('1000x680')
        self.root.minsize(800,575)
        self.root.configure(bg=SURFACE)
        self.root.protocol('WM_DELETE_WINDOW',self.cancel)
        self.selected=None
        self.current=[]
        self.visible=[]
        self.query=tk.StringVar()
        self.company_name=tk.StringVar()
        self.create_open=False
        self.status=tk.StringVar(value='دفترها از یکدیگر جدا نگهداری می‌شوند.')
        self._paint()
        self.refresh()
        self.root.after(80, self.search.focus_set)

    def _paint(self):
        self.shell=tk.Frame(self.root,bg=SURFACE)
        self.shell.pack(fill='both',expand=True)
        self.brand=tk.Canvas(self.shell,width=333,highlightthickness=0,bd=0,bg=DEEP)
        self.brand.pack(side='left',fill='y')
        self.brand.bind('<Configure>',self._render_brand)

        self.page=tk.Frame(self.shell,bg=SURFACE)
        self.page.pack(side='right',fill='both',expand=True)
        header=tk.Frame(self.page,bg=SURFACE)
        header.pack(fill='x',padx=34,pady=(28,10))
        tk.Label(header,text='حسابداری مستقل مدار',font=(PERSIAN_FACE,11,'bold'),
                 bg=SURFACE,fg=INK,anchor='e').pack(side='right')
        tk.Label(header,text='LOCAL WORKSPACE  /  V1',font=('Segoe UI',8),
                 bg=SURFACE,fg=MUTED).pack(side='left')

        tk.Label(self.page,text='انتخاب محیط کار',font=(PERSIAN_FACE,23,'bold'),
                 bg=SURFACE,fg=INK,anchor='e').pack(fill='x',padx=34,pady=(20,5))
        tk.Label(self.page,text='شرکت موردنظر را انتخاب کنید یا دفتر جدیدی بسازید.',
                 font=(PERSIAN_FACE,10),bg=SURFACE,fg=MUTED,
                 anchor='e').pack(fill='x',padx=36)

        tk.Label(self.page,text='جست‌وجوی شرکت‌ها',font=(PERSIAN_FACE,9,'bold'),
                 bg=SURFACE,fg=INK,anchor='e').pack(fill='x',padx=36,pady=(22,5))
        search_frame=tk.Frame(self.page,bg=WHITE,highlightthickness=1,
                              highlightbackground=LINE)
        search_frame.pack(fill='x',padx=36)
        tk.Label(search_frame,text='⌕',font=('Segoe UI',18),bg=WHITE,fg=SEA
                 ).pack(side='right',padx=(10,17))
        self.search=tk.Entry(search_frame,textvariable=self.query,font=(PERSIAN_FACE,11),
                             bg=WHITE,fg=INK,bd=0,justify='right',
                             insertbackground=SEA)
        self.search.pack(side='right',fill='x',expand=True,pady=13)
        self.search.bind('<Return>',lambda _:self._confirm())
        self.query.trace_add('write',lambda *_:self._render_companies())

        info=tk.Frame(self.page,bg=SURFACE)
        info.pack(fill='x',padx=36,pady=(16,9))
        self.count_label=tk.Label(info,text='',font=(PERSIAN_FACE,9,'bold'),
                                  bg=SURFACE,fg=MUTED)
        self.count_label.pack(side='right')
        tk.Label(info,text='دفترهای ثبت‌شده',font=(PERSIAN_FACE,9),
                 bg=SURFACE,fg=INK).pack(side='right',padx=8)

        self.list_shell=tk.Frame(self.page,bg=WHITE,
                                 highlightthickness=1,highlightbackground=LINE)
        self.list_shell.pack(fill='both',expand=True,padx=36)
        self.list_canvas=tk.Canvas(self.list_shell,bg=WHITE,
                                   bd=0,highlightthickness=0)
        self.scroll=tk.Scrollbar(self.list_shell,orient='vertical',
                                 command=self.list_canvas.yview)
        self.list_canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y')
        self.list_canvas.pack(side='left',fill='both',expand=True)
        self.list_inside=tk.Frame(self.list_canvas,bg=WHITE)
        self.list_window=self.list_canvas.create_window((0,0),window=self.list_inside,
                                                        anchor='nw')
        self.list_inside.bind('<Configure>',self._scrollregion)
        self.list_canvas.bind('<Configure>',lambda e:self.list_canvas.itemconfigure(
            self.list_window,width=e.width))
        self.list_canvas.bind('<MouseWheel>',lambda e:self.list_canvas.yview_scroll(
            -int(e.delta/120),'units'))

        self.new_frame=tk.Frame(self.page,bg=SURFACE)
        self.new_frame.pack(fill='x',padx=36,pady=(12,0))
        self.new_entry=tk.Entry(self.new_frame,textvariable=self.company_name,
                                bg=WHITE,fg=INK,justify='right',font=(PERSIAN_FACE,11),
                                relief='solid',bd=1)
        self.new_entry.bind('<Return>',lambda _:self._create())
        self.new_entry.bind('<Escape>',lambda _:self._toggle_create(False))
        self.create_help=tk.Label(self.new_frame,text='نام شرکت، حداکثر ۱۲۰ نویسه',
                                  font=(PERSIAN_FACE,8),bg=SURFACE,fg=MUTED)

        self.footer=tk.Frame(self.page,bg=SURFACE)
        self.footer.pack(fill='x',padx=32,pady=(12,6))
        self.enter_btn=ActionButton(self.footer,'ورود به دفتر',self._confirm,
                                    primary=True,width=172)
        self.enter_btn.pack(side='right',padx=3)
        self.new_btn=ActionButton(self.footer,'+ شرکت جدید',self._toggle_create,
                                  width=138)
        self.new_btn.pack(side='right',padx=5)
        self.cancel_btn=ActionButton(self.footer,'انصراف',self.cancel,width=95)
        self.cancel_btn.pack(side='left')
        self.status_label=tk.Label(self.page,textvariable=self.status,
                                   font=(PERSIAN_FACE,8),bg=SURFACE,fg=MUTED,
                                   anchor='e',wraplength=530)
        self.status_label.pack(fill='x',padx=38,pady=(0,16))
        self.root.bind('<Escape>',lambda _:self.cancel() if not self.create_open
                       else self._toggle_create(False))
        self.root.bind('<F5>',lambda _:self.refresh())
        self.root.bind('<Down>',lambda _:self._move(1))
        self.root.bind('<Up>',lambda _:self._move(-1))
        self.root.bind('<Control-n>',lambda _:self._toggle_create(True))

    def _render_brand(self,_event=None):
        c=self.brand
        c.delete('all')
        w=max(333,c.winfo_width());h=max(575,c.winfo_height())
        c.create_rectangle(0,0,w,h,fill=DEEP,outline=DEEP)
        c.create_oval(-130,h-220,w+95,h+170,outline='#173E51',width=2)
        c.create_oval(-40,h-125,w+135,h+270,outline='#1B4C55',width=1)
        c.create_oval(w-115,60,w+175,345,outline='#214B62',width=2)
        rounded(c,27,44,87,104,17,fill=SEA)
        c.create_text(57,74,text='M',font=('Segoe UI',30,'bold'),fill=DEEP)
        c.create_text(w-32,145,text='M A D A R   /   D E S K',
                      font=('Segoe UI',12,'bold'),fill='#64CEC6',anchor='e')
        c.create_text(w-32,201,text='حسابداری،',font=(PERSIAN_FACE,24,'bold'),
                      fill=WHITE,anchor='e')
        c.create_text(w-32,247,text='با تمرکز بیشتر.',font=(PERSIAN_FACE,20,'bold'),
                      fill=WHITE,anchor='e')
        c.create_text(w-32,303,text='هر شرکت، اطلاعات و دفتر مستقل خودش را دارد.',
                      width=w-62,font=(PERSIAN_FACE,10),fill='#B5C8D4',anchor='e',justify='right')
        rounded(c,27,365,w-27,432,14,fill=MID,outline='#24536B')
        c.create_oval(w-65,382,w-45,402,fill=SEA,outline='')
        c.create_text(w-76,392,text='ورود رمزدار  •  نسخه آفلاین',
                      font=(PERSIAN_FACE,9,'bold'),fill=WHITE,anchor='e')
        c.create_text(w-32,h-53,text='PRIVATE  •  WINDOWS  •  OFFLINE',
                      font=('Segoe UI',9),fill='#7193A7',anchor='e')

    def _scrollregion(self,_=None):
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox('all'))

    def _render_companies(self):
        term=normalized_company_label(self.query.get().strip())
        self.visible=[company for company in self.current if term in normalized_company_label(company['name'])]
        self.count_label.configure(text=str(len(self.visible)))
        for child in self.list_inside.winfo_children():child.destroy()
        if not self.visible:
            empty=tk.Frame(self.list_inside,bg=WHITE)
            empty.pack(fill='both',expand=True,pady=(42,50))
            tk.Label(empty,text='◈',font=('Segoe UI',35),bg=WHITE,fg=SEA).pack()
            tk.Label(empty,text='هنوز شرکتی برای نمایش وجود ندارد' if not term else 'نتیجه‌ای پیدا نشد',
                     font=(PERSIAN_FACE,12,'bold'),bg=WHITE,fg=INK).pack(pady=(5,6))
            tk.Label(empty,text='با «شرکت جدید» اولین دفتر را بسازید.' if not term else 'نام شرکت را اصلاح کنید.',
                     font=(PERSIAN_FACE,9),bg=WHITE,fg=MUTED).pack()
        for i,company in enumerate(self.visible):
            chosen=self.selected==company['id']
            card=tk.Canvas(self.list_inside,height=71,bg=WHITE,
                           highlightthickness=0,bd=0,cursor='hand2')
            card.pack(fill='x',padx=12,pady=(10,0))
            card.bind('<Configure>',lambda _,widget=card,record=company,idx=i:
                      self._draw_card(widget,record,idx))
            card.bind('<Button-1>',lambda _,cid=company['id']:self._select(cid))
            card.bind('<Double-Button-1>',lambda _,cid=company['id']:
                      (self._select(cid),self._confirm()))
        self._scrollregion()
        self._update_buttons()

    def _draw_card(self,canvas,company,index):
        canvas.delete('all');w=max(100,canvas.winfo_width())
        chosen=self.selected==company['id']
        rounded(canvas,1,1,w-2,69,12,fill=SEA_LIGHT if chosen else SURFACE,
                outline=SEA if chosen else LINE,width=1 if not chosen else 2)
        rounded(canvas,w-55,13,w-13,55,12,fill=SEA if chosen else '#E4EDF3')
        canvas.create_text(w-34,34,text=company['name'][:1],
                           fill=DEEP if chosen else MID,font=(PERSIAN_FACE,17,'bold'))
        canvas.create_text(w-69,25,text=company['name'][:33],anchor='e',
                           fill=INK,font=(PERSIAN_FACE,10,'bold'))
        canvas.create_text(w-69,46,text='دفتر مالی مستقل  •  '+str(index+1),
                           anchor='e',fill=MUTED,font=(PERSIAN_FACE,8))
        canvas.create_text(24,35,text='✓' if chosen else '○',
                           fill=SEA if chosen else '#A9B9C5',font=('Segoe UI',18))

    def _update_buttons(self):
        self.enter_btn.set_disabled(not any(c['id']==self.selected for c in self.visible)
                                    or self.create_open)

    def _select(self,company_id):
        self.selected=company_id
        self._render_companies()

    def _move(self,direction):
        if self.create_open or not self.visible:
            return
        ids=[c['id'] for c in self.visible]
        start=ids.index(self.selected) if self.selected in ids else 0
        self._select(ids[max(0,min(len(ids)-1,start+direction))])

    def refresh(self,preferred=None):
        try:
            self.current=self.registry.list_companies()
        except Exception as exc:
            self.current=[]
            self.status.set('خواندن شرکت‌ها ناموفق بود: '+str(exc))
            messagebox.showerror('خطای دفتر شرکت‌ها',str(exc),parent=self.root)
        else:
            self.status.set('Enter: ورود   |   Ctrl+N: شرکت جدید   |   F5: بازخوانی   |   Esc: انصراف')
        ids=[c['id'] for c in self.current]
        if preferred in ids:self.selected=preferred
        elif self.selected not in ids:self.selected=ids[0] if ids else None
        self._render_companies()

    def _toggle_create(self,open_state=None):
        self.create_open=(not self.create_open if open_state is None else bool(open_state))
        for child in self.new_frame.winfo_children():child.pack_forget()
        if self.create_open:
            self.create_help.pack(side='right',padx=(8,0))
            self.new_entry.pack(side='right',fill='x',expand=True,pady=3)
            self.new_btn.label='ثبت شرکت'
            self.new_btn.action=self._create
            self.new_entry.focus_set()
        else:
            self.company_name.set('')
            self.new_btn.label='+ شرکت جدید'
            self.new_btn.action=self._toggle_create
            self.search.focus_set()
        self.new_btn.draw()
        self._update_buttons()

    def _create(self):
        name=self.company_name.get().strip()
        if not name:
            self.status.set('نام شرکت نمی‌تواند خالی باشد.')
            self.new_entry.focus_set()
            return
        try:
            company=self.registry.create_company(name)
        except Exception as exc:
            self.status.set('ساخت شرکت انجام نشد: '+str(exc))
            messagebox.showerror('ثبت شرکت ناموفق',str(exc),parent=self.root)
            return
        self._toggle_create(False)
        self.query.set('')
        self.refresh(company['id'])
        self.status.set('شرکت جدید ثبت شد. برای ورود، اعتبارسنجی رمز این شرکت انجام می‌شود.')

    def _confirm(self):
        if self.create_open:
            self._create();return
        if not self.selected or not any(c['id']==self.selected for c in self.visible):
            self.status.set('ابتدا یکی از شرکت‌های فهرست را انتخاب کنید.')
            return
        self.result=self.selected
        self.root.quit()

    def cancel(self):
        self.result=None
        self.root.quit()

    def run(self):
        self.result=None
        try:
            self.root.mainloop()
            if not self.result:return None
            company=next((c for c in self.registry.list_companies()
                          if c['id']==self.result),None)
            if not company:return None
            return {'name':company['name'],
                    'path':self.registry.company_data_directory(company['id'])}
        finally:
            self.root.destroy()


def pick_premium_company_dialog(registry):
    return PremiumCompanyChooser(registry).run()
