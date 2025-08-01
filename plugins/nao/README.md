# Nao 识图插件

## 功能描述

使用 SauceNAO 识图引擎搜索图片来源，特别适合识别二次元图片、动漫截图、插画等。

## 功能特点

- 🔍 支持高精度图片相似度搜索
- 🎨 专门优化二次元图片识别
- 📚 搜索多个图片数据库
- 🆓 支持免费额度使用
- 🔑 支持 API 密钥提升搜索限制

## 支持的数据库

- Pixiv
- Danbooru
- Gelbooru
- Yande.re
- Konachan
- Anime Screenshots
- H-Magazines
- 等更多数据库...

## 使用方法

### 基础使用
1. 复制 `config.yaml.example` 为 `config.yaml`
2. 在 Misskey 中 @机器人 并发送包含图片的消息
3. 或者在聊天中直接发送图片给机器人

### 配置 API 密钥（可选）
1. 访问 [SauceNAO](https://saucenao.com/user.php) 注册账号
2. 获取 API 密钥
3. 在 `config.yaml` 中设置 `api_key`
4. 或设置环境变量 `SAUCENAO_API_KEY`

## 配置选项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | Boolean | `true` | 是否启用插件 |
| `priority` | Integer | `50` | 插件优先级 |
| `api_key` | String | 空 | SauceNAO API 密钥（可选） |

## 响应格式

插件会返回找到的最佳匹配结果，包含：
- 🔍 相似度百分比
- 📝 作品标题
- 👤 作者信息
- 🔗 来源链接
- 📚 数据库名称

## 限制说明

### 免费使用限制
- 每 24 小时 200 次搜索
- 每 30 秒最多 6 次搜索

### API 密钥限制
- 每 24 小时 2000 次搜索
- 每 30 秒最多 20 次搜索

## 注意事项

1. **隐私保护**: 插件不会存储上传的图片
2. **搜索准确性**: 相似度越高结果越准确
3. **网络依赖**: 需要稳定的网络连接访问 SauceNAO
4. **图片格式**: 支持常见图片格式 (JPG, PNG, GIF, WebP)

## 故障排除

### 常见错误
- **"没有找到相似的图片"**: 图片可能不在数据库中或相似度过低
- **API 限制**: 达到搜索次数限制，等待重置或使用 API 密钥
- **网络错误**: 检查网络连接和 SauceNAO 服务状态

### 调试
查看日志文件中的 `NaoImageSearchPlugin` 相关信息以获取详细错误信息。
