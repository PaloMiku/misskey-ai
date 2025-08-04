# Galinfo 插件

基于月幕 Gal API 的 Galgame 信息查询插件，支持查询游戏基本信息、会社信息，并可选择使用 AI 进行内容增强。新增定时 AI 发帖功能，可以自动基于缓存的游戏数据生成游玩体验分享。

## 功能特性

### 1. 游戏信息查询
- **自动触发查询**：当用户消息包含指定标签（默认 `#galgame`）时自动触发查询  
- **智能游戏匹配**：优先精确匹配，然后关键词匹配，确保返回最相关的游戏  
- **详细游戏信息**：提供游戏名、会社、限制级、汉化状态、简介等完整信息  
- **AI内容增强**：可选的AI功能，使用DeepSeek对游戏简介进行润色优化
- **缓存机制**：查询结果与AI润色内容会缓存，命中时显示缓存时间；支持 `#recreate` 强制刷新

### 2. 定时 AI 发帖（新功能）
- **智能发帖**：基于缓存的游戏数据随机生成游玩体验分享
- **数据选择**：可配置使用原始或AI增强的游戏数据进行发帖生成
- **时间控制**：可配置发帖间隔时间和随机延迟
- **频率限制**：支持每日发帖数量限制
- **AI 生成**：使用 AI 生成自然、真实的第一人称游戏体验
- **完全可配置**：AI 提示词完全可自定义
- **调试功能**：白名单用户可手动触发 AI 发帖预览

## 使用方法

### 游戏信息查询

在消息中使用触发标签 + 游戏名称：

```
#galgame 白色相簿2
#galgame CLANNAD
```

或者在提及中使用：

```
@机器人 想了解下 Fate/stay night #galgame
```

支持的特殊命令：
- `#galgame 游戏名 #recreate` - 强制重建缓存

### 调试功能

白名单用户可以使用以下功能：

#### 1. 调试预览
```
#galinfo_testaichat
```

这将：
1. 从缓存中随机选择游戏数据
2. 生成 AI 发帖内容
3. 显示预览结果和调试信息
4. 不会实际发帖，仅用于测试

#### 2. 直接发帖（私聊推荐）
```
#galinfo_aichat
```

这将：
1. 从缓存中随机选择游戏数据
2. 生成 AI 发帖内容
3. 直接发布到社交媒体
4. 适合在私聊中使用，避免刷屏

### 定时发帖设置

1. 在 `config.yaml` 中启用定时发帖功能：
   ```yaml
   auto_post:
     enabled: true
   ```

2. 调整发帖间隔和频率：
   ```yaml
   auto_post:
     interval_hours: 4      # 每4小时发帖一次
     random_delay_minutes: 60  # 随机延迟0-60分钟
     max_posts_per_day: 6   # 每日最多6次
     use_ai_enhanced_data: true  # 使用AI增强的游戏数据
   ```

3. 配置调试功能：
   ```yaml
   auto_post:
     debug_enabled: true
     debug_whitelist:
       - "your_username"    # 添加你的用户名
     debug_tag: "#galinfo_testaichat"    # 调试预览标签
     direct_post_tag: "#galinfo_aichat"  # 直接发帖标签
   ```

4. 自定义 AI 发帖风格（可选）：
   ```yaml
   auto_post:
     ai_post_system_prompt: |
       你的自定义系统提示词...
   ```

## 配置说明

复制 `config.yaml.example` 为 `config.yaml` 并根据需要修改：

```yaml
# 基础配置
enabled: true           # 是否启用插件
priority: 60           # 插件优先级
gal_tag: "#galgame"   # 触发标签
use_ai_enhancement: true  # 是否启用AI增强

# AI 增强系统提示词
ai_system_prompt: |
  你是一个专业的Galgame评论专家...

# 定时发帖配置
auto_post:
  enabled: false         # 是否启用定时发帖
  interval_hours: 6      # 发帖间隔（小时）
  random_delay_minutes: 30  # 随机延迟（分钟）
  max_posts_per_day: 4   # 每日最大发帖数
  use_ai_enhanced_data: false  # 是否使用AI增强的游戏数据
  
  # 调试功能
  debug_enabled: true
  debug_whitelist: ["admin"]
  debug_tag: "#galinfo_testaichat"
  
  # 自定义AI系统提示词
  ai_post_system_prompt: |
    你是一个热爱Galgame的玩家...
  
  # 用户提示词模板
  ai_post_user_prompt: |
    请基于以下游戏信息，写一篇游玩体验分享：
    {game_info}
```

### 配置项详解

#### 基础配置
- `enabled`: 控制插件是否启用
- `priority`: 插件执行优先级，数值越大越先执行
- `gal_tag`: 自定义触发标签
- `use_ai_enhancement`: 启用后，AI会对游戏简介进行润色

#### 定时发帖配置
- `auto_post.enabled`: 是否启用定时发帖功能
- `auto_post.interval_hours`: 发帖间隔时间（小时），支持小数
- `auto_post.random_delay_minutes`: 随机延迟时间（分钟）
- `auto_post.max_posts_per_day`: 每日最大发帖数量
- `auto_post.use_ai_enhanced_data`: 是否使用AI增强的游戏数据进行发帖
- `auto_post.debug_enabled`: 是否启用调试功能
- `auto_post.debug_whitelist`: 调试功能白名单用户列表
- `auto_post.debug_tag`: 调试触发标签（预览模式）
- `auto_post.direct_post_tag`: 直接发帖触发标签
- `auto_post.ai_post_system_prompt`: AI 发帖系统提示词
- `auto_post.ai_post_user_prompt`: 用户提示词模板

## 定时发帖工作原理

1. **数据来源**：使用用户查询过的游戏缓存数据
2. **缓存结构**：同时保存原始游戏数据和AI增强数据
3. **数据选择**：根据配置选择使用原始或AI增强的游戏数据
4. **随机选择**：从对应类型的缓存中随机选择游戏
5. **AI 生成**：基于游戏信息生成第一人称游玩体验
6. **时间控制**：根据配置的间隔和随机延迟发帖
7. **频率限制**：支持每日发帖数量上限

## 依赖

- `aiohttp`: HTTP 异步请求
- 月幕Gal API: 游戏数据来源
- DeepSeek API: AI内容增强和自动发帖（可选）

## 注意事项

1. 定时发帖功能需要先有游戏查询缓存数据
2. 需要配置 DeepSeek API 才能使用 AI 功能
3. 建议设置合理的发帖间隔，避免刷屏
4. 可以随时通过配置文件启用/禁用定时发帖
5. AI增强失败时会自动降级到原始信息显示
6. 查询关键词建议使用游戏的正式名称以获得最佳匹配结果

## 致谢
本插件移植自 [astrbot_plugin_galinfo](https://github.com/Hxfrzc/astrbot_plugin_galinfo)
