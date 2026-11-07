# -*- coding: utf-8 -*-
"""资源路径解析。

区分两类路径，这是 PyInstaller 打包能否正常工作的关键：
  - 只读资源（模型、图标、背景图）：打包后位于临时解压目录，用 resource_path()。
  - 可写目录（csv_data 等）：必须位于 exe 同级目录，用 data_dir()；
    临时解压目录在程序退出后会被清理，且可能不可写。
"""

import os
import sys

# 源码运行时的基准目录：本文件所在目录
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(rel_path):
    """返回只读资源的绝对路径。

    打包后 sys._MEIPASS 指向 _internal（onedir）或临时解压目录（onefile）。
    """
    base = getattr(sys, "_MEIPASS", _SRC_DIR)
    return os.path.join(base, rel_path)


def app_dir():
    """返回可写文件的根目录：打包后为 exe 所在目录，源码运行时为项目目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _SRC_DIR


def data_dir(rel_path):
    """返回可写子目录的绝对路径，不存在则创建。"""
    path = os.path.join(app_dir(), rel_path)
    os.makedirs(path, exist_ok=True)
    return path
