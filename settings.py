# -*- coding: utf-8 -*-
"""用户设置：低读数邮件告警的开关、阈值判定方式与收件邮箱。

设置写到 exe 同级的 settings.json。选择普通 JSON 而非 QSettings 注册表，
是为了能随程序目录整体拷贝，也方便用户直接打开检查；文件损坏时回落到
默认值而不是抛异常，避免一个坏配置就让程序起不来。
"""

import json
import os
import re

from mailer import my_user as DEFAULT_MAIL_TO
from paths import app_dir

SETTINGS_FILE = 'settings.json'

# 阈值判定方式
MODE_RATIO = 'ratio'   # 按量程百分比：自动适配 25MPa 与 1.6MPa 两种表
MODE_VALUE = 'value'   # 用户指定的固定读数：所有表计统一使用

MODE_LABELS = {
    MODE_RATIO: '按量程百分比',
    MODE_VALUE: '自定义读数阈值',
}

DEFAULT_RATIO = 0.10
DEFAULT_VALUE = 6.0
DEFAULT_CONSECUTIVE = 3

# 上次使用的摄像头序号：外接摄像头通常排在 1 号，记住选择就不用每次重选
DEFAULT_CAMERA_INDEX = 0
CAMERA_INDEX_RANGE = (0, 15)

# 收件邮箱默认值来自本机 mail_config.py；没配置时为空，由界面提示填写
MAX_MAIL_TO = 5

# 系统里出现过两种量程的表，单位相同。界面用它预览「当前生效阈值」
KNOWN_RANGES = (25.0, 1.6)
UNIT = 'MPa'

# 取值上下限：手改 JSON 写了离谱的数也不会让告警失效
RATIO_RANGE = (0.01, 0.90)
VALUE_RANGE = (0.0, 1000.0)
CONSECUTIVE_RANGE = (1, 20)

