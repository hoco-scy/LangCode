"""Store<T> — 极简响应式状态容器。

参考 Claude Code state/store.ts 的 34 行 createStore 实现。
Zustand 的极简子集，无需引入任何第三方依赖。

设计决策：
- 函数式更新器: set_state(lambda prev: next) 避免丢失更新
- is 相等性检查: 避免不必要的通知（非 deep equality）
- onChange 全局回调: 副作用系统的扩展点（同步到磁盘、通知远程会话等）
- Set 作为监听器容器: O(1) 删除，防重复注册
- 返回取消订阅函数: 与 React useEffect cleanup 模式兼容

用法：
    store = create_store(AppState())
    state = store.get_state()
    store.set_state(lambda prev: replace(prev, name="new"))
    unsub = store.subscribe(lambda: print("changed"))
    unsub()  # 取消订阅
"""

from __future__ import annotations

from typing import TypeVar, Callable, Generic, Optional, Any
from dataclasses import dataclass

T = TypeVar("T")

Listener = Callable[[], None]
OnChange = Callable[[dict], None]  # {"new_state": T, "old_state": T}


@dataclass(frozen=True)
class _StoreOps(Generic[T]):
    """Store 的三个操作：get_state / set_state / subscribe"""
    get_state: Callable[[], T]
    set_state: Callable[[Callable[[T], T]], None]
    subscribe: Callable[[Listener], Callable[[], None]]


def create_store(initial_state: T, on_change: Optional[OnChange] = None) -> _StoreOps[T]:
    """创建响应式状态容器。

    Args:
        initial_state: 初始状态
        on_change: 可选的全局副作用回调，在状态变更后调用

    Returns:
        Store 对象，包含 get_state / set_state / subscribe 三个操作
    """
    state: T = initial_state
    listeners: set[Listener] = set()

    def get_state() -> T:
        return state

    def set_state(updater: Callable[[T], T]) -> None:
        nonlocal state
        prev = state
        next_state = updater(prev)
        # 使用 is 而非 ==，避免 deep equality 的性能成本
        # 与 Claude Code 的 Object.is(next, prev) 等价
        if next_state is prev:
            return
        state = next_state
        if on_change is not None:
            on_change({"new_state": next_state, "old_state": prev})
        for listener in listeners:
            listener()

    def subscribe(listener: Listener) -> Callable[[], None]:
        listeners.add(listener)
        def unsubscribe():
            listeners.discard(listener)
        return unsubscribe

    return _StoreOps(get_state=get_state, set_state=set_state, subscribe=subscribe)
