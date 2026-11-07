@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "mail_config.py" (
    echo [!] 未找到 mail_config.py，邮件告警将不可用。
    echo     需要告警功能请复制 mail_config.example.py 为 mail_config.py 并填写邮箱。
    echo.
)

python detect_logic.py
if errorlevel 1 (
    echo.
    echo 程序异常退出。若提示找不到模块，请先执行：
    echo     pip install -r requirements.txt
    pause
)
