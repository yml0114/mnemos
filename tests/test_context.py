# -*- coding: utf-8 -*-
"""
Context Management 基本测试
"""

from mnemos.context import SystemContextImpl


def test_basic_context():
    """测试基本流程：注册、观察、变更检测、admit、compact、checkpoint/restore"""
    ctx = SystemContextImpl()

    # 使用可变状态模拟 source 值变化
    state = {"value": {"num": 42}}

    def factory():
        class DummySource:
            def __init__(self):
                self.key = "test:value"

            def loader(self):
                return state["value"]

            def renderer(self, value):
                return f"Rendered {self.key}: {value}"

            def codec(self):
                return "json"

        return DummySource()

    # 1. 注册 source
    ctx.register(
        key="test:value",
        source_factory=factory,
        priority=0,
        description="Test source",
    )

    # 2. reconcile → 与空基线比较，应检测到新增
    msgs = ctx.reconcile()
    assert len(msgs) == 1
    assert msgs[0].source_key == "test:value"
    assert msgs[0].change_type == "created"

    # 3. admit → 将 pending 复制为当前快照
    ctx.admit()
    assert len(ctx._state.current_snapshot) == 1

    # 4. compact → 创建 epoch，此时基线才稳定
    epoch1 = ctx.compact()
    assert epoch1.epoch_id is not None

    # 5. produce → 应显示基线内容
    baseline = ctx.produce()
    assert "test:value" in baseline
    assert "42" in baseline

    # 6. 第二次 reconcile → 无变化（值相同）
    msgs = ctx.reconcile()
    assert len(msgs) == 0

    # 7. 改变值
    state["value"] = {"num": 43}
    msgs = ctx.reconcile()
    assert len(msgs) == 1
    assert msgs[0].change_type == "updated"
    assert "43" in msgs[0].rendered

    # 8. admit → 更新基线
    ctx.admit()
    msgs = ctx.reconcile()
    assert len(msgs) == 0

    # 9. compact → 创建新 epoch
    epoch2 = ctx.compact()
    assert epoch2.epoch_id != epoch1.epoch_id

    # 10. checkpoint/restore
    checkpoint = ctx.checkpoint()
    ctx2 = SystemContextImpl()
    ctx2.restore(checkpoint)
    assert ctx2._state.current_epoch.epoch_id == epoch2.epoch_id
    assert "test:value" in ctx2.produce()


if __name__ == "__main__":
    test_basic_context()
    print("test_basic_context passed")
