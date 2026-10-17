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

# 微信自己的资源域名：卡片 XML 里到处是这种 stodownload / 头像 / 客服链接，
# 它们是二进制资源的下载地址，**不是**网页链接。以前正文里只要出现这种串就被
# 当成「链接」送去抓取，结果必然是「非 HTML / 提取不到文本」。实测 5307 行里
# 有 478 次命中的是 vweixinf.tc.qq.com、184 次是 wxapp.tc.qq.com。
_ASSET_HOSTS = (
    "vweixinf.tc.qq.com", "wxapp.tc.qq.com", "wxwinstore.getweapp.com",
    "wctcn.bd.qq.com", "store.icf.mmweb.qq.com", "c.weixin.com",
    "wx.qlogo.cn", "mmbiz.qpic.cn", "mmbiz.qlogo.cn",
    "support.weixin.qq.com", "help.wechat.com", "open.weixin.qq.com",
    "wx.tenpay.com", "url.tenpay.com", "tenpay.com", "wxapp.tenpay.com",
    "dldir1.qq.com", "dldir1v6.qq.com",
)


def is_wechat_asset_url(url):
    """True = 这是微信客户端的资源地址，不该当网页链接抓。"""
    if not url:
        return False
    low = str(url).strip().lower()
    if not low.startswith(("http://", "https://")):
        return False
    host = re.sub(r"^https?://", "", low).split("/")[0]
    if any(host == h or host.endswith("." + h.lstrip(".")) for h in _ASSET_HOSTS if h):
        return True
    # 剩下的按路径特征兜一层：这些都是下载端点或错误占位页
    return any(p in low for p in ("/stodownload", "encfilekey=",
                                  "checkresupdate", "/mp/waerrpage"))


def _first_http_url(text):
    """从 XML 里取第一个**像网页**的 http(s) 链接，资源地址一律不要。"""
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0)
        if not is_wechat_asset_url(u):
            return u
    return ""


def _tag_val(text, *names):
    """取 <name>…</name> 或 <name xxx="…" /> 里的文本；CDATA 剥掉。取不到返回 ''。"""
    for name in names:
        m = re.search(r"<%s>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</%s>" % (name, name),
                      text or "", re.S)
        if m:
            v = _strip_tags(m.group(1))
            if v:
                return v
        # 属性形式：<location label="xx" /> / <name title="xx">
        for attr in ("label", "title", "poiname", "desc", "showmsg", "content", "name"):
            m = re.search(r"<%s\b[^>]*\b%s=\"([^\"]+)\"" % (name, attr), text or "")
            if m:
                v = _strip_tags(m.group(1))
                if v:
                    return v
        m = re.search(r"<%s\b[^/>]*>(.*?)" % name, text or "", re.S)
        if m:
            v = _strip_tags(re.sub(r"<[^>]+>", "", m.group(1)))
            if v:
                return v
    return ""


def _looks_like_xml(text):
    t = (text or "").lstrip()
    return t.startswith("<?xml") or (t.startswith("<") and (">" in t[:200] or "/>" in t[:200]))


def _split_sender_prefix(text):
    """群消息正文常是「发送者:\\n真身」。前缀不一定是 wxid_ 或纯数字，也可能是别名。

    返回 (前缀或None, 剩下的部分)。只有当剩下的部分明显是 XML 卡面时才剥，
    免得把「备注: 我今天很忙」这种正常文本也剁一截。
    """
    if not text:
        return None, text
    m = re.match(r"^[^\n:]{1,40}:\n", text)
    if m and _looks_like_xml(text[m.end():].lstrip()):
        return m.group(0).rstrip(":\n"), text[m.end():]
    return None, text


_MERGE_ITEM_RE = re.compile(r"<item\b([^>]*?)(?:/>|>(.*?)</item>)", re.S)
_MERGE_ATTR_RE = re.compile(r'([\w:]+)\s*=\s*"([^"]*)"')
_MERGE_SENDER_KEYS = ("sname", "sendernickname", "sendername", "sender")
_MERGE_TEXT_KEYS = ("msg", "msgdata", "content", "title", "digest")
_MERGE_TIME_KEYS = ("asmantime", "time", "timestamp", "createtime")
_MERGE_ENTITIES = (("&quot;", '"'), ("&apos;", "'"), ("&lt;", "<"),
                   ("&gt;", ">"), ("&#x0a;", "\n"), ("&#10;", "\n"), ("&amp;", "&"))


