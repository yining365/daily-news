"""
HTML 生成模块
根据新闻数据生成精美的 HTML 页面
"""
import os
import json
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from src.config import (
    OUTPUT_DIR,
    THEMES,
    SITE_META,
    SCENARIO_MAP,
    get_theme,
    get_source_info
)

class HTMLGenerator:
    """HTML 页面生成器"""
    
    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_css()

    def _setup_css(self):
        """确保 CSS 文件存在"""
        self.generate_css()

    def generate_daily(self, news_items: List[Dict[str, Any]]) -> str:
        """
        生成日报 HTML 页面
        
        Args:
            news_items: 新闻列表
            
        Returns:
            生成的 HTML 文件路径
        """
        if not news_items:
            return self.generate_empty(datetime.now().strftime("%Y-%m-%d"))

        date_str = datetime.now().strftime("%Y-%m-%d")
        theme = get_theme("blue")  # 默认使用科技蓝
        
        # 按源分类整理数据
        # news_items 结构: [{"source": "Hacker News", "title": "...", "url": "...", "time": "...", "heat": "..."}]
        
        html = self._build_daily_html(date_str, news_items, theme)
        
        output_path = self.output_dir / f"{date_str}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
            
        # 更新 index.html
        self.update_index(date_str, news_items)
            
        return str(output_path)

    def generate_empty(self, date: str, reason: str = "今日暂无资讯") -> str:
        """生成空状态页面"""
        theme = get_theme("gray")
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{reason} - {SITE_META['title']}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body class="theme-{theme}">
    <div class="container empty-state">
        <div class="header">
            <div class="logo">Daily News</div>
            <div class="date">{date}</div>
        </div>
        <div class="empty-content">
            <div class="empty-icon">📭</div>
            <h1>{reason}</h1>
            <p>请稍后再试，或检查网络连接。</p>
        </div>
    </div>
