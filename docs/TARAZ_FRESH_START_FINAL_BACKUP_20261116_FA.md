# TARAZ-FRESH-START-01 | شواهد ادامهٔ ۱۶ نوامبر ۲۰۲۶

## وضعیت اجرایی

**Production Install: NO-GO.** نسخهٔ واقعی نصب‌شده در آغاز و پایان
این بررسی همچنان 1.0.4 بود؛ هیچ یک از سه ریشهٔ داده منتقل یا حذف نشد،
هیچ Installer روی نصب اصلی Apply نشد.

## Backup واقعی تازه

مسیر:

`D:\CoS-Test\TARAZ-FRESH-START-FINAL-BACKUP-20261116-A`

اسکریپت واقعی
`scripts/taraz_live_three_root_backup_20261114.py`
روی همان Windows Principal اجرا شد و گزارش زیر را برگرداند:

- وضعیت: `VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE`
- فایل‌های منبع: 181، مجموع 124011875 بایت
- اعضای Snapshot: 179، شامل 67 فایل SQLite
- تطبیق مستقل پس از Restore: 67 دیتابیس، 85 جدول، 25745 ردیف
- نگه‌داری Handleهای جلوگیری از نوشتن روی فایل‌های داده: True
- نسخهٔ نصب‌شدهٔ اصلی تغییر نکرده: True
- اتمیک بودن Snapshot سه‌ریشه‌ای با VSS: False
- حذف همهٔ Writerهای Create/Delete مقطعی: **اثبات‌نشده**
- بازیابی زیر Principal/دستگاه دیگر: **اثبات‌نشده**

## پردازش‌های قدیمی QA

دو پردازش با PIDهای 37456 (Parent) و 26844 (Child) در بازخوانی زنده بودند.
هر دو فایل `build-5e5253cd7449/binary/Taraz.exe` را اجرا می‌کنند؛
SHA-256 دقیق:
`d4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305`

محیط هر دو دارای `TARAZ_QA_MODE=1` بود و ریشه‌های APPDATA،
LOCALAPPDATA و دادهٔ دفتر به `fresh-windows-frozen-qa-20261115\qa-3443357975f2`
در مسیر آزمایشی اشاره داشتند، نه پوشه‌های فعال واقعی.
Handleهای دیده‌شدهٔ آن‌ها به پروفایل آزمایشی اشاره کردند.

اسکریپت هدفمند فقط‌خواندنی
`scripts/qa_taraz_old_fresh_private_alert_20261116.py`
روی همان Win32 Desktop و همان PIDها اجرا شد:
`READONLY_PRIVATE_QA_ALERT_INSPECTED`. متن هشدار
«عملیات مالی هنوز در حال انجام است» یک‌بار پیدا شد، ولی دکمهٔ
تأیید با مالکیت یکتا در UI Automation دیده نشد:
`matchedExactAlert=false`. هیچ کلیک، SendInput، Force Kill یا
دورزدن محافظ خروج انجام نشد.

## کنترل Writerها

در یک اسکن مکمل، اطلاعات فایل‌های بازِ 395 پردازش بررسی شد؛
برای 16 پردازش دسترسی ممکن نبود. در فایل‌های بازِ قابل مشاهده،
هیچ Handle داخل سه ریشهٔ زندهٔ تراز پیدا نشد. این شاهدِ مکمل
اثبات مطلق نبودن Writerهای غیرقابل مشاهده نیست.

## مانع نصب

کاندیدای `build-5eaec2d34649` دارای Manifest با
`installApplyAllowed=false` و `activateApplyAllowed=false` است.
QA روی Clone نصب/Activation/Rollback را PASS گزارش کرده است،
اما آن گزارش اجازهٔ Production Apply نیست. هیچ Manifest یا
دستور نصب برای دورزدن این قفل تغییر نکرد.

## گام فنی بعدی

استقرار واقعی باید با Installer اختصاصی Fresh Start و گیت مستقلی
که شواهد Backup، Writerها، Clone Rollback، عدم تداخل Madar Bridge و
رفتار خروج واقعی را بررسی کند، مجاز شود. از پرچم Rehearsal روی
دادهٔ عملیاتی یا از Force Kill نباید استفاده کرد.
