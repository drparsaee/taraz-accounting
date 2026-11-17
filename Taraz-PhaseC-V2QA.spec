# -*- mode: python ; coding: utf-8 -*-
# Disposable QA artifact only, not an installer or installed product.

a = Analysis(
    ['taraz_desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=[('dist-phase-c-worker7-qa', 'dist')],
    hiddenimports=['taraz_ecosystem_mailbox_recovery', 'taraz_ecosystem_mailbox_peer',
                   'taraz_ecosystem_mailbox_consent'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Taraz-PhaseC-V2QA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['public/favicon.ico'],
)