# 不做严格的 RFC 校验，只挡住明显写错的情况：
# 必须形如 name@host.tld，不含空格与中文标点
MAIL_PATTERN = re.compile(
    r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$')
# 多个收件人可用中英文逗号、分号、顿号或空格分隔
MAIL_SPLIT = re.compile(r'[;,，；、\s]+')


def parse_mails(text):
    """把用户输入拆成邮箱列表，返回 (合法列表, 非法片段列表)。

    界面保存前的校验、发信前的取值、JSON 手改后的容错都走这一个函数，
    保证「界面能填的」与「程序能发的」始终是同一套规则。
    """
    if not text:
        return [], []
    valid = []
    invalid = []
    for part in MAIL_SPLIT.split(str(text)):
        if not part:
            continue
        if MAIL_PATTERN.match(part):
            valid.append(part)
        else:
            invalid.append(part)
    return valid, invalid


def _clamp(value, bounds):
    low, high = bounds
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if number != number:            # NaN
        return low
    return max(low, min(high, number))


class AppSettings:
    """告警设置。

    每次赋值都会做范围收敛，界面上限、文件里手改的值走同一条校验路径，
    不会出现「界面不让填但配置文件能填」的漏洞。
    """

    def __init__(self, path=None):
        self.path = path or os.path.join(app_dir(), SETTINGS_FILE)
        self.load_error = None
        self._alarm_enabled = True
        self._threshold_mode = MODE_RATIO
        self._alarm_ratio = DEFAULT_RATIO
        self._alarm_value = DEFAULT_VALUE
        self._alarm_consecutive = DEFAULT_CONSECUTIVE
        self._mail_to = DEFAULT_MAIL_TO
        self._camera_index = DEFAULT_CAMERA_INDEX
        self.load()

    # ---------------- 字段 ----------------

    @property
    def alarm_enabled(self):
        return self._alarm_enabled

    @alarm_enabled.setter
    def alarm_enabled(self, value):
        self._alarm_enabled = bool(value)

    @property
    def threshold_mode(self):
        return self._threshold_mode

    @threshold_mode.setter
    def threshold_mode(self, value):
        self._threshold_mode = value if value in MODE_LABELS else MODE_RATIO

    @property
    def alarm_ratio(self):
        return self._alarm_ratio

    @alarm_ratio.setter
    def alarm_ratio(self, value):
        self._alarm_ratio = _clamp(value, RATIO_RANGE)

    @property
    def alarm_value(self):
        return self._alarm_value

    @alarm_value.setter
    def alarm_value(self, value):
        self._alarm_value = _clamp(value, VALUE_RANGE)

    @property
    def alarm_consecutive(self):
        return self._alarm_consecutive

    @alarm_consecutive.setter
    def alarm_consecutive(self, value):
        low, high = CONSECUTIVE_RANGE
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            number = low
        self._alarm_consecutive = max(low, min(high, number))

    @property
    def mail_to(self):
        """收件邮箱，多个用逗号分隔。"""
        return self._mail_to

    @mail_to.setter
    def mail_to(self, value):
        valid, _invalid = parse_mails(value)
        # 只接受合法地址：手改 JSON 写坏了也不会让发信时抛异常；
        # 一个都解析不出来就保留原值，避免把默认收件人清空
        if valid:
            self._mail_to = ', '.join(valid[:MAX_MAIL_TO])

    def mail_to_list(self):
        """发信时用的收件人列表。

        正常情况下非空；`mail_config.py` 与界面都没配时返回空列表，
        由 mailer 给出「未配置收件邮箱」的提示，而不是发往空地址。
        """
        valid, _invalid = parse_mails(self._mail_to)
        if valid:
            return valid
        return [DEFAULT_MAIL_TO] if DEFAULT_MAIL_TO else []

    # ---------------- 摄像头 ----------------

    @property
    def camera_index(self):
        """上次使用的摄像头序号，下次启动直接用它，不必重新选。"""
        return self._camera_index

    @camera_index.setter
    def camera_index(self, value):
        low, high = CAMERA_INDEX_RANGE
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = low
        self._camera_index = max(low, min(high, number))

    # ---------------- 阈值 ----------------

    def threshold_for(self, meter_range):
        """给定量程返回告警下限；无法判定时返回 None。

        recorder（实时）与 dashboard（历史曲线）都走这里，保证两条路径
        画的线、发的告警完全一致。
        """
        if self._threshold_mode == MODE_VALUE:
            return self._alarm_value
        try:
            value = float(meter_range)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value * self._alarm_ratio

    def threshold_text(self):
        """只描述阈值本身，与开关无关。界面用它标注「凭什么算越限」。"""
        if self._threshold_mode == MODE_VALUE:
            return '低于 {:.3f} {}'.format(self._alarm_value, UNIT)
        return '低于量程的 {:.0f}%'.format(self._alarm_ratio * 100)

    def describe_threshold(self):
        """一句话描述当前告警配置，带上开关状态，用于状态栏。"""
        if not self._alarm_enabled:
            return '邮件告警已关闭'
        return self.threshold_text() + ' 告警'

    # ---------------- 持久化 ----------------

    def to_dict(self):
        return {
            'alarm_enabled': self._alarm_enabled,
            'threshold_mode': self._threshold_mode,
            'alarm_ratio': round(self._alarm_ratio, 4),
            'alarm_value': round(self._alarm_value, 4),
            'alarm_consecutive': self._alarm_consecutive,
            'mail_to': self._mail_to,
            'camera_index': self._camera_index,
        }

    def load(self):
        """读配置文件。文件不存在属正常情况，不记录错误。"""
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, mode='r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            # 配置损坏不能影响启动，沿用内存里的默认值
            self.load_error = str(exc)
            return
        if not isinstance(data, dict):
            self.load_error = '配置内容不是键值对'
            return
        self._apply(data)

    def _apply(self, data):
        # 旧版本配置里的 alarm_interval 已经废弃（改为只发一封），
        # 这里不读取也不报错，升级时旧文件可以直接沿用
        self.alarm_enabled = data.get('alarm_enabled', self._alarm_enabled)
        self.threshold_mode = data.get('threshold_mode', self._threshold_mode)
        self.alarm_ratio = data.get('alarm_ratio', self._alarm_ratio)
        self.alarm_value = data.get('alarm_value', self._alarm_value)
        self.alarm_consecutive = data.get('alarm_consecutive',
                                          self._alarm_consecutive)
        self.mail_to = data.get('mail_to', self._mail_to)
        self.camera_index = data.get('camera_index', self._camera_index)

    def save(self):
        """原子写：先写临时文件再替换，避免断电留下半截 JSON。"""
        tmp_path = self.path + '.tmp'
        try:
            with open(tmp_path, mode='w', encoding='utf-8') as handle:
                json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except OSError as exc:
            self.load_error = str(exc)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
        return True
