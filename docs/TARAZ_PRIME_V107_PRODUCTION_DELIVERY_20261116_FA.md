# TARAZ PRIME — تحویل Hotfix واقعی 1.0.7

**تاریخ:** 2026-11-16

**دامنه:** نصب محافظت‌شده 1.0.6 → 1.0.7 روی همان شرکت تازه؛ بدون Reset، مهاجرت حسابداری یا ثبت سند.
**وضعیت:** `PASS` برای ارتقای Production و آزمون‌های مشخص‌شده در پایین؛ ادعای اجرای LLM یا Rollback واقعی Production وجود ندارد.

## ۱. مرجع نصب

| شاهد | نتیجه |
|---|---|
| HEAD پیش از ثبت تغییرات این تحویل | `4b7b5da6a7b9ffaa493a119a5667f8330a33d569` |
| نسخه قبل از نصب | `1.0.6` |
| SHA-256 فایل اجرایی قدیمی، حفظ‌شده | `d0dd7bace4039688cc18768b232bc36bccd5aa1933f4d59bcb253b352b2ac3f2` |
| نسخه نصب‌شده و فعال‌شده | `1.0.7` |
| SHA-256 فایل اجرایی جدید، مستقل از خروجی Installer بازخوانی شد | `83a47d228d111b7ac8c4eff73ce0948a8b8517ae5e95bf0646bb5969fed0ba9b` |
| SHA-256 اشاره‌گر جدید | `e447e3cbb32090cef7308408954892b2e1aab1db7c4ade17ecc4536efb5a0b65` |
| SHA-256 نسخه پشتیبان اشاره‌گر 1.0.6 | `3dd81e3d2bbe930a0c98531afa6c35bd862ee8a08458ec0d7d1b51138d7b3a3c` |
| SHA-256 لانچر بدون تغییر | `93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21` |

برنامه از `%LOCALAPPDATA%\Programs\Taraz\versions\1.0.7\Taraz.exe` اجرا شد. اجرای مجدد از `Run-Taraz.cmd` نیز دو Process از نسخه `1.0.7` و پنجره «تراز | حسابداری» را تولید کرد. نسخه قبلی در پوشه `versions\1.0.6` باقی است.

## ۲. رفع مانع پشتیبان‌گیری

اجرای اول Backup در مسیر `D:\CoS-Test\TARAZ-V107-HOTFIX-BACKUP-20261116-A` به‌درستی و بدون نصب متوقف شد: یک Backup خودکار تاریخ 2026-11-16 هدر SQLite متفاوت از Manifest داشت.

- فقط بایت‌های 27 و 95 در فایل `standalone-accounting-auto-20261116T081947672608Z-52ae1359a84b3032.sqlite3` متفاوت بودند.
- SQLite `integrity_check=ok` و جدول تاریخی آن صفر ردیف داشت.
- نسخه مورد انتظار با بازیابی دو بایت در حافظه، به‌صورت دقیق SHA اصلی Manifest `f9f78bf35580e9d87499ef76d5ffd58e5607991041bbca3bd458370a182d66cb` را بازتولید کرد.
- اصل فایل متفاوت با SHA `d52eb6587366490d9d37f1c2a044e4b2832c98b02015cc9ecd928fa65f079c0c` همراه با Manifest و فایل شاهد سالم، **پیش از اصلاح** در پوشه جداگانه زیر حفظ شد:
  `D:\CoS-Test\TARAZ-V107-ARCHIVE-HEADER-RECOVERY-20261116-A`
- فقط همان دو بایت فایل Backup خودکار قدیمی اصلاح شدند. Manifest اصلی و دفتر فعال دست‌نخورده ماندند. بازخوانی مستقل Manifest بعد از اصلاح PASS شد.
- پوشه شکست‌خورده A حذف یا بازنویسی نشده است.

## ۳. Backup واقعی قبل از نصب

مقصد جدید و create-only:

`D:\CoS-Test\TARAZ-V107-HOTFIX-BACKUP-20261116-B`

گزارش `verification.json`:

- `VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE`
- ۷۷ فایل Snapshot، ۲۴ پایگاه SQLite، ۲۴ جدول، صفر ردیف
- ۷۹ عضو در inventory اولیه، شامل sidecarهایی که طبق قرارداد snapshot نهایی نیستند
- آزمون مستقل بازیابی و مقایسه محتوا PASS
- بازخوانی DPAPI با همان حساب Windows: PASS
- قفل‌های جلوگیری از نوشتن روی اعضای اصلی هنگام Backup برقرار بودند
- `crossRootAtomicVssSnapshot=false`؛ بازیابی روی دستگاه یا حساب ویندوز دیگر تأیید نشده است

Preflight پس از Backup: `PASS_PROTECTED_V107_PREFLIGHT`، بدون Issue.

## ۴. نصب Production

اجرای `--apply` محافظت‌شده:

`PASS_V107_PRODUCTION_BINARY_ONLY_UPDATE`

همراه با `dataMigration=false` و `dataRootsUnchanged=true`. نسخه قبلی، اشاره‌گر قبلی و لاگ تراکنشی در مسیر زیر حفظ شدند:

`D:\CoS-Test\TARAZ-V107-HOTFIX-PRODUCTION-20261116-A`

