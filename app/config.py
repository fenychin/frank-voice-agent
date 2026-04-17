import os
from dotenv import load_dotenv

load_dotenv()

PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
