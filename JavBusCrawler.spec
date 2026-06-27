# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\5A5851\\Desktop\\新建文件夹 (10)\\javbus_crawler.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'selenium.webdriver.edge.webdriver',
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.edge.service',
        'selenium.webdriver.chrome.service',
    ],
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
    name='JavBusCrawler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
