# -*- coding: utf-8 -*-
"""界面样式表（浅色扁平风格）。

单独成模块而非 style.qss 文件：这样 PyInstaller 会随 import 自动打包，
不需要额外维护 datas 配置。
"""

APP_QSS = """
/* ---------- 全局 ---------- */
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #1F2937;
}
QMainWindow, #centralwidget {
    background-color: #F4F6FA;
}

/* ---------- 顶部标题栏 ---------- */
#headerBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E5E9F0;
}
#label_5 {
    font-size: 16pt;
    font-weight: 600;
    color: #17233B;
}
#label_sub {
    font-size: 9pt;
    color: #7C8899;
}

/* ---------- 卡片容器 ---------- */
#leftPanel, #imageCard, #infoCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}

/* ---------- 分节标题 ---------- */
#label_section {
    font-size: 8.5pt;
    font-weight: 600;
    color: #93A0B4;
    padding-left: 2px;
}
#label_3, #label_4 {
    font-size: 10pt;
    font-weight: 600;
    color: #3C4A5F;
}

/* ---------- 普通按钮 ---------- */
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    border-radius: 8px;
    min-height: 40px;
    padding-left: 12px;
    text-align: left;
    font-size: 10.5pt;
    color: #26364D;
}
QPushButton:hover {
    background-color: #F3F7FD;
    border-color: #B7CBE7;
}
QPushButton:pressed {
    background-color: #E7EFFA;
}
QPushButton:disabled {
    color: #AFB9C7;
    background-color: #F8FAFC;
    border-color: #EAEEF4;
}

/* ---------- 主操作按钮 ---------- */
QPushButton[primary="true"] {
    background-color: #1668DC;
    border: 1px solid #1668DC;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background-color: #2C7BE9;
    border-color: #2C7BE9;
}
QPushButton[primary="true"]:pressed {
    background-color: #1156BA;
    border-color: #1156BA;
}
QPushButton[primary="true"]:disabled {
    background-color: #A8C4EA;
    border-color: #A8C4EA;
    color: #F0F5FC;
}

/* ---------- 图像显示区：深色衬底，突出检测框 ---------- */
#label {
    background-color: #0F1319;
    border-radius: 8px;
    color: #7C8899;
    font-size: 11pt;
}

/* ---------- 信息面板 ---------- */
#textBrowser {
    background-color: #FBFCFE;
    border: 1px solid #E9EEF6;
    border-radius: 8px;
    font-size: 10pt;
    color: #1F2937;
    selection-background-color: #CFE0F7;
}

/* ---------- 状态栏 ---------- */
QStatusBar {
    background-color: #FFFFFF;
    border-top: 1px solid #E5E9F0;
    color: #6C7A8D;
    font-size: 9pt;
}
QStatusBar::item {
    border: none;
}
#statusInfo {
    color: #A9B3C1;
    font-size: 8pt;
    padding-right: 12px;
}

/* ---------- 告警开关（左栏） ---------- */
#check_alarm {
    font-size: 10pt;
    color: #26364D;
    padding: 4px 2px;
    spacing: 8px;
}
#check_alarm:hover {
    color: #1668DC;
}
#check_alarm::indicator {
    width: 15px;
    height: 15px;
}
#check_alarm:disabled {
    color: #AFB9C7;
}

/* ---------- 重置预警：预警未被重置时变红，提醒还有事情没处理 ---------- */
QPushButton#pushButton_alarm_reset[alert="true"] {
    background-color: #FDF1EF;
    border-color: #E6A9A1;
    color: #B03A2E;
    font-weight: 600;
}
QPushButton#pushButton_alarm_reset[alert="true"]:hover {
    background-color: #FBE6E2;
    border-color: #D98C81;
}
QPushButton#pushButton_alarm_reset[alert="true"]:pressed {
    background-color: #F7D9D3;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #CBD5E3;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #A9B8CC;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

/* ---------- 数据看板 ---------- */
#toolBarCard, #canvasCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}
#boardTitle {
    font-size: 12pt;
    font-weight: 600;
    color: #17233B;
}
#boardStatus {
    color: #93A0B4;
    font-size: 8.5pt;
}
#kpiCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}
#kpiTitle {
    color: #93A0B4;
    font-size: 9pt;
}
#kpiValue {
    color: #26364D;
    font-size: 15pt;
    font-weight: 600;
}
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    border-radius: 6px;
    min-height: 30px;
    padding-left: 8px;
    padding-right: 6px;
    color: #26364D;
}
QComboBox:hover {
    border-color: #B7CBE7;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    selection-background-color: #E7EFFA;
    selection-color: #17233B;
    outline: none;
}
QPushButton#boardAction {
    min-height: 30px;
    padding: 0 14px;
    text-align: center;
}
"""


