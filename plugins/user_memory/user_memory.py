from __future__ import annotations
import json
import re
import textwrap
from dataclasses import asdict, dataclass, field
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional
from loguru import logger
from src import PluginBase

# 类型声明（用于类型检查）
from src.persistence import PersistenceManager

class MockOpenAI:
    """Mock OpenAI 类用于类型检查"""
    async def generate_text(self, prompt: str) -> str:
        return ""
    
    async def generate_chat(self, messages: list[dict[str, str]]) -> str:
        return ""

class MockBot:
    """Mock 类用于类型检查"""
    def __init__(self):
        self.system_prompt = ""
        self.openai = MockOpenAI()

# 统一 token 正则（仅一次编译）
_TOKEN_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fa5]+")

@dataclass
class _UserData:
    stats: dict[str, Any] = field(default_factory=dict)  # count, first_ts, last_ts, username, etc.
    messages: list[str] = field(default_factory=list)
    summary: str = ""
    profile: dict[str, Any] = field(default_factory=dict)  # 多方面用户画像

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> "_UserData":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            return cls(
                stats=data.get("stats", {}) or {},
                messages=data.get("messages", []) or [],
                summary=data.get("summary", "") or "",
                profile=data.get("profile", {}) or {},
            )
        except json.JSONDecodeError:
            return cls()


