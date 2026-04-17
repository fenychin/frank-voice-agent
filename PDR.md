# 个人化语音 AI Agent — 产品设计需求文档（PDR）

**版本：** v1.0  
**日期：** 2026-04-17  
**定位：** 桌面端悬浮语音 Agent，替代键盘输入 → 记忆系统 → 语音 OpenClaw  

***

## 一、产品愿景与核心诉求

### 1.1 问题本质（第一性原理拆解）

人类自然表达的本质是**语音+语境**，键盘输入是一种妥协——它强迫用户把语言流压缩成线性字符，丢失语气、节奏、模糊性。现有语音助手的失败根源不是技术，而是**设计哲学错误**：它们是面向所有人的，因此对任何一个人都是陌生人，缺乏跨会话记忆、个性理解和场景感知。

真正的需求拆分为三个层次：

| 层级 | 核心诉求 | 现有产品缺失点 |
|------|----------|----------------|
| **L1 输入替代** | 口语 → 整理后的准确文字，零摩擦 | Siri 只能转录，不整理语义 |
| **L2 语境理解** | 知道我是谁、我在哪、我在做什么 | 无跨会话记忆，无场景感知 |
| **L3 个性陪伴** | 情感式回应，像伙伴不像工具 | 通用化人格，无法个性化塑造 |

MVP 聚焦 **L1 + L2 的最小闭环**：以「替代打字」为唯一北极星目标。

### 1.2 成功标准（MVP）

- 戴上耳机，说一句话，在任意输入框得到经过整理的文字，**全程不碰键盘**
- 端到端感知延迟 **< 2 秒**（唤醒词触发 → 文字出现）
- 识别准确率（中英混合口语）**> 92%**
- 支持场景切换：办公（精确输出）/ 跑步（语音回读）/ 开车（简短回应）

***

## 二、三阶段路线图

```
Phase 1 (MVP)：桌面悬浮语音输入替代              ← 当前文档重点
  ├─ 热词唤醒
  ├─ 流式 STT
  ├─ LLM 口语整理 + 场景适配
  ├─ 文字注入 / TTS 回读
  └─ 最小 JSON 记忆文件

Phase 2：持久化记忆系统
  ├─ Chroma 向量长期记忆
  ├─ 自动记忆提炼（后台 LLM 任务）
  └─ 跨会话偏好感知

Phase 3：Agent 能力（语音 OpenClaw）
  ├─ 工具调用（搜索、日历、文件）
  ├─ 多步推理任务执行
  └─ MCP 协议接入
```

***

## 三、Phase 1 技术架构（详细）

### 3.1 整体架构图（文字版）

```
┌─────────────────────────────────────────────────────────────────┐
│                    PC 桌面悬浮窗（System Tray / Overlay）         │
│   [●录音状态指示] [场景切换按钮] [最近记忆预览]                    │
└────────────────────┬────────────────────────────────────────────┘
                     │ 热键 / 热词唤醒
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│  VAD（端点检测）  ←→  麦克风音频流 16kHz mono PCM                │
│  Silero-VAD / WebRTC VAD（本地，< 5ms）                         │
└────────────────────┬────────────────────────────────────────────┘
                     ↓ 确认说话结束
┌─────────────────────────────────────────────────────────────────┐
│  STT 层：流式语音转文字                                           │
│  主力：Gemini 2.5 Flash STT（Google AI Studio API）              │
│  降级：Whisper-large-v3-turbo（本地，llama.cpp whisper）         │
│  输出：原始口语文本 + 置信度                                      │
└────────────────────┬────────────────────────────────────────────┘
                     ↓ 原始口语文本
┌─────────────────────────────────────────────────────────────────┐
│  LLM 整理层（核心）                                               │
│  模型 A：Gemma 4 26B-A4B（本地 MoE，4B 激活参数，低延迟）        │
│  模型 B：Qwen3-235B-A22B via Ollama（高质量，联网推理）           │
│  模型 C：Qwen3.5-9B（轻量本地，CPU 可跑）                        │
│                                                                  │
│  任务：                                                           │
│  1. 口语 → 书面化整理（去语气词、补主语、纠语序）                  │
│  2. 场景适配（办公/跑步/开车 → 不同输出格式）                     │
│  3. 情感意图理解（区分抱怨/指令/闲聊）                            │
│  4. 注入短期对话记忆（Rolling 10轮）+ JSON 记忆文件检索            │
└────────────────────┬────────────────────────────────────────────┘
                     ↓ 整理后文本 / 回应文本
┌──────────────┬──────────────────────────────────────────────────┐
│  输出路径 A  │  文字注入活跃输入框                                 │
│  （办公场景）│  方案：pyperclip 复制 + xdotool/pyautogui 粘贴     │
│              │  效果：Ctrl+V 级别原生输入，兼容所有文本框          │
├──────────────┼──────────────────────────────────────────────────┤
│  输出路径 B  │  TTS 语音回读                                       │
│  （跑步/驾车）│ 方案：Qwen3-TTS（本地）/ Gemini 3.1 Flash TTS     │
│              │  Qwen3-TTS 首包延迟 150ms，RTF 0.25（1.7B模型）    │
└──────────────┴──────────────────────────────────────────────────┘
```

