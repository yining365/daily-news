"""
阿宁日报 V2 - 配置模块
"""
import os

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "docs")

# AI 配置 (DashScope, OpenAI-compatible)
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "kimi-k2.5")

# X (Twitter) 配置
X_AUTH_TOKEN = os.getenv("X_AUTH_TOKEN", "")
X_CT0 = os.getenv("X_CT0", "")

# V2: 5 个高信噪比源
SOURCES = {
    "hackernews": {"name": "Hacker News", "icon": "🔶", "section": "科技/AI"},
    "polymarket": {"name": "Polymarket", "icon": "📊", "section": "市场信号"},
    "github": {"name": "GitHub Trending", "icon": "🐙", "section": "开源趋势"},
    "wallstreetcn": {"name": "华尔街见闻", "icon": "💹", "section": "宏观/金融"},
    "x": {"name": "X (Twitter)", "icon": "𝕏", "section": "社交信号"},
}

SITE_META = {
    "title": "阿宁日报",
    "subtitle": "每日信息编辑部",
    "author": "Daily News V2",
}
