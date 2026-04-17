import os
import sys
import queue
import threading
import numpy as np
import sounddevice as sd
import sherpa_onnx

class KeywordSpotter:
    def __init__(self, model_dir, keywords="小智小智"):
        self.model_dir = model_dir
        self.keywords = keywords
        self.sample_rate = 16000
        self.chunk_size = int(0.1 * self.sample_rate) # 100ms
        self.audio_queue = queue.Queue()
        
        # 寻找模型文件 (根据下载的目录结构调整)
        # 假设下载解压后在 models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01/
        base_path = model_dir
        self.recognizer = self._init_recognizer(base_path)
        self.is_running = False
        self.is_paused = False

    def toggle_pause(self, paused=True):
        """主录音开始时暂停 KWS，防止双麦克风占用冲突"""
        self.is_paused = paused

    def _init_recognizer(self, path):
        # 配置参数适配 sherpa-onnx 1.12+ 的最新 API
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
                num_threads=1, # 降至单线程，减少资源竞争
                provider="cpu",
            ),
            keywords_file=os.path.join(path, "custom_keywords.txt"), # 使用用户自定义的
            max_active_paths=4,
        )
        return kws_mod.KeywordSpotter(config)

    def _create_keywords_file(self, path):
        # 简单创建一个关键字文件
        # 在真实环境里我们需要使用 cli 工具转换文字为 tokens
        # 这里先假设我们直接用拼音或已有的 keywords.txt
        # 改为使用现成的，或者手动写入。为了演示，我们先写入一行硬编码的（如果是 WenetSpeech 中文模型）
        k_file = os.path.join(path, "my_keywords.txt")
        # 温馨提示：真正的 tokens 需要对齐模型的 tokens.txt，这里只是示意结构
        # 建议直接在命令行运行 cli 工具生成。
        with open(k_file, "w", encoding="utf-8") as f:
            f.write(f"{self.keywords} :1.2 #0.4\n")
        return k_file

    def _stream_callback(self, indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        self.audio_queue.put(indata.copy())

    def start(self, callback_func):
        self.is_running = True
        print(f"[KWS] 语音唤醒服务已启动 (模型: WenetSpeech)")
        
        # 创建一个持久流，用于持续处理音频
        stream = self.recognizer.create_stream()
        
        try:
             default_device = sd.query_devices(kind='input')
             print(f"[KWS] 正在监听麦克风: {default_device['name']} (采样率: {self.sample_rate})")
        except:
             print("[KWS] 警告：无法获取默认输入设备，尝试盲启...")

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32', 
                             blocksize=self.chunk_size, callback=self._stream_callback):
            while self.is_running:
                if self.is_paused:
                    time.sleep(0.5)
                    continue
                    
                try:
                    samples = self.audio_queue.get(timeout=0.2)
                    samples = samples.reshape(-1)
                    
                    stream.accept_waveform(self.sample_rate, samples)
                    
                    # 诊断：每隔一段时间打印一下音量峰值，确认麦克风活着
                    if not hasattr(self, '_diag_cnt'): self._diag_cnt = 0
                    self._diag_cnt += 1
                    if self._diag_cnt % 20 == 0:
                        v_max = np.max(np.abs(samples))
                        print(f"[KWS Debug] 监听中... (当前麦克风峰值: {v_max:.4f})\r", end='', flush=True)

                    while self.recognizer.is_ready(stream):
                        self.recognizer.decode_stream(stream)
                    
                    result = self.recognizer.get_result(stream)
                    if result:
                        print(f"[KWS] 匹配到关键词: {result}")
                        callback_func() # 触发主程序的热键逻辑
                        # 识别到后重置流，防止重复触发
                        stream = self.recognizer.create_stream()
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"[KWS] 运行异常: {e}")
                    break

    def stop(self):
        self.is_running = False
