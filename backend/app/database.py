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


def get_gacha_record_legacy_column_ddls(existing_columns: set[str]) -> list[str]:
    """
    返回旧版 `gacha_records` 需要补齐的列定义。

    `game_uid` 是抽卡记录当前唯一可区分“同账号下不同角色”的业务维度。
    但历史库里的老记录并没有可靠来源可以反推出真实 UID，因此冷启动补列只能新增为可空列：
    - 旧数据继续保留，避免为了结构升级直接丢历史记录
    - 新版本导入会显式写入 `game_uid`
    - 依赖精确角色维度的聚合逻辑只统计非空 UID，避免把历史脏维度误当成准确归档结果
    """
    if "game_uid" in existing_columns:
        return []
    return ["ALTER TABLE gacha_records ADD COLUMN game_uid VARCHAR(50) NULL"]


def get_gacha_import_job_legacy_column_ddls(existing_columns: set[str]) -> list[str]:
    """
    返回旧版 `gacha_import_jobs` 需要补齐的列定义。

    导入任务摘要和抽卡记录必须共享同一角色维度；否则列表里看起来是“按角色导入”，
    实际重置/追溯的仍是账号级混合历史。历史任务同样无法安全回填真实 UID，因此这里保持可空兼容。
    """
    if "game_uid" in existing_columns:
        return []
    return ["ALTER TABLE gacha_import_jobs ADD COLUMN game_uid VARCHAR(50) NULL"]


def get_gacha_record_legacy_index_ddls(existing_index_names: set[str]) -> list[str]:
    """
    返回旧版 `gacha_records` 需要调整的索引定义。

    `game_uid` 改造真正影响业务正确性的不是“多一列”本身，而是唯一键维度必须同步升级。
    如果只补列、不替换旧唯一键，两个不同角色出现相同 `record_id` 时仍会被误判成重复记录，
    结果就是接口看起来支持按 UID 导入，数据库却继续按账号级把多角色历史互相覆盖。
    """
    statements: list[str] = []
    if "uq_gacha_record_account_game_record" in existing_index_names:
        statements.append("ALTER TABLE gacha_records DROP INDEX uq_gacha_record_account_game_record")
    if "uq_gacha_record_account_game_uid_record" not in existing_index_names:
        statements.append(
            "ALTER TABLE gacha_records ADD UNIQUE INDEX uq_gacha_record_account_game_uid_record "
            "(account_id, game, game_uid, record_id)"
        )
    if "ix_gacha_records_game_uid" not in existing_index_names:
        statements.append("ALTER TABLE gacha_records ADD INDEX ix_gacha_records_game_uid (game_uid)")
    return statements


def get_gacha_import_job_legacy_index_ddls(existing_index_names: set[str]) -> list[str]:
    """
    返回旧版 `gacha_import_jobs` 需要补齐的索引定义。

    导入任务历史会按 `game_uid` 回查与重置；若补列后不补索引，功能虽然不会立刻报错，
    但随着历史积累，排障和重置会逐渐退化成全表扫描。
    """
    if "ix_gacha_import_jobs_game_uid" in existing_index_names:
        return []
    return ["ALTER TABLE gacha_import_jobs ADD INDEX ix_gacha_import_jobs_game_uid (game_uid)"]


async def ensure_mihoyo_account_storage_ready() -> None:
    """
    为历史 MySQL 库补齐 `mihoyo_accounts` 缺失列。

    `Base.metadata.create_all()` 只能保证“表不存在时建整表”，不会给已存在旧表自动补列。
    当前高权限登录、登录态自愈和资产聚合都直接查询整张 `mihoyo_accounts`，
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


async def ensure_gacha_storage_ready() -> None:
    """
    为历史 MySQL 库补齐抽卡模块缺失的角色维度列。

    2026-03 起抽卡能力已经升级到 `account + game + game_uid` 维度，但旧库里的两张抽卡表仍可能停留在
    “只有账号 + 游戏”的结构上。若不在冷启动期补列并修正索引，资产总览会直接 500，
    多角色抽卡导入也会继续被旧唯一键错误拦截。
    """
    async with engine.begin() as conn:
        def _load_existing_columns(sync_conn, table_name: str):
            inspector = inspect(sync_conn)
            if not inspector.has_table(table_name):
                return None
            return {column["name"] for column in inspector.get_columns(table_name)}

        def _load_existing_index_names(sync_conn, table_name: str):
            inspector = inspect(sync_conn)
            if not inspector.has_table(table_name):
                return None

            index_names = {index["name"] for index in inspector.get_indexes(table_name)}
            index_names.update(
                constraint["name"]
                for constraint in inspector.get_unique_constraints(table_name)
                if constraint.get("name")
            )
            return index_names

        gacha_record_columns = await conn.run_sync(_load_existing_columns, "gacha_records")
        if gacha_record_columns is not None:
            for ddl in get_gacha_record_legacy_column_ddls(gacha_record_columns):
                await conn.exec_driver_sql(ddl)
            gacha_record_index_names = await conn.run_sync(_load_existing_index_names, "gacha_records")
            if gacha_record_index_names is not None:
                for ddl in get_gacha_record_legacy_index_ddls(gacha_record_index_names):
                    await conn.exec_driver_sql(ddl)

        gacha_import_job_columns = await conn.run_sync(_load_existing_columns, "gacha_import_jobs")
        if gacha_import_job_columns is not None:
            for ddl in get_gacha_import_job_legacy_column_ddls(gacha_import_job_columns):
                await conn.exec_driver_sql(ddl)
            gacha_import_job_index_names = await conn.run_sync(_load_existing_index_names, "gacha_import_jobs")
            if gacha_import_job_index_names is not None:
                for ddl in get_gacha_import_job_legacy_index_ddls(gacha_import_job_index_names):
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
    因此这里除了 `create_all()` 以外，还要在冷启动期补齐 `mihoyo_accounts` 与抽卡表的已知缺列；
    否则请求一旦进入 ORM 查询就会直接 500，用户看到的是业务接口异常，根因却是部署结构漂移。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_mihoyo_account_storage_ready()
    await ensure_gacha_storage_ready()
