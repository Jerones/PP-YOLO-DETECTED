# -*- coding: utf-8 -*-
"""SMTP 发件配置模板。

使用方法：把本文件复制一份并改名为 mail_config.py，填入自己的邮箱信息。
mail_config.py 已在 .gitignore 中，不会被提交；本模板可以安全地留在仓库里。

关于 QQ 邮箱授权码：
    登录 QQ 邮箱 → 设置 → 账户 → 开启「POP3/SMTP 服务」→ 生成授权码。
    授权码是 16 位字母，不是 QQ 登录密码；用密码登录会直接被服务器拒绝。
    其他邮箱（163、Gmail 等）同理，需要开启 SMTP 并生成授权码/应用专用密码。
"""

SENDER = 'your_account@qq.com'      # 发件邮箱账号
AUTH_CODE = 'your_auth_code'        # 发件邮箱授权码（16 位，不是登录密码）
DEFAULT_TO = 'receiver@example.com'  # 默认收件人，程序界面里也可以随时改

SMTP_HOST = 'smtp.qq.com'           # 换服务商时改这里，例如 smtp.163.com
SMTP_PORT = 465                     # SSL 端口；若用 587 需在 mailer.py 改成 STARTTLS
