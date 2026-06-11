"""Tests for mnemos.evolve module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from mnemos.evolve import run_evolve


class TestRunEvolve:
    """测试 run_evolve 函数"""

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_basic_flow_with_all_disabled(self, MockHealer, MockCondenser):
        """测试禁用所有可选步骤的基本流程"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        result = run_evolve(
            mock_store,
            embedding_enabled=False,
            path_check_enabled=False,
            compression_age_days=0,
        )

        assert "started_at" in result
        assert "completed_at" in result
        assert "steps" in result
        assert result["steps"]["heal"]["healed"] is True
        assert result["steps"]["duplicate_detection"]["skipped"] is True
        assert result["steps"]["path_validation"]["skipped"] is True

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_heal_step_called(self, MockHealer, MockCondenser):
        """测试 heal 步骤被调用"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = ["issue1", "issue2"]
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        result = run_evolve(
            mock_store,
            embedding_enabled=False,
            path_check_enabled=False,
            compression_age_days=0,
        )

        assert result["steps"]["heal"]["issues_found"] == 2
        mock_healer.heal_all.assert_called_once()

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_condense_step_called(self, MockHealer, MockCondenser):
        """测试 condense 步骤被调用"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 3, "promoted": 1}
        MockCondenser.return_value = mock_condenser

        result = run_evolve(
            mock_store,
            embedding_enabled=False,
            path_check_enabled=False,
            compression_age_days=0,
        )

        assert result["steps"]["condense"]["condensed"] == 3
        assert result["steps"]["condense"]["promoted"] == 1

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_embedding_enabled_raises(self, MockHealer, MockCondenser):
        """测试启用 embedding 时抛出 NotImplementedError"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        with pytest.raises(NotImplementedError, match="重复检测"):
            run_evolve(
                mock_store,
                embedding_enabled=True,
                path_check_enabled=False,
                compression_age_days=0,
            )

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_path_check_enabled_raises(self, MockHealer, MockCondenser):
        """测试启用路径检查时抛出 NotImplementedError"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        with pytest.raises(NotImplementedError, match="URL 路径验证"):
            run_evolve(
                mock_store,
                embedding_enabled=False,
                path_check_enabled=True,
                compression_age_days=0,
            )

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_compression_enabled_raises(self, MockHealer, MockCondenser):
        """测试启用压缩时抛出 NotImplementedError"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        with pytest.raises(NotImplementedError, match="旧印象压缩"):
            run_evolve(
                mock_store,
                embedding_enabled=False,
                path_check_enabled=False,
                compression_age_days=30,
            )

    @patch("mnemos.evolve.AlchemistCondenser")
    @patch("mnemos.evolve.HealerEngine")
    def test_timestamps_present(self, MockHealer, MockCondenser):
        """测试时间戳格式正确"""
        mock_store = MagicMock()
        mock_healer = MagicMock()
        mock_healer.scan.return_value = []
        MockHealer.return_value = mock_healer

        mock_condenser = MagicMock()
        mock_condenser.auto_condense.return_value = {"condensed": 0}
        MockCondenser.return_value = mock_condenser

        result = run_evolve(
            mock_store,
            embedding_enabled=False,
            path_check_enabled=False,
            compression_age_days=0,
        )

        # 验证 ISO 格式时间戳
        datetime.fromisoformat(result["started_at"])
        datetime.fromisoformat(result["completed_at"])
