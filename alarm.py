# -*- coding: utf-8 -*-
"""低读数预警的触发与抑制。

核心规则：同一次越限只发一封邮件。
    连续 N 帧低于下限 → 触发一次预警，发一封邮件 → 进入「已预警」锁定态
    锁定态下读数再怎么波动都不再发信，直到用户在界面点「重置预警」
    重置后重新从零计数，读数仍然偏低时会再发一封，仍然只发一封

锁定状态是「只发一封」的全部依据：没有人工重置，邮件绝不会重复发送，
所以管理员处理完现场回到界面点一下按钮就是「解除抑制」的动作。

状态留在本模块而不是主窗口里，因为它由推理结果驱动，必须与落盘、显示解耦：
recorder 只管写 CSV，主窗口只管显示，这里只管「该不该发信」。
"""

import threading
import time

from mailer import mail


class AlarmCenter:
    """把「连续越限」判定成一次预警，并保证不重复发信。"""

    def __init__(self, settings, sender=None, on_result=None):
        self.settings = settings
        # sender 可注入，测试时替换掉真实 SMTP，不发真邮件
        self._sender = sender or mail
        self.on_result = on_result     # 回调 (ok, detail)，供界面提示发送结果
        self._lock = threading.Lock()
        self._count = {}               # meter_id -> 连续越限帧数
        self._last_value = {}          # meter_id -> 最近一次读数
        self._last_limit = {}          # meter_id -> 该表当前的告警下限
        self._latched = False          # 已发过预警，等待用户重置
        self._latched_at = None
        self._latched_items = []       # [(meter_id, value, limit, unit)]

    # ---------------- 对外状态 ----------------

    @property
    def latched(self):
        return self._latched

    @property
    def latched_summary(self):
        """一句话描述已发出的预警，界面与状态栏用；未预警时为空串。"""
        if not self._latched:
            return ''
        stamp = time.strftime('%H:%M:%S',
                              time.localtime(self._latched_at or time.time()))
        names = '、'.join(str(item[0]) for item in self._latched_items)
        return '{} 已发送预警邮件（表计 {}）'.format(stamp, names)

    def threshold(self, meter):
        """当前表计的告警下限，未知识别量程时返回 None。与开关无关。"""
        return self.settings.threshold_for(meter.get('range'))

    def low_meters(self):
        """按最近一帧的读数，列出当前仍低于下限的表计编号。"""
        with self._lock:
            return [meter_id for meter_id, value in self._last_value.items()
                    if self._last_limit.get(meter_id) is not None
                    and value < self._last_limit[meter_id]]

    def clear_counts(self):
        """摄像头重开等场景调用：清计数，但保留「已预警」锁定态。

        锁定只能由用户点重置解除，否则关一次摄像头再打开就会又发一封。
        """
        with self._lock:
            self._count.clear()
            self._last_value.clear()
            self._last_limit.clear()

    # ---------------- 主流程 ----------------

    def check(self, meters, now=None):
        """处理一帧平滑后的结果，返回本帧是否刚发出预警邮件。"""
        now = time.time() if now is None else now
        if not self.settings.alarm_enabled:
            # 关掉告警后清空计数：重新开启时不该立刻补发一封旧预警
            with self._lock:
                self._count.clear()
            return False

        low_items = []
        triggered = False
        with self._lock:
            for meter in meters:
                value = meter.get('smoothed')
                if value is None or not meter.get('stable'):
                    continue
                meter_id = meter.get('index', 1)
                limit = self.threshold(meter)
                if limit is None:
                    continue
                self._last_value[meter_id] = float(value)
                self._last_limit[meter_id] = limit
                if value >= limit:
                    # 回到正常范围：清掉计数，避免半次越限与新一次累加
                    self._count.pop(meter_id, None)
                    continue
                low_items.append((meter_id, float(value), limit,
                                  meter.get('unit', 'MPa')))
                if self._latched:
                    # 已发过信且未重置：继续记录读数，但绝不再发
                    continue
                count = self._count.get(meter_id, 0) + 1
                self._count[meter_id] = count
                if count >= self.settings.alarm_consecutive:
                    triggered = True

            if not triggered:
                return False
            # 锁定：这一帧所有越限表计并入同一封邮件，一次预警一封信
            self._latched = True
            self._latched_at = now
            self._latched_items = low_items
            self._count.clear()

        self._dispatch(low_items, now)
        return True

    def reset(self):
        """解除预警锁定（界面「重置预警」按钮调用），返回之前是否处于锁定态。"""
        with self._lock:
            was_latched = self._latched
            self._latched = False
            self._latched_at = None
            self._latched_items = []
            self._count.clear()
        return was_latched

    # ---------------- 发信 ----------------

    def _dispatch(self, low_items, now):
        body = self._compose(low_items, now)
        recipients = self.settings.mail_to_list()

        def run():
            ok, detail = self._sender(body=body, to=recipients)
            callback = self.on_result
            if callback is not None:
                callback(ok, detail)

        # SMTP 握手要几秒，放子线程，否则会把界面冻住
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _compose(low_items, now):
        """预警邮件正文。把读数、下限、时间写清楚，收信人不必再查系统。"""
        stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
        lines = ['表计读数低于告警下限，请及时处理。', '']
        for meter_id, value, limit, unit in low_items:
            lines.append('表计编号：第 {} 块'.format(meter_id))
            lines.append('当前读数：{:.3f} {}'.format(value, unit))
            lines.append('告警下限：{:.3f} {}'.format(limit, unit))
            lines.append('')
        lines.append('触发时间：{}'.format(stamp))
        lines.append('')
        lines.append('本次预警只发送这一封邮件，读数持续偏低也不会重复发送。')
        lines.append('处理完成并恢复正常读数后，请在软件界面点击“重置预警”，')
        lines.append('读数再次低于下限时才会发送下一封。')
        return '\n'.join(lines)
