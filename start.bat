@echo off
title IR Platform
cd /d "%~dp0"
set ROOT=%CD%

echo [1/3] 启动后端 ...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 1 >nul

start "IR-Backend" "%ROOT%\backend\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
echo   后端 -> http://localhost:8000/docs

echo [2/3] 启动前端 ...
start "IR-Frontend" cmd /c "cd /d "%ROOT%\frontend" && npm run dev"
echo   前端 -> http://localhost:5173

echo [3/3] 启动完成！
echo.
echo 两个新窗口已打开（后端 + 前端）。
echo 关掉对应窗口即可停止。
echo.
pause
