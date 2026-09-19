"""协调账号删除与签到、登录态维护，锁跨业务提交保持有效"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount
from app.services.user_operations import user_operation


@asynccontextmanager
async def account_operation(db: AsyncSession, account_id: int):
    user_id = await db.scalar(select(MihoyoAccount.user_id).where(MihoyoAccount.id == account_id))
    if user_id is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    with user_operation(user_id):
        async with _account_operation(db, account_id):
            yield


@asynccontextmanager
async def _account_operation(db: AsyncSession, account_id: int):
    # 使用独立连接持有 MySQL 命名锁，避免签到或修复中的 commit 提前释放互斥
    # 按 schema 和账号隔离，名称散列为 64 字符；同一任务内的签到前置修复可重入
    held = db.info.setdefault("account_operation_locks", {})
    owner = asyncio.current_task()
    if account_id in held:
        if held[account_id] is not owner:
            raise HTTPException(status_code=409, detail="账号正在处理中，请稍后重试")
        yield
        return

    async with db.bind.connect() as connection:
        lock_name = (await connection.execute(
            text("SELECT SHA2(CONCAT(DATABASE(), ':account:', :account_id), 256)"),
            {"account_id": account_id},
        )).scalar_one()
        try:
            acquired = (await connection.execute(
                text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name},
            )).scalar_one()
            if acquired != 1:
                raise HTTPException(status_code=409, detail="账号正在签到或维护中，请稍后重试")
            held[account_id] = owner
            try:
                yield
            except BaseException:
                await db.rollback()
                raise
            finally:
                held.pop(account_id, None)
        finally:
            # 命名锁不随事务回滚释放，归还连接池之前必须显式释放
            try:
                await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            except BaseException:
                await connection.invalidate()
                raise


async def load_current_account(db: AsyncSession, account_id: int) -> MihoyoAccount:
    # 当前读绕过巡检/签到列表的旧快照，防止已删除对象继续触发上游请求和日志写入
    account = (await db.execute(
        select(MihoyoAccount).where(MihoyoAccount.id == account_id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account
