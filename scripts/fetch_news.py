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
from src.config import OUTPUT_DIR, AI_BASE_URL, AI_API_KEY, AI_MODEL, SITE_META, X_AUTH_TOKEN, X_CT0, RSS_FEEDS

# 服务器模式：读本地 X 缓存而非 API
X_CACHE_FILE = os.getenv("X_CACHE_FILE", "")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

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


def fetch_x_from_cache(limit=20):
    """从服务器本地 x_raw_cache.jsonl 读取精选账号数据"""
    if not X_CACHE_FILE or not os.path.exists(X_CACHE_FILE):
        sys.stderr.write(f"[X] Cache file not found: {X_CACHE_FILE}\n")
        return fetch_x_timeline(limit)

    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    try:
        with open(X_CACHE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                tweet = json.loads(line)
                fetched = tweet.get("fetched_at", "")
                if fetched:
                    try:
                        dt = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass
                author = tweet.get("author", "")
                title = tweet.get("title", "") or tweet.get("raw_text", "")[:150]
                url = tweet.get("url", "")
                heat = int(tweet.get("heat", 0) or 0)
                bucket = tweet.get("bucket", "")
                items.append({
                    "source": "X (Twitter)",
                    "title": f"@{author}: {title}",
                    "url": url,
                    "engagement": f"热度{heat}",
                    "x_bucket": bucket,
                    "x_heat": heat,
                })
        items.sort(key=lambda x: x.get("x_heat", 0), reverse=True)
        items = items[:limit]
    except Exception as e:
        sys.stderr.write(f"[X] Cache read error: {e}\n")
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


def fetch_rss(limit=10):
    """抓取 RSS 订阅源，取最近 24h 内的文章"""
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    def fetch_single_feed(feed):
        feed_items = []
        try:
            resp = requests.get(feed["url"], headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.content, "xml")
            if not soup.find(["item", "entry"]):
                soup = BeautifulSoup(resp.content, "html.parser")

            for entry in soup.find_all(["item", "entry"])[:5]:
                title_el = entry.find("title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                link_el = entry.find("link")
                if link_el:
                    url = link_el.get("href") or link_el.get_text(strip=True)
                else:
                    url = ""

                # 解析发布时间
                pub_el = entry.find(["pubDate", "published", "updated"])
                if pub_el:
                    from email.utils import parsedate_to_datetime
                    try:
                        pub_text = pub_el.get_text(strip=True)
                        if "T" in pub_text:
                            dt = datetime.fromisoformat(pub_text.replace("Z", "+00:00"))
                        else:
                            dt = parsedate_to_datetime(pub_text)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass

                # 摘要
                desc_el = entry.find(["description", "summary", "content"])
                desc = ""
                if desc_el:
                    desc_text = desc_el.get_text(strip=True)
                    desc = desc_text[:200] if desc_text else ""

                feed_items.append({
                    "source": f"RSS:{feed['name']}",
                    "title": f"[{feed['name']}] {title}",
                    "url": url,
                    "summary": desc,
                })
        except Exception as e:
            sys.stderr.write(f"[RSS:{feed['name']}] Error: {e}\n")
        return feed_items

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_single_feed, f): f for f in RSS_FEEDS}
        for future in concurrent.futures.as_completed(futures):
            try:
                feed_items = future.result()
                items.extend(feed_items)
            except Exception:
                pass

    return items[:limit]


