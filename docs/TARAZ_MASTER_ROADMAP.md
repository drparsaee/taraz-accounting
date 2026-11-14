# TARAZ AaaS — Master Product Roadmap

**آخرین بازبینی:** 2026-11-12
**مالک مأموریت:** TARAZ Prime
**وضعیت سند:** مرجع برنامه‌ریزی محصول؛ این سند به معنی تکمیل قابلیت یا تأیید انتشار نیست.

**جدیدترین شاهد اجرای Prime (۲۰۲۶-۱۱-۱۴):**
`docs/TARAZ_PRIME_EXECUTION_EVIDENCE_20261114.md` مرجع وضعیت جاری است.
کاندیدای غیرنصبی `build-d87b73dc956c` با AI بسته‌بندی شده اما در اولین
آزمون واقعی Login/Company Selection با وضعیت `BLOCKED_NATIVE_UIA` متوقف شد؛
این نتیجه پذیرش Frozen یا نسخهٔ قابل ارتقا نیست. گیت حفظ تمام داده‌های واقعی،
Quiescence، مالکیت Legacy و بازیابی DPAPI بین‌دستگاهی نیز همچنان بازند.
نصب‌شدهٔ ۱.۰.۴ دست‌نخورده است. داده‌های این بند جایگزین Snapshot تاریخی
پایین هستند، نه تأیید تحقق برنامهٔ محصول.

## 1. هدف محصول

تراز باید از یک نرم‌افزار حسابداری فرم‌محور به یک سیستم کاری AaaS عامل‌محور تبدیل شود:

- برای کاربر مبتدی، مسیر ساده و هدایت‌شده داشته باشد و پیچیدگی حسابداری را تا حد لازم پنهان کند.
- برای کاربر حرفه‌ای، کنترل کامل سند، حساب‌ها، مالیات، گزارش‌ها، هزینه‌ها، پرداخت‌ها و تاریخچه را فراهم کند.
- اطلاعات شرکت را با منشأ و سطح دسترسی مشخص نگه دارد.
- درخواست متنی را به کار قابل بررسی و اجرا تبدیل کند، نه اینکه فقط کنار نرم‌افزار چت نشان دهد.
- عملیات حساس مالی را فقط با هویت معتبر و تأیید انسانی انجام دهد.
- مدار را برای مدیریت پروژه و وظایف به کار بگیرد و تراز را مرجع سفارش و حسابداری رسمی نگه دارد.

## 2. اسناد مرجع و سلسله‌مراتب

| سند | مسئولیت |
| --- | --- |
| این Roadmap | دامنهٔ محصول، ترتیب فازها، وابستگی‌ها و معیار پایان |
| TARAZ_POSTGRESQL_MIGRATION_PLAN.md | معماری داده و برنامهٔ مهاجرت PostgreSQL |
| TARAZ_AAAS_AUTONOMOUS_DELIVERY_LEDGER.md | شواهد واقعی، وضعیت اجرا، موانع و اقدام بعدی |
| TARAZ_P0_P1_SOURCE_GATES_20261112.md | جزئیات تاریخی و شواهد گیت‌های فاکتور و چاپ |

Ledger نباید با Roadmap رقابت کند: Roadmap می‌گوید چه چیزی باید تحویل شود؛ Ledger می‌گوید چه چیزی واقعاً و با چه شواهدی انجام شده است.

## 3. واژگان وضعیت

- **NOT STARTED:** هنوز کار اجرایی آغاز نشده است.
- **IN PROGRESS:** پیاده‌سازی یا اعتبارسنجی باز است.
- **REPORTED PASS:** نتیجه در گزارش Prime یا کاربر اعلام شده، اما در این بازبینی مستقل تکرار نشده است.
- **VERIFIED PASS:** فرمان یا آزمون در اجرای مشخص انجام شده و خروجی آن ثبت شده است.
- **BLOCKED:** مانع مشخص، ادامهٔ همان مسیر را متوقف کرده است.
- **NOT ACCEPTED:** معیارهای محصول یا شواهد نهایی کافی نیستند؛ حتی اگر بخشی از تست‌ها سبز باشد.
- **READY FOR APPROVAL:** همهٔ گیت‌های فنی و محصولی پذیرفته شده‌اند، اما اقدام حساس انتشار هنوز نیازمند تأیید کاربر است.

## 4. مبنای پیش از یکپارچه‌سازی — snapshot تاریخی

مقادیر این بخش وضعیت قبل از Gate E هستند. برای وضعیت جاری شاخه، Commitها،
کاندیدا و Gateها فقط بخش Latest integration snapshot بلافاصله پس از این
بخش مرجع است؛ مقادیر قدیمی زیر نباید به‌عنوان وضعیت فعلی نقل شوند.

### سورس و Git پیش از Gate E

- Worktree کاری: D:/CoS-Test/000- Taraz/taraz-mtr-e2-isolated-20261109
- HEAD مشاهده‌شده: 653089bb99747ab1c909cfdb113d2d12bc36e47a
- Worktree دارای تغییرات Tracked و Untracked است؛ این وضعیت یک Release Commit تمیز نیست.
- git diff --check در آخرین بررسی این مأموریت Exit Code 0 داد؛ دو هشدار تبدیل LF/CRLF در خروجی Git دیده شد.
- هیچ Reset، Clean، Commit، Merge یا Push در ساخت این اسناد انجام نشده است.

### کاندیدای باینری تاریخی

- پوشه: D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/build-05511322d050
- Source Freeze گزارش‌شده: 223f87be3892e4567a412701510f100d0607957b47794574994576e9b52b98fb
- EXE SHA-256 گزارش‌شده: fd613f23883dc716277811fc6a908f18bec823bfac39a9ddb76392f59be24ee9
- ZIP SHA-256 گزارش‌شده: 93de7178c46a8bc5ded3710de54f7714d9f43927896cb338b178e06e174ed797
- وضعیت: BUILT / NOT INSTALLED / NOT RELEASE ACCEPTED.
- نسخهٔ نصب‌شدهٔ گزارش‌شده: 1.0.4؛ تغییر آن مجاز نشده است.

