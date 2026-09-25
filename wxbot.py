# -*- coding: utf-8 -*-
"""
wxbot —— 兼容层
让 WeChatBot 项目无需 wxautox4_wechatbot 即可运行。

用法：把 bot.py 顶部的导入
    from wxautox4_wechatbot import WeChat
改成
    from wxbot import WeChat

底层由 wechatauto 驱动：数据库监听接收 + 坐标/OCR 界面发送，
适配当前微信 4.x 自绘渲染（wxautox 旧版依赖的 x11 window 结构已不存在）。

差异说明：
  * 消息接收走本地数据库轮询（每秒一次），延迟约 1~2 秒。
  * 发送走坐标/OCR（打开会话 -> 输入 -> 回车），比旧版稍慢；
    默认用 wechatauto 的 fast 档节奏（见下方 WECHATAUTO_RHYTHM）。
  * 语音转文字、合并转发解析在兼容层不支持，会安全降级
    （返回空值/记录日志），不影响其它功能；语音取不到时用
    WxMessage.voice_note() 说明原因（没在微信里播放过 vs 库/索引问题）。
  * 拍一拍/撤回/语音通话已接上 wechatauto（UIA 热激活 + OCR），
    分别对应 WxMessage.tickle() / select_option('撤回') / WeChat.VoiceCall()。
  * 群消息发送者身份来自 wechatauto 1.2.4.1：WxMessage.sender_wxid 是真 wxid，
    WxMessage.sender 是备注/昵称，群里的图片/文件/语音同样能认出人。
  * 新增纯读库能力（都不驱动界面）：WeChat.GetGroupMembers() 群成员、
    GetRecalled() 撤回记录（配 StartRecallGuard()）、
    GetMoments() / GetNewMoments() / GetMomentInteractions() 朋友圈。
"""

import glob
import logging
import os
import re
import sqlite3
import time

# wechatauto 1.2.3 起对每次对外写动作（发送/点赞/评论…）默认按 natural 档限速：
# 间隔 2.5~6s、120s 内 6 次后冷却 30~75s。本项目是连发多段的聊天机器人，
# 会被拖住，所以默认改成 fast 档（间隔 0.6~1.4s、20 次/120s）。用户自己设的
# 同名环境变量优先（setdefault），要更保守可设 WECHATAUTO_RHYTHM=natural。
os.environ.setdefault("WECHATAUTO_RHYTHM", "fast")

from wechatauto.wx import WeChat as _BaseWeChat
from wechatauto.wx import Chat as _BaseChat
from wechatauto import MediaDownloader
from wechatauto.moment import MomentDB
from wechatauto.param import WxResponse
from wechatauto import wxlog

log = logging.getLogger("wxbot")

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
_URL_RE = re.compile(r"https?://[^\s\"'<>\[\]]+")

# wechatauto 语音可用性的 reason -> 说明（见 MediaDownloader.list_voice_status）
_VOICE_REASON_ZH = {
    "audio_not_downloaded": "微信没把这段音频存到本地（要在微信里播放过一次才有）",
    "audio_missing_from_media_db": "音频索引里查不到这段音频",
    "session_not_in_media_index": "这个会话不在音频索引里",
    "no_server_id": "这条语音没有服务端 ID",
    "empty_blob": "音频数据是空的",
}

# 微信数据库中文类型 -> bot 使用的英文类型
_TYPE_MAP = {
    "文本": "text",
    "图片": "image",
    "语音": "voice",
    "视频": "video",
    "动画表情": "emotion",
    "表情": "emotion",
    "位置": "location",
    "文件/链接/卡片": "file",
    "系统消息": "system",
    "引用消息": "quote",
    "撤回消息": "recall",
}


def _to_text(x):
    if x is None:
        return ""
    if isinstance(x, bytes):
        try:
            return x.decode("utf-8", "ignore")
        except Exception:
            return ""
    return str(x)


def _strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for a, b in (
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&apos;", "'"),
        ("&#10;", "\n"),
        ("&nbsp;", " "),
    ):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def _extract_url(blob):
    m = _URL_RE.search(blob)
    return m.group(0) if m else None


