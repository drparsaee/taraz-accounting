# تراز ۱.۰.۴ — ماتریس پذیرش انتشار P0/P1

تاریخ: ۲۰۲۶-۱۱-۱۱. **وضعیت فعلی: نسخهٔ ۱.۰.۴ RC3 طبق دستور جدیدتر کاربر برای تست شخصی، کنار نسخهٔ ۱.۰.۲ نصب و فعال شد. پذیرش عملیاتی/انتشار عمومی همچنان NO_GO است.** `PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED` نام وضعیت immutable زمان ساخت است، نه وضعیت نصب پس از این رویداد.

## آخرین رویداد: نصب و فعال‌سازی آزمایشی روی سیستم کاربر

کاربر صریحاً اعلام کرد حسابداری قدیمی هنوز سامانهٔ اصلی است و مهاجرت نکرده و نصب سریع ۱.۰.۴ را برای تست شخصی خواست. در نتیجه دستور قبلیِ عدم اجرای `-Apply` روی نصب فعلی، **فقط برای همین نصب و فعال‌سازی آزمایشی** با مجوز جدیدتر جایگزین شد؛ این رویداد مجوز انتشار عمومی، مهاجرت یا عملیات مالی واقعی محسوب نمی‌شود.

- قبل از نصب: `current-version.txt=1.0.2`، نسخهٔ `versions/1.0.4` موجود نبود؛ `Taraz.exe` درحال اجرا: صفر. پیش‌بررسی installer با backup SHA-pinned برگشت `READY_FOR_CREATE_ONLY_1.0.4_INSTALL` و exit0.
- اجرای installer اصلی با `-Apply`: `INSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2` و exit0؛ SHA فایل نصب جدید `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce`.
- پیش‌بررسی activator: `READY_TO_ACTIVATE_1.0.4_OLD_VERSION_RETAINED` و exit0؛ اجرای activator رسمی `-Apply`: `ACTIVATED_1.0.4_VERSION_1.0.2_RETAINED` و exit0.
- **بازخوانی مستقیم پس از activation:** `current-version.txt=1.0.4`، backup pointer `current-version-pre-1.0.4.txt=1.0.2`، فایل اصلی و backup launcher هر دو SHA `93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21`؛ فایل `versions/1.0.2/Taraz.exe` SHA `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` دست‌نخورده، `versions/1.0.4/Taraz.exe` SHA دقیق RC3؛ هیچ پردازش Taraz در لحظهٔ readback فعال نبود.
- مسیر اجرای نسخهٔ فعال: `%LOCALAPPDATA%\Programs\Taraz\Run-Taraz.cmd`. ابزار بازگشت اختصاصی و مستقل: `...\taraz-v1.0.4-p1\rollback-gate-38a3fb5dbb19\Rollback-Taraz-V104-To-V102.ps1`، با preflight بدون `-Apply`؛ اجرای rollback روی نصب اصلی **در این مرحله صورت نگرفته است**.
- هیچ مهاجرت دیتابیس، ثبت سند، اجرا/تست تعاملی نسخهٔ نصب‌شده یا اعلان موفقیت مالی انجام نشد. موفقیت نصب و pointer صرفاً **آمادگی تست کاربری** را ثابت می‌کند. گزارش زمان ساخت و manifest immutable تغییر نکردند و همچنان نشان‌دهندهٔ وضعیت همان لحظهٔ ساخت هستند.

سطرهای پایین که می‌گویند نسخهٔ فعال `1.0.2` و نصب/فعال‌سازی واقعی ممنوع است، **سوابق تاریخی پیش از این رویدادند**؛ این بخش وضعیت جدیدتر و معتبر را ثبت می‌کند.

## تصمیم نهایی این مرحله: RC3، پس از بسته‌شدن گیت‌های بسته‌بندی و rollback

**ارزیابی به‌روزشده در ۲۰۲۶-۱۱-۱۱:** کاندیدای RC3 واقعاً ساخته شده است؛ پذیرش مستقل باینری/ZIP و نصب و فعال‌سازی **فقط در محیط disposable** موفق بوده؛ rollback پین‌شدهٔ **واقعی RC3 → 1.0.2** در محیط disposable موفق بوده؛ فایل اجرایی واقعی RC3 در یک desktop خصوصی **فقط راه‌اندازی اولیه** شده است. **انتشار عملیاتی و نصب اصلی همچنان `NO_GO` هستند.** سطرهای تاریخی RC1، RC2 و وضعیت «در انتظار ساخت RC3» در بخش‌های پایین گزارش، سوابق همان مراحل‌اند، نه وضعیت کنونی.