# 告警设置对话框的补充样式。对话框是独立顶层窗口，不继承主窗口的
# stylesheet，必须同时挂上 APP_QSS 才能拿到字体与基础控件外观。
DIALOG_QSS = """
QDialog {
    background-color: #F4F6FA;
}
#dialogTitle {
    font-size: 13pt;
    font-weight: 600;
    color: #17233B;
}
#dialogSection {
    font-size: 9pt;
    font-weight: 600;
    color: #3C4A5F;
}
#dialogHint {
    font-size: 8.5pt;
    color: #93A0B4;
}
#dialogCard, #dialogPreview {
    background-color: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}
#dialogLine {
    color: #EDF1F7;
    background-color: #EDF1F7;
    max-height: 1px;
    border: none;
}
#dialogPreviewValue {
    font-size: 11pt;
    font-weight: 600;
    color: #1668DC;
}
#enableAlarm {
    font-size: 10.5pt;
    color: #26364D;
    spacing: 9px;
}
QRadioButton {
    font-size: 10pt;
    color: #26364D;
    spacing: 8px;
}
QRadioButton:disabled {
    color: #AFB9C7;
}
QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    border-radius: 6px;
    min-height: 28px;
    padding-left: 6px;
    padding-right: 2px;
    color: #26364D;
    font-size: 10pt;
    selection-background-color: #CFE0F7;
}
QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #B7CBE7;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #1668DC;
}
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #AFB9C7;
    background-color: #F8FAFC;
    border-color: #EAEEF4;
}
QPushButton#dialogPrimary {
    background-color: #1668DC;
    border: 1px solid #1668DC;
    color: #FFFFFF;
    min-height: 34px;
    min-width: 84px;
    padding: 0 16px;
    border-radius: 7px;
    text-align: center;
    font-weight: 600;
}
QPushButton#dialogPrimary:hover {
    background-color: #2C7BE9;
    border-color: #2C7BE9;
}
QPushButton#dialogPrimary:pressed {
    background-color: #1156BA;
    border-color: #1156BA;
}
QPushButton#dialogGhost {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    color: #26364D;
    min-height: 34px;
    min-width: 84px;
    padding: 0 16px;
    border-radius: 7px;
    text-align: center;
}
QPushButton#dialogGhost:hover {
    background-color: #F3F7FD;
    border-color: #B7CBE7;
}
QPushButton#dialogGhost:pressed {
    background-color: #E7EFFA;
}
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    border-radius: 6px;
    min-height: 28px;
    padding-left: 8px;
    padding-right: 6px;
    color: #26364D;
    font-size: 10pt;
    selection-background-color: #CFE0F7;
}
QLineEdit:hover {
    border-color: #B7CBE7;
}
QLineEdit:focus {
    border-color: #1668DC;
}
QLineEdit:disabled {
    color: #AFB9C7;
    background-color: #F8FAFC;
    border-color: #EAEEF4;
}
QPushButton#dialogMini {
    background-color: #FFFFFF;
    border: 1px solid #DCE2EC;
    border-radius: 6px;
    color: #26364D;
    min-height: 30px;
    padding: 0 10px;
    text-align: center;
    font-size: 9pt;
}
QPushButton#dialogMini:hover {
    background-color: #F3F7FD;
    border-color: #B7CBE7;
}
QPushButton#dialogMini:pressed {
    background-color: #E7EFFA;
}
QPushButton#dialogMini:disabled {
    color: #AFB9C7;
    background-color: #F8FAFC;
    border-color: #EAEEF4;
}
"""

