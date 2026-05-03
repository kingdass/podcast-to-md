# 播客转文稿工具

输入播客链接 → 自动抓取音频 → Groq Whisper 转写 → DeepSeek 整理 → 下载 Markdown

## 部署到 Railway（推荐）

### 第一步：准备 API Keys

1. **Groq API Key**（免费）
   - 访问 https://console.groq.com
   - 注册账号 → API Keys → Create API Key
   - 复制保存

2. **DeepSeek API Key**（你已有）
   - 登录 https://platform.deepseek.com
   - 复制你的 API Key

### 第二步：上传代码到 GitHub

1. 在 GitHub 新建一个仓库（如 `podcast-to-md`）
2. 把本项目所有文件上传到仓库

### 第三步：部署到 Railway

1. 访问 https://railway.app，用 GitHub 账号登录
2. 点击 「New Project」→「Deploy from GitHub repo」
3. 选择你刚创建的仓库
4. 等待首次部署完成

### 第四步：设置环境变量

在 Railway 项目页面：
1. 点击你的服务 → 「Variables」标签
2. 添加以下两个变量：
   ```
   GROQ_API_KEY=你的groq密钥
   DEEPSEEK_API_KEY=你的deepseek密钥
   ```
3. 保存后 Railway 自动重新部署

### 第五步：访问

部署完成后，Railway 会给你一个域名（如 `xxx.railway.app`），打开即可使用。

---

## 本地运行（测试用）

```bash
pip install -r requirements.txt
export GROQ_API_KEY=你的key
export DEEPSEEK_API_KEY=你的key
uvicorn main:app --reload --port 8000
```

打开 http://localhost:8000

---

## 注意事项

- 小宇宙部分节目可能因版权限制无法下载，这属于平台限制
- Groq 免费套餐每天有额度限制，够个人日常使用
- 长播客（1小时以上）转写时间较长，请耐心等待
