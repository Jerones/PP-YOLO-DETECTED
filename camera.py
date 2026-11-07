# -*- coding: utf-8 -*-
"""摄像头采集与推理线程。

设计要点：
1. 采集与推理解耦。采集线程独占 VideoCapture 连续读帧，只保留最新一帧，
   推理线程取最新帧跑流水线。任何一方变慢都不会拖住对方。
2. 推理不在主线程。单帧耗时约 0.6~1.1 秒，同步跑会把界面冻住，
   导致“暂停 / 关闭”按钮点不动。
3. 不积压。推理完成后立刻取当前最新帧，而不是排队处理旧帧，
   否则画面会越跑越滞后。
"""

import sys
import threading
import time

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

# 注意：不在这里 import pre。pre 会拉起 openvino（约 0.3 秒），
# 而本模块在启动时就被主窗口导入；推理线程 run() 里按需导入即可，
# 让「窗口先出现、模型后台加载」的启动路径成立。

# 优先使用的采集分辨率。检测框反算与刻度检出精度都要求画面足够大，
# 实测 640x480 会漏检刻度、把 25MPa 表误判为 1.6MPa 表
PREFERRED_WIDTH = 1280
PREFERRED_HEIGHT = 720

# 连续读帧失败超过该次数才判定摄像头掉线，避免偶发丢帧直接中断
MAX_READ_ERRORS = 30

# 设备列表扫描范围：探测 0 ~ MAX_PROBE_INDEX-1。
# 笔记本内置摄像头通常是 0，外接 USB 摄像头按插入顺序往后排，
# 6 个足够覆盖「内置 + 外接 + 虚拟摄像头」的常见组合
MAX_PROBE_INDEX = 6

_BACKEND = cv2.CAP_DSHOW if sys.platform.startswith('win') else cv2.CAP_ANY

# 同一时刻只允许一个地方打开设备。扫描线程与采集线程若同时 open 同一个
# 序号，后到的会拿到「设备被占用」的假失败，所以统一串行化
_DEVICE_LOCK = threading.Lock()


def open_capture(index=0):
    """按首选参数打开摄像头，返回 (cap, 实际宽, 实际高)；失败返回 (None, 0, 0)。"""
    with _DEVICE_LOCK:
        cap = cv2.VideoCapture(index, _BACKEND)
        if not cap.isOpened():
            cap.release()
            return None, 0, 0
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, PREFERRED_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, PREFERRED_HEIGHT)
            # 只缓冲一帧，避免拿到几秒前的旧画面；部分后端不支持，忽略失败
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return cap, width, height


def probe_camera(index):
    """探测某个序号上是否存在可用摄像头，返回 (宽, 高)；没有则 (0, 0)。

    不做分辨率重配（那一步在 DSHOW 上要额外几秒），只确认能打开。
    设备不存在时 DSHOW 会往 stderr 打一行错误，属正常现象。
    """
    with _DEVICE_LOCK:
        cap = cv2.VideoCapture(index, _BACKEND)
        if not cap.isOpened():
            cap.release()
            return 0, 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
    return width, height


class CameraScanner(QThread):
    """后台扫描可用摄像头序号。

    逐个打开设备实测要零点几秒到两秒，放在主线程里点开程序就先卡一下，
    所以放到线程里扫，每找到一个就发一次信号，界面边扫边填列表。
    """

    found = pyqtSignal(int, int, int)   # 序号、宽、高（正在使用的设备报 0, 0）
    scanned = pyqtSignal(int)           # 扫描结束，参数为命中数量

    def __init__(self, max_index=MAX_PROBE_INDEX, skip=(), parent=None):
        super(CameraScanner, self).__init__(parent)
        self._max_index = max_index
        # 正在被采集线程占用的序号不能真去 open，否则会把占用它的程序
        # 挤掉或误判成失败，直接按「存在」上报
        self._skip = set(skip)
        self._cancel = False

    def cancel(self):
        """请求中止扫描：当前这个探完就退出，不再继续往后探。"""
        self._cancel = True

    @property
    def cancelled(self):
        """是否被中止。中止的扫描结果不完整，调用方不能拿它覆盖整份设备列表。"""
        return self._cancel

    def run(self):
        count = 0
        for index in range(self._max_index):
            if self._cancel:
                break
            if index in self._skip:
                count += 1
                self.found.emit(index, 0, 0)
                continue
            width, height = probe_camera(index)
            if self._cancel:
                break
            if width or height:
                count += 1
                self.found.emit(index, width, height)
        self.scanned.emit(count)


