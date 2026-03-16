"""
数据库连接管理
使用 SQLAlchemy 异步引擎 + SQLite
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
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