فایل‌های `000.json` تا `003.json` به ترتیب PREPARED، EXE_INSTALLED_NOT_ACTIVATED، ACTIVATED و DATA_UNCHANGED را ثبت می‌کنند. پس از نصب، SHA فایل‌های قدیم/جدید، Launcher و هر دو Pointer مستقل از Installer بازخوانی شدند.

## ۵. پذیرش نسخه نصب‌شده

- پنجره واقعی `1.0.7` ظاهر شد و صفحه اصلی دفتر تازه و نشانگر `windows_local` دیده شدند.
- در تصاویر بررسی‌شده هشدار «دریافت سوابق تاریخی ناموفق بود» یا Legacy Enrollment مشاهده نشد.
- نمای دستیار تجاری نمایش داده شد. provider مدل زبانی طبق Frozen QA همچنان `DISABLED_BY_POLICY` بود؛ اجرای LLM ادعا نمی‌شود.
- صفر موجودی، صفر فاکتور و نبود داده مهاجرتی روی نمای نصب‌شده دیده شد.
- خروج از پنجره اصلی با `CloseMainWindow` موفق بود؛ فرایندهای Taraz کاملاً خارج شدند.
- Backup خودکار بعد از خروج با نام `standalone-accounting-auto-20261116T101459168063Z-6c86284d7dfc26f3.sqlite3` ساخته و Manifest آن مستقل تأیید شد؛ `integrity_check=ok`، تعداد ردیف دفتر فعال و آرشیو جدید صفر.
- سپس نسخه `1.0.7` دوباره از **Launcher رسمی** شروع شد و مسیر اجرایی Processهای تازه و عنوان پنجره بازخوانی شدند.
- تصویرها در پوشه لاگ نصب: `installed-v107-ui.png`، `installed-v107-assistant.png` و `installed-v107-home-after-navigation.png`.

**حد پوشش:** فاکتور/پیش‌فاکتور، سفارش، قالب چاپ، PDF و persistence چت قبلاً روی Frozen EXE ایزوله با گزارش `PASS_V107_FROZEN_HOME_INVOICE_PROFORMA_ORDER_CHAT_PDF_BACKUP` قبول شده‌اند. در نصب Production روی داده واقعی کاربر سند آزمایشی ایجاد نشد. عکس گرفتن از رابط هم اثبات نمی‌کند هیچ هشدار تأخیری در تمام آینده ممکن نیست.

## ۶. آزمون‌ها و Rollback

| پوشش | نتیجه |
|---|---|
| ۱۹ آزمون Backup نسخه موجود | PASS |
| تست JavaScript خانه تازه و Legacy | PASS، ۱ مورد |
| تست‌های جدید محافظ آرشیو | PASS، ۳ مورد |
| Frozen E2E قبلی | PASS، محیط ایزوله |
| Package Clone نصب/فعال‌سازی/بازگشت | PASS، محیط ایزوله |
| Protected Updater Clone اولیه | PASS، محیط ایزوله |
| Rollback جدید پس از تغییر داده Clone | `PASS_V107_POSTSTART_CLONE_ROLLBACK_NEW_DATA_PRESERVED` |
| نصب واقعی 1.0.7 و SHA readback | PASS |
| خروج واقعی و Backup Guard | PASS |
| Rollback واقعی Production | **اجرا نشد؛ ادعای PASS ندارد** |

برای اصلاح مشکل قبلی Rollback که با ساخته‌شدن Backupهای جدید بعد از اولین اجرای 1.0.7 مسدود می‌شد، Rollback محافظت‌شده اکنون پیش از تغییر Pointer **Backup تازه سه ریشه + Restore مستقل + DPAPI و تطبیق داده زنده** می‌گیرد و هیچ‌وقت Snapshot قدیمی را روی اطلاعات جدید بازنویسی نمی‌کند. در Clone مستقل، فایل افزوده‌شده پس از نصب حفظ شد و Pointer به `1.0.6` برگشت؛ نصب اصلی تغییر نکرد:

`D:\CoS-Test\TARAZ-V107-ROLLBACK-POSTSTART-CLONE-QA-20261116-A\qa-poststart-rollback.json`

این Clone با مسیرهای دیتای ایزوله و حذف بررسی Process فقط در همان فرآیند QA تست شد، زیرا Taraz Production باز بود؛ این حذف در اسکریپت تولیدی وجود ندارد.

## ۷. محدودیت‌ها و مرزبندی

- Rollback به نسخه 1.0.6 روی داده‌هایی که در آینده از قابلیت‌های خاص 1.0.7 تولید می‌شوند، پذیرش سازگاری کامل Runtime ندارد؛ با وجود Backup جدید، همچنان باید در اولین تغییر معنادار Schema جداگانه آزموده شود.
- Backup سه ریشه VSS اتمیک نیست. یک نویسنده غیرهمکار با الگوی create/delete گذرا مطلقاً قابل رد نیست.
- DPAPI فقط روی همان Principal تأیید شد؛ انتقال به ویندوز دیگر اثبات نشده است.
- هیچ سند مالی واقعی تولید یا Post نشد.
- مدل LLM فعال نشده و ارتباط کامل عملیاتی Taraz–Madar/Radar جزو این Hotfix نبوده است.
- ماتریس موجود ۱۳۵ ایدهٔ Taraz/Madar/Radar تغییر نکرد و تحقیق مجدد انجام نشد.
- این Hotfix ارتباطی با انتشار Pack P.O.C. Studio ندارد.
