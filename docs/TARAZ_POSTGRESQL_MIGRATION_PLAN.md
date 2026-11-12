# TARAZ — PostgreSQL Migration Plan

**وضعیت:** PROPOSED / NOT IMPLEMENTED
**DB2 pilot gate:** BLOCKED until financial-authority/fencing, conflict, tenancy, backup and RPO/RTO decisions are approved in TARAZ_ARCHITECTURE_DECISIONS_20261112.md. LAN/Enterprise/Cloud+Offline-Node support and internet-independent core operations are approved requirements.
**هدف:** آماده‌کردن تراز برای سرویس مرکزی، چندکاربره و AaaS بدون از دست دادن قابلیت آفلاین احتمالی یا سابقهٔ مالی.

این سند برنامهٔ معماری و مهاجرت است؛ نه اعلام تصمیم نهایی میزبانی، نه اجرای مهاجرت و نه مجوز تغییر دفترهای واقعی.

## 1. تصمیم پیشنهادی

برای محصول نهایی AaaS چندکاربره، PostgreSQL باید مرجع مرکزی دادهٔ آنلاین باشد؛ اما کل SQLite فعلی نباید یک‌باره حذف شود.

معماری پیشنهادی:

**Taraz Desktop / Madar / Agent Tools → HTTPS Taraz Backend API → PostgreSQL**

- Desktop و WebView2 مستقیماً به PostgreSQL وصل نمی‌شوند.
- رمز DB و دسترسی Superuser داخل EXE یا کد Agent قرار نمی‌گیرد.
- Backend هویت و شرکت فعال را از نشست معتبر استخراج می‌کند؛ company_id ارسالی از مرورگر مرجع مجوز نیست.
- PostgreSQL مرجع رسمی دادهٔ آنلاین و چندکاربره می‌شود.
- SQLite محلی می‌تواند برای دادهٔ تجاری و Outbox گرهٔ مرکزی LAN استفاده شود؛ اما نباید هم‌زمان با PostgreSQL به دو مرجع رسمی متعارض تبدیل شود.
- قابلیت‌های اصلی تجاری در شبکهٔ مشتری بدون اینترنت الزامی‌اند. ثبت مالی رسمی آفلاین فقط در صورت اثبات Authority/Lease و سیاست Fencing مجاز است؛ وگرنه عملیات حساس Pending/Review باقی می‌مانند. قاعدهٔ جزئی انتقال Authority هنوز OPEN است.

**استقرارهای مصوب:** LAN Host کوچک، سرور اختصاصی مشتری، Cloud و Cloud با Offline Node مرکزی در LAN مشتری. انتخاب استقرار در زمان نصب با مشتری است؛ صرف وجود اینترنت یا قطع آن اجازهٔ تغییر خودکار مرجع رسمی مالی نیست.

## 2. شواهد معماری فعلی

**نتیجهٔ جدید DB0/DB1 — 2026-11-12:** ماژول taraz_repository_contracts.py
خواندن ID، Revision و Digest سفارش از Store رسمی SQLite را جدا کرده است.
تست tests.test_taraz_ecosystem_db0_db1_20261112 پنج Store واقعاً ساخته‌شده
با دادهٔ مصنوعی را از نظر Schema و user_version بررسی کرده و تغییر
Revision/Digest را پس از ویرایش اثبات می‌کند. این کار مهاجرت اصلی،
Accounting Writer Repository، یکپارچگی کل داده‌های تاریخی، یا برابری
Event Replay نیست. شرح مرز: TARAZ_ECOSYSTEM_SOURCE_AND_CONTRACT_20261112.md.
Outbox جدید Sender/Inbox معتبر شبکه‌ای ندارد و صرفاً قرارداد محلی پایدار
و وضعیت OUTCOME_UNKNOWN و Receipt را نگه می‌دارد.

بررسی محدود سورس Worktree در 2026-11-12 این Storeها را نشان داد:

