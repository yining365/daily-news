# GitHub Pages 部署指南

## 🚀 快速开始

### 1. 创建 GitHub 仓库

```bash
# 进入项目目录
cd /Users/xiaolin/Downloads/我的/my/news-aggregator-skill

# 初始化 Git（如果还没有）
git init

# 添加远程仓库（替换为你的用户名和仓库名）
git remote add origin https://github.com/你的用户名/daily-news.git

# 推送代码
git add .
git commit -m "Initial commit: Daily news aggregator"
git push -u origin main
```

### 2. 配置 Bark 推送密钥

1. 在 iOS 设备上安装 **Bark** App
2. 打开 App，复制推送 URL 中的密钥（形如 `xxxxxx`）
3. 在 GitHub 仓库中：
   - 进入 **Settings** → **Secrets and variables** → **Actions**
   - 点击 **New repository secret**
   - Name: `BARK_KEY`
   - Value: 你的 Bark 密钥

### 3. 启用 GitHub Pages

1. 进入仓库 **Settings** → **Pages**
2. Source 选择 **GitHub Actions**
3. 第一次 Workflow 运行后，页面将在以下地址可用：
   ```
   https://你的用户名.github.io/daily-news/
   ```

### 4. 手动触发测试

1. 进入仓库 **Actions** 页面
2. 选择 **Daily News Aggregator** workflow
3. 点击 **Run workflow** 手动触发

---

## 📅 定时任务说明

- **执行时间**: 每天北京时间 08:00（UTC 00:00）
- **自动部署**: 生成的 HTML 自动发布到 GitHub Pages
- **iOS 通知**: 部署完成后自动发送 Bark 推送

---

## 🔗 访问地址

部署成功后，你的固定访问地址为：

```
https://你的用户名.github.io/daily-news/
```

每日新闻页面：

```
https://你的用户名.github.io/daily-news/2026-01-22.html
```
