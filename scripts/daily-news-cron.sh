#!/bin/bash
# 阿宁日报 V3 — 服务器 cron 脚本
# 整合 X 情报 + Polymarket + 其他源 → AI 分析 → 微信 bot + GitHub Pages

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/var/log/daily-news.log"
LOCK_FILE="/tmp/daily-news.lock"
ENV_FILE="/root/.config/openclaw/openclaw.env"

# X 缓存路径
export X_CACHE_FILE="/root/.openclaw/workspace/x_digest_data/x_raw_cache.jsonl"

# AI 配置
export AI_BASE_URL="http://74.48.170.132:8317/v1"
export AI_API_KEY="changeme"
export AI_MODEL="gpt-5.4"

# 微信 bot 配置
WX_ACCOUNT_FILE="/root/.openclaw/openclaw-weixin/accounts/ceb58d946a51-im-bot.json"
if [ -f "$WX_ACCOUNT_FILE" ]; then
    export WX_BOT_TOKEN=$(python3 -c "import json;d=json.load(open('$WX_ACCOUNT_FILE'));print(d['token'])")
    export WX_BOT_TO=$(python3 -c "import json;d=json.load(open('$WX_ACCOUNT_FILE'));print(d['userId'])")
fi

export TZ="Asia/Shanghai"

mkdir -p "$(dirname "$LOG_FILE")"

{
    echo "[$(date '+%F %T')] ===== start daily news ====="

    flock -n 9 || {
        echo "[$(date '+%F %T')] another run is active, skip"
        exit 0
    }

    # 拉最新代码
    cd "$REPO_DIR"
    git pull --ff-only origin main 2>/dev/null || true

    # 安装依赖
    pip install -q -r requirements.txt 2>/dev/null || true

    # 运行日报
    python3 scripts/fetch_news.py
    rc=$?

    # 推送 HTML 到 GitHub Pages
    if [ $rc -eq 0 ]; then
        cd "$REPO_DIR"
        if git diff --quiet docs/ 2>/dev/null; then
            echo "[$(date '+%F %T')] no docs changes"
        else
            git add docs/
            git commit -m "daily: $(date '+%Y-%m-%d')" 2>/dev/null || true
            git push origin main 2>/dev/null || true
            echo "[$(date '+%F %T')] docs pushed"
        fi
    fi

    echo "[$(date '+%F %T')] done, rc=$rc"
    exit $rc
} 9>"$LOCK_FILE" >> "$LOG_FILE" 2>&1
