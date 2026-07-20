@echo off
chcp 65001 >nul
title IR Platform - 重启
echo 停止运行中的服务 ...
taskkill /F /FI "WINDOWTITLE eq IR-Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq IR-Frontend*" >nul 2>&1
timeout /t 2 /nobreak >nul
echo 重新启动 ...
call start.bat
