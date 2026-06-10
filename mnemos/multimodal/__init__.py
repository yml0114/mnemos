"""多模态记忆管理 — MultimodalEngine

为记忆系统提供媒体附件存储与检索能力：
- MediaType 枚举（image, audio, video, file, link）
- MediaAttachment Pydantic 模型
- MultimodalEngine 引擎（基于 PalimpsestStore 的 media_attachments / media_embeddings 表）
"""

from __future__ import annotations

from mnemos.multimodal.engine import MediaAttachment, MediaType, MultimodalEngine

__all__ = ["MediaType", "MediaAttachment", "MultimodalEngine"]