### 3.2 唤醒机制设计

**双轨并行**，优先热键，辅以热词：

| 方案 | 技术实现 | 延迟 | 隐私 | 推荐场景 |
|------|----------|------|------|----------|
| **全局热键**（主推） | `keyboard` 库监听，如 `Alt+Space` | < 10ms | 完全本地 | 办公、坐姿使用 |
| **热词唤醒** | Picovoice Porcupine（自定义热词） | < 50ms | 本地推理，不上云 | 跑步、驾车、双手占用 |
| **Push-to-talk** | 长按耳机按键 | < 10ms | 本地 | 快速插话场景 |

Porcupine 支持在设备端训练自定义唤醒词（如「Hey Alex」），不发送任何音频到云端直到触发，CPU 占用 < 1%。

### 3.3 STT 选型细节

**推荐主力方案：Gemini 2.5 Flash STT（API）**

- 流式输出，中英混合口语准确率业界最高
- 支持 PCM/Opus 音频流输入
- 成本极低（Flash 级别）

**本地降级方案：Whisper-large-v3-turbo（whisper.cpp）**

- 完全离线，适合无网络环境
- RTX 3060 12G：~8B tokens/s，约 1.2s 处理 10s 音频
- 中文准确率高，支持词级时间戳

**不推荐 Deepgram 作为主力**（对比 Gemini Flash）：Deepgram 在中文场景的准确率落后，且成本更高。

### 3.4 LLM 整理层：Prompt 工程设计

MVP System Prompt 骨架：

```
你是用户的个人语音助手，负责将口语转化为准确文字。

【用户基础信息】
${从 JSON 记忆文件读取：姓名/职业/常用词汇/偏好}

【当前场景】: ${办公 | 跑步 | 开车 | 自由}

【整理规则】
- 去除口语填充词（"那个"、"就是"、"嗯"）
- 补全省略主语和宾语
- 保留用户原意，不添加内容
- 专业术语保持原样（如 "MCP"、"RAG" 不解释）

【输出格式】
场景=办公：输出整理后文字，不解释
场景=跑步：输出文字+30字以内语音回应
场景=开车：只输出简短语音回应，不粘贴文字

【当前对话记忆（最近10轮）】
${rolling_context}
```

### 3.5 LLM 本地推理性能基准

| 模型 | 量化 | VRAM 需求 | 推理速度（RTX 4060） | 推理速度（RTX 4090） | 适用场景 |
|------|------|-----------|----------------------|----------------------|----------|
| **Gemma 4 26B-A4B** | Q4_K_M | ~12GB | ~18 tok/s | ~45 tok/s | 主力，MoE 低延迟 |
| **Qwen3-235B-A22B** | Q4_K_M | ~28GB（A22B 激活） | ~8 tok/s | ~22 tok/s | 高质量，双卡或高端单卡 |
| **Qwen3.5-9B** | Q4_K_M | ~6GB | ~35 tok/s | ~85 tok/s | CPU/低显存设备降级 |
| **Gemma 4 31B** | Q4_K_M | ~20GB | ~12 tok/s | ~30 tok/s | 最高质量本地单模型 |

