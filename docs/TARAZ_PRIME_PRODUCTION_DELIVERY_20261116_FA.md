# TARAZ PRIME | شاهد انتشار عملیاتی ۱۶ نوامبر ۲۰۲۶

این سند رخدادهای واقعی را از یافته‌های Clone، سورس و موارد تأییدنشده تفکیک می‌کند.

## ۱. نسخهٔ واقعی

- در ابتدای اجرای مأموریت، نسخهٔ نصب‌شده `1.0.4` بود.
- `build-5eaec2d34649` نسخهٔ `1.0.6` با SHA-256 برابر
  `d0dd7bace4039688cc18768b232bc36bccd5aa1933f4d59bcb253b352b2ac3f2` نصب و درجا فعال شد.
- پس از نصب، `%LOCALAPPDATA%\Programs\Taraz\current-version.txt` مقدار `1.0.6` داشت.
- فایل نصب‌شده `versions\1.0.6\Taraz.exe` مستقلاً Hash شد و با Build تطبیق داشت.
- `versions\1.0.4\Taraz.exe` با Hash قبلی
  `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` نگه داشته شد.

## ۲. Fresh Start

- فقط یک شرکت تازه با هویت `windows_local` و نقش Admin ثبت شد.
- خروجی مستقیم `inspect_fresh_workspace`: `mode=windows-local-fresh`، `windowsPrincipalBound=true` و `ledgerRevision=0`.
- ۶۰۹ رویداد قدیمی به دفتر جدید منتقل نشد.
- GUI نصب‌شده با دو پردازش واقعی `Taraz.exe` و عنوان `تراز | حسابداری` باز شد.
- تصویر مستقیم صفحه: `D:\CoS-Test\TARAZ-PRIME-FRESH-PRODUCTION-20261116\installed-ui-screen-20261116.png`.
- در تصویر ورود، فرم Legacy Enrollment دیده نشد و دکمهٔ «فاکتور جدید» و مسیرهای فروش/سفارش‌ها/دستیار تراز دیده شدند. آزمون کلیک روی هر بخش در پروفایل عملیاتی اجرا نشده است.

## ۳. Backup، آرشیو و بازگشت

- Backup مقدماتی واقعی: `D:\CoS-Test\TARAZ-FRESH-START-FINAL-BACKUP-20261116-A\snapshot`.
- نتیجهٔ قبلی آن: ۶۷ SQLite، ۸۵ جدول، ۲۵٬۷۴۵ ردیف، DPAPI فقط روی همان Windows Principal.
- درست پیش از نصب، مطابقت تمام سه ریشهٔ فعال با Snapshot از لحاظ ساختار و Hash فایل‌های غیر-SQLite و محتوای منطقی SQLite دوباره بررسی شد.
- آرشیو پس از نصب در سه پوشهٔ `Taraz-legacy-retained-20261116` زیر Roaming و Local و `Madar-Taraz-Bridge-legacy-retained-20261116` زیر Local حفظ شد؛ مطابقت سه پوشهٔ آرشیوی با Snapshot پس از نصب تأیید شد.
- پوشهٔ Bridge قدیمی چهار عضو شامل pending/reviewed/send-intents داشت؛ صرفاً به آرشیو منتقل شد، نه به دفتر مالی جدید. هیچ فایل داخلی نصب/دادهٔ اصلی MadarDesk جابه‌جا نشد، اما وابستگی‌های عملیاتی به پیام‌های قدیمی Bridge پس از ازسرگیری مدار جداگانه تأیید نشده‌اند.
- `TARAZ-PRIME-CLONE-20261116\qa-2e7807644380`: `PASS_VERIFIED_FRESH_DATA_RESET_EXE_INSTALL_AND_FULL_ROLLBACK_CLONE` با همان Backup.
- `TARAZ-PRIME-PROTECTED-APPLY-QA-20261116\qa-135627d8f15e`: `PASS_NEW_PRODUCTION_DRIVER_CLONE_APPLY_ROLLBACK`.
- `TARAZ-PRIME-PROTECTED-APPLY-QA-20261116\qa-69af3e5b9c0f`: بازیابی موفق از قطع فرضی نصب در مرحلهٔ ۵، بدون Force Kill.
- `TARAZ-PRIME-FRESH-PRODUCTION-20261116\000.json` تا `006.json`: Journal محافظت‌شدهٔ نصب Production.
- خروج عادی Native برنامهٔ واقعی انجام و دو پردازش آن متوقف شدند. Backup خودکار جدید با Manifest معتبر، Hash درست و SQLite معتبر بررسی شد؛ تعداد رویدادها صفر بود.
- **Rollback Production عمداً اجرا نشده است.** Rollback کامل EXE/Data فقط روی Clone آزموده شد. آرشیو و فایل اجرایی قدیمی برای استفاده در Recovery حفظ شده‌اند.
- **محدودیت واقعی:** اتمیک بودن VSS هم‌زمان در سه ریشه و Restore روی Windows Principal دیگر اثبات نشده است. نبود همهٔ Writerهای گذرا نیز اثبات مطلق ندارد.

