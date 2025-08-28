import os
import aiohttp
import json
import datetime
import random
import re
import asyncio
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Set
from types import SimpleNamespace
from src.plugin_base import PluginBase
from src.openai_api import OpenAIAPI
from .constants import (
    DEFAULT_SIMILARITY,
    DEFAULT_AI_SYSTEM_PROMPT,
    DEFAULT_AUTO_POST_SYSTEM_PROMPT,
    DEFAULT_AUTO_POST_USER_PROMPT,
    ErrorCode,
    quote_keyword,
)
from .exceptions import (
    GalInfoError,
    GameNotFoundError,
    APIParamError,
    APIServerError,
)

class APIYm:
    """YM Gal API 封装（保持原有行为，仅改进可读性与类型标注）。"""

    def __init__(self) -> None:
        self.api: str = "https://www.ymgal.games"
        self.cid: str = "ymgal"
        self.c_secret: str = "luna0327"
        self._session: Optional[aiohttp.ClientSession] = None  # 复用 session

    async def _get_session(self, headers: Dict[str, str] | None = None) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        elif headers and self._session.headers != headers:  # 保持兼容：若需要不同头部仍创建新 session
            await self._session.close()
            timeout = aiohttp.ClientTimeout(total=12)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    async def _fetch_json(
        self,
        method: str,
        url: str,
        *,
        session: aiohttp.ClientSession,
        data: Dict[str, Any] | None = None,
        retries: int = 2,
        expect: str = "application/json",
    ) -> Dict[str, Any]:
        """统一请求与 JSON 解析，容错常见 ContentType / 解码问题，附带有限重试。

        重试条件：网络异常、JSON 解析异常、非预期 content-type。
        """
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if method == "GET":
                    async with session.get(url) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        text_body: str | None = None
                        if expect not in ct:
                            # 读取文本用于诊断（不抛弃）；尝试仍按 JSON 解析
                            text_body = await resp.text()
                        try:
                            parsed = await resp.json()
                            return parsed  # 成功
                        except Exception as je:  # noqa: BLE001
                            if text_body is None:
                                text_body = await resp.text()
                            raise APIServerError(
                                f"JSON解析失败/ContentType异常 attempt={attempt} ct={ct} snippet={text_body[:120]!r} err={je}"
                            ) from je
                else:  # POST
                    async with session.post(url, data=data) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        text_body: str | None = None
                        if expect not in ct:
                            text_body = await resp.text()
                        try:
                            parsed = await resp.json()
                            return parsed
                        except Exception as je:  # noqa: BLE001
                            if text_body is None:
                                text_body = await resp.text()
                            raise APIServerError(
                                f"JSON解析失败/ContentType异常 attempt={attempt} ct={ct} snippet={text_body[:120]!r} err={je}"
                            ) from je
            except Exception as e:  # noqa: BLE001
                last_err = e
                # 仅在还有重试机会时等待后继续
                if attempt < retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
        # 全部失败
        raise last_err if last_err else APIServerError("未知错误")

    async def get_token(self) -> str:
        tapi = f"{self.api}/oauth/token?"
        data = {"grant_type": "client_credentials", "client_id": self.cid, "client_secret": self.c_secret, "scope": "public"}
        # 单独 token 不复用主 session，失败重试更健壮
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            res = await self._fetch_json("POST", tapi, session=session, data=data, retries=2)
            token = res.get("access_token")
            if not token:
                raise APIServerError(f"获取 token 失败：返回 {res}")
            return token

    async def header(self, token: str) -> Dict[str, str]:
        return {
            "Accept": "application/json;charset=utf-8",
            "Authorization": f"Bearer {token}",
            "version": "1",
        }

    async def search_game(self, header: Dict[str, str], keyword: str, similarity: int) -> Dict[str, Any]:
        keyword_q = quote_keyword(keyword)
        url = f"{self.api}/open/archive/search-game?mode=accurate&keyword={keyword_q}&similarity={similarity}"
        session = await self._get_session(headers=header)
        res: Dict[str, Any] = await self._fetch_json("GET", url, session=session, retries=1)
        code = res.get("code")
        if code == 0:
            gamedata = res.get("data", {}).get("game", {})
            result = {
                "id": gamedata.get("gid"),
                "oaid": gamedata.get("developerId"),
                "mainimg": gamedata.get("mainImg", "None"),
                "name": gamedata.get("name", "None"),
                "rd": gamedata.get("releaseDate", "None"),
                "rest": gamedata.get("restricted", "None"),
                "hc": gamedata.get("haveChinese", False),
                "cnname": gamedata.get("chineseName", "None"),
                "intro": gamedata.get("introduction", "None"),
            }
            return {"if_oainfo": False, "result": result}
        if code == ErrorCode.PARAM_ERROR:
            raise APIParamError(
                "参数错误，可能是根据关键词搜索不到游戏档案\n在使用游戏简称、汉化名、外号等关键字无法查询到目标内容时，请使用游戏原名（全名+标点+大小写无误）再次尝试，或者使用模糊查找"
            )
        raise APIServerError(f"返回错误，返回码code:{code}")

    async def search_orgid_mergeinfo(
        self, header: Dict[str, str], gid: int, info: Dict[str, Any], if_oainfo: bool
    ) -> Dict[str, Any]:
        url = f"{self.api}/open/archive?orgId={gid}"
        session = await self._get_session(headers=header)
        res: Dict[str, Any] = await self._fetch_json("GET", url, session=session, retries=1)
        code = res.get("code")
        if code == 0:
            org = res.get("data", {}).get("org", {})
            if if_oainfo:
                return {
                    "oaname": org.get("name"),
                    "oacn": org.get("chineseName"),
                    "intro": org.get("introduction"),
                    "country": org.get("country"),
                }
            result_oa = info | {"oaname": org.get("name"), "oacn": org.get("chineseName")}
            result_oa.pop("oaid", None)
            return result_oa
        raise APIServerError(f"查询会社信息失败，返回码code:{code}")

    async def vague_search_game(
        self, header: Dict[str, str], keyword: str, pageNum: int = 1, pageSize: int = 10
    ) -> str:
        keyword_q = quote_keyword(keyword)
        url = (
            f"{self.api}/open/archive/search-game?mode=list&keyword={keyword_q}&pageNum={pageNum}&pageSize={pageSize}"
        )
        session = await self._get_session(headers=header)
        res: Dict[str, Any] = await self._fetch_json("GET", url, session=session, retries=1)
        code = res.get("code")
        if code == 0:
            result: List[Dict[str, Any]] = res.get("data", {}).get("result", [])
            if result:
                original_keyword = keyword_q.replace("%20", " ").lower()
                best_match: Optional[Dict[str, Any]] = None
                exact_match: Optional[Dict[str, Any]] = None
                for game in result:
                    game_name = game.get("name", "").lower()
                    cn_name = game.get("chineseName", "").lower()
                    if game_name == original_keyword or cn_name == original_keyword:
                        exact_match = game
                        break
                    if original_keyword in game_name or original_keyword in cn_name:
                        if not best_match:
                            best_match = game
                selected_game = exact_match or best_match or result[0]
                s_keyword = selected_game.get("name")
                if s_keyword:
                    return s_keyword
                raise APIServerError("模糊搜索返回结果但游戏名为空")
            raise GameNotFoundError("模糊搜索无结果，请尝试更改关键词")
        raise APIServerError(f"模糊搜索返回错误，返回码code:{code}")

    def info_list(self, info: dict[str, Any]):
        import re
        parg = (info.get("intro") or "").split("\n")
        if len(parg) < 2:
            parg = (info.get("intro") or "").split("\n\n")
        pargs = []
        for p in parg:
            pattern = r"\s+"
            clean_p = f"{'':<7}{re.sub(pattern, '', p.strip())}"
            pargs.append(clean_p)
        intro = "\n".join(pargs)
        chain = (
            f"游戏名：{info.get('name')}（{info.get('cnname')}）\n"
            f"会社：{info.get('oaname', 'N/A')}（{info.get('oacn', 'N/A')}）\n"
            f"限制级：{'是' if info.get('rest') else '否'}\n"
            f"是否已有汉化：{'是' if info.get('hc') else '否'}\n"
            f"简介：\n{intro}"
        )
        return chain