این شناسه‌ها از آخرین گزارش Prime بازیابی شده‌اند و در این کار مستندنگاری، باینری دوباره Hash یا اجرا نشده است.

### هویت CoS در اجرای قبلی

آخرین گزارش Prime می‌گوید self=null و run_id=null و Worker قابل‌بازیابی وجود ندارد. در این وضعیت نباید Worker جدیدی ساخت که مالکیت و بازیابی آن روشن نیست. Prime می‌تواند کارهای مستقیم و مجاز را در Worktree ادامه دهد.

### Latest integration snapshot — 2026-11-12

This snapshot supersedes the pre-integration source and gate statuses below
for the current candidate. Detailed test counts are recorded from the Prime
handoff and QA report; they were not rerun during this documentation update.

- Current branch: codex/taraz-final-integration-20261112.
- Current HEAD observed in Git: db22b9cfcbd5120a755820e41b02ceb494efb872.
- Six commits are present, oldest to newest: e658702, 60e0390, f064609,
  ec0ced7, bcef425, db22b9c.
- The first three feature commits cover invoice/print, orders/Agent/Madar,
  and MTR authority/peer integration. The later commits add independent QA,
  durable Madar attempt/recovery evidence, and final candidate/QA evidence.
- Gate E source integration is VERIFIED PASS. At the integration readback,
  tracked files/index were clean; 141 runtime inventory paths were tracked
  and 187 historical untracked paths were preserved.
- Source fingerprint reported for the frozen runtime:
  1661fab1c4e6dd66a70bd596f002a28d7db11dd30816c1ac20d0422d392abe4f.
- Latest candidate: build-8498c703dc4d, BUILT / NOT INSTALLED.
- EXE SHA-256:
  3462cfb0dc93365e202686691eb74cc1b97dcde0333c44266191db934a42e9f4.
- ZIP SHA-256:
  9f8039c50f094f446856d2a69d26f2a59bf204c27500002df8f1304a8d9edebc.
- Installed 1.0.4 remains unchanged. No release, real financial posting,
  production Madar write or physical print was performed.

**Gate snapshot:** Gate A Frozen EXE BLOCKED; Gate B order Backend/SQLite VERIFIED PASS
but frozen UI BLOCKED; C rule-based tools and memory pass but real LLM
autonomy BLOCKED by timeouts; D isolated Madar contract/audit/recovery pass
but live Host BLOCKED; E VERIFIED PASS; F independent source/database QA
5/5 PASS. Source-hosted PDF passes; physical printing is NOT TESTED.

Prime reports integration tests 22/22 Python + 6/6 JavaScript, five-axis
independent QA 5/5, MTR controls 135/135, and a post-final-commit selection
11/11 PASS. The detailed QA report also records 59/59 Python + 16/16 Edge
for the current order suite and 34/34 Python + 11/11 Edge for source-hosted
P1. These are separate reported suites, not one interchangeable test count.
They do not prove frozen EXE or live-host acceptance.

The branch/HEAD/commit log and tracked/untracked status were inspected
directly. The test counts, runtime inventory count, source fingerprint and
candidate hashes above remain report-backed evidence, not fresh reruns in
this documentation update.

**UPDATED 2026-11-12:** Three supported deployment modes (LAN, customer
enterprise server, Cloud + customer LAN Offline Node) and fully online Cloud
are approved product requirements; core commercial work must function
without internet, with AI optional. The older LAN-versus-Cloud and
online-only-versus-offline decision gate is superseded. **PRE-DB2 BLOCKERS**
remain financial Authority/Fencing transfer, nonfinancial/financial conflict
policy, tenant boundaries, backup and RPO/RTO, as detailed in
docs/TARAZ_ARCHITECTURE_DECISIONS_20261112.md. Do not treat product
approval as proof that sync/finance failover has been implemented.

## 5. قراردادهای غیرقابل مذاکرهٔ محصول

### فاکتور و چاپ

- پیش‌فاکتور فروش و فاکتور فروش با شماره‌گذاری و وضعیت مجاز.
- مشتری موجود، جدید، متفرقه یا حضوری.
- حالت ساده و حرفه‌ای روی یک مدل داده؛ تغییر حالت نباید اطلاعات را از بین ببرد.
- ردیف خودکار، شرح، تعداد، واحد، قیمت، تخفیف، مالیات و جمع دقیق.
- پیشنهاد کد کالا از کاتالوگ با امکان قبول یا رد؛ قلم متفرقه مجاز.
- تاریخ سند قابل تغییر؛ زمان واقعی ایجاد و ویرایش جدا و غیرقابل جعل.
- اطلاعات انتقالی مدار فقط در صورت وجود منبع معتبر پر شود و ویرایش دستی کاربر بازنویسی نشود.
- ذخیره، بازخوانی، ویرایش، پیش‌نمایش همان سند، قالب چاپ پایدار و PDF چندصفحه‌ای.
- ویرایش قالب با جابه‌جایی عناصر، ستون و متغیرهای مجاز و کمک AI اختیاری.
- صدور، تأیید و ثبت رسمی مالی نیازمند مجوز و تأیید معتبر است.

### سفارش

