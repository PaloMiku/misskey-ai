import os
import aiohttp
import json
import datetime
import random
from typing import Dict, Any, Optional
from src.plugin_base import PluginBase



class APIYm:
    def __init__(self):
        self.api = "https://www.ymgal.games"
        self.cid = "ymgal"
        self.c_secret = "luna0327"

    async def get_token(self):
        tapi = f"{self.api}/oauth/token?"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.cid,
            "client_secret": self.c_secret,
            
            "scope": "public"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(tapi, data=data) as response:
                token = (await response.json())["access_token"]
                return token

    async def header(self, token):
        return {
            "Accept": "application/json;charset=utf-8",
            "Authorization": f"Bearer {token}",
            "version": "1",
        }

    async def search_game(self, header, keyword: str, similarity: int) -> Dict[str, Any]:
        from urllib.parse import quote
        keyword = quote(keyword)
        url = f"{self.api}/open/archive/search-game?mode=accurate&keyword={keyword}&similarity={similarity}"
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url) as response:
                res = await response.json()
                code = res["code"]
                if code == 0:
                    gamedata = res.get("data", {}).get("game", {})
                    result = {
                        "id": gamedata.get("gid", None),
                        "oaid": gamedata.get("developerId", None),
                        "mainimg": gamedata.get("mainImg", "None"),
                        "name": gamedata.get("name", "None"),
                        "rd": gamedata.get("releaseDate", "None"),
                        "rest": gamedata.get("restricted", "None"),
                        "hc": gamedata.get("haveChinese", False),
                        "cnname": gamedata.get("chineseName", "None"),
                        "intro": gamedata.get("introduction", "None")
                    }
                    return {
                        "if_oainfo": False,
                        "result": result
                    }
                elif code == 614:
                    raise Exception("参数错误，可能是根据关键词搜索不到游戏档案\n在使用游戏简称、汉化名、外号等关键字无法查询到目标内容时，请使用游戏原名（全名+标点+大小写无误）再次尝试，或者使用模糊查找")
                else:
                    raise Exception(f"返回错误，返回码code:{code}")

    async def search_orgid_mergeinfo(self, header, gid: int, info: dict, if_oainfo: bool) -> Dict[str, Any]:
        """搜索游戏机构详细信息，将oaid匹配成对应的会社名"""
        url = f"{self.api}/open/archive?orgId={gid}"
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url) as response:
                res = await response.json()
                code = res["code"]
                if code == 0:
                    if if_oainfo:
                        result_oa = {
                            "oaname": res.get("data", {}).get("org", {}).get("name", None),
                            "oacn": res.get("data", {}).get("org", {}).get("chineseName", None),
                            "intro": res.get("data", {}).get("org", {}).get("introduction", None),
                            "country": res.get("data", {}).get("org", {}).get("country", None)
                        }
                    else:
                        oa = {
                            "oaname": res.get("data", {}).get("org", {}).get("name", None),
                            "oacn": res.get("data", {}).get("org", {}).get("chineseName", None)
                        }
                        result_oa = info | {"oaname": oa.get("oaname"), "oacn": oa.get("oacn")}
                        if "oaid" in result_oa:
                            del result_oa["oaid"]
                    return result_oa
                else:
                    raise Exception(f"查询会社信息失败，返回码code:{code}")
        return None

    async def vague_search_game(self, header, keyword: str, pageNum=1, pageSize=10) -> str:
        """模糊查询游戏名（即可能游戏列表查询，默认命中所请求到列表中的第一个）"""
        from urllib.parse import quote
        keyword = quote(keyword)
        url = f"{self.api}/open/archive/search-game?mode=list&keyword={keyword}&pageNum={pageNum}&pageSize={pageSize}"
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url) as response:
                res = await response.json()
                code = res.get("code")
                if code == 0:
                    result = res.get("data", {}).get("result", [])
                    if result and len(result) > 0:
                        # 查找最匹配的游戏，优先精确匹配或包含关键词的游戏
                        original_keyword = keyword.replace('%20', ' ').lower()  # URL解码并转小写
                        best_match = None
                        exact_match = None
                        
                        for game in result:
                            game_name = game.get("name", "").lower()
                            cn_name = game.get("chineseName", "").lower()
                            
                            # 精确匹配优先
                            if game_name == original_keyword or cn_name == original_keyword:
                                exact_match = game
                                break
                            # 包含关键词的匹配
                            elif original_keyword in game_name or original_keyword in cn_name:
                                if not best_match:
                                    best_match = game
                        
                        # 选择最佳匹配
                        selected_game = exact_match or best_match or result[0]
                        
                        # 只返回游戏名字，用于后续精确搜索
                        s_keyword = selected_game.get("name", None)
                        if s_keyword:
                            return s_keyword
                        else:
                            raise Exception("模糊搜索返回结果但游戏名为空")
                    else:
                        raise Exception("模糊搜索无结果，请尝试更改关键词")
                else:
                    raise Exception(f"模糊搜索返回错误，返回码code:{code}")
        return None

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