class UserMemoryPlugin(PluginBase):
    description = "为用户构建画像与记忆，支持个性化回复"
    
    # 声明动态设置的属性（用于类型检查）
    persistence_manager: PersistenceManager
    bot: MockBot

    def __init__(self, context):  # type: ignore[no-untyped-def]
        super().__init__(context)
        cfg = self.config
        self.handle_messages = cfg.get("handle_messages", True)
        self.handle_mentions = cfg.get("handle_mentions", True)
        self.max_messages = cfg.get("max_messages_per_user", 30)
        self.summary_interval = max(1, cfg.get("summary_interval", 5))
        self.summary_max_length = cfg.get("summary_max_length", 120)
        self.keywords_top_n = cfg.get("keywords_top_n", 8)
        self.min_kw_len = cfg.get("min_keyword_length", 2)
        self.system_memory_prefix = cfg.get(
            "system_memory_prefix", "请结合以下用户画像做出更个性化、贴合其兴趣与语气的回复。"
        )
        self.debug_log = cfg.get("debug_log", False)
        # 是否忽略含 hashtag 的消息（避免与依赖 #tag 的其他插件冲突）
        self.ignore_hashtag_messages = cfg.get("ignore_hashtag_messages", True)
        # 统一插件名（PluginContext 已设定 Name=User_memory => capitalize 可能不同）
        self.storage_plugin_name = "UserMemory"  # DB 中使用统一名字
        # 内存缓存：user_id -> _UserData
        self._user_cache: dict[str, _UserData] = {}
        # 用户名到用户ID的映射缓存：username -> user_id
        self._username_cache: dict[str, str] = {}

    async def initialize(self) -> bool:  # type: ignore[override]
        if not getattr(self, "persistence_manager", None):
            logger.error("UserMemory 插件缺少 persistence_manager")
            return False
        if not getattr(self, "bot", None):
            logger.error("UserMemory 插件缺少 bot 引用以调用 OpenAI")
            return False
        self._log_plugin_action(
            "初始化完成",
            f"messages={self.max_messages} interval={self.summary_interval} handle_msg={self.handle_messages} handle_mention={self.handle_mentions}",
        )
        return True

    # -------------------------- 事件入口 --------------------------

    async def on_message(self, message_data: dict[str, Any]) -> Optional[dict[str, Any]]:  # type: ignore[override]
        try:
            user_id = self._extract_user_id(message_data)
            text = message_data.get("text") or message_data.get("content") or ""
            if not (user_id and text.strip()):
                return None
            if self.ignore_hashtag_messages and self._contains_hashtag(text):
                if self.debug_log:
                    logger.debug("[UserMemory] 跳过含 hashtag 的消息: %s", text[:60])
                return None
            username = self._extract_username(message_data)
            # 仅记录原文本（不去掉 hashtag；因为含 hashtag 的已被跳过）
            await self._record_user_message(user_id, text, username)
            if not self.handle_messages:
                return None
            reply = await self._generate_personalized_reply(user_id, username, text)
            if reply:
                return {"handled": True, "plugin_name": self.name, "response": reply}
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory on_message 失败: {e}")
            return None

    async def on_mention(self, mention_data: dict[str, Any]) -> Optional[dict[str, Any]]:  # type: ignore[override]
        try:
            # bot._process_mention 里传入的是完整 note 数据；文本在 note.note.text 或 note.text
            note = mention_data.get("note") or mention_data
            text = note.get("text", "")
            user = note.get("user") or note.get("fromUser") or {}
            user_id = user.get("id") or note.get("userId")
            if not (user_id and text.strip()):
                return None
            if self.ignore_hashtag_messages and self._contains_hashtag(text):
                if self.debug_log:
                    logger.debug("[UserMemory] 跳过含 hashtag 的提及: %s", text[:60])
                return None
            username = user.get("username", "unknown")
            await self._record_user_message(user_id, text, username)
            if not self.handle_mentions:
                return None
            reply = await self._generate_personalized_reply(user_id, username, text)
            if reply:
                return {"handled": True, "plugin_name": self.name, "response": reply}
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory on_mention 失败: {e}")
            return None

    # -------------------------- 核心逻辑 --------------------------

    async def _record_user_message(self, user_id: str, text: str, username: str = "") -> None:
        """记录用户消息并更新统计信息"""
        data = await self._ensure_cache(user_id)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        stats = data.stats
        count = int(stats.get("count", 0)) + 1
        if not stats.get("first_ts"):
            stats["first_ts"] = now_ts
        stats["last_ts"] = now_ts
        stats["count"] = count
        # 更新用户名映射
        if username and username != "unknown":
            stats["username"] = username
            self._username_cache[username] = user_id
            await self.persistence_manager.set_plugin_data(  # type: ignore[attr-defined]
                self.storage_plugin_name, self._k_username(username), user_id
            )
        # 更新消息
        data.messages.append(text.strip())
        if len(data.messages) > self.max_messages:
            data.messages = data.messages[-self.max_messages :]
        # 触发条件合并
        if count % self.summary_interval == 0 or count == 1:
            await self._update_summary(user_id, data)
        # 单 key 写回（一次 I/O）
        await self._save_user_data(user_id, data)
        if self.debug_log:
            logger.debug(f"[UserMemory] {user_id} 记录消息 #{count}: {text[:40]}")

    async def _update_summary(self, user_id: str, data: _UserData) -> None:
        msgs = data.messages
        if not msgs:
            return
        keywords = self._extract_keywords(msgs)
        # 构造更详细的总结提示
        prompt = (
            "请基于以下用户最近的聊天消息，提炼用户的多方面信息，包括但不限于：\n"
            "- 兴趣爱好和关注话题\n"
            "- 常用语气和表达风格\n"
            "- 情感倾向（积极/消极/中性）\n"
            "- 互动频率和时间偏好\n"
            "- 可能的职业或身份特征\n"
            "- 特殊偏好或忌讳\n\n"
            "输出精炼中文总结，为其构建全面用户画像，不超过"
            f"{self.summary_max_length}字。若信息不足请说明'信息有限'。\n\n"
        )
        numbered = "\n".join(f"{i+1}. {m}" for i, m in enumerate(msgs[-self.max_messages :]))
        prompt += numbered
        if keywords:
            prompt += "\n\n候选关键词: " + ", ".join(keywords)
        try:
            summary = await self.bot.openai.generate_text(prompt)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory 生成 summary 失败: {e}")
            return
        # 截断交给 textwrap.shorten（保持占位符 …）
        summary = textwrap.shorten(
            summary.strip().replace("\n", " "),
            width=self.summary_max_length,
            placeholder="…",
        )
        data.summary = summary
        # 更新多方面画像
        await self._update_profile(user_id, data, keywords)
        await self._save_user_data(user_id, data)
        if self.debug_log:
            logger.debug(f"[UserMemory] 更新 summary {user_id}: {summary}")

    async def _generate_personalized_reply(
        self, user_id: str, username: str, text: str
    ) -> Optional[str]:
        data = await self._ensure_cache(user_id)
        stats = data.stats
        stats_info = (
            f"交互次数:{stats.get('count')} 首次:{self._fmt_ts(stats.get('first_ts'))} 最近:{self._fmt_ts(stats.get('last_ts'))}"
            if stats.get("count")
            else ""
        )
        memory_block = (
            f"\n\n{self.system_memory_prefix}\n用户画像: {data.summary}\n{stats_info}".strip()
            if data.summary
            else ""
        )
        system_prompt = (self.bot.system_prompt or "").strip() + memory_block  # type: ignore[attr-defined]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        try:
            reply = await self.bot.openai.generate_chat(messages)  # type: ignore[attr-defined]
            return reply
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory 个性化回复失败: {e}")
            return None

    # -------------------------- 工具函数 --------------------------

    def _extract_keywords(self, msgs: list[str]) -> list[str]:
        text = " ".join(msgs)
        tokens = [t for t in _TOKEN_RE.split(text) if len(t) >= self.min_kw_len]
        if not tokens:
            return []
        freq = Counter(tokens)
        ranked = sorted(
            freq.items(), key=lambda x: (-x[1], -len(x[0]), x[0])
        )[: self.keywords_top_n]
        return [w for w, _ in ranked]

    def _fmt_ts(self, ts: Any) -> str:
        try:
            if not ts:
                return "-"
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
                "%m-%d %H:%M"
            )
        except Exception:  # noqa: BLE001
            return "-"

    def _k_user(self, uid: str) -> str:  # 统一 key
        return f"user:{uid}:data"

    def _k_username(self, username: str) -> str:  # 用户名映射 key
        return f"username:{username}:user_id"

    async def _update_profile(self, user_id: str, data: _UserData, keywords: list[str]) -> None:
        """更新多方面用户画像"""
        profile = data.profile
        stats = data.stats
        
        # 基础统计信息
        profile["interaction_count"] = stats.get("count", 0)
        profile["first_interaction"] = self._fmt_ts(stats.get("first_ts"))
        profile["last_interaction"] = self._fmt_ts(stats.get("last_ts"))
        profile["username"] = stats.get("username", "unknown")
        
        # 关键词分析
        if keywords:
            profile["top_keywords"] = keywords[:5]  # 保留前5个关键词
        
        # 情感倾向分析（基于关键词和表情符号）
        positive_words = ["喜欢", "好", "棒", "不错", "开心", "快乐", "感谢", "谢谢", "爱", "喜欢", "完美", "优秀"]
        negative_words = ["讨厌", "不好", "差", "生气", "难过", "烦", "讨厌", "糟糕", "失望", "生气", "愤怒"]
        neutral_words = ["一般", "还可以", "普通", "正常"]
        
        text = " ".join(data.messages).lower()
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        neutral_count = sum(1 for word in neutral_words if word in text)
        
        # 加入表情符号分析
        positive_emojis = ["😊", "😄", "😍", "👍", "❤️", "🎉", "😎"]
        negative_emojis = ["😢", "😭", "😠", "👎", "💔", "😞", "😡"]
        
        positive_emoji_count = sum(1 for emoji in positive_emojis if emoji in text)
        negative_emoji_count = sum(1 for emoji in negative_emojis if emoji in text)
        
        total_positive = positive_count + positive_emoji_count
        total_negative = negative_count + negative_emoji_count
        
        if total_positive > total_negative + 1:  # 稍微倾向积极
            profile["sentiment"] = "积极"
        elif total_negative > total_positive + 1:  # 稍微倾向消极
            profile["sentiment"] = "消极"
        elif neutral_count > 0 or (total_positive > 0 and total_negative > 0):
            profile["sentiment"] = "中性"
        else:
            profile["sentiment"] = "未知"
        
        # 时间偏好分析
        if stats.get("first_ts") and stats.get("last_ts"):
            first_hour = datetime.fromtimestamp(stats["first_ts"], tz=timezone.utc).hour
            last_hour = datetime.fromtimestamp(stats["last_ts"], tz=timezone.utc).hour
            profile["active_hours"] = f"{first_hour:02d}:00-{last_hour:02d}:00"
        
        data.profile = profile

    # -------------------------- 预处理助手 --------------------------

    def _contains_hashtag(self, text: str) -> bool:
        """检测文本是否含 # / ＃ 任一字符；含则视为 hashtag 信息整条跳过。"""
        return "#" in text or "＃" in text

    # -------------------------- 缓存与 JSON 工具 --------------------------

    async def _ensure_cache(self, user_id: str) -> _UserData:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        # 优先读统一 key
        raw = await self.persistence_manager.get_plugin_data(  # type: ignore[attr-defined]
            self.storage_plugin_name, self._k_user(user_id)
        )
        data = _UserData.from_json(raw)
        # 兼容旧数据：若 messages 或 stats 为空且存在旧 key，则尝试迁移（只在首次）
        if not data.messages and not data.stats:
            old_stats = await self.persistence_manager.get_plugin_data(  # type: ignore[attr-defined]
                self.storage_plugin_name, f"user:{user_id}:stats"
            )
            old_msgs = await self.persistence_manager.get_plugin_data(  # type: ignore[attr-defined]
                self.storage_plugin_name, f"user:{user_id}:messages"
            )
            old_summary = await self.persistence_manager.get_plugin_data(  # type: ignore[attr-defined]
                self.storage_plugin_name, f"user:{user_id}:summary"
            )
            # 解析
            data.stats = self._safe_json(old_stats, {}) or {}
            data.messages = self._safe_json(old_msgs, []) or []
            if old_summary:
                data.summary = old_summary or ""
            if data.stats or data.messages or data.summary:
                await self._save_user_data(user_id, data)
        self._user_cache[user_id] = data
        return data

    async def _save_user_data(self, user_id: str, data: _UserData) -> None:
        await self.persistence_manager.set_plugin_data(  # type: ignore[attr-defined]
            self.storage_plugin_name, self._k_user(user_id), data.to_json()
        )

    def _safe_json(self, raw: str | None, default: Any) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    async def get_user_by_username(self, username: str) -> Optional[str]:
        """通过用户名获取用户ID"""
        if username in self._username_cache:
            return self._username_cache[username]
        
        # 从数据库查询
        user_id = await self.persistence_manager.get_plugin_data(  # type: ignore[attr-defined]
            self.storage_plugin_name, self._k_username(username)
        )
        if user_id:
            self._username_cache[username] = user_id
            return user_id
        return None

    async def get_user_profile(self, identifier: str) -> Optional[dict[str, Any]]:
        """通过用户ID或用户名获取用户画像"""
        user_id = None
        
        # 检查是否是用户名（以@开头）
        if identifier.startswith('@'):
            username = identifier[1:]  # 去掉@
            user_id = await self.get_user_by_username(username)
            if self.debug_log:
                logger.debug(f"[UserMemory] 通过用户名 {username} 找到用户ID: {user_id}")
        else:
            user_id = identifier
        
        if not user_id:
            if self.debug_log:
                logger.debug(f"[UserMemory] 未找到用户: {identifier}")
            return None
            
        data = await self._ensure_cache(user_id)
        profile_data = {
            "user_id": user_id,
            "username": data.stats.get("username", "unknown"),
            "summary": data.summary,
            "profile": data.profile,
            "stats": data.stats,
            "recent_messages": data.messages[-5:] if data.messages else []
        }
        
        if self.debug_log:
            logger.debug(f"[UserMemory] 获取用户画像: {user_id}, 消息数: {len(data.messages)}")
        
        return profile_data