مسیر immutable کاندیدای RC3: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99`.

| شاهد RC3 | SHA-256 حاصل از بازخوانی مستقیم فایل |
|---|---|
| `binary\Taraz.exe`، 17,056,810 بایت | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| `Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip`، 16,801,376 بایت | `1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e` |
| `offline-update\update-manifest.json` | `b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6` |
| `build-report.json` | `510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb` |
| `offline-update\Install-Taraz-V104.ps1` | `6dda4897c1ce4da9120d3e6fda9c639834080f838602de02e32eea46c3de6a68` |
| `offline-update\Activate-Taraz-V104.ps1` | `3d7cb9aea21e54864fd8215ee686c48245c1b76f032afefe455c6782f3957937` |

ساخت از snapshot منبع ۱۳۱ فایلی با fingerprint `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` انجام شده است. آزمون مستقل worker29 نسخهٔ PE=`1.0.4.0`، PYZ=`1.0.4`، `QA_ONLY=False`، هر ۱۵ asset داخلی EXE و هر هفت عضو ZIP را بررسی کرد؛ JavaScript استخراج‌شده از EXE SHA=`3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` است. بازخوانی مستقیم `build-report.json`: `releaseApproved=false` و `status=PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED`. امضای Windows Authenticode در بازخوانی مستقیم: **`NotSigned`**.

| گیت | نتیجهٔ گزارش‌شده با شاهد قابل مراجعه | حد اعتبار |
|---|---|---|
| RC3 source structural و Vite Edge | ۱۰/۱۰ و ۱۴/۱۴ PASS | stage و backend ساختگی، نه EXE واقعی |
| RC3 compiled Edge | **۱۵/۱۵ PASS**، `docs/TARAZ_V104_RC3_COMPILED_EDGE_20261111.md` | JavaScript واقعاً استخراج‌شده از EXE؛ backend ساختگی |
| Native Windows PS5.1 installer/activator | **۲۰/۲۰ PASS** در گزارش worker26، `docs/TARAZ_V104_P1_SECURE_RC2_20261111.md` | نصب/فعال‌سازی روی پروفایل disposable، بدون نصب اصلی |
| Independent RC3 acceptance | **۱۹/۱۹ PASS**، `docs/TARAZ_V104_RC3_INDEPENDENT_ACCEPTANCE_20261111.md` | PE/PYZ، سورس، ۱۵ asset، هفت عضو ZIP، بکاپ ۱۸۱ فایلی و تست مستقل نصب disposable |
| RC3 operator rollback | **۲۸/۲۸ PASS**، `docs/TARAZ_V104_ROLLBACK_20261111.md` | اجرای همان PS1 پین‌شده بر کپی واقعی RC3/v102 در نصب شبیه‌سازی‌شده |
| Native private GUI | **۱۰/۱۰ unit PASS** و native `PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY`، `docs/TARAZ_V104_RC3_PRIVATE_NATIVE_GUI_20261111.md` | اجرای واقعی EXE روی desktop غیرورودی، ۶ WebView2 و مشاهدهٔ read-only؛ بدون navigation/تراکنش |

### rollback پین‌شدهٔ RC3

خروجی جدید create-only در `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\rollback-gate-38a3fb5dbb19` ایجاد شده است. بازخوانی مستقیم prime: `Rollback-Taraz-V104-To-V102.ps1` SHA=`fa1c3216c59b9f98b0603255c388831ac75c1e4e37032055369f7edda6b31922` و `rollback-gate-manifest.json` SHA=`053fbea99e9a9441c73ff5131185b890f0ba6b044afa1922b1b80ae1b8f91dec`. manifest: `fromVersion=1.0.4`، `toVersion=1.0.2`، `requiresApply=true`، `productionTouched=false` و `rollbackExecuted=false`. این آخرین فیلد فقط به تولید و **عدم اجرای روی production** اشاره دارد؛ اجرای مثبت rollback در مسیر موقت در گزارش مستقل ۲۸/۲۸ ثبت است. rollback فقط pointer را تغییر می‌دهد و باینری‌ها را حذف/بازنویسی نمی‌کند.

### وضعیت production و موارد باز

- بازخوانی مستقیم نسخهٔ فعال: `%LOCALAPPDATA%\Programs\Taraz\current-version.txt = 1.0.2`؛ پوشهٔ نصب `versions\1.0.4` وجود ندارد. بکاپ اصلی ۱۸۱ فایل در پذیرش مستقل بررسی شد؛ هیچ عملیات مالی روی نصب اصلی انجام نشده است.
- **گیت‌های بسته‌شده:** integrity سورس/EXE/ZIP، پوشاندن خطاهای آزمون‌شده در compiled JS، installer/activator disposable، rollback واقعی RC3 disposable، اجرای اولیهٔ private native EXE.
- **گیت‌های هنوز باز:** صحت ثبت سند و دفترکل، مانده‌ها و مهاجرت با دادهٔ واقعی، چرخهٔ کامل خرید/فروش/دریافت/پرداخت، پذیرش تعاملی GUI در Windows/WebView2، پیوند نقش/ACL/TLS واقعی Madar، امضا یا تصمیم مستند سیاست انتشار unsigned، تأیید اپراتور و آزمون بازگشت/بازیابی production. هیچ‌کدام از موفقیت‌های QA فعلی جای این پذیرش‌ها را نمی‌گیرد.
- دستور جدیدتر کاربر: **آزمون تکراری اضافه انجام نشود**. هیچ `-Apply` روی مسیر نصب اصلی مجاز نیست تا تصمیم انتشار جداگانه صادر شود.

---

## سوابق تاریخی RC1 / RC2 و مسیر رسیدن به RC3

## کاندیدای واقعی و اثرانگشت‌ها

ریشهٔ build: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264`