| دامنه | فایل فعلی | ساختار و رفتار مشاهده‌شده |
| --- | --- | --- |
| حسابداری اصلی | standalone_accounting.py | SQLite؛ جدول standalone_accounting با یک ردیف شامل revision، state و digest؛ state یک JSON canonical حاوی eventها است؛ schema version 1، WAL، synchronous FULL، BEGIN IMMEDIATE و CAS |
| سفارش | taraz_order_store.py | فایل per-company به نام taraz-orders.sqlite3؛ schema version 2؛ جدول‌های orders، actions، audit، order_costs، order_payments و order_finance_handoffs |
| حافظه Agent | taraz_aaas_agent.py | فایل per-company به نام taraz-agent-memory.sqlite3؛ schema version 1؛ entries، commands، revisions و audit؛ پیشنهاد/قبول/رد با Revision و Idempotency |
| اتصال پروژه مدار | taraz_madar_order_link.py | فایل per-company به نام taraz-madar-order-links.sqlite3؛ schema version 1؛ links، commands و audit؛ ذخیرهٔ TLS fingerprint و Host state revision |
| Sync مدار | taraz_madar_order_sync.py | HTTPS با TLS pin، CAS و Idempotency؛ عملیات خارجی باید از تراکنش محلی جدا بماند |
| داده‌های تاریخی پارسیان | parsian archive/bridge modules | منابع جانبی و خواندنی؛ بخشی از آن‌ها نباید بدون دامنه و مجوز جداگانه به دفتر جدید منتقل شوند |
| Storeهای MTR و امنیت | چند ماژول جانبی | باید جداگانه طبقه‌بندی شوند؛ همهٔ SQLiteها الزاماً دادهٔ کسب‌وکار نیستند و نباید کورکورانه مهاجرت کنند |

### جزئیات مهم حسابداری

Store اصلی حسابداری یک جدول Relational معمولی از فاکتورها و سطرها نیست. یک ردیف، نسخه و Snapshot canonical JSON را همراه SHA-256 نگه می‌دارد و منطق حسابداری، زنجیرهٔ eventها را از روی آن Replay و Validate می‌کند. مهاجرتی که فقط چند جدول فاکتور بسازد، ممکن است تاریخچه، ترتیب، Revision و معنای Replay را از بین ببرد.

### وضعیت پشتیبانی PostgreSQL در سورس

در جست‌وجوی محدود Worktree برای psycopg، asyncpg، PostgreSQL، DATABASE_URL و Alembic نتیجه‌ای پیدا نشد؛ پوشهٔ Migration/Alembic شناخته‌شده نیز پیدا نشد. این نتیجه فقط دربارهٔ سورس بررسی‌شده است و دربارهٔ سرویس‌های بیرونی یا نصب‌های دیگر ادعا نمی‌کند.

در زمان این بررسی، مهاجرت، Driver، Connection Pool، Schema Migration یا سرویس PostgreSQL در این Worktree احراز نشده‌اند.

## 3. اصول معماری هدف

### 3.1 مرز دسترسی

1. UI و Agent فقط APIهای مجاز Taraz را فراخوانی کنند.
2. Backend تنها لایه‌ای باشد که به PostgreSQL متصل می‌شود.
3. Driver و Secret پایگاه داده فقط در محیط Backend نصب و نگهداری شوند.
4. نقش Migration از نقش Runtime جدا باشد.
5. هیچ Query خامی از مرورگر یا Prompt مدل به DB راه پیدا نکند.

### 3.2 جداسازی شرکت‌ها

- تمام داده‌های کسب‌وکار باید کلید Tenant/Company داشته باشند.
- Tenant از نشست احراز هویت‌شده در Backend استخراج شود، نه از مقدار دلخواه Client.
- Row-Level Security در PostgreSQL به‌عنوان دفاع لایهٔ دوم فعال شود.
- Backend در هر تراکنش، Company context را به‌شکل transaction-local تنظیم کند.
- نقش Runtime مالک جدول یا Superuser نباشد؛ RLS برای نقش واقعی برنامه نیز اعمال شود.
- آزمون منفی باید ثابت کند کاربر شرکت A نمی‌تواند دادهٔ شرکت B را بخواند یا تغییر دهد.

### 3.3 صحت مالی

- مبالغ فعلی به‌صورت Integer و همراه Currency نگهداری شوند؛ برای مدل فعلی BIGINT کافی است، ولی سقف‌های Domain باید مستقل اعتبارسنجی شوند.
- RIAL و TOMAN دو واحد مستقل باقی بمانند؛ هیچ تبدیل ضمنی یا Float مجاز نیست.
- مقدار نامشخص NULL است و صفر معنای مستقل دارد.
- Revision، Idempotency و تأیید انسانی حفظ شوند.
- Eventهای مالی Append-only بمانند؛ اصلاح با Event/سند اصلاحی مجاز انجام شود، نه بازنویسی تاریخچه.
- زمان‌ها در Backend به UTC ذخیره و منطقهٔ زمانی شرکت برای نمایش نگهداری شود.

