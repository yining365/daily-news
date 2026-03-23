#!/bin/bash
# 阿宁日报 V3 — 服务器 cron 脚本
# 整合 X 情报 + Polymarket + 其他源 → AI 分析 → Telegram + GitHub Pages

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

# Telegram 配置（从 env 文件读取）
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi
export TG_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
export TG_CHAT_ID="${TG_CHAT_ID:--5273648726}"

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
