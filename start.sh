#!/bin/bash

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     Frank Voice Agent - Beta 1.0.1            ║"
echo "║     本地STT + 云端LLM/TTS                    ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到Python3，请先安装"
    exit 1
fi

# 检查Node.js
if ! command -v node &> /dev/null; then
    echo "[错误] 未找到Node.js，请先安装"
    exit 1
fi

# 检查依赖
echo "[1/3] 检查Python依赖..."
if ! pip show faster-whisper &> /dev/null; then
    echo "[警告] 正在安装Python依赖..."
    pip install -r requirements.txt -q
fi

echo "[2/3] 启动云端API服务器 (端口3000)..."
node src/server.js &
SERVER_PID=$!

# 等待服务器启动
sleep 2

echo "[3/3] 启动桌面应用..."
python3 -m app.main

# 清理
trap "kill $SERVER_PID 2>/dev/null" EXIT
