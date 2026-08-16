"""LFC News MCP Server — پل کنترل‌شده بین Hermes و News Bot (مرحله ۱۱).

Hermes هرگز مستقیم به DB دسترسی ندارد؛ فقط از طریق این ابزارهای مجاز:

    get_news | get_news_by_id | search_similar_news | get_recent_published_news
    get_channel_examples | get_source_health | get_source_history
    save_ai_analysis | save_verification | save_translation_review

پیاده‌سازی: MCP stdio (JSON-RPC 2.0، هر پیام یک خط) — بدون وابستگی خارجی.
اجرا (برای Hermes):
    hermes mcp add lfc-news -- cmd /c "python lfc_mcp_server.py"
یا مستقیم:  python lfc_mcp_server.py
"""
from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "lfc-news", "version": "1.0.0"}


# ------------------------------------------------------------------ tools
def _json_dumps(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def _get_db():
    import db
    db.init()
    return db


def _tool_get_news(params):
    """آخرین خبرها با فیلتر status — خروجی: [{key, source, title, status, created_at, analysis}]."""
    db = _get_db()
    status = (params.get("status") or "").strip()
    limit = min(int(params.get("limit") or 20), 100)
    sql = "SELECT key, source, title, status, created_at, analysis, verification FROM items"
    args = []
    if status:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = db._c().execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("analysis", "verification"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else None
            except Exception:
                d[k] = None
        out.append(d)
    return out


def _tool_get_news_by_id(params):
    db = _get_db()
    row = db.get(params.get("key") or "")
    if not row:
        return None
    payload = row["payload"]
    out = dict(row)
    out["payload"] = payload
    return out


def _tool_search_similar(params):
    db = _get_db()
    title = params.get("title") or ""
    hours = int(params.get("hours") or 48)
    if not title:
        return []
    items = db._c().execute(
        "SELECT key, source, title, status, created_at FROM items WHERE created_at > ?",
        (__import__("time").time() - hours * 3600,),
    ).fetchall()
    norm = db.normalize_title(title)
    if not norm:
        return []
    from rapidfuzz import fuzz
    out = []
    for r in items:
        if not r["title"]:
            continue
        if fuzz.token_set_ratio(norm, db.normalize_title(r["title"])) >= \
                getattr(__import__("config"), "DUPLICATE_THRESHOLD", 85):
            out.append(dict(r))
    return out


def _tool_recent_published(params):
    db = _get_db()
    limit = min(int(params.get("limit") or 20), 100)
    rows = db._c().execute(
        "SELECT key, source, title, status, created_at FROM items "
        "WHERE status IN ('approved','published') ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _tool_channel_examples(params):
    """نمونه پست‌های تأییدشده کانال (فقط برای استایل ترجمه)."""
    db = _get_db()
    limit = min(int(params.get("limit") or 5), 10)
    return [
        {"title": (p.get("translated") or {}).get("title"),
         "body": (p.get("translated") or {}).get("body"),
         "source": p.get("source_tag")}
        for p in db.channel_examples(limit)
    ]


def _tool_source_health(params):
    db = _get_db()
    rows = db.list_source_health()
    return rows


def _tool_source_history(params):
    db = _get_db()
    sid = (params.get("source_id") or "").strip()
    if not sid:
        return []
    rows = db._c().execute(
        "SELECT key, title, status, created_at FROM items WHERE source=? "
        "ORDER BY created_at DESC LIMIT 30",
        (sid,),
    ).fetchall()
    return [dict(r) for r in rows]


def _tool_save_analysis(params):
    db = _get_db()
    key = params.get("key") or ""
    analysis = params.get("analysis")
    if not key or not isinstance(analysis, dict):
        return {"ok": False, "error": "key and analysis object required"}
    if not db.get(key):
        return {"ok": False, "error": "news not found"}
    db.record_analysis(key, analysis)
    return {"ok": True}


def _tool_save_verification(params):
    db = _get_db()
    key = params.get("key") or ""
    verification = params.get("verification")
    if not key or not isinstance(verification, dict):
        return {"ok": False, "error": "key and verification object required"}
    if not db.get(key):
        return {"ok": False, "error": "news not found"}
    db.record_verification(key, verification)
    return {"ok": True}


def _tool_save_translation_review(params):
    db = _get_db()
    key = params.get("key") or ""
    if not key:
        return {"ok": False, "error": "key required"}
    try:
        db.record_feedback(
            key, ai_decision=None, human_action="ai_review",
            reason=json.dumps(params.get("review") or {}),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOLS = {
    "get_news": {
        "description": "List recent news items, optionally filtered by status "
                       "(e.g. pending_admin, rejected, published).",
        "schema": {"type": "object", "properties": {
            "status": {"type": "string"}, "limit": {"type": "integer"}}},
        "fn": _tool_get_news,
    },
    "get_news_by_id": {
        "description": "Get one news item by its key (full payload incl. "
                       "translation and media).",
        "schema": {"type": "object", "properties": {
            "key": {"type": "string"}}, "required": ["key"]},
        "fn": _tool_get_news_by_id,
    },
    "search_similar_news": {
        "description": "Find news with similar headlines in a time window "
                       "(duplicate / cross-source check).",
        "schema": {"type": "object", "properties": {
            "title": {"type": "string"}, "hours": {"type": "integer"}},
            "required": ["title"]},
        "fn": _tool_search_similar,
    },
    "get_recent_published_news": {
        "description": "Recently approved/published channel posts.",
        "schema": {"type": "object", "properties": {
            "limit": {"type": "integer"}}},
        "fn": _tool_recent_published,
    },
    "get_channel_examples": {
        "description": "Approved channel posts as Persian style examples for "
                       "translation matching.",
        "schema": {"type": "object", "properties": {
            "limit": {"type": "integer"}}},
        "fn": _tool_channel_examples,
    },
    "get_source_health": {
        "description": "Per-source health status (healthy/degraded/failed, "
                       "consecutive failures, latency).",
        "schema": {"type": "object", "properties": {}},
        "fn": _tool_source_health,
    },
    "get_source_history": {
        "description": "Recent items reported by a specific source.",
        "schema": {"type": "object", "properties": {
            "source_id": {"type": "string"}}, "required": ["source_id"]},
        "fn": _tool_source_history,
    },
    "save_ai_analysis": {
        "description": "Persist an AI NewsAnalysis for a news key.",
        "schema": {"type": "object", "properties": {
            "key": {"type": "string"}, "analysis": {"type": "object"}},
            "required": ["key", "analysis"]},
        "fn": _tool_save_analysis,
    },
    "save_verification": {
        "description": "Persist a verification result (evidence, confidence, "
                       "checked_at) for a news key.",
        "schema": {"type": "object", "properties": {
            "key": {"type": "string"}, "verification": {"type": "object"}},
            "required": ["key", "verification"]},
        "fn": _tool_save_verification,
    },
    "save_translation_review": {
        "description": "Record an AI translation review / human feedback.",
        "schema": {"type": "object", "properties": {
            "key": {"type": "string"}, "review": {"type": "object"}},
            "required": ["key"]},
        "fn": _tool_save_translation_review,
    },
}


# ------------------------------------------------------------------ protocol
def _rpc(id_, method, params):
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "tools": [
                {"name": name, "description": t["description"],
                 "inputSchema": t["schema"]}
                for name, t in TOOLS.items()
            ]
        }}
    if method == "tools/call":
        name = (params or {}).get("name") or ""
        args = (params or {}).get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return {"jsonrpc": "2.0", "id": id_, "error": {
                "code": -32601, "message": f"tool not found: {name}"}}
        try:
            result = tool["fn"](args)
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "content": [{"type": "text",
                             "text": _json_dumps(result)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": id_, "error": {
                "code": -32603, "message": str(e)[:300]}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    # notifications
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("method") == "notifications/initialized":
            continue
        rid = msg.get("id")
        if rid is None:
            continue
        resp = _rpc(rid, msg.get("method"), msg.get("params"))
        if resp:
            sys.stdout.write(_json_dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
