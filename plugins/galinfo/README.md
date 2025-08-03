# galinfo 插件

本插件为 misskey-ai 平台提供 Galgame 信息自动查询能力，基于月幕Gal API。

## 功能特性

- **自动触发查询**：当用户消息包含指定标签（默认 `#galgame`）时自动触发查询  
- **智能游戏匹配**：优先精确匹配，然后关键词匹配，确保返回最相关的游戏  
- **详细游戏信息**：提供游戏名、会社、限制级、汉化状态、简介等完整信息  
- **AI内容增强**：可选的AI功能，使用DeepSeek对游戏简介进行润色优化（可配置开关）  
- **缓存机制**：查询结果与AI润色内容会缓存至 `.cache` 文件，命中时返回“【缓存数据】”并显示缓存时间；在请求中添加 `#recreate` 可强制刷新指定条目缓存  

## 使用方法

在聊天中发送包含触发标签的消息：

```
CLANNAD #galgame
```

或者：

```
@机器人 想了解下 Fate/stay night #galgame
```

需要强制重建缓存时，在标签后添加 `#recreate`：

```
Fate/stay night #galgame #recreate
```

## 配置说明

复制 `config.yaml.example` 为 `config.yaml` 并根据需要修改：

```yaml
enabled: true              # 是否启用插件
priority: 60               # 插件优先级
gal_tag: "#galgame"        # 触发标签（可自定义）
use_ai_enhancement: false  # 是否启用AI内容增强
ai_system_prompt: |        # AI系统提示词（可自定义）
  你是一个专业的Galgame(美少女游戏)评论专家。请根据用户提供的游戏基本信息，用更生动、有趣的语言重新整理和润色内容，让介绍更加吸引人。
  
  要求：
  1. 保持所有事实信息准确，不要编造内容
  2. 简介部分可以用更生动的语言重新表述，突出游戏的特色和亮点
  3. 保持原有格式结构，只润色文字内容
  4. 语言要生动有趣但不过于夸张
  5. 如果游戏有中文版，可以适当提及对中文玩家的友好性
  6. 总长度控制在400字以内
```

### 配置项说明

- `enabled`: 控制插件是否启用
- `priority`: 插件执行优先级，数值越大越先执行
- `gal_tag`: 自定义触发标签，用户消息包含此标签时触发查询
- `use_ai_enhancement`: 启用后，AI会对游戏简介进行润色，使内容更生动有趣
- `ai_system_prompt`: AI系统提示词，可以自定义AI的回复风格和要求

## 依赖

- `aiohttp`: HTTP 异步请求
- 月幕Gal API: 游戏数据来源
- DeepSeek API: AI内容增强（可选）

## 注意事项

1. 插件会自动清理用户输入中的 @ 提及标记
2. AI增强功能需要配置DeepSeek API密钥
3. AI增强失败时会自动降级到原始信息显示
4. 查询关键词建议使用游戏的正式名称以获得最佳匹配结果
5. 可以通过修改 `ai_system_prompt` 来自定义AI的回复风格，例如：
   - 更加专业严肃的介绍风格
   - 更加轻松幽默的评论风格
   - 针对特定受众群体的介绍方式

## 致谢
本插件移植自 [astrbot_plugin_galinfo](https://github.com/Hxfrzc/astrbot_plugin_galinfo)
