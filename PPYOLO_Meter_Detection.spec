# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir 模式）。

用法：
    python build_exe.py
    # 或者
    pyinstaller --noconfirm --clean PPYOLO_Meter_Detection.spec

选择 onedir 而非 onefile 的原因：模型有 315MB，onefile 每次启动都要把
全部内容解压到临时目录，启动会等待数十秒；onedir 只解压一次且启动更快。
"""

import glob
import os

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

# 窗口程序（无控制台）。调试时设置环境变量 PPYOLO_CONSOLE=1 可保留控制台输出
CONSOLE = os.environ.get('PPYOLO_CONSOLE') == '1'

# ---- 业务资源：随包分发的只读文件 ----
# background_img 已随界面改为 QSS 纯色主题而废弃，不再打包
# csv_data / settings.json 属运行期生成的可写数据，不进发行包
datas = [
    ('model', 'model'),
    ('ui_imgs', 'ui_imgs'),
]
# 邮箱凭据不进仓库，但打包时如果有本机配置就打进包里做兜底；
# exe 同级目录放 mail_config.py 会优先生效（见 mailer._load_local_config）
if os.path.isfile('mail_config.py'):
    datas.append(('mail_config.py', '.'))
binaries = []
# pre / dashboard 改成「用到时才导入」（启动加速），静态分析虽然能跟到
# 函数内的 import，但显式声明可以避免版本差异导致漏收整个模块
hiddenimports = [
    'pre', 'dashboard', 'alarm', 'mailer',
    'camera', 'recorder', 'settings', 'settings_dialog',
    'detect_ui', 'styles', 'paths',
]

# ---- OpenVINO：推理后端。libs 下的 17 个 dll 与 plugins.xml 需手工收集，
#      打包工具不会自动跟进（配套 rthook_openvino.py 负责运行期 DLL 搜索路径）----
_OPENVINO_DIR = get_package_paths('openvino')[1]
_OPENVINO_LIBS = os.path.join(_OPENVINO_DIR, 'libs')
binaries += [(path, 'openvino/libs')
             for path in glob.glob(os.path.join(_OPENVINO_LIBS, '*.dll'))]
datas += [(path, 'openvino/libs')
          for path in glob.glob(os.path.join(_OPENVINO_LIBS, '*.xml'))
          + glob.glob(os.path.join(_OPENVINO_LIBS, '*.json'))]
hiddenimports += [
    'openvino.runtime',
    'openvino.runtime.ie_api',
    'openvino.frontend',
    'openvino.inference_engine',
]

# ---- matplotlib：字体与样式数据必须显式收集 ----
datas += collect_data_files('matplotlib')
hiddenimports += [
    'matplotlib.backends.backend_qt5agg',
    'PyQt5.QtPrintSupport',  # FigureCanvasQTAgg 依赖
]

# ---- pandas 时间解析的 C 扩展，打包工具偶尔漏收 ----
hiddenimports += [
    'pandas._libs.tslibs.base',
    'pandas._libs.tslibs.np_datetime',
]

excludes = [
    # 训练框架：推理走 OpenVINO，Paddle 与 PyTorch 全部排除，
    # 既能把体积从数百 MB 降下来，也避免 paddle/protobuf 的导入冲突
    'paddle', 'paddlepaddle', 'paddlepaddle_gpu', 'paddlex', 'paddleseg',
    'paddledet', 'paddle_bfloat', 'paddle2onnx',
    'torch', 'torchvision', 'torchaudio', 'easyocr',
    'openvino.tools', 'openvino.model_zoo',
    # 未使用的科学计算与交互式环境
    'scipy', 'sklearn', 'sympy',
    'IPython', 'jupyter', 'notebook', 'nbconvert', 'nbformat', 'ipykernel',
    # 其他 GUI 框架
    'tkinter', 'PyQt6', 'PySide2', 'PySide6',
]

a = Analysis(
    ['detect_logic.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=['rthook_openvino.py'],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PPYOLO_Meter_Detection',
    debug=False,
    strip=False,
    upx=False,
    console=CONSOLE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='PPYOLO_Meter_Detection',
)