def _parse_merge_records(blob):
    """合并转发（``<record>`` 里的 ``<item>``）拆成 ``[[发送者, 内容, 时间], ...]``。

    bot 侧按三元素列表消费（``bot.py`` 的 ``msgtype == 'merge'`` 分支）。各版本属性名
    不一致，所以每个字段给一串候选键；整条解析不出来返回 ``[]``。以前 ``_merge``
    从没被赋过值，``get_messages()`` 永远返回 None —— 合并转发的内容对模型就是空的。
    """
    out = []
    for m in _MERGE_ITEM_RE.finditer(blob or ""):
        attrs = {k.lower(): v for k, v in _MERGE_ATTR_RE.findall(m.group(1) or "")}
        inner = m.group(2) or ""
        sender = next((attrs[k] for k in _MERGE_SENDER_KEYS if attrs.get(k)), "")
        text = next((attrs[k] for k in _MERGE_TEXT_KEYS if attrs.get(k)), "")
        text = text or _tag_val(inner, "title", "msg", "content", "desc")
        for a, b in _MERGE_ENTITIES:
            text = text.replace(a, b)
            sender = sender.replace(a, b)
        ts = next((attrs[k] for k in _MERGE_TIME_KEYS if attrs.get(k)), "")
        stamp = time.strftime("%m-%d %H:%M", time.localtime(int(ts))) if ts.isdigit() else ""
        text = _strip_tags(text or "").strip()
        if text:
            out.append([sender or "未知", text, stamp])
    return out


def _fold_xml_content(text, type_cn):
    """把消息正文里的整坨 XML 折成一行人类可读的话。

    兼容层的 content 会直接喂给模型、并被 bot 的链接正则扫一遍，所以这里
    返回 XML 原文等于同时污染提示词和制造「莫名识别到链接」。非 XML 原样返回。
    """
    if not text or "<" not in text:
        return text
    # 「发送者:\n<?xml…」这种形状：前缀不是 wxid_/纯数字时 _clean_content 那步剥不掉，
    # 于是 XML 整坨留在正文里（实测合并转发卡片就是这么漏网的）。
    _p, rest = _split_sender_prefix(text)
    text = rest
    if not _looks_like_xml(text):
        head = text[:300]
        if not (head.lstrip().startswith("<?xml") or "<appmsg" in head or "<emoji" in head
                or "<msg" in head):
            return text
    if type_cn == "动画表情":
        return "[动画表情]"
    if type_cn == "图片":
        return ""          # 图片正文本来就没人看，交给识图流程
    if type_cn == "视频":
        return "[视频]"
    if type_cn == "语音":
        return ""          # 语音走 voice_note() 说明可用性
    if type_cn == "位置":
        place = _tag_val(text, "location", "label", "poiname", "title")
        return ("[位置] " + place).strip()
    if type_cn == "红包":
        return "[红包] " + (_tag_val(text, "title", "showmsg") or "恭喜发财")
    if type_cn == "音视频通话":
        return "[语音/视频通话] " + _tag_val(text, "content", "title")
    if type_cn == "系统消息":
        plain = _strip_tags(text)
        return plain or "[系统消息]"
    # 文件/链接/卡片：按卡面类型分别折
    if "<refermsg" in text:
        return "[引用消息] " + (_tag_val(text, "title", "content") or "")
    if "<record" in text:
        return "[合并转发的聊天记录]"
    if "<findernamecard" in text or "<finder" in text:
        return "[视频号视频] " + _tag_val(text, "title", "desc")
    if "<wefilename" in text or "<appmsg" in text and "<cdnattachurl" in text:
        return "[文件] " + _tag_val(text, "wefilename", "title")
    title = _tag_val(text, "title")
    if title:
        # 拍一拍、公众号文章分享、小程序卡片等：只留标题，链接另由 _classify 判
        return "[卡片] " + title
    return "[卡片消息]"


