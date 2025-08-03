import os
import aiohttp
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
            
            # 仅检测自己的标签，且标签需为独立词（前后为分隔符或行首/行尾）
            import re
            tag_pattern = r'(?<![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】]){}(?![^\s.,!?;:()\[\]{{}}\'"“”‘’<>《》|/\\~`·、，。！？；：（）【】])'.format(re.escape(self.trigger_tag))
            match = re.search(tag_pattern, text)
            if not match:
                return None  # 没有自己的标签，直接不响应

            self._log_plugin_action("收到消息", f"原始文本: '{text}', 触发标签: '{self.trigger_tag}'")
            self._log_plugin_action("标签匹配", f"在文本中找到触发标签")
            
            # 只移除首次出现的标签
            keyword = re.sub(tag_pattern, '', text, count=1).strip()
            self._log_plugin_action("初步提取", f"移除标签后: '{keyword}'")
            
            # 清理提及标记和其他特殊字符
            keyword = re.sub(r'@\w+', '', keyword).strip()  # 移除 @用户名
            self._log_plugin_action("清理提及", f"移除@标记后: '{keyword}'")
            
            keyword = re.sub(r'\s+', ' ', keyword).strip()   # 规范化空格
            self._log_plugin_action("最终关键词", f"规范化后: '{keyword}'")
            
            if not keyword:
                self._log_plugin_action("关键词为空", "返回提示信息")
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "请在标签后输入要查询的游戏名"
                }
            
            username = self._extract_username(message_data)
            self._log_plugin_action("开始查询", f"用户: {username}, 关键词: '{keyword}'")
            
            try:
                token = await self.ym.get_token()
                self._log_plugin_action("获取Token", "成功获取API Token")
                
                header = await self.ym.header(token)
                self._log_plugin_action("构建Header", "成功构建请求头")
                
                # 先进行模糊搜索获取游戏名
                game_name = await self.ym.vague_search_game(header, keyword)
                self._log_plugin_action("模糊搜索", f"找到最匹配游戏名: '{game_name}'")
                
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
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": f"已匹配最符合的一条：{game_name}{ai_status}\n{chains}"
                }
            except Exception as api_error:
                self._log_plugin_action("API调用失败", f"错误: {str(api_error)}")
                raise api_error
        except Exception as e:
            self._log_plugin_action("查询失败", str(e))
            return {
                "handled": True,
                "plugin_name": self.name,
                "response": f"查询失败：{e}"
            }
        
        return None