| شاهد | SHA-256 (بازخوانی مستقیم prime) |
|---|---|
| `binary\Taraz.exe`، ۱۷٬۰۵۶٬۴۶۳ بایت | `8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6` |
| `Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip`، ۱۶٬۸۰۱٬۱۳۱ بایت | `721bbf8d6fd461fb1317fb1394b26d0ad67237d4fbc8f3d9cbfc8442b5f79777` |
| `offline-update\update-manifest.json` | `116f325052c8db7b5386e0eae937d45db809760fbac42780d3e0d62657b32c75` |
| `build-report.json` | `c2f3ed699c679098e158f8dff619fc440abaf180089ea30a4e5796139bb8027b` |
| `offline-update\Install-Taraz-V104.ps1` | `f904625641734ba23912a39430ccfdc2581bdbb0cbc2a6a3686b8698b8abb0c4` |
| `offline-update\Activate-Taraz-V104.ps1` | `c2547005c3246b1519db7be8c864936ada4eb994963d1fc5a7c3eadf28577900` |

سورس ورودی نسخهٔ جدید: ۱۳۱ فایل، ۹ اصلاح محدود در رابط، اثرانگشت `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1`. فایل اجرایی با نسخهٔ PE `1.0.4.0` و PYZ `1.0.4` و `QA_ONLY=False` ساخته شده است؛ شواهد آن در گزارش builder ثبت شده و همچنان نیازمند پذیرش مستقل بسته است. امضای Authenticode مستقیم در ویندوز `NotSigned` بود.

## آزمون‌های اجراشده

