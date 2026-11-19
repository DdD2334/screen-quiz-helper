# -*- mode: python ; coding: utf-8 -*-
"""pack.spec — screen-quiz-helper 精简打包定义。

只保留运行必需：
  Qt 模块：Core / Gui / Widgets / Network（QLocalServer 单实例）+ 基础平台/图片插件
  翻译：仅 qtbase_zh_CN（其余 313 个语言包不打）
裁掉：QtQml/Quick/OpenGL/Pdf/Svg/虚拟键盘、opengl32sw(19.7MB)、开发期模块
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# ---- OpenSSL 修正：PATH 上有 MySQL 的 libssl/libcrypto（OpenSSL 3.0），
#     会先于 Python 自带的 3.5 被解析进包，导致 _ssl 导入时报
#     "DLL load failed ... 找不到指定的程序"。强制改用 Python 自带版本。
_OPENSSL = ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
_DLL_DIR = os.path.join(sys.base_prefix, "DLLs")
_openssl_low = {n.lower() for n in _OPENSSL}

# 需要保留的 Qt 翻译文件
_KEEP_TRANSLATIONS = {"qtbase_zh_CN.qm"}

# 二进制/插件裁剪关键字（小写、正斜杠匹配）
_DROP_KEYS = (
    "qt6qml", "qt6quick", "qt6opengl", "qt6pdf", "qt6svg", "qt6virtualkeyboard",
    "opengl32sw",
    "qsvg", "qpdf", "qoffscreen", "qminimal", "qdirect2d",
    "qnetworklistmanager", "qtuiotouchplugin", "qtvirtualkeyboardplugin",
    "qt6printsupport", "qt6sql", "qt6test", "qt6webengine", "qt6multimedia",
)


def _drop(name: str) -> bool:
    low = name.replace("\\", "/").lower()
    if "/translations/" in low:
        return os.path.basename(low) not in {t.lower() for t in _KEEP_TRANSLATIONS}
    return any(k in low for k in _DROP_KEYS)


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["keyboard"] + collect_submodules("mss"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "setuptools", "pkg_resources", "pip", "IPython", "tkinter",
        "numpy", "pandas", "matplotlib",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL",
        "PySide6.QtSvg", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtPrintSupport", "PySide6.QtNetworkAuth", "PySide6.QtVirtualKeyboard",
    ],
    noarchive=False,
)

# 过滤多余二进制与翻译
a.binaries = [b for b in a.binaries if not _drop(b[0])]
a.datas = [d for d in a.datas if not _drop(d[0])]

# 剔除错误来源的 OpenSSL，替换为 Python 自带的
a.binaries = [
    b for b in a.binaries
    if not (os.path.basename(b[0]).lower() in _openssl_low
            and os.path.dirname(b[1]).lower() != _DLL_DIR.lower())
]
for _n in _OPENSSL:
    _src = os.path.join(_DLL_DIR, _n)
    if os.path.exists(_src) and not any(
        os.path.basename(b[0]).lower() == _n.lower()
        and os.path.dirname(b[1]).lower() == _DLL_DIR.lower()
        for b in a.binaries
    ):
        a.binaries.append((_n, _src, "BINARY"))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="screen-quiz-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)