# wechatauto 4.x 的消息正文列可能是 zstd 帧（首字节 28 B5 2F FD），
# get_messages 的摘要列已经解过，但 get_message_row 的原始列没有 —— 不解就
# 永远抽不到 URL，「链接/引用/合并转发」这套判据等于死代码（实测 336/336 是帧）。
def _decode_cell(value):
    if isinstance(value, (bytes, bytearray)):
        head = bytes(value[:4])
        if head == b"\x28\xb5\x2f\xfd":
            try:
                from wechatauto.db import _get_zstd_module, _zstd_decompress
                zstd = _get_zstd_module()
                if zstd is not None:
                    out = _zstd_decompress(zstd, bytes(value))
                    if out:
                        return out
            except Exception as e:  # 换版本/缺库时退回原值，别把整条消息判死
                log.debug("zstd 解压失败: %s" % e)
        return _to_text(value)
    return value


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


def read_history_text(who, limit=30, max_chars=4000, db=None):
    """纯读库版聊天记录（不启动 GUI/UIA），配置编辑器用这个。

    和 :meth:`WeChat.GetHistoryText` 同一套格式化逻辑，只是不依赖界面，
    每次自己开一个 :class:`WeChatDB`（传 ``db`` 可复用已有实例）。

    Returns:
        (username, text)：解析不到会话是 (None, "")；读库失败时 username
        有值、text 为空串，调用方据此区分「没这个人」和「读不到」。
    """
    from wechatauto.db import WeChatDB

    if db is None:
        try:
            db = WeChatDB()
        except Exception as e:
            wxlog.warning("打开微信数据库失败: %s" % e)
            return None, ""
    text_db = db
    uname = None
    name = (who or "").strip()
    if not name:
        # 空名字绝不能往下走：search_contact("") 会命中昵称为空的
        # notifymessage 会话，读出来是「有 username 但没内容」的假成功。
        return None, ""
    if name.endswith("@chatroom") or name.startswith(("wxid_", "gh_")):
        uname = name
    elif name in ("filehelper", "文件传输助手"):
        uname = "filehelper"
    else:
        for _ in range(5):
            try:
                for hit in text_db.search_contact(name):
                    if name in (hit.get("nick_name"), hit.get("remark")):
                        uname = hit["username"]
                        break
                break
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                log.warning("数据库暂不可用(解析会话): %s", e)
                time.sleep(1.5)
        if uname is None:
            # 群不在 search_contact 的覆盖范围里（实测 5/5 个群按群名读不到，
            # 按 xxx@chatroom 才读到），拿 nickname_map 反查一次。
            try:
                for u, n in (text_db.nickname_map() or {}).items():
                    if n == name:
                        uname = u
                        break
            except Exception as e:
                log.warning("按昵称反查会话失败: %s" % e)
        if uname is None:
            # 也可能直接传了个 username 进来
            uname = name
    if not uname:
        return None, ""

    def nick_of(wxid):
        try:
            return text_db.nickname_map().get(wxid, "") or ""
        except Exception:
            return ""

    try:
        rows = text_db.get_messages(uname, limit=max(1, _as_int(limit, 30)))
    except Exception as e:
        wxlog.warning("读取聊天记录失败 (%s): %s" % (who, e))
        return uname, ""
    is_group = uname.endswith("@chatroom")
    # 群里的"对方"不是一个人：正文里没有 wxid 前缀的那几条（图片/表情/语音）
    # 只能标成一个不带名字的群成员，别拿串号的名字冒充，也别写成"对方"骗模型是一对一。
    peer_nick = "群成员" if is_group else (nick_of(uname) or uname)
    return uname, format_history_rows(rows, nick_of, peer_nick=peer_nick,
                                       max_chars=_as_int(max_chars, 0),
                                       self_ids=resolve_self_ids(text_db, uname, rows))


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_XML_SELF_RE = re.compile(r'fromusername\s*=\s*["\']?\s*([A-Za-z0-9_\-@]+)')
_MSG_TABLE_RE = re.compile(r'^Msg_[0-9a-f]{32}$')
_SENDER_PREFIX_RE = re.compile(r"^(wxid_[^\s:\n]+|gh_[^\s:\n]+|\d{6,}):\n")