### 3.4 تراکنش و عملیات خارجی

- تغییر وضعیت سفارش، ثبت/تأیید هزینه، پرداخت، Handoff و ایجاد Draft حسابداری باید تراکنش‌های اتمیک و Revision-aware داشته باشند.
- درخواست مدل AI خارج از تراکنش DB اجرا شود. نتیجه به Revision و Digest منبع متصل شود؛ در صورت تغییر منبع، پیشنهاد منقضی گردد.
- درخواست شبکه‌ای Madar داخل تراکنش باز PostgreSQL اجرا نشود.
- برای Sync از Transactional Outbox و Receipt/Idempotency استفاده شود.
- تکرار درخواست پس از Timeout نباید پرداخت، سند یا Task تکراری ایجاد کند.

## 4. مدل دادهٔ پیشنهادی

این مدل منطقی است؛ نام و نوع نهایی جدول‌ها پس از طراحی Schema و پایلوت تعیین می‌شود.

| دامنه | موجودیت‌های پیشنهادی | ملاحظات |
| --- | --- | --- |
| هویت | companies، users، memberships، roles، permissions، sessions | Company context فقط از هویت معتبر |
| حسابداری | accounting_state، accounting_events یا event projection، accounting_snapshots | ابتدا حفظ Snapshot canonical و Digest فعلی؛ Normalization فقط پس از Replay parity |
| طرف حساب | parties، party_identifiers | جلوگیری از مشتری/تأمین‌کنندهٔ تکراری در محدودهٔ شرکت |
| فاکتور | invoices، invoice_lines، invoice_events، print_templates | Draft و Issued از هم جدا؛ تاریخچهٔ immutable |
| سفارش | orders، order_lines، order_costs، order_payments، order_finance_handoffs، order_actions، order_audit | حفظ مدل واقعی فعلی، CAS و Idempotency |
| Agent | agent_runs، agent_proposals، agent_memory_entries، agent_memory_reviews، tool_invocations، agent_audit | منشأ، Revision، وضعیت قبول/رد و Company scope |
| تأیید | approvals، approval_events | هویت، نقش، زمان، Digest سند و دامنهٔ مجوز |
| Madar | madar_links، sync_outbox، sync_receipts، sync_conflicts | Host revision، TLS pin، Idempotency و بازیابی |
| اسناد و فایل‌ها | document_metadata، attachment_metadata | فایل‌های بزرگ در Object/File Storage امن؛ Hash و ACL در DB |
| عملیات | schema_migrations، idempotency_records، audit_events، backup_runs | پایش، بازیابی و ممیزی |

## 5. سازگاری با ساختار فعلی

### 5.1 حسابداری

مرحلهٔ اول نباید فرمت فعلی Event Store را بی‌دلیل تغییر دهد:

- یک جدول سازگاری مانند accounting_state با company_id، revision، canonical payload bytes، digest و updated_at ایجاد شود.
- در هر تراکنش، Revision مورد انتظار بررسی و Snapshot جدید به‌صورت اتمیک جایگزین شود.
- Digest از همان canonical bytes فعلی محاسبه و دوباره اعتبارسنجی شود.
- در مرحلهٔ اول می‌توان Eventها را برای جست‌وجو در جدول Projection جداگانه منعکس کرد؛ Projection منبع رسمی حقیقت نیست.
- Replay از روی Snapshot مهاجرت‌یافته باید همان View و همان نتیجهٔ مالی را تولید کند.
- تبدیل Event Store به جدول‌های نرمال‌شده فقط در ADR جدا و پس از اثبات برابری معنایی مجاز است.

### 5.2 سفارش

- orders.data_json فعلی باید بدون حدس به JSONB یا ساختار Relational کنترل‌شده نگاشت شود.
- status، revision، created_at و updated_at حفظ شوند.
- order_costs و order_payments به‌صورت موجودیت‌های مستقل باقی بمانند.
- actions و audit به جداول Idempotency و Audit مهاجرت کنند.
- order_finance_handoffs با Digest و Source Revision حفظ شود.
- هزینهٔ تخمینی، هزینهٔ ثبت‌شده و هزینهٔ تأییدشده هرگز با هم ادغام نشوند.
- Payment planned، recorded و settled معناهای جدا دارند؛ وضعیت بانکی از روی متن یا مرجع تراکنش جعل نشود.

### 5.3 حافظه Agent

