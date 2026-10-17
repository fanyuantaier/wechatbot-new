# -*- coding: utf-8 -*-
"""wxbot 读库层的桩测试：不启动微信、不碰界面，专测「这条是不是我发的」。

    python test_wxbot.py

回归的起因：real_sender_id 是分片内的短编号，本机 2025-07~2026-02 自己是 4、
2026-06 之后是 2。写死 `sender_id == 2` 会把整段旧历史里的我算成对方，
风格档案于是照着对方的口吻写，再被当成这个人设发出去。
"""
import sys
import time

sys.path.insert(0, ".")
import wxbot

FAILS = []
T0 = 1750000000


def ck(name, cond, got=""):
    print("%-4s %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  <- %r" % (got,)))
    if not cond:
        FAILS.append(name)


def row(sid, ts, content="嗯", type_cn="文本", sort_seq=None):
    return dict(sender_id=sid, create_time=ts, content=content, type=type_cn,
                sort_seq=sort_seq if sort_seq is not None else ts, local_id=ts,
                sender_username="")


# 1) 判定：status==2 是主证据，表情 XML 里的 fromusername 是辅证据
votes = {"4": [43, 43], "69": [50, 0], "2": [53, 44], "94": [34, 0], "7": [4, 0]}
rows = [row(4, T0), row(69, T0 + 5), row(2, T0 + 10), row(94, T0 + 15),
        row(7, T0 + 20, "<?xml?><sysmsg/>", "系统消息"),
        row(4, T0 + 25, '<msg><emoji fromusername = "wxid_me" /></msg>', "动画表情"),
        row(94, T0 + 30, '<msg><emoji fromusername = "wxid_other" /></msg>', "动画表情")]
ids, ev = wxbot.classify_senders(rows, "wxid_me", votes)
ck("旧编号年代 status=2 的 4 判成我", "4" in ids)
ck("当前编号的 2 判成我", "2" in ids)
ck("对方 69/94 没混进来", not ({"69", "94"} & set(ids)), sorted(ids))
ck("系统消息的 id 不算我", "7" not in ids)
plain = [row(2, T0), row(4, T0 + 5), row(94, T0 + 10)]
ck("零证据时才退回 sender_id==2", wxbot.classify_senders(plain, "wxid_other", {})[0] == {"2"},
   wxbot.classify_senders(plain, "wxid_other", {})[0])
ck("只有 XML 证据也认（读不到 status 时）",
   wxbot.classify_senders([row(9, T0, '<emoji fromusername="wxid_me"/>', "动画表情")],
                          "wxid_me", {"9": [1, 0]})[0] == {"9"})
ck("名片里的 username 不算自证",
   wxbot.classify_senders([row(11, T0, '<msg username="wxid_me"/>', "42")], "wxid_me", {})[0] == set())
gids = wxbot.classify_senders([row(s, T0 + i) for i, s in enumerate([2, 4, 5, 8])],
                              "wxid_me", {"2": [9, 0], "4": [10, 10], "5": [86, 0], "8": [367, 0]})[0]
ck("群里判得出我之后，id=2 不再靠兜底冒充我", gids == {"4"}, sorted(gids))

# 2) 历史文本：说话人标签必须跟着判定走
text = wxbot.format_history_rows([row(4, T0, "我说的"), row(69, T0 + 5, "你说的")],
                                 {"wxid_peer": "小李"}.get, peer_nick="小李", self_ids={"4"})
ck("旧编号年代标成「我」", text.splitlines()[0].endswith("我：我说的"), text.splitlines()[0])
ck("单聊对方用昵称，不是串号的裸 wxid", text.splitlines()[1].endswith("小李：你说的"), text.splitlines()[1])
old = wxbot.format_history_rows([row(4, T0, "我说的"), row(69, T0 + 5, "你说的")],
                                {"wxid_peer": "小李"}.get, peer_nick="小李")
ck("不传 self_ids 时退回老口径（可回滚）", "我：" not in old, old)
grp = wxbot.format_history_rows([row(5, T0, "wxid_aaa:\n甲说的"), row(6, T0 + 5, "wxid_bbb:\n乙说的")],
                                {"wxid_aaa": "群友甲"}.get, self_ids=set())
ck("群里按正文前缀认人", grp.splitlines()[0].endswith("群友甲：甲说的"), grp.splitlines()[0])
ck("群里认不出的人留原 wxid，不编名字", grp.splitlines()[1].endswith("wxid_bbb：乙说的"), grp.splitlines()[1])

# 3) 同秒连发：get_messages 是"新的在前"，只按 create_time 稳定排序会倒着读
same = wxbot.format_history_rows([row(4, T0, "我后说", sort_seq=12), row(4, T0, "我先说", sort_seq=11)],
                                 None, self_ids={"4"})
ck("同秒内按 sort_seq 正序（不跟着入参顺序走）",
   0 <= same.index("我先说") < same.index("我后说"), same)

# 4) 合并转发：以前 _merge 从没赋值，get_messages() 永远返回 None
blob = ('<?xml version="1.0"?><msg chatrecord count="2" title="群聊的聊天记录">'
        '<record displaytype="4">'
        '<item type="0" sender="wxid_aaa" sname="甲" msg="今晚八点" asmantime="1750000000" />'
        '<item type="0" sender="wxid_bbb" sname="乙" msg="收到&amp;好的" asmantime="1750000600" />'
        '</record></msg>')
got = wxbot._parse_merge_records(blob)
ck("合并转发解析出两条", len(got) == 2, got)
ck("每条是 [发送者, 内容, 时间] 三元素", all(len(x) == 3 for x in got), got)
ck("HTML 实体还原", got[1][1] == "收到&好的", got[1])
ck("时间戳转成了可读时间", got[0][2].startswith(time.strftime("%m-%d", time.localtime(1750000000))), got[0][2])
ck("解析不出来给空列表不是 None", wxbot._parse_merge_records("<msg>没有 item</msg>") == [])

# 5) 连接必须关：不关会让缓存重建的 os.replace 变成 PermissionError(13)，
#    监听/防撤回从此每轮报错（2.2.8 线上就是这么炸的）
class _FakeConn:
    def __init__(self, rows, boom=False):
        self.rows, self.closed, self.boom = rows, False, boom

    def execute(self, sql, args=()):
        if self.boom:
            raise RuntimeError("execute 失败")
        return list(self.rows)

    def close(self):
        self.closed = True


class _FakeDB:
    def __init__(self, conns):
        self._conns = conns

    def _msg_conns(self, user, **kw):
        return self._conns


TBL = "Msg_" + "0" * 32
c1, c2 = _FakeConn([(2, 2), (4, 2), (69, 3)]), _FakeConn([(94, 0)])
v = wxbot.status_votes(_FakeDB([(c1, TBL), (c2, TBL)]), "u")
ck("status_votes 统计正确", v == {"2": [1, 1], "4": [1, 1], "69": [1, 0], "94": [1, 0]}, v)
ck("status_votes 用完关闭全部分片连接", c1.closed and c2.closed, (c1.closed, c2.closed))
c3 = _FakeConn([])
wxbot.status_votes(_FakeDB([(c3, "不是表名")]), "u")
ck("表名不合规时也要关连接", c3.closed)
c4 = _FakeConn([], boom=True)
wxbot.status_votes(_FakeDB([(c4, TBL)]), "u")
ck("查询抛错时也要关连接", c4.closed)

print("\n%s" % ("失败 %d 项: %s" % (len(FAILS), FAILS) if FAILS else "全部通过"))
sys.exit(1 if FAILS else 0)
