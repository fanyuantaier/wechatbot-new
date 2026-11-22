"""virtual-life 记忆引擎桥接：给 wechatbot-new 提供检索式记忆与遗忘曲线。

复用 virtual-life 的 store.py（向量+BM25+RRF）和 forgetting.py（key0-3 分级），
按用户建独立记忆库（每用户一个 .db），bot.py 三行接入。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

VL_ROOT = Path(r"D:\.zcode\workspace\draft-f3e4a1ee-5b90-4231-8256-94a1d1b43a52\virtual-life")
sys.path.insert(0, str(VL_ROOT))
sys.path.insert(0, str(VL_ROOT / "memory"))
# 注意：绝不 os.chdir(VL_ROOT)——宿主 bot.py 的相对路径（Memory_Temp 等）依赖原 cwd。
# store.py 的 db_path 由下方 get_store 显式传绝对路径，不依赖工作目录。
# embedding 端点走 config_local.json（store.py 内部按其自身 BASE_DIR 解析，也不受 cwd 影响）。

from store import MemoryStore           # noqa: E402

_DATA = Path(__file__).resolve().parent / "data" / "memory_bridge"
_STORES: dict[str, MemoryStore] = {}


def get_store(user_id: str) -> MemoryStore:
    """每个用户一个独立记忆库。"""
    key = "".join(c if c.isalnum() else "_" for c in user_id)[:30]
    if key not in _STORES:
        _DATA.mkdir(parents=True, exist_ok=True)
        _STORES[key] = MemoryStore(db_path=_DATA / f"{key}.db")
    return _STORES[key]


def remember(user_id: str, text: str, kind: str = "chat",
             importance: float = 4.0, key: int = 1) -> None:
    """记一条消息/事件。key: 0 琐事 1 普通 2 重要 3 终身留痕。失败静默（不影响聊天主流程）。"""
    try:
        get_store(user_id).add(kind, text, importance=importance, key=key)
    except Exception:
        pass


def recall_scored(user_id: str, query: str, top_k: int = 5) -> list[dict]:
    """检索相关记忆（向量+BM25+RRF + 遗忘曲线加权 + 模糊化），带保留度。"""
    try:
        hits = get_store(user_id).retrieve(query, top_k=top_k)
        return [{"text": n["text"], "kind": n["kind"],
                 "retention": round(n.get("retention", 1.0), 2),
                 "score": round(s, 4)} for n, s in hits]
    except Exception:
        return []


def render_memories_block(user_id: str, query: str, top_k: int = 5) -> str:
    """渲染成 wechatbot-new 的记忆片段格式——替换它的全量 50 条塞 prompt。"""
    hits = recall_scored(user_id, query, top_k)
    if not hits:
        return ""
    lines = []
    for h in hits:
        blur = "（有点模糊）" if h["retention"] < 0.5 else ""
        lines.append(f"## 记忆片段 [{datetime.now():%Y-%m-%d}]\n"
                     f"**保留度**: {h['retention']}\n"
                     f"**摘要**: {blur}{h['text']}\n\n")
    return "".join(lines)