def fetch_reddit(limit=10):
    """抓取 Reddit AI 相关子版块热门帖"""
    items = []
    subs = ["LocalLLaMA", "ChatGPT", "MachineLearning"]
    for sub in subs:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                headers={"User-Agent": "morning-brief/1.0"},
                timeout=10,
            )
            data = resp.json()
            for post in data.get("data", {}).get("children", []):
                d = post.get("data", {})
                if d.get("stickied"):
                    continue
                score = d.get("score", 0)
                if score < 50:
                    continue
                title = d.get("title", "")
                url = d.get("url", "")
                if url.startswith("/r/"):
                    url = f"https://www.reddit.com{url}"
                selftext = (d.get("selftext", "") or "")[:200]
                items.append({
                    "source": f"Reddit:r/{sub}",
                    "title": title,
                    "url": url,
                    "score": f"{score} upvotes",
                    "summary": selftext,
                })
        except Exception as e:
            sys.stderr.write(f"[Reddit:r/{sub}] Error: {e}\n")
    items.sort(key=lambda x: int(x.get("score", "0").split()[0]), reverse=True)
    return items[:limit]


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
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        sys.stderr.write(f"[AI] Error: {e}\n")
        return None


def _format_items_text(all_items):
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
        if item.get("summary"):
            line += f" | {item['summary'][:100]}"
        if item.get("url"):
            line += f" | {item['url']}"
        items_text += line + "\n"
    return items_text


FEW_SHOT_GOOD = """### [12] 板块: 宏观地缘
美国衰退定价跳到 38%
结论：不是恐慌，是关税冲击消化完后的"慢衰退"共识，企业开始推迟招聘。
信号：Polymarket Yes 38%（$12.3M），降息 3 次以上的合约从 45% 降到 31%。
为什么重要：过 40% 企业就开始砍预算，你定投的纳指和标普要做好回撤准备。
观察点：盯 4 月非农和初领失业金，连续两周 > 25 万则衰退定价可能破 50%。"""

FEW_SHOT_BAD = """### 不合格的分析（不要写成这样）
结论：OpenAI 发布了 GPT-5。  ← 陈述事实不是判断
信号：这是一个重大进展。  ← 没数字
为什么重要：AI 将改变世界。  ← 正确但无用
观察点：值得持续关注。  ← 废话"""


def _load_recent_titles(days=3):
    try:
        if not os.path.exists(WATCHPOINTS_FILE):
            return []
        all_wp = json.loads(open(WATCHPOINTS_FILE, encoding="utf-8").read())
        cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [wp["title"] for wp in all_wp if wp.get("date", "") >= cutoff]
    except Exception:
        return []


def _recent_titles_block():
    titles = _load_recent_titles()
    if not titles:
        return ""
    titles_list = "\n".join(f"- {t}" for t in titles)
    return f"""## 去重要求（重要！）
以下是最近 3 天已经分析过的条目，不要重复选择相同话题，除非今天有重大新进展：
{titles_list}"""


def ai_round1_filter_and_analyze(all_items):
    items_text = _format_items_text(all_items)

    prompt = f"""你是阿宁日报的编辑。从以下 {len(all_items)} 条原始信息中，按板块选出最有价值的条目。

## 读者画像

阿宁，30 岁，广州，母婴电商创业者（抖音+小红书+微信社群），同时是：
- AI 重度用户：每天用 Claude/Cursor/各种 agent 工具干活
- 指数投资者：定投纳指、标普、沪深 300，持有黄金
- 关注健康优化（补剂、睡眠）

他刷 X 和 HN 已经知道大新闻了。他要你告诉他的是：漏掉了什么、没想透什么、不同领域之间有什么连接。

## 6 个板块（每个板块选 0-2 条，没有就跳过）

1. **AI工程** — prompt 技巧、agent 架构、MCP、开源工具、本地模型
2. **AI行业** — 模型发布、产品更新、融资、重大合作
3. **商业/电商** — 电商运营、流量玩法、平台规则、商业模式
4. **宏观/金融** — 市场异动、地缘政治、通胀、利率、预测市场
5. **开发者/开源** — GitHub 热门项目、开发工具、技术趋势
6. **其他值得看的** — 健康、科学、不属于以上但确实重要的

## 输出格式（8-10 条，每条都详细分析）

```
### [原始序号] 板块: 板块名
中文标题
结论：一句话判断。说人话，别端着。
信号：原始数据里的数字。不要编造。
为什么重要：跟阿宁有什么关系，1-2 句。
观察点：接下来盯什么，具体到事件/数据/时间。
来源：源名称
链接：URL
```

## 写作风格——说人话

- 像聪明朋友在微信上跟你说，不像分析师写报告
- "这事说白了就是……" 比 "这一事件的深层含义在于……" 好
- 有态度，敢下判断，别两边讨好
- 结论要短，一句话能说清就不要两句

## 准入标准
1. 改变判断——看完想法不一样了
2. 有数字——不是"可能会"，是"已经到了多少"
3. 跨领域连接——A 的事对 B 意味着什么
4. 时效性——今天看有用，下周就没用了

## 不要选的
- 刷 5 分钟 X 就知道的共识新闻
- 没数据的泛泛而谈
- 产品发布公告（除非改变格局）
- 融资新闻（除非金额本身是信号）

## 合格示例
{FEW_SHOT_GOOD}

## 不合格示例
{FEW_SHOT_BAD}

## 源多样性（重要！）
每个源最多 2 条。覆盖至少 4 个不同源。

## 原始数据
{items_text}

{_recent_titles_block()}

宁缺毋滥。8-10 条，每条都详细分析。标题必须中文。"""

    messages = [
        {"role": "system", "content": "你是阿宁的信息助理。说人话，别端着。规则：1) 每句话有信息量，废话删掉；2) 只用原始数据里的数字，不编造；3) 写得像朋友聊天，不像写报告；4) 所有标题用中文。"},
        {"role": "user", "content": prompt},
    ]
    return call_ai(messages, temperature=0.4)


