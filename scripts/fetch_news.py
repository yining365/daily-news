"""
阿宁日报 V2 - 主脚本
抓取 → AI 筛选分析 → AI 归纳点评 → 生成日报
"""
import json
import re
import sys
import os
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import OUTPUT_DIR, AI_BASE_URL, AI_API_KEY, AI_MODEL, SITE_META, X_AUTH_TOKEN, X_CT0
from src.html_generator import HTMLGenerator

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


# ============================================================================
# 源抓取
# ============================================================================

def fetch_hackernews(limit=30):
    items = []
    try:
        resp = requests.get("https://news.ycombinator.com/news", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for row in soup.select(".athing")[:limit]:
            try:
                id_ = row.get("id")
                a = row.select_one(".titleline a")
                if not a:
                    continue
                title = a.get_text()
                url = a.get("href", "")
                if url.startswith("item?id="):
                    url = f"https://news.ycombinator.com/{url}"
                score_el = soup.select_one(f"#score_{id_}")
                score = score_el.get_text() if score_el else "0 points"
                items.append({"source": "Hacker News", "title": title, "url": url, "score": score})
            except Exception:
                continue
    except Exception as e:
        sys.stderr.write(f"[HN] Error: {e}\n")
    return items


def fetch_polymarket(limit=15):
    SPORTS_KEYWORDS = [
        "fifa", "world cup winner", "nba", "nfl", "mlb", "nhl",
        "premier league", "la liga", "champions league", "serie a",
        "bundesliga", "ufc", "mma", "f1 driver", "masters - winner",
        "australian open", "stanley cup", "nba mvp", "nba champion",
        "eurovision",
    ]
    items = []
    try:
        resp = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={"limit": limit * 3, "active": "true", "closed": "false",
                    "order": "volume", "ascending": "false"},
            timeout=10,
        )
        data = resp.json()
        for event in data:
            title = event.get("title", "")
            if any(kw in title.lower() for kw in SPORTS_KEYWORDS):
                continue
            volume = float(event.get("volume", 0))
            if volume < 1_000_000:
                continue

            slug = event.get("slug", "")
            url = f"https://polymarket.com/event/{slug}" if slug else ""
            vol_str = f"${volume / 1_000_000:.1f}M"

            markets = event.get("markets", [])
            top_markets = []
            for m in markets[:5]:
                q = m.get("question", "")
                prices_raw = m.get("outcomePrices", "")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    if prices and len(prices) >= 2:
                        yes_pct = float(prices[0]) * 100
                        if 5 < yes_pct < 95:
                            top_markets.append(f"{q}: Yes {yes_pct:.0f}%")
                except Exception:
                    pass

            prices_str = " | ".join(top_markets[:3]) if top_markets else ""
            items.append({
                "source": "Polymarket",
                "title": title,
                "url": url,
                "prices": prices_str,
                "volume": vol_str,
            })
            if len(items) >= limit:
                break
    except Exception as e:
        sys.stderr.write(f"[Polymarket] Error: {e}\n")
    return items


