# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for HistogramFAdeA (one-dir build).
# Produces:  dist/HistogramFAdeA/HistogramFAdeA.exe   (+ _internal/)
# Consumed by installer.iss  (SourceDir = "dist\HistogramFAdeA").
#
# Build:  .\.venv\Scripts\pyinstaller.exe HistogramFAdeA.spec --noconfirm

from PyInstaller.utils.hooks import collect_all

# Bundle data files (fonts, templates) for packages whose default hooks
# may miss them, so HTML/PDF export works in the frozen app.
datas, binaries, hiddenimports = [], [], []
for pkg in ("xhtml2pdf", "reportlab", "svglib"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Backends / submodules imported indirectly that PyInstaller can miss.
hiddenimports += [
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_svg",
    "scipy.stats",
    "PyQt5.sip",
]

a = Analysis(
    ["histogram.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HistogramFAdeA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                 # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="histogram_icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HistogramFAdeA",
)
