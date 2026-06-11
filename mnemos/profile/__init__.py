"""
用户画像引擎 — Mneme

对标 Supermemory 的自动用户画像构建：
- 从记忆中自动提取用户偏好、习惯、身份信息
- 静态画像（长期不变）+ 动态画像（近期活跃）
- 单次 API 调用返回完整画像，消除 Agent 冷启动问题
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mnemos.core.models import MemoryEntry as MemoryEntry, MemoryTier as MemoryTier, ScopeType
from mnemos.storage.palimpsest import PalimpsestStore


# 偏好关键词 → 画像类别映射
PREFERENCE_CATEGORIES = {
    "喜欢|偏好|爱用|习惯|倾向|首选|常用|最喜欢|最爱": "preference",
    "使用|在用|用了|选择|采用|决定用|换成": "tool",
    "住在|居住|地址|搬到|搬家": "location",
    "工作在|担任|就职|入职|加入.*公司|在.*上班": "job",
    "学习|研究|探索|尝试|实验": "learning",
    "项目|正在做|开发|搭建|构建|建设": "project",
    "目标|计划|打算|想要|希望|期望": "goal",
    "不喜欢|讨厌|避免|不用|放弃|拒绝": "dislike",
    "语言|编程|代码|技术|框架|工具链": "tech_stack",
    "团队|同事|老板|客户|合作伙伴": "people",
}


class UserProfile:
    """用户画像数据结构"""

    def __init__(self, scope_id: str = ""):
        self.scope_id = scope_id
        self.static: dict[str, list[str]] = {}    # 长期稳定事实
        self.dynamic: dict[str, list[str]] = {}   # 近期活跃信息
        self.preferences: list[str] = []
        self.tools: list[str] = []
        self.projects: list[str] = []
        self.last_updated: str = ""


class Mneme:
    """
    用户画像引擎 — 自动从记忆中构建用户画像。

    对标 Supermemory 的自动画像构建（~50ms 查询），
    用规则引擎实现，不依赖 LLM。

    使用示例:
        mneme = Mneme(store)
        profile = mneme.build("user_001")
        print(profile.preferences)  # ["喜欢黑暗模式", "偏好看板视图"]
    """

    def __init__(self, store: PalimpsestStore):
        self._store = store

    def build(self, scope_id: str) -> UserProfile:
        """构建用户完整画像"""
        profile = UserProfile(scope_id=scope_id)

        all_memories = self._store.by_scope(
            ScopeType.TENANT, scope_id, limit=200
        )

        now = datetime.now(timezone.utc)
        recent_threshold = now - timedelta(days=14)

        for mem in all_memories:
            # 只关注活跃状态（排除已过期的历史状态）
            if hasattr(mem, 'is_active') and not mem.is_active:
                continue

            content = mem.content
            # 兼容 offset-naive 和 aware 的比较
            if mem.created_at:
                if mem.created_at.tzinfo is None:
                    mem_created = mem.created_at.replace(tzinfo=timezone.utc)
                else:
                    mem_created = mem.created_at
                is_recent = mem_created >= recent_threshold
            else:
                is_recent = False

            # 分类
            for pattern, category in PREFERENCE_CATEGORIES.items():
                import re
                if re.search(pattern, content):
                    # 提取关键信息
                    extracted = self._extract_fact(content, pattern)

                    if is_recent:
                        profile.dynamic.setdefault(category, []).append(extracted)
                    else:
                        profile.static.setdefault(category, []).append(extracted)

                    # 特殊分类
                    if category == "preference":
                        profile.preferences.append(extracted)
                    elif category == "tool":
                        profile.tools.append(extracted)
                    elif category == "project":
                        profile.projects.append(extracted)
                    break  # 一条记忆只归一个类别

        # 去重
        profile.preferences = list(dict.fromkeys(profile.preferences))
        profile.tools = list(dict.fromkeys(profile.tools))
        profile.projects = list(dict.fromkeys(profile.projects))
        profile.last_updated = now.isoformat()

        return profile

    def _extract_fact(self, content: str, pattern: str) -> str:
        """提取简洁事实描述"""
        # 截取模式匹配附近的关键内容
        import re
        m = re.search(pattern, content)
        if m:
            start = max(0, m.start() - 5)
            end = min(len(content), m.end() + 40)
            snippet = content[start:end].strip()
            # 截断到句末
            for punct in '。！？.!?':
                idx = snippet.find(punct)
                if idx > 0:
                    snippet = snippet[:idx + 1]
                    break
            return snippet
        return content[:80]

    def summary(self, profile: UserProfile) -> str:
        """生成画像摘要文本（适合注入系统提示）"""
        parts = []

        if profile.preferences:
            parts.append(f"偏好: {'; '.join(profile.preferences[:5])}")
        if profile.tools:
            parts.append(f"工具: {'; '.join(profile.tools[:5])}")
        if profile.projects:
            parts.append(f"项目: {'; '.join(profile.projects[:3])}")

        for cat, facts in profile.dynamic.items():
            if facts:
                parts.append(f"近期{cat}: {'; '.join(facts[:3])}")

        return "\n".join(parts) if parts else "(无画像)"