def ai_round2_synthesize(round1_output, all_items):
    prompt = f"""基于以下已筛选的条目，写两部分。

## 1. 今日主线（2-3 段，写长写深）

把今天这些信息串成一个故事。不是"今天 AI 有新闻、金融有动向"这种分类清单，而是找到它们之间的共同方向和底层逻辑。

写 2-3 段，每段 2-3 句。第一段点出今天最核心的一条线索，第二段串联具体条目佐证，第三段给出一句可操作的判断。每句话都要有信息量，不许凑字数。

好的（照这个水平写，可以更长）：
"今天最核心的一条，不是"AI 又有新模型"，而是大家都开始从拼概念，转去拼"能不能长期跑、能不能赚钱、能不能接真实数据"。记忆层、agent 调度层、开源企业栈在补基础设施；邮件、前端性能、小程序式工具在补最后一公里；小米利润和港股平台反弹，则是在提醒市场：能活着把效率做出来的公司，估值会重新拿回来。

说白了，市场现在奖赏的不是最会讲故事的人，而是最会把系统拧顺的人。无论你做 AI、电商还是投资，接下来都别再盯"哪个最强"，要盯"哪个能复用、能落地、能形成经营杠杆"。"

差的：
"今天科技领域有多个重要进展，金融市场也有新动向。" ← 废话

每 1-2 句分一段，方便手机阅读。

## 2. 阿宁点评

你是阿宁，一个有主见的人，不是播音员。写三段：

**今天值得花时间看的：** 挑 2-3 条最被低估的，说清楚为什么。写得像跟朋友说"这条你别错过，因为……"

**可以跳过的：** 大家都在聊但没啥新信息的。敢点名，别怂。

**下周盯这几个：** 2-3 个具体的事——某个日期、某个数据、某个人的决定。不要"持续关注 AI 发展"这种废话。尽量跟阿宁的业务挂钩（电商、AI 工具、投资）。

## 已筛选分析
{round1_output}

直接输出，不用 ``` 包裹：
## 今日主线
（内容）

## 阿宁点评
（内容）"""

    messages = [
        {"role": "system", "content": '你是阿宁，30 岁，做母婴电商也搞 AI。说话直接、有态度，像跟哥们聊天。三个原则：1) 有立场，不和稀泥；2) 说具体的，"盯下周四的 CPI"比"关注通胀"有用一万倍；3) 敢说某条热门新闻是噪音。'},
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
        for item in items[:5]:
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

def parse_round1_items(round1_text, all_items=None):
    # 去掉 ``` 代码块包裹
    text = re.sub(r'^```\w*\s*\n?', '', round1_text.strip())
    text = re.sub(r'\n?```\s*$', '', text)

    items = []
    current = {}
    in_quick = False  # 是否在"速览"区域

    def extract_value(line):
        for sep in ["：", ":"]:
            if sep in line:
                return line.split(sep, 1)[1].strip()
        return line.strip()

    def resolve_source(title_line):
        idx_match = re.match(r'\[(\d+)\]', title_line)
        source, url = "", ""
        if idx_match and all_items:
            idx = int(idx_match.group(1))
            if 0 <= idx < len(all_items):
                source = all_items[idx].get("source", "")
                url = all_items[idx].get("url", "")
        return source, url

    for line in text.split("\n"):
        line = line.strip()

        # 检测"速览"分界
        if re.match(r'^##\s*速览', line):
            if current and current.get("title"):
                items.append(current)
                current = {}
            in_quick = True
            continue

        if in_quick:
            # 速览格式: - [序号] 板块名 | 中文标题 — 一句话
            m = re.match(r'^-\s*\[(\d+)\]\s*(.+?)\s*[|｜]\s*(.+?)\s*[—–-]\s*(.+?)(?:\s*来源[：:](.+?))?(?:\s*[|｜]\s*链接[：:](.+))?$', line)
            if m:
                idx = int(m.group(1))
                category = m.group(2).strip()
                title = m.group(3).strip()
                summary = m.group(4).strip()
                source, url = "", ""
                if all_items and 0 <= idx < len(all_items):
                    source = all_items[idx].get("source", "")
                    url = all_items[idx].get("url", "")
                if m.group(5):
                    source = source or m.group(5).strip()
                if m.group(6):
                    url = url or m.group(6).strip()
                items.append({
                    "title": title, "source": source, "url": url,
                    "category": category, "tier": 2,
                    "conclusion": summary,
                })
            continue

        # 第一梯队格式
        if line.startswith("### "):
            if current and current.get("title"):
                items.append(current)
            header = line.replace("### ", "").strip()
            source, url = resolve_source(header)
            # 提取板块
            category = ""
            cat_match = re.search(r'板块[：:]\s*(\S+)', header)
            if cat_match:
                category = cat_match.group(1)
            current = {"source": source, "url": url, "category": category, "tier": 1}
        elif not current.get("title") and line and not line.startswith(("结论", "信号", "为什么", "观察点", "来源", "链接")):
            # 标题行（板块行之后的第一个非字段行）
            if current.get("tier") == 1 and "category" in current:
                current["title"] = re.sub(r'^\s*\[\d+\]\s*', '', line).strip()
        elif line.startswith("结论"):
            current["conclusion"] = extract_value(line)
        elif line.startswith("信号"):
            current["signal"] = extract_value(line)
        elif line.startswith("为什么重要"):
            current["why"] = extract_value(line)
        elif line.startswith("观察点"):
            current["watch"] = extract_value(line)
        elif line.startswith("来源"):
            if not current.get("source"):
                current["source"] = extract_value(line)
        elif line.startswith("链接"):
            if not current.get("url"):
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
# 观察点追踪
# ============================================================================

WATCHPOINTS_FILE = os.path.join(OUTPUT_DIR, "watchpoints.json")


def load_watchpoints(days=14):
    if not os.path.exists(WATCHPOINTS_FILE):
        return []
    try:
        all_wp = json.loads(open(WATCHPOINTS_FILE, encoding="utf-8").read())
        cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [wp for wp in all_wp if wp.get("date", "") >= cutoff and wp.get("status") == "open"]
    except Exception:
        return []


def save_watchpoints(date, analyzed_items):
    existing = []
    if os.path.exists(WATCHPOINTS_FILE):
        try:
            existing = json.loads(open(WATCHPOINTS_FILE, encoding="utf-8").read())
        except Exception:
            existing = []

    existing_watches = {wp.get("watch", "") for wp in existing}
    for item in analyzed_items:
        watch = item.get("watch", "")
        if not watch or watch in existing_watches:
            continue
        existing_watches.add(watch)
        existing.append({
            "date": date,
            "title": re.sub(r'^\s*\[\d+\]\s*', '', item.get("title", "")),
            "watch": watch,
            "source": item.get("source", ""),
            "status": "open",
        })

    # 只保留最近 30 天
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=30)).strftime("%Y-%m-%d")
    existing = [wp for wp in existing if wp.get("date", "") >= cutoff]

    open(WATCHPOINTS_FILE, "w", encoding="utf-8").write(json.dumps(existing, ensure_ascii=False, indent=2))


