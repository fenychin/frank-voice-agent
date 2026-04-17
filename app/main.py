import sys
import os
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DASHSCOPE_API_KEY
from app.audio_handler import record_audio_smart, stop_recording_event
from app.api_client import process_voice_pipeline
from app.ui_tray import FloatingOverlay

import keyboard
from app.kws_handler import KeywordSpotter

# 使用主容器自身作为挂钩，极其长寿与稳定！
overlay = None
kws_engine = None
is_recording = False

def core_voice_pipeline():
    """这是在后方执行大管线的核心，不阻塞 UI"""
    global is_recording, overlay, kws_engine
    try:
        if kws_engine: kws_engine.toggle_pause(True)
        overlay.status_signal.emit('listening', "Listening... (按 F4 或等待静音以结束)")
        
        # 启用【自适应环境校准】：不再使用硬编码门限，而是自动嗅探背景噪音
        # 提效：缩短静音检测时间 1.0 -> 0.8
        wav_file = record_audio_smart(filename="temp.wav", silence_duration=0.8, volume_threshold=None)
        
        # ⚠️ 【极其关键升级】录音完毕就立刻释放占用锁！
        is_recording = False
        if kws_engine: kws_engine.toggle_pause(False)
        
        overlay.status_signal.emit('processing', "Processing... 正在投递至阿里云转化注入...")
        
        text = process_voice_pipeline(wav_file)
        
        if text and len(text.strip()) > 0:
            short_text = text[:15] + "..." if len(text)>16 else text
            overlay.status_signal.emit('success', f"READY: {short_text}")
        else:
            overlay.status_signal.emit('idle', "WAITING FOR VOICE...")
    except Exception as e:
        print(f"[Error] core_voice_pipeline 异常: {e}")
        overlay.status_signal.emit('idle', "WAITING FOR VOICE...")
        is_recording = False
        if kws_engine: kws_engine.toggle_pause(False)

def on_hotkey_triggered():
    global is_recording
    if not is_recording:
        is_recording = True
        # 开一个线程以免 `speech_recognition` 和 `VAD` 挂起阻塞 `keyboard` 事件本身！
        stop_recording_event.clear() # 开始新一轮录音前，先重制保险丝
        threading.Thread(target=core_voice_pipeline, daemon=True).start()
    else:
        # 如果还在录音期（红灯），二次按键绝对用来掐断！
        # 直接把保险丝烧掉，然后绝不跑其他任何动作！
        print("[System] -> 用户按下热键触发强行中止")
        stop_recording_event.set()

def setup_hotkey_listener():
    try:
        # 改用 F4 以避开 Windows 常用的 Alt+Space 冲突
        keyboard.add_hotkey('f4', on_hotkey_triggered)
        print("[System] -> 热键 F4 注册成功！")
    except Exception as e:
        print(f"[Error] 热键注册失败: {e}")

import signal

def safe_exit(signum, frame):
    print("\n[System] 收到强制退出指令，正在拆除全局按键钩子与服务...")
    try:
        keyboard.unhook_all()
    except BaseException: pass
    QApplication.quit()
    sys.exit(0)

def on_api_text_callback(mode, text):
    global overlay
    if overlay:
        overlay.text_signal.emit(mode, text)

def main():
    print("=" * 45)
    print(" [Core] Frank Voice Agent - 正在启动...")
    print("=" * 45)
    
    # 接管系统的 Ctrl+C 强制退出信号，防止 PyQt 的死锁卡死终端不掉线
    signal.signal(signal.SIGINT, safe_exit)
    
    # PyQt 的任何挂载必须排在 QApplication 实例化之后，否则会导致毁灭性 C++ 段层崩溃
    qt_app = QApplication(sys.argv)
    
    global overlay
    # 实例化我们的半透明组件，且永生活着
    overlay = FloatingOverlay()
    
    # 信号就挂在自己身上连接自己，绝无丢失的可能
    overlay.status_signal.connect(overlay.set_status)
    overlay.text_signal.connect(overlay.update_text)
    
    # 彻底杜绝使用 Qt 信号的跨模块直接传递！这是引起段错误回收的致命雷！
    # 替换为安全、原生通用的 Python def 控制回调委派：
    import app.api_client
    app.api_client.ON_TEXT_UPDATE = on_api_text_callback
    
    # 注册热键
    setup_hotkey_listener()
    
    print("\n[READY] 屏幕下方已经待机，按下 F4 测试魔法吧！...")
    
    # 启动语音唤醒（KWS）线程
    try:
        model_path = os.path.join(os.getcwd(), "models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
        if os.path.exists(model_path):
            global kws_engine
            kws_engine = KeywordSpotter(model_path)
            threading.Thread(target=kws_engine.start, args=(on_hotkey_triggered,), daemon=True).start()
        else:
            print("[System] 唤醒模型未准备好，仅支持热键唤醒。")
    except Exception as e:
        print(f"[System] 语音唤醒启动失败: {e}")

    # 建立一个定时心跳起搏器，让 Python 能在底层捕捉到您强制敲击的 Ctrl+C 并响应退出
    # 这是 PyQt + 命令行脚本的标准除僵尸死锁防坑补丁
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    
    # PyQt6 事件循环
    sys.exit(qt_app.exec())

if __name__ == "__main__":
    main()