- Company scope، source_revision، source_digest، normalized_digest و وضعیت proposed/accepted/rejected حفظ شوند.
- Revision حافظه و Audit قابل Replay باشند.
- Memory پذیرفته‌شده فقط وقتی به‌روز است که Revision و Digest منبع آن معتبر باشد.
- حافظهٔ یک شرکت به Agent شرکت دیگر نشت نکند.

### 5.4 ارتباط Madar

- شناسه سفارش، شناسه پروژه، Revision سفارش، Revision Host، Actor، URL و TLS fingerprint حفظ شوند.
- لینک قدیمی بدون احراز مجدد Host به‌عنوان عضویت جاری تلقی نشود.
- Sync Outbox و Receipt وضعیت‌های pending، delivered، conflict و retry را قابل ممیزی کنند.
- تغییر پروژه یا Host state بدون Reconciliation مجاز نباشد.

### 5.5 منابع تاریخی و Storeهای جانبی

- Archiveهای Parsian و داده‌های شخصی/قدیمی در دامنهٔ مهاجرت اصلی فرض نمی‌شوند.
- Storeهای MTR، Witness، Receipt، Peer و Security ابتدا از نظر مالکیت، چرخهٔ عمر و حساسیت طبقه‌بندی شوند.
- فایل‌های SQLite آزمایشی و Fixture اصلاً دادهٔ قابل مهاجرت نیستند.

## 6. فازهای اجرای مهاجرت

### DB0 — تصمیم معماری و موجودی داده

خروجی:

- انتخاب توپولوژی: Office LAN، Managed Cloud یا استقرار مستقل برای هر مشتری.
- تصمیم نیاز آفلاین: فقط خواندن، Draft محلی، یا صف فرمان‌های آفلاین.
- مدل Tenant: پایگاه مشترک با RLS یا Database جدا برای مشتریان خاص.
- سیاست نگهداری، محل داده، رمزنگاری، RPO و RTO.
- فهرست کامل تمام فایل‌ها، Schema versionها، حجم، شرکت مالک و حساسیت داده.

**Gate:** تصمیم میزبانی و رفتار آفلاین تأیید شده و مالکیت داده مشخص باشد.

### DB1 — قرارداد Repository

برای Accounting، Orders، Agent Memory، Madar Links و Audit، Interfaceهای مستقل تعریف شود.

- SQLite Adapter فعلی حفظ شود.
- Business Logic از SQL و نوع Driver جدا شود.
- Contract Test مشترک برای هر Adapter نوشته شود.
- Revision، Idempotency، transaction boundary و error mapping در قرارداد مشخص شوند.
- UI و Agent هیچ وابستگی مستقیمی به SQLite یا PostgreSQL نداشته باشند.

**Gate:** همان Contract Testها روی SQLite فعلی پاس شوند و رفتار محصول تغییر نکند.

### DB2 — PostgreSQL Pilot ایزوله

**Entry gate: BLOCKED. Do not provision or start this pilot until ADR-TARAZ-001
(Office LAN vs Cloud) and ADR-TARAZ-002 (offline policy) have explicit,
user-approved decisions recorded in docs/TARAZ_ARCHITECTURE_DECISIONS_20261112.md.**

- محیط PostgreSQL توسعه/QA با نسخهٔ پشتیبانی‌شده و TLS راه‌اندازی شود.
- Driver سمت Backend انتخاب شود؛ پیشنهاد اولیه psycopg 3 است.
- Migration tooling انتخاب شود؛ پیشنهاد اولیه Alembic یا SQL Migrationهای نسخه‌دار است.
- انتخاب نهایی پس از آزمون Python 3.12، PyInstaller boundaries، Backup و Restore انجام شود.
- Desktop EXE نباید Secret یا Connection مستقیم PostgreSQL دریافت کند.
- Roleهای migration، runtime و read-only جدا باشند.

**Gate:** اتصال، Migration، Rollback schema، TLS و دسترسی حداقلی در محیط ایزوله اثبات شود.

### DB3 — Schema و امنیت Tenant

- Schema نسخه‌دار ایجاد شود.
- Foreign Key، Unique Constraint، Check Constraint و Indexها طراحی شوند.
- RLS و آزمون منفی cross-tenant پیاده شود.
- تراکنش‌های Revision/CAS و Idempotency در PostgreSQL بازتولید شوند.
- Audit و Event history در برابر Update/Delete عادی محافظت شوند.
- Pool، Timeout، Connection leak و Lock wait اندازه‌گیری شوند.