## ۴. قابلیت‌های قابل استفاده / محدود

- فاکتور و پیش‌فاکتور Draft، سفارش Draft، طراحی قالب چاپ و PDF و تاریخچهٔ Chat در Frozen EXE از شواهد قبلی پذیرش شده‌اند؛ این آزمون‌ها نباید به‌عنوان تکرار شده در نسخهٔ نصب‌شده گزارش شوند.
- نسخهٔ نصب‌شده با UI عملیاتی اجرا شد؛ مسیرهای اصلی قابل مشاهده بودند. راهنمای دقیق دسترسی: `docs/TARAZ_V106_VISIBLE_FEATURES_20261116_FA.md`.
- Provider هوش مصنوعی در آزمون Frozen غیرفعال بود؛ هیچ ادعای فعال بودن مدل یا ثبت مالی خودکار وجود ندارد.
- CRM رادار در مدار مستقل باقی مانده؛ همهٔ قابلیت‌های آن در نسخهٔ نصب‌شدهٔ تراز قرار ندارند.

## ۵. ایراد UI مشاهده‌شده در نسخهٔ نصب‌شده

- صفحهٔ خانه در شروع دفتر صفر، هشدار `دریافت سوابق تاریخی ناموفق بود: Unverified personal accounting ledger` نشان داد.
- علت در `src/taraz_home_command.jsx`: خواندن بی‌قیدوشرط تاریخچهٔ پارسیان توسط رابط کاربری قدیمی.
- Backend در `taraz_desktop.py::_source_guard` به‌درستی اجازهٔ خواندن آرشیو منبع شخصی از دفتر تازه را رد می‌کند. این گیت نباید دور زده شود.
- اصلاح در **سورس پس از بسته‌شدن Build نصب‌شده** انجام شده و فعلاً فقط در سورس و آزمون است: Flag از مسیر احرازشدهٔ Windows-bound به UI می‌رسد و تاریخچهٔ Legacy در دفتر تازه درخواست نمی‌شود.
- آزمون Python برای عدم تضعیف گیت و آزمون Browser برای صفر بودن آمار دفتر و صفر بودن فراخوانی Legacy: PASS.
- **این اصلاح هنوز در فایل اجرایی نصب‌شدهٔ SHA بالا نیست.** تنها پس از Build جدید، Clone QA و نصب کنترل‌شده می‌توان هشدار را از لحاظ نسخهٔ نصب‌شده «رفع‌شده» اعلام کرد.

## ۶. ماتریس ۱۳۵ ایده و ۱۸ بسته

- فایل HTML و نوت‌های نسخه‌های ۱.۴ و ۱.۲۸ در مخزن مدار با Commit مستقل حفظ شده‌اند.
- ماتریس کامل و CSV و ممیزی بسته‌ها در `D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107\docs\modernization` قرار دارند.
- شمارش ایده‌ها: `VERIFIED_IMPLEMENTED=0`، `PARTIAL_IMPLEMENTATION=19`، `SOURCE_ONLY=22`، `PLANNED=10`، `BLOCKED=2`، `NOT_VERIFIED=82`.
- C-IDها انتساب معنایی پیشنهادی‌اند، نه نقشهٔ ایده‌به‌بستهٔ تصویب‌شده. وجود فایل و حتی موفقیت تست در Clone، تکمیل ایده در نسخهٔ نصب‌شده نیست.

## ۷. مسیر بعدی

1. P1 UX Hotfix: Build جدید از سورس محافظت‌شده و رفع هشدار پارسیان در دفتر تازه، همراه با تمام تست‌های Frozen روی همان Binary؛ بدون بازنویسی فایل فعلی.
2. P6/P7: آزمون واقعی متصلِ دو برنامه در محیط کنترل‌شده، Backup-guard failure injection، Restore روی دستگاه/Principal دیگر فقط در صورت تعریف راهکار DPAPI امن.
3. P2/D1/P3/P4/P5: پذیرش مستقل سفارش، لایهٔ داده، Provider، اتصال Madar و CRM Radar طبق ماتریس.

هیچ درصد پیشرفت بدون مخرج و وزن مصوب محاسبه نشده است.
