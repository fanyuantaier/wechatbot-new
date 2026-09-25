# -*- coding: utf-8 -*-
"""导入本目录即启动 Run.exe（Windows 一键启动器）。

Run.exe 会把**自身所在目录**当作工作目录去装依赖、起 Web UI，所以这里用
绝对路径调用它，不依赖调用者的当前工作目录（原来的 `os.system('Run.exe')`
要求 cwd 正好是本目录，从别处导入就会静默失败）。
非 Windows 或文件不存在时安静跳过，不影响正常 `import`。
"""
import os
import subprocess
import sys

_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Run.exe")

if sys.platform == "win32" and os.path.exists(_EXE):
    subprocess.call([_EXE], cwd=os.path.dirname(_EXE))
