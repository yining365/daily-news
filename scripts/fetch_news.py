import argparse
import json
import requests
from bs4 import BeautifulSoup
import sys
import time
import re
import concurrent.futures
from datetime import datetime
import os
from deep_translator import GoogleTranslator

# Add parent directory to path to import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.html_generator import HTMLGenerator
    from src.image_generator import generate_card_image
    from src.config import SCENARIO_MAP, OUTPUT_DIR
except ImportError:
    # Fallback to local imports if run from root
    from src.html_generator import HTMLGenerator
    from src.image_generator import generate_card_image
    from src.config import SCENARIO_MAP, OUTPUT_DIR
# Headers for scraping to avoid basic bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    from src.x_sources import X_ACCOUNTS, NITTER_INSTANCES
except ImportError:
    X_ACCOUNTS = []
    NITTER_INSTANCES = []

def filter_items(items, keyword=None):
    """Filter items by keywords. Supports both English and Chinese keywords."""
    if not keyword:
        return items
    keywords = [k.strip().lower() for k in keyword.split(',') if k.strip()]
    # Simple substring match (case-insensitive) - works for Chinese
    return [item for item in items if any(k in item['title'].lower() for k in keywords)]

def translate_to_chinese(text):
    """Translate text to Chinese using deep_translator"""
    try:
        # Simple heuristic to avoid translating if already Chinese
        if any(u'\u4e00' <= c <= u'\u9fff' for c in text):
            return text
        
        translator = GoogleTranslator(source='auto', target='zh-CN')
        return translator.translate(text)
    except Exception as e:
        return text