Gemma 4 26B-A4B 的 MoE 设计：总参数 26B，但每次推理仅激活 4B 参数，速度接近 4B 模型而质量接近 26B 模型。

### 3.6 TTS 选型细节

**主推：Qwen3-TTS 1.7B（本地）**

- 首包延迟：150ms（12Hz tokenizer）
- RTF（实时因子）：0.25（即生成速度是播放速度的 4 倍）
- 支持情感化语音、中英混合
- 要求：FlashAttention 2，否则 RTF 骤降到 0.3x
- 开源协议：Apache 2.0

**云端升级：Gemini 3.1 Flash TTS**

- 支持精细化 audio tags 控制语气（激动、平静、强调）
- 流式 PCM 输出，首包延迟更低
- 适合 Phase 2 陪伴型回应场景

**不使用 ElevenLabs 作为 MVP**：成本过高，且本地 Qwen3-TTS 已满足需求。

### 3.7 文字注入方案

```
方案一（推荐）：pyperclip + pyautogui
  1. LLM 输出整理后文本
  2. pyperclip.copy(text)
  3. pyautogui.hotkey('ctrl', 'v')  # Windows/Linux
  4. pyperclip.copy('')  # 清空剪贴板

方案二（高级）：xdotool type（Linux）
  os.system(f'xdotool type --clearmodifiers "{text}"')
  # 支持 Unicode，不依赖剪贴板

方案三（Windows 专用）：Win32 SendMessage
  # 直接发送 WM_SETTEXT，无剪贴板污染
```

注意事项：密码框检测（title/class 黑名单），不注入敏感输入框。

***

## 四、Phase 1 记忆系统（最小 JSON 方案）

MVP 阶段使用轻量 JSON 文件记忆，Phase 2 再升级到 Chroma 向量库。

### 4.1 JSON 记忆文件结构

```json
{
  "user_profile": {
    "name": "用户姓名",
    "occupation": "职业",
    "language_preference": "中英混合",
    "common_terms": ["MCP", "RAG", "OpenClaw"],
    "disliked_phrases": ["我认为", "首先"],
    "output_style": "简洁直接，不废话"
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
  "session_log": [
    {
      "ts": "2026-04-17T10:23:00",
      "scene": "office",
      "raw": "那个帮我把那个会议记录整理一下发给老板",
      "output": "请将会议记录整理后发送给负责人",
      "intent": "task"
    }
  ],
  "facts": [
    {"key": "常用邮件签名", "value": "Best regards, Alex", "updated": "2026-04-10"},
    {"key": "不喜欢早会", "value": true, "updated": "2026-04-12"}
  ]
}
```

### 4.2 记忆更新触发逻辑

- **即时更新**：每次会话后追加 `session_log`（保留最近 50 条）
- **定期提炼**：每 10 次会话后，用后台 LLM 任务扫描 `session_log`，提炼新 facts 写入 `facts` 数组
- **手动编辑**：悬浮窗提供「记忆面板」，用户可直接查看/修改

***

## 五、Phase 2：持久化记忆系统（设计预览）

### 5.1 Chroma 向量记忆架构

Phase 2 将 JSON facts 升级为向量检索，实现语义级相关记忆注入。

```python
import chromadb
from chromadb.utils import embedding_functions

# 本地持久化
client = chromadb.PersistentClient(path="./memory_db")

# 三个 Collection
conversations = client.get_or_create_collection("conversations")  # 历史对话摘要
facts         = client.get_or_create_collection("user_facts")     # 提炼出的事实
preferences   = client.get_or_create_collection("preferences")    # 偏好与习惯

# 每次对话前：RAG 检索相关记忆
def recall_relevant(query: str, n=5) -> list[str]:
    results = conversations.query(query_texts=[query], n_results=n)
    return results["documents"][0]

# 每次对话后：异步存储摘要
def store_session(summary: str, metadata: dict):
    conversations.add(
        documents=[summary],
        metadatas=[metadata],
        ids=[f"session_{metadata['ts']}"]
    )
```

### 5.2 记忆分层设计

