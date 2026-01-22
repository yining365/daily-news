"""
News Aggregator Skill - 配置模块
包含所有配置信息和主题定义
"""
import os

# ============================================================================
# 输出配置
# ============================================================================
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "docs")

# ============================================================================
# 8种主题配色方案
# ============================================================================
THEMES = {
    "blue": {
        "name": "科技蓝",
        "description": "适用于科技/商务/数据类内容",
        "glow_start": "#0A1929",
        "glow_end": "#1A3A52",
        "title": "#FFFFFF",
        "text": "#E3F2FD",
        "accent": "#42A5F5",
        "secondary": "#B0BEC5",
        "gradient": "linear-gradient(135deg, #0A1929 0%, #1A3A52 100%)"
    },
    "indigo": {
        "name": "深靛蓝",
        "description": "适用于高端/企业/权威类内容",
        "glow_start": "#0F1C3F",
        "glow_end": "#1A2F5A",
        "title": "#FFFFFF",
        "text": "#E3F2FD",
        "accent": "#5C9FE5",
        "secondary": "#BBDEFB",
        "gradient": "linear-gradient(135deg, #0F1C3F 0%, #1A2F5A 100%)"
    },
    "purple": {
        "name": "优雅紫色",
        "description": "适用于创意/奢华/创新类内容",
        "glow_start": "#1A0A28",
        "glow_end": "#2D1B3D",
        "title": "#FFFFFF",
        "text": "#F3E5F5",
        "accent": "#B39DDB",
        "secondary": "#D1C4E9",
        "gradient": "linear-gradient(135deg, #1A0A28 0%, #2D1B3D 100%)"
    },
    "green": {
        "name": "清新绿色",
        "description": "适用于健康/可持续/成长类内容",
        "glow_start": "#0D1F12",
        "glow_end": "#1B3A26",
        "title": "#FFFFFF",
        "text": "#E8F5E9",
        "accent": "#66BB6A",
        "secondary": "#C8E6C9",
        "gradient": "linear-gradient(135deg, #0D1F12 0%, #1B3A26 100%)"
    },
    "orange": {
        "name": "温暖橙色",
        "description": "适用于活力/热情/社交类内容",
        "glow_start": "#1F1410",
        "glow_end": "#3D2415",
        "title": "#FFFFFF",
        "text": "#FFF3E0",
        "accent": "#FFA726",
        "secondary": "#FFCCBC",
        "gradient": "linear-gradient(135deg, #1F1410 0%, #3D2415 100%)"
    },
    "pink": {
        "name": "玫瑰粉色",
        "description": "适用于生活/美妆/健康类内容",
        "glow_start": "#1F0A14",
        "glow_end": "#3D1528",
        "title": "#FFFFFF",
        "text": "#FCE4EC",
        "accent": "#F06292",
        "secondary": "#F8BBD0",
        "gradient": "linear-gradient(135deg, #1F0A14 0%, #3D1528 100%)"
    },
    "teal": {
        "name": "冷色青绿",
        "description": "适用于金融/信任/稳定类内容",
        "glow_start": "#0A1F1F",
        "glow_end": "#164E4D",
        "title": "#FFFFFF",
        "text": "#E0F2F1",
        "accent": "#26A69A",
        "secondary": "#B2DFDB",
        "gradient": "linear-gradient(135deg, #0A1F1F 0%, #164E4D 100%)"
    },
    "gray": {
        "name": "中性灰色",
        "description": "适用于极简/专业/通用类内容",
        "glow_start": "#1A1A1D",
        "glow_end": "#2D2D30",
        "title": "#FFFFFF",
        "text": "#F5F5F5",
        "accent": "#9E9E9E",
        "secondary": "#E0E0E0",
        "gradient": "linear-gradient(135deg, #1A1A1D 0%, #2D2D30 100%)"
    }
}

# ============================================================================
# 信息源分类 - 适配 news-aggregator-skill 的8大信源
# ============================================================================
SOURCE_CATEGORIES = {
    "hackernews": {"name": "Hacker News", "icon": "🔶", "theme": "orange"},
    "producthunt": {"name": "Product Hunt", "icon": "🚀", "theme": "orange"},
    "github": {"name": "GitHub Trending", "icon": "🐙", "theme": "purple"},
    "v2ex": {"name": "V2EX", "icon": "💬", "theme": "green"},
    "36kr": {"name": "36Kr", "icon": "📰", "theme": "blue"},
    "tencent": {"name": "腾讯科技", "icon": "🐧", "theme": "blue"},
    "weibo": {"name": "微博热搜", "icon": "🔥", "theme": "pink"},
    "wallstreetcn": {"name": "华尔街见闻", "icon": "💹", "theme": "teal"},
}

# ============================================================================
# 场景分类映射 (V2.0 Dashboard)
# ============================================================================
SCENARIO_MAP = {
    "ai": {
        "name": "🔥 AI 热点",
        "description": "硅谷前沿：Hacker News + Product Hunt",
        "sources": ["hackernews", "producthunt"],
        "keywords": ["AI", "LLM", "GPT", "Claude", "Model", "RAG", "Agent", "Generative"]
    },
    "china": {
        "name": "🇨🇳 科技",
        "description": "国内大厂与创投：36Kr + 腾讯新闻",
        "sources": ["36kr", "tencent"],
        "keywords": []  # No filtering - these sources are already tech/business focused
    },
    "github": {
        "name": "🐙 开源精选",
        "description": "GitHub Trending 热门项目",
        "sources": ["github"],
        "keywords": []
    },
    "global": {
        "name": "🌐 全网扫描",
        "description": "全网关键词扫描 (Agent + LLM)",
        "sources": ["all"],
        "keywords": ["Agent", "LLM", "RAG", "AI", "Startup", "SaaS", "Open Source"]
    }
}

# ============================================================================
# 默认主题
# ============================================================================
DEFAULT_THEME = "blue"

# ============================================================================
# 网站元信息
# ============================================================================
SITE_META = {
    "title": "News Aggregator",
    "subtitle": "全网新闻聚合",
    "description": "多源新闻聚合，一站式掌握全球动态",
    "author": "News Aggregator Skill",
    "keywords": ["新闻", "聚合", "科技", "热搜", "GitHub", "创投"]
}

# ============================================================================
# 图片生成 API 配置 (可选)
# ============================================================================
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL", "https://fireflycard-api.302ai.cn/api/saveImg")
FIREFLY_API_KEY = os.getenv("FIREFLY_API_KEY", "")
ENABLE_IMAGE_GENERATION = os.getenv("ENABLE_IMAGE_GENERATION", "false").lower() == "true"


def get_theme(theme_name: str) -> dict:
    """获取指定主题配置"""
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def get_source_info(source_key: str) -> dict:
    """获取信息源配置"""
    return SOURCE_CATEGORIES.get(source_key.lower(), {"name": source_key, "icon": "📄", "theme": DEFAULT_THEME})
