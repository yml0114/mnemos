#!/usr/bin/env python3
"""
Mnemos 统一服务入口（API + Web Dashboard）

- 继承 `mnemos.api.server` 的所有 REST API 端点
- 在根路径 `/` 提供交互式可视化仪表板
- 新增仪表板数据供给端点
- 新增对话抽取端点
- 新增 LightRAG 查询端点
"""

from __future__ import annotations

import uuid
from typing import Optional, List, Dict, Any

from fastapi import HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from mnemos.api.server import app, _get_store
from mnemos.viz.data_provider import DashboardProvider
from mnemos.core.models import MemoryEntry, MemoryTier, ScopeType

# ── 私有单例 ─────────────────────────────────────────────────────────────

_dashboard_provider: DashboardProvider | None = None


def _get_dashboard_provider() -> DashboardProvider:
    """延迟初始化仪表板数据提供者"""
    global _dashboard_provider
    if _dashboard_provider is None:
        _dashboard_provider = DashboardProvider(_get_store())
    return _dashboard_provider


# ── 根路径：仪表板 UI ─────────────────────────────────────────────────────

try:
    from mnemos.viz.dashboard import _DASHBOARD_HTML
except Exception:
    _DASHBOARD_HTML = (
        "<h1>Mnemos</h1><p>Dashboard not available. "
        "Please ensure `mnemos.viz.dashboard` is importable.</p>"
    )


@app.get("/")
def root() -> HTMLResponse:
    """返回内嵌的交互式仪表板页面"""
    return HTMLResponse(_DASHBOARD_HTML)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── 仪表板数据 API ───────────────────────────────────────────────────────

@app.get("/api/galaxy")
def api_galaxy():
    """记忆星系数据（节点/连线/时间线）"""
    return _get_dashboard_provider().galaxy()


@app.get("/api/belief-tree")
def api_belief_tree(memory_id: Optional[str] = Query(None)):
    """信念演化树。可选参数 memory_id 限定单个记忆的修订链。"""
    return _get_dashboard_provider().belief_tree(memory_id)


@app.get("/api/entity-graph")
def api_entity_graph(center: Optional[str] = Query(None)):
    """实体关系图。可选参数 center 为中心实体标签。"""
    return _get_dashboard_provider().entity_graph(center)


@app.get("/api/overview")
def api_overview():
    """系统概览面板"""
    return _get_dashboard_provider().overview()


# ── 对话知识自动抽取 ─────────────────────────────────────────────────────

class ExtractRequest(BaseModel):
    messages: List[Dict[str, Any]]
    conversation_id: Optional[str] = None


@app.post("/v1/extract/conversation")
def extract_conversation(req: ExtractRequest):
    """
    从对话消息中自动抽取结构化记忆。
    简易实现：将每条消息作为独立印象层记忆入库。
    """
    store = _get_store()
    created_ids = []

    for msg in req.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content:
            continue

        entry_id = str(uuid.uuid4())
        title = content[:50] + ("..." if len(content) > 50 else "")

        entry = MemoryEntry(
            entry_id=entry_id,
            content=content,
            title=title,
            scope_type=ScopeType.TENANT,
            scope_id=req.conversation_id or "general",
            tier=MemoryTier.IMPRESSION,
            tags=["auto-extracted", role],
            entities_json=[],
        )
        store.inscribe(entry)
        created_ids.append(entry_id)

    return {"created": created_ids}


# ── LightRAG 查询集成 ────────────────────────────────────────────────────

class LightRAGQueryRequest(BaseModel):
    query: str


@app.post("/v1/lightrag/query")
def lightrag_query(req: LightRAGQueryRequest):
    """
    将查询转发给外部的 LightRAG 服务。
    环境变量 LIGHTRAG_URL 指定服务地址（默认 http://localhost:8020）。
    """
    import os
    import httpx

    url = os.getenv("LIGHTRAG_URL", "http://localhost:8020").rstrip("/") + "/query"
    try:
        resp = httpx.post(url, json={"query": req.query}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"LightRAG service unavailable: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