| دروازه | نتیجه و حد پوشش |
|---|---|
| سورس و Vite stage، ۱۳۱ فایل | ۱۱/۱۱ آزمون Python با تنظیم هر سه مسیر stage، بدون skip، خروجی ۰؛ فایل‌های مبنا تغییر نکردند |
| Frontend Vite قبل از EXE | ۱۰/۱۰ آزمون Microsoft Edge، فقط backend ساختگی و بدون عملیات مالی، خروجی ۰ |
| **JavaScript واقعی داخل EXE جدید** | **۱۰/۱۰ آزمون Edge، بدون skip، خروجی ۰**؛ استخراج واقعی JS از PyInstaller و تطبیق با asset، هفت خطای محرمانهٔ ساختگی مخفی، دو پیام اعتبارسنجی تألیفی باقی ماند |
| اصل نصب‌شده و پشتیبان | نسخهٔ فعال `1.0.2`، پوشهٔ نسخهٔ نصب‌شدهٔ `1.0.4` وجود ندارد؛ شواهد backup قبلی ۱۸۱ فایل/۶۷ SQLite معتبر در دامنهٔ خود |
| installer/activator امن RC1 | **۲۴/۲۴ آزمون مستقل مجدد در PowerShell 5.1 PASS** با فایل اجرایی واقعی v104 و v102 در مسیر موقت، سناریوهای Junction/Hard Link و backup؛ هیچ اجرای `-Apply` روی نصب اصلی نبود |
| rollback خود نسخهٔ v104 | **در انتظار خروجی عملیاتی پین‌شده به هش EXE v104**؛ ۲۶/۲۶ آزمون ابزار مقدماتی با surrogate فقط پوشش مکانیکی داشت |
| آزمون مستقل PE/PYZ/ZIP | عامل ممیزی مستقل ۱۵/۱۵ آزمون موفق گزارش کرد: ۱۳۱ سورس، PYZ/PE، همهٔ ۱۵ asset و ۷ عضو ZIP؛ هنوز نتیجهٔ نصب موقت مستقل نیست |
| **ممیزی تکمیلی نمایش شناسهٔ خصوصی و خطای محلی** | **۳ ایراد جداگانه در رابط آزمایشی ۱.۰.۴ بازتولید شد**: چاپگر/Canvas، خواندن CSV بانکی و انعکاس شناسهٔ فاکتور نامعتبر در خطای تحلیل مدیریتی. این‌ها با هفت خطای native قبلی فرق دارند و **نسخهٔ ۱.۰.۴ فعلی را NO_GO نگه می‌دارند** |
| مرحلهٔ اصلاحی RC2، سورس و Vite | stage با ۱۳۱ فایل و ۳ اصلاح، SHA `aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8`؛ **۱۲/۱۲ آزمون structural PASS**، اما Edge به‌درستی FAIL کرد: دو خطای Canvas/CSV پوشانده شدند، شناسهٔ فاکتور همچنان از `analytics.error` برگشتی نمایش داده شد |
| مرحلهٔ بعد RC3 | **اصلاح نمایش نتیجهٔ `analytics.error`، نه فقط `catch`**؛ snapshot و Vite/Edge تازه، سپس ساخت EXE جدید لازم است؛ هنوز تأیید نشده |

### RC3 source/Vite دروازهٔ جدید (به‌روزرسانی ۲۰۲۶-۱۱-۱۱)

اصلاح با snapshot جداگانه انجام شد، بدون بازنویسی کاندیدای قبلی:

- Source: `...\taraz-v1.0.4-p1\source-stage-ca9761aa43d8`، **۱۳۱ فایل**، SHA-256 `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de`؛ فقط `accounting_management_dashboard.jsx` نسبت به RC2 عوض شده است.
- Vite: `...\taraz-v1.0.4-p1\vite-qa-72ee216638e4`، JavaScript SHA-256 `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9`؛ manifest Vite SHA-256 `5940d2765b6a9ff6810078364fb5422c1eb112697f7f02f46156aa85624d69b8`.
- Structural RC3: **۱۰/۱۰ PASS exit0**، مستقلاً با Python اجرا و همهٔ فایل‌های سورس و خروجی Vite مجدداً هش شدند.
- Dynamic RC3 Stage-only: **۱۴/۱۴ PASS exit0** در Microsoft Edge جداشده، ۱۳ سناریوی برگ شامل سه مورد residual (شناسهٔ فاکتور نامعتبر، Canvas و خواندن CSV)، هفت مورد Error.message قبلی و سناریوهای اعتبارسنجی. این **فقط Vite STAGE_UI_ONLY** است.
- اجرای مستقیم prime: گزارش‌های مستقل `qa-evidence-rc3-prime-59c27fd65bbe` شامل لاگ فرمان‌های واقعاً اجراشده و سه شاهد هشی:
  - `rc3-source-stage-qa.json`: `0accc1863a82dadfd057b19ad48c962747b1f2a06290c7937c207d4d958b027f`.
  - `rc3-original-seven-edge-qa.json`: `1743aaa93d185c1895545b497b324344d25541ef1bde1d2e4df54bf1524ece54`.
  - `rc3-residual-three-edge-qa.json`: `b6db26fceb2197e1125c97e313cf16ff510ddb64ae7eef9d1aaa519928e08f25`.