def status_votes(db, username, since=0, until=0, cap=0):
    """``{sender_id: [条数, 其中 status==2 的条数]}``。

    ``status`` 不在 ``get_messages()`` 的返回里，只能自己开分片读；读不到就回空表，
    调用方退到「只看 XML」这一条证据上。

    窗口参数是给热路径留的：历史格式化只查被格式化的那批消息的时间跨度
    （``since``/``until``），实时判定只看这个会话最近的 ``cap`` 条 ——
    一个几万条的群全表扫一遍是不能放在收消息的循环里的。
    """
    out = {}
    try:
        conns = db._msg_conns(username)
    except Exception as e:
        wxlog.warning("读 status 失败（只用 XML 证据判定「我」）: %s" % e)
        return {}
    try:
        for conn, table in conns or []:
            if not _MSG_TABLE_RE.match(str(table)):      # 表名进 SQL 前先卡死格式
                continue
            sql = 'SELECT real_sender_id, status FROM "%s"' % table
            args = []
            if since and until:
                sql += " WHERE create_time BETWEEN ? AND ?"
                args += [int(since), int(until)]
            if cap:
                sql += " ORDER BY sort_seq DESC LIMIT ?"
                args.append(int(cap))
            try:
                for sid, st in conn.execute(sql, args):
                    v = out.setdefault(str(sid), [0, 0])
                    v[0] += 1
                    if st == 2:
                        v[1] += 1
            except Exception as e:
                wxlog.warning("分片 %s 读 status 失败: %s" % (table, e))
    finally:
        # _msg_conns 的 docstring 写着「调用方负责 close 连接」——不关的话，
        # Windows 上这几个句柄会让缓存重建的 os.replace 一直失败（PermissionError 13），
        # 监听轮询和防撤回扫描从此每轮报错、也再收不到新消息。2.2.8 就是这么炸的。
        for conn, _table in conns or []:
            try:
                conn.close()
            except Exception:
                pass
    return out


def classify_senders(rows, own_wxid, votes):
    """这个会话里哪些 ``sender_id`` 是「我」，返回 ``(self_ids, 证据列表)``。

    ``real_sender_id`` 是**分片内**的短编号，同一个人换个分片就换个号：本机实测
    2025-07~2026-02 自己是 4、2026-06 之后是 2，所以 ``== 2`` 会把整段旧历史里的
    我算成对方（风格档案于是描述的是对方的口吻）。只认两条正向证据：
    ① ``status == 2``（微信给自己发的消息打的标，跨分片稳）；
    ② 表情/图片 XML 里的 ``fromusername`` == 本机 wxid。
    整场都没有正向证据才退回 ``== 2``；只要判得出「我」，剩下的 id 一律算对方
    —— 群里十几个成员编号，不该有一个靠 ``== 2`` 混进来。
    """
    win, xml = {}, {}
    for r in rows or []:
        sid = str(r.get("sender_id"))
        win[sid] = win.get(sid, 0) + 1
        m = _XML_SELF_RE.search(_to_text(r.get("content")))
        if m and own_wxid and m.group(1) == own_wxid:
            xml[sid] = xml.get(sid, 0) + 1
    self_ids, ev = set(), []

    def positive(sid):
        n, st2 = votes.get(sid, [0, 0])
        return st2 >= max(1, int(0.3 * n)) or bool(xml.get(sid))

    decided = any(positive(s) for s in set(list(win) + list(votes)))
    for sid in sorted(set(list(win) + list(votes))):
        n, st2 = votes.get(sid, [0, 0])
        x = xml.get(sid, 0)
        if st2 >= max(1, int(0.3 * n)):
            is_self, how = True, "status=2 占 %d/%d" % (st2, n)
        elif x:
            is_self, how = True, "表情 XML 里 fromusername 是本机号，%d 条" % x
        elif not decided and sid == "2":
            is_self, how = True, "整场都没有正向证据，退回 sender_id==2"
        else:
            is_self, how = False, "无正向证据（status=2 只有 %d/%d）" % (st2, n)
        if is_self:
            self_ids.add(sid)
        ev.append((sid, win.get(sid, 0), is_self, how))
    return self_ids, ev


