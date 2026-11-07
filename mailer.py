# -*- coding: utf-8 -*-
"""预警邮件发送。

单独成模块的原因：util.py 一被导入就会拉起 openvino（约 0.3 秒、数百 MB），
而告警与设置对话框只需要发信能力。把 SMTP 部分抽出来，启动阶段就不必为了
一个邮件函数把推理运行时也加载进来。

凭据来源按优先级取：`mail_config.py`（本机私有文件，不进版本库）→ 环境变量。
两者都没有时程序照常启动，只在真正要发信时返回一句明确的提示，
不会因为缺配置就崩溃——别人克隆仓库后可以先把界面跑起来再配邮箱。
"""

import importlib.util
import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formataddr


def _load_local_config():
    """读取本机的 mail_config.py，找不到返回 None。

    优先按「程序目录下的文件」加载，而不是直接 import：打包成 exe 后
    import 只会命中打进包里的那份副本，用户改了配置必须重新打包；
    改为读文件则 exe 同级放一份就能生效。源码运行时两者指向同一个文件。
    """
    base = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'mail_config.py')
    if os.path.isfile(path):
        try:
            spec = importlib.util.spec_from_file_location('mail_config', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            # 配置文件写坏了也要能启动：退回「未配置」状态并给出提示
            return None
    try:
        import mail_config as module
        return module
    except ImportError:
        return None


# 配置文件缺失属正常情况（首次克隆仓库时就没有），不记为错误
_local = _load_local_config()


def _setting(name, env_name, default=''):
    """先读本机配置文件，再退回环境变量，最后用默认值。"""
    value = getattr(_local, name, None) if _local is not None else None
    if not value:
        value = os.environ.get(env_name)
    return value if value else default


my_sender = _setting('SENDER', 'METER_SMTP_USER')
my_pass = _setting('AUTH_CODE', 'METER_SMTP_PASS')
my_user = _setting('DEFAULT_TO', 'METER_MAIL_TO')      # 默认收件人，界面可改

# SMTP 连接超时（秒）。不设上限时网络不通会一直挂着后台线程，
# 用户只看到“发送中”却永远等不到结果
SMTP_TIMEOUT = 15

SMTP_HOST = _setting('SMTP_HOST', 'METER_SMTP_HOST', 'smtp.qq.com')
SMTP_PORT = int(_setting('SMTP_PORT', 'METER_SMTP_PORT', 465))   # QQ 邮箱为 SSL 465

CONFIG_HINT = ('未配置发件邮箱：请复制 mail_config.example.py 为 mail_config.py，'
               '填写邮箱账号与授权码后重启程序')


def is_configured():
    """发信所需的最小配置是否齐全。界面可据此提前提示，而不是等到越限。"""
    return bool(my_sender and my_pass)


def _to_list(recipients):
    """把收件人统一成列表：允许传字符串、列表或 None。"""
    if not recipients:
        return [my_user] if my_user else []
    if isinstance(recipients, str):
        return [part.strip() for part in recipients.replace(';', ',').split(',')
                if part.strip()]
    return [str(item).strip() for item in recipients if str(item).strip()]


def mail(body='表计读数异常请查看', subject="表计读数监测系统", to=None):
    """发送告警邮件，返回 (是否成功, 说明)。

    body 携带具体读数，收信人无需再登录系统确认；to 由界面设置传入，
    为空时退回默认收件人。
    """
    if not is_configured():
        return False, CONFIG_HINT
    recipients = _to_list(to)
    if not recipients:
        return False, '未配置收件邮箱：请在「告警设置」里填写收件人'
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = formataddr(["表计读数监测系统", my_sender])
        # 多个收件人直接以逗号拼接；地址本身是 ASCII，无需再编码昵称
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject

        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        try:
            server.login(my_sender, my_pass)
            server.sendmail(my_sender, recipients, msg.as_string())
        finally:
            # 登录失败时也要关掉连接，否则异常路径会留下半开的 socket
            try:
                server.quit()
            except Exception:
                pass
    except Exception as exc:
        # 把失败原因带回界面：打包后没有控制台，静默失败等于没有告警
        return False, '{}: {}'.format(type(exc).__name__, exc)
    return True, '、'.join(recipients)