</body>
</html>"""
        
        output_path = self.output_dir / f"{date}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return str(output_path)

    def generate_dashboard(self, date: str, scenarios_data: Dict[str, List[Dict[str, Any]]], summary: str = None) -> str:
        """生成 Dashboard HTML 页面 - 滚动布局版本"""
        theme = get_theme("blue")
        
        # 构建所有场景的内容（垂直排列）
        sections_html = ""
        
        # 排序：China -> X Social -> AI -> GitHub -> Global (科技优先)
        scenario_order = ["china", "x_social", "ai", "github", "global"]
        
        total_count = 0
        for key in scenario_order:
            if key not in SCENARIO_MAP: continue
            
            info = SCENARIO_MAP[key]
            items = scenarios_data.get(key, [])
            count = len(items)
            # Skip empty sections
            if count == 0:
                continue
            
            total_count += count

            
            # 构建每个场景的内容区块
            section_html = self._build_section_content(items)
            sections_html += f"""
            <section class="scenario-section" id="{key}">
                <div class="scenario-header">
                    <h2 class="scenario-name">{info['name']}</h2>
                    <span class="scenario-count">{count} 条</span>
                    <span class="scenario-desc">{info['description']}</span>
                </div>
                {section_html}
            </section>
            """

        # Build Summary HTML if provided
        summary_html = ""
        if summary:
            summary_html = f"""
            <div class="daily-summary">
                <div class="summary-content">
                    <span class="summary-icon">💡</span>
                    <p>{summary}</p>
                </div>
            </div>
            """



        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{date} {SITE_META['subtitle']} - {SITE_META['title']}</title>
    <link rel="stylesheet" href="style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        :root {{
            --glow-start: {theme['glow_start']};
            --glow-end: {theme['glow_end']};
            --text-primary: {theme['text']};
            --accent-color: {theme['accent']};
            --secondary-color: {theme['secondary']};
            --bg-gradient: {theme['gradient']};
        }}
        
        /* 快速导航 */
        .quick-nav {{
            display: flex;
            justify-content: center;
            gap: 1rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
            position: sticky;
            top: 0;
            background: rgba(15, 23, 42, 0.95);
            padding: 1rem;
            z-index: 100;
            backdrop-filter: blur(10px);
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .quick-nav-item {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            color: var(--text-primary);
            text-decoration: none;
            font-size: 0.9rem;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .quick-nav-item:hover {{
            background: var(--accent-color);
            color: #fff;
        }}
        .quick-nav-item span {{
            background: rgba(0,0,0,0.2);
            padding: 2px 6px;
            border-radius: 8px;
            font-size: 0.75rem;
        }}
        
        /* 场景区块 */
        .scenario-section {{
            margin-bottom: 4rem;
            scroll-margin-top: 80px;
        }}
        .scenario-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid var(--accent-color);
            flex-wrap: wrap;
        }}
        .scenario-name {{
            font-size: 1.8rem;
            font-weight: 700;
            color: #fff;
        }}
        .scenario-count {{
            background: var(--accent-color);
            color: #fff;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
        }}
        .scenario-desc {{
            opacity: 0.6;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="app-container">
        <header class="main-header">
            <div class="header-content">
                <div class="logo-area">
                    <div class="logo-icon">🤖</div>
                    <div class="logo-text">
                        <h1>{SITE_META['title']}</h1>
                        <p class="subtitle">{SITE_META['subtitle']}</p>
                    </div>
                </div>
                <div class="date-display">
                    <span class="date-icon">📅</span>
                    <span>{self._format_date(date)}</span>
                </div>
            </div>
        </header>

        {summary_html}



        <main class="main-content">
            {sections_html}
        </main>

        <footer class="main-footer">
            <p>Generated by {SITE_META['author']} • <a href="index.html">History</a></p>
        </footer>
    </div>
    
    <script>
    // Keyboard Navigation
    document.addEventListener('keydown', function(e) {{
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

        const cards = Array.from(document.querySelectorAll('.card'));
        if (!cards.length) return;
        
        let activeIndex = cards.findIndex(c => c === document.activeElement || c.classList.contains('active-card'));
        
        if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowDown') {{
             activeIndex = (activeIndex + 1) % cards.length;
             e.preventDefault();
        }} else if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowUp') {{
             if (activeIndex === -1) activeIndex = 0;
             else activeIndex = (activeIndex - 1 + cards.length) % cards.length;
             e.preventDefault();
        }} else if (e.key === 'Enter') {{
             if (activeIndex >= 0) {{
                const link = cards[activeIndex].querySelector('a');
                if(link) window.open(link.href, '_blank');
             }}
             return;
        }} else {{
             return;
        }}
        
        cards.forEach(c => c.classList.remove('active-card'));
        if (activeIndex >= 0) {{
            cards[activeIndex].classList.add('active-card');
            cards[activeIndex].focus();
            cards[activeIndex].scrollIntoView({{behavior: 'smooth', block: 'center'}});
        }}
    }});
    </script>
</body>
</html>"""
        
        output_path = self.output_dir / f"{date}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
            
        return str(output_path)

    def _build_section_content(self, items: List[Dict[str, Any]]) -> str:
        """构建单个 Tab 的内容"""
        if not items:
            return '<div class="empty-tab">暂无内容，请稍候再试。</div>'
            
        grouped_items = {}
        for item in items:
            source = item.get('source', 'Other')
            if source not in grouped_items:
                grouped_items[source] = []
            grouped_items[source].append(item)
            
        html = ""
        # 简单排序源
        for source in sorted(grouped_items.keys()):
            source_items = grouped_items[source]
            info = get_source_info(source.lower().replace(" ", "").replace("hotsearch", "").replace("trending", "")) # heuristic key matching
            
            html += f"""
            <div class="category-section">
                <div class="category-header">
                    <span class="category-icon">{info.get('icon', '📰')}</span>
                    <h2 class="category-title">{source}</h2>
                    <span class="category-count">{len(source_items)}</span>
                </div>
                <div class="cards-grid">
            """
            
            # Sort items by heat_score within source (as fallback if not global sort)
            # Actually fetch_news.py sorts globally, but here we group by source. 
            # If we want "Top 3 Must Read" at the top of the TAB, we should change the layout logic.
            # But per current "group by source" layout, we can just highlight the high heat ones.
            # Let's keep existing group layout but highlight heat.
            
            for i, item in enumerate(source_items):
                title = item.get('title', '')
                url = item.get('url', '#')
                time_str = item.get('time', '')
                heat = item.get('heat', '')
                
                meta_html = ""
                if time_str:
                    meta_html += f'<span class="meta-item"><span class="meta-icon">🕒</span>{time_str}</span>'
                if heat:
                     meta_html += f'<span class="meta-item"><span class="meta-icon">🔥</span>{heat}</span>'

                summary_text = item.get('summary', '')
                summary_html = ""
                if summary_text:
                    summary_html = f'<p class="card-summary">{summary_text}</p>'

                # Determine if item is "Hot"
                is_hot = False
                heat_str = str(heat).lower()
                if '万' in heat_str or 'w' in heat_str or 'k' in heat_str:
                    is_hot = True
                elif 'points' in heat_str:
                    try:
                        if int(heat_str.split()[0]) >= 200: is_hot = True
                    except: pass
                elif 'reply' in heat_str or 'replies' in heat_str:
                    try:
                         if int(heat_str.split()[0]) >= 50: is_hot = True
                    except: pass

                # Determine Rank (Gold/Silver/Bronze) based on heat_score if available
                rank_class = ""
                if item.get('heat_score', 0) > 1000: # Super high heat
                    rank_class = "rank-gold"
                
                hot_class = "is-hot" if is_hot else ""
                
                # Check for practicality tags in title to add badge
                badge_html = ""
                if "🛠️" in title:
                    badge_html += '<span class="badge badge-tool">Tool</span>'
                    title = title.replace("🛠️", "").strip()
                if "📖" in title:
                    badge_html += '<span class="badge badge-tutorial">Tutorial</span>'
                    title = title.replace("📖", "").strip()

                html += f"""
                    <div class="card {hot_class} {rank_class}" tabindex="0">
                        <div class="card-content">
                            <a href="{url}" target="_blank" class="card-title-link">
                                <h3 class="card-title">{title}</h3>
                            </a>
                             <div class="badges">{badge_html}</div>
                            {summary_html}
                            <div class="card-meta">
                                {meta_html}
                            </div>
                        </div>
                    </div>
                """
            html += "</div></div>"
        return html


    def _format_date(self, date_str: str) -> str:
        """格式化日期显示"""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return f"{dt.month}月{dt.day}日 {weekdays[dt.weekday()]}"
        except:
            return date_str

    def update_index(self, date: str, items: List[Dict[str, Any]] = None):
        """更新索引页"""
        index_path = self.output_dir / "index.html"
        entries = []
        
        # 读取现有索引
        if index_path.exists():
            try:
                content = index_path.read_text(encoding='utf-8')
                # 这里是个简化处理，实际应该用 soup 解析或存 json 数据文件
                # 为了简单起见，我们暂不实现复杂的历史记录解析，而是追加生成的
                pass 
            except:
                pass
        
        # 创建 index.html - 自动跳转到今日新闻
        today_file = f"{date}.html"
        index_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url={today_file}">
    <title>{SITE_META['title']}</title>
    <script>window.location.href = "{today_file}";</script>