- سفارش خرید و فروش مستقل از پیش‌فاکتور و سند حسابداری.
- ورود دستی یا متنی، مشتری/تأمین‌کننده، پروژه، مراحل و زمان‌بندی.
- تفکیک مقدار فروش، برنامهٔ تولید، تولید واقعی، پرت واقعی و مازاد سالم.
- هزینهٔ برآوردی و هزینهٔ واقعی جدا؛ هزینهٔ نامشخص هرگز صفر فرض نشود.
- دریافت و پرداخت با وضعیت‌های برنامه‌ریزی‌شده، ثبت‌شده و تسویه‌شده.
- تأیید مسئول مالی، تاریخچه، Idempotency و کنترل Revision.
- تحویل کنترل‌شده به حسابداری؛ سفارش به‌تنهایی رویداد دفترکل نیست.

### AaaS

- Agentهای وظیفه‌محور با ابزارهای واقعی و مجوز محدود.
- حافظهٔ سازمانی تفکیک‌شده بر اساس شرکت، نسخه‌دار و قابل ممیزی.
- پیشنهاد قابل مشاهده، قبول، ویرایش یا رد.
- پرسش فقط برای دادهٔ ضروری و در زمان قابل تنظیم.
- اجرای خودکار کارهای کم‌خطر و تکراری فقط در محدودهٔ مجاز.
- مدل واقعی باید با دادهٔ آزمایشی، سنجش کیفیت و آزمون منفی ارزیابی شود.
- Agent حق جعل داده، منبع، تأیید یا نتیجهٔ مالی ندارد.

### مدار

- مدار مرجع پروژه، وظیفه و اجرای عملیاتی است.
- تراز مرجع سفارش، هزینه، پرداخت و حسابداری رسمی است.
- اتصال باید هویت، مجوز، Revision، Idempotency و منشأ داده را حفظ کند.
- ورود دوبارهٔ اطلاعات و Sync خاموش یا بدون رسید ممنوع است.

## 6. نقشهٔ فازها

| شناسه | فاز | وضعیت فعلی | وابستگی اصلی |
| --- | --- | --- | --- |
| P0 | مبنای سورس، تصمیمات محصول و کنترل تحویل | VERIFIED PASS برای Gate E؛ انتشار و تأیید محصول جداست | ندارد |
| P1 | فاکتور ساده/حرفه‌ای و چاپ | NOT ACCEPTED؛ Source-hosted PDF PASS؛ Frozen EXE BLOCKED؛ چاپ فیزیکی NOT TESTED | P0 |
| P2 | مدیریت سفارش و گردش مالی کنترل‌شده | Backend و SQLite آزمایشی VERIFIED PASS؛ Frozen UI BLOCKED؛ پذیرش کلی باز | P0 و قراردادهای P1 |
| D1 | مرزبندی ذخیره‌سازی و پایلوت PostgreSQL | DB0 پنج SQLite Store ساختگی و DB1 Order Read Contract محدود PASS؛ DB2 تا Authority/Fencing، Conflict و RPO/RTO مسدود | شواهد DB0/DB1 و ADR مصوب |
| P3 | AaaS Agent Engine و حافظهٔ سازمانی | ابزار/حافظهٔ قاعده‌محور PASS؛ مدل واقعی BLOCKED به‌علت Timeout | P2 و قرارداد Repository؛ برای پذیرش چندکاربره D1 |
| P4 | یکپارچگی عملیاتی Madar ↔ Taraz | قرارداد و بازیابی ایزوله PASS؛ اتصال واقعی Host BLOCKED | P2، P3 و API مرکزی؛ برای پذیرش چندکاربره D1 |
| P5 | چندکاربره، آفلاین، امنیت و عملیات پایدار | NOT STARTED؛ سیاست آفلاین و توپولوژی هنوز OPEN است | D1، P3، P4 و تصمیم معماری |
| P6 | QA مستقل سرتاسری و آمادگی انتشار | 5/5 در سطح سورس/دادهٔ آزمایشی PASS؛ پذیرش محصول NOT ACCEPTED | تمام فازهای لازم |
| P7 | استقرار مرحله‌ای و پشتیبانی | NOT READY FOR APPROVAL | P6 و تأیید صریح انتشار |

**نگاشت شماره‌گذاری قبلی:** مأموریت قدیمی Phase 4 همان P2 مدیریت سفارش، Phase 5 همان P3 موتور AaaS و Phase 6 همان P4 یکپارچگی مدار است. شناسه‌های P برای ماتریس پذیرش استفاده می‌شوند؛ این نگاشت قابلیت یا فاز جدیدی را به‌صورت انجام‌شده اعلام نمی‌کند.

## 7. وضعیت شواهد هر فاز

### P0 — Source of Truth

**وضعیت: VERIFIED PASS برای Gate E در محدودهٔ یکپارچه‌سازی فعلی**

- شاخهٔ نهایی و شش Commit آن در Git مشاهده شده‌اند.
- تمام 141 مسیر Runtime طبق گزارش در Git قابل ردیابی‌اند.
- در لحظهٔ تحویل Gate E، Tracked tree/index پاک بوده و 187 Untracked قدیمی حفظ شده‌اند.
- این Gate به معنی Push، Merge به main، نصب یا انتشار نیست.

**مرز پذیرش:** Source integration بسته شده است؛ Release readiness همچنان تابع Gateهای A تا D و QA محصول است.

### P1 — Invoice & Print

**وضعیت: NOT ACCEPTED**

شواهد گزارش‌شده شامل ذخیره و بازخوانی SQLite، ویرایش همان فاکتور و پیش‌فاکتور، حفظ Revision و Audit، تغییر سه حالت رابط، قالب چاپ سفارشی و PDF است. آزمون Native Source-hosted با WebView2 و Bridge واقعی و PDF در Source-hosted موفق گزارش شده است. تعامل کامل روی Frozen EXE همچنان BLOCKED است؛ چاپ فیزیکی NOT TESTED است.

گیت‌های باز:

1. تعامل کامل Save/Edit/Reopen و قالب/PDF در Frozen EXE واقعی.
2. تکمیل ممیزی تمام تصمیمات Clarify تاریخی.
3. QA مستقل پس از ادغام.
4. چاپگر فیزیکی به‌عنوان گیت سخت‌افزاری جداگانه.

