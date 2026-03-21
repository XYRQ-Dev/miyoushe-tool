import os
import unittest

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

    async def asyncSetUp(self) -> None:
        self.database_url = get_test_database_url()
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            **build_engine_kwargs(self.database_url),
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        await self._reset_schema()

    async def asyncTearDown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    async def _reset_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # 必须在同一连接里暂时关闭外键检查再清表。
            # MySQL 下若直接按任意顺序 DELETE/TRUNCATE，带循环依赖或父子表关系的测试数据
            # 会随机触发约束错误，最终把“环境没清干净”误判成业务回归。
            await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
            try:
                for table in reversed(Base.metadata.sorted_tables):
                    await conn.execute(table.delete())
            finally:
                await conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
