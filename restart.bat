@echo off
chcp 65001 >nul
title IR Platform - 重启前后端
setlocal enabledelayedexpansion

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend
set PYTHON=%BACKEND%\venv\Scripts\python.exe

echo ============================================
echo   IR Platform 一键重启
echo   项目目录: %ROOT%
echo ============================================
echo.

REM ============================================
REM Step 1: 杀掉后端进程（端口 8000）
REM ============================================
echo [1/5] 正在停止后端 (port 8000) ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " 2^>nul') do (
    echo   杀掉 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo   后端已停止

REM ============================================
REM Step 2: 杀掉前端进程（端口 5173）
REM ============================================
echo [2/5] 正在停止前端 (port 5173) ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " 2^>nul') do (
    echo   杀掉 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo   前端已停止

REM 等待端口释放
timeout /t 2 /nobreak >nul

REM ============================================
REM Step 3: 清理 Python 缓存
REM ============================================
echo [3/5] 清理 Python 缓存 ...
for /d /r "%BACKEND%\app" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
)
echo   缓存已清理

REM ============================================
REM Step 4: 启动后端
REM ============================================
echo [4/5] 启动后端 (port 8000) ...
if not exist "%PYTHON%" (
    echo   [错误] Python 未找到: %PYTHON%
    goto :error
)

cd /d "%BACKEND%"
start "IR-Backend" cmd /k "cd /d %BACKEND% && echo ===== 后端 http://localhost:8000/docs ===== && %PYTHON% -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo   后端窗口已打开

REM ============================================
REM Step 5: 启动前端
REM ============================================
echo [5/5] 启动前端 (port 5173) ...
if not exist "%FRONTEND%\package.json" (
    echo   [错误] 前端项目未找到: %FRONTEND%
    goto :error
)

cd /d "%FRONTEND%"
start "IR-Frontend" cmd /k "cd /d %FRONTEND% && echo ===== 前端 http://localhost:5173 ===== && npm run dev"
echo   前端窗口已打开

echo.
echo ============================================
echo   全部启动完成！
echo   后端: http://localhost:8000/docs
echo   前端: http://localhost:5173
echo ============================================
goto :end

:error
echo.
echo ============================================
echo   启动失败！请检查项目路径
echo ============================================

:end
pause
