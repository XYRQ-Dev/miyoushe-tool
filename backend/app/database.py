"""
数据库连接管理

当前运行时已经冻结为 MySQL-only。
这里必须把“只接受 `mysql+asyncmy://` 系列连接串”收口在同一处，
避免调用方继续靠 SQLite 回退或驱动自动替换侥幸启动，最后让测试环境和正式部署再次分叉。
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_database_url(database_url: str) -> str:
    """
    把外部传入的数据库连接串统一转换为当前项目可直接使用的 MySQL 异步 URL。

    约束说明：
    1. 运行时与测试基座都只允许 MySQL 异步驱动 `mysql+asyncmy://`
    2. 历史 SQLite 只允许被独立迁移脚本以文件方式读取，不能再作为应用数据库 URL 混入运行期
    3. 这里统一转换 `mysql://` / `mysql+pymysql://`，避免调用方误以为同步驱动仍被支持
    """
    normalized = database_url.strip()
    if normalized.startswith("mysql://"):
        return normalized.replace("mysql://", "mysql+asyncmy://", 1)
    if normalized.startswith("mysql+pymysql://"):
        return normalized.replace("mysql+pymysql://", "mysql+asyncmy://", 1)
    if normalized.startswith("mysql+asyncmy://"):
        return normalized
    raise RuntimeError(
        "DATABASE_URL 只支持 mysql+asyncmy:// 连接串；SQLite 兼容路径已下线，请先完成数据迁移"
    )


def build_engine_kwargs(database_url: str) -> dict:
    """
    根据数据库方言返回引擎参数。

    运行时既然已经冻结为 MySQL-only，就不能再保留 SQLite 参数分支。
    否则维护者会误以为“只是没人在用”，后续很容易把 SQLite URL 又悄悄接回主链路。
    """
    normalize_database_url(database_url)

    return {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }


DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    **build_engine_kwargs(DATABASE_URL),
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    初始化数据库，创建所有表。

    当前发布策略是“新 MySQL 库由 ORM 创建表 + 旧 SQLite 数据通过独立迁移脚本导入”，
    启动阶段只负责创建当前 ORM 所描述的完整结构，不再承担历史库补列。
    否则部署人员会误以为“只要重启进程就等价于完成迁移”，最终把迁移遗漏变成线上数据问题。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_account_columns(target_engine: AsyncEngine) -> None:
    """
    兼容空壳：历史调用点仍可能导入本函数，但运行时已经不再做 SQLite 补列。

    这里故意保留 no-op，而不是继续偷偷补列：
    1. 当前 worktree 里仍有旧模块通过 import 引用这个名字，直接删除会让无关路径在导入阶段崩溃
    2. 但实现必须清空，避免任何入口继续把“运行时修库”当成正式升级方案
    3. 若后续有人想恢复 SQLite 补列，请通过显式迁移脚本而不是回填这里
    """
    _ = target_engine


async def ensure_redeem_columns(target_engine: AsyncEngine) -> None:
    """
    兼容空壳：保留旧名字仅为避免当前导入方立即断裂，禁止再承担 SQLite 结构演进。
    """
    _ = target_engine
