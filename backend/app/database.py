"""
数据库连接管理

当前运行时已经冻结为 MySQL-only。
这里必须把“只接受 `mysql+asyncmy://` 系列连接串”收口在同一处，
避免调用方继续靠旧方言回退或驱动自动替换侥幸启动，最后让测试环境和正式部署再次分叉。
"""

from sqlalchemy import inspect
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


def get_mihoyo_account_legacy_column_ddls(existing_columns: set[str]) -> list[str]:
    """
    返回旧版 `mihoyo_accounts` 需要补齐的列定义。

    这里故意把“缺哪些列、各列该如何建”写成显式白名单，而不是运行时从 ORM 自动拼 DDL：
    1. 冷启动补列属于兼容旧部署的救援路径，要求行为稳定、可审计
    2. 若直接把 ORM 列定义无差别翻译成 ALTER TABLE，后续模型里新增索引/约束/方言参数时，
       很容易在没有审查的情况下把启动期 DDL 扩大成不可控变更
    3. 当前项目已经下线 SQLite 兼容，剩余的历史包袱集中在老 MySQL 库缺少 Passport 根凭据相关列
    """
    ddl_by_column = {
        "ltoken_encrypted": "ADD COLUMN ltoken_encrypted TEXT NULL",
        "cookie_token_encrypted": "ADD COLUMN cookie_token_encrypted TEXT NULL",
        "login_ticket_encrypted": "ADD COLUMN login_ticket_encrypted TEXT NULL",
        "credential_source": "ADD COLUMN credential_source VARCHAR(30) NULL",
        "credential_status": "ADD COLUMN credential_status VARCHAR(30) NULL DEFAULT 'reauth_required'",
        "last_token_refresh_at": "ADD COLUMN last_token_refresh_at DATETIME NULL",
        "last_token_refresh_status": "ADD COLUMN last_token_refresh_status VARCHAR(30) NULL",
        "last_token_refresh_message": "ADD COLUMN last_token_refresh_message TEXT NULL",
    }
    return [
        f"ALTER TABLE mihoyo_accounts {ddl}"
        for column_name, ddl in ddl_by_column.items()
        if column_name not in existing_columns
    ]


async def ensure_mihoyo_account_storage_ready() -> None:
    """
    为历史 MySQL 库补齐 `mihoyo_accounts` 缺失列。

    `Base.metadata.create_all()` 只能保证“表不存在时建整表”，不会给已存在旧表自动补列。
    当前高权限登录和登录态自愈都直接查询整张 `mihoyo_accounts`，
    所以只要旧库少了 Passport 根凭据相关列，请求就会在 ORM 选列阶段直接 500。

    这类 schema inspect + DDL 只能放在冷启动期执行，不能退回到 `/accounts`、`/tasks/status`
    这样的热路径里，否则每次请求都会背上结构探测成本，还会把真实 SQL 异常伪装成“应用会自己修”。
    """
    async with engine.begin() as conn:
        def _load_existing_columns(sync_conn):
            inspector = inspect(sync_conn)
            if not inspector.has_table("mihoyo_accounts"):
                return None
            return {column["name"] for column in inspector.get_columns("mihoyo_accounts")}

        existing_columns = await conn.run_sync(_load_existing_columns)
        if existing_columns is None:
            return

        for ddl in get_mihoyo_account_legacy_column_ddls(existing_columns):
            await conn.exec_driver_sql(ddl)


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

    运行时已经冻结为 MySQL-only，但历史本地库仍可能残留“表存在、列不全”的状态。
    因此这里除了 `create_all()` 以外，还要在冷启动期补齐 `mihoyo_accounts` 的已知缺列；
    否则请求一旦进入 ORM 查询就会直接 500，用户看到的是业务接口异常，根因却是部署结构漂移。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_mihoyo_account_storage_ready()
