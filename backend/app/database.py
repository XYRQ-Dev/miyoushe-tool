"""
数据库连接管理
使用 SQLAlchemy 异步引擎 + SQLite
"""

from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 异步引擎，SQLite 需要 aiosqlite 驱动
# connect_args 中 check_same_thread=False 是 SQLite 必须的
engine = create_async_engine(
    settings.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
    if "aiosqlite" not in settings.DATABASE_URL
    else settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},
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
    """初始化数据库，创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_account_columns(engine)


async def ensure_account_columns(target_engine: AsyncEngine) -> None:
    """
    为旧版本 SQLite 库补齐 `mihoyo_accounts` 的登录态维护字段。

    本项目当前没有 Alembic；线上很多实例是直接覆盖代码后复用旧库。
    如果这里只更新 ORM 模型而不补列，任意一个 `select(MihoyoAccount)` 都会因为缺列直接失败，
    影响范围比“某个新功能不可用”更大，会把账号列表、签到和调度都一起打坏。
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