def ai_round3_review_watchpoints(open_watchpoints, all_items):
    if not open_watchpoints:
        return None

    wp_text = ""
    for i, wp in enumerate(open_watchpoints):
        wp_text += f"[W{i}] ({wp['date']}) {wp['title']}\n  观察点：{wp['watch']}\n\n"

    items_summary = ""
    for item in all_items[:50]:
        items_summary += f"- [{item['source']}] {item['title']}\n"

    prompt = f"""你面前有两组数据：

## 过去的观察点（之前日报说"接下来盯什么"）
{wp_text}

## 今天的原始信息
{items_summary}

对照今天的信息，判断哪些观察点已经有了结果。对每个有结果的观察点，输出：

```
### [W序号] 原始观察点标题
状态：✅ 验证 / ❌ 推翻 / ⏳ 进展中
回顾：1-2 句话说明发生了什么，与原始观察点的预测对比
```

规则：
- 只输出有明确结果或明显进展的观察点，没有新信息的跳过
- "验证"= 观察点预测的事情发生了或趋势确认
- "推翻"= 观察点预测的方向错了
- "进展中"= 有相关新信息但尚未最终确认
- 如果今天的数据跟所有观察点都无关，输出"无更新"
"""

    messages = [
        {"role": "system", "content": "你是阿宁日报的追踪编辑。你的工作是诚实地回顾过去的判断——对了就说对了，错了就说错了，不要找借口。"},
        {"role": "user", "content": prompt},
    ]
    return call_ai(messages, temperature=0.2)


