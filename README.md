# Frank Voice Agent 🚀

基于阿里云 DashScope Qwen-Audio 与 Sherpa-ONNX 的闭环式语音 AI 助手。

## 🌟 核心特性
- **本地语音唤醒**：集成 `sherpa-onnx` 工业级唤醒引擎，支持自定义唤醒词（默认：小V）。
- **智能意图精炼**：不仅仅是语音转文字，更能自动优化口语词、纠正逻辑、提炼精准表达。
- **闭环交互**：支持通过语音指令（如“发送”）自动同步至剪贴板并在当前窗口执行粘贴发送。
- **Apple 磨砂 UI**：精致的半透明磨砂面板，多态呼吸灯实时反馈。
- **环境自适应降噪**：启动时自动校准底噪，支持 300Hz-3400Hz 带通滤波增强人声。

## 🛠️ 快速启动
1. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```
2. **配置环境**：
   复制 `.env.example` 为 `.env` 并填写您的 `DASHSCOPE_API_KEY`。
3. **运行**：
   ```bash
   python app/main.py
   ```

## ⌨️ 快捷操作
- **语音唤醒**：大声说“小V”或“小爱同学”。
- **热键激活**：按下 `F4` 键。
- **发送指令**：在识别完成后说“发送”或“OK”。

## 📦 项目结构
- `app/main.py`: 核心启动逻辑。
- `app/kws_handler.py`: 本地语音唤醒管理。
- `app/api_client.py`: 阿里云大模型交互逻辑。
- `app/audio_handler.py`: 后台录音、降噪与自适应校准。
- `app/ui_tray.py`: PyQt6 磨砂视觉组件。