def fetch_github(limit=15):
    items = []
    try:
        resp = requests.get("https://github.com/trending", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for article in soup.select("article.Box-row")[:limit]:
            try:
                h2 = article.select_one("h2 a")
                if not h2:
                    continue
                name = h2.get_text(strip=True).replace("\n", "").replace(" ", "")
                url = "https://github.com" + h2["href"]
                desc = article.select_one("p")
                desc_text = desc.get_text(strip=True) if desc else ""
                stars_el = article.select_one("a[href$='/stargazers']")
                stars = stars_el.get_text(strip=True) if stars_el else ""
                items.append({
                    "source": "GitHub Trending",
                    "title": f"{name}: {desc_text}" if desc_text else name,
                    "url": url,
                    "stars": stars,
                })
            except Exception:
                continue
    except Exception as e:
        sys.stderr.write(f"[GitHub] Error: {e}\n")
    return items


def fetch_wallstreetcn(limit=20):
    items = []
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30"
        data = requests.get(url, timeout=10).json()
        for item in data["data"]["items"][:limit]:
            res = item.get("resource", {})
            title = res.get("title") or res.get("content_short", "")
            if not title:
                continue
            ts = res.get("display_time", 0)
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""
            items.append({
                "source": "华尔街见闻",
                "title": title,
                "url": res.get("uri", ""),
                "time": time_str,
            })
    except Exception as e:
        sys.stderr.write(f"[WallStreetCN] Error: {e}\n")
    return items


def fetch_x_timeline(limit=20):
    if not X_AUTH_TOKEN or not X_CT0:
        sys.stderr.write("[X] No auth tokens, skipping\n")
        return []

    items = []
    try:
        headers = {
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'x-csrf-token': X_CT0,
            'cookie': f'auth_token={X_AUTH_TOKEN}; ct0={X_CT0}',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        }
        variables = {"count": 40, "includePromotedContent": False, "requestContext": "launch", "withCommunity": True}
        features = {"rweb_video_screen_enabled":False,"profile_label_improvements_pcf_label_in_post_enabled":True,"responsive_web_profile_redirect_enabled":False,"rweb_tipjar_consumption_enabled":False,"verified_phone_label_enabled":False,"creator_subscriptions_tweet_preview_api_enabled":True,"responsive_web_graphql_timeline_navigation_enabled":True,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":False,"premium_content_api_read_enabled":False,"communities_web_enable_tweet_community_results_fetch":True,"c9s_tweet_anatomy_moderator_badge_enabled":True,"responsive_web_grok_analyze_button_fetch_trends_enabled":False,"responsive_web_grok_analyze_post_followups_enabled":True,"responsive_web_jetfuel_frame":True,"responsive_web_grok_share_attachment_enabled":True,"responsive_web_grok_annotations_enabled":True,"articles_preview_enabled":True,"responsive_web_edit_tweet_api_enabled":True,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":True,"view_counts_everywhere_api_enabled":True,"longform_notetweets_consumption_enabled":True,"responsive_web_twitter_article_tweet_consumption_enabled":True,"tweet_awards_web_tipping_enabled":False,"content_disclosure_indicator_enabled":True,"content_disclosure_ai_generated_indicator_enabled":True,"freedom_of_speech_not_reach_fetch_enabled":True,"standardized_nudges_misinfo":True,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":True,"longform_notetweets_rich_text_read_enabled":True,"longform_notetweets_inline_media_enabled":False,"responsive_web_enhance_cards_enabled":False}
        params = {'variables': json.dumps(variables), 'features': json.dumps(features)}

        resp = requests.get(
            'https://x.com/i/api/graphql/L8Lb9oomccM012S7fQ-QKA/HomeTimeline',
            headers=headers, params=params, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        instructions = data.get('data', {}).get('home', {}).get('home_timeline_urt', {}).get('instructions', [])
        tweets = []
        for inst in instructions:
            for e in inst.get('entries', []):
                if e.get('entryId', '').startswith('promoted'):
                    continue
                content = e.get('content', {})
                ic = content.get('itemContent', {})
                result = ic.get('tweet_results', {}).get('result', {})
                if result.get('__typename') == 'TweetWithVisibilityResults':
                    result = result.get('tweet', {})
                if result.get('__typename') != 'Tweet':
                    continue
                legacy = result.get('legacy', {})
                user = result.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {})
                text = legacy.get('full_text', '')
                if not text or text.startswith('RT @'):
                    continue
                clean_text = text.split('https://t.co/')[0].strip()
                if len(clean_text) < 10:
                    continue
                screen_name = user.get('screen_name', '')
                fav = legacy.get('favorite_count', 0)
                rt = legacy.get('retweet_count', 0)
                tweet_id = legacy.get('id_str', '')
                tweets.append({
                    'text': clean_text,
                    'screen_name': screen_name,
                    'fav': fav,
                    'rt': rt,
                    'url': f"https://x.com/{screen_name}/status/{tweet_id}",
                    'engagement': fav + rt * 3,
                })

        tweets.sort(key=lambda x: x['engagement'], reverse=True)

        for t in tweets[:limit]:
            items.append({
                "source": "X (Twitter)",
                "title": f"@{t['screen_name']}: {t['text'][:150]}",
                "url": t['url'],
                "engagement": f"L{t['fav']} RT{t['rt']}",
            })
    except Exception as e:
        sys.stderr.write(f"[X] Error: {e}\n")
    return items


# ============================================================================
# AI 编辑层
# ============================================================================

def call_ai(messages, temperature=0.7):
    if not AI_API_KEY:
        sys.stderr.write("[AI] No API key, skipping AI analysis\n")
        return None

    try:
        resp = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        sys.stderr.write(f"[AI] Error: {e}\n")
        return None


def ai_round1_filter_and_analyze(all_items):
    items_text = ""
    for i, item in enumerate(all_items):
        line = f"[{i}] [{item['source']}] {item['title']}"
        if item.get("prices"):
            line += f" | 定价: {item['prices']}"
        if item.get("volume"):
            line += f" | 交易量: {item['volume']}"
        if item.get("score"):
            line += f" | {item['score']}"
        if item.get("stars"):
            line += f" | {item['stars']} stars"
        if item.get("engagement"):
            line += f" | {item['engagement']}"
        if item.get("url"):
            line += f" | {item['url']}"
        items_text += line + "\n"

    prompt = f"""你是一个高质量日报的编辑。从以下 {len(all_items)} 条信息中，选出 5-10 条最有价值的，并为每条写分析。

## 准入标准（满足至少一个才入选）
1. 改变判断 — 看完之后观点和之前不一样
2. 量化不确定性 — 有具体数字/定价，不是泛泛而谈
3. 意外连接 — 把看似无关的事串成一条线
4. 时间窗口 — 今天看有价值，下周看就没有了

## 不该入选的
- 刷 5 分钟 X 就知道的新闻
- 所有人都在说的共识性观点
- "某公司融了 X 亿"但不说意味着什么
- 正确但无用的分析

## 每条分析的格式
对每条选中的信息，输出：
```
### [序号] 原始标题
结论：一句话判断——不是"发生了什么"，而是"这意味着什么"
信号：量化证据——定价、数据、增速、措辞变化等
为什么重要：连接到更大的趋势
观察点：接下来盯什么——具体事件、数据、时间点
来源：源名称
链接：URL
```

## 原始数据
{items_text}

请严格按格式输出，选 5-10 条。宁缺毋滥。"""

    messages = [
        {"role": "system", "content": "你是阿宁日报的 AI 编辑，擅长从噪音中提取高价值信号。你的分析简洁有力，每句话都有信息增量。"},
        {"role": "user", "content": prompt},
    ]
    return call_ai(messages, temperature=0.3)


def ai_round2_synthesize(round1_output, all_items):
    prompt = f"""基于以下已筛选分析的条目，完成两件事：

1. **今日主线**：3-5 句话归纳今天的大图——跨源、跨领域找共同方向。不是列表，是一段连贯的分析。

2. **阿宁点评**：以个人编辑视角写 2-3 段：
   - 今天真正值得看的是什么
   - 噪音是什么（大家都在聊但其实没信息增量的）
   - 接下来一周盯什么

## 已筛选分析
{round1_output}

请输出格式：
```
## 今日主线
（3-5 句话）

## 阿宁点评
（2-3 段）
```"""

    messages = [
        {"role": "system", "content": "你是阿宁，一个有独立判断力的信息编辑。你的点评直接、有态度、不怕得罪人。你不说'值得关注'这种废话，你说具体该盯什么、为什么。"},
        {"role": "user", "content": prompt},
    ]
    return call_ai(messages, temperature=0.5)


# ============================================================================
# 降级输出
# ============================================================================

def generate_degraded_output(all_items):
    sections = {}
    for item in all_items:
        source = item["source"]
        if source not in sections:
            sections[source] = []
        sections[source].append(item)

    lines = ["## 今日主线\n（AI 分析暂不可用，以下为原始信息）\n"]
    for source, items in sections.items():
        lines.append(f"\n### {source}")
        for item in items[:8]:
            title = item["title"]
            url = item.get("url", "")
            extra = ""
            if item.get("prices"):
                extra = f" ({item['prices']})"
            elif item.get("score"):
                extra = f" ({item['score']})"
            elif item.get("stars"):
                extra = f" ({item['stars']} stars)"
            lines.append(f"- [{title}]({url}){extra}")

    return "\n".join(lines), ""


# ============================================================================
# 解析 AI 输出
# ============================================================================

def parse_round1_items(round1_text):
    # 去掉 ``` 代码块包裹
    text = re.sub(r'^```\w*\s*\n?', '', round1_text.strip())
    text = re.sub(r'\n?```\s*$', '', text)

    items = []
    current = {}

    def extract_value(line):
        for sep in ["：", ":"]:
            if sep in line:
                return line.split(sep, 1)[1].strip()
        return line.strip()

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### "):
            if current and current.get("title"):
                items.append(current)
            current = {"title": line.replace("### ", "").strip()}
        elif line.startswith("结论"):
            current["conclusion"] = extract_value(line)
        elif line.startswith("信号"):
            current["signal"] = extract_value(line)
        elif line.startswith("为什么重要"):
            current["why"] = extract_value(line)
        elif line.startswith("观察点"):
            current["watch"] = extract_value(line)
        elif line.startswith("来源"):
            current["source"] = extract_value(line)
        elif line.startswith("链接"):
            current["url"] = extract_value(line)
    if current and current.get("title"):
        items.append(current)
    return items


def parse_round2(round2_text):
    main_theme = ""
    commentary = ""
    current_section = None
    lines = round2_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if "今日主线" in stripped:
            current_section = "theme"
            continue
        elif "阿宁点评" in stripped:
            current_section = "commentary"
            continue
        elif stripped.startswith("```"):
            continue

        if current_section == "theme":
            main_theme += line + "\n"
        elif current_section == "commentary":
            commentary += line + "\n"

    return main_theme.strip(), commentary.strip()


# ============================================================================
# 主流程
# ============================================================================

def main():
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz).strftime("%Y-%m-%d")
    sys.stderr.write(f"=== 阿宁日报 V2 === {today} ===\n")

    # Step 1: 并行抓取 5 源
    sys.stderr.write("Step 1: 抓取数据...\n")
    all_items = []
    fetchers = [
        ("HN", fetch_hackernews),
        ("Polymarket", fetch_polymarket),
        ("GitHub", fetch_github),
        ("华尔街见闻", fetch_wallstreetcn),
        ("X", fetch_x_timeline),
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(fn): name for name, fn in fetchers}
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                items = future.result()
                sys.stderr.write(f"  [{name}] {len(items)} items\n")
                all_items.extend(items)
            except Exception as e:
                sys.stderr.write(f"  [{name}] FAILED: {e}\n")

    sys.stderr.write(f"Total: {len(all_items)} items\n")

    if not all_items:
        sys.stderr.write("No data fetched.\n")
        generator = HTMLGenerator()
        generator.generate_empty(today, "今日数据抓取失败")
        generator.update_index(today)
        sys.exit(1)

    # Step 2: AI Round 1
    sys.stderr.write("Step 2: AI Round 1 (筛选+分析)...\n")
    round1_output = ai_round1_filter_and_analyze(all_items)

    if not round1_output:
        sys.stderr.write("AI Round 1 failed, using degraded output\n")
        content, commentary = generate_degraded_output(all_items)
        analyzed_items = []
        main_theme = ""
    else:
        # Step 3: AI Round 2
        sys.stderr.write("Step 3: AI Round 2 (归纳+点评)...\n")
        round2_output = ai_round2_synthesize(round1_output, all_items)

        analyzed_items = parse_round1_items(round1_output)
        if round2_output:
            main_theme, commentary = parse_round2(round2_output)
        else:
            sys.stderr.write("AI Round 2 failed, skipping main theme + commentary\n")
            main_theme = ""
            commentary = ""
        content = round1_output

    sys.stderr.write(f"Selected items: {len(analyzed_items)}\n")

    # Step 4: 生成 HTML
    sys.stderr.write("Step 4: 生成 HTML...\n")
    generator = HTMLGenerator()
    html_path = generator.generate_daily_brief(
        date=today,
        analyzed_items=analyzed_items,
        main_theme=main_theme,
        commentary=commentary,
        raw_content=content,
    )
    generator.update_index(today)
    sys.stderr.write(f"Output: {html_path}\n")
    print(f"Daily brief generated: {html_path}")


if __name__ == "__main__":
    main()
