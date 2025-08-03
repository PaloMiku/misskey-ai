#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import logging

logger = logging.getLogger("scheduler")

from src.plugin_base import PluginBase


class SchedulerPlugin(PluginBase):
    description = "定时调度插件，支持每日发送、节日发送以及机器人启动时发送预设内容"

    def __init__(self, context):
        super().__init__(context)
        # 配置参数
        self.enabled = self.config.get("enabled", True)
        self.daily_enabled = self.config.get("daily_enabled", True)
        self.holiday_enabled = self.config.get("holiday_enabled", True)
        self.startup_enabled = self.config.get("startup_enabled", True)
        
        # 每日发送配置
        self.daily_hour = self.config.get("daily_hour", 0)  # 每天0点发送
        self.daily_minute = self.config.get("daily_minute", 0)
        
        # 预设内容
        self.daily_messages = self.config.get("daily_messages", [])
        self.holiday_messages = self.config.get("holiday_messages", {})
        self.startup_messages = self.config.get("startup_messages", [])
        
        # 内部状态
        self.last_startup_time = None
        self.last_daily_send_date = None

    async def initialize(self) -> bool:
        try:
            if not self.persistence_manager:
                logger.error("Scheduler 插件未获得 persistence_manager 实例")
                return False
            
            # 初始化插件数据
            await self._initialize_plugin_data()
            
            self._log_plugin_action(
                "初始化完成", 
                f"每日发送: {'启用' if self.daily_enabled else '禁用'}, "
                f"节日发送: {'启用' if self.holiday_enabled else '禁用'}, "
                f"启动发送: {'启用' if self.startup_enabled else '禁用'}"
            )
            return True
        except Exception as e:
            logger.error(f"Scheduler 插件初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        await super().cleanup()

    async def on_startup(self) -> None:
        """机器人启动时的处理"""
        if not self.startup_enabled or not self.startup_messages:
            return

        try:
            # 记录启动时间
            current_time = datetime.now(timezone.utc)
            # 检查上一次启动时间，若5分钟内则不发送
            last_startup_str = await self.persistence_manager.get_plugin_data(
                self.name, "last_startup_time"
            )
            if last_startup_str:
                try:
                    last_startup_time = datetime.fromisoformat(last_startup_str)
                    delta = (current_time - last_startup_time).total_seconds()
                    if delta < 300:  # 5分钟=300秒
                        self._log_plugin_action("启动处理", "距离上次启动不足5分钟，不发送启动消息")
                        return
                except Exception as e:
                    logger.warning(f"解析 last_startup_time 失败: {e}")

            self.last_startup_time = current_time
            await self.persistence_manager.set_plugin_data(
                self.name, "last_startup_time", current_time.isoformat()
            )

            # 标记有启动消息需要发送
            await self.persistence_manager.set_plugin_data(
                self.name, "should_send_startup", "true"
            )

            self._log_plugin_action("启动处理", "已标记启动消息待发送")

        except Exception as e:
            logger.error(f"Scheduler 插件处理启动事件失败: {e}")

    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        """自动发帖时的处理"""
        try:
            current_time = datetime.now(timezone.utc)
            current_date = current_time.date()
            
            # 检查是否有启动消息需要发送
            should_send_startup = await self.persistence_manager.get_plugin_data(
                self.name, "should_send_startup"
            )
            if should_send_startup == "true":
                # 发送启动消息
                startup_message = self._get_random_message(self.startup_messages)
                if startup_message:
                    # 清除启动标记
                    await self.persistence_manager.set_plugin_data(
                        self.name, "should_send_startup", "false"
                    )
                    
                    self._log_plugin_action("启动消息", f"发送启动消息: {startup_message[:30]}...")
                    return {
                        "handled": True,
                        "plugin_name": self.name,
                        "content": startup_message
                    }
            
            # 检查是否是节日
            if self.holiday_enabled:
                holiday_message = await self._check_holiday_message(current_time)
                if holiday_message:
                    self._log_plugin_action("节日消息", f"发送节日消息: {holiday_message[:30]}...")
                    return {
                        "handled": True,
                        "plugin_name": self.name,
                        "content": holiday_message
                    }
            
            # 检查是否是每日发送时间
            if self.daily_enabled:
                current_hour = current_time.hour
                current_minute = current_time.minute
                current_second = current_time.second
                window_seconds = 60  # 容忍窗口，单位：秒

                # 只允许在目标分钟的前window_seconds秒内发送
                if (current_hour == self.daily_hour and
                    current_minute == self.daily_minute and
                    self.last_daily_send_date != current_date and
                    current_second < window_seconds):
                    daily_message = self._get_random_message(self.daily_messages)
                    if daily_message:
                        self.last_daily_send_date = current_date
                        await self.persistence_manager.set_plugin_data(
                            self.name, "last_daily_send_date", current_date.isoformat()
                        )
                        self._log_plugin_action("每日消息", f"发送每日消息: {daily_message[:30]}...")
                        return {
                            "handled": True,
                            "plugin_name": self.name,
                            "content": daily_message
                        }
            return None
            
        except Exception as e:
            logger.error(f"Scheduler 插件处理自动发帖失败: {e}")
            return None

    async def _initialize_plugin_data(self) -> None:
        """初始化插件数据"""
        try:
            # 恢复最后发送日期
            last_date_str = await self.persistence_manager.get_plugin_data(
                self.name, "last_daily_send_date"
            )
            if last_date_str:
                self.last_daily_send_date = datetime.fromisoformat(last_date_str).date()
            
            # 恢复最后启动时间
            last_startup_str = await self.persistence_manager.get_plugin_data(
                self.name, "last_startup_time"
            )
            if last_startup_str:
                self.last_startup_time = datetime.fromisoformat(last_startup_str)
                
        except Exception as e:
            logger.error(f"初始化 Scheduler 插件数据失败: {e}")

    async def _check_holiday_message(self, current_time: datetime) -> Optional[str]:
        """检查是否有节日消息需要发送"""
        try:
            # 检查今天是否是配置的节日
            date_key = current_time.strftime("%m-%d")  # 格式如 "01-01", "12-25"
            month_day_key = current_time.strftime("%m月%d日")  # 格式如 "1月1日", "12月25日"
            
            # 检查不同的日期格式
            for key in [date_key, month_day_key]:
                if key in self.holiday_messages:
                    messages = self.holiday_messages[key]
                    if isinstance(messages, list):
                        return self._get_random_message(messages)
                    else:
                        return str(messages)
            
            # 检查特殊节日（可以添加农历节日等复杂逻辑）
            special_holidays = await self._get_special_holidays(current_time)
            for holiday in special_holidays:
                if holiday in self.holiday_messages:
                    messages = self.holiday_messages[holiday]
                    if isinstance(messages, list):
                        return self._get_random_message(messages)
                    else:
                        return str(messages)
            
            return None
            
        except Exception as e:
            logger.error(f"检查节日消息失败: {e}")
            return None

    async def _get_special_holidays(self, current_time: datetime) -> List[str]:
        """获取特殊节日列表（可扩展支持农历等）"""
        special_holidays = []
        
        # 可以在这里添加更复杂的节日逻辑
        # 比如农历节日、星期几相关的节日等
        
        return special_holidays

    def _get_random_message(self, messages: List[str]) -> Optional[str]:
        """从消息列表中随机选择一条消息"""
        if not messages:
            return None
        
        import random
        return random.choice(messages)