**معیار پایان:** کاربر بتواند تمام مسیر فاکتور و چاپ را در EXE پذیرفته‌شده اجرا کند و داده‌ها بعد از Restart حفظ شوند؛ هیچ سند مالی بدون تأیید صادر نشود.

### P2 — Order Management

**وضعیت: NOT ACCEPTED**

کد فعلی SQLite دارای سفارش، Action/Idempotency، Audit، هزینهٔ واقعی مرحله، پرداخت و Finance Handoff است. سناریوی ۱۰۰ فروش / ۱۲۰ تولید، ثبت هزینه و پرداخت، تأیید انسانی و Draft حسابداری در گزارش‌های Prime آزموده شده است.

آخرین گزارش نهایی، Backend و SQLite آزمایشی را VERIFIED PASS می‌داند؛ سناریوی ۱۰۰ فروش، ۱۲۰ تولید، ۵ پرت، ۱۵ مازاد سالم، شش مرحلهٔ هزینهٔ واقعی، دو تسویهٔ مصنوعی، بازخوانی مستقل SQLite و Finance Draft بدون ثبت Journal را پوشش داده است. گزارش QA همچنین برای مجموعهٔ جاری سفارش 59/59 Python و 16/16 Edge و برای بستهٔ Integration مستقل 22/22 Python و 6/6 JavaScript ثبت می‌کند. این‌ها مجموعه‌های جدا هستند و جایگزین یکدیگر نیستند. Frozen UI و بانک واقعی همچنان آزموده نشده‌اند.

گیت‌های باز:

1. مسیر کامل سفارش در Frozen EXE واقعی.
2. QA مستقل هزینه، پرداخت، تأیید و Handoff.
3. آزمون حسابداری روی محیط آزمایشی مستقل و بدون دفترکل عملیاتی.
4. حفظ تفکیک آزمون‌های Backend/SQLite از پذیرش Frozen EXE و عدم ادعای تسویهٔ بانکی واقعی.

**معیار پایان:** سفارش خرید و فروش از درخواست تا تولید، هزینهٔ واقعی، پرداخت و آماده‌سازی سند مالی، در رابط واقعی و با کنترل مجوز قابل اجرا باشد.

### D1 — Data Platform / PostgreSQL

**وضعیت: PLAN ONLY؛ DB2 BLOCKED تا تصویب ADR معماری**

- Store اصلی حسابداری، سفارش، حافظهٔ Agent و ارتباط Madar در چند SQLite مستقل قرار دارند.
- در جست‌وجوی محدود سورس فعلی، ارجاعی به psycopg، asyncpg، PostgreSQL، DATABASE_URL یا Alembic پیدا نشد.
- پوشهٔ Migration/Alembic شناخته‌شده‌ای در Worktree پیدا نشد.
- هیچ مهاجرت یا سرویس PostgreSQL در این مأموریت انجام نشده است.
- محل استقرار Backend مرکزی (Office LAN یا Cloud) و سیاست آفلاین هنوز OPEN هستند.
- فقط DB0 read-only inventory و DB1 Repository contracts ایزوله مجاز به ادامه‌اند؛ DB2 pilot نباید شروع شود.

**معیار پایان:** Repository contract، پایلوت ایزوله PostgreSQL، مهاجرت آزمایشی قابل تکرار، تطبیق کامل داده و آزمون امنیت چندشرکتی موفق باشند. Cutover عملیاتی یک Gate جدا با تأیید کاربر است.

### P3 — AaaS Agent Engine

**وضعیت: IN PROGRESS / NOT ACCEPTED**

- Agent ابزارخوان واقعی و حافظهٔ SQLite نسخه‌دار، Audit و تأیید انسانی دارد.
- ابزارهای قاعده‌محور و حافظهٔ نسخه‌دار در QA گزارش‌شده موفق‌اند.
- مدل qwen3:4b در حدود 22 ثانیه Timeout شده و qwen3:0.6b در دو فراخوانی عملیاتی Fail-closed شده است.
- موتور Agent مبتنی بر مدل واقعی و اقدام مستقل BLOCKED است؛ مسیر قاعده‌محور را نباید خودمختاری LLM نامید.

**معیار پایان:** مدل واقعی روی درخواست‌های فارسی با کیفیت اندازه‌گیری‌شده، منبع داده، پیشنهاد قابل اصلاح، ابزارهای مجاز، حافظهٔ شرکتی و تأیید انسانی کار کند؛ خطا و Timeout باید ایمن مدیریت شوند.

### P4 — Madar Integration

**وضعیت: IN PROGRESS / NOT ACCEPTED**

- قرارداد خواندن احراز‌شده، TLS pin، Revision/CAS و Idempotency در سورس وجود دارد.
- Sync سفارش به وظیفهٔ Madar در سورس پیاده‌سازی شده است.
- قرارداد احراز هویت‌شده، TLS pin، CAS، Audit پایدار تلاش Sync و بازیابی Read-only در محیط ایزوله گزارش شده‌اند.
- MadarHost مجاز و قابل دسترس برای E2E واقعی در محیط آزمون موجود نبوده است؛ Gate عملیاتی BLOCKED است.

**معیار پایان:** روی Host آزمایشی مجاز، ایجاد/به‌روزرسانی و بازیابی Sync با هویت، ACL، Revision، رسید و بدون رکورد تکراری موفق باشد. دادهٔ مالی در Madar مرجع نمی‌شود.

### P5 — Operational Reliability

**وضعیت: NOT STARTED به‌عنوان پذیرش جامع**

- جداسازی Tenant و کاربر، نقش‌ها، نشست‌ها و Secretها.
- Backup، Restore Drill، نگهداری، پایش سلامت و گزارش خطا.
- رفتار قطع شبکه و حالت آفلاین، در صورت تأیید نیاز محصول.
- کنترل هم‌زمانی و تعارض چند کاربر.
- سیاست Update/Rollback و بازیابی بعد از Crash.

