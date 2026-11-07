# -*- coding: utf-8 -*-
"""基于 PP-YOLO 的表计读数检测系统 —— 主窗口逻辑。

摄像头链路采用「采集 / 推理 / 显示」三段解耦：
- 采集线程独占设备，持续读帧，只保留最新一帧
- 推理线程取最新帧跑流水线，完成即取下一帧，绝不积压
- 主线程只负责显示，永远不做推理，界面不会被单帧 1 秒的耗时冻住

启动同样按「先出界面、后加载模型」组织：
openvino(0.3s) + 模型加载编译(1.6s) 放在后台线程，pandas/matplotlib(2s)
推迟到打开分析看板时再导入。窗口因此能在 0.6 秒内出现，而不是先白屏 4 秒。
"""

import os
import sys
import time
import traceback
from collections import deque

import cv2
import numpy as np
from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from alarm import AlarmCenter
from camera import DetectWorker, FrameGrabber, ReadingSmoother, draw_overlay
from detect_ui import Ui_MainWindow, reset_icon
from paths import data_dir
from recorder import ReadingRecorder
from settings import AppSettings
from settings_dialog import open_alarm_settings as show_alarm_dialog

# 预览刷新周期(毫秒)。约 30fps，与推理速度无关
PREVIEW_INTERVAL_MS = 33

# 看板自动刷新间隔(秒)。每帧重绘一次 matplotlib 要 100ms，会让界面周期性卡顿
BOARD_REFRESH_INTERVAL = 3.0


class ModelLoader(QtCore.QThread):
    """后台加载推理模型。

    模型加载 + OpenVINO 编译实测 1.6 秒，加上 openvino 自身的导入约 2 秒。
    放在主线程里就是「点了图标先白屏两秒」，用户会以为没打开。
    """

    loaded = QtCore.pyqtSignal(bool, str)

    def run(self):
        try:
            import pre          # 延迟导入：openvino 的导入开销也挪到后台
            pre.warmup()
        except Exception as exc:
            self.loaded.emit(False, '{}: {}'.format(type(exc).__name__, exc))
            return
        self.loaded.emit(True, '')


class ImageDetectWorker(QtCore.QThread):
    """单张图片检测。

    一张图约 0.8~1.2 秒，原来在主线程里跑，点完「图片检测」整个窗口会卡住
    并出现「未响应」，鼠标一直转圈。改为后台执行，界面可以照常拖动。
    """

    done = QtCore.pyqtSignal(object, object, object, float)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, path, parent=None):
        super(ImageDetectWorker, self).__init__(parent)
        self.path = path

    def run(self):
        start = time.time()
        try:
            import pre
            image, readings, meters = pre.detect(self.path)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(image, readings, meters, time.time() - start)


