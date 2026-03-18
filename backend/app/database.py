"""
数据库连接管理

生产部署现在以 MySQL 8 为默认目标库，但测试与一次性迁移工具仍会显式使用 SQLite。
因此这里不能把某一种方言写死，而要把“URL 规范化”和“引擎参数分支”收口到同一处，
避免部署、脚本、单测各自拼接连接串，后续再出现“应用能连、脚本却连不上”的漂移。
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_database_url(database_url: str) -> str:
    """
    把外部传入的数据库连接串统一转换为当前项目可直接使用的异步 URL。

    约束说明：
    1. 生产默认要求 MySQL 异步驱动 `mysql+asyncmy://`
    2. 测试与 SQLite 源库迁移仍允许显式传入 SQLite URL
    3. 这里统一转换，避免调用方误传 `mysql://` / `mysql+pymysql://` 导致运行期才报方言不匹配
    """
    normalized = database_url.strip()
    if normalized.startswith("mysql://"):
        return normalized.replace("mysql://", "mysql+asyncmy://", 1)
    if normalized.startswith("mysql+pymysql://"):
        return normalized.replace("mysql+pymysql://", "mysql+asyncmy://", 1)
    if normalized.startswith("sqlite:///") and not normalized.startswith("sqlite+aiosqlite:///"):
        return normalized.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return normalized


def build_engine_kwargs(database_url: str) -> dict:
    """
    根据数据库方言返回引擎参数。

    不要把 SQLite 的 `check_same_thread=False` 带到 MySQL；
    也不要漏掉 MySQL 的连接保活配置，否则服务空闲一段时间后容易在首个请求上打出陈旧连接错误。
    """
    normalized = normalize_database_url(database_url)
    if normalized.startswith("sqlite+aiosqlite://"):
        return {"connect_args": {"check_same_thread": False}}

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
    因此启动阶段不能继续依赖 SQLite 补列逻辑来隐式修库。
    否则部署人员会误以为“只要重启进程就等价于完成迁移”，最终把迁移遗漏变成线上数据问题。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_account_columns(target_engine: AsyncEngine) -> None:
    """
    为旧版本 SQLite 库补齐 `mihoyo_accounts` 的登录态维护字段。

    这个函数只保留给旧 SQLite 库的兼容读取与历史数据迁移使用，
    不能再作为 MySQL 正式部署的主升级路径。误把它当成“通用迁移方案”，
    会让团队继续在生产代码里堆方言特判，而不是显式执行数据迁移。
    """
    columns_to_add = {
        "stoken_encrypted": "TEXT",
        "stuid": "VARCHAR(50)",
        "mid": "VARCHAR(100)",
        "cookie_token_updated_at": "DATETIME",
        "last_refresh_attempt_at": "DATETIME",
        "last_refresh_status": "VARCHAR(30)",
        "last_refresh_message": "TEXT",
        "reauth_notified_at": "DATETIME",
    }

    async with target_engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect != "sqlite":
            return

        result = await conn.exec_driver_sql("PRAGMA table_info(mihoyo_accounts)")
        existing_columns = {row[1] for row in result.fetchall()}
        if not existing_columns:
            return

        for column_name, column_type in columns_to_add.items():
            if column_name in existing_columns:
                continue
            await conn.exec_driver_sql(
                f"ALTER TABLE mihoyo_accounts ADD COLUMN {column_name} {column_type}"
            )


async def ensure_redeem_columns(target_engine: AsyncEngine) -> None:
    """
    为旧版本 SQLite 库补齐 `redeem_batches` 的新增统计字段。

    同样只用于旧 SQLite 库兼容；MySQL 正式部署不应依赖这里做结构演进。
    """
    columns_to_add = {
        "error_count": "INTEGER DEFAULT 0",
    }

    async with target_engine.begin() as conn:
        if conn.dialect.name != "sqlite":
            return

        result = await conn.exec_driver_sql("PRAGMA table_info(redeem_batches)")
        existing_columns = {row[1] for row in result.fetchall()}
        if not existing_columns:
            return

        for column_name, column_type in columns_to_add.items():
            if column_name in existing_columns:
                continue
            await conn.exec_driver_sql(
                f"ALTER TABLE redeem_batches ADD COLUMN {column_name} {column_type}"
            )