def resolve_self_ids(db, username, rows=None, cap=0):
    """历史/实时两条路共用的入口：拿本机 wxid + status 证据，判出「我」的编号集合。"""
    try:
        own = (getattr(db, "wxid", "") or "").strip()
    except Exception:
        own = ""
    since = until = 0
    if rows:
        ts = [_as_int(r.get("create_time")) for r in rows if _as_int(r.get("create_time"))]
        if ts:
            since, until = min(ts), max(ts)
    try:
        votes = status_votes(db, username, since=since, until=until, cap=cap)
    except Exception as e:
        wxlog.warning("判定「我」的 sender_id 失败（退回 sender_id==2）: %s" % e)
        votes = {}
    ids, _ev = classify_senders(rows or [], own, votes)
    return ids


def format_history_rows(rows, nick_of=None, self_nick="我", peer_nick="",
                        max_chars=0, self_ids=None):
    """把 ``db.get_messages()`` 的消息行转成可读文本，用于喂给模型。

    每行 ``[月-日 时:分] 名字：内容``。行序按 ``sort_seq``（同值时按 ``local_id``）
    **升序**排好 —— ``WeChatDB.get_messages()`` 返回的是「最近 N 条、新的在前」，
    直接顺着读会变成倒着说话。名字的取法：自己发的用 ``self_nick``，
    群里其它人优先用真实 wxid 换备注/昵称（wechatauto 1.2.4.1 的
    ``sender_username``），私聊用 ``peer_nick``。非文本消息只写类型
    （``[图片]`` 等），系统/撤回消息丢掉——它们对「模仿说话风格」没用，
    还会把微信自己的文案带进上下文。

    Args:
        rows: ``WeChatDB.get_messages()`` 返回的行。
        nick_of: ``wxid -> 备注/昵称`` 的函数，缺省就不换名。
        self_nick: 账号主人这一方显示成什么，默认「我」。
        peer_nick: 私聊对方的名字；群聊里用不到（按每条消息的发送者取名）。
        max_chars: >0 时从**头部**截断（保留最近的对话）。
    """
    ordered = sorted(rows or [], key=lambda r: (_as_int(r.get("sort_seq")),
                                                _as_int(r.get("local_id"))))
    self_ids = self_ids if self_ids else {"2"}
    lines = []
    for row in ordered:
        type_cn = row.get("type") or ""
        if type_cn in ("系统消息", "撤回消息"):
            continue
        content = _to_text(row.get("content")).strip()
        m = _SENDER_PREFIX_RE.match(content)
        if type_cn and type_cn != "文本":
            # 语音/图片/表情这些没有可直接模仿的文字，只留类型标记
            content = "[%s]" % type_cn
        else:
            content = (content[m.end():] if m else content).strip()
        if not content:
            continue
        sender_id = row.get("sender_id")
        if str(sender_id) in self_ids:
            who = self_nick
        elif m:
            # 群里：正文前缀里的 wxid 才是发送者。sender_username 拿的是
            # message_resource 的全局 rowid，跨分片会串号，不能用来认人。
            who = (nick_of(m.group(1)) if nick_of else "") or m.group(1)
        else:
            who = peer_nick or "对方"
        ts = _as_int(row.get("create_time"))
        stamp = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "时间未知"
        lines.append("[%s] %s：%s" % (stamp, who, content))
    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        text = text[-max_chars:]
    return text


