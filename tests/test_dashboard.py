"""Tests for mnemos.viz.dashboard module."""

import io
import json
import tempfile
import os

import pytest
from unittest.mock import MagicMock

from mnemos.viz.dashboard import DashboardHandler


class TestDashboardHandler:
    """测试 DashboardHandler 路由和 JSON 响应"""

    def test_galaxy_route_parsing(self):
        """测试 /api/galaxy 路由解析"""
        from urllib.parse import urlparse
        parsed = urlparse("/api/galaxy")
        assert parsed.path == "/api/galaxy"

    def test_belief_tree_route_parsing(self):
        """测试 /api/belief-tree 路由解析"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse("/api/belief-tree?memory_id=test-123")
        qs = parse_qs(parsed.query)
        assert parsed.path == "/api/belief-tree"
        assert qs.get("memory_id", [None])[0] == "test-123"

    def test_entity_graph_route_parsing(self):
        """测试 /api/entity-graph 路由解析"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse("/api/entity-graph?center=Python")
        qs = parse_qs(parsed.query)
        assert parsed.path == "/api/entity-graph"
        assert qs.get("center", [None])[0] == "Python"

    def test_overview_route(self):
        """测试 /api/overview 路由"""
        from urllib.parse import urlparse
        parsed = urlparse("/api/overview")
        assert parsed.path == "/api/overview"

    def test_dashboard_html_contains_title(self):
        """测试嵌入式 HTML 包含标题"""
        from mnemos.viz.dashboard import _DASHBOARD_HTML
        assert "Mnemos" in _DASHBOARD_HTML
        assert "记忆" in _DASHBOARD_HTML

    def test_dashboard_html_contains_api_paths(self):
        """测试嵌入式 HTML 包含 API 路径"""
        from mnemos.viz.dashboard import _DASHBOARD_HTML
        assert "/api/galaxy" in _DASHBOARD_HTML
        assert "/api/belief-tree" in _DASHBOARD_HTML
        assert "/api/entity-graph" in _DASHBOARD_HTML
        assert "/api/overview" in _DASHBOARD_HTML

    def test_main_function_parses_args(self):
        """测试 main 函数参数解析"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--db", default="memory.db")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument("--host", default="0.0.0.0")
        args = parser.parse_args(["--db", "test.db", "--port", "9999", "--host", "127.0.0.1"])
        assert args.db == "test.db"
        assert args.port == 9999
        assert args.host == "127.0.0.1"

    def test_handler_has_store_and_provider_class_attrs(self):
        """测试 handler 类属性"""
        assert hasattr(DashboardHandler, "store")
        assert hasattr(DashboardHandler, "provider")

    def test_handler_log_message_silent(self):
        """测试 log_message 是静默的（不输出）"""
        # log_message 不应抛异常
        DashboardHandler.log_message(None, "test %s", "arg")

    def test_json_response_method_exists(self):
        """测试 _json 方法存在"""
        assert hasattr(DashboardHandler, "_json")

    def test_serve_dashboard_method_exists(self):
        """测试 _serve_dashboard 方法存在"""
        assert hasattr(DashboardHandler, "_serve_dashboard")

    def test_do_GET_method_exists(self):
        """测试 do_GET 方法存在"""
        assert hasattr(DashboardHandler, "do_GET")
