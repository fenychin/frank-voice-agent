import sys
import os
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QTextEdit
from PyQt6.QtGui import QColor, QFont, QTextCursor
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer

class FloatingOverlay(QWidget):
    # 发送状态切换信号：'listening', 'processing', 'success', 'error'
    status_signal = pyqtSignal(str, str)
    # text_signal: 用于展示大模型流式或最终精炼的文字
    text_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        
        # 让窗口悬浮置顶且无边框，不在任务栏显示，而且坚决不能抢夺焦点！否则会断掉打字注入！
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        
        # 增加整体尺寸以容纳下方的大框 (更扁长一些，符合 Apple 通知风格)
        self.setFixedSize(500, 180)
        
        # 居中在屏幕底部
        screen_geo = QApplication.primaryScreen().geometry()
        x = (screen_geo.width() - self.width()) // 2
        y = screen_geo.height() - self.height() - 80 
        self.move(x, y)
        
        # 背景完全透明由 QSS 控制毛玻璃效果
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 主内容容器（用于圆角阴影渲染）
        self.container = QWidget(self)
        self.container.setFixedSize(self.size())
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.container)

        # 内部布局
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(25, 20, 25, 20)
        self.layout.setSpacing(5)
        
        # 顶部：核心状态栏文字提示 (和原来一样)
        self.label = QLabel("Frank Voice Agent 随时待命", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(QFont("微软雅黑", 11, QFont.Weight.Bold))
        self.label.setStyleSheet("color: white;")
        
        # 底部：极大的可复制展示面板区，用来展示模型的识别字
        self.text_box = QTextEdit(self)
        self.text_box.setFont(QFont("微软雅黑", 13))
        self.text_box.setPlaceholderText("准备大声说出您的想法......\n最终大模型精炼的文字将会显示与留存于此！")
        self.text_box.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.05);
                color: #ffffff;
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 12px;
                line-height: 1.5;
            }
        """)
        
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.text_box)
        
        # 允许用户点击面板直接复制结果（兜底交互）
        self.text_box.setReadOnly(False) 
        self.text_box.mousePressEvent = lambda e: self._handle_click_copy()
        
        self.current_color = "rgba(10, 10, 10, 0.85)" # 默认为 Apple 质感深灰黑
        self._update_stylesheet()

        # 补全：初始化自动隐藏定时器（处理成功后隐藏）
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self.hide)

    def _handle_click_copy(self):
        import pyperclip
        txt = self.text_box.toPlainText()
        if txt:
            pyperclip.copy(txt)
            self.label.setText("Success! 已手动复制到剪贴板")

    def _update_stylesheet(self):
        # 究极 Apple 风格：30% 透明度黑色磨砂 + 极细边框级边
        self.container.setStyleSheet(f"""
            QWidget {{
                background-color: {self.current_color};
                border-radius: 24px;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }}
        """)

    def update_text(self, text_mode, new_text):
        """流式或直接替换下面输入展示框内的文本内容"""
        # 为了让效果出众和直观：展示最新的内容
        self.text_box.setText(new_text)
        # 滚动条到底
        self.text_box.moveCursor(QTextCursor.MoveOperation.End)
        
        # 如果是带有强提醒的重要阶段，也应该将它展示，不要被收起来
        self.show()

    def set_status(self, state, message=""):
        # 状态切换不再生硬改色背景，只改文字提示内容
        if message:
            self.label.setText(message.upper())
            
        if state == 'listening':
             self.text_box.clear()
             self.text_box.setPlaceholderText("RECORDING...")
             self.current_color = "rgba(10, 30, 60, 0.9)" # 录音状态微蓝
             
        if state == 'success':
             self.current_color = "rgba(10, 50, 10, 0.9)" # 成功状态微绿
             self.hide_timer.start(8000)
             
        if state == 'error':
             self.current_color = "rgba(60, 10, 10, 0.9)" # 错误状态微红
             self.hide_timer.start(8000)

        self._update_stylesheet()
        
        if state == 'idle':
            self.hide()
        else:
            self.show()
            self.raise_()
