# ECOSYSTEM PRIME | Local AI QA | ۱۶ نوامبر ۲۰۲۶

**وضعیت:** `SOURCE_TESTED / RUNTIME_UNSTABLE / NOT_INSTALLED / RELEASE_NO_GO`.

## مبنا و شواهد

- نصب Taraz: `1.0.7`، SHA-256 EXE: `83a47d228d111b7ac8c4eff73ce0948a8b8517ae5e95bf0646bb5969fed0ba9b`.
- نصب Madar: `1.0.28`، SHA-256 EXE: `2bb04e2aa9c770469615d0716991fea8fcfc6b887b92003eeaa1ce565696ab49`.
- Source HEAD زمان شروع: Taraz `05f09f49b3719f08a8cf7270e1d657d87fc7e121`؛ Madar `b90ec8b2573e20ac0185f5a25d2578a206b27335`.
- در مدار ۱۹ فایل Tracked تغییرکرده باقی ماندند؛ نصب آن دستکاری نشد. ممیزی مستقل: `D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107\docs\modernization\ECOSYSTEM_MADAR_SOURCE_LINEAGE_20261116_FA.md`.
- Ollama در دستگاه موجود است؛ `ollama list` دو مدل `qwen3:0.6b` (~۵۲۲ مگابایت) و `qwen3:4b` (~۲.۵ گیگابایت) را نشان داد.
- RAM واقعی ۳۴٬۲۷۲٬۰۰۶٬۱۴۴ بایت؛ ۲۸ CPU منطقی؛ در یکی از نمونه‌ها RAM آزاد ۸٬۵۲۴٬۲۵۱٬۱۳۶ بایت. GPU/VRAM قابل‌اتکا از طریق API جدید هنوز Unknown است. `ollama ps` در زمان اجرا `qwen3:0.6b` را با `100% GPU` نشان داد، اما این نشانهٔ تأیید کارایی یا سازگاری پایدار نیست.

## اجرای واقعی مدل، نه Mock

۱. درخواست فارسیِ مصنوعی به `http://127.0.0.1:11434/api/generate` با `qwen3:0.6b`: پاسخ HTTP 200 با `done=true` پس از حدود ۱۱ ثانیه؛ در همان آزمون پاسخ مدل دربارهٔ مجازبودن ثبت مالی قطعی **اشتباه** بود. این مدل برای ابزار مالی **مردود** است.

۲. `qwen3:4b` روی متن مصنوعی بعد از timeout=120 ثانیه پاسخ معتبر نداد. **FAIL/TIMEOUT**.

۳. پس از افزودن Adapter جدید، درخواست واقعی `qwen3:0.6b` از `taraz_ai_local_runtime.generate` بعد از ۴۵ ثانیه به `LocalModelError` تبدیل شد. **FAIL/TIMEOUT**. هیچ دفتر عملیاتی یا سند مالی خوانده/نوشته نشد.

این آزمون‌ها نه کیفیت فارسی را تأیید می‌کنند، نه انطباق یک مدل با Tool Calling و نه عملکرد آفلاین پس از قطع اینترنت را.

## سورس پیاده‌سازی‌شده

- `taraz_ai_local_runtime.py`: کشف مدل‌های واقعاً نصب‌شده، اندازه‌ها، CPU/RAM/Disk با Unknown صریح برای GPU، HTTP مستقیم به Loopback بدون DNS/Proxy، محدودیت ورودی/خروجی/زمان، تک‌درخواست و پاسخ متنی بدون Tools مالی.
- `taraz_desktop.py`: دو API احرازشدهٔ `tarazAiLocalStatus` و `tarazAiLocalGenerate`. فراخوانی دوم نیازمند Editor و `manualConsent=true` است.
- `standalone_accounting_desktop.py`: APIها در Bridge واقعی WebView اضافه شدند.
- `src/taraz_ai_local_panel.jsx`: UI فارسی، انتخاب فقط از مدل‌های موجود، نمایش وضعیت، درخواست دستی و پاسخ محدود بدون ذخیرهٔ دفتر؛ `src/taraz_ai_chat_workspace.jsx` آن را به‌صورت بخش جدا از پیشنهاد مالی اضافه می‌کند.

## نتایج آزمون و Build

- Python: ۷ آزمون Backend/Auth جدید + ۴ آزمون Fresh Windows در اجرای ترکیبی نهایی: **۱۱ PASS**.
- Browser: آزمون کنترل Manual Consent و عدم فراخوانی فرمان مالی **۱ PASS**.
- AST و `git diff --check`: PASS.
- خروجی Vite در فضای QA مستقل: `D:\CoS-Test\ECOSYSTEM-PRIME-20261116\taraz-ai-web`، Build موفق با ۲۰۶۳ ماژول؛ هشدار موجود دربارهٔ بزرگ‌بودن Chunk.
- SHA-256 باندل `accounting-I8FMuGMu.js`: `614572ac18731f489812a441111675691e94d0dc6a5cbdc9754ea63f6ef54cb3`.
- **این Vite Build، بستهٔ PyInstaller و نسخهٔ نصب‌شده نیست.**

## گیت‌های باز و اقدام اجرایی بعدی

۱. لایحهٔ «Local AI» هنوز نیازمند آزمون سخت‌افزار/Runtime و مدل بهتر با کیفیت فارسی و Tool Calling معتبر است. مدل `0.6b` برای تصمیم مالی مردود است؛ `4b` در سخت‌افزار فعلی Timeout شده. دانلود مدل جدید بدون نمایش حجم، منبع و تأیید کاربر ممنوع است.

۲. پنل مدل محلی فقط پاسخ متنی است. دانلود/Resume/Hash/Activation داخل برنامه، Credential Manager و Adapter آنلاین، Business Tools مجاز و تست Offline/Restart با مدل هنوز کامل نشده‌اند.

۳. Pairing واقعی و خواندن دوطرفهٔ دادهٔ دارای Scope، inbox مالی و چرخهٔ پاسپورت هنوز در نسخهٔ نصب‌شده PASS نشده‌اند. قبل از Upgrade، اختلاف سورس با باینری `Madar 1.0.28` باید رفع شود.

۴. تا زمانی که Frozen EXE جدید، Clone و تمام گیت‌ها PASS نشده‌اند، نسخه‌های نصب‌شدهٔ `Taraz 1.0.7` و `Madar 1.0.28` **بدون تغییر** باقی می‌مانند.