### P6 — Independent QA & Release Readiness

**وضعیت: 5/5 VERIFIED PASS در سطح سورس و دادهٔ آزمایشی؛ محصول NOT ACCEPTED**

QA مستقل پنج سناریوی تازه را با Fixtureهای جدا و بازخوانی مستقیم SQLite با 5/5 PASS گزارش کرده است. این نتیجه، QA مستقل در سطح سورس و دادهٔ آزمایشی را می‌بندد؛ اما Frozen EXE، مدل واقعی، Host زندهٔ Madar، چاپگر فیزیکی و بازیابی محیط تولید هنوز پذیرش نشده‌اند. نتیجه‌ها فقط یکی از این وضعیت‌ها باشند: VERIFIED PASS، VERIFIED FAIL، BLOCKED یا NOT TESTED.

### P7 — Controlled Rollout

**وضعیت: NOT STARTED**

پس از پذیرش کامل، بستهٔ امضاشده/قابل‌ردیابی، راهنمای کاربر، برنامهٔ Backup، نصب آزمایشی و Rollback آماده می‌شود. نصب، فعال‌سازی، مهاجرت دفتر واقعی و انتشار عمومی فقط با تأیید صریح کاربر انجام می‌شوند.

## 8. ترتیب اجرایی و وابستگی‌ها

1. P0: حفظ تغییرات، نقشهٔ مالکیت فایل و تثبیت Source Freeze.
2. P1 و P2: بستن مسیرهای Frozen EXE و پوشش تصمیمات کاربر؛ کارهای مستقل می‌توانند موازی باشند، اما ادغام باید کنترل‌شده باشد.
3. D1: تثبیت قراردادهای داده و Repository abstraction؛ سپس پایلوت PostgreSQL روی دادهٔ آزمایشی. تا قبل از این گیت، Storeهای SQLite جدید و پراکنده به‌عنوان معماری بلندمدت اضافه نشوند.
4. P3: تکمیل Agent روی قرارداد ابزار و Repository؛ inference مدل خارج از تراکنش DB انجام شود و پیشنهاد با Revision منبع ذخیره گردد.
5. P4: تکمیل Sync عملیاتی از طریق API و Outbox؛ هیچ درخواست شبکه‌ای داخل تراکنش DB باز نگه داشته نشود.
6. P5: آزمون چندکاربره، آفلاین در صورت نیاز، امنیت و بازیابی.
7. P6: QA مستقل کل جریان و Release Readiness.
8. P7: استقرار مرحله‌ای فقط پس از تأیید.

پیاده‌سازی موجود P2/P3/P4 حفظ می‌شود. این ترتیب به معنی بازنویسی آن‌ها از صفر نیست؛ ابتدا قرارداد و شکاف موجود اصلاح می‌شود.

## 9. قواعد مدیریت CoS

- Prime مالک محصول، اولویت، معماری، ادغام و گزارش نهایی است.
- حداکثر دو Worker پیاده‌سازی هم‌زمان، فقط وقتی Session و Run قابل‌شناسایی و بازیابی باشند.
- Workerها مالکیت فایل مشخص و خروجی آزمون‌پذیر داشته باشند.
- QA پس از ادغام مستقل باشد.
- کاربر واسطهٔ پیام Workerها نیست.
- در صورت self=null و run_id=null، Worker گم‌شونده نساز؛ کار مستقیم و ایمن را ادامه بده.
- Ledger بعد از هر تغییر معنادار با فرمان، Exit Code، نتیجه و محدودهٔ آزمون به‌روز شود.
- Build، تعداد تست یا پایان Worker به‌تنهایی معادل پذیرش محصول نیست.

## 10. کار بعدی

1. بستن Gate A با تعامل قابل اتکای WebView2 در Frozen EXE و اثبات Save/Edit/Reload/PDF؛ بدون دورزدن Bridge یا مجوز مالی.
2. بستن Gate C با ارزیابی مدل واقعی روی درخواست‌های فارسی مصنوعی، کنترل منبع/فیلدهای مفقود و Timeout محدود؛ تا آن زمان اقدام قاعده‌محور باید Human-reviewed بماند.
3. بستن Gate D فقط با MadarHost آزمایشی مجاز و قابل دسترس؛ بدون استفاده از داده یا Credential واقعی و بدون Retry کور پس از Lost ACK.
4. آزمون Windows Print Dialog روی EXE و چاپ فیزیکی فقط با چاپگر موجود و مجاز.
5. استقرارهای Office LAN، سرور اختصاصی، Cloud + Offline LAN Node و Cloud-only و سیاست Offline-First همگی **مصوب** هستند. باز بودن Financial Single Writer / Fencing، Conflict و RPO/RTO نباید با باز بودن تصمیم LAN-vs-Cloud اشتباه گرفته شود؛ ADR مرجع است.
6. DB2 پایلوت PostgreSQL فقط پس از بسته‌شدن گیت مرجع مالی، Fencing، Conflict، Tenant و Backup/RPO/RTO آغاز شود؛ DB0/DB1 می‌توانند مستقل و بدون دادهٔ زنده ادامه یابند.

**تعریف پایان کل محصول:** تمام فازهای لازم VERIFIED PASS شده باشند، QA مستقل انجام شده باشد، داده و امنیت قابل بازیابی باشند و بستهٔ نهایی READY FOR APPROVAL باشد. تا آن زمان وضعیت کل مأموریت IN PROGRESS یا NOT ACCEPTED است.

## 11. Gate A Frozen واقعی — بازیابی 2026-11-14

**وضعیت: PARTIAL VERIFIED / GATE A NOT ACCEPTED.**

