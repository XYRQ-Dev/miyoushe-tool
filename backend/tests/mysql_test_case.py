import os
import unittest

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, build_engine_kwargs


def get_test_database_url() -> str:
    """
    统一读取测试库连接串，并强制要求显式的 MySQL 异步 URL。

    测试基座绝不能在变量缺失时私自回落到 SQLite 或别的默认库；
    否则用例会在“临时数据库”里看起来全部通过，但真实部署依赖的 MySQL 约束、方言差异和外键行为
    都被绕开，最终把回归风险藏进 CI 和本地环境差异里。
    """
    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("缺少 TEST_DATABASE_URL；MySQL-only 测试必须显式指定 mysql+asyncmy:// 连接串")
    if not database_url.startswith("mysql+asyncmy://"):
        raise RuntimeError("TEST_DATABASE_URL 只支持 mysql+asyncmy:// 连接串，禁止回落到 SQLite")
    return database_url


class MySqlIsolatedAsyncioTestCase(unittest.IsolatedAsyncioTestCase):
    """
    为需要真实 MySQL 行为的异步测试提供统一隔离基座。

    每个用例都会先建表再清库，而不是依赖“上一个测试正好把环境整理干净”。
    这样可以把失败定位收敛到当前测试本身，避免并行执行或中途失败后把脏数据遗留给后续用例。
    """

    engine = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    recreate_schema = False
    _lock_connection = None
    _lock_name = None
    _lock_timeout_seconds = 30

    async def asyncSetUp(self) -> None:
        self.database_url = get_test_database_url()
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            **build_engine_kwargs(self.database_url),
        )
        database_name = make_url(self.database_url).database or "default"
        # 测试锁必须按目标 schema 隔离，而不是整台 MySQL 实例共用一个固定名字。
        # 否则多个代理即便切到各自独立的测试库，也会因为抢同一把全局锁而互相阻塞，
        # 最终把“验证资源隔离做对了”误伤成“测试框架卡死”。
        self._lock_name = f"{database_name}_suite_lock"
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        await self._acquire_database_lock()
        await self._reset_schema()

    async def asyncTearDown(self) -> None:
        try:
            await self._release_database_lock()
        finally:
            if self.engine is not None:
                await self.engine.dispose()

    async def _new_session(self):
        if self.session_factory is None:
            raise RuntimeError("测试会话工厂尚未初始化，请先执行 asyncSetUp")
        return self.session_factory()

    def _resolve_lock_name(self) -> str:
        if self._lock_name:
            return self._lock_name

        database_url = getattr(self, "database_url", None)
        if not database_url and self.engine is not None and getattr(self.engine, "url", None) is not None:
            database_url = str(self.engine.url)

        database_name = make_url(database_url).database if database_url else None
        return f"{database_name or 'default'}_suite_lock"

    async def _reset_schema(self) -> None:
        async with self.engine.begin() as conn:
            # `recreate_schema` 只给极少数需要强制重建表结构的用例使用。
            # 这类测试通常是在锁定“当前 ORM 元数据必须真正落到 MySQL 表结构”这一约束；
            # 如果仍走 create_all()+清库，旧表残留字段/索引会被静默保留，测试就会把结构漂移误判成业务问题。
            if self.recreate_schema:
                await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    await conn.run_sync(Base.metadata.drop_all)
                    await conn.run_sync(Base.metadata.create_all)
                finally:
                    await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
                return

            await conn.run_sync(Base.metadata.create_all)
            # 必须在同一连接里暂时关闭外键检查再清表。
            # MySQL 下若直接按任意顺序 DELETE/TRUNCATE，带循环依赖或父子表关系的测试数据
            # 会随机触发约束错误，最终把“环境没清干净”误判成业务回归。
            await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
            try:
                for table in reversed(Base.metadata.sorted_tables):
                    await conn.execute(table.delete())
                    # MySQL 的 DELETE 不会回卷 AUTO_INCREMENT。
                    # 现有大量单测会显式断言“首个用户/账号的 id 为 1”或把 job_id 拼成 `checkin_user_1`；
                    # 如果这里只清行不重置序列，用例会在完整测试集中随机漂移成 2/3/4...，
                    # 看起来像业务回归，实则只是测试基座没有恢复到确定性初始状态。
                    if table._autoincrement_column is not None:
                        await conn.exec_driver_sql(f"ALTER TABLE `{table.name}` AUTO_INCREMENT = 1")
            finally:
                await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")

    async def _acquire_database_lock(self) -> None:
        if self.engine is None:
            raise RuntimeError("测试引擎尚未初始化，无法申请数据库锁")
        self._lock_name = self._resolve_lock_name()
        # 当前多个代理会共享同一个 `miyoushe_test` 库。
        # 如果仍让每个测试实例在无锁状态下执行 `create_all()/drop_all()/全表 DELETE`，
        # 最先暴露的就会是并发 DDL 冲突和清库死锁，而不是本用例真正要验证的业务/FK 回归。
        # 这里把锁覆盖整个测试生命周期，避免别的用例在本测试执行中途再次清空共享库。
        self._lock_connection = await self.engine.connect()
        result = await self._lock_connection.exec_driver_sql(
            f"SELECT GET_LOCK('{self._lock_name}', {self._lock_timeout_seconds})"
        )
        if result.scalar_one() != 1:
            await self._lock_connection.close()
            self._lock_connection = None
            raise RuntimeError(
                f"未能在 {self._lock_timeout_seconds} 秒内获取测试库锁：{self._lock_name}"
            )

    async def _release_database_lock(self) -> None:
        if self._lock_connection is None:
            return
        try:
            await self._lock_connection.exec_driver_sql(
                f"SELECT RELEASE_LOCK('{self._lock_name}')"
            )
        finally:
            await self._lock_connection.close()
            self._lock_connection = None
