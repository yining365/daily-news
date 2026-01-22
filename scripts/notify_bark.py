#!/usr/bin/env python3
"""
Bark iOS 推送通知脚本
在 GitHub Actions 中运行，发送每日新闻摘要通知
"""

import os
import requests
from datetime import datetime
from urllib.parse import quote

def send_bark_notification():
    """发送 Bark 推送通知"""
    
    bark_key = os.environ.get('BARK_KEY')
    if not bark_key:
        print("⚠️ BARK_KEY not set, skipping notification")
        return False
    
    # 获取 GitHub Pages URL
    github_repo = os.environ.get('GITHUB_REPOSITORY', '')
    if github_repo:
        # 格式: username/repo -> username.github.io/repo
        parts = github_repo.split('/')
        if len(parts) == 2:
            pages_url = f"https://{parts[0]}.github.io/{parts[1]}/"
        else:
            pages_url = os.environ.get('GITHUB_PAGES_URL', '')
    else:
        pages_url = os.environ.get('GITHUB_PAGES_URL', '')
    
    # 今日日期
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 构建通知内容
    title = f"📰 今日新闻已更新"
    body = f"{today} 每日科技热点已准备就绪，点击查看完整 Dashboard"
    
    # Bark API URL
    # 格式: https://api.day.app/{key}/{title}/{body}?url={click_url}
    bark_url = f"https://api.day.app/{bark_key}/{quote(title)}/{quote(body)}"
    
    params = {
        'url': pages_url,  # 点击通知后打开的链接
        'group': 'DailyNews',  # 通知分组
        'icon': 'https://raw.githubusercontent.com/nicepkg/vscode-ai-assistant/main/icon.png',  # 可选图标
        'sound': 'minuet',  # 通知声音
    }
    
    try:
        response = requests.get(bark_url, params=params, timeout=10)
        result = response.json()
        
        if result.get('code') == 200:
            print(f"✅ Bark notification sent successfully!")
            print(f"   Dashboard URL: {pages_url}")
            return True
        else:
            print(f"❌ Bark notification failed: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending Bark notification: {e}")
        return False


if __name__ == "__main__":
    send_bark_notification()
