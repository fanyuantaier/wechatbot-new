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
  * 发送走坐标/OCR（打开会话 -> 输入 -> 回车），比旧版稍慢。
  * 语音转文字、合并转发解析、发起语音通话在兼容层不支持，
    会安全降级（返回空值/记录日志），不影响其它功能。
"""

import glob
import logging
import os
import re
import sqlite3
import time

from wechatauto.wx import WeChat as _BaseWeChat
from wechatauto.wx import Chat as _BaseChat
from wechatauto import MediaDownloader
from wechatauto.param import WxResponse
from wechatauto import wxlog

log = logging.getLogger("wxbot")

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
_URL_RE = re.compile(r"https?://[^\s\"'<>\[\]]+")

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

    def _resolve_sender(self, sender_id, prefix):
        # 微信4.x 数据库里 real_sender_id 只是短数字ID，不能当 wxid 用。
        if self.attr == "self":
            try:
                return self._db.get_self_info().get("nick_name") or "我"
            except Exception:
                return "我"
        # 群聊：文本消息带 "wxid_xxx:\n" 前缀，据此解析发者昵称
        if prefix:
            try:
                return self._db.get_nickname(prefix) or prefix
            except Exception:
                return prefix
        if self._is_group:
            # 群聊图片/文件等无前缀，短ID 无法解析，原样返回
            return str(sender_id)
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

    def __str__(self):
        return "<WxMessage %s from %s: %s>" % (self.type, self.sender, self.content[:50])


class WeChat(_BaseWeChat):
    """兼容层主类：在 wechatauto.wx.WeChat 之上补齐 bot 需要的接口。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._media = MediaDownloader(self._db)

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

    def GetAllSubWindow(self):
        """返回所有会话的 Chat 实例（用于 bot 判断群聊/私聊）。"""
        subs = []
        try:
            for row in self._db.get_sessions(limit=50):
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

    # ------------------------------------------------------------ 不支持项

    def VoiceCall(self, user_id=None, **kwargs):
        wxlog.info("VoiceCall 在 wechatauto 兼容层不支持，已跳过 (user=%s)", user_id)
        return False
