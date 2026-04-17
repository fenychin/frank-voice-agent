"""
核心语音管线 — 重构版
流程: 录音 -> 本地 STT(Faster-Whisper) -> 场景检测 -> LLM 精炼 -> 记忆更新 -> 注入/回读

关键指标对齐:
  - 3秒内响应 (本地 STT ~1s + LLM ~1.5s)
  - 3轮上下文语义连贯
  - 场景自适应 (office/running/driving)
"""
import os
import re
import time
import json
import threading
import dashscope
from app.config import DASHSCOPE_API_KEY
from app.memory_manager import MemoryManager
from app.scene import classify_scene, get_scene_system_prompt, get_max_length

if not DASHSCOPE_API_KEY:
    print("[Warning] 未获取到 DASHSCOPE_API_KEY，阿里云接口调用可能会失败！")

dashscope.api_key = DASHSCOPE_API_KEY

# 全局单例
memory = MemoryManager()
current_scene = "office"
LAST_CONTENT_BUFFER = ""

# 回调钩子（由 main.py 注入）
ON_TEXT_UPDATE = None


def _build_system_prompt(scene, raw_text=""):
    """构建完整的 System Prompt，注入记忆、场景、档案"""
    profile = memory.get_profile_prompt()
    facts = memory.get_facts_prompt()
    scene_prompt = get_scene_system_prompt(scene)
    recall = memory.get_recall_prompt(raw_text) if raw_text else ""
    max_len = get_max_length(scene)
    
    parts = [
        "你是用户的个人语音助手，负责将口语转化为准确文字。",
        "",
        profile,
        facts,
        scene_prompt,
        recall,
        "",
        "【整理规则】",
        "- 去除口语填充词（\"那个\"、\"就是\"、\"嗯\"）",
        "- 补全省略主语和宾语",
        "- 保留用户原意，不添加内容",
        "- 专业术语保持原样（如 \"MCP\"、\"RAG\" 不解释）",
        f"- 输出不超过 {max_len} 字",
        "",
        "【输出格式】",
        "直接输出精炼后的正文，严禁客套话。",
        "如果用户明确说了\"发送\"类指令，在末尾加 [SEND] 标记。",
    ]
    
    # 注入滚动上下文
    ctx = memory.get_rolling_context()
    if ctx:
        parts.append("")
        parts.append("【最近对话上下文（延续语境）】")
        for msg in ctx:
            role_label = "用户" if msg["role"] == "user" else "助手"
            parts.append(f"  {role_label}: {msg['content'][:80]}")
    
    return "\n".join(parts)