**Gate:** تست‌های امنیت، هم‌زمانی و سازگاری Contract موفق باشند.

### DB4 — Export/Import آزمایشی

- از Clone آزمایشی و دادهٔ ساختگی استفاده شود.
- Snapshot و Manifest شامل نام منبع، Schema version، تعداد رکورد، Revision و Hash ساخته شود.
- داده‌ها به PostgreSQL آزمایشی وارد شوند.
- هیچ منبع SQLite اصلی تغییر یا حذف نشود.
- فرآیند Export/Import باید تکرارپذیر و Idempotent باشد.

**Gate:** تطبیق کامل داده و Replay بدون اختلاف.

### DB5 — Reconciliation و آزمون خرابی

موارد زیر مقایسه شوند:

- تعداد و شناسهٔ شرکت‌ها، طرف حساب‌ها، فاکتورها و سفارش‌ها.
- Revision و Digest دفترهای حسابداری.
- Replay تمام Eventها و View نهایی.
- هزینه‌های واقعی، تأییدها، پرداخت‌ها و Handoffها.
- حافظهٔ Agent و وضعیت پیشنهادها.
- لینک‌ها و رسیدهای Madar.
- تاریخ‌ها، واحد پول، NULL در برابر صفر و رشته‌های فارسی.

آزمون‌های منفی:

- دو Writer هم‌زمان روی Revision یکسان.
- تکرار Idempotency Key با Payload متفاوت.
- قطع اتصال وسط Transaction.
- Restart Backend هنگام Outbox pending.
- تلاش دسترسی Tenant دیگر.
- Restore از Backup و بررسی Point-in-Time Recovery.

**Gate:** هیچ اختلاف توضیح‌نداده‌شده‌ای در داده، حسابداری یا مجوز باقی نماند.

### DB6 — Shadow Read و Pilot

- ابتدا Read-only comparison بین SQLite و PostgreSQL انجام شود.
- در این مرحله Dual-write روی دادهٔ واقعی ممنوع است.
- یک شرکت آزمایشی یا Tenant پایلوت انتخاب شود.
- Backend به‌صورت کنترل‌شده فقط برای همان Pilot به PostgreSQL وصل شود.
- همهٔ فرمان‌ها، خطاها و Reconciliationها قابل ممیزی باشند.

**Gate:** Pilot بدون اختلاف داده، نقض Tenant یا رویداد مالی تکراری کار کند.

### DB7 — Offline Mode اختیاری

فقط اگر نیاز محصول تأیید شد:

- SQLite محلی Cache و Outbox را نگه دارد.
- هر فرمان آفلاین شناسهٔ Idempotency، Actor، Company، زمان و Revision پایه داشته باشد.
- Sync پس از اتصال با CAS انجام شود.
- تعارض به صف بررسی انسانی برود؛ Last-write-wins ممنوع.
- عملیات رسمی مالی تا تأیید Backend مرکزی Pending بماند.

**Gate:** قطع و وصل شبکه، تکرار Sync و تعارض چند دستگاه بدون از دست‌رفتن یا دوباره‌ثبت‌شدن داده آزموده شوند.

### DB8 — Cutover کنترل‌شده

این فاز فقط با مجوز صریح کاربر:

1. Backup کامل و تأیید Restore.
2. توقف کنترل‌شدهٔ نوشتن در منبع قدیمی.
3. Export نهایی و Import در PostgreSQL.
4. تطبیق Hash، Revision، Event Replay و شمارش داده.
5. تغییر تنظیم Backend به PostgreSQL.
6. Smoke Test و کنترل دفترکل.
7. پایش خطا و آماده‌بودن برنامهٔ برگشت.
8. عدم حذف SQLite قدیمی تا پایان دورهٔ پذیرش و تأیید Backup.

**Gate:** تأیید صریح Cutover و نتیجهٔ موفق Reconciliation.

## 7. سیاست Rollback

- پیش از Cutover، SQLite منبع اصلی باقی می‌ماند و PostgreSQL فقط محیط آزمایشی است.
- در Pilot، دادهٔ آزمایشی و Tenant پایلوت باید جدا و قابل حذف/بازسازی باشد.
- پس از پذیرش نوشتن دادهٔ واقعی در PostgreSQL، برگشت ساده به فایل SQLite قدیمی امن نیست؛ ممکن است آخرین عملیات را از دست بدهد.
- Rollback پس از Cutover فقط در صورت وجود Reverse Migration یا Replay تأییدشده‌ای مجاز است که تمام Writeهای پذیرفته‌شده را حفظ کند.
- اگر حفظ Writeها اثبات نشده، گزینهٔ امن Forward Fix یا توقف نوشتن و بازیابی کنترل‌شده است؛ نه تعویض کورکورانهٔ Connection String.

