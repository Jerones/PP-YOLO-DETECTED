# -*- coding: utf-8 -*-
"""PyInstaller 运行时钩子：把 OpenVINO 的 dll 目录加入 DLL 搜索路径。

必须在 openvino 被导入之前执行，否则 _pyopenvino.pyd 会报
"ImportError: DLL load failed while importing _pyopenvino"。
"""

import os
import sys

if getattr(sys, 'frozen', False):
    _base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    for _dir in (os.path.join(_base, 'openvino', 'libs'), _base):
        if not os.path.isdir(_dir):
            continue
        os.environ['PATH'] = _dir + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(_dir)
            except OSError:
                pass
