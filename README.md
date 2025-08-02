> [!NOTE]
>
> 本仓库是上游仓库的 Fork 魔改版本！存在诸多不稳定因素，请注意！

<div align="center">

<h1>Misskey AI</h1>

一只 Python 实现的 Misskey 机器人<br>
使用 DeepSeek 生成的内容发帖或与用户互动<br>
支持兼容 OpenAI API 架构的其他模型<br>

目前运行在：[misskey.site/@misuki](misskey.site/@misuki)
<br>

<a href="https://www.python.org/downloads">
    <img alt="python 3.11+" src="https://img.shields.io/badge/python-3.11+-3776ab.svg?style=for-the-badge&labelColor=303030"></a>
<a href="./LICENSE">
    <img alt="license" src="https://img.shields.io/badge/license-AGPL--3.0-603669.svg?style=for-the-badge&labelColor=303030"></a>
</div>

## 快速开始

### `1` 克隆仓库

```bash
git clone https://github.com/oreeke/misskey-ai.git
cd misskey-ai
```

### `2` 部署方式

#### `a` 手动安装

- 复制 `config.yaml.example` 为 `config.yaml` 并修改配置
<details>
<summary><kbd>📃 config.yaml</kbd></summary>

```yaml
misskey:
  instance_url: "https://misskey.example.com"       # Misskey 实例 URL
  access_token: "your_access_token_here"            # Misskey 访问令牌

deepseek:
  api_key: "your_deepseek_api_key_here"             # DeepSeek API 密钥
  model: "deepseek-chat"                            # 使用的模型名称
  api_base: "https://api.deepseek.com/v1"           # DeepSeek API 端点
  max_tokens: 1000                                  # 最大生成 token 数
  temperature: 0.8                                  # 温度参数

bot:
  system_prompt: |                                  # 系统提示词（支持文件导入："prompts/*.txt"，"file://path/to/*.txt"）
    你是一个可爱的AI助手，运行在Misskey平台上。
    请用简短、友好的方式发帖和回答问题。

  auto_post:
    enabled: true                                   # 是否启用自动发帖
    interval_minutes: 180                           # 发帖间隔（分钟）
    max_posts_per_day: 8                            # 每日最大发帖数量（凌晨 0 点重置计数器）
    visibility: "public"                            # 发帖可见性（public/home/followers/specified）
    prompt: |                                       # 发帖提示词
      生成一篇有趣、有见解的社交媒体帖子。

  response:
    mention_enabled: true                           # 是否响应提及（@）
    chat_enabled: true                              # 是否响应聊天
    chat_memory: 10                                 # 聊天上下文记忆长度（条）

db:
  cleanup_days: 30                                  # SQLite 旧消息 ID 保留天数

log:
  level: "INFO"                                     # 日志级别 (DEBUG/INFO/WARNING/ERROR)
```
</details>

使用 uv 管理依赖

```bash
pip install uv # 对于 Arch Linux 调试使用 python-uv 包
uv sync
uv run run.py
```

> 后台运行（可选）
```bash
nohup python run.py & tail -f logs/misskey_ai.log
```

> 作为服务（可选）

<details>
<summary><kbd>📃 misskey-ai.service</kbd></summary>

```ini
[Unit]
Description=Misskey AI Service
After=network.target

[Service]
Type=exec
WorkingDirectory=/path/to/misskey-ai
ExecStart=/path/to/envs/misskey-ai/bin/python run.py
KillMode=control-group
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
```
</details>

```bash
systemctl daemon-reload
systemctl start misskey-ai.service
```

#### `b` Docker Compose

- 修改 `docker-compose.yaml` 中的环境变量
<details>
<summary><kbd>📃 docker-compose.yaml</kbd></summary>

```yaml
MISSKEY_INSTANCE_URL=https://misskey.example.com           # Misskey 实例 URL
MISSKEY_ACCESS_TOKEN=your_access_token_here                # Misskey 访问令牌
DEEPSEEK_API_KEY=your_deepseek_api_key_here                # DeepSeek API 密钥
DEEPSEEK_MODEL=deepseek-chat                               # 使用的模型名称
DEEPSEEK_API_BASE=https://api.deepseek.com/v1              # DeepSeek API 端点
DEEPSEEK_MAX_TOKENS=1000                                   # DeepSeek 最大生成 token 数
DEEPSEEK_TEMPERATURE=0.8                                   # DeepSeek 温度参数
BOT_SYSTEM_PROMPT=你是一个可爱的AI助手...                    # 系统提示词（支持文件导入："prompts/*.txt"，"file://path/to/*.txt"）
BOT_AUTO_POST_ENABLED=true                                 # 是否启用自动发帖
BOT_AUTO_POST_INTERVAL=180                                 # 发帖间隔（分钟）
BOT_AUTO_POST_MAX_PER_DAY=8                                # 每日最大发帖数量（凌晨 0 点重置计数器）
BOT_AUTO_POST_VISIBILITY=public                            # 发帖可见性（public/home/followers/specified）
BOT_AUTO_POST_PROMPT=生成一篇有趣、有见解的社交媒体帖子。      # 发帖提示词
BOT_RESPONSE_MENTION_ENABLED=true                          # 是否响应提及（@）
BOT_RESPONSE_CHAT_ENABLED=true                             # 是否响应聊天
BOT_RESPONSE_CHAT_MEMORY=10                                # 聊天上下文记忆长度（条）
DB_CLEANUP_DAYS=30                                         # SQLite 旧消息 ID 保留天数
LOG_LEVEL=INFO                                             # 日志级别 (DEBUG/INFO/WARNING/ERROR)
```
</details>

```bash
docker compose build
docker compose up -d
```

> [!NOTE]
>
> 自动发帖时 API 请求默认携带时间戳，以绕过 [DeepSeek 缓存](https://api-docs.deepseek.com/zh-cn/news/news0802)