## 8. امنیت و عملیات

- PostgreSQL روی شبکهٔ خصوصی بماند؛ Port پایگاه داده برای اینترنت عمومی باز نشود.
- ارتباط Client با Backend و Backend با DB با TLS باشد.
- Secretها در Credential Store/Secret Manager نگهداری شوند؛ در فایل، Log یا EXE قرار نگیرند.
- Runtime DB role حداقل مجوز لازم را داشته باشد.
- Migration با حساب جدا و در زمان کنترل‌شده انجام شود.
- Backup رمزگذاری‌شده، نسخهٔ خارج از Host و Restore Drill منظم لازم است.
- WAL archiving و PITR بر اساس RPO/RTO مصوب طراحی شوند.
- Health check، Connection pool، Query latency، Lock wait، Backup age و Outbox backlog پایش شوند.

## 9. معیار پذیرش PostgreSQL

مهاجرت فقط زمانی پذیرفته می‌شود که:

1. Inventory کامل و مالکیت تمام Storeها مشخص باشد.
2. دادهٔ اصلی بدون حذف، جعل یا تبدیل واحد منتقل شود.
3. Digest، Revision، Event Replay و View مالی برابر باشند.
4. Order costs/payments و تأییدها دقیقاً حفظ شوند.
5. حافظهٔ Agent و Audit آن با Tenant scope حفظ شوند.
6. لینک‌ها و وضعیت Sync مدار قابل بازیابی باشند.
7. آزمون چندکاربره، CAS، Idempotency و RLS موفق باشد.
8. Backup Restore و PITR عملاً آزموده شده باشند.
9. Desktop و Agent هیچ Credential مستقیم DB نداشته باشند.
10. Rollback داده‌حافظ و مستند باشد.
11. QA مستقل گزارش قابل بازبینی ارائه کند.
12. Cutover عملیاتی فقط پس از تأیید صریح کاربر انجام شود.

## 10. تصمیم‌های باز پیش از DB2

دو تصمیم اجباری هنوز OPEN هستند و نباید از پیشنهادهای قبلی استنباط شوند:

1. **میزبانی Backend مرکزی:** Office LAN/local host یا Cloud/managed hosting.
2. **سیاست آفلاین:** online-only، read-only cache، Draft محلی Pending یا صف محدود فرمان‌ها.

جزئیات گزینه‌ها، محدودیت‌های موجود LAN/MadarHost، معیارهای تصمیم و وضعیت مجاز
هر فاز در docs/TARAZ_ARCHITECTURE_DECISIONS_20261112.md ثبت شده است.

تا ثبت تصمیم صریح کاربر، DB2 متوقف است. DB0 موجودی‌برداری Read-only و DB1
قراردادهای Repository ایزوله می‌توانند ادامه پیدا کنند.

موارد تکمیلی لازم پیش از طراحی نهایی DB2:

3. **Tenant isolation:** پایگاه مشترک با RLS یا DB جدا برای هر شرکت؛ پیشنهاد
   Shared Schema + tenant_id + RLS فقط گزینهٔ اولیه است، نه تصمیم مصوب.
4. **اهداف بازیابی:** RPO/RTO قابل قبول برای دفتر مالی و سرویس Agent.

## 11. کارهای ممنوع در این برنامه

- جایگزینی یک‌بارهٔ تمام SQLiteها با PostgreSQL.
- Dual-write هم‌زمان در دو منبع رسمی.
- انتقال دادهٔ شخصی Parsian یا Archive بدون دامنه و مجوز جداگانه.
- قراردادن رمز DB داخل EXE یا Agent Prompt.
- بازکردن مستقیم PostgreSQL برای Desktop Clientها.
- حذف فایل SQLite بعد از Import بدون Reconciliation و Restore Drill.
- ادعای مهاجرت موفق صرفاً با سبزشدن Build یا تعداد رکوردها.
- مهاجرت یا Cutover روی دادهٔ واقعی بدون تأیید صریح کاربر.

**نتیجه:** PostgreSQL مقصد پیشنهادی برای مرجع مرکزی چندکاربره است؛ SQLite فعلی تا پایان پایلوت و تأیید مهاجرت حفظ می‌شود. این برنامه هنوز اجرا نشده است.
