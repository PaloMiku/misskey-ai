from __future__ import annotations

from enum import IntEnum

__all__ = [
	"ErrorCode",
	"DEFAULT_SIMILARITY",
	"DEFAULT_AI_SYSTEM_PROMPT",
	"DEFAULT_AUTO_POST_SYSTEM_PROMPT",
	"DEFAULT_AUTO_POST_USER_PROMPT",
]


class ErrorCode(IntEnum):
	PARAM_ERROR = 614


# 搜索相似度默认值（原先 DEFAULT_SIMILARITY = 70）
DEFAULT_SIMILARITY: int = 70

# ===== 默认提示词（保持原文，不修改以避免行为变更） =====
DEFAULT_AI_SYSTEM_PROMPT = """你是一个专业的Galgame(美少女游戏)评论专家。请根据用户提供的游戏基本信息，用更生动、有趣的语言重新整理和润色内容，让介绍更加吸引人。

  要求：
  1. 保持所有事实信息准确，不要编造内容
  2. 简介部分可以用更生动的语言重新表述，突出游戏的特色和亮点
  3. 保持原有格式结构，只润色简介内容，其他内容不要改变
  4. 语言要生动有趣但不过于夸张
  5. 如果游戏有中文版，可以适当提及对中文玩家的友好性
  6. 总长度控制在400字以内
  7. 由于 Misskey 不支持列表语法，会导致解析器出错，因此禁止使用。列举时请使用「・」。
"""

DEFAULT_AUTO_POST_SYSTEM_PROMPT = """你是一个热爱Galgame的玩家，正在社交媒体上分享你最近游玩某个游戏的体验和感受。请基于提供的游戏信息，以第一人称的视角写一篇自然、真实的游戏体验分享。

要求：
1. 以第一人称视角，就像真的在玩这个游戏一样
2. 可以提及游戏的剧情、角色、画风、音乐等方面的感受
3. 语言要自然随意，像平时和朋友聊天一样
4. 可以包含一些个人情感和主观评价
5. 不要复述游戏的基本信息，而是写游玩感受
6. 长度控制在150-300字之间
7. 由于 Misskey 不支持列表语法，禁止使用。可以用「・」来替代
8. 可以适当使用一些网络用语和表情符合当代社交媒体风格
9. 不要透露这是AI生成的内容，要像真人发的一样自然
"""

DEFAULT_AUTO_POST_USER_PROMPT = (
	"请基于以下游戏信息，写一篇游玩体验分享：\n\n{game_info}\n\n请以自然的语气分享你对这个游戏的感受和体验。"
)


def build_cache_key(game_name: str, ai: bool) -> str:
	"""统一的缓存 key 生成函数。

	Args:
		game_name: 游戏名称（已精确匹配）
		ai: 是否为 AI 增强内容
	"""
	return f"{game_name}_{'AI' if ai else 'original'}"


def quote_keyword(keyword: str) -> str:
	"""清洗并 URL 编码关键词（保持与原逻辑等价）"""
	from urllib.parse import quote

	return quote(keyword.strip())

