#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

from loguru import logger

from src.plugin_base import PluginBase


class StatusPlugin(PluginBase):
    description = "在线时间统计插件，统计机器人每日在线时间并定时发布统计结果"

    def __init__(self, context):
        super().__init__(context)
        # 配置参数
        self.enabled = self.config.get("enabled", True)
        self.auto_post_enabled = self.config.get("auto_post_enabled", True)
        self.manual_trigger_enabled = self.config.get("manual_trigger_enabled", True)
        
        # 发布时间配置
        self.post_hour = self.config.get("post_hour", 0)  # 每天0点发布
        self.post_minute = self.config.get("post_minute", 0)
        
        # 标签配置
        self.status_tag = self.config.get("status_tag", "#status")
        self.auto_tag = self.config.get("auto_tag", "#dailystatus")
        
        # 消息模板
        self.message_template = self.config.get("message_template", 
            "📊 昨日在线时间统计\n\n"
            "⏰ 在线时长：{online_hours}小时{online_minutes}分钟\n"
            "📈 在线率：{online_percentage:.1f}%\n"
            "🔄 重连次数：{reconnection_count}次\n"
            "⏱️ 最长连续在线：{max_continuous_hours}小时{max_continuous_minutes}分钟\n\n"
            "日期：{date} {auto_tag}")
        
        # 内部状态
        self.session_start_time = None
        self.daily_online_time = timedelta()  # 当日累计在线时间
        self.last_post_date = None  # 上次发布日期
        self.daily_reconnections = 0  # 当日重连次数
        self.current_session_start = None  # 当前会话开始时间
        self.max_continuous_time = timedelta()  # 最长连续在线时间
        self.today_max_continuous = timedelta()  # 今日最长连续在线时间
        
        # 插件数据目录
        self.plugin_dir = Path(__file__).parent
        self.data_dir = self.plugin_dir / "data"
        self.data_dir.mkdir(exist_ok=True)

    async def initialize(self) -> bool:
        try:
            if not self.persistence_manager:
                logger.error("Status 插件未获得 persistence_manager 实例")
                return False
            
            # 初始化数据库表
            await self._initialize_database()
            
            # 恢复今日的统计数据
            await self._load_today_stats()
            
            # 记录插件启动时间
            self.current_session_start = datetime.now(timezone.utc)
            
            self._log_plugin_action(
                "初始化完成", 
                f"自动发布: {'启用' if self.auto_post_enabled else '禁用'}, "
                f"手动触发: {'启用' if self.manual_trigger_enabled else '禁用'}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Status 插件初始化失败: {e}")
            return False

    async def _initialize_database(self):
        """初始化数据库表"""
        conn = await self.persistence_manager._pool.get_connection()
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS status_daily_stats (
                    date TEXT PRIMARY KEY,
                    online_seconds INTEGER DEFAULT 0,
                    reconnection_count INTEGER DEFAULT 0,
                    max_continuous_seconds INTEGER DEFAULT 0,
                    last_session_start TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS status_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    duration_seconds INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await conn.commit()
        finally:
            await self.persistence_manager._pool.return_connection(conn)

    async def _load_today_stats(self):
        """加载今日统计数据"""
        today = datetime.now(timezone.utc).date().isoformat()
        
        conn = await self.persistence_manager._pool.get_connection()
        try:
            cursor = await conn.execute(
                "SELECT online_seconds, reconnection_count, max_continuous_seconds, last_session_start "
                "FROM status_daily_stats WHERE date = ?",
                (today,)
            )
            row = await cursor.fetchone()
            
            if row:
                self.daily_online_time = timedelta(seconds=row[0])
                self.daily_reconnections = row[1]
                self.today_max_continuous = timedelta(seconds=row[2])
                
                # 如果有未结束的会话，继续计时
                if row[3]:
                    try:
                        self.current_session_start = datetime.fromisoformat(row[3])
                        logger.info(f"恢复未结束的会话，开始时间: {self.current_session_start}")
                    except ValueError:
                        logger.warning("无法解析上次会话开始时间，重新开始计时")
                        self.current_session_start = datetime.now(timezone.utc)
            else:
                # 创建今日记录
                await conn.execute(
                    "INSERT INTO status_daily_stats (date, last_session_start) VALUES (?, ?)",
                    (today, datetime.now(timezone.utc).isoformat())
                )
                await conn.commit()
        finally:
            await self.persistence_manager._pool.return_connection(conn)

    async def on_startup(self) -> None:
        """机器人启动时调用"""
        logger.info("Status 插件检测到机器人启动")
        
        # 如果有未结束的会话，先结束它（这意味着上次是异常关闭）
        if self.current_session_start:
            self.daily_reconnections += 1
            await self._end_current_session()
            logger.info("检测到未正常结束的会话，已计入重连次数")
        
        # 开始新会话
        self.current_session_start = datetime.now(timezone.utc)
        await self._update_session_start()

    async def on_shutdown(self) -> None:
        """机器人关闭时调用"""
        logger.info("Status 插件检测到机器人关闭")
        if self.current_session_start:
            await self._end_current_session()

    async def on_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理消息，检查是否为手动触发状态统计"""
        if not self.manual_trigger_enabled:
            return None
            
        try:
            # 获取消息文本
            text = message_data.get("text", "").strip()
            
            # 检查是否包含状态标签
            if self.status_tag in text:
                logger.info(f"检测到手动触发状态统计请求: {text}")
                
                # 生成昨日统计报告
                report = await self._generate_yesterday_report()
                if report:
                    return {
                        "handled": True,
                        "plugin_name": self.name,
                        "response": report
                    }
                else:
                    return {
                        "handled": True,
                        "plugin_name": self.name,
                        "response": "抱歉，无法生成昨日统计报告，可能还没有足够的数据。"
                    }
            
        except Exception as e:
            logger.error(f"Status 插件处理消息失败: {e}")
            return None

    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        """自动发布功能和状态保存"""
        if not self.auto_post_enabled:
            # 即使不自动发布，也要定期保存状态
            await self._save_current_state()
            return None
            
        try:
            now = datetime.now(timezone.utc)
            
            # 检查是否到了发布时间
            if (now.hour == self.post_hour and 
                now.minute >= self.post_minute and 
                now.minute < self.post_minute + 5):  # 5分钟窗口期
                
                today = now.date().isoformat()
                
                # 检查今天是否已经发布过
                if self.last_post_date != today:
                    logger.info("开始生成每日在线时间统计报告")
                    
                    # 生成昨日统计报告
                    report = await self._generate_yesterday_report()
                    if report:
                        self.last_post_date = today
                        return {
                            "handled": True,
                            "plugin_name": self.name,
                            "response": report
                        }
            else:
                # 不是发布时间，定期保存当前状态
                await self._save_current_state()
            
        except Exception as e:
            logger.error(f"Status 插件自动发布失败: {e}")
            
        return None

    async def _save_current_state(self):
        """保存当前会话状态，用于异常恢复"""
        if not self.current_session_start:
            return
            
        try:
            now = datetime.now(timezone.utc)
            session_duration = now - self.current_session_start
            current_total_time = self.daily_online_time + session_duration
            current_max_continuous = max(self.today_max_continuous, session_duration)
            
            today = now.date().isoformat()
            
            conn = await self.persistence_manager._pool.get_connection()
            try:
                await conn.execute(
                    "UPDATE status_daily_stats SET "
                    "online_seconds = ?, max_continuous_seconds = ?, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE date = ?",
                    (
                        int(current_total_time.total_seconds()),
                        int(current_max_continuous.total_seconds()),
                        today
                    )
                )
                await conn.commit()
            finally:
                await self.persistence_manager._pool.return_connection(conn)
                
        except Exception as e:
            logger.error(f"保存当前状态失败: {e}")

    async def _generate_yesterday_report(self) -> Optional[str]:
        """生成昨日统计报告"""
        try:
            # 先结束当前会话并保存今日数据
            if self.current_session_start:
                await self._end_current_session()
            
            # 获取昨日数据
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
            
            conn = await self.persistence_manager._pool.get_connection()
            try:
                cursor = await conn.execute(
                    "SELECT online_seconds, reconnection_count, max_continuous_seconds "
                    "FROM status_daily_stats WHERE date = ?",
                    (yesterday,)
                )
                row = await cursor.fetchone()
            finally:
                await self.persistence_manager._pool.return_connection(conn)
                
                if not row:
                    logger.warning(f"未找到昨日({yesterday})的统计数据")
                    return None
                
                online_seconds, reconnection_count, max_continuous_seconds = row
                
                # 计算统计数据
                online_time = timedelta(seconds=online_seconds)
                max_continuous_time = timedelta(seconds=max_continuous_seconds)
                
                online_hours = int(online_time.total_seconds() // 3600)
                online_minutes = int((online_time.total_seconds() % 3600) // 60)
                
                max_continuous_hours = int(max_continuous_time.total_seconds() // 3600)
                max_continuous_minutes = int((max_continuous_time.total_seconds() % 3600) // 60)
                
                # 计算在线率 (一天总共86400秒)
                online_percentage = (online_seconds / 86400) * 100
                
                # 格式化日期
                date_obj = datetime.fromisoformat(yesterday)
                formatted_date = date_obj.strftime("%Y年%m月%d日")
                
                # 生成报告
                report = self.message_template.format(
                    online_hours=online_hours,
                    online_minutes=online_minutes,
                    online_percentage=online_percentage,
                    reconnection_count=reconnection_count,
                    max_continuous_hours=max_continuous_hours,
                    max_continuous_minutes=max_continuous_minutes,
                    date=formatted_date,
                    auto_tag=self.auto_tag
                )
                
                return report
                
        except Exception as e:
            logger.error(f"生成昨日统计报告失败: {e}")
            return None

    async def _update_session_start(self):
        """更新会话开始时间"""
        today = datetime.now(timezone.utc).date().isoformat()
        
        conn = await self.persistence_manager._pool.get_connection()
        try:
            await conn.execute(
                "UPDATE status_daily_stats SET last_session_start = ?, "
                "reconnection_count = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE date = ?",
                (self.current_session_start.isoformat(), self.daily_reconnections, today)
            )
            await conn.commit()
        finally:
            await self.persistence_manager._pool.return_connection(conn)

    async def _end_current_session(self):
        """结束当前会话并保存数据"""
        if not self.current_session_start:
            return
            
        try:
            now = datetime.now(timezone.utc)
            session_duration = now - self.current_session_start
            
            # 累加到今日在线时间
            self.daily_online_time += session_duration
            
            # 更新今日最长连续在线时间
            if session_duration > self.today_max_continuous:
                self.today_max_continuous = session_duration
            
            today = now.date().isoformat()
            
            # 保存会话记录
            conn = await self.persistence_manager._pool.get_connection()
            try:
                # 保存会话记录
                await conn.execute(
                    "INSERT INTO status_sessions (date, start_time, end_time, duration_seconds) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        today,
                        self.current_session_start.isoformat(),
                        now.isoformat(),
                        int(session_duration.total_seconds())
                    )
                )
                
                # 更新日统计
                await conn.execute(
                    "UPDATE status_daily_stats SET "
                    "online_seconds = ?, max_continuous_seconds = ?, reconnection_count = ?, "
                    "last_session_start = NULL, updated_at = CURRENT_TIMESTAMP "
                    "WHERE date = ?",
                    (
                        int(self.daily_online_time.total_seconds()),
                        int(self.today_max_continuous.total_seconds()),
                        self.daily_reconnections,
                        today
                    )
                )
                
                await conn.commit()
            finally:
                await self.persistence_manager._pool.return_connection(conn)
            
            logger.info(f"会话结束，持续时间: {session_duration}, 今日总在线时间: {self.daily_online_time}")
            self.current_session_start = None
            
        except Exception as e:
            logger.error(f"结束会话时发生错误: {e}")

    async def cleanup(self) -> None:
        """清理资源"""
        if self.current_session_start:
            await self._end_current_session()
        await super().cleanup()

    def get_info(self) -> Dict[str, Any]:
        """获取插件信息"""
        info = super().get_info()
        info.update({
            "auto_post_enabled": self.auto_post_enabled,
            "manual_trigger_enabled": self.manual_trigger_enabled,
            "status_tag": self.status_tag,
            "post_time": f"{self.post_hour:02d}:{self.post_minute:02d}",
            "current_session_duration": str(
                datetime.now(timezone.utc) - self.current_session_start
                if self.current_session_start else timedelta()
            ),
            "daily_online_time": str(self.daily_online_time),
            "daily_reconnections": self.daily_reconnections,
        })
        return info