class UI_Logic_Window(QMainWindow):
    # 发信在子线程完成，用信号把「成功/失败」搬回界面线程再弹提示
    mailResult = QtCore.pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super(UI_Logic_Window, self).__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.img_name = None           # 当前导入的图片路径
        self.result2 = None            # 最近一帧 BGR 画面，供保存使用
        self.board = None              # 数据分析看板
        self.is_detecting = False      # True 时对画面做读数检测
        self.settings = AppSettings()  # 告警开关与阈值，持久化到 settings.json
        self._info_img_path = None     # 信息栏当前展示的图片来源
        self._last_dir = ''            # 上次打开/保存的目录

        self.grabber = FrameGrabber(0, self)
        self.grabber.opened.connect(self._on_camera_opened)
        self.grabber.failed.connect(self._on_camera_failed)
        self.worker = None             # 推理线程，按需创建
        self._camera_ready = False     # 设备是否真正打开完成
        self._pending_mode = None      # 打开过程中用户想做的事：preview / detect
        self.smoother = ReadingSmoother()
        self.recorder = ReadingRecorder(data_dir('csv_data'))
        # 告警只发一封、需手动重置，状态由 AlarmCenter 维护
        self.alarm = AlarmCenter(self.settings,
                                 on_result=self._relay_mail_result)
        self._latest_meters = []       # 最近一次检测结果，用于在新帧上重绘
        self._frame_costs = deque(maxlen=6)
        self._recorded = 0
        self._mail_error = None        # 最近一次预警邮件的发送失败原因
        self._model_ready = False      # 模型是否已在后台加载完成
        self._loader = None            # 模型加载线程
        self._img_task = None          # 单张图片检测线程
        self._img_busy = False         # 图片检测是否在进行（线程启动到结束之间）
        self._board_last_refresh = 0.0 # 看板上次重绘时间，用于节流

        # 预览定时器：只做取帧与显示，永不阻塞
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._preview_tick)

        # 图像标签自身的尺寸变化不经过主窗口的 resizeEvent，
        # 不监听的话首次布局完成前绘制的画面会一直停留在错误尺寸
        self.ui.label.installEventFilter(self)

        self.init_slots()
        self.show_initial_image()
        self.ui.textBrowser.setHtml(
            '<div style="color:#7C8899;font-size:10pt;padding-top:4px;">请选择左侧操作</div>'
            '<div style="color:#3C4A5F;font-size:10pt;padding-top:12px;">'
            '1. 导入图片后点击“图片检测”</div>'
            '<div style="color:#3C4A5F;font-size:10pt;padding-top:6px;">'
            '2. 或打开摄像头做实时读数</div>')
        self._sync_buttons()
        self.statusBar().showMessage("就绪")

    def init_slots(self):
        self.ui.pushButton_img.clicked.connect(self.button_image_open)
        self.ui.pushButton_img2.clicked.connect(self.detect_img)
        self.ui.pushButton_video.clicked.connect(self.button_camera_open)
        self.ui.pushButton_video_countinue.clicked.connect(self.countinue)
        self.ui.pushButton_video_stop.clicked.connect(self.stop)
        self.ui.pushButton_video_off.clicked.connect(self.button_camera_off)
        self.ui.pushButton_save.clicked.connect(self.save_img)
        self.ui.pushButton_new_window.clicked.connect(self.open_new_window)
        self.ui.pushButton_alarm.clicked.connect(self.open_alarm_settings)
        self.ui.pushButton_alarm_reset.clicked.connect(self.reset_alarm)
        self.ui.check_alarm.toggled.connect(self._on_alarm_toggled)
        self.mailResult.connect(self._on_mail_done)
        # 初始化开关状态时屏蔽信号：否则启动瞬间就会把默认值写回配置文件
        self.ui.check_alarm.blockSignals(True)
        self.ui.check_alarm.setChecked(self.settings.alarm_enabled)
        self.ui.check_alarm.blockSignals(False)
        self._refresh_alarm_state()

    # ---------------- 启动：模型后台加载 ----------------

    def start_model_loading(self):
        """窗口显示之后再调用：模型在后台加载，界面先能用。"""
        self._set_model_busy_hint(True)
        self._loader = ModelLoader(self)
        self._loader.loaded.connect(self._on_model_loaded)
        self._loader.start()

    def _on_model_loaded(self, ok, detail):
        self._model_ready = ok
        self._set_model_busy_hint(False)
        self._sync_buttons()
        if ok:
            self.statusBar().showMessage(
                "模型加载完成 · {}".format(self.settings.describe_threshold()))
            if self.result2 is None:
                self.show_initial_image()
            return
        self.ui.label.setText("识别模型加载失败\n\n请检查 model 目录是否完整")
        self.statusBar().showMessage("模型加载失败")
        QMessageBox.critical(
            self, "启动失败",
            "模型加载失败：{}\n\n请确认 model 目录与程序位于同一位置。".format(detail))

    def _set_model_busy_hint(self, busy):
        """加载期间给出可见提示：占位文字 + 状态栏 + 按钮置灰。"""
        if busy:
            self.ui.label.setText("正在加载识别模型…\n\n约需 2 秒")
            self.ui.textBrowser.setHtml(
                '<div style="color:#7C8899;font-size:10pt;padding-top:4px;">'
                '正在加载识别模型…</div>'
                '<div style="color:#3C4A5F;font-size:10pt;padding-top:12px;">'
                '首次启动需要 1~2 秒，加载完成后即可检测</div>')
            self.statusBar().showMessage("正在加载识别模型…")

    def _sync_buttons(self):
        """按「模型是否就绪 / 摄像头是否打开 / 是否在检测」统一决定按钮可点性。

        原来按钮始终可点，点重复了只在函数里 return，用户看到的是「点了没反应」。
        """
        ready = self._model_ready
        busy_img = self._img_busy
        self.ui.pushButton_img2.setEnabled(ready and not busy_img)
        self.ui.pushButton_img2.setText("检测中…" if busy_img else "图片检测")
        self.ui.pushButton_video.setEnabled(ready and not self._camera_ready)
        self.ui.pushButton_video_countinue.setEnabled(ready and not self.is_detecting)
        self.ui.pushButton_video_stop.setEnabled(self.is_detecting)
        self.ui.pushButton_video_off.setEnabled(
            self._camera_ready or self.grabber.running)

    # ---------------- 画面显示 ----------------

    def _display(self, bgr_image):
        """记录当前画面并显示到标签上。"""
        self.result2 = bgr_image
        self._render_current()

    def _render_current(self):
        """按标签当前尺寸等比缩放后绘制，避免图像被拉伸变形。"""
        image = getattr(self, 'result2', None)
        if image is None:
            return
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[0:2]
        qimage = QtGui.QImage(rgb.data, width, height, rgb.strides[0],
                              QtGui.QImage.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qimage)
        target = self.ui.label.size()
        if target.width() > 0 and target.height() > 0:
            pixmap = pixmap.scaled(target, QtCore.Qt.KeepAspectRatio,
                                   QtCore.Qt.SmoothTransformation)
        self.ui.label.setPixmap(pixmap)

    def resizeEvent(self, event):
        """窗口尺寸变化后重绘，保持图像比例。"""
        super(UI_Logic_Window, self).resizeEvent(event)
        if getattr(self, 'ui', None) is not None:
            self._render_current()

    def eventFilter(self, obj, event):
        """图像标签尺寸变化时重绘，避免画面停在旧的缩放尺寸上。"""
        if obj is self.ui.label and event.type() == QtCore.QEvent.Resize:
            self._render_current()
        return super(UI_Logic_Window, self).eventFilter(obj, event)

    def show_initial_image(self):
        """回到初始占位状态。用提示文字而非位图，避免小图放大后发虚。"""
        self.result2 = None
        if getattr(self, '_model_ready', False):
            self.ui.label.setText("请导入图片\n\n或打开摄像头")
        else:
            # 模型还没加载完时，占位文字顺便充当进度提示
            self.ui.label.setText("正在加载识别模型…\n\n约需 2 秒")

    def _show_meters(self, meters, img_path=None):
        """把检测结果写入右侧信息栏。"""
        if img_path is not None:
            self._info_img_path = img_path
        browser = self.ui.textBrowser
        browser.clear()
        if self._info_img_path:
            browser.append(
                '<div style="color:#7C8899;font-size:9pt;">图片路径</div>'
                '<div style="color:#26364D;font-size:9pt;">{}</div>'.format(
                    self._info_img_path))
        if not meters:
            browser.append(
                '<div style="color:#B03A2E;font-size:10pt;font-weight:600;'
                'padding-top:10px;">未检测到表计</div>')
            return
        valid_count = sum(1 for meter in meters if meter.get('valid'))
        browser.append(
            '<div style="color:#3C4A5F;font-size:10pt;padding-top:8px;">'
            '共检测到 {} 个目标，{} 个可读</div>'.format(len(meters), valid_count))
        # 把当前阈值写在结果上方，避免用户对着红字猜「凭什么算越限」。
        # 文案要短：信息栏宽 330px，多写四个字就会折行
        threshold_text = '阈值：{}'.format(self.settings.threshold_text())
        if not self.settings.alarm_enabled:
            threshold_text += ' · 邮件已关'
        browser.append(
            '<div style="color:#93A0B4;font-size:8.5pt;padding-top:6px;">'
            '{}</div>'.format(threshold_text))
        # 预警已发出但未重置时，信息栏长期显示这条，避免用户误以为还会再发
        if self.alarm.latched:
            headline = self.alarm.latched_summary
            if self._mail_error:
                headline = '预警邮件发送失败 · 请检查网络或收件邮箱'
            browser.append(
                '<div style="color:#B03A2E;font-size:9pt;font-weight:600;'
                'padding-top:8px;">{}<br>'
                '<span style="font-weight:400;color:#7C8899;">'
                '处理完成后请点击“重置预警”</span></div>'.format(headline))
        for meter in meters:
            index = meter.get('index', 0)
            if not meter.get('valid'):
                browser.append(
                    '<div style="color:#7C8899;font-size:9pt;padding-top:12px;">'
                    '表计 {}</div>'
                    '<div style="color:#93A0B4;font-size:14pt;font-weight:600;">'
                    '未识别</div>'.format(index))
                continue
            value = meter.get('smoothed')
            if value is None:
                value = meter['reading']
            # 越限判断与开关无关：关掉告警只是不发邮件，异常仍要看得见
            limit = self.settings.threshold_for(meter.get('range'))
            exceed = limit is not None and value < limit
            color = '#D9534F' if exceed else '#1668DC'
            browser.append(
                '<div style="color:#7C8899;font-size:9pt;padding-top:12px;">'
                '表计 {}{}</div>'.format(
                    index, '  ·  低于告警下限 {:.3f}'.format(limit)
                    if exceed else ''))
            browser.append(
                '<div style="color:{};font-size:16pt;font-weight:600;">'
                '{:.3f}<span style="font-size:9pt;color:#7C8899;"> {}</span>'
                '</div>'.format(color, value, meter.get('unit', 'MPa')))
            # 平滑后的稳定值与瞬时值一并给出，便于判断读数是否已经稳住
            if meter.get('smoothed') is not None:
                browser.append(
                    '<div style="color:#A9B3C1;font-size:8.5pt;">'
                    '瞬时 {:.3f}  ·  {}</div>'.format(
                        meter['reading'],
                        '已稳定' if meter.get('stable') else '采样中'))

    # ---------------- 图片 ----------------

    def button_image_open(self):
        img_name, _ = QFileDialog.getOpenFileName(
            self, "打开图片", self._last_dir, "*.jpg;;*.png;;All Files(*)")
        if not img_name:
            return
        # imdecode 而非 imread，规避中文路径读取失败
        image = cv2.imdecode(np.fromfile(img_name, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            QMessageBox.warning(self, "提示", "图片读取失败，请检查文件是否损坏。")
            return
        self.img_name = img_name
        self._last_dir = os.path.dirname(img_name)
        self._display(image)
        self.statusBar().showMessage("已导入：{}".format(os.path.basename(img_name)))

    def detect_img(self):
        """图片检测：推理放后台，界面保持可操作。"""
        if not self.img_name:
            QMessageBox.information(self, "提示", "请先导入图片。")
            return
        if not self._model_ready:
            QMessageBox.information(self, "提示", "识别模型还在加载，请稍候再试。")
            return
        if self._img_busy:
            return
        task = ImageDetectWorker(self.img_name, self)
        task.done.connect(self._on_image_done)
        task.failed.connect(self._on_image_failed)
        task.finished.connect(self._on_image_task_finished)
        self._img_task = task
        self._img_busy = True
        self._sync_buttons()
        self.statusBar().showMessage("正在检测图片…（约 1 秒）")
        task.start()

    def _on_image_done(self, image, _readings, meters, elapsed):
        self._display(image)
        # 记下来，改告警阈值后可以直接重绘，不必重新检测
        self._latest_meters = meters
        self._show_meters(meters, self.img_name)
        self.statusBar().showMessage("检测完成，耗时 {:.2f} 秒".format(elapsed))

    def _on_image_failed(self, message):
        self.statusBar().showMessage("检测失败")
        QMessageBox.critical(self, "检测失败", message)

    def _on_image_task_finished(self):
        self._img_busy = False
        self._sync_buttons()

    def save_img(self):
        if self.result2 is None:
            QMessageBox.information(self, "提示", "暂无可保存的画面。")
            return
        default_name = 'result_{}.png'.format(time.strftime('%Y%m%d_%H%M%S'))
        start_dir = os.path.join(self._last_dir, default_name) if self._last_dir \
            else default_name
        file_name, _ = QFileDialog.getSaveFileName(
            self, "保存图片", start_dir,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg);;位图 (*.bmp)")
        if not file_name:
            return
        self._last_dir = os.path.dirname(file_name)
        ext = os.path.splitext(file_name)[1].lower()
        if not ext:
            ext = ".png"
            file_name += ext
        # imwrite 在中文路径下会静默失败，改用 imencode + tofile
        ok, buffer = cv2.imencode(ext, self.result2)
        if not ok:
            QMessageBox.warning(self, "提示", "图片编码失败。")
            return
        try:
            buffer.tofile(file_name)
        except OSError as exc:
            QMessageBox.warning(self, "提示", "保存失败：{}".format(exc))

    # ---------------- 摄像头 ----------------

    def button_camera_open(self):
        if self.grabber.running and self._camera_ready:
            return
        # 打开设备要 3~4 秒，这里只发请求，界面立刻返回，结果走 opened 信号
        self._pending_mode = 'preview'
        self._camera_ready = False
        self._sync_buttons()
        self.statusBar().showMessage("正在打开摄像头…（首次约 3 秒）")
        self.grabber.start_capture()

    def _on_camera_opened(self, width, height):
        """采集线程真正打开设备后回调：启动预览，并处理用户的待办请求。"""
        self._camera_ready = True
        self.smoother.reset()
        self.recorder.reset()
        # 只清计数，不清「已预警」锁定：关掉摄像头不等于处理完预警
        self.alarm.clear_counts()
        self._latest_meters = []
        self._info_img_path = None     # 摄像头模式下信息栏不再显示图片路径
        if not self.preview_timer.isActive():
            self.preview_timer.start(PREVIEW_INTERVAL_MS)
        mode = getattr(self, '_pending_mode', None)
        self._pending_mode = None
        if mode == 'detect':
            self._start_detection()
            return
        ratio_hint = ''
        if height > 0 and abs(width / float(height) - 16.0 / 9.0) > 0.05:
            ratio_hint = ('<div style="color:#B8860B;font-size:9pt;padding-top:8px;">'
                          '当前画面为 {}×{}，非 16:9，已自动补边处理</div>'.format(
                              width, height))
        self.ui.textBrowser.setHtml(
            '<div style="color:#3C4A5F;font-size:10pt;">摄像头已打开（{}×{}），'
            '当前为预览模式</div>'
            '<div style="color:#7C8899;font-size:9pt;padding-top:8px;">'
            '点击“摄像头检测”开始实时读数</div>{}'.format(width, height, ratio_hint))
        self._sync_buttons()
        self.statusBar().showMessage(
            "摄像头已打开 {}×{}（预览中）".format(width, height))

    def countinue(self):
        if self.is_detecting:
            return
        if not self._camera_ready:
            # 设备还没打开完，记下意图，等 opened 信号自动开始检测
            self._pending_mode = 'detect'
            self._sync_buttons()
            self.statusBar().showMessage("正在打开摄像头…（首次约 3 秒）")
            if not self.grabber.running:
                self.grabber.start_capture()
            return
        self._start_detection()

    def _start_detection(self):
        if self.worker is None:
            self.worker = DetectWorker(self.grabber, self)
            self.worker.result_ready.connect(self._on_result)
            self.worker.failed.connect(self._on_detect_failed)
        self.worker.start_detect()
        self.is_detecting = True
        self._sync_buttons()
        self.statusBar().showMessage("检测中…（首帧需要 1 秒左右）")

    def stop(self):
        self.is_detecting = False
        if self.worker is not None:
            self.worker.stop_detect()
        self._sync_buttons()
        if self.grabber.running:
            self.statusBar().showMessage("已暂停检测（预览中）")
        else:
            self.statusBar().showMessage("已暂停检测")

    def button_camera_off(self):
        self.is_detecting = False
        self._pending_mode = None
        self._camera_ready = False
        # 不等待推理线程收尾：它会在当前帧结束后自行退出，
        # 界面立即回到初始态，用户不会觉得按钮卡住
        if self.worker is not None:
            self.worker.stop_detect()
        self.preview_timer.stop()
        self.grabber.stop_capture()
        self._latest_meters = []
        self.smoother.reset()
        self.ui.textBrowser.clear()
        self.show_initial_image()
        self._sync_buttons()
        self.statusBar().showMessage("摄像头已关闭")

    def _preview_tick(self):
        """预览定时器：取最新帧显示，检测结果以叠加方式重绘，画面不冻结。"""
        frame, _seq = self.grabber.latest()
        if frame is None:
            return
        if self._latest_meters:
            frame = draw_overlay(frame, self._latest_meters)
        self._display(frame)

    def _on_result(self, meters, elapsed):
        """推理线程回传一帧结果：平滑、判定预警、显示、落盘。"""
        self._frame_costs.append(elapsed)
        smoothed = self.smoother.update(meters)
        self._latest_meters = smoothed
        try:
            fired = self.alarm.check(smoothed)
        except Exception:
            # 告警判定异常不能连累读数显示与落盘
            fired = False
        self._show_meters(smoothed)
        try:
            written = self.recorder.feed(smoothed)
        except Exception:
            written = []
        self._recorded += len(written)
        if fired:
            self._refresh_alarm_state()
        average = sum(self._frame_costs) / len(self._frame_costs)
        self.statusBar().showMessage(
            "检测中 · {:.1f} fps · 单帧 {:.2f} 秒 · {} 块表 · 已记录 {} 条".format(
                1.0 / average if average > 0 else 0, average,
                len(smoothed), self._recorded))
        # 看板开着时边测边看，但重绘要节流：matplotlib 每次约 100ms，
        # 跟着 1fps 的推理每帧重绘，界面就会周期性卡一下
        if self.board is not None and self.board.isVisible():
            now = time.time()
            if now - self._board_last_refresh >= BOARD_REFRESH_INTERVAL:
                self._board_last_refresh = now
                self.board.auto_refresh()

    def _on_detect_failed(self, message):
        self.is_detecting = False
        self.statusBar().showMessage("检测中断：{}".format(message))

    def _on_camera_failed(self, message):
        """采集线程掉线或打不开：停掉检测与预览，恢复初始状态。"""
        self.is_detecting = False
        self._camera_ready = False
        self._pending_mode = None
        if self.worker is not None:
            self.worker.stop_detect(wait=True)
        self.preview_timer.stop()
        self.show_initial_image()
        self._sync_buttons()
        QMessageBox.warning(self, "摄像头", message)
        self.statusBar().showMessage("摄像头未就绪")

    # ---------------- 告警设置 ----------------

    def open_alarm_settings(self):
        """打开阈值设置窗口。告警开关本身在左栏可直接切换。"""
        if not show_alarm_dialog(self.settings, self):
            return
        # 对话框改的是同一个 settings 对象，这里只需同步左侧开关外观
        self._sync_alarm_box()
        self._refresh_alarm_views()
        self.statusBar().showMessage(
            "告警设置已保存 · {}".format(self.settings.describe_threshold()))

    def _on_alarm_toggled(self, checked):
        self.settings.alarm_enabled = checked
        self.settings.save()
        if not checked:
            # 关掉告警等同于关掉预警：顺手清掉锁定，重新开启时从干净状态开始，
            # 否则会出现「开关明明打开了却再也不发信」的困惑
            self.alarm.reset()
            self._mail_error = None
        self._refresh_alarm_state()
        self._refresh_alarm_views()
        self.statusBar().showMessage(
            "邮件告警已{}".format("开启" if checked else "关闭"))

    def _sync_alarm_box(self):
        """让左栏开关与 settings 保持一致，且不触发 toggled 造成重复写盘。"""
        box = self.ui.check_alarm
        box.blockSignals(True)
        box.setChecked(self.settings.alarm_enabled)
        box.blockSignals(False)

    def _refresh_alarm_views(self):
        """开关或阈值变化后刷新已有画面上的标注，不必重新检测。"""
        if self._latest_meters:
            self._show_meters(self._latest_meters)
        if self.board is not None and self.board.isVisible() and self.board.has_data():
            self.board.redraw()

    def reset_alarm(self):
        """重置预警：解除「本次只发一封」的锁定，重新具备预警能力。"""
        was_latched = self.alarm.reset()
        self._mail_error = None
        self._refresh_alarm_state()
        if self._latest_meters:
            self._show_meters(self._latest_meters)
        if not was_latched:
            self.statusBar().showMessage("当前没有待重置的预警")
        elif self.alarm.low_meters():
            # 读数还没恢复就重置：会重新计数，再发一封，先把话说清楚
            self.statusBar().showMessage(
                "预警已重置 · 读数仍低于阈值，连续确认后将再发一封")
        else:
            self.statusBar().showMessage(
                "预警已重置 · 下次读数低于阈值时将重新发送邮件")

    def _refresh_alarm_state(self):
        """预警未重置时把「重置预警」按钮标红，让待处理状态一眼可见。"""
        button = self.ui.pushButton_alarm_reset
        latched = self.alarm.latched
        button.setProperty('alert', 'true' if latched else 'false')
        # 图标是位图，不会跟着 QSS 的文字色走，需要同步换成红色版本
        button.setIcon(reset_icon(latched))
        # 动态属性变化后必须重新 polish，QSS 才会重新匹配选择器
        button.style().unpolish(button)
        button.style().polish(button)

    def _relay_mail_result(self, ok, detail):
        """由发信子线程调用：转成信号，回到界面线程再更新提示。"""
        self.mailResult.emit(ok, detail)

    def _on_mail_done(self, ok, detail):
        """发信结果回到界面线程。失败不弹模态框——检测还在跑，
        弹窗会把整个界面冻住，改为状态栏提示 + 信息栏红字。"""
        if ok:
            self._mail_error = None
            self.statusBar().showMessage("预警邮件已发送至 {}".format(detail))
        else:
            self._mail_error = detail
            self.statusBar().showMessage("预警邮件发送失败：{}".format(detail))
        if self._latest_meters:
            self._show_meters(self._latest_meters)

    # ---------------- 分析看板 ----------------

    def open_new_window(self):
        # 复用同一实例，避免反复点击不断创建窗口
        if self.board is None:
            # dashboard 会拉起 pandas + matplotlib（实测约 2 秒），
            # 首次打开才导入，启动阶段不必为它买单
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            self.statusBar().showMessage("正在加载数据分析模块…（首次约 2 秒）")
            try:
                from dashboard import DataBoard
                self.board = DataBoard(data_dir('csv_data'),
                                       settings=self.settings, parent=self)
            except Exception as exc:
                QMessageBox.critical(self, "打开失败",
                                     "数据分析模块加载失败：{}".format(exc))
                return
            finally:
                QApplication.restoreOverrideCursor()
        self.board.refresh_files()
        self.board.show()
        self.board.raise_()
        self.board.activateWindow()
        self._board_last_refresh = time.time()

    def closeEvent(self, event):
        """退出时停止线程并释放摄像头，否则下次启动会提示设备被占用。"""
        self.preview_timer.stop()
        if self.worker is not None:
            self.worker.shutdown()
        if self._img_task is not None and self._img_task.isRunning():
            # 正在跑的图片检测会被一起打断，最多等 3 秒
            self._img_task.wait(3000)
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(3000)
        self.grabber.stop_capture()
        super(UI_Logic_Window, self).closeEvent(event)


def _install_excepthook():
    """未捕获异常弹窗提示。打包成窗口程序后没有控制台，否则异常会静默退出。"""
    def hook(exc_type, exc_value, exc_tb):
        text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(text)
        QMessageBox.critical(None, "程序异常", text[-1500:])

    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    _install_excepthook()
    window = UI_Logic_Window()
    window.show()
    # 先让窗口出来，模型随后在后台加载：用户点开就有反应，
    # 而不是对着白屏等 openvino + 模型编译的两三秒
    window.start_model_loading()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
