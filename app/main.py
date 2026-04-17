"""
Frank Voice Agent — 主入口
架构: KWS唤醒 / F4热键 -> VAD录音 -> 本地STT -> LLM精炼 -> 注入
"""
import sys
import os
import signal
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DASHSCOPE_API_KEY
from app.api_client import process_voice_pipeline
from app.ui_tray import FloatingOverlay

import keyboard
from app.kws_handler import KeywordSpotter

# ── 全局状态 ──
overlay = None
kws_engine = None
is_recording = False


def core_voice_pipeline():
    """主管线：录音 -> STT -> LLM -> 注入"""
    global is_recording, overlay, kws_engine
    try:
        # 暂停 KWS 释放麦克风
        if kws_engine:
            kws_engine.toggle_pause(True)
        
        overlay.status_signal.emit('listening', "Listening... (按 F4 或等待静音以结束)")
        
        # 使用 Silero VAD 进行精准录制
        from app.vad import SileroVAD
        from app.audio_handler import stop_recording_event, SAMPLE_RATE
        import scipy.io.wavfile as wav
        
        vad = SileroVAD(silence_duration=0.8)
        audio_data = vad.record_until_silence(stop_event=stop_recording_event)
        
        wav_file = "temp.wav"
        wav.write(wav_file, SAMPLE_RATE, audio_data)
        
        is_recording = False
        if kws_engine:
            kws_engine.toggle_pause(False)
        
        overlay.status_signal.emit('processing', "Processing...")
        
        # 调用核心管线（本地 STT + LLM 精炼）
        text = process_voice_pipeline(wav_file)
        
        if text and len(text.strip()) > 0:
            short_text = text[:20] + "..." if len(text) > 21 else text
            overlay.status_signal.emit('success', f"READY: {short_text}")
        else:
            overlay.status_signal.emit('idle', "WAITING FOR VOICE...")
            
    except Exception as e:
        print(f"[Error] core_voice_pipeline: {e}")
        overlay.status_signal.emit('idle', "WAITING FOR VOICE...")
        is_recording = False
        if kws_engine:
            kws_engine.toggle_pause(False)


def on_hotkey_triggered():
    global is_recording
    if not is_recording:
        is_recording = True
        from app.audio_handler import stop_recording_event
        stop_recording_event.clear()
        threading.Thread(target=core_voice_pipeline, daemon=True).start()
    else:
        print("[System] -> 用户按下热键触发强行中止")
        from app.audio_handler import stop_recording_event
        stop_recording_event.set()


def setup_hotkey_listener():
    try:
        keyboard.add_hotkey('f4', on_hotkey_triggered)
        print("[System] -> 热键 F4 注册成功")
    except Exception as e:
        print(f"[Error] 热键注册失败: {e}")


def safe_exit(signum, frame):
    print("\n[System] 正在安全退出...")
    try:
        keyboard.unhook_all()
    except BaseException:
        pass
    QApplication.quit()
    sys.exit(0)


def on_api_text_callback(mode, text):
    global overlay
    if overlay:
        overlay.text_signal.emit(mode, text)


def main():
    print("=" * 50)
    print("  Frank Voice Agent v2.0 — 本地 STT + 记忆 + 场景感知")
    print("=" * 50)
    
    signal.signal(signal.SIGINT, safe_exit)
    
    qt_app = QApplication(sys.argv)
    
    global overlay
    overlay = FloatingOverlay()
    overlay.status_signal.connect(overlay.set_status)
    overlay.text_signal.connect(overlay.update_text)
    
    # 注入回调
    import app.api_client
    app.api_client.ON_TEXT_UPDATE = on_api_text_callback
    
    # 预热 STT 模型（后台线程，不阻塞 UI）
    # 必须与 api_client.py 中的推理模型一致
    def warmup_stt():
        try:
            from app.stt import get_model
            get_model("large-v3-turbo")
        except Exception as e:
            print(f"[System] STT 预热失败: {e}")
    threading.Thread(target=warmup_stt, daemon=True).start()
    
    # 热键
    setup_hotkey_listener()
    print("\n[READY] 按 F4 或喊 '小V' 开始语音输入")
    
    # KWS 唤醒线程
    try:
        model_path = os.path.join(os.getcwd(), "models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
        if os.path.exists(model_path):
            global kws_engine
            kws_engine = KeywordSpotter(model_path)
            threading.Thread(target=kws_engine.start, args=(on_hotkey_triggered,), daemon=True).start()
        else:
            print("[System] KWS 模型未就绪，仅支持热键唤醒")
    except Exception as e:
        print(f"[System] KWS 启动失败: {e}")
    
    # 心跳（防 PyQt 僵死）
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
