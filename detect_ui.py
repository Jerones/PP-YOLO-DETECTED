# -*- coding: utf-8 -*-
"""界面定义。

原始版本由 pyuic5 从 detect_ui.ui 生成，此后已手工改造布局与样式，
因此不要再用 pyuic5 重新生成，否则改动会被覆盖。

布局结构：
    顶部标题栏
    主体三栏 —— 左侧操作面板(固定宽度) / 中间图像区(自适应) / 右侧信息面板(固定宽度)
    底部状态栏

控件对象名与原始版本保持一致，主窗口逻辑按名字取用。
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QSizePolicy

from paths import resource_path
from styles import APP_QSS

# 图标是 24x24 网格绘制的单色线稿（见 ui_imgs/icons），显示尺寸取 20，
# 留出与 40px 高按钮的上下留白
ICON_SIZE = 20
ICON_DIR = 'ui_imgs/icons/'
# 单色图标按按钮底色着色：白底用深灰、蓝色主按钮用白、置灰用浅灰
ICON_NORMAL = '#3F4B5E'
ICON_ON_PRIMARY = '#FFFFFF'
ICON_DISABLED = '#C2CAD6'
# 与 styles.py 里 [alert="true"] 的文字色保持一致
ICON_ALERT = '#B03A2E'


def _tinted(pixmap, color):
    """把单色图标染成指定颜色。

    图标本身只维护一份深灰 PNG，白/灰版本在运行时用 SourceIn 合成，
    省掉三套重复文件，也不会出现「改了图形忘了改另一个颜色」的问题。
    """
    canvas = QtGui.QPixmap(pixmap.size())
    canvas.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
    painter.fillRect(canvas.rect(), QtGui.QColor(color))
    painter.end()
    return canvas


def _load_icon(name, on_primary=False, color=None):
    """读取 base 图标，并生成「正常 / 置灰」两种状态。

    置灰态必须显式给出：Qt 默认会把彩色图标转灰度，但透明度不会降低，
    在浅灰底上会显得比文字更抢眼。
    """
    source = QtGui.QPixmap(resource_path(ICON_DIR + name + '.png'))
    if source.isNull():
        return QtGui.QIcon()
    base = color or (ICON_ON_PRIMARY if on_primary else ICON_NORMAL)
    icon = QtGui.QIcon()
    icon.addPixmap(_tinted(source, base), QtGui.QIcon.Normal)
    icon.addPixmap(_tinted(source, ICON_DISABLED), QtGui.QIcon.Disabled)
    return icon


def reset_icon(latched):
    """「重置预警」按钮的图标：预警待处理时跟着文字一起变红。"""
    return _load_icon('icon_reset', color=ICON_ALERT if latched else ICON_NORMAL)


class CameraCombo(QtWidgets.QComboBox):
    """摄像头选择下拉框，自己画下拉箭头。

    两件事逼着自绘：QSS 给 ::drop-down 设了 border:none 之后 Qt 不再画箭头，
    而 QSS 的 image: url(...) 在「中文 + 空格」的资源路径下并不可靠。
    自己画还能顺手让箭头与按钮图标同一套线宽和颜色。
    """

    def paintEvent(self, event):
        super(CameraCombo, self).paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        color = QtGui.QColor(ICON_NORMAL if self.isEnabled() else ICON_DISABLED)
        pen = QtGui.QPen(color, 1.6)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 12.0
        cy = self.height() / 2.0
        path = QtGui.QPainterPath()
        path.moveTo(cx - 3.8, cy - 2.0)
        path.lineTo(cx, cy + 1.8)
        path.lineTo(cx + 3.8, cy - 2.0)
        painter.drawPath(path)
        painter.end()


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1280, 800)
        # 左栏按钮多了一个“重置预警”，最小高度留够，避免小窗口下按钮被压扁
        MainWindow.setMinimumSize(QSize(1080, 730))
        MainWindow.setWindowIcon(self._window_icon())

        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        root = QtWidgets.QVBoxLayout(self.centralwidget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_header()
        root.addWidget(self.headerBar)

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 14)
        body.setSpacing(14)
        self._build_left_panel()
        self._build_image_card()
        self._build_info_card()
        body.addWidget(self.leftPanel)
        body.addWidget(self.imageCard, 1)
        body.addWidget(self.infoCard)
        root.addLayout(body, 1)

        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        # 版本信息从左侧面板挪到状态栏右侧：左栏要腾给告警开关，
        # 而这类只读信息本来更适合常驻在状态栏
        self.statusInfo = QtWidgets.QLabel(self.statusbar)
        self.statusInfo.setObjectName("statusInfo")
        self.statusbar.addPermanentWidget(self.statusInfo)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

        # 样式表放在最后设置，确保 primary 属性已经就位
        MainWindow.setStyleSheet(APP_QSS)

    # ---------------- 各区域构建 ----------------

    def _build_header(self):
        self.headerBar = QtWidgets.QFrame()
        self.headerBar.setObjectName("headerBar")
        self.headerBar.setFixedHeight(66)

        layout = QtWidgets.QVBoxLayout(self.headerBar)
        layout.setContentsMargins(22, 9, 22, 9)
        layout.setSpacing(2)

        self.label_5 = QtWidgets.QLabel(self.headerBar)
        self.label_5.setObjectName("label_5")
        layout.addWidget(self.label_5)

        self.label_sub = QtWidgets.QLabel(self.headerBar)
        self.label_sub.setObjectName("label_sub")
        layout.addWidget(self.label_sub)

    def _build_left_panel(self):
        self.leftPanel = QtWidgets.QFrame()
        self.leftPanel.setObjectName("leftPanel")
        self.leftPanel.setFixedWidth(212)

        layout = QtWidgets.QVBoxLayout(self.leftPanel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        self.label_section_file = self._section_label("文件")
        layout.addWidget(self.label_section_file)
        self.pushButton_img = self._make_button("pushButton_img")
        layout.addWidget(self.pushButton_img)
        self.pushButton_img2 = self._make_button("pushButton_img2", primary=True)
        layout.addWidget(self.pushButton_img2)

        layout.addSpacing(4)
        # 摄像头序号与分节标题同排：左栏在最小窗口下只剩二十几像素余量，
        # 单开一行会把下面的按钮压扁，合到标题行只多占一行标题的高度
        camera_row = QtWidgets.QHBoxLayout()
        camera_row.setContentsMargins(0, 0, 0, 0)
        camera_row.setSpacing(6)
        self.label_section_camera = self._section_label("摄像头")
        camera_row.addWidget(self.label_section_camera)
        self.combo_camera = CameraCombo(self.leftPanel)
        self.combo_camera.setObjectName("combo_camera")
        self.combo_camera.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.combo_camera.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_camera.setMinimumWidth(96)
        self.combo_camera.setMaxVisibleItems(10)
        self.combo_camera.setToolTip(
            "选择使用哪个摄像头。接上外接摄像头后，点下拉框最后一项可重新扫描设备；"
            "摄像头已打开时切换会立即改用新设备")
        camera_row.addWidget(self.combo_camera, 1)
        layout.addLayout(camera_row)
        self.pushButton_video = self._make_button("pushButton_video")
        layout.addWidget(self.pushButton_video)
        self.pushButton_video_countinue = self._make_button(
            "pushButton_video_countinue", primary=True)
        layout.addWidget(self.pushButton_video_countinue)
        self.pushButton_video_stop = self._make_button("pushButton_video_stop")
        layout.addWidget(self.pushButton_video_stop)
        self.pushButton_video_off = self._make_button("pushButton_video_off")
        layout.addWidget(self.pushButton_video_off)

        layout.addSpacing(4)
        self.label_section_output = self._section_label("输出")
        layout.addWidget(self.label_section_output)
        self.pushButton_save = self._make_button("pushButton_save")
        layout.addWidget(self.pushButton_save)
        self.pushButton_new_window = self._make_button("pushButton_new_window")
        layout.addWidget(self.pushButton_new_window)

        layout.addSpacing(4)
        self.label_section_alarm = self._section_label("告警")
        layout.addWidget(self.label_section_alarm)
        # 开关直接留在界面上，不必进对话框；阈值另开设置窗口修改
        self.check_alarm = QtWidgets.QCheckBox(self.leftPanel)
        self.check_alarm.setObjectName("check_alarm")
        self.check_alarm.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        layout.addWidget(self.check_alarm)
        self.pushButton_alarm = self._make_button("pushButton_alarm")
        layout.addWidget(self.pushButton_alarm)
        # 重置预警：解除「只发一封」的锁定，下一次跌破才重新发信
        self.pushButton_alarm_reset = self._make_button(
            "pushButton_alarm_reset")
        self.pushButton_alarm_reset.setProperty("alert", "false")
        self.pushButton_alarm_reset.setToolTip(
            "预警邮件已发送后，处理完现场回到这里点击重置，才会重新具备预警能力")
        layout.addWidget(self.pushButton_alarm_reset)

        layout.addStretch(1)

    def _build_image_card(self):
        self.imageCard = QtWidgets.QFrame()
        self.imageCard.setObjectName("imageCard")
        self.imageCard.setMinimumWidth(520)

        layout = QtWidgets.QVBoxLayout(self.imageCard)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.label_3 = QtWidgets.QLabel(self.imageCard)
        self.label_3.setObjectName("label_3")
        layout.addWidget(self.label_3)

        self.label = QtWidgets.QLabel(self.imageCard)
        self.label.setObjectName("label")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setMinimumSize(QSize(320, 240))
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.label, 1)

    def _build_info_card(self):
        self.infoCard = QtWidgets.QFrame()
        self.infoCard.setObjectName("infoCard")
        self.infoCard.setFixedWidth(330)

        layout = QtWidgets.QVBoxLayout(self.infoCard)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.label_4 = QtWidgets.QLabel(self.infoCard)
        self.label_4.setObjectName("label_4")
        layout.addWidget(self.label_4)

        self.textBrowser = QtWidgets.QTextBrowser(self.infoCard)
        self.textBrowser.setObjectName("textBrowser")
        self.textBrowser.setFrameShape(QtWidgets.QFrame.NoFrame)
        # QTextBrowser 不接受 QSS 的 padding，内边距要通过文档边距设置
        self.textBrowser.document().setDocumentMargin(12)
        layout.addWidget(self.textBrowser, 1)

    # ---------------- 控件工厂 ----------------

    def _section_label(self, text):
        label = QtWidgets.QLabel(self.leftPanel)
        label.setObjectName("label_section")
        label.setText(text)
        return label

    def _make_button(self, name, primary=False):
        button = QtWidgets.QPushButton(self.leftPanel)
        button.setObjectName(name)
        button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setMinimumHeight(40)
        if primary:
            # QSS 通过 [primary="true"] 选择器识别主操作按钮
            button.setProperty("primary", "true")
        return button

    # ---------------- 文案与图标 ----------------

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(
            _translate("MainWindow", "基于 PP-YOLO 的表计读数检测系统"))
        self.label_5.setText(
            _translate("MainWindow", "基于 PP-YOLO 的表计读数检测系统"))
        self.label_sub.setText(
            _translate("MainWindow", "工业指针式表计自动读数系统 · 检测 / 分割 / 几何换算"))
        self.label_3.setText(_translate("MainWindow", "检测结果"))
        self.label_4.setText(_translate("MainWindow", "检测信息"))
        self.label_section_file.setText(_translate("MainWindow", "文件"))
        self.label_section_camera.setText(_translate("MainWindow", "摄像头"))
        self.label_section_output.setText(_translate("MainWindow", "输出"))
        self.label_section_alarm.setText(_translate("MainWindow", "告警"))
        self.check_alarm.setText(_translate("MainWindow", "低读数邮件告警"))
        self.statusInfo.setText(
            _translate("MainWindow", "OpenVINO 2022.3 · PPYOLOv2 + DeepLabV3P"))

        self._set_button(self.pushButton_img, "导入图片", "icon_image")
        self._set_button(self.pushButton_img2, "图片检测", "icon_detect", on_primary=True)
        self._set_button(self.pushButton_video, "摄像头打开", "icon_camera")
        self._set_button(self.pushButton_video_countinue, "摄像头检测", "icon_play",
                         on_primary=True)
        self._set_button(self.pushButton_video_stop, "暂停检测", "icon_pause")
        self._set_button(self.pushButton_video_off, "关闭摄像头", "icon_camera_off")
        self._set_button(self.pushButton_save, "保存图片", "icon_save")
        self._set_button(self.pushButton_new_window, "分析数据", "icon_chart")
        self._set_button(self.pushButton_alarm, "告警设置", "icon_bell")
        self._set_button(self.pushButton_alarm_reset, "重置预警", "icon_reset")

    def _set_button(self, button, text, icon_name, on_primary=False):
        button.setText(text)
        button.setIcon(_load_icon(icon_name, on_primary))
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))

    @staticmethod
    def _window_icon():
        """窗口 / 任务栏图标：表盘。另挂 256px 一份，供高 DPI 任务栏取用。"""
        icon = QtGui.QIcon(resource_path(ICON_DIR + 'icon_app.png'))
        icon.addFile(resource_path(ICON_DIR + 'icon_app_256.png'))
        return icon
