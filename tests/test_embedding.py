"""测试 Hermes 语义嵌入引擎（hash 降级路径）"""
import os
import numpy as np
import pytest

# 强制 hash 降级，跳过 ONNX 模型下载
os.environ["MNEMOS_NO_DOWNLOAD"] = "1"


@pytest.fixture
def hermes(tmp_path):
    from mnemos.embedding import Hermes
    return Hermes(cache_dir=tmp_path / "embeddings")


class TestHermesInit:
    def test_not_ready_without_model(self, hermes):
        """无 ONNX 模型时 not ready"""
        assert hermes.ready is False

    def test_default_dim(self, hermes):
        assert hermes.dim == 1024

    def test_custom_dim(self, tmp_path):
        from mnemos.embedding import Hermes
        h = Hermes(dim=256, cache_dir=tmp_path / "emb2")
        assert h.dim == 256

    def test_cache_dir_created(self, hermes):
        assert hermes.cache_dir.exists()


class TestEmbedHash:
    def test_single_text(self, hermes):
        v = hermes.embed("hello world")
        assert isinstance(v, np.ndarray)
        assert v.shape == (1024,)

    def test_normalized(self, hermes):
        v = hermes.embed("test normalization")
        norm = np.linalg.norm(v)
        assert abs(norm - 1.0) < 1e-5

    def test_batch(self, hermes):
        texts = ["hello", "world", "test"]
        v = hermes.embed(texts)
        assert v.shape == (3, 1024)
        # Each row normalized
        for i in range(3):
            norm = np.linalg.norm(v[i])
            assert abs(norm - 1.0) < 1e-5

    def test_empty_string(self, hermes):
        v = hermes.embed("")
        assert isinstance(v, np.ndarray)
        assert v.shape == (1024,)

    def test_deterministic(self, hermes):
        v1 = hermes.embed("deterministic test")
        v2 = hermes.embed("deterministic test")
        np.testing.assert_array_equal(v1, v2)

    def test_different_texts_different_vectors(self, hermes):
        v1 = hermes.embed("cats are great")
        v2 = hermes.embed("quantum physics theory")
        assert not np.allclose(v1, v2)

    def test_custom_dim_embed(self, tmp_path):
        from mnemos.embedding import Hermes
        h = Hermes(dim=512, cache_dir=tmp_path / "emb512")
        v = h.embed("custom dimension")
        assert v.shape == (512,)


class TestCosineSimilarity:
    def test_identical(self, hermes):
        v = hermes.embed("same text")
        sim = hermes.cosine_similarity(v, v)
        assert abs(sim - 1.0) < 1e-5

    def test_different(self, hermes):
        v1 = hermes.embed("completely different topic A")
        v2 = hermes.embed("totally unrelated subject B")
        sim = hermes.cosine_similarity(v1, v2)
        assert -1.0 <= sim <= 1.0
        assert sim < 0.99  # not identical

    def test_similar_texts(self, hermes):
        v1 = hermes.embed("machine learning is great")
        v2 = hermes.embed("machine learning is wonderful")
        sim = hermes.cosine_similarity(v1, v2)
        assert sim > 0.3  # should have some similarity


class TestBatchSimilarity:
    def test_shape(self, hermes):
        query = hermes.embed("query")
        candidates = np.array([hermes.embed(f"doc {i}") for i in range(5)])
        sims = hermes.batch_similarity(query, candidates)
        assert sims.shape == (5,)

    def test_top_match(self, hermes):
        query = hermes.embed("specific query about cats")
        candidates = np.array([
            hermes.embed("specific query about cats"),
            hermes.embed("something about dogs"),
            hermes.embed("unrelated topic"),
        ])
        sims = hermes.batch_similarity(query, candidates)
        assert sims[0] == sims.max()


class TestSimpleEncode:
    def test_simple_encode(self, hermes):
        ids, mask = hermes._simple_encode(["hello", "world"])
        assert ids.shape[0] == 2
        assert mask.shape[0] == 2
        # mask should have 1s for actual chars
        assert mask[0].sum() > 0


class TestGetHermes:
    def test_singleton(self):
        from mnemos.embedding import get_hermes, _hermes
        # Reset singleton for test
        import mnemos.embedding
        mnemos.embedding._hermes = None
        h1 = get_hermes()
        h2 = get_hermes()
        assert h1 is h2
        # Reset after test
        mnemos.embedding._hermes = None
