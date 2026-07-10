@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where python >nul 2>&1 || (echo [错误] 未找到 python，请先安装 Python 3.11+ && pause && exit /b 1)
python start.py %*