@dataclass
class AutoPostConfig:
    enabled: bool = False
    interval_hours: int = 6
    random_delay_minutes: int = 30
    max_posts_per_day: int = 4
    use_ai_enhanced_data: bool = False
    ai_post_system_prompt: str = DEFAULT_AUTO_POST_SYSTEM_PROMPT
    ai_post_user_prompt: str = DEFAULT_AUTO_POST_USER_PROMPT


class GalinfoPlugin(PluginBase):
    name = "galinfo"
    description = "提供Galgame信息查询，基于月幕Gal的api"
    version = "1.0"

    def __init__(self, context):
        super().__init__(context)
        self.ym = APIYm()
        self.trigger_tag = context.config.get('gal_tag', '#galgame')
        self.use_ai_enhancement = context.config.get('use_ai_enhancement', False)
        self.openai_api = getattr(getattr(context, "bot", None), "openai", None)
        self.ai_system_prompt = context.config.get('ai_system_prompt', DEFAULT_AI_SYSTEM_PROMPT)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.cache_file = os.path.join(root_dir, 'data', 'galinfo.json')
        self._memory_cache = {}
        self._cache_lock = asyncio.Lock()
        self._cache_loaded = False
        raw_auto_post = context.config.get('auto_post', {}) or {}
        filtered: Dict[str, Any] = {k: raw_auto_post.get(k) for k in AutoPostConfig.__annotations__.keys() if k in raw_auto_post}
        self.auto_post = AutoPostConfig(**filtered)
        self.debug_enabled = raw_auto_post.get('debug_enabled', True)
        self.debug_whitelist = raw_auto_post.get('debug_whitelist', [])
        self.debug_tag = raw_auto_post.get('debug_tag', '#galinfo_testaichat')
        self.direct_post_tag = raw_auto_post.get('direct_post_tag', '#galinfo_aichat')
        self.last_auto_post_time = None
        self.auto_posts_today = 0
        self.auto_post_reset_date = None
        self.recent_games = []
        # 伪随机防重复相关
        self.avoid_repeat = bool(
            getattr(self.auto_post, 'enabled', False)
            and context.config.get('auto_post', {}).get('avoid_repeat', True)
        )
        self.used_game_names: Set[str] = set()
        self.tag_pattern = re.compile(
            r'(?<![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】]){}(?![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】])'.format(
                re.escape(self.trigger_tag)
            )
        )
        self.cache_suffix = "_AI" if self.use_ai_enhancement else "_original"
        # 可选缓存策略（默认不启用以保持行为）
        cache_cfg = context.config.get('galinfo_cache', {}) if hasattr(context, 'config') else {}
        self.cache_ttl_seconds = int(cache_cfg.get('ttl_seconds', 0) or 0)
        self.cache_max_entries = int(cache_cfg.get('max_entries', 0) or 0)

    # ---------------- 缓存相关（异步 & 内存） -----------------
    async def _ensure_cache_loaded(self) -> None:
        if self._cache_loaded:
            return
        async with self._cache_lock:
            if self._cache_loaded:
                return
            disk_cache = self._load_cache()  # 复用原同步读
            self._memory_cache.update(disk_cache)
            if self.cache_ttl_seconds or self.cache_max_entries:
                self._prune_cache_locked()
            self._cache_loaded = True

    async def _get_cache(self) -> Dict[str, Any]:
        await self._ensure_cache_loaded()
        return self._memory_cache

    async def _update_cache_entry(self, key: str, value: Any) -> None:
        await self._ensure_cache_loaded()
        async with self._cache_lock:
            self._memory_cache[key] = value
            if self.cache_ttl_seconds or self.cache_max_entries:
                self._prune_cache_locked()
            await self._save_cache_async()  # 直接写盘（规模小，保持语义简单）

    async def _save_cache_async(self) -> None:
        try:
            import importlib
            aiofiles = importlib.import_module('aiofiles')  # 动态导入
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            async with aiofiles.open(self.cache_file, 'w', encoding='utf-8') as f:  # type: ignore[attr-defined]
                await f.write(json.dumps(self._memory_cache, ensure_ascii=False, indent=2))
        except ModuleNotFoundError:
            # 回退同步
            self._save_cache(self._memory_cache)
        except Exception as e:
            self._log_plugin_action("缓存写入失败", str(e))

    # ---------------- 缓存清理逻辑（内部调用需持锁） -----------------
    def _prune_cache_locked(self) -> None:
        """在已获取 _cache_lock 的情况下执行清理。"""
        if not (self.cache_ttl_seconds or self.cache_max_entries):
            return
        # TTL 处理
        if self.cache_ttl_seconds:
            now = datetime.datetime.now()
            expired_keys = []
            for k, v in self._memory_cache.items():
                ts = v.get('timestamp') if isinstance(v, dict) else None
                if ts:
                    try:
                        dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        if (now - dt).total_seconds() > self.cache_ttl_seconds:
                            expired_keys.append(k)
                    except Exception:
                        continue
            for k in expired_keys:
                self._memory_cache.pop(k, None)
        # 容量限制（简单 FIFO：按时间升序删除超出部分）
        if self.cache_max_entries and len(self._memory_cache) > self.cache_max_entries:
            sortable = []
            for k, v in self._memory_cache.items():
                ts = v.get('timestamp') if isinstance(v, dict) else None
                try:
                    order_dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if ts else datetime.datetime.min
                except Exception:
                    order_dt = datetime.datetime.min
                sortable.append((order_dt, k))
            sortable.sort()  # 旧的在前
            overflow = len(self._memory_cache) - self.cache_max_entries
            for _, k in sortable[:overflow]:
                self._memory_cache.pop(k, None)

    # 合并的默认提示词函数
    def _get_default_prompt(self, prompt_type: str = "enhance") -> str:
        """获取默认的AI系统提示词"""
        if prompt_type == "auto_post":
            return DEFAULT_AUTO_POST_SYSTEM_PROMPT
        return DEFAULT_AI_SYSTEM_PROMPT

    # 工具函数：统一错误响应
    def _error_response(self, msg: str, e: Exception | None = None) -> Dict[str, Any]:
        error_msg = f"{msg}失败：{e}" if e else f"{msg}失败"
        return {
            "handled": True,
            "plugin_name": self.name,
            "response": error_msg
        }

    async def _safe_generate_post(self, username: str) -> Optional[Dict[str, Any]]:
        if username not in self.debug_whitelist:
            return self._error_response("权限检查")
        # 只获取一次游戏信息，后续调试展示复用，避免与缓存示例不一致
        game_info = await self._get_game_info_for_post(log_details=True)
        if not game_info:
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": "缓存中没有可用的游戏数据。请先通过查询功能生成一些缓存数据。",
            }
        if not self.openai_api:
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": "未检测到全局 OpenAI 客户端，无法生成 AI 发帖内容。",
            }
        post_content = await self._generate_auto_post_content(game_info)
        if not post_content:
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": "AI生成发帖内容失败。",
            }
        # 返回用于预览的原始缓存文本（截断留到上层处理）和使用的数据类型
        preview_source = "AI增强" if getattr(self.auto_post, 'use_ai_enhanced_data', False) else "原始"
        return {
            "content": post_content,
            "visibility": "public",
            "handled": True,
            "plugin_name": self.name,
            "cache_preview": game_info,  # 复用同一份，避免再次随机导致不一致
            "preview_source": preview_source,
        }

    # 载入缓存
    def _load_cache(self) -> Dict[str, Any]:
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    # 保存缓存
    def _save_cache(self, cache: Dict[str, Any]) -> None:
        try:
            # 确保缓存目录存在
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    async def on_mention(self, mention_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 @mention 事件"""
        return await self._process_message(mention_data)

    async def on_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理聊天消息事件"""
        return await self._process_message(message_data)

    async def _enhance_with_ai(self, game_info: str, game_name: str) -> str:
        """使用 AI 对游戏信息进行增强处理"""
        if not self.use_ai_enhancement or not self.openai_api:
            return game_info
        
        try:
            user_prompt = f"请对以下Galgame信息进行润色优化：\n\n{game_info}"
            
            enhanced_info = await self.openai_api.generate_text(
                prompt=user_prompt,
                system_prompt=self.ai_system_prompt,
                max_tokens=500,
                temperature=0.7
            )
            
            return enhanced_info.strip()
            
        except Exception as e:
            self._log_plugin_action("AI 增强失败", f"{game_name}: {e}")
            return game_info

    async def _process_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理消息的核心逻辑"""
        try:
            # 获取消息文本内容
            note = message_data.get("note", message_data)
            text = note.get("text", "")
            
            # 检查是否是调试触发标签
            if self.debug_enabled and self.debug_tag in text:
                return await self._handle_debug_trigger(message_data)
            
            # 检查是否是直接发帖触发标签
            if self.debug_enabled and self.direct_post_tag in text:
                return await self._handle_direct_post_trigger(message_data)
            
            # 新增：只有 #recreate 而未包含触发标签时，提示格式错误
            if "#recreate" in text and self.trigger_tag not in text:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "格式错误：重建缓存需同时包含触发标签和#recreate"
                }
            
            # 仅检测自己的标签，且标签需为独立词（前后为分隔符或行首/行尾）
            match = self.tag_pattern.search(text)
            if not match:
                return None  # 没有触发标签，且非单独 #recreate，不做响应
            
            # 只移除首次出现的标签
            keyword = self.tag_pattern.sub('', text, count=1).strip()
            
            # 清理提及标记和其他特殊字符
            keyword = re.sub(r'@\w+', '', keyword).strip()  # 移除 @用户名
            
            keyword = re.sub(r'\s+', ' ', keyword).strip()
            # 新增：检测 #recreate 标志
            recreate = False
            if '#recreate' in keyword:
                recreate = True
                keyword = re.sub(r'#recreate\b', '', keyword).strip()

            if not keyword:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "请在标签后输入要查询的游戏名"
                }
            
            username = self._extract_username(message_data)
            
            # 获取Token/headers
            token = await self.ym.get_token()
            header = await self.ym.header(token)
            # 模糊搜索游戏名
            game_name = await self.ym.vague_search_game(header, keyword)

            # 检查缓存 - 直接查找对应的缓存类型
            cache = await self._get_cache()
            cache_key = f"{game_name}{self.cache_suffix}"
                    
            if cache_key in cache and not recreate:
                entry = cache[cache_key]
                ts = entry.get("timestamp") or "未知"
                # 命中缓存时标明这是缓存数据并显示时间
                resp = f"【缓存数据】\n{entry['response']}\n\n缓存时间：{ts}"
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": resp
                }

            # 使用获取到的游戏名进行精确搜索
            search_result = await self.ym.search_game(header, game_name, DEFAULT_SIMILARITY)  # similarity=70
            
            result = search_result["result"]
            
            # 判断命中游戏信息中是否存在Oaid，如果存在则查询会社信息
            if result.get("oaid"):
                allinfo = await self.ym.search_orgid_mergeinfo(
                    header,
                    result.get("oaid"),
                    result,
                    False
                )
            else:
                allinfo = result.copy()
                allinfo.update({"oaname": None, "oacn": None})
            
            chains = self.ym.info_list(allinfo)
            
            # 使用 AI 增强处理（如果启用）
            if self.use_ai_enhancement:
                chains = await self._enhance_with_ai(chains, game_name)
            
            ai_status = " (AI增强)" if self.use_ai_enhancement else ""
            response_text = f"已匹配最符合的一条：{game_name}{ai_status}\n{chains}"

            # 保存缓存：同时保存原始和AI增强数据
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 保存原始数据
            original_response = f"已匹配最符合的一条：{game_name}\n{self.ym.info_list(allinfo)}"
            await self._update_cache_entry(
                f"{game_name}_original",
                {"response": original_response, "timestamp": timestamp, "game_data": allinfo},
            )
            if self.use_ai_enhancement:
                await self._update_cache_entry(
                    f"{game_name}_AI",
                    {"response": response_text, "timestamp": timestamp, "game_data": allinfo},
                )

            return {
                "handled": True,
                "plugin_name": self.name,
                "response": response_text,
            }
        except GalInfoError as e:
            return self._error_response("查询", e)
        except Exception as e:  # 保留兜底，行为与之前一致
            return self._error_response("查询", e)

    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        """定时发帖功能"""
        try:
            if not self._can_auto_post():
                return None
            
            # 从缓存中随机选择一个游戏
            game_info = await self._get_game_info_for_post()
            if not game_info:
                return None
            
            # 生成AI发帖内容
            post_content = await self._generate_auto_post_content(game_info)
            if not post_content:
                return None
            
            # 更新发帖状态
            self.last_auto_post_time = datetime.datetime.now()
            self.auto_posts_today += 1
            
            return {
                "content": post_content,
                "visibility": "public"  # 可以根据需要调整可见性
            }
        
        except Exception as e:
            return None

    def _can_auto_post(self) -> bool:
        """检查是否可以进行自动发帖"""
        if not self.auto_post.enabled:
            return False
        
        if not self._should_auto_post():
            return False
        
        self._reset_daily_counter_if_needed()
        if self.auto_posts_today >= getattr(self.auto_post, 'max_per_day', 4):
            return False
        return True

    def _should_auto_post(self) -> bool:
        """检查是否应该进行自动发帖"""
        if self.last_auto_post_time is None:
            return True
        
        # 计算下次发帖时间（包含随机延迟）
        interval_seconds = self.auto_post.interval_hours * 3600
        random_delay_seconds = random.randint(0, self.auto_post.random_delay_minutes * 60)
        next_post_time = self.last_auto_post_time + datetime.timedelta(
            seconds=interval_seconds + random_delay_seconds
        )
        
        return datetime.datetime.now() >= next_post_time
    
    def _reset_daily_counter_if_needed(self) -> None:
        """如果是新的一天，重置每日发帖计数"""
        today = datetime.date.today()
        if self.auto_post_reset_date != today:
            self.auto_post_reset_date = today
            self.auto_posts_today = 0
    
    async def _get_game_info_for_post(self, log_details: bool = False) -> Optional[str]:
        """获取用于发帖的随机游戏信息（异步内存缓存）。"""
        return await self._get_random_game_from_cache_async()

    def _get_random_game_from_cache(self) -> Optional[str]:
        """从缓存中随机获取游戏信息，确保最近5次获取的游戏不重复"""
        # 注意：此函数在自动发帖中同步调用，仍使用磁盘快照以保持原始行为；
        # 若需要完全异步，可重构调用链为 async。
        cache = self._memory_cache or self._load_cache()
        if not cache:
            return None
        
        # 获取所有游戏名（去重）
        game_names = set()
        for key in cache.keys():
            if key.endswith('_original') or key.endswith('_AI'):
                game_name = key.rsplit('_', 1)[0]  # 移除后缀
                game_names.add(game_name)
        
        if not game_names:
            return None
        selected_game = self._select_game_name(game_names)

        # 更新最近游戏列表
        self.recent_games.append(selected_game)
        if len(self.recent_games) > 5:
            self.recent_games.pop(0)  # 移除最旧的

        # 根据配置选择数据类型
        suffix = "_AI" if self.auto_post.use_ai_enhanced_data else "_original"
        cache_key = f"{selected_game}{suffix}"

        # 如果指定类型不存在，回退到另一种
        if cache_key not in cache:
            alt_suffix = "_original" if suffix == "_AI" else "_AI"
            alt_key = f"{selected_game}{alt_suffix}"
            if alt_key in cache:
                cache_key = alt_key

        entry = cache.get(cache_key)
        if entry:
            return entry.get("response", "")

        return None

    # 新的异步版本，优先使用内存缓存（不命中则加载）
    async def _get_random_game_from_cache_async(self) -> Optional[str]:
        await self._ensure_cache_loaded()
        cache = self._memory_cache
        if not cache:
            return None
        game_names = {k.rsplit('_', 1)[0] for k in cache if k.endswith('_original') or k.endswith('_AI')}
        if not game_names:
            return None
        selected_game = self._select_game_name(game_names)
        self.recent_games.append(selected_game)
        if len(self.recent_games) > 5:
            self.recent_games.pop(0)
        suffix = "_AI" if getattr(self.auto_post, 'use_ai_enhanced_data', False) else "_original"
        cache_key = f"{selected_game}{suffix}"
        if cache_key not in cache:
            alt_suffix = "_original" if suffix == "_AI" else "_AI"
            alt_key = f"{selected_game}{alt_suffix}"
            if alt_key in cache:
                cache_key = alt_key
        entry = cache.get(cache_key)
        if entry:
            return entry.get('response', '')
        return None

    async def _generate_auto_post_content(self, game_info: str) -> Optional[str]:
        """使用AI生成自动发帖内容"""
        if not self.openai_api:
            return None
        try:
            user_prompt = self.auto_post.ai_post_user_prompt.format(game_info=game_info)
            
            post_content = await self.openai_api.generate_text(
                prompt=user_prompt,
                system_prompt=self.auto_post.ai_post_system_prompt,
                max_tokens=400,
                temperature=0.8  # 稍高的温度以增加创造性
            )
            
            return post_content.strip()
        
        except Exception as e:
            self._log_plugin_action("自动发帖文本生成失败", str(e))
            return None
    
    async def _handle_debug_trigger(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理调试触发事件"""
        # 改进：避免多次随机抽取不同游戏信息
        try:
            username = self._extract_username(message_data)
            result = await self._safe_generate_post(username)
            if not result:
                return None
            if 'content' in result:
                cached_preview = result.get('cache_preview')  # 直接复用生成内容所基于的数据
                preview_source = result.get('preview_source', '未知')
                cache_preview_text = (cached_preview or "")[:200]
                if cached_preview and len(cached_preview) > 200:
                    cache_preview_text += "..."
                result['response'] = (
                    f"【调试模式 AI 发帖预览】\n使用数据类型：{preview_source}\n\n"
                    f"{result['content']}\n\n--- 缓存数据示例 (同源) ---\n{cache_preview_text}"
                )
            return result
        except Exception as e:
            return self._error_response("调试", e)

    async def _handle_direct_post_trigger(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理直接发帖触发事件"""
        try:
            self._log_plugin_action("直接发帖", "开始处理直接发帖触发事件")
            
            # 检查用户权限
            username = self._extract_username(message_data)
            self._log_plugin_action("权限检查", f"检查用户 {username} 权限，白名单: {self.debug_whitelist}")
            
            if username not in self.debug_whitelist:
                self._log_plugin_action("直接发帖权限检查", f"用户 {username} 不在白名单中")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "抱歉，您没有使用直接发帖功能的权限。"
                }
            
            self._log_plugin_action("直接发帖触发", f"用户 {username} 触发了直接发帖功能")
            
            # 从缓存中随机选择一个游戏
            game_info = await self._get_game_info_for_post(log_details=True)
            if not game_info:
                self._log_plugin_action("缓存检查", "缓存中没有可用的游戏数据")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "直接发帖失败：缓存中没有可用的游戏数据。请先通过查询功能生成一些缓存数据。"
                }
            
            # 生成AI发帖内容前检查
            if not self.openai_api:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "未检测到全局 OpenAI 客户端，无法生成 AI 发帖内容。"
                }
            
            post_content = await self._generate_auto_post_content(game_info)
            if not post_content:
                self._log_plugin_action("内容生成", "AI生成发帖内容失败")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "直接发帖失败：AI生成发帖内容失败。"
                }
            
            self._log_plugin_action("内容生成", f"成功生成发帖内容，长度: {len(post_content)}")
            
            # 更新发帖状态（如果需要）
            self.last_auto_post_time = datetime.datetime.now()
            self.auto_posts_today += 1
            
            result = {
                "content": post_content,
                "visibility": "public",
                "handled": True,
                "plugin_name": self.name
            }
            
            self._log_plugin_action("直接发帖成功", f"已生成内容 长度={len(post_content)}")
            return result
        except Exception as e:
            self._log_plugin_action("直接发帖处理失败", str(e))
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": f"直接发帖功能出错：{str(e)}"
            }
    
    async def initialize(self) -> bool:
        """初始化插件（若有需要可在加载时调用）"""
        try:
            # 仅记录（全局 OpenAI 由框架统一管理）
            self._log_plugin_action("初始化", "Galinfo 插件已就绪（使用全局 OpenAI 客户端）")
            # 加载已使用的游戏名（用于伪随机防重复）
            await self._load_used_games()
            return True
        except Exception as e:
            self._log_plugin_action("插件初始化失败", str(e))
            return False

    async def cleanup(self) -> None:
        try:
            # 无需关闭全局 OpenAI
            self._log_plugin_action("清理", "完成")
        except Exception:
            pass

    # ---------------- 伪随机防重复逻辑 -----------------
    def _select_game_name(self, all_game_names: Set[str]) -> str:
        """选择一个游戏名：
        - 若启用 avoid_repeat：不重复直到全部用完（持久化 used_game_names）
        - 否则：使用最近窗口 + 全集兜底策略
        """
        if not all_game_names:
            return ""
        if self.avoid_repeat:
            remaining = list(all_game_names - self.used_game_names)
            if not remaining:  # 一轮已用完，重置
                self.used_game_names.clear()
                remaining = list(all_game_names)
            selected = random.choice(remaining)
            # 记录并尝试异步保存（不 await 以免阻塞同步路径）
            self.used_game_names.add(selected)
            # 调度保存（如果事件循环可用）
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._save_used_games())
            except RuntimeError:
                # 若无事件循环（极少数同步路径），忽略，稍后异步调用会覆盖
                pass
            return selected
        # 旧逻辑：避免最近 5 次重复
        available = list(all_game_names - set(self.recent_games)) or list(all_game_names)
        return random.choice(available)

    async def _load_used_games(self) -> None:
        if not hasattr(self, 'persistence_manager') or not self.persistence_manager:
            return
        try:
            data = await self.persistence_manager.get_plugin_data("Galinfo", "used_games")
            if data:
                loaded = json.loads(data)
                if isinstance(loaded, list):
                    self.used_game_names = set(map(str, loaded))
        except Exception:
            # 忽略加载错误，保持空集合
            self.used_game_names = set()

    async def _save_used_games(self) -> None:
        if not hasattr(self, 'persistence_manager') or not self.persistence_manager:
            return
        try:
            await self.persistence_manager.set_plugin_data("Galinfo", "used_games", json.dumps(list(self.used_game_names), ensure_ascii=False))
        except Exception:
            pass
