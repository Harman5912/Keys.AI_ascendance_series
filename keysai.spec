# -*- mode: python ; coding: utf-8 -*-
# Keys.ai - ACENDENCE VII [GEN I] - PyInstaller spec (optimized build).
#
# Notes:
#  - Heavy tool dependencies (cv2, numpy, mss, pyautogui, pywinauto, playwright,
#    easyocr, python-docx/pptx, google SDKs) are imported lazily at runtime, but
#    PyInstaller still collects them so the frozen app keeps every feature.
#  - Dev/test/legacy packages are excluded to shrink the bundle.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('core/prompt.txt', 'core'),
        ('config/api_keys.json', 'config'),
        ('config/certs', 'config/certs'),
        ('config/personality.json', 'config'),
        ('config/entities.json', 'config'),
        ('workspace', 'workspace'),
        ('icon.png', '.'),
    ],
    hiddenimports=[
        'google.genai',
        'sounddevice',
        'psutil',
        'pywinauto',
        'pyautogui',
        'pygetwindow',
        'mss',
        'cv2',
        'numpy',
        'easyocr',
        'PIL',
        'docx',
        'pptx',
        'youtube_transcript_api',
        'duckduckgo_search',
        'send2trash',
        'win10toast',
        'fastapi',
        'uvicorn',
        'cryptography',
        'personality',
        'personality.humor',
        'personality.workspace',
        'language',
        'language.spell_corrector',
        'language.entity_resolver',
        'language.semantic_parser',
        'skills.registry',
        'brain.intelligence',
        'whatsapp',
        'whatsapp.selenium_client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtMultimedia',
        'PyQt6.QtSvg',
        'IPython',
        'jupyter',
        'pytest',
        'unittest',
        'test',
        'pydoc_data',
        'pydoc',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KeysAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='icon.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KeysAI',
)