- SHA256 کاندیدای نصب‌نشده `build-8ad80825928e` برابر `70eb46a3430985cca18aeaaf21339a2c7f49fca3f75066f091a8600d862dc512` و Freeze صد‌وچهل‌وپنج فایل برابر `96cd0132dff1c8769df0dc7e6454241bf61433b85abcb8efaa62730defd3138e` است؛ Build جدید برای اصلاح صرفاً ابزار QA ساخته نشد.
- **Verified Frozen:** محیط خصوصی WebView2، ایجاد Invoice `INV-1405-0001` به مبلغ ۱۳٬۵۰۰ ریال، Restart و ویرایش همان ID به ۱۸٬۰۰۰ با Revision دفترکل ۳→۴، بدون رکورد تکراری؛ ایجاد Proforma `PF-1405-0001` به مبلغ ۵٬۰۰۰، `createdBy` و `createdAt` از خود Frozen؛ ذخیره و بازخوانی قالب چاپ `QA FROZEN PRIVATE PRINT TEMPLATE`.
- **Verified Frozen order:** سفارش ساختگی با ۱۰۰ فروش، برنامهٔ تولید ۱۲۰ و یک مرحله (Revision ۱)، سپس ثبت دریافت آزمایشی ۵۰۰٬۰۰۰ ریالی فقط در پرونده سفارش (Revision ۲، وضعیت `recorded` و نه تسویه/بانک). دفترکل حسابداری در تمام این آزمون‌ها `journalCount=0` بود.
- **BLOCKED:** ویرایش Proforma در UIA حفظ مقادیر کنترل‌شده React را ثابت نکرد؛ هزینه واقعی سفارش به‌علت ناتوانی UIA در انتخاب تاریخ `type=date` ذخیره نشد؛ فراخوانی دکمه PDF مشاهده شد اما فایل خروجی در دایرکتوری دانلود خصوصی به دست نیامد. هیچ Save یا PDF صرفاً از روی Click ادعا نشده است.
- **Safe recovery:** تست قدیمی با Dialog کنارگذاشتن فرم آزمایشی به‌طور عادی بسته شد؛ هیچ Force Kill یا تغییر حسابداری واقعی/نصب انجام نشد. پروفایل خصوصی `qa-3edf86189818` و فایل‌های گزارش آن برای ممیزی نگه داشته شدند.
- **Parsian:** راه‌اندازی دفترکل جدید دیگر نیازمند شاهد ۶۰۸ رویداد شخصی نیست؛ همهٔ APIهای تاریخچهٔ شخصی همچنان `_source_guard` دارند. آزمون منفی Digest خراب، بدون اصلاح خودکار، Fail-closed است.
- سایر Gateهای Agent واقعی، MADAR عملیاتی، RADAR، Cloud Authority/Fencing، LAN چنددستگاهی، Backup/Restore، Rollback و چاپ فیزیکی **OPEN** می‌مانند؛ DB2 آغاز نشده است.

## 12. Frozen Gate A — نتیجهٔ جدید 2026-11-14

**وضعیت: VERIFIED PASS برای سناریوهای Windows Frozen + Synthetic، بدون مجوز نصب/انتشار و بدون پذیرش مالی عملیاتی.**
این نتیجه فقط وضعیت قدیمی بخش ۱۱ را برای Gate A و کاندیدای جدید جایگزین می‌کند؛ بقیهٔ Gateها باز می‌مانند.

- کاندیدای **نصب‌نشده**: `build-e13b4438f5d4`، SHA-256 فایل EXE:
  `300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3`.
  Source freeze: `73b692ca3b8790315a3c41be96960e059a06c6f9d6884cd8205edb1c2fe460c8`.
- UI واقعی Frozen + Bridge + بازخوانی SQLite خصوصی: ایجاد فاکتور جدید در Fixture تازه، ویرایش همان فاکتور به ۱۸٬۰۰۰ ریال؛ ایجاد پیش‌فاکتور و ویرایش همان ID از ۵٬۰۰۰ به ۷٬۵۰۰ ریال؛ ذخیره قالب چاپ؛ ایجاد سفارش با فروش ۱۰۰ و برنامه تولید ۱۲۰؛ هزینهٔ ثبت‌شده ۱۸۰٬۰۰۰ ریال با تاریخ `2026-11-14`؛ دریافتِ ثبت‌شدهٔ صرفاً داخلی ۵۰۰٬۰۰۰ ریال. گزارش‌های همهٔ این مراحل **PASS** هستند.
- PDF یک‌صفحه‌ای از Save As واقعی ویندوز در پوشه خصوصی تولید شد: ۵۶٬۴۶۲ بایت،
  SHA-256 `0413641cde01ee0d99692a21962f704e4ef916677a896fc8246cdf3444452466`،
  تصویر غیربلانک و بررسی بصری مطابق فاکتور ویرایش‌شده. گزارش خام فاز PDF اولیه BLOCKED باقی مانده و با گزارش جداگانه Save As تطبیق داده شده، نه اینکه بازنویسی شود.
- گزارش نهایی: `qa-8d2a2170c741/gate-a-synthetic-evidence-reconciled-20261114.json` با
  `PASS_FROZEN_GATE_A_SYNTHETIC_EVIDENCE_RECONCILED`، هشت فاز موفق، `journalCount=0`،
  و `financialEventCreated=false`. آزمون‌های منفی و رگرسیون source/Edge/native نیز Exit 0 داشتند.
- هیچ `Taraz.exe` فعال در بررسی پایان دیده نشد؛ نصب موجود تغییر نکرد؛ تراکنش بانکی،
  ثبت مالی رسمی، تغییر دادهٔ واقعی، چاپ فیزیکی، Publish یا Push انجام نشد.