def parse_watchpoint_reviews(review_text, open_watchpoints):
    if not review_text or "无更新" in review_text:
        return []

    reviews = []
    current = {}
    for line in review_text.split("\n"):
        line = line.strip()
        if line.startswith("### [W"):
            if current and current.get("review"):
                reviews.append(current)
            idx_match = re.match(r'###\s*\[W(\d+)\]', line)
            idx = int(idx_match.group(1)) if idx_match else -1
            wp = open_watchpoints[idx] if 0 <= idx < len(open_watchpoints) else {}
            current = {"title": wp.get("title", ""), "date": wp.get("date", ""), "watch": wp.get("watch", ""), "idx": idx}
        elif line.startswith("状态"):
            status_text = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            if "验证" in status_text or "✅" in status_text:
                current["status"] = "verified"
                current["status_label"] = "✅ 验证"
            elif "推翻" in status_text or "❌" in status_text:
                current["status"] = "invalidated"
                current["status_label"] = "❌ 推翻"
            else:
                current["status"] = "progress"
                current["status_label"] = "⏳ 进展中"
        elif line.startswith("回顾"):
            current["review"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()

    if current and current.get("review"):
        reviews.append(current)
    return reviews


def update_watchpoint_status(reviews, open_watchpoints):
    if not os.path.exists(WATCHPOINTS_FILE):
        return
    try:
        all_wp = json.loads(open(WATCHPOINTS_FILE, encoding="utf-8").read())
    except Exception:
        return

    for rev in reviews:
        idx = rev.get("idx", -1)
        if 0 <= idx < len(open_watchpoints):
            wp = open_watchpoints[idx]
            for stored in all_wp:
                if stored.get("date") == wp.get("date") and stored.get("watch") == wp.get("watch") and stored.get("status") == "open":
                    if rev["status"] in ("verified", "invalidated"):
                        stored["status"] = rev["status"]
                    break

    open(WATCHPOINTS_FILE, "w", encoding="utf-8").write(json.dumps(all_wp, ensure_ascii=False, indent=2))


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
        ("X", fetch_x_from_cache if X_CACHE_FILE else fetch_x_timeline),
        ("RSS", fetch_rss),
        ("Reddit", fetch_reddit),
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
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

        analyzed_items = parse_round1_items(round1_output, all_items)
        if round2_output:
            main_theme, commentary = parse_round2(round2_output)
        else:
            sys.stderr.write("AI Round 2 failed, skipping main theme + commentary\n")
            main_theme = ""
            commentary = ""
        content = round1_output

    sys.stderr.write(f"Selected items: {len(analyzed_items)}\n")

    # Step 4: 观察点追踪
    watchpoint_reviews = []
    open_watchpoints = load_watchpoints()
    if open_watchpoints and AI_API_KEY:
        sys.stderr.write(f"Step 4: 观察点回顾 ({len(open_watchpoints)} open)...\n")
        review_output = ai_round3_review_watchpoints(open_watchpoints, all_items)
        if review_output:
            watchpoint_reviews = parse_watchpoint_reviews(review_output, open_watchpoints)
            update_watchpoint_status(watchpoint_reviews, open_watchpoints)
            sys.stderr.write(f"  Watchpoint updates: {len(watchpoint_reviews)}\n")

    if analyzed_items:
        save_watchpoints(today, analyzed_items)

    # Step 5: 更新 JSON
    sys.stderr.write("Step 5: 更新 data.json...\n")
    data_path = save_daily_json(today, analyzed_items, main_theme, commentary, watchpoint_reviews)
    sys.stderr.write(f"Output: {data_path}\n")
    print(f"Daily brief saved: {data_path}")

    # Step 6: Telegram 推送
    if TG_BOT_TOKEN and TG_CHAT_ID:
        sys.stderr.write("Step 6: 发送 Telegram...\n")
        try:
            send_telegram(today, main_theme, analyzed_items, commentary, watchpoint_reviews)
            sys.stderr.write("  Telegram sent.\n")
        except Exception as e:
            sys.stderr.write(f"  Telegram failed: {e}\n")


DATA_JSON = os.path.join(OUTPUT_DIR, "data.json")


def save_daily_json(date, items, main_theme, commentary, watchpoint_reviews):
    entry = {
        "date": date,
        "main_theme": main_theme,
        "commentary": commentary,
        "items": [
            {
                "title": re.sub(r'^\s*\[\d+\]\s*', '', item.get("title", "")),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "conclusion": item.get("conclusion", ""),
                "signal": item.get("signal", ""),
                "why": item.get("why", ""),
                "watch": item.get("watch", ""),
                "category": item.get("category", ""),
                "tier": item.get("tier", 1),
            }
            for item in items
        ],
        "watchpoint_reviews": [
            {
                "watch": wp.get("watch", ""),
                "status_label": wp.get("status_label", ""),
                "review": wp.get("review", ""),
                "date": wp.get("date", ""),
            }
            for wp in (watchpoint_reviews or [])
        ],
    }

    data = []
    if os.path.exists(DATA_JSON):
        try:
            data = json.loads(open(DATA_JSON, encoding="utf-8").read())
        except Exception:
            data = []

    data = [d for d in data if d.get("date") != date]
    data.insert(0, entry)
    data = data[:90]

    open(DATA_JSON, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
    return DATA_JSON


def _tg_escape(text):
    for ch in ("&", "<", ">"):
        text = text.replace(ch, {"&": "&amp;", "<": "&lt;", ">": "&gt;"}[ch])
    return text


def _md_to_tg_html(text):
    text = _tg_escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    return text


def _make_short_title(item):
    conclusion = item.get("conclusion", "")
    if conclusion:
        t = re.split(r'[。；;，]', conclusion)[0].strip()
        if len(t) >= 8:
            return t[:60]
    title = re.sub(r'^\s*\[\d+\]\s*', '', item.get("title", ""))
    title = re.sub(r'^@\w+:\s*', '', title)
    return title[:60]


def send_telegram(date, main_theme, items, commentary, watchpoint_reviews):
    CATEGORY_ICONS = {
        "AI工程": "🤖", "AI行业": "📡", "商业/电商": "🛒",
        "宏观/金融": "🌍", "开发者/开源": "⚙️", "其他值得看的": "💡",
    }

    parts = []

    if main_theme:
        parts.append(_md_to_tg_html(main_theme.strip()))
        parts.append("")

    tier1 = [i for i in items if i.get("tier", 1) == 1]
    tier2 = [i for i in items if i.get("tier") == 2]

    # 按板块分组
    from collections import OrderedDict
    groups = OrderedDict()
    for item in tier1[:6]:
        cat = item.get("category", "其他")
        groups.setdefault(cat, []).append(item)

    for cat, cat_items in groups.items():
        icon = CATEGORY_ICONS.get(cat, "📌")
        parts.append(f"<b>{icon} {_tg_escape(cat)}</b>")
        for item in cat_items:
            title = re.sub(r'^\s*\[\d+\]\s*', '', item.get("title", ""))
            title = re.sub(r'^@\w+:\s*', '', title)[:50]
            url = item.get("url", "")
            conclusion = item.get("conclusion", "")
            # 标题带链接
            if url:
                line = f"· <a href=\"{_tg_escape(url)}\">{_tg_escape(title)}</a>"
            else:
                line = f"· {_tg_escape(title)}"
            # 结论用 " — " 接在后面，不重复标题
            if conclusion and conclusion[:10] != title[:10]:
                short = conclusion[:80] + ("…" if len(conclusion) > 80 else "")
                line += f"\n  {_tg_escape(short)}"
            parts.append(line)
        parts.append("")

    parts.append(f"<a href=\"https://yining365.github.io/daily-news/\">→ 完整版</a>")

    message = "\n".join(parts)
    if len(message) > 4000:
        message = message[:3990] + "\n..."
    _send_tg_message(message)


def _send_tg_message(message):
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API error: {result}")


# ============================================================================
# 周报
# ============================================================================

def weekly_summary():
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz)
    today_str = today.strftime("%Y-%m-%d")
    sys.stderr.write(f"=== 阿宁周报 === {today_str} ===\n")

    # 读取本周数据（周一~周五）
    data = []
    if os.path.exists(DATA_JSON):
        try:
            data = json.loads(open(DATA_JSON, encoding="utf-8").read())
        except Exception:
            pass

    # 取最近 7 天的日报（排除周报本身）
    cutoff = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    week_entries = [d for d in data if d.get("date", "") >= cutoff and d.get("type") != "weekly"]

    if not week_entries:
        sys.stderr.write("No daily entries found for this week.\n")
        sys.exit(1)

    # 收集所有 items 和主线
    all_items_text = ""
    for entry in week_entries:
        date = entry.get("date", "")
        all_items_text += f"\n## {date}\n"
        if entry.get("main_theme"):
            all_items_text += f"主线：{entry['main_theme'][:200]}\n"
        for it in entry.get("items", []):
            cat = it.get("category", "")
            title = it.get("title", "")
            conclusion = it.get("conclusion", "")
            all_items_text += f"- [{cat}] {title} — {conclusion}\n"

    date_range_start = week_entries[-1].get("date", "")
    date_range_end = week_entries[0].get("date", "")
    range_label = f"{date_range_start.split('-', 1)[1].replace('-', '/')} ~ {date_range_end.split('-', 1)[1].replace('-', '/')}"

    sys.stderr.write(f"Week range: {range_label}, {len(week_entries)} days\n")

    # AI 生成周报
    prompt = f"""回顾这一周（{range_label}）的阿宁日报，挑出 5 条最值得记住的。

选择标准：
- 哪些判断被验证了，或者被推翻了
- 哪些趋势在加速，回头看更清楚了
- 哪些你当时没在意但现在回头看很重要
- 对阿宁（母婴电商创业者 + AI 用户 + 指数投资者）下周有什么影响

## 输出格式

### 本周回顾
（2-3 段总结，像周末跟朋友复盘这一周。说人话，有态度。）

### 本周 5 条
1. **标题** — 一句话说清楚为什么值得记住
2. ...
3. ...
4. ...
5. ...

## 本周日报内容
{all_items_text}"""

    messages = [
        {"role": "system", "content": "你是阿宁，周末复盘这一周。说话直接，像跟朋友聊天。不要写成总结报告，要写成\"这周我想明白了几件事\"。"},
        {"role": "user", "content": prompt},
    ]

    sys.stderr.write("Generating weekly summary...\n")
    output = call_ai(messages, temperature=0.5)

    if not output:
        sys.stderr.write("AI failed for weekly summary.\n")
        sys.exit(1)

    # 解析
    review_text = ""
    top5 = []
    current_section = None
    for line in output.split("\n"):
        stripped = line.strip()
        if "本周回顾" in stripped and stripped.startswith("#"):
            current_section = "review"
            continue
        elif "本周" in stripped and "5" in stripped and stripped.startswith("#"):
            current_section = "top5"
            continue

        if current_section == "review":
            review_text += line + "\n"
        elif current_section == "top5":
            m = re.match(r'^\d+\.\s*\*\*(.+?)\*\*\s*[—–-]\s*(.+)', stripped)
            if m:
                top5.append({"title": m.group(1).strip(), "conclusion": m.group(2).strip()})
            elif re.match(r'^\d+\.\s*(.+?)\s*[—–-]\s*(.+)', stripped):
                m2 = re.match(r'^\d+\.\s*(.+?)\s*[—–-]\s*(.+)', stripped)
                top5.append({"title": m2.group(1).strip(), "conclusion": m2.group(2).strip()})

    review_text = review_text.strip()
    sys.stderr.write(f"Parsed: review={len(review_text)} chars, top5={len(top5)} items\n")

    # 保存到 data.json
    entry = {
        "date": today_str,
        "type": "weekly",
        "date_range": range_label,
        "main_theme": review_text,
        "commentary": "",
        "items": [
            {"title": it["title"], "conclusion": it["conclusion"], "source": "", "url": "",
             "signal": "", "why": "", "watch": "", "category": "", "tier": 1}
            for it in top5
        ],
        "watchpoint_reviews": [],
    }

    data = [d for d in data if not (d.get("date") == today_str and d.get("type") == "weekly")]
    data.insert(0, entry)
    data = data[:90]
    open(DATA_JSON, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
    sys.stderr.write(f"Saved weekly to {DATA_JSON}\n")

    # Telegram 推送
    if TG_BOT_TOKEN and TG_CHAT_ID:
        sys.stderr.write("Sending Telegram...\n")
        parts = [f"<b>📅 阿宁周报 · {_tg_escape(range_label)}</b>", ""]
        if review_text:
            parts.append(_md_to_tg_html(review_text))
            parts.append("")
        if top5:
            parts.append("<b>🔑 本周 5 条</b>")
            for i, it in enumerate(top5[:5], 1):
                parts.append(f"{i}. <b>{_tg_escape(it['title'])}</b> — {_tg_escape(it['conclusion'])}")
            parts.append("")
        parts.append(f"<a href=\"https://yining365.github.io/daily-news/\">→ 完整版</a>")
        message = "\n".join(parts)
        if len(message) > 4000:
            message = message[:3990] + "\n..."
        try:
            _send_tg_message(message)
            sys.stderr.write("Telegram sent.\n")
        except Exception as e:
            sys.stderr.write(f"Telegram failed: {e}\n")

    sys.stderr.write("Weekly summary done.\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "weekly":
        weekly_summary()
    else:
        main()
