import os
import sys
import time as _time  # 避免与 sounddevice callback 参数名冲突
import queue
import numpy as np
import sounddevice as sd

class KeywordSpotter:
    def __init__(self, model_dir):
        self.model_dir = model_dir
        self.sample_rate = 16000
        self.chunk_size = int(0.1 * self.sample_rate) # 100ms
        self.audio_queue = queue.Queue()
        self.recognizer = self._init_recognizer(model_dir)
        self.is_running = False
        self.is_paused = False
        self._diag_cnt = 0

    def toggle_pause(self, paused=True):
        """主录音开始时暂停 KWS，防止双麦克风占用冲突"""
        self.is_paused = paused

    def _init_recognizer(self, path):
        import sherpa_onnx.keyword_spotter as kws_mod
        
        config = kws_mod.KeywordSpotterConfig(
            feat_config=kws_mod.FeatureExtractorConfig(
                sample_rate=self.sample_rate,
                feature_dim=80,
            ),
            model_config=kws_mod.OnlineModelConfig(
                transducer=kws_mod.OnlineTransducerModelConfig(
                    encoder=os.path.join(path, "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                    decoder=os.path.join(path, "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                    joiner=os.path.join(path, "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
                ),
                tokens=os.path.join(path, "tokens.txt"),
                num_threads=1,
                provider="cpu",
            ),
            keywords_file=os.path.join(path, "custom_keywords.txt"),
            max_active_paths=4,
        )
        return kws_mod.KeywordSpotter(config)

    def _stream_callback(self, indata, frames, time_info, status):
        """注意：参数名改为 time_info，避免遮蔽 stdlib time 模块"""
        if status:
            print(status, file=sys.stderr)
        self.audio_queue.put(indata.copy())

    def start(self, callback_func):
        self.is_running = True
        print("[KWS] 语音唤醒服务已启动 (模型: WenetSpeech)")
        
        stream = self.recognizer.create_stream()
        
        try:
             default_device = sd.query_devices(kind='input')
             print(f"[KWS] 正在监听麦克风: {default_device['name']} (采样率: {self.sample_rate})")
        except Exception:
             print("[KWS] 警告：无法获取默认输入设备，尝试盲启...")

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32', 
                             blocksize=self.chunk_size, callback=self._stream_callback):
            while self.is_running:
                if self.is_paused:
                    # 暂停时清空积压的音频数据，防止恢复后误触发
                    while not self.audio_queue.empty():
                        try: self.audio_queue.get_nowait()
                        except queue.Empty: break
                    _time.sleep(0.3)
                    continue
                    
                try:
                    samples = self.audio_queue.get(timeout=0.2)
                    samples = samples.reshape(-1)
                    
                    stream.accept_waveform(self.sample_rate, samples)
                    
                    # 诊断日志（每 2 秒一次）
                    self._diag_cnt += 1
                    if self._diag_cnt % 20 == 0:
                        v_max = np.max(np.abs(samples))
                        print(f"[KWS] 监听中... (峰值: {v_max:.4f})\r", end='', flush=True)

                    while self.recognizer.is_ready(stream):
                        self.recognizer.decode_stream(stream)
                    
                    result = self.recognizer.get_result(stream)
                    if result:
                        print(f"\n[KWS] >>> 匹配到唤醒词: {result}")
                        callback_func()
                        stream = self.recognizer.create_stream()
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"[KWS] 运行异常: {e}")
                    break

    def stop(self):
        self.is_running = False
