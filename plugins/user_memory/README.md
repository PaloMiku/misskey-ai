# User Memory Plugin

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
