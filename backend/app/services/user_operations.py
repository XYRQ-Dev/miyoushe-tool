"""单进程内协调用户永久删除，正常业务之间不互斥"""

from contextlib import contextmanager

from fastapi import HTTPException


_operations: dict[int, int] = {}
_deleting: set[int] = set()


@contextmanager
def user_operation(user_id: int):
    # 与现有调度、扫码会话一样限定在单进程事件循环；检查与登记之间不能 await
    # 这里只保护操作生命周期，调用方仍须读取最新用户状态，拒绝已删除用户的旧请求
    if user_id in _deleting:
        raise HTTPException(status_code=409, detail="用户正在删除中，请稍后重试")
    _operations[user_id] = _operations.get(user_id, 0) + 1
    try:
        yield
    finally:
        remaining = _operations[user_id] - 1
        if remaining:
            _operations[user_id] = remaining
        else:
            _operations.pop(user_id)


@contextmanager
def user_deletion(user_id: int):
    if user_id in _deleting or _operations.get(user_id, 0):
        raise HTTPException(status_code=409, detail="用户正在处理中，请稍后重试")
    _deleting.add(user_id)
    try:
        yield
    finally:
        _deleting.remove(user_id)
