"""
同步引擎 — 多进程 SQLite WAL 模式下的记忆同步

设计哲学:
  记忆如河流，从源头流向远方，沿途留下痕迹。
  同步不是复制，而是让不同河段的记忆交汇。
  冲突不可避免，但可以通过策略（末位写入优先）自动化解。

核心能力:
  - push: 将本地变更推送到远程
  - pull: 从远程拉取变更到本地
  - merge: 双向合并
  - resolve: 冲突消解（末位写入优先 / 手动覆盖）
"""

from mnemos.sync.engine import SyncEngine

__all__ = ["SyncEngine"]