- سند کامل شواهد و محدودیت‌ها: `docs/TARAZ_FROZEN_GATE_A_ACCEPTANCE_20261114.md`.
  Gateهای مالی رسمی، MadarHost زنده، Cloud Authority/Fencing، پشتیبان‌گیری/بازیابی، نصب عمومی و چاپ فیزیکی همچنان **OPEN** هستند؛ تأیید فنی Gate A را با Release Readiness یکسان ندانید.

## 13. AI Business Command Engine و مشاهدهٔ تغییرات — PLANNED

**وضعیت: PLANNED / NOT IMPLEMENTED / NOT ACCEPTED.** این درخواست در 2026-11-14 ثبت شده است. ماژول‌های فعلی Agent و Order Intake جایگزین این قابلیت کامل نیستند.

### AI-1: پیش‌نویس فاکتور با دستور فارسی

- کاربر بتواند در متن، مشتری، اقلام، تعداد، منبع قیمت و نوع سند را مشخص کند.
- AI فقط Intent را استخراج کند؛ هویت مشتری، کد کالا، واحد، ارز، مقدار و مالیات توسط APIهای دارای مجوز و قواعد قطعی بررسی شوند.
- برای «قیمت آخرین فاکتور»، نخست آخرین فاکتور معتبر همان مشتری با همان کالا/واحد/ارز انتخاب شود؛ شماره، تاریخ و قیمت مرجع نمایش داده شود. در نبود منبع معتبر، قیمت جعل نشود و تأیید کاربر خواسته شود.
- خروجی ابتدا Draft قابل ویرایش باشد؛ صدور رسمی یا Journal تنها با مجوز و تأیید انسانی انجام شود.

### AI-2: منابع MADAR و RADAR

- جزئیات تسک/پروژه مدار فقط از API مجاز با شناسه و Revision منبع وارد شود.
- اطلاعات مشتری رادار فقط پس از یافتن سورس/API واقعی و تعیین مالکیت اطلاعات استفاده شود؛ قابلیت ناشناخته را ساخته‌شده فرض نکن.
- ورودی‌های دستی کاربر نباید با Sync یا AI بی‌صدا بازنویسی شوند.

### AI-3: تکمیل اطلاعات شرکت از اینترنت

- در حالت آنلاین و با مجوز، اطلاعات عمومی شرکت با URL، تاریخ مشاهده و وضعیت تأیید پیشنهاد شود.
- دادهٔ یافت‌شده بدون تأیید به اطلاعات حقوقی، مالیاتی، بانکی یا حسابداری قطعی تبدیل نشود.
- در حالت آفلاین وب زنده وجود ندارد؛ اگر مدل Local فعال نباشد امکانات AI خاموش می‌شوند و فرم‌های دستی باید کامل کار کنند.

### AI-4: آزمون مستقل

- آزمون Provider آنلاین، Provider Local، AI Disabled، عدم مجوز، Timeout، جعل منبع، Revision و Idempotency.
- اثبات گردش‌کار UI → Agent → API → پایگاه آزمایشی و تأیید انسانی، شامل آزمون مستقل Frozen.

### Change visibility: What’s New داخل نرم‌افزار

**خواستهٔ کاربر:** کاربر باید تغییرات قابل دیدن را در نرم‌افزار بشناسد؛ Git و تعداد تست کافی نیست.

- هر نسخهٔ آزمایشی یک راهنمای فارسی «چه چیز جدید است؟» داشته باشد: صفحه/مسیر، قابلیت جدید، تصویر واقعی و مثال آزمایشی.
- تغییرات در چهار دسته نشان داده شوند: «در رابط قابل استفاده»، «فنی و پشت صحنه»، «آزمایشی/تأییدنشده» و «برنامه‌ریزی‌شده».
- Preview قابل مشاهده بدون نصب یا دسترسی به دادهٔ عملیاتی باشد. تصویر Mock باید صریحاً Mock نامیده شود.
- مقایسهٔ «نسخهٔ نصب‌شدهٔ 1.0.4» با کاندیدای جدید فقط پس از مشاهدهٔ واقعی هر دو انجام شود، نه حدس از Git Diff.
- صفحهٔ What's New و Preview یک قابلیت **PLANNED** است و هنوز در محصول تحویل نشده است.
- گالری مرور تصویریِ خارج از برنامه، فقط برای مشاهدهٔ اسکرین‌شات‌های واقعی QA، ساخته شد: `docs/TARAZ_VISUAL_CHANGELOG_20261114.html`. این گالری نه معادل What's New داخل اپ است و نه تأیید انتشار.

## 14. قرارداد اجباری به‌روزرسانی درجا و حفظ اطلاعات — APPROVED PRODUCT REQUIREMENT

**تصمیم کاربر (2026-11-14):** هر نسخهٔ جدید باید به‌شکل Update روی نسخهٔ قبلی نصب شود و **تمام اطلاعات و تنظیمات موجود را حفظ کند**. Fresh Install یا موفقیت EXE روی SQLite ساختگی، به‌تنهایی اثبات سازگاری Update نیست.

### الزامات غیرقابل مذاکره