class WxMessage:
    """bot 兼容消息对象（对齐 wxautox4_wechatbot 的消息接口）"""

    def __init__(self, row, chat, db, media, self_wxid, self_ids=None):
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
        # self_ids 由调用方按 status/XML 证据判好传进来（一个会话算一次，见
        # WeChat._make_listen_cb）。real_sender_id 是分片内的短编号，写死 ==2
        # 在换过分片编号的机器上会把"我"当成"对方"，于是自己回复自己。
        is_self = str(sender_id) in (self_ids or {"2"})
        self.attr = "self" if is_self else "friend"

        content = _to_text(row.get("content"))
        prefix = self._extract_prefix_sender(content)
        self.sender_wxid = self._resolve_sender_wxid(row, prefix)
        self.sender = self._resolve_sender(sender_id, prefix)
        self.content = self._clean_content(content, prefix, type_cn)

        self.quote_content = None
        self._link_url = None
        self._merge = None
        self._file_path = None
        self._file_name = None
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
                    full = (
                        self._db.get_message_row(self._chat._wxid, self.local_id) or {}
                    )
                    # 原始列可能是 zstd 帧，不解的话判据永远拿到空串
                    self._cached_full = {
                        k: _decode_cell(v) for k, v in full.items()
                    }
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
            return name or ("群成员%s" % sender_id if str(sender_id).isdigit() else str(sender_id))
        # 私聊：对方就是聊天窗口本身
        try:
            return self._chat.who or "对方"
        except Exception:
            return "对方"

    @staticmethod
    def _clean_content(content, prefix, type_cn=""):
        if prefix:
            content = re.sub(r"^" + re.escape(prefix) + r":\n", "", content)
        content = content.replace("[文本]", "").strip()
        return _fold_xml_content(content, type_cn)

    def _classify(self):
        if self._type_cn == "文件/链接/卡片":
            full = self._full_row()
            raw = _to_text(full.get("content"))
            packed = _to_text(full.get("packed_info"))
            summary = _to_text(self._row.get("content"))
            # 摘要列(get_messages)通常是解开的 XML，原始列解压后字段更全；
            # 两边都看一眼，取信息多的那份。
            blob = "\n".join(t for t in (raw, packed, summary) if t)
            title = _tag_val(blob, "title")

            if "<refermsg" in blob:
                self.type = "quote"
                self.quote_content = (
                    _tag_val(blob, "content") or title or self.content or "[引用消息]"
                )
                return
            if "<record" in blob:
                self.type = "merge"
                self._merge = _parse_merge_records(blob)
                return

            # 链接卡片：只认卡面 <url> 里的网页地址。以前是「blob 里有 http 就算链接」，
            # 于是视频号/表情卡片的 stodownload 资源地址被当成网页链接送去抓取。
            url = _first_http_url(_tag_val(blob, "url")) or _first_http_url(_tag_val(blob, "linkurl"))
            if not url and "<findernamecard" not in blob and "<wefilename" not in blob:
                # 公众号文章一类会把链接直接写在正文里，过滤掉资源域名后仍可接受
                url = _first_http_url(_strip_tags(blob))
            if url:
                self.type = "link"
                self._link_url = url
                return

            if "<wefilename" in blob or "<md5" in blob and "<appmsg" not in blob:
                self.type = "file"
                self._file_name = _tag_val(blob, "wefilename", "title")
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
        return self._merge or []

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
        # 一个会话只判一次（订阅时），不放在每条消息的回调里。cap=400：只看这个
        # 会话最近的几百条，几万条的群不做全表扫。
        wxid = str(getattr(chat, "_wxid", "") or "")
        self_ids = resolve_self_ids(self._db, wxid, cap=400) if wxid else set()
        if wxid:
            wxlog.info("会话 %s 的「我」= sender_id %s"
                       % (wxid, "、".join(sorted(self_ids)) or "（未判出，按 2 兜底）"))

        def _wrapper(row, listener):
            try:
                msg = WxMessage(row, chat, self._db, self._media, self_wxid, self_ids)
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

    # ------------------------------------------------------------- 聊天记录

    def ResolveSession(self, nickname):
        """昵称/备注/username -> 会话 username；找不到返回 None。纯读库。"""
        return self._as_session_username(nickname or "")

    def GetHistoryText(self, who, limit=30, max_chars=4000):
        """读某个会话最近的聊天记录并转成文本（纯读库，不驱动界面）。

        Args:
            who: 昵称、备注或 username。
            limit: 读最近多少条消息（非文本只留类型标记）。
            max_chars: 文本上限，超出从头部截断（保留最近的）。

        Returns:
            (username, text)：解析不到会话时是 (None, "")；读库失败时
            username 有值、text 为空串，调用方据此区分「没这个人」和「读不到」。
        """
        return read_history_text(who, limit=limit, max_chars=max_chars, db=self._db)

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