class GalinfoPlugin(PluginBase):
    name = "galinfo"
    description = "提供Galgame信息查询，基于月幕Gal的api"
    version = "1.0"

    def __init__(self, context):
        super().__init__(context)
        self.ym = APIYm()
        # 标签从 config.yaml 读取，默认 #galgame
        self.trigger_tag = context.config.get('gal_tag', '#galgame')
        # AI增强功能开关
        self.use_ai_enhancement = context.config.get('use_ai_enhancement', False)
        # 获取 DeepSeek API 实例
        self.deepseek_api = self._get_deepseek_api()
        # AI系统提示词（支持自定义）
        self.ai_system_prompt = context.config.get('ai_system_prompt', self._get_default_prompt())
        # 缓存文件路径，存放到项目根目录 data/galinfo.json
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.cache_file = os.path.join(root_dir, 'data', 'galinfo.json')

        # 定时发帖功能配置
        auto_post_config = context.config.get('auto_post', {})
        self.auto_post_enabled = auto_post_config.get('enabled', False)
        self.auto_post_interval_hours = auto_post_config.get('interval_hours', 6)
        self.auto_post_random_delay_minutes = auto_post_config.get('random_delay_minutes', 30)
        self.auto_post_max_per_day = auto_post_config.get('max_posts_per_day', 4)
        self.auto_post_use_ai_enhanced_data = auto_post_config.get('use_ai_enhanced_data', False)
        
        # 设置默认的AI发帖提示词
        default_system_prompt = """你是一个热爱Galgame的玩家，正在社交媒体上分享你最近游玩某个游戏的体验和感受。请基于提供的游戏信息，以第一人称的视角写一篇自然、真实的游戏体验分享。

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
        
        self.auto_post_system_prompt = auto_post_config.get('ai_post_system_prompt', default_system_prompt)
        self.auto_post_user_prompt = auto_post_config.get('ai_post_user_prompt', '请基于以下游戏信息，写一篇游玩体验分享：\n\n{game_info}\n\n请以自然的语气分享你对这个游戏的感受和体验。')
        
        # 调试功能配置
        self.debug_enabled = auto_post_config.get('debug_enabled', True)
        self.debug_whitelist = auto_post_config.get('debug_whitelist', [])
        self.debug_tag = auto_post_config.get('debug_tag', '#galinfo_testaichat')
        self.direct_post_tag = auto_post_config.get('direct_post_tag', '#galinfo_aichat')
        
        # 定时发帖状态跟踪
        self.last_auto_post_time = None
        self.auto_posts_today = 0
        self.auto_post_reset_date = None

    # 载入缓存
    def _load_cache(self) -> Dict[str, Any]:
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    # 保存缓存
    def _save_cache(self, cache: Dict[str, Any]):
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

    def _get_default_prompt(self) -> str:
        """获取默认的AI系统提示词"""
        return """你是一个专业的Galgame(美少女游戏)评论专家。请根据用户提供的游戏基本信息，用更生动、有趣的语言重新整理和润色内容，让介绍更加吸引人。

  要求：
  1. 保持所有事实信息准确，不要编造内容
  2. 简介部分可以用更生动的语言重新表述，突出游戏的特色和亮点
  3. 保持原有格式结构，只润色简介内容，其他内容不要改变
  4. 语言要生动有趣但不过于夸张
  5. 如果游戏有中文版，可以适当提及对中文玩家的友好性
  6. 总长度控制在400字以内
  7. 由于 Misskey 不支持列表语法，会导致解析器出错，因此禁止使用。列举时请使用「・」。
