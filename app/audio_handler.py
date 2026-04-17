import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import queue
import time
import os
import threading

# 暴露一个用户层主导的热键熔断保险丝
stop_recording_event = threading.Event()

# 音频配置参数
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = 'int16'

def apply_voice_filter(data, rate):
    """
    带通滤波器：保留 300Hz - 3400Hz (标准电话音质频段)
    有效过滤环境低频隆隆声（风扇、空调）和高频刺耳噪音。
    """
    from scipy.signal import butter, lfilter
    lowcut = 300.0
    highcut = 3400.0
    nyq = 0.5 * rate
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(2, [low, high], btype='band')
    return lfilter(b, a, data).astype(np.int16)

def record_audio_smart(filename="temp.wav", silence_duration=0.8, volume_threshold=None, max_duration=10.0):
    """
    智能录音：支持环境底噪自适应。
    如果 volume_threshold 为 None，则自动嗅探当前环境。
    """
    print(f"[Audio] 请说话... (最长录制 {max_duration} 秒或自动探测静音结束)\r", end='', flush=True)
    q = queue.Queue()
    stop_recording_event.clear()

    def callback(indata, frames, time_info, status):
        q.put(indata.copy())

    audio_data = []
    silent_chunks = 0
    # 每次缓冲约 0.1 秒
    chunk_size = int(SAMPLE_RATE * 0.1) 
    
    start_time = time.time()
    
    # --- 环境音自适应校准 ---
    if volume_threshold is None:
        print("[Audio] 正在校准环境噪音... 请保持安静 0.3s\r", end='', flush=True)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
             noise_sample, _ = stream.read(int(SAMPLE_RATE * 0.3))
             rms_noise = np.sqrt(np.mean(np.square(noise_sample.astype(np.float32))))
             # 将阈值设为底噪的 3 倍，但不低于 400
             volume_threshold = max(400, int(rms_noise * 3.0))
             print(f"[Audio] 校准完成，动态触发阈值: {volume_threshold}       ")
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, blocksize=chunk_size, callback=callback):
        while True:
            # 防爆大绝杀：无论环境有多吵、无论热键二次点击是否失效，超过绝对时间则直接强行出锅！！
            if (time.time() - start_time) > max_duration:
                print("\n[Audio] 达到最长发言极限(10s)，强行熔断结算！")
                break
                
            # 第一优先级：监控用户是否焦急地强行再次按下了断开按钮
            if stop_recording_event.is_set():
                print("\n[Audio] 检测到用户主动释放热键，强制停止录音！")
                break
            
            try:
                # 第二优先级：自动探测停顿
                chunk = q.get(timeout=0.1)
            except queue.Empty:
                continue
                
            audio_data.append(chunk)
            
            # 计算当期切片的 RMS(均方根) 能量
            rms = np.sqrt(np.mean(np.square(chunk.astype(np.float32))))
            
            if rms < volume_threshold:
                silent_chunks += 1
            else:
                rc = ' ' * 20
                print(f"[Audio] 录制中... (当前音量: {int(rms)}) {rc}\r", end='', flush=True)
                silent_chunks = 0 # 说话中打断静音计时
            
            # 当累计静音区块时间 > silence_duration 时，停止
            if silent_chunks > (silence_duration / 0.1):
                # 录制的时间也得大于哪怕0.5秒以免刚启动就退出
                if len(audio_data) > 5:
                    break

    print("\n[Audio] 检测到说话完毕，停止录音。")
    
    if not audio_data:
        print("[Audio] 未采集到有效音频数据。")
        # 写入空白 wav 文件以避免下游报错
        wav.write(filename, SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.int16))
        return filename
    
    final_audio = np.concatenate(audio_data, axis=0)
    
    # 应用带通滤波，让音色更纯净
    try:
        final_audio = apply_voice_filter(final_audio.flatten(), SAMPLE_RATE)
    except Exception as e:
        print(f"[Warning] 语音滤波失败: {e}")
        
    wav.write(filename, SAMPLE_RATE, final_audio)
    return filename

def read_audio_file(filename):
    with open(filename, 'rb') as f:
         return f.read()