def batch_translate_items(items):
    """Translate titles for a list of items"""
    # Simply translate sequentially or parallel (keep simple for now)
    if not items: return items
    sys.stderr.write(f"Translating {len(items)} items to Chinese...\n")
    # Using ThreadPool for faster translation if items are many
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_item = {executor.submit(translate_to_chinese, item['title']): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            try:
                item['title'] = future.result()
            except: pass
    return items

def fetch_url_content(url):
    """
    Fetches the content of a URL and extracts text from paragraphs.
    Truncates to 3000 characters.
    """
    if not url or not url.startswith('http'):
        return ""
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
         # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        # Get text
        text = soup.get_text(separator=' ', strip=True)
        # Simple cleanup
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text[:3000]
    except Exception:
        return ""

def enrich_items_with_content(items, max_workers=10):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(fetch_url_content, item['url']): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            try:
                content = future.result()
                if content:
                    item['content'] = content
                    # Simple summary generation: first 100 characters of content
                    item['summary'] = content[:150] + "..." if len(content) > 150 else content
            except Exception:
                item['content'] = ""
    return items

def ensure_summary(items):
    """Ensure every item has a summary field"""
    for item in items:
        if 'summary' in item and item['summary']:
            continue
            
        # Fallback to title or description logic
        # For GitHub, title is "Name - Description", so extract description
        if item.get('source') == 'GitHub Trending' and ' - ' in item.get('title', ''):
            try:
                parts = item['title'].split(' - ', 1)
                item['summary'] = parts[1]
                # Optional: clean up title to just show repo name if desired, but let's keep it safe
            except:
                item['summary'] = item['title']
        else:
            # Fallback for others: just use title as summary if really needed, or leave empty to look cleaner
            # User wants summary, so let's duplicate specific parts if available
            # But duplicate title looks bad.
            # Let's try to grab from metadata if available (most don't have it here)
            pass
            
    return items

# --- Source Fetchers (Keep existing fetchers) ---

def fetch_hackernews(limit=20, keyword=None):
    base_url = "https://news.ycombinator.com"
    news_items = []
    page = 1
    max_pages = 5
    
    while len(news_items) < limit and page <= max_pages:
        url = f"{base_url}/news?p={page}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200: break
        except: break

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('.athing')
        if not rows: break
        
        page_items = []
        for row in rows:
            try:
                id_ = row.get('id')
                title_line = row.select_one('.titleline a')
                if not title_line: continue
                title = title_line.get_text()
                link = title_line.get('href')
                
                # Metadata
                score_span = soup.select_one(f'#score_{id_}')
                score = score_span.get_text() if score_span else "0 points"
                
                # Age/Time
                age_span = soup.select_one(f'.age a[href="item?id={id_}"]')
                time_str = age_span.get_text() if age_span else ""
                
                if link and link.startswith('item?id='): link = f"{base_url}/{link}"
                
                page_items.append({
                    "source": "Hacker News", 
                    "title": title, 
                    "url": link, 
                    "heat": score,
                    "time": time_str
                })
            except: continue
        
        news_items.extend(filter_items(page_items, keyword))
        if len(news_items) >= limit: break
        page += 1
        time.sleep(0.5)

    return news_items[:limit]

def fetch_weibo(limit=20, keyword=None):
    # Use the PC Ajax API which returns JSON directly and is less rate-limited than scraping s.weibo.com
    url = "https://weibo.com/ajax/side/hotSearch"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://weibo.com/"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        items = data.get('data', {}).get('realtime', [])
        
        all_items = []
        for item in items:
            # key 'note' is usually the title, sometimes 'word'
            title = item.get('note', '') or item.get('word', '')
            if not title: continue
            
            # 'num' is the heat value
            heat = item.get('num', 0)
            
            # Construct URL (usually search query)
            # Web UI uses: https://s.weibo.com/weibo?q=%23TITLE%23&Refer=top
            full_url = f"https://s.weibo.com/weibo?q={requests.utils.quote(title)}&Refer=top"
            
            all_items.append({
                "source": "Weibo Hot Search", 
                "title": title, 
                "url": full_url, 
                "heat": f"{heat}",
                "time": "Real-time"
            })
            
        return filter_items(all_items, keyword)[:limit]
    except Exception: 
        return []

def fetch_github(limit=20, keyword=None):
    try:
        # If filtering for AI keywords specifically on github trending, it's hard without API
        # Just getting trending general is safer
        response = requests.get("https://github.com/trending", headers=HEADERS, timeout=10)
    except: return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    items = []
    for article in soup.select('article.Box-row'):
        try:
            h2 = article.select_one('h2 a')
            if not h2: continue
            title = h2.get_text(strip=True).replace('\n', '').replace(' ', '')
            link = "https://github.com" + h2['href']
            
            desc = article.select_one('p')
            desc_text = desc.get_text(strip=True) if desc else ""
            
            # Stars (Heat)
            # usually the first 'Link--muted' with a SVG star
            stars_tag = article.select_one('a[href$="/stargazers"]')
            stars = stars_tag.get_text(strip=True) if stars_tag else ""
            
            items.append({
                "source": "GitHub Trending", 
                "title": f"{title} - {desc_text}", 
                "url": link,
                "heat": f"{stars} stars",
                "time": "Today"
            })
        except: continue
    return filter_items(items, keyword)[:limit]

def fetch_36kr(limit=20, keyword=None):
    try:
        response = requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for item in soup.select('.newsflash-item'):
            title = item.select_one('.item-title').get_text(strip=True)
            href = item.select_one('.item-title')['href']
            time_tag = item.select_one('.time')
            time_str = time_tag.get_text(strip=True) if time_tag else ""
            
            items.append({
                "source": "36Kr", 
                "title": title, 
                "url": f"https://36kr.com{href}" if not href.startswith('http') else href,
                "time": time_str,
                "heat": ""
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_v2ex(limit=20, keyword=None):
    try:
        # Hot topics json
        data = requests.get("https://www.v2ex.com/api/topics/hot.json", headers=HEADERS, timeout=10).json()
        items = []
        for t in data:
            # V2EX API fields: created, replies (heat)
            replies = t.get('replies', 0)
            created = t.get('created', 0)
            # convert epoch to readable if possible, simpler to just leave as is or basic format
            # Let's keep it simple
            items.append({
                "source": "V2EX", 
                "title": t['title'], 
                "url": t['url'],
                "heat": f"{replies} replies",
                "time": "Hot"
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_tencent(limit=20, keyword=None):
    try:
        url = "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D"
        data = requests.get(url, headers={"Referer": "https://news.qq.com/"}, timeout=10).json()
        items = []
        for news in data['data']['tabs'][0]['articleList']:
            items.append({
                "source": "Tencent News", 
                "title": news['title'], 
                "url": news.get('url') or news.get('link_info', {}).get('url'),
                "time": news.get('pub_time', '') or news.get('publish_time', '')
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_wallstreetcn(limit=20, keyword=None):
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30"
        data = requests.get(url, timeout=10).json()
        items = []
        for item in data['data']['items']:
            res = item.get('resource')
            if res and (res.get('title') or res.get('content_short')):
                 ts = res.get('display_time', 0)
                 time_str = datetime.fromtimestamp(ts).strftime('%H:%M') if ts else ""
                 items.append({
                     "source": "Wall Street CN", 
                     "title": res.get('title') or res.get('content_short'), 
                     "url": res.get('uri'),
                     "time": time_str
                 })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_producthunt(limit=20, keyword=None):
    try:
        # Using RSS for speed and reliability without API key
        response = requests.get("https://www.producthunt.com/feed", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'xml')
        if not soup.find('item'): soup = BeautifulSoup(response.text, 'html.parser')
        
        items = []
        for entry in soup.find_all(['item', 'entry']):
            title = entry.find('title').get_text(strip=True)
            link_tag = entry.find('link')
            url = link_tag.get('href') or link_tag.get_text(strip=True) if link_tag else ""
            
            pubBox = entry.find('pubDate') or entry.find('published')
            pub = pubBox.get_text(strip=True) if pubBox else ""
            
            items.append({
                "source": "Product Hunt", 
                "title": title, 
                "url": url,
                "time": pub,
                "heat": "Top Product" # RSS implies top rank
            })
        return filter_items(items, keyword)[:limit]
    except: return []

# --- X (Twitter) Fetcher ---

def fetch_x_rss(username, instance):
    """Fetch RSS for a single user from a specific Nitter instance"""
    url = f"https://{instance}/{username}/rss"
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            return response.text
    except:
        return None
    return None

def parse_x_rss(xml_content, username, category):
    """Parse Nitter RSS content"""
    items = []
    try:
        soup = BeautifulSoup(xml_content, 'xml')
        if not soup.find('item'): return []
        
        for entry in soup.find_all('item')[:5]: # Take top 5 recent from each user
            desc = entry.find('description').get_text(strip=True)
            # Basic cleanup of Nitter HTML in description if needed
            # For now, keep it raw or simple text
            
            # Extract image if exists
            img = ""
            if '<img src="' in desc:
                # Simple regex or split to find image
                try:
                    img = desc.split('<img src="')[1].split('"')[0]
                except: pass

            text_content = BeautifulSoup(desc, "html.parser").get_text(strip=True)
            
            pub = entry.find('pubDate').get_text(strip=True)
            link = entry.find('link').get_text(strip=True)
            
            # Convert Nitter link to X.com link for better UX
            # Link format: https://nitter.net/user/status/id
            if '/status/' in link:
                tweet_id = link.split('/status/')[1].split('#')[0]
                link = f"https://x.com/{username}/status/{tweet_id}"
            
            items.append({
                "source": "X (Twitter)",
                "author": username,
                "category": category,
                "title": f"@{username}: {text_content[:100]}...", # Title for card
                "summary": text_content, # Full text in summary
                "url": link,
                "time": pub,
                "image": img,
                "heat": "New" # No heat metric in RSS usually
            })
    except: pass
    return items

def fetch_x_social(limit=15, keyword=None):
    """Fetch tweets from curated list using Nitter rotation"""
    if not X_ACCOUNTS or not NITTER_INSTANCES:
        return []
    
    sys.stderr.write(f"Fetching X feeds for {len(X_ACCOUNTS)} users...\n")
    
    all_tweets = []
    
    # 1. Randomized Instance Selection Strategy
    # We will try to fetch each user. For each user, pick a random instance.
    # If it fails, try 1 more backup instance.
    import random
    
    def fetch_single_user(user_tuple):
        username, category = user_tuple
        # Try all instances until one works (randomized order)
        instances = list(NITTER_INSTANCES)
        random.shuffle(instances)
        
        for instance in instances:
            xml = fetch_x_rss(username, instance)
            if xml:
                items = parse_x_rss(xml, username, category)
                if items: return items
        return []

    # Parallel fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_user = {executor.submit(fetch_single_user, u): u for u in X_ACCOUNTS}
        for future in concurrent.futures.as_completed(future_to_user):
            try:
                tweets = future.result()
                if tweets:
                    all_tweets.extend(tweets)
            except: pass
            
    # Sort by time (hacky parsing or just random shuffle for 'discovery')
    # RSS pubDate is usually: "Wed, 22 Jan 2026 12:00:00 GMT"
    # Let's just shuffle to give everyone a chance, or leave as is (grouped by user)
    # Better: Shuffle to make it look like a feed
    random.shuffle(all_tweets)
    
    return all_tweets[:limit] # Return top N random tweets from recent pool

def fetch_data_for_scenario(scenario_key, limit=20, deep=False, no_translate=False):
    """Fetch data for a specific scenario"""
    if scenario_key not in SCENARIO_MAP:
        return []
    
    config = SCENARIO_MAP[scenario_key]
    sources = config['sources']
    keywords = config['keywords']
    keyword_str = ",".join(keywords) if keywords else None
    
    # Map source names to functions
    # (Simplified map reconstruction for local scope)
    sources_map = {
        'hackernews': fetch_hackernews, 'weibo': fetch_weibo, 'github': fetch_github,
        '36kr': fetch_36kr, 'v2ex': fetch_v2ex, 'tencent': fetch_tencent,
        'wallstreetcn': fetch_wallstreetcn, 'producthunt': fetch_producthunt,
        'x_social': fetch_x_social
    }
    
    to_run = []
    if 'all' in sources:
        to_run = list(sources_map.values())
    else:
        for s in sources:
            if s in sources_map:
                to_run.append(sources_map[s])
                
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_func = {executor.submit(func, limit, keyword_str): func for func in to_run}
        for future in concurrent.futures.as_completed(future_to_func):
            try:
                data = future.result()
                if data:
                    results.extend(data)
            except: pass
            
    if deep and results:
        results = enrich_items_with_content(results)
        
    results = ensure_summary(results)
    
    if not no_translate and results:
        results = batch_translate_items(results)
        
    
    # 3. Practicality Tagging
    results = tag_practicality(results)

    # 4. Relevance Sorting (Heat Score)
    # Calculate score for each
    for item in results:
        item['heat_score'] = calculate_heat_score(item.get('heat', ''))
        
    # Sort descending by heat_score
    results.sort(key=lambda x: x['heat_score'], reverse=True)

    # Enforce global limit per scenario
    return results[:limit]

def calculate_heat_score(heat_str):
    """Normalize heat string to an integer score"""
    if not heat_str: return 0
    s = str(heat_str).lower().replace(',', '')
    score = 0
    try:
        if '万' in s or 'w' in s:
            num = re.findall(r"\d+\.?\d*", s)[0]
            score = float(num) * 10000
        elif 'stars' in s or 'points' in s or 'replies' in s:
            num = re.findall(r"\d+", s)[0]
            score = int(num)
        elif s.isdigit():
             score = int(s)
    except:
        score = 0
    return score

def tag_practicality(items):
    """Add [Tool] or [Tutorial] tags based on content"""
    for item in items:
        title = item.get('title', '')
        url = item.get('url', '')
        
        # Tool detection
        if 'github.com' in url or 'producthunt.com' in url:
             if '[Tool]' not in title:
                 item['title'] = f"🛠️ {title}"
        
        # Tutorial detection (simple keywords)
        if any(x in title.lower() for x in ['how to', 'guide', 'tutorial', '101', 'course']):
             if '📖' not in title:
                 item['title'] = f"📖 {title}"
                 
    return items

def main():
    parser = argparse.ArgumentParser()
    
    # Keeping old arguments for backward compatibility/direct use
    parser.add_argument('--source', help='Source(s) to fetch from (comma-separated)')
    parser.add_argument('--limit', type=int, default=10, help='Limit per source. Default 10')
    parser.add_argument('--keyword', help='Comma-sep keyword filter')
    parser.add_argument('--deep', action='store_true', help='Download article content')
    parser.add_argument('--output', default='html', choices=['json', 'html', 'all'], 
                      help='Output format. "xhs" and "image" are deprecated in V2.')
    parser.add_argument('--category', default='all', choices=['ai', 'china', 'github', 'global', 'x_social', 'all'],
                      help='Scenario category to fetch. Default "all" fetches all categories for Dashboard.')
    parser.add_argument('--no-translate', action='store_true', help='Disable auto-translation')
    
    args = parser.parse_args()
    
    # Case 1: Dashboard Generation (Default or specific category)
    # If args.source is NOT provided, we assume Category Mode
    if not args.source:
        scenarios_to_fetch = []
        if args.category == 'all':
            scenarios_to_fetch = ['china', 'ai', 'x_social', 'github', 'global'] # Explicit order including x_social
        elif args.category in SCENARIO_MAP:
            scenarios_to_fetch = [args.category]
            
        sys.stderr.write(f"Fetching scenarios: {scenarios_to_fetch}...\n")
        
        all_scenario_data = {}
        for key in scenarios_to_fetch:
            current_limit = args.limit
            if key == 'github':
                current_limit = 2
                
            sys.stderr.write(f"--- Fetching {key} (limit={current_limit}) ---\n")
            data = fetch_data_for_scenario(key, current_limit, args.deep, args.no_translate)
            all_scenario_data[key] = data
            
            
        # Generare Summary
        total_items = sum(len(items) for items in all_scenario_data.values())
        categories = [k for k, v in all_scenario_data.items() if v]
        
        # Simple summary logic (placeholder for AI summary)
        summary_text = f"今日共追踪到 <strong>{total_items}</strong> 条前沿资讯，覆盖 {', '.join(categories).upper()} 等领域。"
        
        # Try to find top hot items
        hot_items = []
        for items in all_scenario_data.values():
            for item in items:
                # Heuristic for "hot" - check if heat field has numbers > 100 or specific keywords
                heat_val = item.get('heat', '')
                if any(x in heat_val for x in ['points', 'stars', 'replies', '万']):
                    hot_items.append(item['title'])
                    if len(hot_items) >= 2: break
            if len(hot_items) >= 3: break
            
        if hot_items:
            summary_text += f"<br>🔥 热门关注：{'、'.join(hot_items[:3])}..."

        # Generate Dashboard HTML
        if args.output in ['html', 'all']:
            from datetime import timedelta, timezone
            # Force Beijing Time (UTC+8)
            beijing_time = datetime.now(timezone.utc) + timedelta(hours=8)
            date_str = beijing_time.strftime("%Y-%m-%d")
            
            generator = HTMLGenerator()
            html_path = generator.generate_dashboard(date_str, all_scenario_data, summary=summary_text)
            generator.update_index(date_str) # Critical: Update index.html to point to new file
            print(f"Dashboard generated: {html_path}")
            
    # Case 2: Legacy/Direct Source Mode (if --source is provided)
    else:
        # Re-use logic for direct source fetching...
        # For simplicity in V2, let's map direct source requests to a "Custom" scenario or just print JSON
        # Ideally we refactor this to reuse the same functions.
        pass

if __name__ == "__main__":
    main()