**دروازهٔ ورودی سازنده RC3** با بازخوانی مستقل این سه شاهد، hashهای stage/Vite و `qa_preflight` واقعی سازنده، `RC3_READ_ONLY_GATES_PASS` را برگرداند. ساخت EXE جدید در خروجی create-only آغاز شده است؛ تا وقتی build report و آزمون compiled EXE ثبت نشود، این بخش به‌عنوان «ساخته‌شده/پذیرفته‌شده» اعلام نمی‌شود. تأیید انتشار همچنان `NO_GO` است.

### RC3 Native candidate واقعی (ساخته شد، پذیرش انتشار هنوز NO_GO)

Build جدید، جدا از RC1/RC2: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99`.

| فایل RC3 | SHA-256 بازخوانی مستقیم |
|---|---|
| `binary\Taraz.exe` | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| `Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip` | `1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e` |
| `offline-update\update-manifest.json` | `b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6` |
| `build-report.json` | `510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb` |
| `offline-update\Install-Taraz-V104.ps1` | `6dda4897c1ce4da9120d3e6fda9c639834080f838602de02e32eea46c3de6a68` |
| `offline-update\Activate-Taraz-V104.ps1` | `3d7cb9aea21e54864fd8215ee686c48245c1b76f032afefe455c6782f3957937` |

گزارش build وضعیت `PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED`، منبع ۱۳۱ فایل RC3 با SHA `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de`، PE واقعی `1.0.4.0` و PYZ `1.0.4` با حالت غیر QA را ثبت کرد. امضای Authenticode کاندیدا `NotSigned` است. نسخهٔ تولیدی همچنان روی **۱.۰.۲** است و پوشهٔ نصب ۱.۰.۴ وجود ندارد.

این خروجی به‌خودی‌خود فقط ساخت RC3 را ثابت می‌کند. **یادداشت پسینی:** آزمون‌های EXE/ZIP، نصب/فعال‌سازی در TEMP، compiled JS و rollback اختصاصی RC3 اکنون انجام شده و شواهد دقیقشان در بخش «تصمیم نهایی این مرحله» در ابتدای سند ثبت شده است. این پیشرفت همچنان مجوز نصب production نیست.
| مجوزهای واقعی نقش/ACL/TLS مدار، ثبت مالی و مهاجرت واقعی | در این مرحله آزمون E2E و پذیرش مستقل نهایی نشده‌اند |

## شواهد تأیید اجرا

پیش از ساخت کاندیدا، دو شاهد مستقل با اجرای واقعی ابزارها ساخته شد:

- `...\taraz-v1.0.4-p1\qa-evidence-prime-79d7d3c40b08\source-stage-qa.json`، SHA-256 `ee9743970f38f4d1086ffca5edcbd9843fc0509dc9ec7ba7de4690744c1abe74`، ۱۱ آزمون.
- `...\taraz-v1.0.4-p1\qa-evidence-prime-79d7d3c40b08\staged-edge-qa.json`، SHA-256 `1c2856c365298950a64235fac68f35642832c3c43a56f12aa594756ca0c0e997`، ۱۰ آزمون.

در اجرای مستقیم پس از ساخت:

```powershell
$env:TARAZ_V104_BUILD_DIR='D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264'
node --test tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs
# 10 tests, 10 pass, 0 fail, 0 skipped, exit 0; VERIFIED_MODE=EXE_COMPILED_UI
```

این آزمون از bridge مصنوعی استفاده می‌کند، پس دربارهٔ پذیرش ثبت سند مالی روی میزبان واقعی، TLS، احراز هویت یا صحت کلیهٔ اسناد حسابداری اظهارنظر نمی‌کند.

## ممنوعیت عملیات واقعی تا بسته‌شدن گیت‌ها

**دستورهای PowerShell با `-Apply` نباید روی مسیر واقعی `%LOCALAPPDATA%\Programs\Taraz` یا داده‌های `%APPDATA%\Taraz` اجرا شوند.** هر نصب/فعال‌سازی/بازگردانی صرفاً در محیط موقت ایزوله آزمون شده است. بستهٔ قدیمی ۱.۰.۳ و RC1/RC2 ردشده‌اند؛ سه نشت شناخته‌شده در **RC3** اصلاح و با JS استخراج‌شده از EXE آزمون شده‌اند. بااین‌حال، RC3 به‌علت گیت‌های مالی/مهاجرت/GUI تعاملی/پیوند واقعی/امضا یا تصمیم سیاست unsigned و مجوز اپراتور **همچنان NO_GO برای production** است. اصل کاندیداهای قبلی برای ردگیری شواهد حفظ می‌شود.
