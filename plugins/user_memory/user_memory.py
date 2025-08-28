from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from src import PluginBase


class UserMemoryPlugin(PluginBase):
    """用户记忆与画像插件。

    设计目标：
    - 低侵入：使用已有 `plugin_data` 表；键命名空间规范化。
    - 可控成本：定期摘要，避免每条消息都调用模型。
    - 可选拦截：允许只记录不回复。
    """

    description = "为用户构建画像与记忆，支持个性化回复"

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
            await self._record_user_message(user_id, text)
            if not self.handle_messages:
                return None
            reply = await self._generate_personalized_reply(user_id, username, text)
            return self._create_response(reply) if reply else None
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
            await self._record_user_message(user_id, text)
            if not self.handle_mentions:
                return None
            reply = await self._generate_personalized_reply(user_id, username, text)
            return self._create_response(reply) if reply else None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory on_mention 失败: {e}")
            return None

    # -------------------------- 核心逻辑 --------------------------

    async def _record_user_message(self, user_id: str, text: str) -> None:
        # stats
        stats_key = self._k_stats(user_id)
        stats_raw = await self.persistence_manager.get_plugin_data(
            self.storage_plugin_name, stats_key
        )
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if stats_raw:
            try:
                stats = json.loads(stats_raw)
            except json.JSONDecodeError:
                stats = {}
        else:
            stats = {}
        count = int(stats.get("count", 0)) + 1
        if not stats.get("first_ts"):
            stats["first_ts"] = now_ts
        stats["last_ts"] = now_ts
        stats["count"] = count
        await self.persistence_manager.set_plugin_data(
            self.storage_plugin_name, stats_key, json.dumps(stats, ensure_ascii=False)
        )

        # messages
        msgs_key = self._k_messages(user_id)
        msgs_raw = await self.persistence_manager.get_plugin_data(
            self.storage_plugin_name, msgs_key
        )
        if msgs_raw:
            try:
                msgs = json.loads(msgs_raw)
            except json.JSONDecodeError:
                msgs = []
        else:
            msgs = []
        msgs.append(text.strip())
        if len(msgs) > self.max_messages:
            msgs = msgs[-self.max_messages :]
        await self.persistence_manager.set_plugin_data(
            self.storage_plugin_name, msgs_key, json.dumps(msgs, ensure_ascii=False)
        )
        if self.debug_log:
            logger.debug(f"[UserMemory] {user_id} 记录消息 #{count}: {text[:40]}")
        # summarization trigger
        if count == 1 or count % self.summary_interval == 0:
            await self._update_summary(user_id, msgs)

    async def _update_summary(self, user_id: str, msgs: list[str] | None = None) -> None:
        summary_key = self._k_summary(user_id)
        if msgs is None:
            raw = await self.persistence_manager.get_plugin_data(
                self.storage_plugin_name, self._k_messages(user_id)
            )
            try:
                msgs = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                msgs = []
        if not msgs:
            return
        keywords = self._extract_keywords(msgs)
        # 构造总结提示
        prompt = (
            "请基于以下用户最近的聊天消息，提炼其兴趣、常用语气、可能的偏好或关注点。"
            "输出精炼中文总结，不超过"
            f"{self.summary_max_length}字。若信息不足请说明‘信息有限’。\n\n"
        )
        numbered = "\n".join(f"{i+1}. {m}" for i, m in enumerate(msgs[-self.max_messages :]))
        prompt += numbered
        if keywords:
            prompt += "\n\n候选关键词: " + ", ".join(keywords)
        try:
            summary = await self.bot.openai.generate_text(prompt)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory 生成 summary 失败: {e}")
            return
        # 截断
        summary = summary.strip().replace("\n", " ")
        if len(summary) > self.summary_max_length:
            summary = summary[: self.summary_max_length].rstrip() + "…"
        await self.persistence_manager.set_plugin_data(
            self.storage_plugin_name, summary_key, summary
        )
        if self.debug_log:
            logger.debug(f"[UserMemory] 更新 summary {user_id}: {summary}")

    async def _generate_personalized_reply(
        self, user_id: str, username: str, text: str
    ) -> Optional[str]:
        # 取 summary
        summary = await self.persistence_manager.get_plugin_data(
            self.storage_plugin_name, self._k_summary(user_id)
        )
        stats_raw = await self.persistence_manager.get_plugin_data(
            self.storage_plugin_name, self._k_stats(user_id)
        )
        stats_info = ""
        if stats_raw:
            try:
                stats = json.loads(stats_raw)
                stats_info = f"交互次数:{stats.get('count')} 首次:{self._fmt_ts(stats.get('first_ts'))} 最近:{self._fmt_ts(stats.get('last_ts'))}"
            except json.JSONDecodeError:  # noqa: PERF203
                pass
        memory_block = ""
        if summary:
            memory_block = f"\n\n{self.system_memory_prefix}\n用户画像: {summary}\n{stats_info}".strip()
        system_prompt = (self.bot.system_prompt or "").strip() + memory_block
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        try:
            reply = await self.bot.openai.generate_chat(messages)
            return reply
        except Exception as e:  # noqa: BLE001
            logger.warning(f"UserMemory 个性化回复失败: {e}")
            return None

    # -------------------------- 工具函数 --------------------------

    def _create_response(self, response_text: str) -> Optional[dict[str, Any]]:
        try:
            response = {
                "handled": True,
                "plugin_name": self.name,
                "response": response_text,
            }
            return response if self._validate_plugin_response(response) else None
        except Exception as e:  # noqa: BLE001
            logger.error(f"UserMemory 创建响应失败: {e}")
            return None

    def _extract_keywords(self, msgs: list[str]) -> list[str]:
        text = " ".join(msgs)
        # 简单分词：按非字母数字汉字分割
        tokens = [
            t
            for t in re.split(r"[^0-9A-Za-z\u4e00-\u9fa5]+", text)
            if len(t) >= self.min_kw_len
        ]
        freq = {}
        for tok in tokens:
            freq[tok] = freq.get(tok, 0) + 1
        # 排序：频次 -> 长度 -> 字典序
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

    def _k_stats(self, uid: str) -> str:  # key helpers
        return f"user:{uid}:stats"

    def _k_messages(self, uid: str) -> str:
        return f"user:{uid}:messages"

    def _k_summary(self, uid: str) -> str:
        return f"user:{uid}:summary"

    # -------------------------- 预处理助手 --------------------------

    def _contains_hashtag(self, text: str) -> bool:
        """检测文本是否含 # / ＃ 任一字符；含则视为 hashtag 信息整条跳过。"""
        return "#" in text or "＃" in text
