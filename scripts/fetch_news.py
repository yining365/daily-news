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


def fetch_aihot_brief():
    """从 aihot.virxact.com 拿当天日报，作为外部参考视角喂给 round 1 LLM。
    返回一段 markdown 文本，失败返回空串。
    """
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    try:
        resp = requests.get("https://aihot.virxact.com/api/public/daily",
                            headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        d = resp.json()
        parts = []
        lead = d.get("lead") or {}
        if lead.get("title"):
            parts.append(f"### aihot 今日主线：{lead['title']}")
        if lead.get("leadParagraph"):
            lp = lead["leadParagraph"].strip()
            if len(lp) > 400:
                lp = lp[:398] + "…"
            parts.append(lp)
        for sec in d.get("sections", []):
            label = sec.get("label", "")
            its = sec.get("items", [])
            if not its:
                continue
            parts.append(f"\n**{label}**")
            for it in its[:3]:
                title = (it.get("title") or "").strip()
                if title:
                    parts.append(f"- {title}")
        flashes = d.get("flashes", []) or []
        if flashes:
            parts.append("\n**快讯**")
            for f in flashes[:5]:
                t = (f.get("title") or "").strip()
                if t:
                    parts.append(f"- {t}")
        return "\n".join(parts)
    except Exception as e:
        sys.stderr.write(f"[aihot_brief] Error: {e}\n")
        return ""


def fetch_aihot(limit=60):
    """从 aihot.virxact.com 拉过去 24h 的精选 AI 动态。
    数据已经 LLM 摘要+分类，直接当数据源喂进主筛选池。
    """
    items = []
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    try:
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        import urllib.parse
        url = "https://aihot.virxact.com/api/public/items?" + urllib.parse.urlencode({
            "mode": "selected",
            "take": str(min(limit, 100)),
            "since": since,
        })
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for it in data.get("items", []):
            cat = it.get("category") or "ai"
            title = it.get("title") or ""
            if not title:
                continue
            items.append({
                "source": f"aihot:{cat}",
                "title": f"[{cat}] {title}",
                "url": it.get("url") or "",
                "summary": it.get("summary") or "",
            })
    except Exception as e:
        sys.stderr.write(f"[aihot] Error: {e}\n")
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
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        sys.stderr.write(f"[AI] Error: {e}\n")
        return None


def _annotate_cross_source(all_items):
    """标题相似度粗聚簇：同一事件被多个源报道时，给条目加多源计数。
    只做信号标注不做合并，最终去留仍由 AI 决定。"""
    def tokens(title):
        words = re.findall(r'[a-zA-Z0-9]+', title.lower())
        han = re.findall(r'[一-鿿]', title)
        bigrams = {han[i] + han[i + 1] for i in range(len(han) - 1)}
        return set(words) | bigrams

    token_sets = [tokens(item.get("title", "")) for item in all_items]
    for i, item in enumerate(all_items):
        if not token_sets[i]:
            continue
        related_sources = {item["source"]}
        for j, other in enumerate(all_items):
            if i == j or not token_sets[j]:
                continue
            inter = len(token_sets[i] & token_sets[j])
            union = len(token_sets[i] | token_sets[j])
            if union and inter / union >= 0.4:
                related_sources.add(other["source"])
        if len(related_sources) > 1:
            item["cross_sources"] = sorted(related_sources)


def _format_items_text(all_items):
    items_text = ""
    for i, item in enumerate(all_items):
        line = f"[{i}] [{item['source']}] {item['title']}"
        if item.get("cross_sources"):
            line += f" | 多源信号: {len(item['cross_sources'])} 个源在报（{'/'.join(item['cross_sources'])}）"
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


FEW_SHOT_GOOD = """### [12] 行动线: 动钱
美国衰退定价跳到 38%
结论：不是恐慌，是关税冲击消化完后的"慢衰退"共识，企业开始推迟招聘。
信号：Polymarket Yes 38%（$12.3M），降息 3 次以上的合约从 45% 降到 31%。
so what：不用动仓位，定投规则内照跑；但这周别手痒加机动仓，等非农落地再说。
观察点：盯 4 月非农和初领失业金，连续两周 > 25 万则衰退定价可能破 50%。"""

FEW_SHOT_BAD = """### 不合格的分析（不要写成这样）
结论：OpenAI 发布了 GPT-5。  ← 陈述事实不是判断
信号：这是一个重大进展。  ← 没数字
so what：值得关注 AI 发展。  ← 不是动作，是废话
观察点：值得持续关注。  ← 废话"""


FEEDBACK_FILE = "/root/hermes/workspace/daily-news-feedback.jsonl"


def _feedback_block():
    """读取用户在飞书里的数字反馈（Hermes 记录），喂给筛选 prompt 做校准。"""
    try:
        if not os.path.exists(FEEDBACK_FILE):
            return ""
        useful, useless = [], []
        with open(FEEDBACK_FILE, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                title = (rec.get("title") or "").strip()
                if not title:
                    continue
                if rec.get("score") == 1:
                    useful.append(title)
                elif rec.get("score") == 0:
                    useless.append(title)
        if not useful and not useless:
            return ""
        lines = ["## 用户反馈校准（阿宁对历史条目的真实打分，选条时向「有用」靠拢）"]
        for t in useful[-8:]:
            lines.append(f"- 👍 有用：{t}")
        for t in useless[-8:]:
            lines.append(f"- 👎 废话：{t}")
        return "\n".join(lines)
    except Exception:
        return ""


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


def ai_round1_filter_and_analyze(all_items, aihot_brief=""):
    _annotate_cross_source(all_items)
    items_text = _format_items_text(all_items)
    if aihot_brief:
        aihot_ref_block = (
            "## 外部参考（aihot 今日 AI 日报概览）\n"
            "下面是另一家 AI 日报站点对今天的判断。仅作视野扩展和查漏，不要照搬它的标题/判断；\n"
            "你的筛选要独立，但如果它点出的主线你的原始数据里也有，注意别漏掉。\n\n"
            + aihot_brief
        )
    else:
        aihot_ref_block = ""

    prompt = f"""你是阿宁的决策情报员，不是新闻编辑。从以下 {len(all_items)} 条原始信息中，只挑出可能改变阿宁行动的条目。

## 第一性原理

信息的价值 = 改变行动的概率 × 那个行动的价值。阿宁刷 X 和 HN 已经知道大新闻了，共识新闻对他是零价值。你的唯一任务：找出会让他「做点什么或明确不做什么」的信息。

## 阿宁的三条行动线（每条信息必须落到其中一条，落不到就不选）

1. **工作流/技巧** — 他每天用 Claude Code/Codex/各种 agent 干活，跑着建站流水线和自动化 cron。什么工具/模型/开发流程的变化值得他迁移或试用？什么 prompt 技巧、agent 用法、窍门值得他今天就学着用？不必非到"换工具"级别，一个能立刻上手的技巧也算。
2. **动钱** — 他定投纳指、标普、沪深 300，持有黄金，有固定规则（基础额 10000，配比固定）。注意：他另有投资日报专线，这里只报「值得去看专线/警惕情绪化操作」级别的信号，不给操作指令。
3. **选品池** — 他在做产品工厂（海外小工具站），跑着需求雷达。什么变化会降低某类产品的门槛、打开某个新机会、或杀死某类产品？

极少数不落在三条线上但真正重大的（健康、重大范式变化），可标「其他」，一周最多一两次。

## 输出格式（0-5 条。今天没有就输出「今日无信号」四个字，不许硬凑）

```
### [原始序号] 行动线: 工作流技巧/动钱/选品池/其他
直接写中文标题，不要带"中文标题："前缀
结论：一句话判断。说人话，别端着。
信号：原始数据里的数字。不要编造。
so what：具体到"建议你做什么/不做什么"。必须是可执行的动作或明确的不动作，落到阿宁的真实工具链、仓位纪律或选品池。写不出具体动作的条目直接放弃。
观察点：必须写成可判伪的预测——指标 + 阈值 + 期限（如"7 月 25 日前纳指回撤是否超 5%"）。写不成这个格式就留空，不要写"持续关注 X"这类永远不会错的话。
来源：源名称
链接：URL
```

## 写作风格——说人话

- 像聪明朋友在微信上跟你说，不像分析师写报告
- "这事说白了就是……" 比 "这一事件的深层含义在于……" 好
- 有态度，敢下判断，别两边讨好
- 结论要短，一句话能说清就不要两句

## 准入标准（全部满足才能入选）
1. 能写出具体的 so what——答不出"所以呢"就不选
2. 有数字——不是"可能会"，是"已经到了多少"
3. 时效性——今天知道和下周知道有差别
4. 多源交叉优先——带"多源信号"标注的条目说明多个独立源同时在报；同一事件只出一条，优先选一手来源（官方公告、当事人原声），转发和二手解读放弃

## 不要选的
- 刷 5 分钟 X 就知道的共识新闻
- 没数据的泛泛而谈
- 产品发布公告（除非改变格局）
- 融资新闻（除非金额本身是信号）
- 纯宏观叙事（投资日报专线已覆盖，除非当天异动大到要提醒他管住手）

## 合格示例
{FEW_SHOT_GOOD}

## 不合格示例
{FEW_SHOT_BAD}

{_feedback_block()}

{aihot_ref_block}

## 原始数据
{items_text}

{_recent_titles_block()}

宁缺毋滥，0 条是合格答案。标题必须中文。"""

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

说白了，市场现在奖赏的不是最会讲故事的人，而是最会把系统拧顺的人。无论你做 AI 还是投资，接下来都别再盯"哪个最强"，要盯"哪个能复用、能落地、能形成经营杠杆"。"

差的：
"今天科技领域有多个重要进展，金融市场也有新动向。" ← 废话

每 1-2 句分一段，方便手机阅读。

## 2. 阿宁点评

你是阿宁，一个有主见的人，不是播音员。写三段：

**今天值得花时间看的：** 挑 2-3 条最被低估的，说清楚为什么。写得像跟朋友说"这条你别错过，因为……"

**可以跳过的：** 大家都在聊但没啥新信息的。敢点名，别怂。

**下周盯这几个：** 2-3 个具体的事——某个日期、某个数据、某个人的决定。不要"持续关注 AI 发展"这种废话。尽量跟阿宁的关注挂钩（AI 工具、投资、宏观）。

## 已筛选分析
{round1_output}

直接输出，不用 ``` 包裹：
## 今日主线
（内容）

## 阿宁点评
（内容）"""

    messages = [
        {"role": "system", "content": '你是阿宁，30 岁，AI 工程师 + 指数投资者。说话直接、有态度，像跟哥们聊天。三个原则：1) 有立场，不和稀泥；2) 说具体的，"盯下周四的 CPI"比"关注通胀"有用一万倍；3) 敢说某条热门新闻是噪音。'},
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

def _clean_generated_title(title):
    return re.sub(r"^\s*(?:中文标题|标题)\s*[：:]\s*", "", title or "").strip()


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
                title = _clean_generated_title(m.group(3))
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
            # 提取板块/行动线
            category = ""
            cat_match = re.search(r'(?:板块|行动线)[：:]\s*(\S+)', header)
            if cat_match:
                category = cat_match.group(1)
            current = {"source": source, "url": url, "category": category, "tier": 1}
        elif not current.get("title") and line and not line.lower().startswith(("结论", "信号", "为什么", "so what", "so：", "so:", "观察点", "来源", "链接")):
            # 标题行（板块行之后的第一个非字段行）
            if current.get("tier") == 1 and "category" in current:
                current["title"] = _clean_generated_title(re.sub(r'^\s*\[\d+\]\s*', '', line))
        elif line.startswith("结论"):
            current["conclusion"] = extract_value(line)
        elif line.startswith("信号"):
            current["signal"] = extract_value(line)
        elif line.startswith("为什么重要"):
            current["why"] = extract_value(line)
        elif line.lower().startswith("so what"):
            current["so_what"] = extract_value(line)
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

    # 过期机制：open 状态超过 14 天仍无结论的观察点自动关闭，防止 open 池无限膨胀
    expire_cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=14)).strftime("%Y-%m-%d")
    for wp in existing:
        if wp.get("status") == "open" and wp.get("date", "") < expire_cutoff:
            wp["status"] = "expired"

    existing_watches = {wp.get("watch", "") for wp in existing}
    for item in analyzed_items:
        if item.get("tier", 1) != 1:
            continue
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

规则（判定要严，这个结果会进公开的命中率统计）：
- 只输出有明确结果或明显进展的观察点，没有新信息的跳过
- "验证"= 观察点里写的指标确实触发了阈值，且在期限内。必须能指出今天数据里的具体证据
- "推翻"= 指标在期限内明确走向了反面，或期限已过阈值未触发
- "进展中"= 有相关新信息但阈值未触发、期限未到。拿不准一律算进展中，不算验证
- 观察点本身如果写得模糊（没有指标/阈值/期限），不许强行判验证，最多算进展中
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
    # aihot（精选主源）+ 华尔街见闻（金融）+ Polymarket（预测市场）+ RSS（杂源）
    # X：采集器凭证失效，主人决定暂不接入（2026-07-18）；恢复时把 fetch_x_from_cache 加回来即可
    # Reddit 已砍：服务器 IP 被 403 封禁（2026-07-18 实测 www/old 端点均不通）
    fetchers = [
        ("aihot", fetch_aihot),
        ("华尔街见闻", fetch_wallstreetcn),
        ("Polymarket", fetch_polymarket),
        ("RSS", fetch_rss),
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
        sys.exit(1)

    # Step 2: AI Round 1
    sys.stderr.write("Step 2: AI Round 1 (筛选+分析)...\n")
    aihot_brief = fetch_aihot_brief()
    if aihot_brief:
        sys.stderr.write(f"  [aihot brief] {len(aihot_brief)} chars\n")
    round1_output = ai_round1_filter_and_analyze(all_items, aihot_brief=aihot_brief)

    ai_failed = False
    if not round1_output:
        sys.stderr.write("AI Round 1 failed, using degraded output\n")
        ai_failed = True
        content, commentary = generate_degraded_output(all_items)
        analyzed_items = []
        main_theme = ""
    else:
        analyzed_items = parse_round1_items(round1_output, all_items)
        main_theme = ""
        commentary = ""
        if analyzed_items:
            # Step 3: AI Round 2
            sys.stderr.write("Step 3: AI Round 2 (归纳+点评)...\n")
            round2_output = ai_round2_synthesize(round1_output, all_items)
            if round2_output:
                main_theme, commentary = parse_round2(round2_output)
            else:
                sys.stderr.write("AI Round 2 failed, skipping main theme + commentary\n")
        else:
            sys.stderr.write("今日无信号，跳过 Round 2\n")
        content = round1_output

    sys.stderr.write(f"Selected items: {len(analyzed_items)}\n")

    # Step 4: 观察点追踪
    watchpoint_reviews = []
    open_watchpoints = load_watchpoints()
    # 只回顾最近的 30 条，避免 open 池过大稀释回顾质量（W 序号需与后续解析共用同一列表）
    if len(open_watchpoints) > 30:
        open_watchpoints = sorted(open_watchpoints, key=lambda w: w.get("date", ""), reverse=True)[:30]
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

    # Step 6: 写入 Hermes 投递缓存（Telegram 由 Hermes 接管）
    sys.stderr.write("Step 6: 写入 Hermes 投递缓存...\n")
    if ai_failed:
        # AI 挂了不等于今天无信号，宁可不发也不发假的空日报
        sys.stderr.write("  AI failed — skip Hermes cache to avoid a fake empty daily.\n")
    else:
        try:
            write_daily_hermes_cache(today, main_theme, analyzed_items, commentary, watchpoint_reviews, total_count=len(all_items))
            sys.stderr.write("  Hermes message queued for cron delivery.\n")
        except Exception as e:
            sys.stderr.write(f"  Hermes cache write failed: {e}\n")


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
                "so_what": item.get("so_what", ""),
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
        "AI工程": "🤖", "AI行业": "📡",
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
    message = message.replace("**", "")
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




def _fetch_guangzhou_weather():
    """广州海珠区今日天气：温度区间、体感、降雨概率。失败返回 None。"""
    import urllib.request, urllib.parse
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode({
            "latitude": "23.0833",
            "longitude": "113.3172",
            "timezone": "Asia/Shanghai",
            "current": "apparent_temperature,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": "1",
        })
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        sys.stderr.write(f"  weather fetch failed: {e}\n")
        return None
    try:
        cur = payload.get("current", {})
        daily = payload.get("daily", {})
        tmax = round(daily["temperature_2m_max"][0])
        tmin = round(daily["temperature_2m_min"][0])
        feels = round(cur["apparent_temperature"]) if cur.get("apparent_temperature") is not None else None
        prob = daily.get("precipitation_probability_max", [None])[0]
        wcode = cur.get("weather_code", 0) or 0
        # 简化天气符号
        icon = "☀️"
        if wcode in (1, 2): icon = "🌤"
        elif wcode == 3: icon = "☁️"
        elif 45 <= wcode <= 48: icon = "🌫"
        elif 51 <= wcode <= 67: icon = "🌧"
        elif 71 <= wcode <= 77: icon = "🌨"
        elif 80 <= wcode <= 82: icon = "🌧"
        elif 95 <= wcode <= 99: icon = "⛈"
        # 出门建议
        if prob is None:
            advice = "降雨概率暂无可靠数据"
        elif prob >= 70:
            advice = "带伞，雨概率高"
        elif prob >= 40:
            advice = "带把伞稳一点"
        elif tmax >= 32:
            advice = "高温，注意防晒补水"
        elif tmin <= 12:
            advice = "偏冷，加件外套"
        else:
            advice = "天气还行"
        feels_str = f"体感{feels}℃" if feels is not None else "体感暂无可靠数据"
        prob_str = f"降雨概率{prob}%" if prob is not None else "降雨概率暂无可靠数据"
        return f"{icon} 广州天气：{tmin}-{tmax}℃，{feels_str}，{prob_str}。出门建议：{advice}。"
    except Exception as e:
        sys.stderr.write(f"  weather parse failed: {e}\n")
        return None


ACTION_LINE_ORDER = [
    (("工作流", "技巧", "改工作流"), "🔧 工作流/技巧"),
    (("动钱",), "💰 动钱"),
    (("选品池",), "📦 选品池"),
    (("其他",), "🧭 其他"),
]


def _ledger_lines(watchpoint_reviews, limit=3):
    """预测账本：只报有结果的（验证/推翻），进展中不占版面。"""
    lines = []
    for r in watchpoint_reviews or []:
        if r.get("status") not in ("verified", "invalidated"):
            continue
        label = "✅ 说对了" if r["status"] == "verified" else "❌ 说错了"
        review = (r.get("review") or "").strip()
        if len(review) > 90:
            review = review[:88] + "…"
        lines.append(f"{label}：「{r.get('title', '')}」——{review}")
        if len(lines) >= limit:
            break
    return lines


def write_daily_hermes_cache(date, main_theme, items, commentary, watchpoint_reviews, total_count=0):
    """飞书日报：按行动线分组的 0-5 条（带 so what）+ 预测账本 + 天气 + 反馈脚注。"""
    tier1 = [i for i in items if i.get("tier", 1) == 1][:5]
    ledger = _ledger_lines(watchpoint_reviews)
    weather = _fetch_guangzhou_weather()
    parts = []

    if not tier1:
        # 空日报：敢发空，比硬凑可信
        parts.append(f"📰 阿宁日报｜{date}｜扫描 {total_count} 条，没有值得你改判断的事。")
        if ledger:
            parts.append("")
            parts.append("📌 预测账本：")
            parts.extend(ledger)
        if weather:
            parts.append("")
            parts.append(weather)
    else:
        groups = {}
        for item in tier1:
            cat = (item.get("category") or "").strip()
            header = next((h for aliases, h in ACTION_LINE_ORDER if any(a in cat for a in aliases)), "🧭 其他")
            groups.setdefault(header, []).append(item)

        n = 0
        for _aliases, header in ACTION_LINE_ORDER:
            if header not in groups:
                continue
            parts.append(header)
            for item in groups[header]:
                n += 1
                title = re.sub(r"^\s*\[\d+\]\s*", "", item.get("title", ""))
                title = _clean_generated_title(re.sub(r"^@\w+:\s*", "", title))[:50]
                conclusion = (item.get("conclusion") or "").strip()
                first_sent = re.split(r"(?<=[。！？!?])\s*", conclusion, maxsplit=1)[0]
                if len(first_sent) > 80:
                    first_sent = first_sent[:78] + "…"
                if first_sent and first_sent[:10] != title[:10]:
                    parts.append(f"{n}. {title}：{first_sent}")
                else:
                    parts.append(f"{n}. {title}")
                so_what = (item.get("so_what") or item.get("why") or "").strip()
                if so_what:
                    if len(so_what) > 100:
                        so_what = so_what[:98] + "…"
                    parts.append(f"so what：{so_what}")
            parts.append("")

        if ledger:
            parts.append("📌 预测账本：")
            parts.extend(ledger)
            parts.append("")

        if weather:
            parts.append(weather)
            parts.append("")

        stats = f"📰 阿宁日报｜{date}"
        if total_count:
            stats += f"｜扫描 {total_count} 条 · 入选 {len(tier1)} 条"
        parts.append(stats)
        parts.append("→ 完整版：https://yining365.github.io/daily-news/")
        parts.append("有用回个数字，全是废话回 0")

    message = "\n".join(parts)
    message = message.replace("**", "")
    if len(message) > 4000:
        message = message[:3990] + "\n..."

    # 把消息写到文件，由 Hermes cron 统一投递到微信。
    out_path = "/tmp/hermes_daily_news.txt"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(message)
        sys.stderr.write(f"  message written: {out_path}\n")
    except Exception as e:
        sys.stderr.write(f"  write file failed: {e}\n")


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
            url = it.get("url", "")
            all_items_text += f"- [{cat}] {title} — {conclusion} | {url}\n"
            so_what = (it.get("so_what") or "").strip()
            if so_what:
                all_items_text += f"  当时的 so what：{so_what}\n"

    date_range_start = week_entries[-1].get("date", "")
    date_range_end = week_entries[0].get("date", "")
    range_label = f"{date_range_start.split('-', 1)[1].replace('-', '/')} ~ {date_range_end.split('-', 1)[1].replace('-', '/')}"

    sys.stderr.write(f"Week range: {range_label}, {len(week_entries)} days\n")

    # AI 生成周报
    prompt = f"""回顾这一周（{range_label}）的阿宁日报，写一份复盘，不是再摘要一遍新闻。

日报按三条行动线组织（工作流/技巧、动钱、选品池），每条都带 so what（当时建议做什么/不做什么）。复盘的职责：

- 三条行动线各自这周的趋势：分散的条目串起来指向什么方向
- 检查 so what：哪几条建议这周被后续信息证明是对的/错的/该做但估计还没做的，点名说
- 哪些当时没在意但回头看很重要

## 输出格式

### 本周回顾
（2-3 段，像周末跟朋友复盘。第一段说行动线趋势，第二段核对本周 so what 的成色，敢认错。说人话，有态度。）

### 本周 5 条
（本周最值得留档的 5 条，格式如下）
1. **标题** | 链接URL
2. ...

### 下周判断
（2 句话。对阿宁下周最重要的判断，写成可判伪的形式：指标 + 阈值 + 期限。）

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
    verdict = ""
    current_section = None
    for line in output.split("\n"):
        stripped = line.strip()
        if "本周回顾" in stripped and stripped.startswith("#"):
            current_section = "review"
            continue
        elif "本周" in stripped and "5" in stripped and stripped.startswith("#"):
            current_section = "top5"
            continue
        elif "下周判断" in stripped and stripped.startswith("#"):
            current_section = "verdict"
            continue

        if current_section == "review":
            review_text += line + "\n"
        elif current_section == "top5":
            # 格式: 1. **标题** | URL  或  1. 标题 | URL
            m = re.match(r'^\d+\.\s*\*\*(.+?)\*\*\s*[|｜]\s*(\S+)', stripped)
            if not m:
                m = re.match(r'^\d+\.\s*(.+?)\s*[|｜]\s*(\S+)', stripped)
            if m:
                top5.append({"title": m.group(1).strip(), "url": m.group(2).strip()})
        elif current_section == "verdict":
            verdict += line + "\n"

    review_text = review_text.strip()
    verdict = verdict.strip()
    sys.stderr.write(f"Parsed: review={len(review_text)} chars, top5={len(top5)} items, verdict={len(verdict)} chars\n")

    # 保存到 data.json
    entry = {
        "date": today_str,
        "type": "weekly",
        "date_range": range_label,
        "main_theme": review_text,
        "commentary": verdict,
        "items": [
            {"title": it["title"], "conclusion": "", "source": "", "url": it.get("url", ""),
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

    # 周报推送：由 Hermes cron 接管，保留旧环境变量作为手动兼容入口
    html_parts = [f"<b>📅 阿宁周报 · {_tg_escape(range_label)}</b>", ""]
    plain_parts = [f"📅 阿宁周报 · {range_label}", ""]
    if review_text:
        html_parts.append(_md_to_tg_html(review_text))
        html_parts.append("")
        plain_parts.append(review_text)
        plain_parts.append("")
    if top5:
        html_parts.append("<b>🔑 本周 5 条</b>")
        plain_parts.append("🔑 本周 5 条")
        for i, it in enumerate(top5[:5], 1):
            url = it.get("url", "")
            title = _tg_escape(it["title"])
            if url:
                html_parts.append(f'{i}. <a href="{_tg_escape(url)}">{title}</a>')
                plain_parts.append(f"{i}. {it['title']}\n{url}")
            else:
                html_parts.append(f"{i}. {title}")
                plain_parts.append(f"{i}. {it['title']}")
        html_parts.append("")
        plain_parts.append("")
    if verdict:
        html_parts.append(f"💡 {_md_to_tg_html(verdict)}")
        html_parts.append("")
        plain_parts.append(f"💡 {verdict}")
        plain_parts.append("")
    # 预测校准：近 30 天已有结果的观察点命中率
    try:
        if os.path.exists(WATCHPOINTS_FILE):
            all_wp = json.loads(open(WATCHPOINTS_FILE, encoding="utf-8").read())
            cutoff30 = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            settled = [wp for wp in all_wp if wp.get("date", "") >= cutoff30 and wp.get("status") in ("verified", "invalidated")]
            hits = sum(1 for wp in settled if wp["status"] == "verified")
            if settled:
                calib = f"🎯 近 30 天预测校准：{len(settled)} 判 {hits} 中（{hits * 100 // len(settled)}%）"
                html_parts.append(_tg_escape(calib))
                html_parts.append("")
                plain_parts.append(calib)
                plain_parts.append("")
    except Exception as e:
        sys.stderr.write(f"calibration failed: {e}\n")

    html_parts.append('<a href="https://yining365.github.io/daily-news/">→ 完整版</a>')
    plain_parts.append("完整版：https://yining365.github.io/daily-news/")
    plain_parts.append("这周日报有几天对你有用？回个数字。")

    weekly_cache = "/tmp/hermes_weekly_news.txt"
    weekly_message = "\n".join(plain_parts)
    if len(weekly_message) > 4000:
        weekly_message = weekly_message[:3990] + "\n..."
    try:
        with open(weekly_cache, "w", encoding="utf-8") as f:
            f.write(weekly_message + "\n")
        sys.stderr.write(f"Hermes weekly message written: {weekly_cache}\n")
    except Exception as e:
        sys.stderr.write(f"Hermes weekly cache write failed: {e}\n")

    if TG_BOT_TOKEN and TG_CHAT_ID:
        sys.stderr.write("Sending Telegram...\n")
        message = "\n".join(html_parts)
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