</head>
<body>
    <p>正在跳转到今日新闻... <a href="{today_file}">点击这里</a></p>
</body>
</html>"""
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        
        # 生成历史链接列表
        files = sorted(self.output_dir.glob("*.html"), reverse=True)
        html_links = ""
        for f in files:
            if f.name in ["index.html", "history.html"]: continue
            name = f.stem
            html_links += f'<li><a href="{f.name}">{name}</a></li>'
        
        # 创建 history.html - 历史归档页面
        history_path = self.output_dir / "history.html"
        history_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>History - {SITE_META['title']}</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; line-height: 1.6; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ background: white; margin-bottom: 1rem; padding: 1rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        a {{ text-decoration: none; color: #0066cc; font-weight: 500; font-size: 1.1rem; }}
        a:hover {{ text-decoration: underline; }}
        .back {{ margin-bottom: 1.5rem; display: inline-block; }}
    </style>
</head>
<body>
    <a href="index.html" class="back">← 返回今日新闻</a>
    <h1>📚 历史归档</h1>
    <ul>
        {html_links}
    </ul>
</body>
</html>"""
        with open(history_path, "w", encoding="utf-8") as f:
            f.write(history_html)

    def generate_css(self):
        """生成 CSS 文件"""
        css_content = self._get_css_content()
        css_path = self.output_dir / "style.css"
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(css_content)

    def _get_css_content(self) -> str:
        return """
/* 基础重置 */
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0f172a; /* Fallback */
    background: var(--bg-gradient);
    color: var(--text-primary);
    min-height: 100vh;
    line-height: 1.6;
}

/* 布局容器 */
.app-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

/* 头部样式 */
.main-header {
    margin-bottom: 1.5rem; /* Reduced bottom margin to fit summary */
    padding-bottom: 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.header-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.logo-area {
    display: flex;
    align-items: center;
    gap: 1rem;
}
.logo-icon {
    font-size: 2.5rem;
    background: rgba(255, 255, 255, 0.1);
    width: 60px;
    height: 60px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.logo-text h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--title-color);
    margin-bottom: 0.2rem;
}
.subtitle {
    font-size: 0.9rem;
    opacity: 0.7;
    font-weight: 400;
}
.date-display {
    background: rgba(255, 255, 255, 0.05);
    padding: 0.5rem 1rem;
    border-radius: 20px;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    backdrop-filter: blur(5px);
}

/* Daily Summary */
.daily-summary {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin-bottom: 2.5rem;
    backdrop-filter: blur(5px);
}
.summary-content {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
}
.summary-icon {
    font-size: 1.5rem;
    margin-top: 0.2rem;
}
.daily-summary p {
    font-size: 1rem;
    line-height: 1.6;
    color: #eceff4;
    margin: 0;
    max-width: 800px;
}

/* 分类部分 */
.category-section {
    margin-bottom: 2.5rem;
}
.category-header {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin-bottom: 1.2rem;
    padding-left: 0.5rem;
    border-left: 4px solid var(--accent-color);
}
.category-icon { font-size: 1.4rem; }
.category-title {
    font-size: 1.4rem;
    font-weight: 600;
    color: #fff;
}
.category-count {
    background: rgba(255,255,255,0.1);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.75rem;
    opacity: 0.8;
}

/* Tabs 导航 */
.tabs-nav {
    display: flex;
    justify-content: center;
    gap: 1rem;
    margin-bottom: 2.5rem;
    flex-wrap: wrap;
}
.tab-btn {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    padding: 0.8rem 1.5rem;
    border-radius: 2rem;
    color: var(--text-primary);
    cursor: pointer;
    font-size: 1rem;
    transition: all 0.3s ease;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.tab-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-2px);
}
.tab-btn.active {
    background: var(--accent-color);
    border-color: var(--accent-color);
    color: #fff;
    box-shadow: 0 4px 15px rgba(66, 165, 245, 0.4);
}
.tab-count {
    background: rgba(0, 0, 0, 0.2);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.8rem;
}

/* Tab 内容显隐 */
.tab-content {
    display: none;
    animation: fadeIn 0.5s ease;
}
.tab-content.active {
    display: block;
}
.scenario-desc {
    text-align: center;
    opacity: 0.6;
    margin-bottom: 2rem;
    font-size: 0.95rem;
}

/* 卡片网格 */
.cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.5rem;
}

/* 卡片样式 */
.card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 16px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
    position: relative;
    backdrop-filter: blur(10px);
}
.card:hover {
    transform: translateY(-4px) scale(1.02);
    background: rgba(255, 255, 255, 0.08);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.3);
    border-color: var(--accent-color);
    z-index: 10;
}
.card-content {
    padding: 1.5rem;
}
/* 链接颜色 */
.card-title-link {
    text-decoration: none;
    color: inherit;
    display: block;
}
.card-title-link:visited .card-title {
    color: rgba(255, 255, 255, 0.4);
}

.card:focus {
    outline: none;
    border-color: var(--accent-color);
    box-shadow: 0 0 0 2px rgba(66, 165, 245, 0.5);
}
.card.active-card {
    border-color: var(--accent-color);
    box-shadow: 0 0 20px rgba(66, 165, 245, 0.3);
    transform: scale(1.02);
    z-index: 5;
}
.card.is-hot {
    border-color: rgba(255, 167, 38, 0.6); /* Orange border for hot */
    background: linear-gradient(to bottom right, rgba(255, 167, 38, 0.05), rgba(255, 255, 255, 0.03));
}
.card.is-hot::after {
    content: "🔥";
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    font-size: 1rem;
    opacity: 0.8;
}

.card-title {
    font-size: 1.1rem;
    font-weight: 600;
    line-height: 1.5;
    margin-bottom: 1rem;
    color: #eceff4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.card-title-link:hover .card-title {
    color: var(--accent-color);
}
.card-summary {
    font-size: 0.9rem;
    color: rgba(255, 255, 255, 0.7);
    margin-bottom: 1rem;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.card-meta {
    display: flex;
    gap: 1rem;
    font-size: 0.8rem;
    color: rgba(255, 255, 255, 0.5);
    align-items: center;
}
.meta-item {
    display: flex;
    align-items: center;
    gap: 0.3rem;
}
.meta-icon { opacity: 0.7; font-size: 0.9em; }

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Badges */
.badges {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
}
.badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    text-transform: uppercase;
}
.badge-tool {
    background: rgba(66, 165, 245, 0.2);
    color: #42A5F5;
    border: 1px solid rgba(66, 165, 245, 0.3);
}
.badge-tutorial {
    background: rgba(102, 187, 106, 0.2);
    color: #66BB6A;
    border: 1px solid rgba(102, 187, 106, 0.3);
}

.card.rank-gold {
   border: 1px solid rgba(255, 215, 0, 0.5);
   box-shadow: 0 0 15px rgba(255, 215, 0, 0.2);
}

/* 响应式调整 - 手机适配 */
@media (max-width: 768px) {
    .app-container { 
        padding: 0.75rem; 
    }
    
    /* 头部 */
    .main-header {
        margin-bottom: 1rem;
        padding-bottom: 1rem;
    }
    .header-content { 
        flex-direction: column; 
        align-items: flex-start; 
        gap: 0.75rem; 
    }
    .logo-icon {
        width: 48px;
        height: 48px;
        font-size: 1.8rem;
    }
    .logo-text h1 {
        font-size: 1.2rem;
    }
    .date-display { 
        align-self: flex-start;
        font-size: 0.8rem;
        padding: 0.4rem 0.8rem;
    }
    
    /* 每日摘要 */
    .daily-summary {
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
    }
    .summary-content {
        flex-direction: column;
        gap: 0.5rem;
    }
    .daily-summary p {
        font-size: 0.9rem;
    }
    
    /* 快速导航 - 手机版 */
    .quick-nav {
        gap: 0.5rem;
        padding: 0.75rem 0.5rem;
    }
    .quick-nav-item {
        padding: 0.4rem 0.75rem;
        font-size: 0.8rem;
    }
    .quick-nav-item span {
        padding: 1px 5px;
        font-size: 0.7rem;
    }
    
    /* 场景区块 */
    .scenario-section {
        margin-bottom: 2.5rem;
        scroll-margin-top: 70px;
    }
    .scenario-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.5rem;
        margin-bottom: 1rem;
        padding-bottom: 0.75rem;
    }
    .scenario-name {
        font-size: 1.3rem;
    }
    .scenario-count {
        padding: 2px 10px;
        font-size: 0.75rem;
    }
    .scenario-desc {
        font-size: 0.8rem;
    }
    
    /* 分类区块 */
    .category-section {
        margin-bottom: 1.5rem;
    }
    .category-header {
        margin-bottom: 0.8rem;
        padding-left: 0.4rem;
    }
    .category-icon { font-size: 1.1rem; }
    .category-title { font-size: 1.1rem; }
    
    /* 卡片网格 - 单列 */
    .cards-grid { 
        grid-template-columns: 1fr; 
        gap: 1rem;
    }
    
    /* 卡片 */
    .card-content {
        padding: 1rem;
    }
    .card-title {
        font-size: 1rem;
        margin-bottom: 0.75rem;
    }
    .card-summary {
        font-size: 0.85rem;
        -webkit-line-clamp: 2;
        margin-bottom: 0.75rem;
    }
    .card-meta {
        gap: 0.75rem;
        font-size: 0.75rem;
    }
    
    /* 底部 */
    .main-footer {
        margin-top: 2rem;
        font-size: 0.8rem;
    }
}

/* 底部 */

.main-footer {
    text-align: center;
    margin-top: 5rem;
    padding-top: 2rem;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    font-size: 0.9rem;
    color: rgba(255, 255, 255, 0.3);
}
.main-footer a { color: inherit; text-decoration: none; opacity: 0.7; }
.main-footer a:hover { opacity: 1; }
"""

def generate_daily_html(news_items: List[Dict[str, Any]]) -> str:
    """便捷函数：生成日报 HTML"""
    generator = HTMLGenerator()
    return generator.generate_daily(news_items)