class WxMessage:
    """bot 兼容消息对象（对齐 wxautox4_wechatbot 的消息接口）"""

    def __init__(self, row, chat, db, media, self_wxid):
        self._row = row
        self._chat = chat
        self._db = db
        self._media = media
        self._self_wxid = self_wxid or ""
        self.local_id = row.get("local_id")
        self.create_time = row.get("create_time")
        self.sort_seq = row.get("sort_seq")

        type_cn = row.get("type") or ""
        self._type_cn = type_cn
        self.type = _TYPE_MAP.get(type_cn, "text")

        sender_id = row.get("sender_id")
        self._is_group = bool(
            self._chat
            and str(getattr(self._chat, "_wxid", "")).endswith("@chatroom")
        )
        is_self = sender_id in (2, "2") or str(sender_id) == self._self_wxid
        self.attr = "self" if is_self else "friend"

        content = _to_text(row.get("content"))
        prefix = self._extract_prefix_sender(content)
        self.sender_wxid = self._resolve_sender_wxid(row, prefix)
        self.sender = self._resolve_sender(sender_id, prefix)
        self.content = self._clean_content(content, prefix)

        self.quote_content = None
        self._link_url = None
        self._merge = None
        self._file_path = None
        self._cached_full = None
        self._classify()

    # ---------------------------------------------------------------- 内部

    def _full_row(self):
        if self._cached_full is None:
            try:
                if (
                    self._chat
                    and getattr(self._chat, "_wxid", None)
                    and self.local_id is not None
                ):
                    self._cached_full = (
                        self._db.get_message_row(self._chat._wxid, self.local_id) or {}
                    )
                else:
                    self._cached_full = {}
            except Exception:
                self._cached_full = {}
        return self._cached_full

    @staticmethod
    def _extract_prefix_sender(content):
        m = re.match(r"^(wxid_[^\s:\n]+|gh_[^\s:\n]+|\d{6,}):\n", content)
        return m.group(1) if m else None

    def _resolve_sender_wxid(self, row, prefix):
        """真实发送者 wxid（wechatauto 1.2.4.1 起由 db 层把 real_sender_id 换好）。

        纯数字要丢掉：1.2.4 之前那套兜底会把数字 rowid 冒充成用户名。
        拿不到时退正文前缀（文本消息里才有），再拿不到就是空字符串。
        """
        if self.attr == "self":
            return self._self_wxid
        value = str(row.get("sender_username") or "").strip()
        if value and not value.isdigit():
            return value
        return prefix or ""

    def _nickname_of(self, wxid):
        """wxid -> 备注/昵称（进程内缓存，逐条查 contact.db 太贵）。"""
        if not wxid:
            return ""
        try:
            return self._db.nickname_map().get(wxid, "") or ""
        except Exception:
            return ""

    def _resolve_sender(self, sender_id, prefix):
        # 微信4.x 数据库里 real_sender_id 只是短数字ID，不能当 wxid 用。
        if self.attr == "self":
            try:
                return self._db.get_self_info().get("nick_name") or "我"
            except Exception:
                return "我"
        if self._is_group:
            # 群里先用真 wxid 换名字：图片/文件/语音这些类型正文里没有
            # "wxid_xxx:\n" 前缀，旧实现只能回落到一个无意义的数字。
            name = self._nickname_of(self.sender_wxid) or self._nickname_of(prefix)
            return name or str(sender_id)
        # 私聊：对方就是聊天窗口本身
        try:
            return self._chat.who or str(sender_id)
        except Exception:
            return str(sender_id)

    @staticmethod
    def _clean_content(content, prefix):
        if prefix:
            content = re.sub(r"^" + re.escape(prefix) + r":\n", "", content)
        content = content.replace("[文本]", "").strip()
        return content

    def _classify(self):
        if self._type_cn == "文件/链接/卡片":
            full = self._full_row()
            raw = _to_text(full.get("content"))
            packed = _to_text(full.get("packed_info"))
            blob = raw + "\n" + packed
            url = _extract_url(blob)
            if url:
                self.type = "link"
                self._link_url = url
                return
            text = _to_text(full.get("content"))
            if "<refermsg" in text or "<appmsg" in text:
                title = re.search(r"<title>(.*?)</title>", text, re.S)
                self.quote_content = _strip_tags(title.group(1)) if title else _strip_tags(text)[:200]
                if "<record" in text or "record" in text.lower():
                    self.type = "merge"
                else:
                    self.type = "quote"
                return
            self.type = "file"
        elif self._type_cn == "系统消息":
            if "拍了拍" in self.content:
                self.attr = "tickle"

    # ------------------------------------------------------------- 对外接口

    def to_text(self):
        if self.type == "voice":
            return ""
        return self.content

    def get_url(self):
        return self._link_url

    def get_messages(self):
        return self._merge

    def voice_status(self):
        """这条语音的音频到底在不在本地（委托 wechatauto 的 voice_status）。

        取不到音频时 `download_voice()` 只返回 None，调用方分不清「微信本地
        根本没存这段音频」和「库读挂了」；这里给出 reason。非语音/查不到返回 {}。
        """
        if self.type != "voice" or not self._chat or self.local_id is None:
            return {}
        wxid = getattr(self._chat, "_wxid", None)
        if not wxid:
            return {}
        try:
            return self._media.voice_status(wxid, self.local_id) or {}
        except Exception as e:
            wxlog.debug("语音状态查询失败: %s" % e)
            return {}

    def voice_note(self):
        """语音可用性的一句话说明（供拼进模型上下文）。非语音返回空串。"""
        if self.type != "voice":
            return ""
        status = self.voice_status()
        reason = status.get("reason")
        if reason == "ok":
            return "音频在本地，但本兼容层不做语音转文字"
        if reason:
            return _VOICE_REASON_ZH.get(reason, "音频不可用 (%s)" % reason)
        return "音频不可用"

    def download(self):
        if (
            self.type == "image"
            and self._chat
            and getattr(self._chat, "_wxid", None)
            and self.local_id is not None
        ):
            try:
                p = self._media.download_image(self._chat._wxid, self.local_id)
                if p:
                    return p
            except Exception as e:
                log.warning("图片下载失败: %s", e)
            # 原图未下载到本地时，回退到缩略图 _t.dat，图片识别仍可用
            try:
                return self._download_thumbnail()
            except Exception as e:
                log.warning("缩略图下载失败: %s", e)
        return None

    def _download_thumbnail(self):
        row = self._db.get_message_row(self._chat._wxid, self.local_id)
        if not row:
            return None
        md5 = self._media._img_md5(row)
        if not md5:
            return None
        base = os.path.join(self._db.account_dir, "msg", "attach")
        hits = glob.glob(os.path.join(base, "**", md5 + "_t.dat"), recursive=True)
        if not hits:
            return None
        data = self._media.decrypt_image(hits[0])
        if not data:
            return None
        if data[:4] == b"\x89PNG":
            ext = "png"
        elif data[:3] == b"GIF":
            ext = "gif"
        else:
            ext = "jpg"
        out = os.path.join(
            self._media.save_dir, "%s_%s_thumb.%s" % (self._chat._wxid, self.local_id, ext)
        )
        os.makedirs(self._media.save_dir, exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)
        return out

    def capture(self, save_dir: str = None):
        """截取当前表情消息画面，返回图片路径；失败返回 None。

        委托 wechatauto 的 EmojiMessage.capture()：打开会话 → 滚动到底 →
        对最后一条消息区域截图并自动裁剪。非表情消息返回 None。
        """
        if self.type != "emotion":
            return None
        try:
            from wechatauto.wx import _db_row_to_message

            # 兼容层把 "表情"/"动画表情" 都归一为 emotion，但 wechatauto
            # 的消息工厂只认 "动画表情"，这里统一后再委托。
            row = dict(self._row)
            if row.get("type") == "表情":
                row["type"] = "动画表情"
            msg = _db_row_to_message(row, self._chat, self._self_wxid)
            return msg.capture(save_dir)
        except Exception as e:
            log.warning("表情截图失败: %s", e)
            return None

    def tickle(self, who: str = None) -> bool:
        """对消息所在会话的对方发起「拍一拍」。

        委托 wechatauto 的 Chat.Poke（右键对方头像 + OCR 菜单）。返回
        是否成功。不指定 who 时拍当前会话对象。
        """
        try:
            chat = self._chat
            if chat is None:
                log.warning("拍一拍失败: 无会话对象")
                return False
            resp = chat.Poke(who or getattr(chat, "who", None))
            return bool(resp and resp.get("status") in ("成功",))
        except Exception as e:
            log.warning("拍一拍失败: %s", e)
            return False

    def select_option(self, option: str, **kwargs) -> bool:
        """对消息所在会话执行菜单操作（当前支持「撤回」）。

        委托 wechatauto 的 Chat.RecallLastMessage。返回是否成功。
        """
        if option not in ("撤回", "recall"):
            log.info("select_option(%s) 暂不支持，已忽略", option)
            return False
        try:
            chat = self._chat
            if chat is None:
                log.warning("撤回失败: 无会话对象")
                return False
            resp = chat.RecallLastMessage(getattr(chat, "who", None))
            return bool(resp and resp.get("status") in ("成功",))
        except Exception as e:
            log.warning("撤回失败: %s", e)
            return False

    def __str__(self):
        return "<WxMessage %s from %s: %s>" % (self.type, self.sender, self.content[:50])


