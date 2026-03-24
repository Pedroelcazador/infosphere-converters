# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec voor Infosphere Converters
# Gebruik: pyinstaller infosphere.spec --clean

from pathlib import Path

ROOT = Path(SPECPATH)

# ---------------------------------------------------------------------------
# Data-bestanden: alles wat niet als Python-import wordt gevonden
# ---------------------------------------------------------------------------
datas = [
    # HTML-template voor de web UI
    (str(ROOT / 'web_ui_template.html'), '.'),
    # README (voor de ? Help knop)
    (str(ROOT / 'README.md'), '.'),
    # Converter-scripts (worden via importlib geladen, niet als imports)
    (str(ROOT / 'ds_convert'  / 'ds_convert.py'),  'ds_convert'),
    (str(ROOT / 'ds_flow'     / 'ds_flow.py'),      'ds_flow'),
    (str(ROOT / 'ds_job_flow' / 'ds_job_flow.py'),  'ds_job_flow'),
    (str(ROOT / 'ldm_convert' / 'ldm_convert.py'),  'ldm_convert'),
    (str(ROOT / 'dbm_convert' / 'dbm_convert.py'),  'dbm_convert'),
    (str(ROOT / 'msl_convert' / 'msl_convert.py'),  'msl_convert'),
    (str(ROOT / 'msl_lineage' / 'msl_lineage.py'),      'msl_lineage'),
    (str(ROOT / 'msl_lineage' / 'lineage_template.html'), 'msl_lineage'),
    # Gedeelde module (geïmporteerd door converter-scripts via sys.path)
    (str(ROOT / 'md_to_html.py'),  '.'),
    (str(ROOT / 'converters.py'),  '.'),
    (str(ROOT / 'version.py'),     '.'),
]

# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------
a = Analysis(
    [str(ROOT / 'web_ui.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],      # alleen stdlib — geen pip-packages nodig
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
    name='infosphere-converters',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX uitgeschakeld: betrouwbaarder op UWV-machines
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # geen zwart terminal-venster bij dubbelklikken
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
