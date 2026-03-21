"""
数据库连接管理

当前运行时已经冻结为 MySQL-only。
这里必须把“只接受 `mysql+asyncmy://` 系列连接串”收口在同一处，
避免调用方继续靠旧方言回退或驱动自动替换侥幸启动，最后让测试环境和正式部署再次分叉。
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_database_url(database_url: str) -> str:
    """
    把外部传入的数据库连接串统一转换为当前项目可直接使用的 MySQL 异步 URL。

    约束说明：
    1. 运行时与测试基座都只允许 MySQL 异步驱动 `mysql+asyncmy://`
    2. 已废弃的旧数据库迁移路径不能再作为应用数据库 URL 混入运行期
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

    启动阶段只负责创建当前 ORM 所描述的完整结构，不承担历史补表补列。
    否则部署人员会误以为“只要重启进程就等价于完成升级”，最终把结构漂移变成线上数据问题。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
