# galinfo 插件

本插件为 misskey-ai 平台提供 Galgame 信息自动查询能力，基于月幕Gal API。

## 功能
发送内容包含自定义标签（如 `#galgame`，可在配置中修改）时，自动提取标签后的内容进行 Galgame 信息模糊搜索，并以纯文本形式回复最匹配结果。

## 配置
请参考 `config.yaml.example` 进行配置，支持如下字段：

- `enabled`: 是否启用本插件
- `priority`: 插件优先级，数值越大越优先
- `gal_tag`: 触发标签，默认为 `#galgame`

## 依赖
- aiohttp

## 致谢
本插件移植自 [astrbot_plugin_galinfo](https://github.com/Hxfrzc/astrbot_plugin_galinfo)
