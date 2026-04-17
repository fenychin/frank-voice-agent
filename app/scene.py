"""
场景分类器 — 自动检测 office / running / driving
基于关键词匹配 + 上下文推断的轻量级场景感知。
"""
import re

# 场景关键词映射（按优先级排列）
SCENE_KEYWORDS = {
    "driving": [
        "开车", "驾驶", "导航", "高速", "红绿灯", "限速",
        "加油站", "收费站", "路况", "车道", "停车",
    ],
    "running": [
        "跑步", "运动", "健身", "锻炼", "走路", "散步",
        "卡路里", "心率", "步数", "公里", "配速",
    ],
    "office": [
        "会议", "邮件", "报告", "文档", "PPT", "代码",
        "项目", "需求", "Bug", "部署", "发送",
        "老板", "同事", "客户", "方案", "排期",
    ],
}

# 默认场景
DEFAULT_SCENE = "office"


def classify_scene(text, current_scene=None):
    """
    基于文本内容自动推断场景。
    
    Args:
        text: 用户说的话（原始口语）
        current_scene: 当前场景（用于惯性保持）
    
    Returns:
        str: "office" | "running" | "driving"
    """
    if not text:
        return current_scene or DEFAULT_SCENE
    
    scores = {}
    text_lower = text.lower()
    
    for scene, keywords in SCENE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw.lower() in text_lower:
                score += 1
        scores[scene] = score
    
    # 找到最高分的场景
    best_scene = max(scores, key=scores.get)
    best_score = scores[best_scene]
    
    # 如果没有匹配到任何关键词，保持当前场景（惯性）
    if best_score == 0:
        return current_scene or DEFAULT_SCENE
    
    # 场景切换时打印日志
    if current_scene and best_scene != current_scene:
        print(f"[Scene] 场景切换: {current_scene} -> {best_scene}")
    
    return best_scene


def get_scene_system_prompt(scene):
    """
    根据场景返回不同的 LLM System Prompt 补丁。
    """
    prompts = {
        "office": """[场景: 办公]
输出整理后的书面文字，不需要语音回应。
保持专业、精练，直接输出要点。
适合复制粘贴到聊天窗口或文档中使用。""",
        
        "running": """[场景: 运动]
输出简短文字 + 30字以内的语音回应建议。
语气轻松亲切，像朋友一样鼓励。
不要长篇大论，保持简洁。""",
        
        "driving": """[场景: 驾驶]
只输出极简指令式回应（15字以内）。
优先安全，不分散注意力。
如非必要不输出长文。""",
    }
    return prompts.get(scene, prompts["office"])


def get_max_length(scene):
    """根据场景返回输出字数上限"""
    limits = {
        "office": 500,
        "running": 80,
        "driving": 40,
    }
    return limits.get(scene, 500)
