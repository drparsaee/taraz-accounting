# ECOSYSTEM PRIME | اتصال آزمایشی مدار ↔ تراز | ۱۶ نوامبر ۲۰۲۶

## نتیجه

**SOURCE / LOCAL-QA PASS — INSTALLED RELEASE NO-GO.** این سند اثبات نصب یا انتشار نیست.

### بازیابی نسخهٔ نصب‌شدهٔ مدار

- آرشیو مرجع: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\madar-v1.0.28\production-candidate-v128-worker25-20261110-b`.
- EXE آرشیو و نصب‌شده `1.0.28` هر دو ۱۸٬۰۶۷٬۶۰۲ بایت و SHA-256 برابر `2bb04e2aa9c770469615d0716991fea8fcfc6b887b92003eeaa1ce565696ab49` دارند.
- فایل JS مرحله و JS استخراج‌شدهٔ نصب‌شده با SHA-256 برابر `6401496b1c1d602b0d8158681201a4b1a1f3696a56b2503ee532dbd323267740` تطبیق دارند.
- ممیزی Worker خواندن‌فقط از ۷۱ ماژول Python در PYZ تطبیق CodeType برابر `71/71`، و از ۱۸ دارایی Frontend تطبیق هش برابر `18/18` را گزارش کرد. بازتولید Build کامل انجام نشده است.
- کاربرگ فعال مدار نسبت به مرحلهٔ `1.0.28` در ۱۶ فایل Frontend/PWA کمبود دارد. نام‌ها، کدهای Dirty و Untracked نباید در فرآیند Merge پاک شوند.

### پیاده‌سازی و آزمون در سورس

- **مدار:** `integration_key_registry.py` اعتبارنامهٔ هش‌شده و ابطال پایدار دارد. `integration_pairing_v1.py` کد ۱۳حرفی Base32 با عمر پنج دقیقه، حداکثر پنج خطا و مصرف یک‌بار را پیاده می‌کند؛ Route جدید `POST /integrations/v1/pair` روی HTTPS موجود، بدون حق Posting، اعتبارنامهٔ مستقل برای نصب TARAZ صادر می‌کند. رابط «اتصال نرم‌افزارها» در Source اضافه شده است.
- **تراز:** `taraz_ecosystem_credentials.py` اعتبارنامهٔ واقعی صادرشده از مدار را با Windows DPAPI و Scope مسیر نگهداری می‌کند. `taraz_ecosystem_client.py` قبل از ارسال کد یا اعتبارنامه، SHA-256 گواهی TLS را بررسی می‌کند. `taraz_ecosystem_native_boundary.py` از پوشهٔ اختصاصی با ACL فعلی Windows استفاده می‌کند؛ Bridge فقط برای مدیر احرازشدهٔ شرکت و با اقدام دستی فعال است.
- **قابلیت فعلی:** خواندن دادهٔ ACL-scoped کارت‌های مدار از تراز در QA؛ هیچ SQL به دیتابیس مدار و هیچ Journal Posting انجام نمی‌شود. بازگشت طرف‌حساب واقعی تراز به مدار و گردش مالی هنوز ساخته/پذیرفته نشده‌اند.

### شواهد آزمون جاری

| آزمون | نتیجه |
| --- | --- |
| Madar API / HTTP Security / Pairing + Persistence | `29 tests, OK` |
| Taraz Windows DPAPI + واقعی TLS cross-product / native company bridge | `25 tests, OK` |
| Taraz React browser pairing click (stubbed backend) | `1 PASS` |
| Madar Vite QA | `PASS`, 1693 modules، هشدار chunk بزرگ |
| Taraz Vite QA | `PASS`, 2065 modules، هشدار chunk بزرگ |
| Windows Fresh Taraz company | دفتر `revision=0` قبل و بعد از اتصال، Restart، خواندن کارت، لغو و اتصال مجدد |

Cross-product test با `MADAR_QA_SOURCE`، دیتابیس/کاربر آزمایشی و TLS loopback واقعی اجرا شده است. Browser test با Stub API است؛ با شبکهٔ واقعی اشتباه گرفته نشود.

### بازتولید آزمون‌ها (QA، نه نصب)

در مخزن Madar:

```powershell
py -3.12 -B -m unittest tests.test_integration_api_v1 tests.test_integration_http_security tests.test_integration_durable_keys_20261116 -q
```

در مخزن Taraz:

```powershell
$env:MADAR_QA_SOURCE='D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107'
py -3.12 -B -m unittest tests.test_taraz_ecosystem_client_20261116 tests.test_taraz_ecosystem_credentials_20261116 -q
node --test tests/taraz_ecosystem_link_panel_20261116.test.cjs
```

### موارد باقی‌مانده / NO-GO

1. کد فعلی مدار از مرحلهٔ نصب‌شدهٔ `1.0.28` فاصله دارد؛ حفظ ۱۶ فایل Stage و انتقال امن اصلاحات بدون رگرسیون و Build بازتولیدپذیر لازم است.
2. هر دو EXE جدید Frozen/Installer نشده‌اند و آزمون GUI نصب‌شده و Backup/Restore مخصوص این Upgrade وجود ندارد.
3. مسیر عکس **Counterparties.Search/Get** از تراز به مدار، Service Discovery، باطل‌سازی از هر دو سمت و تست LAN واقعی هنوز تأیید نشده است.
4. Durable Financial Inbox/Outbox، Idempotent Return Receipt، سناریوی ۱۰۰ پاسپورت و Human Approval واقعی هنوز آزمون Cross-App ندارند.
5. Ollama مدل `qwen3:0.6b` در یک پاسخ مالی نامعتبر بود و `4b` Timeout داشت. پاسخ کوتاه CPU-only، پذیرش AI مالی نیست؛ ابزارهای مالی مدل غیرفعال باقی بمانند.
6. Online Provider و Key واقعی وجود ندارد، آزمون آنلاین **NOT TESTED**؛ هیچ دادهٔ مالی به اینترنت ارسال نشده است.
7. `TarazEcosystemForget` صرفاً خزانهٔ محلی را لغو می‌کند؛ ابطال سمت مدار با عملیات مدیر مدار انجام می‌شود و نباید دوطرفهٔ خودکار معرفی شود.

**نتیجه: NO-GO برای نصب یا انتشار؛ فقط Source و محیط آزمایشی مجاز است.**
