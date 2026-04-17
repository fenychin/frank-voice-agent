"""
记忆管理器 — JSON 短期 + Chroma 长期
对齐 PDR §4: session_log 即时追加 + facts 定期提炼 + Chroma 向量检索
"""
import os
import json
import time
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")

# 默认记忆结构（对齐 PDR §4.1）
DEFAULT_MEMORY = {
    "user_profile": {
        "name": "Frank",
        "occupation": "",
        "language_preference": "中文为主，专有名词带英文",
        "common_terms": ["OpenClaw", "MCP", "RAG", "PyQt6"],
        "disliked_phrases": [],
        "output_style": "极为简洁，没有任何啰嗦的礼貌用语"
    },
    "scene_configs": {
        "office": {
            "output_mode": "text_inject",
            "formality": "professional",
            "max_length": 500
        },
        "running": {
            "output_mode": "tts_response",
            "response_length": "short",
            "max_length": 80
        },
        "driving": {
            "output_mode": "tts_only",
            "response_length": "minimal",
            "max_length": 40
        }
    },
    "session_log": [],
    "facts": [],
    "rolling_context": []   # 最近 3 轮对话上下文
}


class MemoryManager:
    def __init__(self):
        self.data = self._load()
        self.chroma = self._init_chroma()
    
    def _load(self):
        """加载 JSON 记忆文件，不存在则创建默认结构"""
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 合并缺失的字段（向前兼容）
                for key, default_val in DEFAULT_MEMORY.items():
                    if key not in data:
                        data[key] = default_val
                return data
            except Exception as e:
                print(f"[Memory] 加载记忆文件失败: {e}")
        return DEFAULT_MEMORY.copy()
    
    def _save(self):
        """持久化到磁盘"""
        try:
            with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Memory] 保存失败: {e}")
    
    def _init_chroma(self):
        """初始化 Chroma 向量记忆（可选）"""
        try:
            import chromadb
            db_path = os.path.join(os.path.dirname(__file__), '..', 'memory_db')
            client = chromadb.PersistentClient(path=db_path)
            collection = client.get_or_create_collection(
                "conversations",
                metadata={"hnsw:space": "cosine"}
            )
            print(f"[Memory] Chroma 向量库就绪 (已有 {collection.count()} 条记忆)")
            return collection
        except ImportError:
            print("[Memory] chromadb 未安装，仅使用 JSON 记忆")
            return None
        except Exception as e:
            print(f"[Memory] Chroma 初始化失败: {e}")
            return None
    
    # ── 用户档案 ──
    
    def get_profile(self):
        return self.data.get("user_profile", {})
    
    def get_profile_prompt(self):
        """生成注入 LLM 的用户档案 Prompt 段"""
        p = self.get_profile()
        terms = ", ".join(p.get("common_terms", []))
        style = p.get("output_style", "")
        name = p.get("name", "用户")
        parts = [f"[用户档案] 姓名: {name}"]
        if terms:
            parts.append(f"常用专有名词: {terms}")
        if style:
            parts.append(f"输出风格要求: {style}")
        return "\n".join(parts)
    
    # ── 滚动上下文（3 轮）──
    
    def get_rolling_context(self):
        """返回最近 3 轮对话，格式为 LLM messages"""
        return self.data.get("rolling_context", [])[-6:]  # 3轮 = 6条消息
    
    def append_context(self, user_text, assistant_text):
        """追加一轮对话到滚动上下文"""
        ctx = self.data.setdefault("rolling_context", [])
        ctx.append({"role": "user", "content": user_text})
        ctx.append({"role": "assistant", "content": assistant_text})
        # 保留最近 3 轮（6 条消息）
        if len(ctx) > 6:
            self.data["rolling_context"] = ctx[-6:]
        self._save()
    
    # ── Session Log ──
    
    def log_session(self, raw_text, output_text, scene="office", intent="input"):
        """记录一次会话到 session_log"""
        entry = {
            "ts": datetime.now().isoformat(),
            "scene": scene,
            "raw": raw_text,
            "output": output_text,
            "intent": intent
        }
        log = self.data.setdefault("session_log", [])
        log.append(entry)
        # 保留最近 50 条
        if len(log) > 50:
            self.data["session_log"] = log[-50:]
        self._save()
        
        # 同时写入 Chroma（如果可用）
        if self.chroma:
            try:
                self.chroma.add(
                    documents=[f"用户说: {raw_text}\n精炼: {output_text}"],
                    metadatas=[{"scene": scene, "intent": intent, "ts": entry["ts"]}],
                    ids=[f"session_{int(time.time()*1000)}"]
                )
            except Exception as e:
                print(f"[Memory] Chroma 写入失败: {e}")
    
    # ── 相关记忆检索 ──
    
    def recall(self, query, n=3):
        """从 Chroma 中检索与当前查询最相关的历史记忆"""
        if not self.chroma or self.chroma.count() == 0:
            return []
        try:
            results = self.chroma.query(query_texts=[query], n_results=min(n, self.chroma.count()))
            docs = results.get("documents", [[]])[0]
            return docs
        except Exception:
            return []
    
    def get_recall_prompt(self, query):
        """生成相关记忆的 Prompt 注入段"""
        memories = self.recall(query)
        if not memories:
            return ""
        lines = ["[相关历史记忆]"]
        for i, m in enumerate(memories, 1):
            lines.append(f"  {i}. {m[:100]}")
        return "\n".join(lines)
    
    # ── Facts ──
    
    def get_facts_prompt(self):
        """将已知 facts 注入 Prompt"""
        facts = self.data.get("facts", [])
        if not facts:
            return ""
        lines = ["[已知用户偏好]"]
        for f in facts[-10:]:
            lines.append(f"  - {f.get('key', '')}: {f.get('value', '')}")
        return "\n".join(lines)
    
    def get_scene_config(self, scene_name):
        """获取场景配置"""
        configs = self.data.get("scene_configs", {})
        return configs.get(scene_name, configs.get("office", {}))