"""

    def _get_default_auto_post_prompt(self) -> str:
        """获取默认的自动发帖AI系统提示词"""
        return """你是一个热爱Galgame的玩家，正在社交媒体上分享你最近游玩某个游戏的体验和感受。请基于提供的游戏信息，以第一人称的视角写一篇自然、真实的游戏体验分享。

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

    async def _enhance_with_ai(self, game_info: str, game_name: str) -> str:
        """使用 AI 对游戏信息进行增强处理"""
        if not self.use_ai_enhancement or not self.deepseek_api:
            return game_info
        
        try:
            self._log_plugin_action("AI增强", f"开始对游戏 '{game_name}' 的信息进行AI处理")
            
            user_prompt = f"请对以下Galgame信息进行润色优化：\n\n{game_info}"
            
            enhanced_info = await self.deepseek_api.generate_text(
                prompt=user_prompt,
                system_prompt=self.ai_system_prompt,
                max_tokens=500,
                temperature=0.7
            )
            
            self._log_plugin_action("AI增强", f"AI处理完成，增强内容长度: {len(enhanced_info)}")
            return enhanced_info.strip()
            
        except Exception as e:
            self._log_plugin_action("AI增强失败", f"错误: {str(e)}")
            # AI增强失败时返回原始信息
            return game_info

    async def _process_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理消息的核心逻辑"""
        try:
            # 获取消息文本内容
            note = message_data.get("note", message_data)
            text = note.get("text", "")
            
            self._log_plugin_action("消息处理", f"收到消息内容: {text[:100]}...")
            
            # 检查是否是调试触发标签
            if self.debug_enabled and self.debug_tag in text:
                self._log_plugin_action("触发检测", "检测到调试触发标签")
                return await self._handle_debug_trigger(message_data)
            
            # 检查是否是直接发帖触发标签
            if self.debug_enabled and self.direct_post_tag in text:
                self._log_plugin_action("触发检测", "检测到直接发帖触发标签")
                return await self._handle_direct_post_trigger(message_data)
            
            # 新增：只有 #recreate 而未包含触发标签时，提示格式错误
            if "#recreate" in text and self.trigger_tag not in text:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "格式错误：重建缓存需同时包含触发标签和#recreate"
                }
            
            # 仅检测自己的标签，且标签需为独立词（前后为分隔符或行首/行尾）
            import re
            tag_pattern = r'(?<![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】]){}(?![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】])'.format(
                re.escape(self.trigger_tag)
            )
            match = re.search(tag_pattern, text)
            if not match:
                return None  # 没有触发标签，且非单独 #recreate，不做响应
            
            self._log_plugin_action("收到消息", f"原始文本: '{text}', 触发标签: '{self.trigger_tag}'")
            self._log_plugin_action("标签匹配", f"在文本中找到触发标签")
            
            # 只移除首次出现的标签
            keyword = re.sub(tag_pattern, '', text, count=1).strip()
            self._log_plugin_action("初步提取", f"移除标签后: '{keyword}'")
            
            # 清理提及标记和其他特殊字符
            keyword = re.sub(r'@\w+', '', keyword).strip()  # 移除 @用户名
            self._log_plugin_action("清理提及", f"移除@标记后: '{keyword}'")
            
            keyword = re.sub(r'\s+', ' ', keyword).strip()
            # 新增：检测 #recreate 标志
            recreate = False
            if '#recreate' in keyword:
                recreate = True
                keyword = re.sub(r'#recreate\b', '', keyword).strip()
            self._log_plugin_action("重建缓存", f"recreate={recreate}")

            if not keyword:
                self._log_plugin_action("关键词为空", "返回提示信息")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "请在标签后输入要查询的游戏名"
                }
            
            username = self._extract_username(message_data)
            self._log_plugin_action("开始查询", f"用户: {username}, 关键词: '{keyword}'")
            
            # 获取Token/headers
            token = await self.ym.get_token()
            header = await self.ym.header(token)
            # 模糊搜索游戏名
            game_name = await self.ym.vague_search_game(header, keyword)
            self._log_plugin_action("模糊搜索", f"找到最匹配游戏名: '{game_name}'")

            # 检查缓存 - 直接查找对应的缓存类型
            cache = self._load_cache()
            cache_key = f"{game_name}{'_AI' if self.use_ai_enhancement else '_original'}"
                    
            if cache_key in cache and not recreate:
                entry = cache[cache_key]
                ts = entry.get("timestamp") or "未知"
                # 命中缓存时标明这是缓存数据并显示时间
                resp = f"【缓存数据】\n{entry['response']}\n\n缓存时间：{ts}"
                self._log_plugin_action("缓存命中", f"使用缓存回复游戏 '{game_name}'，时间：{ts}")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": resp
                }

            # 使用获取到的游戏名进行精确搜索
            search_result = await self.ym.search_game(header, game_name, 70)  # similarity=70
            self._log_plugin_action("精确搜索", f"获取游戏详细信息成功")
            
            result = search_result["result"]
            self._log_plugin_action("游戏数据", f"游戏完整信息: name={result.get('name')}, cnname={result.get('cnname')}")
            
            # 判断命中游戏信息中是否存在Oaid，如果存在则查询会社信息
            if result.get("oaid"):
                self._log_plugin_action("查询会社", f"OAID: {result.get('oaid')}")
                allinfo = await self.ym.search_orgid_mergeinfo(
                    header,
                    result.get("oaid"),
                    result,
                    False
                )
            else:
                self._log_plugin_action("无会社信息", "游戏没有OAID，跳过会社查询")
                allinfo = result.copy()
                allinfo.update({"oaname": None, "oacn": None})
            
            chains = self.ym.info_list(allinfo)
            self._log_plugin_action("格式化信息", f"生成回复内容，长度: {len(chains)}")
            
            # 使用 AI 增强处理（如果启用）
            if self.use_ai_enhancement:
                chains = await self._enhance_with_ai(chains, game_name)
                self._log_plugin_action("AI增强", f"AI增强完成，最终内容长度: {len(chains)}")
            
            self._log_plugin_action("查询完成", f"找到游戏: {game_name}")
            
            ai_status = " (AI增强)" if self.use_ai_enhancement else ""
            response_text = f"已匹配最符合的一条：{game_name}{ai_status}\n{chains}"

            # 保存缓存：同时保存原始和AI增强数据
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 保存原始数据
            original_response = f"已匹配最符合的一条：{game_name}\n{self.ym.info_list(allinfo)}"
            cache[f"{game_name}_original"] = {
                "response": original_response,
                "timestamp": timestamp,
                "game_data": allinfo
            }
            
            # 如果启用了AI增强，保存AI增强后的数据
            if self.use_ai_enhancement:
                cache[f"{game_name}_AI"] = {
                    "response": response_text,
                    "timestamp": timestamp,
                    "game_data": allinfo
                }
            
            self._save_cache(cache)

            return {
                "handled": True,
                "plugin_name": self.name,
                "response": response_text
            }
        except Exception as e:
            self._log_plugin_action("查询失败", str(e))
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": f"查询失败：{e}"
            }
        
        return None

    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        """定时发帖功能"""
        if not self.auto_post_enabled:
            return None
        
        try:
            # 检查是否到了发帖时间
            if not self._should_auto_post():
                return None
            
            # 重置每日计数（如果需要）
            self._reset_daily_counter_if_needed()
            
            # 检查每日发帖限制
            if self.auto_posts_today >= self.auto_post_max_per_day:
                self._log_plugin_action("发帖限制", f"今日已达发帖上限 {self.auto_post_max_per_day}")
                return None
            
            # 从缓存中随机选择一个游戏
            game_info = self._get_random_game_from_cache()
            if not game_info:
                self._log_plugin_action("无缓存数据", "缓存中没有可用的游戏数据")
                return None
            
            # 生成AI发帖内容
            post_content = await self._generate_auto_post_content(game_info)
            if not post_content:
                self._log_plugin_action("生成失败", "AI生成发帖内容失败")
                return None
            
            # 更新发帖状态
            self.last_auto_post_time = datetime.datetime.now()
            self.auto_posts_today += 1
            
            self._log_plugin_action("自动发帖", f"生成发帖内容成功，今日第 {self.auto_posts_today} 次发帖")
            
            return {
                "content": post_content,
                "visibility": "public"  # 可以根据需要调整可见性
            }
        
        except Exception as e:
            self._log_plugin_action("自动发帖失败", str(e))
            return None
    
    def _should_auto_post(self) -> bool:
        """检查是否应该进行自动发帖"""
        if self.last_auto_post_time is None:
            return True
        
        # 计算下次发帖时间（包含随机延迟）
        interval_seconds = self.auto_post_interval_hours * 3600
        random_delay_seconds = random.randint(0, self.auto_post_random_delay_minutes * 60)
        next_post_time = self.last_auto_post_time + datetime.timedelta(
            seconds=interval_seconds + random_delay_seconds
        )
        
        return datetime.datetime.now() >= next_post_time
    
    def _reset_daily_counter_if_needed(self):
        """如果是新的一天，重置每日发帖计数"""
        today = datetime.date.today()
        if self.auto_post_reset_date != today:
            self.auto_post_reset_date = today
            self.auto_posts_today = 0
            self._log_plugin_action("重置计数", f"新的一天开始，重置发帖计数")
    
    def _get_random_game_from_cache(self) -> Optional[str]:
        """从缓存中随机选择一个游戏信息"""
        try:
            cache = self._load_cache()
            if not cache:
                return None
            
            # 根据配置选择使用AI增强数据还是原始数据
            target_suffix = '_AI' if self.auto_post_use_ai_enhanced_data else '_original'
            
            # 收集符合条件的游戏数据
            eligible_games = []
            for key, entry in cache.items():
                if key.endswith(target_suffix) and 'game_data' in entry:
                    game_data = entry['game_data']
                    if game_data:
                        # 直接使用保存的游戏基本数据重新格式化
                        game_info = self.ym.info_list(game_data)
                        eligible_games.append(game_info)
            
            if not eligible_games:
                # 如果没找到目标类型的数据，尝试使用另一种类型
                fallback_suffix = '_original' if self.auto_post_use_ai_enhanced_data else '_AI'
                for key, entry in cache.items():
                    if key.endswith(fallback_suffix) and 'game_data' in entry:
                        game_data = entry['game_data']
                        if game_data:
                            game_info = self.ym.info_list(game_data)
                            eligible_games.append(game_info)
                            
                if eligible_games:
                    self._log_plugin_action("备用数据", f"未找到{'AI增强' if self.auto_post_use_ai_enhanced_data else '原始'}数据，使用{'原始' if self.auto_post_use_ai_enhanced_data else 'AI增强'}数据")
                else:
                    return None
            
            # 随机选择一个游戏
            selected_game = random.choice(eligible_games)
            data_type = "AI增强" if self.auto_post_use_ai_enhanced_data else "原始"
            self._log_plugin_action("随机选择", f"从 {len(eligible_games)} 个缓存游戏中选择了一个({data_type}数据)")
            return selected_game
        
        except Exception as e:
            self._log_plugin_action("获取随机游戏失败", str(e))
            return None
    
    async def _generate_auto_post_content(self, game_info: str) -> Optional[str]:
        """使用AI生成自动发帖内容"""
        if not self.deepseek_api:
            return None
        
        try:
            user_prompt = self.auto_post_user_prompt.format(game_info=game_info)
            
            self._log_plugin_action("AI生成发帖", "开始生成自动发帖内容")
            
            post_content = await self.deepseek_api.generate_text(
                prompt=user_prompt,
                system_prompt=self.auto_post_system_prompt,
                max_tokens=400,
                temperature=0.8  # 稍高的温度以增加创造性
            )
            
            self._log_plugin_action("AI生成完成", f"生成内容长度: {len(post_content)}")
            return post_content.strip()
        
        except Exception as e:
            self._log_plugin_action("AI生成发帖失败", str(e))
            return None
    
    async def _handle_debug_trigger(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理调试触发事件"""
        try:
            # 检查用户权限
            username = self._extract_username(message_data)
            if username not in self.debug_whitelist:
                self._log_plugin_action("调试权限检查", f"用户 {username} 不在白名单中")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "抱歉，您没有使用调试功能的权限。"
                }
            
            self._log_plugin_action("调试触发", f"用户 {username} 触发了调试发帖功能")
            
            # 从缓存中随机选择一个游戏
            game_info = self._get_random_game_from_cache()
            if not game_info:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "调试失败：缓存中没有可用的游戏数据。请先通过查询功能生成一些缓存数据。"
                }
            
            # 生成AI发帖内容
            post_content = await self._generate_auto_post_content(game_info)
            if not post_content:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "调试失败：AI生成发帖内容失败。"
                }
            
            data_type = "AI增强" if self.auto_post_use_ai_enhanced_data else "原始"
            debug_response = f"【调试模式 AI 发帖预览】\n使用数据类型：{data_type}\n\n{post_content}\n\n--- 调试信息 ---\n游戏数据预览：\n{game_info[:200]}{'...' if len(game_info) > 200 else ''}"
            
            self._log_plugin_action("调试成功", f"为用户 {username} 生成了调试发帖内容")
            
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": debug_response
            }
            
        except Exception as e:
            self._log_plugin_action("调试处理失败", str(e))
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": f"调试功能出错：{str(e)}"
            }
    
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
            game_info = self._get_random_game_from_cache()
            if not game_info:
                self._log_plugin_action("缓存检查", "缓存中没有可用的游戏数据")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "直接发帖失败：缓存中没有可用的游戏数据。请先通过查询功能生成一些缓存数据。"
                }
            
            self._log_plugin_action("缓存检查", f"成功获取游戏数据，长度: {len(game_info)}")
            
            # 生成AI发帖内容
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
            
            data_type = "AI增强" if self.auto_post_use_ai_enhanced_data else "原始"
            self._log_plugin_action("直接发帖成功", f"为用户 {username} 生成了发帖内容，使用{data_type}数据")
            
            # 返回发帖格式，这将触发实际的发帖
            result = {
                "content": post_content,
                "visibility": "public",
                "handled": True,
                "plugin_name": self.name
            }
            
            self._log_plugin_action("返回结果", f"返回发帖结果: {result}")
            return result
            
        except Exception as e:
            self._log_plugin_action("直接发帖处理失败", str(e))
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": f"直接发帖功能出错：{str(e)}"
            }




