import edge_tts
import asyncio
import pygame
import os
import tempfile

class TTSHandler:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural"):
        self.voice = voice
        # 初始化 pygame mixer 用于播放音频
        pygame.mixer.init()

    async def speak(self, text):
        if not text:
            return
            
        print(f"[TTS] 正在合成语音: {text[:20]}...")
        
        # 创建临时文件
        temp_file = os.path.join(tempfile.gettempdir(), f"tts_{os.getpid()}.mp3")
        
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(temp_file)
            
            # 播放音频
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            
            # 等待播放结束
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
                
        except Exception as e:
            print(f"[TTS] 错误: {e}")
        finally:
            # 停止播放并卸载文件，以便在下次之前删除
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def speak_sync(self, text):
        """同步包装器，方便在非异步环境调用"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        loop.run_until_complete(self.speak(text))

# 全局单例
_tts = TTSHandler()

def speak(text):
    _tts.speak_sync(text)
