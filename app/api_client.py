import os
import json
import requests
from app.config import DASHSCOPE_API_KEY
import dashscope

if not DASHSCOPE_API_KEY:
    print("[Warning] 未获取到 DASHSCOPE_API_KEY，阿里云接口调用可能会失败！")

# 全局暂存区：存放上一次精炼好但还没发出的内容
LAST_CONTENT_BUFFER = ""

def process_voice_pipeline(file_path):
    print("=" * 30)
    print(f"[API] 正在将录音 {file_path} 直接投递给通义千问 Audio 多模混合底座...")
    
    dashscope.api_key = DASHSCOPE_API_KEY
    
    try:
        # 直接使用大模型多模态能力，极其稳定。并且原生提供对 file:// 本机的临时 OSS 上传缓冲！
        import json
        memory_str = ""
        try:
            memory_file = os.path.join(os.path.dirname(__file__), 'memory.json')
            if os.path.exists(memory_file):
                with open(memory_file, 'r', encoding='utf-8') as f:
                     memory_data = json.load(f)
                     profile = memory_data.get('user_profile', {})
                     terms = ", ".join(profile.get('common_terms', []))
                     style = profile.get('output_style', '')
                     memory_str = f"【用户专属设定】常用拼写专有名词参考：{terms}。\n【期望风格】：{style}\n"
        except Exception:
            pass
            
        messages = [
            {
                "role": "user",
                "content": [
                    {"audio": f"file://{os.path.abspath(file_path)}"},
                    {"text": f"{memory_str}任务：你是用户的思想精炼器。将用户零散、不流畅、口语化的语音实时整理为逻辑严密、用词专业的书面表达。\n禁令：严禁输出'好的'、'收到'、'明白了'等任何礼貌用语或语气词！直接输出精炼后的正文。如果识别内容包含'发送'，并在末尾加上 [SEND] 标记。"}
                ]
            }
        ]
        
        try:
            if globals().get('ON_TEXT_UPDATE'):
                 ON_TEXT_UPDATE('sys', "💫 已经抓取话音，智能大模型正在深思精修中......\n这通常需要 1~3 秒")
        except BaseException: pass
        
        response = dashscope.MultiModalConversation.call(
            model='qwen-audio-turbo',
            messages=messages
        )
        
        if response.status_code == 200:
             content_list = response.output.choices[0].message.content
             final_text = "".join([item.get('text', '') for item in content_list if 'text' in item])
             
             # 给 UI 第一个带壳的毛坯成果视觉冲击（极速反馈）
             if globals().get('ON_TEXT_UPDATE'):
                  ON_TEXT_UPDATE('raw', f"【已抓取话音，校对精炼中】：\n{final_text}")
             
             # 再次清洗掉可能遗留的大模型废话
             import re
             if final_text.startswith("好的"):
                 final_text = final_text.split("好的", 1)[-1].lstrip('，。：,.: ')
                 if final_text.startswith("我明白了"):
                      final_text = final_text.split("我明白了", 1)[-1].lstrip('，。：,.: ')

             # 终极剥壳刀：针对大模型顽固的 "语音中说的是: '我就是觉得吧'" 进行脱水
             match = re.search(r"[:：]\s*['\"‘“](.*?)['\"’”]", final_text)
             if match:
                 final_text = match.group(1)
             else:
                 # 粗暴消解前缀
                 final_text = re.sub(r"^(这段话|语音中|他说|原话).*?[:：\s]+", "", final_text).strip("'\"‘“。， ")

             if final_text and len(final_text.strip()) > 0:
                 print(f"[OK] 智能脑提取整理完毕: {final_text}")
                 
                 global LAST_CONTENT_BUFFER
                 
                 # 核心意图判断（大幅扩大关键词感应范围）
                 text_norm = final_text.strip().replace("。", "").replace("！", "").replace(".", "")
                 trigger_words = ["发送", "发出去", "完成", "OK", "确定", "OK。", "发送。"]
                 
                 is_pure_send = text_norm in trigger_words
                 contains_send_flag = "[SEND]" in final_text or any(w in final_text for w in ["说发送", "执行发送"])
                 
                 should_trigger_injection = is_pure_send or contains_send_flag
                 
                 # 准备正文
                 if is_pure_send:
                      payload_text = LAST_CONTENT_BUFFER
                      if not payload_text:
                           payload_text = "（没找到刚才的内容，请重新说一遍）"
                 else:
                      payload_text = final_text.replace("[SEND]", "").strip()
                      # 如果不是纯指令，则更新缓存，供后续指令使用
                      LAST_CONTENT_BUFFER = payload_text

                 # 在 UI 上展示最终定型的精炼文字
                 if globals().get('ON_TEXT_UPDATE'):
                      label_msg = "确认发送中..." if should_trigger_injection else "已智能为您精炼"
                      ON_TEXT_UPDATE('final', payload_text)
                 
                 if should_trigger_injection and payload_text and payload_text != "（没找到刚才的内容，请重新说一遍）":
                      # 执行闭环注入
                      import pyperclip, keyboard, time
                      pyperclip.copy(payload_text)
                      keyboard.release('alt')
                      keyboard.release('space')
                      time.sleep(0.2) 
                      keyboard.press_and_release('ctrl+v')
                      time.sleep(0.1)
                      keyboard.press_and_release('enter')
                      print(f"[Action] -> 已执行注入：{payload_text}")
                      # 发送完后清理缓存
                      LAST_CONTENT_BUFFER = ""
                 
                 return payload_text
             else:
                 print("[!] 无效语音或背景噪音。")
                 return ""
        else:
             print(f"[ERROR] 阿里接口错误: HTTP {response.status_code}")
             return ""
             
    except Exception as e:
        print(f"[ERROR] 底层调用发生根本性阻断: {e}")
        return None
