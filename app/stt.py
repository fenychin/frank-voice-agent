"""
本地 STT 引擎 — Faster-Whisper
完全免费、离线运行，替代 OpenAI Whisper API。
"""
import os
import time

# 全局缓存模型实例（避免重复加载）
_model = None
_model_size = None

def get_model(model_size="base"):
    """
    懒加载 Faster-Whisper 模型。
    
    推荐模型：
    - "tiny"  : 最快 (~0.3s/5s音频)，中文准确率一般
    - "base"  : 平衡 (~0.8s/5s音频)，中文准确率不错
    - "small" : 较慢 (~2s/5s音频)，中文准确率好
    - "large-v3-turbo" : GPU 推荐，准确率最高
    """
    global _model, _model_size
    
    if _model is not None and _model_size == model_size:
        return _model
    
    try:
        from faster_whisper import WhisperModel
        
        print(f"[STT] 正在加载 Faster-Whisper 模型: {model_size} ...")
        t0 = time.time()
        
        # 自动检测计算设备
        device = "cpu"
        compute_type = "int8"  # CPU 模式下用 int8 量化加速
        
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                compute_type = "float16"
                print(f"[STT] 检测到 GPU: {torch.cuda.get_device_name(0)}")
        except ImportError:
            pass
        
        _model = WhisperModel(
            model_size, 
            device=device, 
            compute_type=compute_type,
            download_root=os.path.join(os.getcwd(), "models", "whisper"),
        )
        _model_size = model_size
        print(f"[STT] 模型加载完成 ({time.time()-t0:.1f}s, device={device})")
        return _model
        
    except ImportError:
        print("[STT] faster-whisper 未安装！请运行: pip install faster-whisper")
        return None


def transcribe(audio_file, model_size="base", language="zh"):
    """
    将音频文件转录为文本。
    
    Args:
        audio_file: WAV 文件路径
        model_size: Whisper 模型大小
        language: 语言代码 ("zh" 中文, "en" 英文)
    
    Returns:
        str: 转录出的文本
    """
    model = get_model(model_size)
    if model is None:
        return ""
    
    t0 = time.time()
    
    segments, info = model.transcribe(
        audio_file,
        language=language,
        beam_size=3,           # 降低 beam_size 提速
        best_of=1,
        vad_filter=True,       # 内置 VAD 过滤静音段
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )
    
    # 拼接所有 segment 的文本
    text_parts = []
    for segment in segments:
        text_parts.append(segment.text.strip())
    
    full_text = " ".join(text_parts).strip()
    elapsed = time.time() - t0
    print(f"[STT] 转录完成 ({elapsed:.2f}s): {full_text[:50]}...")
    
    return full_text


def transcribe_array(audio_array, sample_rate=16000, model_size="base", language="zh"):
    """
    直接从 numpy 数组转录（跳过文件 I/O）。
    
    Args:
        audio_array: int16 或 float32 的 numpy 数组
        sample_rate: 采样率
    """
    import numpy as np
    import scipy.io.wavfile as wav
    import tempfile
    
    # 写入临时文件（faster-whisper 需要文件路径）
    tmp_path = os.path.join(os.getcwd(), "_stt_tmp.wav")
    
    if audio_array.dtype == np.float32:
        audio_array = (audio_array * 32767).astype(np.int16)
    
    wav.write(tmp_path, sample_rate, audio_array)
    
    try:
        result = transcribe(tmp_path, model_size=model_size, language=language)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    
    return result
