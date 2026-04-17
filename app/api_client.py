"""
Core Voice Pipeline - Local STT + Cloud LLM/TTS MVP
Architecture: KWS wake / F4 hotkey -> VAD recording -> Local STT -> Cloud LLM+TTS -> Local play/inject

Stack:
  - STT: Local faster-whisper-large-v3-turbo (PRIMARY)
  - LLM: MiniMax-M2.7-highspeed (cloud via server.js)
  - TTS: Qwen3-TTS-Flash (cloud via server.js)

Target Metrics:
  - End-to-end latency < 2.5s (STT ~1s + LLM ~1s + TTS ~0.5s)
  - Chinese-English mixed recognition accuracy > 92%
"""
import os
import re
import time
import wave
import requests
from app.config import MINIMAX_API_KEY
from app.memory_manager import MemoryManager

if not MINIMAX_API_KEY:
    print("[Warning] MINIMAX_API_KEY not found, cloud LLM/TTS may fail!")

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:3000")

memory = MemoryManager()
current_scene = "office"
LAST_CONTENT_BUFFER = ""

ON_TEXT_UPDATE = None


def _notify(mode, text):
    """Safely notify UI update"""
    try:
        if ON_TEXT_UPDATE:
            ON_TEXT_UPDATE(mode, text)
    except Exception:
        pass


def _build_system_prompt(scene, raw_text=""):
    """Build complete System Prompt with memory, scene, and profile"""
    profile = memory.get_profile_prompt()
    facts = memory.get_facts_prompt()
    from app.scene import get_scene_system_prompt, get_max_length
    scene_prompt = get_scene_system_prompt(scene)
    recall = memory.get_recall_prompt(raw_text) if raw_text else ""
    max_len = get_max_length(scene)
    
    parts = [
        "You are the user's personal voice assistant, responsible for converting speech to accurate text.",
        "",
        profile,
        facts,
        scene_prompt,
        recall,
        "",
        "[Refinement Rules]",
        "- Remove verbal fillers (like 'that', 'um', 'er')",
        "- Complete omitted subjects and objects",
        "- Preserve user intent, do not add content",
        "- Keep technical terms as-is (e.g., 'MCP', 'RAG' do not explain)",
        f"- Output not exceed {max_len} characters",
        "",
        "[Output Format]",
        "Directly output refined text, no pleasantries.",
        "If user explicitly says 'send' type instruction, add [SEND] marker at end.",
    ]
    
    ctx = memory.get_rolling_context()
    if ctx:
        parts.append("")
        parts.append("[Recent Conversation Context]")
        for msg in ctx:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"  {role_label}: {msg['content'][:80]}")
    
    return "\n".join(parts)


def process_voice_pipeline(file_path):
    """
    Local STT + Cloud LLM/TTS pipeline.
    
    Flow: Audio file -> Local STT (faster-whisper) -> Cloud LLM -> Cloud TTS -> Play/Inject
    """
    global current_scene, LAST_CONTENT_BUFFER
    
    print("=" * 40)
    t_start = time.time()
    
    # ── Step 1: Local STT (faster-whisper-large-v3-turbo) ──
    try:
        _notify('sys', "Transcribing with local STT...")
        from app.stt import transcribe
        raw_text = transcribe(file_path, model_size="large-v3-turbo", language="zh")
    except Exception as e:
        print(f"[Pipeline] Local STT failed ({e})")
        return ""
    
    if not raw_text or len(raw_text.strip()) < 2:
        print("[Pipeline] No valid speech content detected")
        return ""
    
    t_stt = time.time()
    print(f"[Pipeline] Local STT done ({t_stt - t_start:.2f}s): {raw_text}")
    _notify('raw', f"[STT] {raw_text}")
    
    # ── Step 2: Scene Detection ──
    from app.scene import classify_scene
    current_scene = classify_scene(raw_text, current_scene)
    
    # ── Step 3: Cloud LLM + TTS ──
    try:
        _notify('sys', "Processing with cloud LLM...")
        
        response = requests.post(
            f"{SERVER_URL}/api/voice",
            json={"text": raw_text},
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Server error: {response.status_code}")
        
        reply_text = response.headers.get('X-Reply-Text', '')
        try:
            from urllib.parse import unquote
            reply_text = unquote(reply_text)
        except Exception:
            pass
        
        audio_content = response.content
        
    except Exception as e:
        print(f"[Pipeline] Cloud processing failed ({e}), using text only...")
        reply_text = raw_text
        audio_content = None
    
    t_cloud = time.time()
    print(f"[Pipeline] Cloud processing done ({t_cloud - t_stt:.2f}s): {reply_text}")
    
    # ── Step 4: Clean output ──
    reply_text = _clean_llm_output(reply_text)
    
    if not reply_text or len(reply_text.strip()) == 0:
        return ""
    
    # ── Step 5: Update Memory ──
    memory.append_context(raw_text, reply_text)
    memory.log_session(raw_text, reply_text, scene=current_scene, intent="input")
    
    # ── Step 6: Scene-based routing ──
    scene_cfg = memory.get_scene_config(current_scene)
    out_mode = scene_cfg.get("output_mode", "text_inject")
    
    _notify('final', reply_text)
    
    if current_scene == "office":
        if "[SEND]" not in reply_text:
            _execute_injection(reply_text)
    
    elif current_scene == "running":
        if audio_content:
            _play_audio_response(audio_content)
        if "[SEND]" not in reply_text:
            _execute_injection(reply_text)
    
    elif current_scene == "driving":
        if audio_content:
            _play_audio_response(audio_content)
    
    t_total = time.time() - t_start
    print(f"[Pipeline] Total time: {t_total:.2f}s (target <2.5s)")
    
    return reply_text.replace("[SEND]", "").strip()


def _clean_llm_output(text):
    """Clean redundant prefixes from LLM output"""
    if not text:
        return ""
    
    if text.startswith("好的"):
        text = text.split("好的", 1)[-1].lstrip(',.。：,: ')
    if text.startswith("我明白了"):
        text = text.split("我明白了", 1)[-1].lstrip(',.。：,: ')
    
    match = re.search(r"""[:：]\s*['"](.*?)['"]""", text)
    if match:
        text = match.group(1)
    
    return text.strip()


def _execute_injection(text):
    """Execute closed-loop injection: copy to clipboard + Ctrl+V + Enter"""
    try:
        import pyperclip
        import keyboard
        import time as _time
        pyperclip.copy(text)
        _time.sleep(0.15)
        keyboard.press_and_release('ctrl+v')
        _time.sleep(0.08)
        keyboard.press_and_release('enter')
        print(f"[Action] Injected: {text[:30]}...")
    except Exception as e:
        print(f"[Action] Injection failed: {e}")


def _play_audio_response(audio_bytes):
    """Play TTS audio returned from cloud"""
    try:
        import pygame
        import tempfile
        import os
        
        temp_file = os.path.join(tempfile.gettempdir(), f"tts_response_{os.getpid()}.mp3")
        
        with open(temp_file, 'wb') as f:
            f.write(audio_bytes)
        
        pygame.mixer.init()
        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        
        os.remove(temp_file)
    except Exception as e:
        print(f"[TTS] Playback failed: {e}")