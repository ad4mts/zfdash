# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


# Cross-distro compatibility: Exclude binaries that conflict with host systems
EXCLUDED_PATTERNS = [
    'libxkbcommon',          # Incompatible with Fedora's keymap definitions
    'platforminputcontexts', # Input method plugins (ibus/compose) causing ABI mismatches
]

a.binaries = [
    x for x in a.binaries 
    if not any(pattern in x[0] for pattern in EXCLUDED_PATTERNS)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='zfdash',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='zfdash',
)
