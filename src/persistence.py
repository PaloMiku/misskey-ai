#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import aiosqlite
from loguru import logger

from .config import Config
from .constants import ConfigKeys


class ConnectionPool:
    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = asyncio.Queue(maxsize=max_connections)
        self._created_connections = 0
        self._lock = asyncio.Lock()

    async def get_connection(self) -> aiosqlite.Connection:
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            async with self._lock:
                if self._created_connections < self.max_connections:
                    conn = await aiosqlite.connect(
                        self.db_path, timeout=30.0, isolation_level=None
                    )
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute("PRAGMA cache_size=10000")
                    await conn.execute("PRAGMA busy_timeout=30000")
                    self._created_connections += 1
                    return conn
            return await self._pool.get()

    async def return_connection(self, conn: aiosqlite.Connection) -> None:
        try:
            self._pool.put_nowait(conn)
        except asyncio.QueueFull:
            await conn.close()
            async with self._lock:
                self._created_connections -= 1

    async def close_all(self) -> None:
        connections = []
        while not self._pool.empty():
            try:
                connections.append(self._pool.get_nowait())
            except asyncio.QueueEmpty:
                break
        for conn in connections:
            await conn.close()
        self._created_connections = 0


class PersistenceManager:
    def __init__(self, db_path: Optional[str] = None, max_connections: int = 10):
        if db_path is None:
            config = Config()
            db_path = config._get_builtin_default(ConfigKeys.DB_PATH)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._pool = ConnectionPool(str(self.db_path), max_connections)
        self._initialized = False

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._create_tables()
        self._initialized = True
        logger.debug(f"持久化管理器已初始化，数据库: {self.db_path}")

    async def close(self) -> None:
        await self._pool.close_all()
        logger.debug("持久化管理器已关闭")

    async def _create_tables(self) -> None:
        conn = await self._pool.get_connection()
        try:
            await self._execute_schema(conn)
        finally:
            await self._pool.return_connection(conn)

    async def _execute_schema(self, conn: aiosqlite.Connection) -> None:
        schema_statements = [
            """
            CREATE TABLE IF NOT EXISTS processed_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id TEXT UNIQUE NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                username TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                chat_type TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS plugin_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(plugin_name, key)
            )
            """,
        ]
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_mentions_note_id ON processed_mentions(note_id)",
            "CREATE INDEX IF NOT EXISTS idx_mentions_processed_at ON processed_mentions(processed_at)",
            "CREATE INDEX IF NOT EXISTS idx_messages_message_id ON processed_messages(message_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_processed_at ON processed_messages(processed_at)",
            "CREATE INDEX IF NOT EXISTS idx_plugin_data_name_key ON plugin_data(plugin_name, key)",
        ]
        async with conn.execute("BEGIN TRANSACTION"):
            for statement in schema_statements:
                await conn.execute(statement)
            for index_sql in index_statements:
                await conn.execute(index_sql)
            await conn.commit()

    async def _execute(self, query: str, params: tuple = (), fetch_type: str = "one"):
        conn = await self._pool.get_connection()
        try:
            async with conn.execute(query, params) as cursor:
                if fetch_type == "all":
                    return await cursor.fetchall()
                elif fetch_type == "one":
                    return await cursor.fetchone()
                elif fetch_type == "insert":
                    await conn.commit()
                    return cursor.lastrowid
                elif fetch_type == "update":
                    await conn.commit()
                    return cursor.rowcount
        except (aiosqlite.Error, OSError, ValueError) as e:
            if fetch_type in ("insert", "update"):
                await conn.rollback()
                logger.error(f"数据库{fetch_type}操作失败: {e}")
            raise
        finally:
            await self._pool.return_connection(conn)

    async def is_mention_processed(self, note_id: str) -> bool:
        return bool(
            await self._execute(
                "SELECT 1 FROM processed_mentions WHERE note_id = ? LIMIT 1", (note_id,)
            )
        )

    async def mark_mention_processed(
        self,
        note_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO processed_mentions (note_id, user_id, username) VALUES (?, ?, ?)",
            (note_id, user_id, username),
            "insert",
        )

    async def get_recent_mentions(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await self._execute(
            "SELECT note_id, processed_at, user_id, username FROM processed_mentions ORDER BY processed_at DESC LIMIT ?",
            (limit,),
            "all",
        )
        return [
            {
                "note_id": row[0],
                "processed_at": row[1],
                "user_id": row[2],
                "username": row[3],
            }
            for row in rows
        ]

    async def get_processed_mentions_count(self) -> int:
        result = await self._execute("SELECT COUNT(*) FROM processed_mentions")
        return result[0] if result else 0

    async def is_message_processed(self, message_id: str) -> bool:
        return bool(
            await self._execute(
                "SELECT 1 FROM processed_messages WHERE message_id = ? LIMIT 1",
                (message_id,),
            )
        )

    async def mark_message_processed(
        self,
        message_id: str,
        user_id: Optional[str] = None,
        chat_type: Optional[str] = None,
    ) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO processed_messages (message_id, user_id, chat_type) VALUES (?, ?, ?)",
            (message_id, user_id, chat_type),
            "insert",
        )

    async def get_recent_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await self._execute(
            "SELECT message_id, processed_at, user_id, chat_type FROM processed_messages ORDER BY processed_at DESC LIMIT ?",
            (limit,),
            "all",
        )
        return [
            {
                "message_id": row[0],
                "processed_at": row[1],
                "user_id": row[2],
                "chat_type": row[3],
            }
            for row in rows
        ]

    async def get_processed_messages_count(self) -> int:
        result = await self._execute("SELECT COUNT(*) FROM processed_messages")
        return result[0] if result else 0

    async def get_plugin_data(self, plugin_name: str, key: str) -> Optional[str]:
        result = await self._execute(
            "SELECT value FROM plugin_data WHERE plugin_name = ? AND key = ?",
            (plugin_name, key),
        )
        return result[0] if result else None

    async def set_plugin_data(self, plugin_name: str, key: str, value: str) -> None:
        await self._execute(
            "INSERT OR REPLACE INTO plugin_data (plugin_name, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (plugin_name, key, value, datetime.now()),
            "update",
        )

    async def delete_plugin_data(self, plugin_name: str, key: str = None) -> int:
        query = "DELETE FROM plugin_data WHERE plugin_name = ?" + (
            " AND key = ?" if key else ""
        )
        params = (plugin_name, key) if key else (plugin_name,)
        return await self._execute(query, params, "update")

    async def cleanup_old_records(self, days: int = 30) -> int:
        cutoff_date = datetime.now() - timedelta(days=days)
        mentions_deleted = await self._execute(
            "DELETE FROM processed_mentions WHERE processed_at < ?",
            (cutoff_date,),
            "update",
        )
        messages_deleted = await self._execute(
            "DELETE FROM processed_messages WHERE processed_at < ?",
            (cutoff_date,),
            "update",
        )
        total_deleted = mentions_deleted + messages_deleted
        if total_deleted > 0:
            logger.debug(
                f"已清理 {total_deleted} 条过期记录 (提及: {mentions_deleted}, 消息: {messages_deleted})"
            )
        return total_deleted

    async def get_statistics(self) -> Dict[str, Any]:
        today = datetime.now().date()
        queries = [
            "SELECT COUNT(*) FROM processed_mentions",
            "SELECT COUNT(*) FROM processed_messages",
            "SELECT COUNT(*) FROM processed_mentions WHERE DATE(processed_at) = ?",
            "SELECT COUNT(*) FROM processed_messages WHERE DATE(processed_at) = ?",
            "SELECT COUNT(*) FROM plugin_data",
            "SELECT COUNT(*) FROM plugin_data WHERE DATE(updated_at) = ?",
        ]
        params = [(), (), (today,), (today,), (), (today,)]
        results = []
        for query, param in zip(queries, params):
            result = await self._execute(query, param)
            results.append(result[0])
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_mentions": results[0],
            "total_messages": results[1],
            "today_mentions": results[2],
            "today_messages": results[3],
            "total_plugin_data": results[4],
            "today_plugin_data": results[5],
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
        }

    async def vacuum(self) -> None:
        conn = await self._pool.get_connection()
        try:
            await conn.execute("VACUUM")
            logger.debug("数据库优化完成")
        except (aiosqlite.Error, OSError) as e:
            logger.error(f"数据库优化失败: {e}")
        finally:
            await self._pool.return_connection(conn)

    async def execute_query(
        self, query: str, params: tuple = ()
    ) -> List[aiosqlite.Row]:
        return await self._execute(query, params, "all")

    async def execute_update(self, query: str, params: tuple = ()) -> int:
        return await self._execute(query, params, "update")

    async def execute_insert(self, query: str, params: tuple = ()) -> int:
        return await self._execute(query, params, "insert")