def process_voice_pipeline(file_path):
    """
    核心管线入口。
    
    双轨模式:
    - Mode A (快速): 本地 Faster-Whisper STT + DashScope LLM
    - Mode B (备用): DashScope Qwen-Audio 端到端
    """
    global current_scene, LAST_CONTENT_BUFFER
    
    print("=" * 40)
    t_start = time.time()
    
    # ── Step 1: 本地 STT ──
    try:
        _notify('sys', "正在本地转录语音...")
        from app.stt import transcribe
        raw_text = transcribe(file_path, model_size="base", language="zh")
    except Exception as e:
        print(f"[Pipeline] 本地 STT 失败 ({e})，回退到云端 Qwen-Audio")
        raw_text = _fallback_qwen_audio_stt(file_path)
    
    if not raw_text or len(raw_text.strip()) < 2:
        print("[Pipeline] 未检测到有效语音内容")
        return ""
    
    t_stt = time.time()
    print(f"[Pipeline] STT 完成 ({t_stt - t_start:.2f}s): {raw_text}")
    _notify('raw', f"[语音识别] {raw_text}")
    
    # ── Step 2: 场景检测 ──
    current_scene = classify_scene(raw_text, current_scene)
    
    # ── Step 3: LLM 精炼 ──
    system_prompt = _build_system_prompt(current_scene, raw_text)
    
    try:
        _notify('sys', "正在精炼文字...")
        
        response = dashscope.Generation.call(
            model='qwen-turbo',
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请精炼以下口语：{raw_text}"}
            ],
            max_tokens=get_max_length(current_scene),
            temperature=0.3,
            result_format='message',
        )
        
        if response.status_code == 200:
            final_text = response.output.choices[0].message.content.strip()
        else:
            print(f"[Pipeline] LLM 精炼失败: {response.status_code}")
            final_text = raw_text  # 降级：直接使用原始文本
            
    except Exception as e:
        print(f"[Pipeline] LLM 调用异常: {e}")
        final_text = raw_text
    
    t_llm = time.time()
    print(f"[Pipeline] LLM 完成 ({t_llm - t_stt:.2f}s): {final_text}")
    
    # ── Step 4: 清洗与意图判断 ──
    final_text = _clean_llm_output(final_text)
    
    if not final_text or len(final_text.strip()) == 0:
        return ""
    
    # 意图判断
    text_norm = final_text.strip().replace("。", "").replace("！", "").replace(".", "")
    trigger_words = ["发送", "发出去", "完成", "OK", "确定", "行了"]
    
    is_pure_send = text_norm in trigger_words
    contains_send_flag = "[SEND]" in final_text
    should_inject = is_pure_send or contains_send_flag
    
    # 准备有效载荷
    if is_pure_send:
        payload = LAST_CONTENT_BUFFER or "(没有暂存内容，请重新说一遍)"
    else:
        payload = final_text.replace("[SEND]", "").strip()
        LAST_CONTENT_BUFFER = payload
    
    # ── Step 5: 更新记忆 ──
    memory.append_context(raw_text, payload)
    memory.log_session(raw_text, payload, scene=current_scene, 
                       intent="send" if should_inject else "input")
    
    # ── Step 6: 场景化路由 (Text vs TTS) ──
    scene_cfg = memory.get_scene_config(current_scene)
    out_mode = scene_cfg.get("output_mode", "text_inject")
    
    _notify('final', payload)
    
    # 根据场景执行动作
    if current_scene == "office":
        # 办公：仅文字注入 (且非纯发送指令时)
        if should_inject and payload and not payload.startswith("("):
            _execute_injection(payload)
            LAST_CONTENT_BUFFER = ""
    
    elif current_scene == "running":
        # 跑步：文字展示 + TTS 回读
        from app.tts_handler import speak
        threading.Thread(target=speak, args=(payload,), daemon=True).start()
        if should_inject and payload and not payload.startswith("("):
            _execute_injection(payload)
            LAST_CONTENT_BUFFER = ""
            
    elif current_scene == "driving":
        # 驾驶：仅 TTS，不干扰屏幕输入
        from app.tts_handler import speak
        threading.Thread(target=speak, args=(payload,), daemon=True).start()
        # 驾驶模式下不自动注入文字到窗口，保持安全
        LAST_CONTENT_BUFFER = ""

    t_total = time.time() - t_start
    print(f"[Pipeline] 总耗时: {t_total:.2f}s (目标 <3s)")
    
    return payload


def _fallback_qwen_audio_stt(file_path):
    """备用方案：使用 DashScope Qwen-Audio 端到端处理"""
    try:
        response = dashscope.MultiModalConversation.call(
            model='qwen-audio-turbo',
            messages=[{
                "role": "user",
                "content": [
                    {"audio": f"file://{os.path.abspath(file_path)}"},
                    {"text": "请将这段语音的内容原样转录为文字，不要修改、不要总结。"}
                ]
            }]
        )
        if response.status_code == 200:
            content_list = response.output.choices[0].message.content
            return "".join([item.get('text', '') for item in content_list if 'text' in item])
    except Exception as e:
        print(f"[Fallback] Qwen-Audio 也失败了: {e}")
    return ""


def _clean_llm_output(text):
    """清洗大模型输出中的冗余前缀和礼貌废话"""
    if not text:
        return ""
    
    # 去掉常见废话前缀
    if text.startswith("好的"):
        text = text.split("好的", 1)[-1].lstrip('，。：,.: ')
    if text.startswith("我明白了"):
        text = text.split("我明白了", 1)[-1].lstrip('，。：,.: ')
    
    # 脱壳处理：提取引号内容
    match = re.search(r"""[:：]\s*['\"""'](.*?)['\"""']""", text)
    if match:
        text = match.group(1)
    else:
        text = re.sub(r"^(这段话|语音中|他说|原话).*?[:：\s]+", "", text).strip("'\"'"。， ")
    
    return text.strip()


def _execute_injection(text):
    """执行闭环注入：复制到剪贴板 + Ctrl+V + Enter"""
    try:
        import pyperclip, keyboard, time as _time
        pyperclip.copy(text)
        _time.sleep(0.15)
        keyboard.press_and_release('ctrl+v')
        _time.sleep(0.08)
        keyboard.press_and_release('enter')
        print(f"[Action] 已注入: {text[:30]}...")
    except Exception as e:
        print(f"[Action] 注入失败: {e}")


def _notify(mode, text):
    """安全地通知 UI 更新"""
    try:
        if ON_TEXT_UPDATE:
            ON_TEXT_UPDATE(mode, text)
    except Exception:
        pass
