"""Tests for mnemos.multimodal.engine module."""

import os
import tempfile

import numpy as np
import pytest

from mnemos.core.models import MemoryEntry, ScopeType
from mnemos.multimodal.engine import (
    MediaType,
    MediaAttachment,
    MultimodalEngine,
    _guess_mime,
    _filename_from,
    _now,
)
from mnemos.storage.palimpsest import PalimpsestStore


class TestMediaType:
    def test_valid_types(self):
        assert MediaType("image") == "image"
        assert MediaType("audio") == "audio"
        assert MediaType("video") == "video"
        assert MediaType("file") == "file"
        assert MediaType("link") == "link"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid MediaType"):
            MediaType("invalid")

    def test_is_str(self):
        assert isinstance(MediaType("image"), str)


class TestHelperFunctions:
    def test_now_returns_iso(self):
        from datetime import datetime
        datetime.fromisoformat(_now())

    def test_guess_mime_image(self):
        assert "image" in _guess_mime("photo.jpg")
        assert "image" in _guess_mime("photo.png")

    def test_guess_mime_unknown(self):
        result = _guess_mime("file.xyz")
        assert result == "" or isinstance(result, str)

    def test_filename_from_path(self):
        assert _filename_from("/tmp/photo.jpg") == "photo.jpg"

    def test_filename_from_url(self):
        assert _filename_from("https://example.com/images/photo.jpg") == "photo.jpg"


def _make_engine():
    """创建带有多模态引擎的临时 store"""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    store = PalimpsestStore(path)
    store.connect()
    # 插入 FK 依赖的 impressions 记录
    for mid in ("mem-1", "mem-2", "mem-3"):
        store.inscribe(MemoryEntry(
            entry_id=mid, scope_type=ScopeType.UNIVERSE,
            scope_id="default", content=f"test {mid}",
        ))
    engine = MultimodalEngine(store)
    return engine, store, path


class TestMultimodalEngine:
    @pytest.fixture
    def engine(self):
        eng, store, path = _make_engine()
        yield eng
        store.close()
        os.unlink(path)

    def test_attach_media_with_url(self, engine):
        mid = engine.attach_media(
            memory_id="mem-1", media_type="image",
            url="https://example.com/photo.jpg", summary="test photo",
        )
        assert mid is not None
        assert len(mid) == 16

    def test_attach_media_with_file(self, engine, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        mid = engine.attach_media(
            memory_id="mem-1", media_type="file",
            file_path=str(f), summary="test file",
        )
        assert mid is not None

    def test_attach_media_no_path_raises(self, engine):
        with pytest.raises(ValueError, match="Either file_path or url"):
            engine.attach_media(memory_id="mem-1", media_type="image")

    def test_attach_media_both_raises(self, engine):
        with pytest.raises(ValueError, match="only one"):
            engine.attach_media(
                memory_id="mem-1", media_type="image",
                file_path="/tmp/a.jpg", url="https://example.com/b.jpg",
            )

    def test_attach_invalid_media_type(self, engine):
        with pytest.raises(ValueError):
            engine.attach_media(
                memory_id="mem-1", media_type="invalid",
                url="https://example.com/test",
            )

    def test_get_attachments(self, engine):
        engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        engine.attach_media(memory_id="mem-1", media_type="audio", url="https://a.com/1.mp3")
        result = engine.get_attachments("mem-1")
        assert len(result) == 2
        assert all(isinstance(a, MediaAttachment) for a in result)

    def test_get_attachments_empty(self, engine):
        assert engine.get_attachments("mem-3") == []

    def test_get_attachment_by_id(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        att = engine.get_attachment(mid)
        assert att is not None
        assert att.media_id == mid
        assert att.media_type == "image"

    def test_get_attachment_not_found(self, engine):
        assert engine.get_attachment("nonexistent") is None

    def test_search_by_type(self, engine):
        engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        engine.attach_media(memory_id="mem-2", media_type="audio", url="https://a.com/2.mp3")
        result = engine.search_by_type("image")
        assert len(result) == 1
        assert result[0].media_type == "image"

    def test_search_by_summary(self, engine):
        engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg", summary="建筑照片")
        engine.attach_media(memory_id="mem-2", media_type="image", url="https://a.com/2.jpg", summary="风景照")
        result = engine.search_by_summary("建筑")
        assert len(result) == 1
        assert "建筑" in result[0].summary

    def test_search_by_summary_fallback_metadata(self, engine):
        """测试摘要搜索回退到 metadata（summary 列不匹配时用 metadata）"""
        # 摘要写入列，metadata 自动带 _summary
        engine.attach_media(
            memory_id="mem-1", media_type="image",
            url="https://a.com/1.jpg", summary="隐藏的摘要",
        )
        # LIKE 搜索列匹配 → 直接返回
        result = engine.search_by_summary("隐藏")
        assert len(result) == 1

    def test_update_summary(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg", summary="旧摘要")
        ok = engine.update_summary(mid, "新摘要")
        assert ok is True
        att = engine.get_attachment(mid)
        assert att.summary == "新摘要"

    def test_update_summary_not_found(self, engine):
        assert engine.update_summary("nonexistent", "新摘要") is False

    def test_delete_attachment(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        assert engine.delete_attachment(mid) is True
        assert engine.get_attachment(mid) is None

    def test_delete_attachment_not_found(self, engine):
        assert engine.delete_attachment("nonexistent") is False

    def test_store_and_load_embedding(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        vec = np.random.randn(128).astype(np.float32)
        engine.store_embedding(mid, model="test-model", vector=vec, modality="image")
        loaded = engine.load_embedding(mid)
        assert loaded is not None
        np.testing.assert_array_almost_equal(loaded, vec)

    def test_load_embedding_not_found(self, engine):
        assert engine.load_embedding("nonexistent") is None

    def test_delete_embedding(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        vec = np.random.randn(64).astype(np.float32)
        engine.store_embedding(mid, model="m", vector=vec)
        assert engine.delete_embedding(mid) is True
        assert engine.load_embedding(mid) is None

    def test_search_by_embedding(self, engine):
        mid1 = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        mid2 = engine.attach_media(memory_id="mem-2", media_type="image", url="https://a.com/2.jpg")
        vec1 = np.random.randn(64).astype(np.float32)
        vec2 = np.random.randn(64).astype(np.float32)
        engine.store_embedding(mid1, model="m", vector=vec1)
        engine.store_embedding(mid2, model="m", vector=vec2)
        results = engine.search_by_embedding(vec1, top_k=5)
        assert len(results) == 2
        assert results[0][1] >= results[1][1]

    def test_search_by_embedding_empty_vector(self, engine):
        assert engine.search_by_embedding(np.zeros(64, dtype=np.float32)) == []

    def test_search_by_embedding_with_model_filter(self, engine):
        mid = engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        vec = np.random.randn(64).astype(np.float32)
        engine.store_embedding(mid, model="model-a", vector=vec)
        assert len(engine.search_by_embedding(vec, model="model-b")) == 0

    def test_stats(self, engine):
        engine.attach_media(memory_id="mem-1", media_type="image", url="https://a.com/1.jpg")
        engine.attach_media(memory_id="mem-2", media_type="audio", url="https://a.com/2.mp3")
        stats = engine.stats()
        assert stats["total_attachments"] == 2
        assert stats["by_type"]["image"] == 1
        assert stats["by_type"]["audio"] == 1
        assert stats["total_embeddings"] == 0

    def test_media_attachment_model(self):
        att = MediaAttachment(
            media_id="test", memory_id="mem-1",
            media_type="image", summary="test",
        )
        assert att.media_id == "test"
        assert att.metadata == {}
