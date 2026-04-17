"""
Silero VAD（语音活动检测）
利用 sherpa-onnx 内置的 Silero VAD 模型实现高精度端点检测。
延迟 < 30ms，CPU 占用极低。
"""
import os
import numpy as np
import sounddevice as sd
import threading
import queue
import time

SAMPLE_RATE = 16000

class SileroVAD:
    """
    基于 sherpa-onnx 的 Silero VAD 封装。
    功能：从麦克风流中精准检测"说话开始"和"说话结束"。
    """
    def __init__(self, 
                 silence_duration=0.8,     # 静音多久算说完（秒）
                 speech_threshold=0.5,     # VAD 概率阈值
                 min_speech_duration=0.3,  # 最短有效说话时长（秒），过滤咳嗽/喷嚏
                 max_duration=15.0):       # 最大录音时长（防爆保护）
        self.silence_duration = silence_duration
        self.speech_threshold = speech_threshold
        self.min_speech_duration = min_speech_duration
        self.max_duration = max_duration
        self.sample_rate = SAMPLE_RATE
        
        # 尝试使用 sherpa-onnx 内置 Silero VAD
        self.vad = self._init_vad()
    
    def _init_vad(self):
        """初始化 Silero VAD via sherpa-onnx"""
        try:
            import sherpa_onnx
            
            # sherpa-onnx 内置了 Silero VAD 模型，无需额外下载
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = self._find_vad_model()
            config.silero_vad.threshold = self.speech_threshold
            config.silero_vad.min_silence_duration = self.silence_duration
            config.silero_vad.min_speech_duration = self.min_speech_duration
            config.sample_rate = self.sample_rate
            
            vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
            print("[VAD] Silero VAD 初始化成功 (sherpa-onnx)")
            return vad
        except Exception as e:
            print(f"[VAD] Silero VAD 初始化失败: {e}，将回退至 RMS 能量检测")
            return None
    
    def _find_vad_model(self):
        """查找 Silero VAD ONNX 模型文件"""
        # 优先在项目 models 目录下查找
        candidates = [
            os.path.join(os.getcwd(), "models", "silero_vad.onnx"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        
        # 没找到就让 sherpa-onnx 使用内置路径（某些版本支持）
        # 如果不支持则抛出异常，回退到 RMS
        raise FileNotFoundError("silero_vad.onnx 未找到")
    
    def record_until_silence(self, stop_event=None):
        """
        核心接口：打开麦克风，等待说话开始，检测说话结束，返回完整音频。
        
        Returns:
            np.ndarray: int16 格式的音频数据
        """
        if self.vad:
            return self._record_with_vad(stop_event)
        else:
            return self._record_with_rms(stop_event)
    
    def _record_with_vad(self, stop_event):
        """使用 Silero VAD 的精准录音"""
        audio_chunks = []
        audio_q = queue.Queue()
        chunk_size = int(self.sample_rate * 0.1)  # 100ms
        
        def callback(indata, frames, time_info, status):
            audio_q.put(indata.copy())
        
        start_time = time.time()
        has_speech = False
        
        with sd.InputStream(samplerate=self.sample_rate, channels=1, 
                           dtype='float32', blocksize=chunk_size, callback=callback):
            while True:
                # 超时保护
                if (time.time() - start_time) > self.max_duration:
                    print("\n[VAD] 达到最大录音时长，强制结束")
                    break
                
                # 外部中断信号
                if stop_event and stop_event.is_set():
                    print("\n[VAD] 收到外部中断信号")
                    break
                
                try:
                    chunk = audio_q.get(timeout=0.15)
                except queue.Empty:
                    continue
                
                samples = chunk.reshape(-1)
                audio_chunks.append(samples)
                
                # 喂入 VAD
                self.vad.accept_waveform(samples)
                
                if self.vad.is_speech_detected():
                    if not has_speech:
                        print("[VAD] >> 检测到说话开始")
                        has_speech = True
                
                # 当 VAD 检测到一段完整的话结束时
                while not self.vad.empty():
                    segment = self.vad.front()
                    self.vad.pop()
                    if has_speech:
                        print(f"[VAD] << 说话结束 (持续 {segment.duration:.1f}s)")
                        # 将所有收集到的音频拼接并转为 int16
                        all_audio = np.concatenate(audio_chunks)
                        return (all_audio * 32767).astype(np.int16)
        
        # 退出循环（超时或中断）
        if audio_chunks:
            all_audio = np.concatenate(audio_chunks)
            return (all_audio * 32767).astype(np.int16)
        return np.zeros(self.sample_rate, dtype=np.int16)
    
    def _record_with_rms(self, stop_event):
        """回退方案：基于 RMS 能量的录音（增强版）"""
        import scipy.io.wavfile as wav
        
        audio_data = []
        audio_q = queue.Queue()
        chunk_size = int(self.sample_rate * 0.1)
        silent_chunks = 0
        
        # 环境校准
        print("[VAD-RMS] 正在校准环境噪音...", end='', flush=True)
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16') as stream:
            noise_sample, _ = stream.read(int(self.sample_rate * 0.3))
            rms_noise = np.sqrt(np.mean(np.square(noise_sample.astype(np.float32))))
            threshold = max(400, int(rms_noise * 3.0))
            print(f" 阈值={threshold}")
        
        def callback(indata, frames, time_info, status):
            audio_q.put(indata.copy())
        
        start_time = time.time()
        
        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                           dtype='int16', blocksize=chunk_size, callback=callback):
            while True:
                if (time.time() - start_time) > self.max_duration:
                    break
                if stop_event and stop_event.is_set():
                    break
                
                try:
                    chunk = audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                audio_data.append(chunk)
                rms = np.sqrt(np.mean(np.square(chunk.astype(np.float32))))
                
                if rms < threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                
                if silent_chunks > (self.silence_duration / 0.1) and len(audio_data) > 5:
                    break
        
        if not audio_data:
            return np.zeros(self.sample_rate, dtype=np.int16)
        return np.concatenate(audio_data, axis=0).flatten()
