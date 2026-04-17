"""
TTS Handler - Cloud-First MVP Edition
Primary: Qwen3-TTS-Flash via DashScope
Fallback: Edge-TTS (zh-CN-XiaoxiaoNeural)
"""
import os
import asyncio
import tempfile
import requests
import edge_tts
import pygame

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:3000")


class TTSHandler:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural"):
        self.voice = voice
        pygame.mixer.init()
    
    async def speak(self, text):
        if not text:
            return
            
        print(f"[TTS] Synthesizing: {text[:20]}...")
        
        temp_file = os.path.join(tempfile.gettempdir(), f"tts_{os.getpid()}.mp3")
        
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(temp_file)
            
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
                
        except Exception as e:
            print(f"[TTS] Error: {e}")
        finally:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def speak_sync(self, text):
        """Sync wrapper for non-async contexts"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        loop.run_until_complete(self.speak(text))


async def speak_qwen_cloud(text):
    """Call Qwen3.5-Flash TTS via cloud server"""
    if not text:
        return
        
    try:
        response = requests.post(
            f"{SERVER_URL}/api/tts",
            json={"text": text},
            timeout=15
        )
        
        if response.status_code == 200:
            temp_file = os.path.join(tempfile.gettempdir(), f"tts_cloud_{os.getpid()}.mp3")
            
            with open(temp_file, 'wb') as f:
                f.write(response.content)
            
            pygame.mixer.init()
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
            
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            os.remove(temp_file)
        else:
            print(f"[TTS] Cloud TTS failed: {response.status_code}")
            raise Exception("Cloud TTS unavailable")
            
    except Exception as e:
        print(f"[TTS] Falling back to Edge-TTS: {e}")
        await speak_edge_local(text)


async def speak_edge_local(text):
    """Fallback: Edge-TTS local synthesis"""
    if not text:
        return
        
    temp_file = os.path.join(tempfile.gettempdir(), f"tts_edge_{os.getpid()}.mp3")
    
    try:
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await communicate.save(temp_file)
        
        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass


def speak(text):
    """Public API: Try cloud TTS first, fallback to Edge-TTS"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(speak_qwen_cloud(text))
    except Exception as e:
        print(f"[TTS] All TTS failed: {e}")