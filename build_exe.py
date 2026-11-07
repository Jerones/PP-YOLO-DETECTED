# -*- coding: utf-8 -*-
"""一键打包脚本。

用法：
    python build_exe.py

产物：
    dist/PPYOLO_Meter_Detection/PPYOLO_Meter_Detection.exe
    双击即可运行，model / ui_imgs 已随包分发。

调试：
    set PPYOLO_CONSOLE=1 && python build_exe.py
    保留控制台窗口，便于查看启动阶段的报错。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, 'PPYOLO_Meter_Detection.spec')

# 模型是运行时必需资源，缺失就没必要打包下去
REQUIRED_FILES = [
    os.path.join(HERE, 'model', 'meter_det_model', 'model.pdmodel'),
    os.path.join(HERE, 'model', 'meter_seg_model', 'model.pdmodel'),
]


def main():
    missing = [path for path in REQUIRED_FILES if not os.path.isfile(path)]
    if missing:
        print('缺少模型文件，打包中止：')
        for path in missing:
            print('   ', path)
        return 1

    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', SPEC]
    print('执行：', ' '.join(cmd))
    code = subprocess.call(cmd, cwd=HERE)
    if code != 0:
        print('打包失败，退出码', code)
        return code

    exe_path = os.path.join(HERE, 'dist', 'PPYOLO_Meter_Detection',
                            'PPYOLO_Meter_Detection.exe')
    print('打包完成：', exe_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