1. آپدیت باید نصب قبلی را تشخیص دهد، مسیر داده و Profile/Company ID را حفظ کند و بدون پاک‌کردن یا جایگزین‌کردن پایگاه دادهٔ موجود، کد و فایل‌های برنامه را به‌روزرسانی کند.
2. مشتریان، کالاها، فاکتورها، پیش‌فاکتورها، سفارش‌ها، پرداخت‌ها، هزینه‌ها، Journal و Event History، شناسه و Revision، قالب‌های چاپ، تنظیمات شرکت و کاربران، مجوزها، حافظهٔ Agent، پیوندهای Madar، دادهٔ Sync/Outbox و تاریخچهٔ Audit باید پس از Update سالم و قابل بازیابی باقی بمانند؛ دامنهٔ دقیق Storeها قبل از اجرای Migration Inventory شود.
3. هر تغییر Schema با Migration نسخه‌دار، قابل تکرار و Idempotent انجام شود؛ روی نسخهٔ قبلی Backward Compatibility یا مسیر مهاجرت معتبر داشته باشد. اگر نسخه/Schema ناشناخته یا داده خراب بود، Update باید **ایمن متوقف شود** و داده را تعمیر یا بازنویسی خودکار نکند.
4. پیش از هر Migration، Backup کامل، قابل ردیابی و قابل Restore از همهٔ Storeهای مرتبط و تنظیمات ضروری گرفته شود. موفقیت Backup فقط بعد از Verify و حداقل یک Restore Drill ایزوله قابل پذیرش است.
5. اگر Update یا Migration شکست خورد، نسخهٔ عملیاتی قبلی و داده باید قابل بازیابی باشند؛ Rollback برنامه بدون Rollback سازگار Schema کافی نیست. هر Migration برگشت‌ناپذیر مستلزم مسیر Recovery مستقل و آزموده است.
6. آپدیت در شبکهٔ چندکاربره و Offline LAN باید کنترل نشست کاربران، Lock/Quiesce، توقف امن نوشتن، نسخهٔ مشترک Client/Server و ادامه‌دادن Outbox بدون Replay مالی تکراری را پوشش دهد؛ Update روی دادهٔ فعال و بدون حفاظت ممنوع است.
7. دادهٔ واقعی نباید برای تست Upgrade تغییر کند. آزمایش فقط با کپی کاملاً ایزولهٔ دادهٔ مصنوعی یا Backup مجاز انجام شود؛ نصب/آپدیت عملیاتی تنها پس از تأیید صریح مالک است.
8. Release Notes فارسی باید بین «نصب جدید» و «آپدیت از نسخهٔ قبلی» فرق بگذارد و بگوید چه چیزهایی حفظ می‌شوند، آیا Migration انجام می‌شود، حداقل نسخهٔ قابل ارتقا کدام است و چگونه Restore انجام می‌شود.

### Gate اجباری UPGRADE-DATA-PRESERVATION

- حداقل مسیر کنونی: `1.0.4 installed-profile clone → latest candidate`؛ سپس مسیرهای نسخه‌به‌نسخه و Skip-version پشتیبانی‌شده، مطابق ماتریس نسخه‌ها.
- Snapshot قبل و بعد از Update برای شمار/شناسه/Revision/Digest رکوردها، Journal و Event Replay، دادهٔ شرکت، تنظیمات، چاپ، سفارش و سایر Storeها مقایسه شود؛ هیچ رکورد یا مرجع موجود بی‌مجوز حذف یا جعل نشود.
- همان اطلاعات قدیمی از GUI نسخهٔ ارتقایافته باز شود، ویرایشِ آزمایشی ماندگار شود و بعد از Restart دوباره قابل بازخوانی باشد.
- آزمون قطع برق/Crash شبیه‌سازی‌شده، کمبود فضا، Migration ناموفق، Restart، نصب مجدد و Restore روی نسخهٔ ایزوله اجرا شود.
- در صورت فقدان شاهد، وضعیت Gate `NOT TESTED` یا `BLOCKED` و انتشار **NOT READY FOR APPROVAL** باقی بماند؛ هیچ‌کس حق ندارد صرفاً به دلیل PASS بودن Fresh Install، آپدیت را ایمن اعلام کند.

**وضعیت اجرا:** REQUIREMENT APPROVED؛ پیاده‌سازی و QA مسیر `1.0.4 → 1.0.6` در این نوبت انجام نشده و تا اثبات عملی، Gate باز است.

## 15. Upgrade 1.0.4 + AI Business Workspace — نتیجهٔ عملیاتی 2026-11-14

**Upgrade نصب‌شده: BLOCKED / بدون تغییر.** نسخهٔ فعال واقعاً `1.0.4` است. موجودی Metadata-only سه ریشه داده شامل ۱۸۱ فایل و ۶۷ SQLite است. ۱۳ آزمون ایزولهٔ حفاظت داده/Backup/Restore موفق شد؛ اما Backup جامع و Restore واقعی نسخهٔ نصب‌شده، Quiescence دیتابیس و Migration در محیط کپی‌شده اثبات نشد. لانچر نصب نهایی نیز هنوز به Build قدیمی‌تر اشاره دارد. بنابراین نسخه جدید نصب/فعال‌سازی نشد. تفصیل: `docs/TARAZ_UPGRADE_104_TO_106_GATE_20261114.md`.

**AI Chat Phase 1: SOURCE-HOSTED NATIVE PASS / FROZEN NOT TESTED.** در سورس، چت فارسی نسخه‌دار و رمزگذاری‌شده با DPAPI، تفکیک کاربر/شرکت، بازخوانی گفتگو پس از Restart و پیشنهاد فاکتور از قیمت آخرین فاکتور صادرشدهٔ همان مشتری پیاده‌سازی شد. ثبت فقط به شکل Draft بعد از تأیید انسانی از API رسمی انجام می‌شود. آزمون‌های Python و Native WebView2→Bridge→SQLite موفق‌اند؛ مدل محلی/آنلاین اجرا نشده، اتصال وب/MADAR/RADAR و بازیابی کلید بین دستگاه‌ها BLOCKED مانده‌اند. علاوه بر آن، لانچر معمولی هنوز هویت کاربر را احراز نمی‌کند، بنابراین دسترسی AI در آن **fail-closed** است. تفصیل: `docs/TARAZ_AI_CHAT_PHASE1_20261114.md`.

گیت کلی انتشار، چاپ فیزیکی و نصب روی داده واقعی همچنان **NOT READY FOR APPROVAL** است. مقایسه نسخه نصب‌شده با Preview در گالری یا سایر گزارش‌ها جایگزین Upgrade Acceptance نیست.