| 层级 | 存储形式 | 容量 | 检索方式 | 更新频率 |
|------|----------|------|----------|----------|
| **工作记忆** | Context Window | 10轮对话 | 直接注入 | 每轮实时 |
| **情节记忆** | Chroma（对话摘要） | 无限 | 向量语义检索 | 每次会话后 |
| **语义记忆** | Chroma（提炼事实） | 无限 | 关键词+向量 | 每周 LLM 提炼 |
| **用户档案** | JSON（结构化） | 固定字段 | 全量注入 | 手动 + 自动触发 |

### 5.3 自动记忆提炼 Prompt

```
分析以下对话记录，提炼出关于用户的新事实（不超过5条）。
只记录客观事实，不记录情绪和猜测。
格式：JSON 数组 [{"key": "...", "value": "..."}]

对话记录：
${last_10_sessions_summary}
```

***

## 六、Phase 3：Agent 能力（语音 OpenClaw，设计预览）

### 6.1 工具调用架构

基于 MCP（Model Context Protocol）构建工具层，LLM 通过函数调用触发：

```
用户语音指令
    ↓ STT + LLM 意图识别
意图分类：
  ├── 输入替代  → Phase 1 流程
  ├── 信息查询  → 搜索工具（Brave Search API）
  ├── 任务执行  → 文件/日历/邮件 工具
  └── 深度推理  → 多步 CoT + 工具链
```

### 6.2 核心工具列表（Phase 3 目标）

| 工具 | 功能 | 实现方案 |
|------|------|----------|
| `web_search` | 实时搜索 | Brave Search API / Serper |
| `file_read_write` | 读写本地文件 | Python `pathlib` |
| `calendar_access` | 日历查询/创建 | Google Calendar API |
| `clipboard_inject` | 文字注入 | Phase 1 已实现 |
| `app_control` | 打开/控制应用 | pyautogui + subprocess |
| `memory_retrieve` | 检索长期记忆 | Chroma RAG |
| `memory_store` | 存储新记忆 | Chroma + JSON |
| `translation` | 实时翻译 | LLM 内置 / DeepL API |

### 6.3 「翻译给倾听者」功能设计

用户说中文 → Agent 实时翻译为英文语音输出（给外国人听）：

```
用户中文语音
    ↓ STT（中文）
    ↓ LLM 翻译 + 语气保留
    ↓ TTS（英文，Qwen3-TTS 支持多语言）
    → 耳机/扬声器输出给倾听者
```

延迟估算：STT 800ms + LLM 翻译 500ms + TTS 150ms ≈ **1.5 秒总延迟**，接近实时口译体验。

***

## 七、桌面悬浮窗 UI 设计规范

### 7.1 技术方案选型

| 方案 | 框架 | 优势 | 劣势 |
|------|------|------|------|
| **推荐：PyQt6 / PySide6** | Python | 原生窗口，透明悬浮，全平台 | 需要学习 Qt |
| Electron | Node.js/HTML | 开发快，WebUI 灵活 | 内存占用高（200MB+） |
| Tauri | Rust+WebView | 极轻（<10MB），高性能 | 需要 Rust，开发复杂 |
| **轻量替代：Tkinter + pywin32** | Python | 零依赖 | 样式难看，动画差 |

**推荐 PyQt6**：与 Python AI 栈无缝集成，支持真透明悬浮窗，系统托盘图标，全局热键监听。

### 7.2 UI 状态机

```
待机（System Tray 图标）
    ↓ Alt+Space / 热词触发
聆听中（悬浮窗展开，麦克风波形动画，红色录音指示）
    ↓ VAD 检测说话结束
处理中（旋转加载动画，显示「理解中...」）
    ↓ LLM 输出完成
输出完成（绿色确认，显示整理后文字 2秒）
    ↓ 自动收起 / 等待下一次唤醒
错误状态（红色提示，显示错误类型）
```

### 7.3 悬浮窗视觉规格

- **尺寸**：收起态 40×40px 半透明圆角图标；展开态 360×80px 底部悬浮条
- **位置**：屏幕底部中央，不遮挡任务栏
- **透明度**：90% 不透明度，blur 背景
- **颜色状态**：待机蓝 → 聆听红 → 处理橙 → 完成绿
- **字体显示**：展开态显示最近一条整理后文字（truncated 50字）

***

## 八、开发实施路径

### 8.1 技术栈最终确认

