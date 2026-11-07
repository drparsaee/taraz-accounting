# Taraz | Independent Accounting Desktop

Taraz is a Windows desktop accounting application, built independently from
Madar Task Manager. It uses a separate EXE, a separate build entrypoint
(accounting.html), and its own per-user SQLite profile.

## Source and runtime

- App entry: taraz_desktop.py
- UI entry: accounting.html -> src/standalone_main.jsx
- Accounting store: standalone_accounting.py
- Migration reader: personal_parsian_bridge.py
- Optional Madar metadata inbox: taraz_integration.py
- User data: %APPDATA%\Taraz
- Installed program: %LOCALAPPDATA%\Programs\Taraz
- User-owned Parsian archives: %LOCALAPPDATA%\Taraz\Parsian-Migration-20261107

No private SQLite book, Parsian BAK archive, user file, or secret belongs in
this Git repository. The existing user profile is not a development fixture.

## Build

    npm ci
    npm exec -- vite build
    py -3.12 -m PyInstaller --onefile --windowed --name Taraz \
        --icon=assets\taraz.ico --add-data="dist;dist" taraz_desktop.py

Only accounting.html is compiled. Madar's task main page is not an entrypoint.

## Integration boundary

Madar can explicitly queue a source-validated, limited metadata proposal to
%LOCALAPPDATA%\Madar-Taraz-Bridge\pending\<uuidhex>.json. Taraz can review
or reject that proposal. No monetary journal, invoice, receipt, or payment is
created by this integration; user decisions in native Taraz are authoritative.
No network connection is required and no automatic data sharing is enabled.

## Current limitations

This first Windows distribution is attached to the owner's migrated finance
ledger. A universal new-account onboarding workflow and standalone updater
have not yet been completed. The old task-manager source is not part of the
Taraz runtime, but some Python compatibility modules are retained locally
while the accounting dependencies are refactored.

## Interface aligned with Madar

Taraz uses Madar's Vitrea visual pattern without embedding the Madar
task-manager code: a glass top navigation capsule, left icon dock, grouped
keyboard-accessible navigation drawer, neutral/graphite cards, and separate
light/dark preferences (taraz-ui-theme). The accounting section model,
host authorization, invoices, journal entries and Parsian archive stay
independent. Layout switches to a horizontal bottom dock on narrow screens.

UX source: src/accounting_navigation_shell.jsx and
src/taraz_vitrea_shell.css. Regression coverage:
node --test tests/taraz_vitrea_shell.test.cjs.
