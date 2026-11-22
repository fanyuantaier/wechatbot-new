"""Virtual Life 记忆管理路由：给 WeChatBot WebUI 加记忆专属功能页。

接入方式：config_editor.py 末尾 `from vl_memory_routes import register_memory_routes; register_memory_routes(app)`
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import jsonify, render_template, request, session

import vl_memory_bridge as bridge

_BRIDGE_DATA = Path(__file__).resolve().parent / "data" / "memory_bridge"


def _login_guard(f):
    """沿用 config_editor 的登录态（session['logged_in']）。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import session as _s
        # 登录保护判断交给 config_editor 的全局登录流程（若开启）；此处不 import config——
        # vl_memory_bridge 已把 virtual-life 插进 sys.path，那里的 config.py 没有这个键。
        # （若未来要开保护：把 ENABLE_LOGIN_PASSWORD 判断放进 config_editor 的全局 before_request）
        return f(*args, **kwargs)
    return wrapper


def _list_users() -> list[dict]:
    """扫 bridge 数据目录列出所有记忆库用户。"""
    users = []
    if not _BRIDGE_DATA.exists():
        return users
    for db in sorted(_BRIDGE_DATA.glob("*.db")):
        try:
            con = sqlite3.connect(str(db))
            total = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            kinds = dict(con.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
            key3 = con.execute("SELECT COUNT(*) FROM nodes WHERE mem_key >= 3").fetchone()[0]
            last = con.execute("SELECT MAX(ts) FROM nodes").fetchone()[0]
            con.close()
            users.append({
                "user": db.stem.replace("_", " ") if db.stem.count("_") <= 2 else db.stem,
                "db": db.name,
                "total": total,
                "kinds": kinds,
                "key3": key3,
                "last": datetime.fromtimestamp(last).strftime("%m-%d %H:%M") if last else "-",
            })
        except Exception:
            continue
    return users


def _search_user(db_name: str, query: str, top_k: int = 8) -> list[dict]:
    """在指定用户库里检索。"""
    user = db_name.replace(".db", "").replace("_", " ")
    return bridge.recall_scored(user, query, top_k=top_k)


def register_memory_routes(app):
    @app.route('/vl_memory')
    @_login_guard
    def vl_memory_page():
        users = _list_users()
        return render_template('vl_memory.html', users=users)

    @app.route('/vl_memory/api/search', methods=['POST'])
    @_login_guard
    def vl_memory_search():
        data = request.get_json(force=True)
        db_name = data.get("db", "")
        query = (data.get("query") or "").strip()
        if not db_name or not query:
            return jsonify({"error": "参数缺失"}), 400
        if "/" in db_name or "\\" in db_name or ".." in db_name:
            return jsonify({"error": "非法库名"}), 400
        hits = _search_user(db_name, query, top_k=int(data.get("top_k", 8)))
        return jsonify({"hits": hits})

    @app.route('/vl_memory/api/list', methods=['GET'])
    @_login_guard
    def vl_memory_list():
        return jsonify({"users": _list_users()})

    @app.route('/vl_memory/api/add', methods=['POST'])
    @_login_guard
    def vl_memory_add():
        """上帝之手：手工给某用户写入记忆（key3 终身留痕）。"""
        data = request.get_json(force=True)
        db_name = data.get("db", "")
        text = (data.get("text") or "").strip()
        importance = float(data.get("importance", 8))
        if not db_name or not text:
            return jsonify({"error": "参数缺失"}), 400
        user = db_name.replace(".db", "").replace("_", " ")
        bridge.remember(user, text, kind="thought", importance=importance, key=3)
        return jsonify({"ok": True, "note": f"已写入 key3 终身记忆（重要度 {importance}）"})

    @app.route('/vl_memory/api/delete', methods=['POST'])
    @_login_guard
    def vl_memory_delete():
        """按 id 删除一条记忆。"""
        data = request.get_json(force=True)
        db_name = data.get("db", "")
        node_id = int(data.get("id", 0))
        if not db_name or not node_id:
            return jsonify({"error": "参数缺失"}), 400
        if "/" in db_name or "\\" in db_name or ".." in db_name:
            return jsonify({"error": "非法库名"}), 400
        con = sqlite3.connect(str(_BRIDGE_DATA / db_name))
        con.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        con.commit()
        con.close()
        return jsonify({"ok": True})

    @app.route('/vl_memory/api/all', methods=['GET'])
    @_login_guard
    def vl_memory_all():
        """列出某用户全部记忆（管理视图用）。"""
        db_name = request.args.get("db", "")
        if "/" in db_name or "\\" in db_name or ".." in db_name:
            return jsonify({"error": "非法库名"}), 400
        path = _BRIDGE_DATA / db_name
        if not path.exists():
            return jsonify({"error": "库不存在"}), 404
        con = sqlite3.connect(str(path))
        rows = con.execute(
            "SELECT id, kind, text, importance, mem_key, access_count FROM nodes ORDER BY ts DESC LIMIT 200"
        ).fetchall()
        con.close()
        return jsonify({"items": [
            {"id": r[0], "kind": r[1], "text": r[2],
             "importance": r[3], "key": r[4], "access": r[5]} for r in rows]})
