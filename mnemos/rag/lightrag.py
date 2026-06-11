"""
LightRAG 集成模块

将 LightRAG 作为外部 RAG 服务集成。使用 HTTP 与其查询端点通信。
环境变量：
- LIGHTRAG_URL: 服务基址（默认 http://localhost:8020）
- LIGHTRAG_TIMEOUT: 请求超时秒数（默认 10）
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

LIGHTRAG_URL = os.getenv("LIGHTRAG_URL", "http://localhost:8020")
TIMEOUT = float(os.getenv("LIGHTRAG_TIMEOUT", "10.0"))


def query_lightrag(query: str) -> Dict[str, Any]:
    """
    向 LightRAG 发送检索请求。

    参数:
        query: 用户查询文本

    返回:
        LightRAG 返回的 JSON 数据。

    异常:
        httpx.RequestError, httpx.HTTPStatusError, RuntimeError
    """
    url = f"{LIGHTRAG_URL.rstrip('/')}/query"
    resp = httpx.post(url, json={"query": query}, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"LightRAG error: {data['error']}")
    return data
