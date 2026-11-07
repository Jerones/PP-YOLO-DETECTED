# -*- coding: utf-8 -*-
"""告警设置对话框。

四件事：开关、阈值判定方式、阈值数值、收件邮箱。改动即时预览「当前生效
阈值」，保存后在内存中立即生效，不重启检测流程。

「发送测试」按钮的意义：邮箱写错了界面上看不出来，只有在预警那一刻才
暴露，不如配置时先发一封测试邮件确认链路通。
"""

import threading

from PyQt5 import QtCore, QtWidgets

from settings import (KNOWN_RANGES, MAX_MAIL_TO, MODE_RATIO, MODE_VALUE,
                      UNIT, parse_mails)
from styles import APP_QSS, DIALOG_QSS
from mailer import mail

TEST_SUBJECT = '表计读数监测系统 · 测试邮件'
TEST_BODY = ('这是一封来自表计读数检测系统的测试邮件。\n\n'
             '收到它说明预警邮件的收件地址与发信通道都正常。')


class AlarmSettingsDialog(QtWidgets.QDialog):
    # 测试发信在子线程完成，用信号把结果搬回界面线程
    testFinished = QtCore.pyqtSignal(bool, str)

    def __init__(self, settings, parent=None):
        super(AlarmSettingsDialog, self).__init__(parent)
        self.settings = settings
        self.setWindowTitle('告警设置')
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(APP_QSS + DIALOG_QSS)
        self._build()
        self._load_values()
        self._refresh_state()
        self.testFinished.connect(self._on_test_finished)

    # ---------------- 构建 ----------------

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QtWidgets.QLabel('告警设置', self)
        title.setObjectName('dialogTitle')
        layout.addWidget(title)

        hint = QtWidgets.QLabel('读数持续低于阈值时发送一封邮件，'
                               '点击界面“重置预警”后才会再次发送', self)
        hint.setObjectName('dialogHint')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(self._build_card())
        layout.addWidget(self._build_preview())
        layout.addLayout(self._build_buttons())

    def _build_card(self):
        card = QtWidgets.QFrame(self)
        card.setObjectName('dialogCard')
        box = QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)

        self.enableBox = QtWidgets.QCheckBox('启用低读数邮件告警')
        self.enableBox.setObjectName('enableAlarm')
        self.enableBox.setCursor(QtCore.Qt.PointingHandCursor)
        self.enableBox.toggled.connect(self._refresh_state)
        box.addWidget(self.enableBox)

        self.triggerHint = QtWidgets.QLabel()
        self.triggerHint.setObjectName('dialogHint')
        self.triggerHint.setWordWrap(True)
        box.addWidget(self.triggerHint)

        box.addWidget(self._line())

        mode_label = QtWidgets.QLabel('阈值判定方式')
        mode_label.setObjectName('dialogSection')
        box.addWidget(mode_label)

        self.ratioRadio = QtWidgets.QRadioButton('按量程百分比')
        self.ratioRadio.toggled.connect(self._refresh_state)
        self.ratioSpin = self._make_spin(decimals=0, low=1, high=90,
                                         suffix=' %', width=92)
        self.ratioSpin.valueChanged.connect(self._refresh_state)
        box.addLayout(self._row(self.ratioRadio, self.ratioSpin))

        self.valueRadio = QtWidgets.QRadioButton('自定义读数')
        self.valueRadio.toggled.connect(self._refresh_state)
        self.valueSpin = self._make_spin(decimals=3, low=0.0, high=1000.0,
                                         suffix=' ' + UNIT, width=112,
                                         step=0.1)
        self.valueSpin.valueChanged.connect(self._refresh_state)
        box.addLayout(self._row(self.valueRadio, self.valueSpin))

        self.modeHint = QtWidgets.QLabel()
        self.modeHint.setObjectName('dialogHint')
        self.modeHint.setWordWrap(True)
        box.addWidget(self.modeHint)

        box.addWidget(self._line())

        mail_label = QtWidgets.QLabel('预警邮件收件人')
        mail_label.setObjectName('dialogSection')
        box.addWidget(mail_label)

        self.mailEdit = QtWidgets.QLineEdit()
        self.mailEdit.setPlaceholderText('name@example.com')
        self.mailEdit.setClearButtonEnabled(True)
        self.mailEdit.textChanged.connect(self._refresh_mail_state)
        self.testBtn = QtWidgets.QPushButton('发送测试')
        self.testBtn.setObjectName('dialogMini')
        self.testBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.testBtn.setFixedWidth(84)
        self.testBtn.clicked.connect(self._send_test)
        mail_row = QtWidgets.QHBoxLayout()
        mail_row.setContentsMargins(0, 0, 0, 0)
        mail_row.setSpacing(10)
        mail_row.addWidget(self.mailEdit, 1)
        mail_row.addWidget(self.testBtn)
        box.addLayout(mail_row)

        self.mailHint = QtWidgets.QLabel()
        self.mailHint.setObjectName('dialogHint')
        self.mailHint.setWordWrap(True)
        box.addWidget(self.mailHint)
        return card

    @staticmethod
    def _line():
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setObjectName('dialogLine')
        return line

    @staticmethod
    def _make_spin(decimals, low, high, suffix, width, step=1.0):
        """数值输入框。

        去掉系统自带的上下箭头：那套原生箭头与自定义圆角边框格格不入，
        而键盘上下键与滚轮调节仍然可用，属于纯视觉取舍。
        """
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setFixedWidth(width)
        spin.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        return spin

    @staticmethod
    def _row(radio, spin):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(radio)
        layout.addStretch(1)
        layout.addWidget(spin)
        return layout

    def _build_preview(self):
        frame = QtWidgets.QFrame(self)
        frame.setObjectName('dialogPreview')
        box = QtWidgets.QVBoxLayout(frame)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)

        cap = QtWidgets.QLabel('当前生效阈值')
        cap.setObjectName('dialogHint')
        box.addWidget(cap)

        self.previewLabel = QtWidgets.QLabel()
        self.previewLabel.setObjectName('dialogPreviewValue')
        self.previewLabel.setWordWrap(True)
        box.addWidget(self.previewLabel)
        return frame

    def _build_buttons(self):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch(1)

        cancel = QtWidgets.QPushButton('取消')
        cancel.setObjectName('dialogGhost')
        cancel.setCursor(QtCore.Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

        save = QtWidgets.QPushButton('保存')
        save.setObjectName('dialogPrimary')
        save.setCursor(QtCore.Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        layout.addWidget(save)
        return layout

    # ---------------- 数据 ----------------

    def _load_values(self):
        settings = self.settings
        self.enableBox.setChecked(settings.alarm_enabled)
        self.ratioRadio.setChecked(settings.threshold_mode == MODE_RATIO)
        self.valueRadio.setChecked(settings.threshold_mode == MODE_VALUE)
        self.ratioSpin.setValue(settings.alarm_ratio * 100.0)
        self.valueSpin.setValue(settings.alarm_value)
        self.mailEdit.setText(settings.mail_to)
        # 光标回到行首，否则输入框会滚到末尾，前面的字符被挡住看不见
        self.mailEdit.setCursorPosition(0)
        self.triggerHint.setText(
            '连续 {} 次越限后发送一封邮件；此后读数再怎么变化也不会重复发送，'
            '直到点击界面“重置预警”'.format(settings.alarm_consecutive))

    def _refresh_state(self):
        enabled = self.enableBox.isChecked()
        use_ratio = self.ratioRadio.isChecked()
        # 未选中的那一项控件置灰，避免误以为同时在生效
        self.ratioRadio.setEnabled(enabled)
        self.valueRadio.setEnabled(enabled)
        self.ratioSpin.setEnabled(enabled and use_ratio)
        self.valueSpin.setEnabled(enabled and not use_ratio)
        for widget in (self.mailEdit, self.testBtn):
            widget.setEnabled(enabled)

        self.modeHint.setText(
            '按量程百分比：各表按自己的量程换算，两种表都适用'
            if use_ratio else
            '自定义读数：所有表计统一使用这个绝对值')
        self.previewLabel.setText(self._preview_text(enabled, use_ratio))
        self._refresh_mail_state()

    def _refresh_mail_state(self):
        valid, invalid = parse_mails(self.mailEdit.text())
        self.testBtn.setEnabled(self.enableBox.isChecked() and bool(valid))
        if invalid:
            self.mailHint.setText(
                '<span style="color:#D9534F;">无法识别的地址：{}　'
                '格式应形如 name@example.com</span>'.format('、'.join(invalid)))
        elif not valid:
            self.mailHint.setText(
                '<span style="color:#D9534F;">请填写收件邮箱，'
                '否则预警邮件发不出去</span>')
        elif len(valid) > MAX_MAIL_TO:
            self.mailHint.setText(
                '<span style="color:#D9534F;">最多 {} 个收件人，'
                '多余的会被忽略</span>'.format(MAX_MAIL_TO))
        elif len(valid) > 1:
            self.mailHint.setText(
                '将发送至 {} 个收件人：{}'.format(len(valid), '、'.join(valid)))
        else:
            self.mailHint.setText('将发送至：{}'.format(valid[0]))

    def _preview_text(self, enabled, use_ratio):
        if not enabled:
            return '邮件告警已关闭，读数越限仍会在界面标红'
        if use_ratio:
            ratio = self.ratioSpin.value() / 100.0
            lines = [
                '{} MPa 表　低于 {:.3f} MPa'.format(rng, rng * ratio)
                for rng in KNOWN_RANGES
            ]
            return '<br>'.join(lines)
        return '所有表计　低于 {:.3f} {}'.format(
            self.valueSpin.value(), UNIT)

    # ---------------- 测试发信 ----------------

    def _send_test(self):
        valid, _invalid = parse_mails(self.mailEdit.text())
        if not valid:
            return
        self.testBtn.setEnabled(False)
        self.testBtn.setText('发送中')
        self.mailHint.setText('正在连接邮件服务器…')
        threading.Thread(target=self._run_test, args=(valid,),
                         daemon=True).start()

    def _run_test(self, recipients):
        ok, detail = mail(body=TEST_BODY, subject=TEST_SUBJECT, to=recipients)
        try:
            self.testFinished.emit(ok, detail)
        except RuntimeError:
            # 对话框已被关闭销毁，结果无处可显示，直接丢弃
            pass

    def _on_test_finished(self, ok, detail):
        self.testBtn.setEnabled(self.enableBox.isChecked())
        self.testBtn.setText('发送测试')
        if ok:
            self.mailHint.setText(
                '<span style="color:#1E7F4F;">测试邮件已发送至 {}，'
                '请到收件箱确认</span>'.format(detail))
        else:
            self.mailHint.setText(
                '<span style="color:#D9534F;">发送失败：{}</span>'.format(detail))

    # ---------------- 保存 ----------------

    def _save(self):
        settings = self.settings
        enabled = self.enableBox.isChecked()
        valid, invalid = parse_mails(self.mailEdit.text())
        if enabled and not valid:
            QtWidgets.QMessageBox.warning(
                self, '提示',
                '请先填写正确的收件邮箱。\n\n格式应形如 name@example.com。')
            self.mailEdit.setFocus()
            return
        if enabled and invalid:
            QtWidgets.QMessageBox.warning(
                self, '提示',
                '以下地址格式不正确，请修正或删除：\n{}'.format(
                    '、'.join(invalid)))
            self.mailEdit.setFocus()
            return

        settings.alarm_enabled = enabled
        settings.threshold_mode = (
            MODE_RATIO if self.ratioRadio.isChecked() else MODE_VALUE)
        settings.alarm_ratio = self.ratioSpin.value() / 100.0
        settings.alarm_value = self.valueSpin.value()
        if valid:
            settings.mail_to = self.mailEdit.text()
        saved = settings.save()
        if not saved:
            QtWidgets.QMessageBox.warning(
                self, '提示',
                '设置已在本次运行中生效，但写入配置文件失败：\n{}'.format(
                    settings.load_error))
        self.accept()


def open_alarm_settings(settings, parent=None):
    """弹出对话框，返回是否保存了修改。"""
    dialog = AlarmSettingsDialog(settings, parent)
    return dialog.exec_() == QtWidgets.QDialog.Accepted