def draw_overlay(frame, meters):
    """把一次检测得到的框与读数画到新帧上。

    检测约 1 秒一次，预览是 30fps。用上一次的检测结果在新帧上重绘，
    画面不会在两次检测之间冻结，视觉上框和数字能稳稳跟着画面走。
    """
    if not meters or frame is None:
        return frame
    canvas = frame.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    for meter in meters:
        box = meter.get('box')
        if not box:
            continue
        x1, y1, x2, y2 = box
        color = (0, 150, 0) if meter.get('valid') else (0, 110, 200)
        label = "#{:.3f}".format(meter['reading']) if meter.get('valid') else "#--"
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 3)
        cv2.rectangle(canvas, (x1, y1), (x1 + 130, y1 + 40), color, -1)
        cv2.putText(canvas, label, (x1 + 6, y1 + 28),
                    font, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


class FrameGrabber(QThread):
    """独占摄像头的采集线程，持续读帧并只保留最新一帧。

    序号可以在运行中切换（多摄像头场景）：切换只置标志位，由 run() 的
    外层循环重新打开设备，线程本身不销毁重建。
    """

    opened = pyqtSignal(int, int)   # 实际宽、高
    failed = pyqtSignal(str)        # 掉线原因

    def __init__(self, index=0, parent=None):
        super().__init__(parent)
        self._index = index
        self._cap = None
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self._running = False
        self._switch = False          # 请求换设备
        self._read_errors = 0
        self.width = 0
        self.height = 0

    @property
    def index(self):
        return self._index

    def start_capture(self):
        """请求打开设备，立即返回。

        DSHOW 打开设备并重配分辨率实测要 3~4 秒，放在主线程里会让界面
        定格同样长的时间。这里改成在采集线程内部打开，结果通过
        opened / failed 信号异步通知。
        """
        if self._running:
            return True
        self._running = True
        self._read_errors = 0
        self.start()
        return True

    def switch_to(self, index):
        """切换到另一个摄像头序号。

        不 stop + start 重启 QThread：反复重启容易遇到线程还没收尾就再次
        start 的竞态。改为置 _switch，让 run() 退出读帧循环、释放旧设备、
        再用新序号重新打开，全程同一个线程。
        """
        self._index = index
        self._read_errors = 0
        if not self._running:
            return self.start_capture()
        self._switch = True
        return True

    def run(self):
        while self._running:
            # 每轮外层循环重新读 _index：切换设备时这里会拿到新序号
            cap, width, height = open_capture(self._index)
            if not self._running:
                # 打开过程中用户已经点了关闭，直接收尾
                if cap is not None:
                    cap.release()
                return
            if cap is None:
                self._running = False
                self._switch = False
                self.failed.emit(
                    "无法打开摄像头 {}，请检查设备是否被占用或权限是否允许"
                    "，也可在左栏换一个序号试试".format(self._index + 1))
                return
            self._cap = cap
            self.width, self.height = width, height
            self.opened.emit(width, height)

            while self._running and not self._switch:
                ret, frame = self._cap.read()
                if not ret:
                    self._read_errors += 1
                    if self._read_errors >= MAX_READ_ERRORS:
                        self.failed.emit("摄像头连续读帧失败，可能已被其他程序占用")
                        self._running = False
                        break
                    self.msleep(20)
                    continue
                self._read_errors = 0
                # 只存最新帧，读得比算得快时旧帧直接丢弃
                with self._lock:
                    self._frame = frame
                    self._seq += 1

            if self._cap is not None:
                self._cap.release()
                self._cap = None
            if not self._running:
                break
            # 走到这里只可能是切换请求：丢掉旧设备的最后一帧，接着开新设备
            with self._lock:
                self._frame = None
            self._switch = False
        self._running = False

    def latest(self):
        """返回 (最新帧, 序号)。帧是引用，调用方不要就地修改。"""
        with self._lock:
            return self._frame, self._seq

    def stop_capture(self):
        """停止读帧并释放设备。"""
        self._running = False
        self._switch = False
        if self.isRunning():
            self.wait(2000)
        # run() 正常退出时会自己 release；这里兜底处理异常退出的情况
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._lock:
            self._frame = None

    @property
    def running(self):
        return self._running


class DetectWorker(QThread):
    """在后台对最新帧执行读数流水线，完成即取下一帧，不积压。

    线程常驻，用 _active 控制是否推理：暂停 / 继续只是切一个标志位，
    不需要反复创建和销毁线程，切换是瞬时的。
    """

    result_ready = pyqtSignal(list, float)  # meters、耗时秒
    failed = pyqtSignal(str)

    def __init__(self, grabber, parent=None):
        super().__init__(parent)
        self._grabber = grabber
        self._running = False     # 线程是否存活
        self._active = False      # 是否执行推理
        self._last_seq = -1

    def start_detect(self):
        """开始（或恢复）检测。线程未启动时才真正起线程。"""
        self._last_seq = -1
        self._active = True
        if not self._running:
            self._running = True
            self.start()

    def stop_detect(self, wait=False):
        """暂停检测。

        默认不阻塞：单帧推理要 0.6~1.1 秒，等它跑完会让“暂停”按钮看起来
        没反应。线程保留，退出程序或关闭摄像头时才用 wait=True / shutdown。
        """
        self._active = False
        if wait:
            self.shutdown()

    def shutdown(self):
        """结束线程并等待收尾，仅在关闭摄像头或退出程序时调用。"""
        self._active = False
        self._running = False
        if self.isRunning():
            self.wait(5000)

    def run(self):
        while self._running:
            if not self._active:
                self.msleep(40)
                continue
            frame, seq = self._grabber.latest()
            if frame is None or seq == self._last_seq:
                # 没有新帧，稍等再看，避免空转吃满一个核
                self.msleep(15)
                continue
            self._last_seq = seq
            start = time.time()
            try:
                import pre
                _image, _readings, meters = pre.detect_image(frame)
            except Exception as exc:      # 单帧异常不应终止整个检测流程
                self.failed.emit("{}: {}".format(type(exc).__name__, exc))
                self._running = False
                break
            if not self._running:
                break
            # 标注图不跨线程传：主线程会用 meters 在最新预览帧上重绘，
            # 保证画面 30fps 流畅，而不是被 1 fps 的标注图卡成幻灯片
            self.result_ready.emit(meters, time.time() - start)
        self._running = False


class ReadingSmoother:
    """按表位维护读数滑动窗口，用中位数抑制逐帧抖动。

    指针分割存在一两个像素的随机跳动，逐帧独立换算会让读数在相邻两格
    （0.5 MPa 或 0.05 MPa）之间反复跳。取中位数能压掉孤立跳变，
    同时保留真实的阶跃变化。
    """

    def __init__(self, window=7):
        self._window = window
        self._history = {}

    def reset(self):
        self._history.clear()

    def update(self, meters):
        """写入一帧结果，返回平滑后的 meters 副本（含 smoothed 字段）。"""
        seen = set()
        result = []
        for meter in meters:
            key = meter.get('index', 0)
            seen.add(key)
            item = dict(meter)
            if meter.get('valid'):
                history = self._history.setdefault(key, [])
                history.append(meter['reading'])
                if len(history) > self._window:
                    del history[0]
                item['smoothed'] = sorted(history)[len(history) // 2]
                # 样本不足半窗时先标记为不稳定，避免刚开检测就记录
                item['stable'] = len(history) >= max(3, self._window // 2)
            else:
                item['smoothed'] = None
                item['stable'] = False
            result.append(item)
        # 表从画面里消失后清掉它的历史，否则重新出现时会带着旧数据
        for key in list(self._history):
            if key not in seen:
                del self._history[key]
        return result
