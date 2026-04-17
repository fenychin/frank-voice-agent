@echo off
chcp 65001 >nul
title Frank Voice Agent

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║     Frank Voice Agent - Beta 1.0.1            ║
echo  ║     本地STT + 云端LLM/TTS                    ║
echo  ╚══════════════════════════════════════════════╝
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Node.js，请先安装
    pause
    exit /b 1
)

:: 检查依赖
echo [1/3] 检查Python依赖...
pip show faster-whisper >nul 2>&1
if errorlevel 1 (
    echo [警告] 正在安装Python依赖...
    pip install -r requirements.txt -q
)

echo [2/3] 启动云端API服务器 (端口3000)...
start "Frank API Server" cmd /c "node src\server.js"

:: 等待服务器启动
timeout /t 2 /nobreak >nul

echo [3/3] 启动桌面应用...
python -m app.main

pause
