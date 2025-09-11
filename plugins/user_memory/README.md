# User Memory Plugin

为与机器人发生过聊天/提及互动的用户建立轻量级画## 数据键命名

`UserMemory` 插件下：

* `user:<uid>:## 后续可扩展方向

* 向 Bot 核心添加"chat 前置上下文" hook，避免拦截生成。
* 引入 embedding 与语义检索（需新增表）。
* 引入遗忘策略：基于时间/权重衰减。
* 支持通过用户名精准查询用户画像。
* 多维度用户画像分析（情感、话题、时间偏好等）。

## 新功能说明

### 按用户名查询

插件现在支持通过用户名（@XXXXX格式）精准查询用户记忆：

```python
# 在其他插件中调用
user_profile = await user_memory_plugin.get_user_profile("@example_user")
if user_profile:
    print(f"用户画像: {user_profile['summary']}")
    print(f"情感倾向: {user_profile['profile']['sentiment']}")
```

### 多方面用户画像

用户画像现在包含更多维度信息：
- **基础统计**：交互次数、首次/最近互动时间
- **关键词分析**：用户最常提及的话题关键词
- **情感倾向**：基于消息内容分析用户情感（积极/消极/中性）
- **时间偏好**：用户活跃的时间段分析
- **个性化总结**：AI生成的综合用户画像描述 => JSON格式的用户完整数据（包含stats, messages, summary, profile）
* `username:<username>:user_id` => 用户名到用户ID的映射

### 用户画像结构

```json
{
  "user_id": "用户ID",
  "username": "用户名",
  "summary": "AI生成的个性化总结",
  "profile": {
    "interaction_count": 10,
    "first_interaction": "12-01 14:30",
    "last_interaction": "12-05 16:45",
    "username": "example_user",
    "top_keywords": ["技术", "编程", "AI"],
    "sentiment": "积极",
    "active_hours": "14:00-16:00"
  },
  "stats": {
    "count": 10,
    "first_ts": 1733000000,
    "last_ts": 1733500000,
    "username": "example_user"
  },
  "recent_messages": ["消息1", "消息2", "消息3"]
}
```支持：

1. 统计用户交互次数、最近时间。
2. 保留最近 N 条消息并周期性生成"兴趣/偏好/语气"总结。
3. 生成多方面用户画像，包括情感倾向、关键词分析、活跃时间等。
4. 支持按用户名（@XXXXX）精准查询用户记忆。
5. 可选择由插件直接生成带个性化上下文的 AI 回复，或仅维护记忆供后续扩展。

数据统一存储在主数据库 `data/misskey_ai.db` 的 `plugin_data` 表中（JSON格式）。mory Plugin

为与机器人发生过聊天/提及互动的用户建立轻量级画像与按需记忆，支持：

1. 统计用户交互次数、最近时间。
2. 保留最近 N 条消息并周期性生成“兴趣/偏好/语气”总结。
3. 可选择由插件直接生成带个性化上下文的 AI 回复，或仅维护记忆供后续扩展。

数据统一存储在主数据库 `data/misskey_ai.db` 的 `plugin_data` 表中（无需额外文件）。

## 配置 (config.yaml / config.yaml.example)

| 键 | 说明 | 默认 |
|----|------|------|
| enabled | 是否启用 | false |
| priority | 插件优先级 | 90 |
| handle_messages | 是否拦截私信消息并个性化回复 | true |
| handle_mentions | 是否拦截提及并个性化回复 | true |
| max_messages_per_user | 每用户保留最近消息条数 | 30 |
| summary_interval | 每累积多少条消息刷新总结 | 5 |
| summary_max_length | 总结最大字数 | 120 |
| keywords_top_n | 关键词数量 | 8 |
| min_keyword_length | 最短关键词长度 | 2 |
| system_memory_prefix | 附加到系统提示前的额外说明 | 请结合以下用户画像做出更个性化... |
| debug_log | 是否输出调试日志 | false |
| ignore_hashtag_messages | 含 # 的消息是否直接忽略（不记录不回复） | true |

## 工作流程

1. 用户私信或提及时，插件记录消息并更新计数、时间。
2. 当消息数达到 `summary_interval` 的倍数或尚无总结时：
   * 汇总最近消息 → 提取简单关键词 → 调用 OpenAI 生成画像总结。
3. 若 `handle_messages/handle_mentions` 为 true：
   * 构造 system: `原系统提示 + system_memory_prefix + 用户画像`。
   * 调用聊天模型生成个性化回复并返回 handled。

## 数据键命名

`UserMemory` 插件下：

* `user:<uid>:stats`  => {"count", "first_ts", "last_ts"}
* `user:<uid>:messages` => JSON 列表 (按时间升序，截断至 max_messages_per_user)
* `user:<uid>:summary` => 最新画像摘要（字符串）

## 命令插件辅助

可用 `^dbclear UserMemory` 清空全部画像，或 `^dbclear UserMemory user:<uid>:summary` 清除单个键。

## 后续可扩展方向

* 向 Bot 核心添加“chat 前置上下文” hook，避免拦截生成。
* 引入 embedding 与语义检索（需新增表）。
* 引入遗忘策略：基于时间/权重衰减。
