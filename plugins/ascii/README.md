# ASCII Art Plugin

将图片转换为ASCII艺术的插件。

## 功能

- 当回复中包含指定标签且带有图片时，自动将图片转换为ASCII艺术
- 支持各种图片格式（JPEG、PNG、GIF等）
- 可配置ASCII艺术的宽度、高度、字符集和触发标签

## 配置

```yaml
enabled: true        # 是否启用插件
priority: 40         # 插件优先级
width: 80           # ASCII艺术的宽度（字符数）
height: 40          # ASCII艺术的最大高度（字符数）
chars: " .:-=+*#%@" # 用于生成ASCII艺术的字符集，从暗到亮
tag: "#ascii"       # 触发ASCII转换的标签，可自定义
```

## 使用方法

1. 在回复中添加图片
2. 在回复文本中包含配置的触发标签（默认为 `#ascii`）
3. 机器人会自动将图片转换为ASCII艺术并回复

## 自定义触发标签

你可以在 `config.yaml` 中修改 `tag` 字段来自定义触发标签：

```yaml
tag: "#art"      # 使用 #art 作为触发标签
tag: "转ascii"    # 使用中文标签
tag: "ascii me"  # 使用多词标签
```

## 依赖

- Pillow: 用于图片处理
- aiohttp: 用于下载图片

## 注意事项

- 图片会被下载到内存中处理，对于大图片可能消耗较多内存
- ASCII艺术的质量取决于原图的对比度和内容
- 建议原图具有清晰的轮廓和较好的对比度以获得更好的效果