class WeChat(_BaseWeChat):
    """兼容层主类：在 wechatauto.wx.WeChat 之上补齐 bot 需要的接口。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._media = MediaDownloader(self._db)
        self._recall_guard = None
        self._moment_db_cache = None

    # ------------------------------------------------------------- 消息监听

    def _make_listen_cb(self, chat, callback):
        self_wxid = ""
        try:
            self_wxid = self._db.get_self_info()["username"]
        except Exception:
            pass

        def _wrapper(row, listener):
            try:
                msg = WxMessage(row, chat, self._db, self._media, self_wxid)
                callback(msg, chat)
            except Exception:
                import traceback

                wxlog.debug("wxbot 监听回调错误:\n%s" % traceback.format_exc())

        return _wrapper

    def AddListenChat(self, nickname=None, callback=None, **kwargs):
        """校验昵称确实存在后再监听；找不到返回失败（falsy），供 bot 退出。

        相比基类更稳健：
          * 微信写库瞬间会抛 sqlite "database disk image is malformed"，这里做重试；
          * 预先设置水位后再注册回调，避免水位初始化失败导致旧消息洪泛。
        """
        if not nickname:
            return WxResponse.failure("昵称为空")
        if nickname in self.listen:
            return WxResponse.failure("该聊天已监听")
        uname = self._resolve_uname(nickname)
        if uname is None:
            return WxResponse.failure("找不到聊天窗口: %s" % nickname)
        if not self._listener_is_listening:
            self._listener_start()  # 首次调用，listen 为空，仅启动监听线程
        chat = _BaseChat(nickname, self._gui, self._db)
        if uname != chat._wxid:
            chat._wxid = uname
        self.listen[nickname] = (chat, callback)
        self._listen_wrappers[nickname] = self._make_listen_cb(chat, callback)
        listener = self._listener
        if listener is None:
            return WxResponse.failure("监听器未启动: %s" % nickname)
        # 先设水位（带重试），再注册回调
        for attempt in range(5):
            try:
                msgs = self._db.get_messages(uname, limit=1)
                listener._watermark[uname] = msgs[0]["sort_seq"] if msgs else 0
                listener.add_listener(uname, self._listen_wrappers[nickname])
                return chat
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                log.warning("数据库暂不可用(第%d次, %s): %s", attempt + 1, nickname, e)
                time.sleep(1.5)
        return WxResponse.failure("监听失败: %s" % nickname)

    def _resolve_uname(self, nickname):
        """昵称 -> username；数据库瞬时不可用时重试。找不到返回 None。"""
        if nickname in ("filehelper", "文件传输助手"):
            return "filehelper"
        for _ in range(5):
            try:
                for hit in self._db.search_contact(nickname):
                    if nickname in (hit.get("nick_name"), hit.get("remark")):
                        return hit["username"]
                return None
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                log.warning("数据库暂不可用(解析昵称): %s", e)
                time.sleep(1.5)
        return None

    # --------------------------------------------------------------- 发送

    def _display_name(self, who):
        """who 可能是昵称，也可能是 username(wxid/@chatroom)，统一转成界面显示名。"""
        if not who:
            return who
        if who in ("filehelper", "文件传输助手"):
            return "文件传输助手"
        try:
            nick = self._db.get_nickname(who)
            if nick and nick != who:
                return nick
        except Exception:
            pass
        return who

    def SendMsg(self, msg, who=None, **kwargs):
        return super().SendMsg(msg, who=self._display_name(who), **kwargs)

    def SendFiles(self, filepath, who=None, **kwargs):
        who = self._display_name(who)
        if isinstance(filepath, str) and filepath.lower().endswith(_IMG_EXTS):
            try:
                return self._gui.send_image(filepath, who)
            except Exception as e:
                log.warning("send_image 失败，回退为文件发送: %s", e)
        return super().SendFiles(filepath, who=who, **kwargs)

    # ----------------------------------------------------------- 会话/窗口

    def GetListenChatType(self, nickname):
        """直接从已注册的监听对象读取聊天类型，避免全量扫描会话。

        返回 "group"/"friend"；未监听该昵称时返回 None。
        """
        if not nickname:
            return None
        entry = self.listen.get(nickname)
        if not entry:
            return None
        chat = entry[0] if isinstance(entry, tuple) else entry
        try:
            info = chat.ChatInfo()
        except Exception as e:
            log.warning("GetListenChatType(%s) 失败: %s", nickname, e)
            return None
        return info.get("chat_type")

    def GetAllSubWindow(self):
        """返回所有会话的 Chat 实例（用于 bot 判断群聊/私聊）。

        会话上限从 50 提到 500：wechatauto 自己的监听发现用的就是 500，
        50 会让「最近 50 个会话之外」的群聊判不出类型（get_chat_type_info
        的回退路径依赖这个列表）。
        """
        subs = []
        try:
            for row in self._db.get_sessions(limit=500):
                username = row.get("username")
                if not username:
                    continue
                name = username
                try:
                    nick = self._db.get_nickname(username)
                    if nick and nick != username:
                        name = nick
                except Exception:
                    pass
                chat = _BaseChat(name, self._gui, self._db)
                if username != chat._wxid:
                    chat._wxid = username
                subs.append(chat)
        except Exception as e:
            log.warning("GetAllSubWindow 失败: %s", e)
        return subs

    def _as_session_username(self, name):
        """把会话标识统一成 username。

        传进来的可能已经是 username（`xxx@chatroom` / `wxid_xxx`），这时不能
        再走一遍通讯录搜索——`_resolve_uname` 是按昵称/备注匹配的，对群 wxid
        会返回 None，于是「按 wxid 查群成员」会查不到。
        """
        if not name:
            return None
        text = str(name)
        if text.endswith("@chatroom") or text.startswith(("wxid_", "gh_")):
            return text
        if text in ("filehelper", "文件传输助手"):
            return "filehelper"
        try:
            return self._resolve_uname(text)
        except Exception:
            return None

    # --------------------------------------------------------------- 群成员

    def GetGroupMembers(self, nickname):
        """群成员列表（静态读库，不点界面）。

        每条含 username / nick_name / remark / is_owner。wechatauto 的
        GetGroupMembers 只对 `@chatroom` 生效，配合监听回调里的
        `msg.sender_wxid` 能认出「不在通讯录里的人」。非群聊/找不到返回 []。
        """
        uname = self._as_session_username(nickname or "")
        if not uname or not uname.endswith("@chatroom"):
            return []
        try:
            return self._db.get_group_members(uname) or []
        except Exception as e:
            wxlog.warning("群成员查询失败 (%s): %s" % (nickname, e))
            return []

    # ------------------------------------------------------------ 防撤回

    def GetNickname(self, user):
        """wxid/username -> 备注或昵称（拿不到就返回空串，不抛异常）。

        朋友圈动态只给发布者 wxid，要对上「用户列表」里填的名字就得用它。
        """
        if not user:
            return ""
        try:
            name = self._db.nickname_map().get(user, "")
            if name:
                return name
        except Exception:
            pass
        try:
            name = self._db.get_nickname(user)
            return "" if name == user else (name or "")
        except Exception:
            return ""

    def StartRecallGuard(self, backfill=50, scan_interval=None, scan_limit=None):
        """挂上 wechatauto 的 RecallGuard（镜像 + 媒体备份 + 撤回复原）。

        只读微信库、只写自己的镜像目录（默认 ~/Documents/wechatauto_recall），
        不驱动界面。覆盖范围是当前**已监听**的会话：传 users=None 给底层会
        监听全部会话，轮询成本随会话数线性涨。

        Args:
            backfill: 启动时把每个会话最近多少条历史消息补进镜像（0 表示不补）。
            scan_interval: 撤回轮询间隔秒数，None 用底层默认 2.0。
            scan_limit: 每会话每轮重读最近多少条，None 用底层默认 30。

        返回是否挂载成功。重复调用是幂等的。
        """
        if self._recall_guard is not None:
            return True
        if self._listener is None:
            wxlog.warning("RecallGuard 未启动：监听器尚未启动")
            return False
        users = []
        for name in list(self.listen.keys()):
            try:
                uname = self._resolve_uname(name)
            except Exception:
                uname = None
            if uname and uname not in users:
                users.append(uname)
        if not users:
            wxlog.warning("RecallGuard 未启动：监听列表为空")
            return False
        kwargs = {}
        try:
            if scan_interval:
                kwargs["scan_interval"] = max(0.5, float(scan_interval))
            if scan_limit:
                kwargs["scan_limit"] = max(1, int(scan_limit))
        except (TypeError, ValueError):
            kwargs = {}
        try:
            from wechatauto.recall import RecallGuard

            guard = RecallGuard(self._db, downloader=self._media, **kwargs)
            guard.watch(self._listener, users=users, backfill=int(backfill or 0))
        except Exception as e:
            wxlog.warning("RecallGuard 启动失败: %s" % e)
            return False
        self._recall_guard = guard
        log.info("防撤回已挂载，覆盖 %d 个会话", len(users))
        return True

    def StopRecallGuard(self):
        guard, self._recall_guard = self._recall_guard, None
        if guard is not None:
            try:
                guard.close()
            except Exception as e:
                wxlog.debug("RecallGuard 关闭异常: %s" % e)

    def GetRecalled(self, chat=None, limit=20):
        """撤回事件记录（新的在前）：chat/revoke_time/revoker/original_content。

        chat 传昵称或 username，留空为全部会话。original_content 是监听期间
        存进镜像的原文；监听之前就被撤回的救不回来，这一条会是空串。
        未挂 RecallGuard 时返回 []。
        """
        if self._recall_guard is None:
            return []
        uname = self._as_session_username(chat) if chat else None
        try:
            return self._recall_guard.get_recalled(uname, limit=limit) or []
        except Exception as e:
            wxlog.warning("读取撤回记录失败: %s" % e)
            return []

    # ------------------------------------------------------------ 朋友圈

    def _moment_db(self):
        if self._moment_db_cache is None:
            self._moment_db_cache = MomentDB(self._db)
        return self._moment_db_cache

    def GetMoments(self, who=None, limit=5):
        """读某人最近的朋友圈动态（纯读库，不驱动界面）。

        who 传昵称/username；留空读自己的。返回 feed 列表，每条含
        tid / nickname / text / create_time / images / videos / likes / comments。
        """
        try:
            username = self._as_session_username(who) if who else None
            return self._moment_db().get_moments(
                username=username or self._db.wxid, limit=limit
            ) or []
        except Exception as e:
            wxlog.warning("读取朋友圈失败 (%s): %s" % (who, e))
            return []

    def GetNewMoments(self, since_tid=None, limit=200):
        """增量拉取比 since_tid 新的动态，返回 (feeds, new_latest_tid)。

        适合自己写「有新朋友圈就处理」的轮询：无新动态时 feeds 为空、
        new_latest_tid 为 None（水位不用推进）。

        注意水位要用返回的 new_latest_tid（int），别用 feed['tid']：自己发的
        动态 tid 是 wxid 字符串，拿它当水位会直接抛 TypeError。
        """
        try:
            return self._moment_db().get_moments_since(since_tid, limit=limit)
        except Exception as e:
            wxlog.warning("增量读取朋友圈失败: %s" % e)
            return [], None

    def GetMomentInteractions(self, only_unread=False, limit=50):
        """他人对我朋友圈的点赞/评论通知（SnsMessage_tmp3，纯读库）。

        每条含 type(1=赞/2=评论)、from_nickname、content、create_time、unread。
        """
        try:
            return self._moment_db().get_interactions(
                limit=limit, only_unread=only_unread
            ) or []
        except Exception as e:
            wxlog.warning("读取朋友圈互动失败: %s" % e)
            return []

    # ------------------------------------------------------------ 通话/撤回

    def VoiceCall(self, user_id=None, **kwargs):
        """发起语音通话（委托 wechatauto 的 Chat.VoiceCall）。

        需 UIA 驱动可用（热激活后生效）；失败时返回 False 由调用方降级。
        """
        try:
            chat = _BaseChat(user_id, self._gui, self._db)
            resp = chat.VoiceCall(video=bool(kwargs.get("video", False)))
            return bool(resp and resp.get("status") in ("成功",))
        except Exception as e:
            wxlog.warning("VoiceCall 失败 (%s): %s", user_id, e)
            return False
