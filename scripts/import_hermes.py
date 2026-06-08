#!/usr/bin/env python3
"""
从 Hermes state.db 批量导入有价值对话历史到 Mnemos 记忆系统。

读取 Hermes 的 sessions 和 messages 表，筛选有实际内容的 user/assistant
对话（排除纯工具调用、compaction 提示、空消息等），
按 session 分组生成 mnemos 记忆条目（title 用 session title，
content 用对话摘要），通过 subprocess 调用 mnemos MCP server 的
stdio 接口批量写入。

用法:
    python scripts/import_hermes.py --dry-run          # 预览模式，只统计不写入
    python scripts/import_hermes.py                     # 正式导入
    python scripts/import_hermes.py --batch-size 10     # 每批导入 10 条
    python scripts/import_hermes.py --min-messages 3    # 最少 3 条有效消息
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 默认路径 ─────────────────────────────────────────────

HERMES_DB_PATH = "/Users/liangliang/.hermes/state.db"
MNEMOS_DB_PATH = "/Users/liangliang/workspace/mnemos/mnemos.db"
MNEMOS_MCP_MODULE = "mnemos.mcp.server"

# ── 筛选参数 ─────────────────────────────────────────────

# 跳过这些 role
SKIP_ROLES = {"system", "session_meta"}

# 用户消息：内容至少这么多字符才保留
MIN_USER_CONTENT_LEN = 3

# 助手消息：如果只有 tool_calls 没有 content，跳过
# 如果 content 太短（纯 "done"/"ok" 之类），也跳过
MIN_ASSISTANT_CONTENT_LEN = 5

# session 级别：至少要有这么多条有效消息
DEFAULT_MIN_MESSAGES = 2

# 跳过的 content 模式（compaction 提示、空响应提示等）
SKIP_CONTENT_PATTERNS = (
    "[CONTEXT COMPACTION",
    "You just executed tool calls but returned an empty response.",
    "It appears that you can only understand text content.",
    "You responded without making any tool calls",
)


# ── 数据库读取 ────────────────────────────────────────────

def connect_hermes(db_path: str) -> sqlite3.Connection:
    """连接 Hermes state.db（只读模式）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """读取所有 session。"""
    cur = conn.execute(
        "SELECT id, title, message_count, tool_call_count, started_at, ended_at "
        "FROM sessions ORDER BY started_at"
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_messages_for_session(
    conn: sqlite3.Connection, session_id: str
) -> list[dict[str, Any]]:
    """读取某个 session 的所有消息。"""
    cur = conn.execute(
        "SELECT role, content, tool_calls, tool_name, timestamp "
        "FROM messages WHERE session_id = ? AND active = 1 ORDER BY timestamp",
        (session_id,),
    )
    return [dict(row) for row in cur.fetchall()]


# ── 消息筛选 ──────────────────────────────────────────────

def should_skip_content(content: str | None) -> bool:
    """判断消息内容是否应该跳过。"""
    if not content:
        return True
    text = content.strip()
    if not text:
        return True
    for pattern in SKIP_CONTENT_PATTERNS:
        if text.startswith(pattern):
            return True
    return False


def is_valuable_message(msg: dict[str, Any]) -> bool:
    """判断单条消息是否有价值（有实际对话内容）。"""
    role = msg["role"]
    if role in SKIP_ROLES:
        return False

    content = msg["content"] or ""
    tool_calls = msg["tool_calls"] or ""

    if role == "user":
        # 用户消息：需要有实际文本内容
        if should_skip_content(content):
            return False
        # 纯 URL 消息保留（可能是有意义的指令）
        return len(content.strip()) >= MIN_USER_CONTENT_LEN

    elif role == "assistant":
        # 助手消息：
        # - 有 content 且不为空 → 保留
        # - 只有 tool_calls 没有 content → 跳过（纯工具调用）
        # - content 太短 → 看 tool_calls 情况
        has_content = bool(content and content.strip())
        has_tool_calls = bool(tool_calls and tool_calls.strip())

        if not has_content and not has_tool_calls:
            return False

        # 有 content：检查是否太短
        if has_content:
            text = content.strip()
            if len(text) < MIN_ASSISTANT_CONTENT_LEN:
                # 只有很短的 content，且有 tool_calls → 可能是空回复
                if has_tool_calls:
                    return False
                return False
            return True

        # 只有 tool_calls，没有 content → 纯工具调用，跳过
        return False

    return False


def extract_conversation_summary(
    messages: list[dict[str, Any]],
    max_chars: int = 2000,
) -> str:
    """从一组消息中提取对话摘要（截断到 max_chars 字符）。"""
    lines: list[str] = []
    total_len = 0

    for msg in messages:
        role = msg["role"]
        content = (msg["content"] or "").strip()
        # 截断单条消息
        if len(content) > 500:
            content = content[:500] + "…"

        line = f"[{role}] {content}"
        if total_len + len(line) > max_chars:
            remaining = max_chars - total_len
            if remaining > 20:
                lines.append(line[:remaining] + "…")
            break
        lines.append(line)
        total_len += len(line) + 1

    return "\n\n".join(lines)


# ── 会话过滤 → 记忆条目 ──────────────────────────────────

def filter_session_to_memory(
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    min_messages: int = DEFAULT_MIN_MESSAGES,
) -> dict[str, Any] | None:
    """
    将一个 session 过滤后生成一条 mnemos 记忆条目。
    返回 None 表示该 session 不值得导入。
    """
    # 筛选有价值的消息
    valuable = [m for m in messages if is_valuable_message(m)]

    # 按 role 分组统计
    user_msgs = [m for m in valuable if m["role"] == "user"]
    assistant_msgs = [m for m in valuable if m["role"] == "assistant"]

    # 至少要有 min_messages 条有效消息
    if len(valuable) < min_messages:
        return None

    # 生成标题
    title = session.get("title") or ""
    if not title:
        # 用第一条用户消息作为标题
        if user_msgs:
            first_content = (user_msgs[0]["content"] or "").strip()
            title = first_content[:80]
        else:
            title = f"Session {session['id'][:12]}"

    # 生成摘要内容
    summary = extract_conversation_summary(valuable)

    # 时间信息
    started_at = session.get("started_at")
    if started_at:
        started_str = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")
    else:
        started_str = "unknown"

    content = (
        f"会话时间: {started_str}\n"
        f"会话ID: {session['id']}\n"
        f"有效消息数: {len(valuable)} (user: {len(user_msgs)}, assistant: {len(assistant_msgs)})\n\n"
        f"--- 对话内容 ---\n\n{summary}"
    )

    # 标签：基于 session title 提取关键词
    tags = ["hermes", "conversation"]
    if title and title != f"Session {session['id'][:12]}":
        # 从标题提取有意义的部分
        clean_title = title.replace("#", "").strip()
        if len(clean_title) <= 50:
            tags.append(clean_title)

    # 实体：标注来源
    entities = [
        {
            "label": "Hermes",
            "entity_type": "agent",
            "description": "Hermes 分身的历史对话记录",
        }
    ]

    return {
        "title": title,
        "content": content,
        "scope_type": "tenant",
        "scope_id": "",
        "tags": tags,
        "entities": entities,
        "related_to": [],
    }


# ── MCP 调用 ─────────────────────────────────────────────

def call_mnemos_import(
    memories: list[dict[str, Any]],
    db_path: str,
    dry_run: bool = False,
    workspace_dir: str = "/Users/liangliang/workspace/mnemos",
) -> dict[str, Any]:
    """
    通过 subprocess 调用 mnemos MCP server 的 stdio 接口，
    执行 batch_import 写入。

    使用 JSON-RPC over stdio 协议与 FastMCP server 通信。
    """
    # 构建 MCP initialize 请求
    init_request = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "import-hermes", "version": "1.0"},
        },
    }

    # 构建 initialized 通知
    initialized_notification = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }

    # 构建 tools/call 请求
    params_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "mnemos",
            "arguments": {
                "action": "import",
                "params": json.dumps(
                    {"memories": memories, "dry_run": dry_run},
                    ensure_ascii=False,
                ),
            },
        },
    }

    # 拼接为 JSON Lines 输入
    input_lines = (
        json.dumps(init_request, ensure_ascii=False)
        + "\n"
        + json.dumps(initialized_notification, ensure_ascii=False)
        + "\n"
        + json.dumps(params_request, ensure_ascii=False)
        + "\n"
    )

    env = os.environ.copy()
    env["MNEMOS_DB_PATH"] = db_path

    try:
        proc = subprocess.run(
            [sys.executable, "-m", MNEMOS_MCP_MODULE],
            input=input_lines,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=workspace_dir,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "MCP server timed out"}

    if proc.returncode != 0:
        # MCP server 可能因为协议问题退出，尝试解析 stderr 中的状态信息
        stderr = proc.stderr.strip() if proc.stderr else ""
        if "Mnemos server ready" in stderr:
            # Server 启动了但 stdio 协议可能没对齐
            pass

    # 解析输出：FastMCP 返回 JSON-RPC responses
    response = None
    for line in (proc.stdout or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("id") == 1 and "result" in data:
                response = data["result"]
                break
        except json.JSONDecodeError:
            continue

    if response is None:
        # 也检查 stderr（FastMCP 有时把响应写到 stderr）
        for line in (proc.stderr or "").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("id") == 1 and "result" in data:
                    response = data["result"]
                    break
                if "text" in str(data):
                    response = data
                    break
            except (json.JSONDecodeError, ValueError):
                continue

    if response is None:
        return {
            "status": "error",
            "message": "Failed to parse MCP response",
            "stdout": (proc.stdout or "")[:500],
            "stderr": (proc.stderr or "")[:500],
            "returncode": proc.returncode,
        }

    # FastMCP 返回格式: {"content": [{"type": "text", "text": "..."}]}
    if isinstance(response, dict) and "content" in response:
        for item in response["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    return {"raw_text": item["text"]}
    elif isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_text": response}

    return {"raw_response": response}


# ── 主流程 ────────────────────────────────────────────────

def scan_all_sessions(
    hermes_db: str,
    min_messages: int = DEFAULT_MIN_MESSAGES,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """扫描 Hermes DB，筛选有价值会话，生成记忆列表。"""
    conn = connect_hermes(hermes_db)
    sessions = fetch_sessions(conn)

    memories: list[dict[str, Any]] = []
    skipped = 0

    for i, session in enumerate(sessions):
        messages = fetch_messages_for_session(conn, session["id"])
        mem = filter_session_to_memory(session, messages, min_messages=min_messages)

        if mem is not None:
            memories.append(mem)
            if verbose:
                title = mem["title"]
                print(f"  ✓ [{i+1}] {title} ({len(messages)} msgs)")
        else:
            skipped += 1
            if verbose:
                title = session.get("title") or "(no title)"
                print(f"  ✗ [{i+1}] {title} — skipped ({len(messages)} msgs)")

    conn.close()
    return memories, len(sessions), skipped


def main():
    parser = argparse.ArgumentParser(
        description="从 Hermes state.db 批量导入有价值对话到 Mnemos 记忆系统"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只扫描和统计，不实际写入",
    )
    parser.add_argument(
        "--hermes-db",
        default=HERMES_DB_PATH,
        help=f"Hermes state.db 路径 (默认: {HERMES_DB_PATH})",
    )
    parser.add_argument(
        "--db",
        default=MNEMOS_DB_PATH,
        help=f"Mnemos DB 路径 (默认: {MNEMOS_DB_PATH})",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=DEFAULT_MIN_MESSAGES,
        help=f"每个 session 至少要有多少条有效消息 (默认: {DEFAULT_MIN_MESSAGES})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="每次通过 MCP 写入的记忆条数 (默认: 20)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )
    args = parser.parse_args()

    # ── 阶段 1: 扫描 ──
    print("🔍 扫描 Hermes 数据库...")
    print(f"   数据库: {args.hermes_db}")
    print()

    memories, total_sessions, skipped = scan_all_sessions(
        args.hermes_db,
        min_messages=args.min_messages,
        verbose=args.verbose,
    )

    print(f"\n📊 统计:")
    print(f"   总 sessions:    {total_sessions}")
    print(f"   有价值 sessions: {len(memories)}")
    print(f"   跳过 sessions:   {skipped}")

    if not memories:
        print("\n⚠️  没有符合筛选条件的记忆条目。")
        return

    # ── 阶段 2: 预览摘要 ──
    if args.dry_run:
        print(f"\n📋 预览 (前 10 条):")
        for i, mem in enumerate(memories[:10], 1):
            preview = mem["content"][:120].replace("\n", " ")
            print(f"   [{i}] {mem['title']}")
            print(f"       {preview}...")
        if len(memories) > 10:
            print(f"   ... 还有 {len(memories) - 10} 条")
        print(f"\n✅ 预览完成。使用不带 --dry-run 执行正式导入。")
        return

    # ── 阶段 3: 批量导入 ──
    print(f"\n🚀 开始批量导入 {len(memories)} 条记忆...")
    batch_size = args.batch_size
    total_imported = 0
    total_errors = 0

    for batch_start in range(0, len(memories), batch_size):
        batch = memories[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(memories) + batch_size - 1) // batch_size

        print(f"\n   📦 Batch {batch_num}/{total_batches} ({len(batch)} 条)...")

        result = call_mnemos_import(
            memories=batch,
            db_path=args.db,
            dry_run=False,
        )

        status = result.get("status", "unknown")
        imported = result.get("imported", 0)
        errors = result.get("errors", [])

        if status == "error":
            print(f"   ❌ 失败: {result.get('message', 'unknown error')}")
            total_errors += len(batch)
        else:
            total_imported += imported
            total_errors += len(errors)
            print(f"   ✅ 导入 {imported}/{len(batch)} 条")
            if errors:
                for err in errors[:3]:
                    print(f"      ⚠️  {err}")

        # 短暂间隔避免压力
        if batch_start + batch_size < len(memories):
            time.sleep(0.5)

    # ── 结果 ──
    print(f"\n{'=' * 50}")
    print(f"📊 导入完成:")
    print(f"   总记忆: {len(memories)}")
    print(f"   成功导入: {total_imported}")
    print(f"   失败/错误: {total_errors}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