```
核心运行时：    Python 3.12
LLM 推理：      Ollama（管理本地模型）+ Google Gemini API（STT/TTS）
STT：           google.generativeai（Gemini 2.5 Flash）/ faster-whisper（本地降级）
VAD：           silero-vad（PyTorch，< 5ms）
LLM：           ollama（Gemma 4 26B-A4B 主力）/ gemini-flash（云端高速通道）
TTS：           Qwen3-TTS（本地，FlashAttention 2 必装）
记忆：          JSON 文件（Phase 1）→ chromadb（Phase 2）
UI：            PyQt6（悬浮窗）+ pystray（系统托盘）
热键：          keyboard 库（全局热键监听）
热词：          pvporcupine（Picovoice，自定义热词）
文字注入：      pyperclip + pyautogui
音频：          sounddevice + numpy（PCM 音频流）
```

### 8.2 Phase 1 开发里程碑

| 里程碑 | 内容 | 预估工时 |
|--------|------|----------|
| **M1** | 音频采集 + VAD + Whisper STT 跑通 | 1 天 |
| **M2** | Ollama Gemma 4 本地推理 + 口语整理 Prompt | 1 天 |
| **M3** | 文字注入（pyperclip）+ 基础悬浮窗（PyQt6） | 1.5 天 |
| **M4** | Qwen3-TTS 本地 TTS 回读集成 | 1 天 |
| **M5** | 热词唤醒（Porcupine）+ 场景切换逻辑 | 1 天 |
| **M6** | JSON 记忆文件 + 用户档案注入 | 0.5 天 |
| **M7** | 端到端联调，延迟优化，UI 打磨 | 1.5 天 |
| **总计** | **完整 MVP** | **~7.5 天** |

### 8.3 硬件最低配置建议

| 配置等级 | 硬件 | 可运行模型 | 预期延迟 |
|----------|------|------------|----------|
| **最低** | CPU only, 16GB RAM | Qwen3.5-9B Q4，本地 Whisper-small | 4-6s |
| **推荐** | RTX 3060 12GB | Gemma 4 26B-A4B Q4，Whisper-large | 1.5-2.5s |
| **理想** | RTX 4090 24GB | Qwen3-235B-A22B Q4，全本地 | < 1.5s |
| **极简云端** | 任意 CPU + 网络 | Gemini Flash API（STT+LLM+TTS 全云） | 1.5-2s |

***

## 九、风险与缓解策略

| 风险 | 可能性 | 影响 | 缓解方案 |
|------|--------|------|----------|
| Qwen3-TTS 无 FlashAttention 2 导致极慢 | 高 | 高 | 安装指引前置；降级到 Gemini TTS API |
| 文字注入到错误窗口（如密码框） | 中 | 中 | 窗口类型黑名单检测；注入前显示预览确认 |
| Gemini API 限流/网络中断 | 中 | 中 | 本地 Whisper 自动降级；离线模式标识 |
| 热词误触发率过高 | 中 | 低 | 调高 Porcupine 灵敏度阈值；引入 500ms 确认窗口 |
| 长时间运行内存泄漏 | 低 | 中 | Rolling 上下文限制 + 定期 GC |

***

## 十、Phase 2 & 3 关键技术预研结论

### Chroma 向量记忆可行性

Chroma 支持本地持久化（`PersistentClient`），嵌入式运行无需独立服务，适合个人桌面 Agent。向量检索延迟 < 10ms（百万条以内），完全满足实时注入需求。

### Qwen3-235B-A22B 本地推理可行性

通过 Ollama v0.12.7+ 可在本地运行 Qwen3-235B-A22B（MoE，22B 激活参数）。以 Q4 量化，双卡 RTX 4090（48GB 合并显存）可达约 15-22 tok/s，单卡 4090 需要量化到 Q3 或使用 CPU offload。对于 Phase 3 复杂 Agent 推理，该模型质量超过 DeepSeek-R1。

### MCP 协议集成

Phase 3 优先接入 MCP（Model Context Protocol）工具层，使 LLM 能直接调用结构化工具，避免 function calling prompt 维护成本。LiveKit Agents 框架已原生支持 MCP。

***

*文档版本 v1.0 | 下次更新：Phase 1 MVP 完成后进行 v1.1 修订*
