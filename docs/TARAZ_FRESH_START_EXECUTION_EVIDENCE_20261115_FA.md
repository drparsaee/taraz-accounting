# TARAZ-FRESH-START-01 | شواهد اجرای ۱۵ نوامبر ۲۰۲۶

**وضعیت نصب عملیاتی: NO-GO.** تراز نصب‌شده همچنان `1.0.4` است. سه ریشهٔ دادهٔ واقعی در این مأموریت جابه‌جا، حذف، بازنشانی یا جایگزین نشده‌اند.

## تصمیم کاربر

- دقیقاً یک شرکت تازهٔ متصل به هویت ویندوز با دفتر خالی؛ بدون Legacy Enrollment و رمز مستقل.
- عدم انتقال Ledger قدیمی و ۶۰۹ رویداد مالی به شرکت تازه.
- حفظ کامل داده‌ها و Backupهای قدیمی در آرشیوی مستقل و قابل‌بازیابی.
- نصب `1.0.6` روی همان مسیر نصب فقط بعد از عبور گیت‌ها، بدون Force Kill یا دورزدن محافظ مالی.

## منبع و بسته

- HEAD آغاز مأموریت: `575c891cc60fa523d1e83213544f7f37c2bcfc64`
- Fingerprint محاسبه‌شدهٔ منبع اجرایی: `f06c9727b72c54b2cbd166a60adf2b4b00ca96e58cdf73ba1085ecbe6aafb186`؛ ۱۵۷ فایل.
- EXE آزموده‌شده: `build-5eaec2d34649\binary\Taraz.exe`
- SHA-256 EXE: `d0dd7bace4039688cc18768b232bc36bccd5aa1933f4d59bcb253b352b2ac3f2`
- SHA-256 Manifest: `f46e4e29bc74e4d18348a249fbc583d075afe5f7bfa15aa758569b9c31baf2ca`
- کنترل نسخهٔ نصب‌شده: `%LOCALAPPDATA%\Programs\Taraz\current-version.txt` برابر `1.0.4`.

## آزمون واقعی EXE

- `fresh-windows-frozen-qa-20261115\qa-bf5543b489e3`: PASS فاکتور Draft، پیش‌فاکتور Draft، PDF Preview (۸۲٬۲۷۰ بایت)، یک سفارش Draft با تعداد ۱۰ و برنامهٔ تولید ۱۲، دو پیام چت، Provider غیرفعال، Journal صفر، خروج واقعی و Backup Guard.
- `fresh-windows-frozen-qa-20261115\qa-8c8f69a724b2`: اجرای اول Frozen PASS و سپس اجرای دوم **روی همان پروفایل**؛ `PASS_FROZEN_SAME_PROFILE_RESTART_DRAFT_ORDER_DPAPI_CHAT`، بازخوانی فاکتور و سفارش و دو پیام DPAPI، Revision ۳، Journal صفر، خروج و Backup Guard PASS.
- `qa-be2195cf1d03`: بررسی مستقل `taraz-orders.sqlite3` در SQLite read-only؛ `quick_check=ok` و یک سفارش Draft با تعداد ۱۰ و برنامهٔ تولید ۱۲.
- `qa-2e276a7dbe1d\private-pdf-saved\QA-FROZEN-RESTART-INVOICE.pdf`: **Save As واقعی پنجرهٔ ویندوز** به مسیر خصوصی QA، ۵۸٬۴۰۴ بایت، سربرگ و انتهای معتبر PDF، SHA-256: `9e352917499f47f9e3e3ed9566d64a32903b4817e6c3154a518fce3b02296375`. هشدار «Location is not available» دربارهٔ مسیر پیش‌فرض ایزوله ثبت، سپس با انتخاب مسیر خصوصی صحیح برطرف شد. خروج همان EXE بعد از درخواست معتبر Close از گیت مالی واقعی عبور کرد؛ `exit-proof.json` برابر `VERIFIED_NATIVE_CLOSE_AND_BACKUP`. **محدودیت:** Harness ترکیبی PDF به دلیل بازبودن Save As، `BLOCKED_UI_TEST_TIMEOUT` ثبت کرد. ادعای PASS برای *کل همان Harness* نادرست است؛ شواهد Save As و خروج مستقل بررسی شدند.

## Backup و Rollback واقعی روی Clone

- Snapshot واقعی سه‌ریشه‌ای: `D:\CoS-Test\TARAZ-FRESH-START-BACKUP-20261115-A\snapshot`.
- تأیید Snapshot/Restore: ۶۷ SQLite، ۸۵ جدول، ۲۵٬۷۴۵ ردیف؛ DPAPI فقط برای همان Windows Principal.
- آزمون Clone: `D:\CoS-Test\TARAZ-FRESH-START-ROLLBACK-QA-20261115\qa-16227ce8e446\fresh-reset-rollback-evidence.json`.
- نتیجه: `PASS_VERIFIED_FRESH_DATA_RESET_EXE_INSTALL_AND_FULL_ROLLBACK_CLONE`؛ ایجاد شرکت تازهٔ Windows-bound با Revision صفر، نصب/فعال‌سازی `1.0.6` در Clone، سپس Rollback نسخه و تمام سه ریشه به `1.0.4`. دادهٔ تاریخی و ۶۰۹ رویداد بعد از Rollback در Clone بازیابی شدند؛ در شرکت جدید مهاجرت نشدند.
- **محدودیت Backup:** Snapshot سه‌ریشه‌ای، اتمیک VSS نیست؛ نبود تمام Writerهای Create/Delete و بازیابی DPAPI روی دستگاه دیگر اثبات نشده است.

## گیت‌های باز

1. پردازش‌های قدیمی `37456` و `26844` متعلق به EXE آزمایشی قدیمیِ ایزوله با SHA `d4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305` هنوز هنگام بازخوانی فعال بودند؛ پنجرهٔ واقعی هشدار می‌دهد «عملیات مالی هنوز در حال انجام است». بستن اجباری یا دورزدن JS/Native Financial Close Guard ممنوع است. این پیام، به‌تنهایی، اثبات انجام یک تراکنش مالی زنده نیست، اما گیت خروج عادی را مسدود کرده است.
2. بستهٔ Installer/Activate موجود عمداً `Production -Apply` را قفل می‌کند (`installApplyAllowed=false` و `activateApplyAllowed=false`). آزمون Clone با `-Rehearsal` به معنی مجوز یا موفقیت نصب Production نیست.
3. پیش از هر جابه‌جایی عملیاتی: بررسی دوبارهٔ Writerها، تطبیق تازه‌بودن Snapshot، اثبات Rollback در بستهٔ آمادهٔ Production، و پذیرش نصب در همان مسیر لازم است.
4. شکست `BLOCKED_UI_TEST_TIMEOUT` در Harness خودکار PDF باید جدا از تأیید دستی/خودکارِ مسیر واقعی Save As گزارش شود؛ نباید در آمار PASS ترکیبی پنهان شود.

**ممنوعیت‌ها در اجرای ثبت‌شده رعایت شده‌اند:** Force Kill، حذف غیرقابل‌بازیابی، مهاجرت ۶۰۹ رویداد، Push، نصب عملیاتی و دست‌کاری ریشه‌های واقعی انجام نشدند.
