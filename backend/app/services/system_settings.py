"""
系统配置服务

集中处理全局单例配置的读取与创建，避免多个服务各自“没有就自己造一份”，
从而导致数据库里出现多行配置或设备标识漂移。
"""

import weakref

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.system_setting import SystemSetting
from app.schemas.system_setting import (
    AdminMenuVisibilityItem,
    AdminMenuVisibilityResponse,
    AdminMenuVisibilityUpdate,
)
from app.services.menu_visibility import (
    APP_MENU_DEFINITIONS,
    GUARDED_ADMIN_MENU_KEY,
    MENU_DEFINITION_MAP,
    is_menu_visible_for_role,
    normalize_menu_visibility,
    serialize_menu_visibility,
)
from app.utils.timezone import utc_now_naive


class SystemSettingsService:
    # `system_settings` 的补表/补列只应该在同一个数据库引擎上做一次。
    # 这里按 sync_engine 实例做弱引用缓存，避免把“已检查过”的状态错误复用到另一个测试库/
    # 另一个部署实例上；若误按 URL 或全局布尔值缓存，内存库与多库场景会直接跳过必要补列。
    _storage_ready_sync_engines = weakref.WeakSet()

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_sync_engine(self):
        bind = self.db.bind
        if bind is None:
            raise RuntimeError("SystemSettingsService 需要绑定数据库引擎的 AsyncSession")
        return bind.sync_engine

    @staticmethod
    def _is_missing_storage_error(exc: Exception) -> bool:
        """
        判断是否属于旧库缺表/缺列导致的结构性错误。

        这里故意只兜“存储结构尚未准备好”的异常，避免把真实 SQL 语义错误吞掉后重复查询，
        否则排障时会看到接口静默重试，却找不到真正的失败根因。
        """
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "no such table",
                "no such column",
                "unknown column",
                "doesn't exist",
            )
        )

    async def ensure_storage_ready(self, *, force: bool = False) -> None:
        """
        显式准备系统配置存储结构。

        补表/补列会触发 schema inspect 和 DDL，不应该挂在登录态恢复这类高频热路径上。
        正常请求只做业务查询；只有启动阶段或明确探测到旧库结构缺失时，才进入这里做一次性修复。
        """
        sync_engine = self._get_sync_engine()
        if not force and sync_engine in self._storage_ready_sync_engines:
            return

        await self.ensure_table_exists()
        await self.ensure_required_columns()
        self._storage_ready_sync_engines.add(sync_engine)

    async def ensure_table_exists(self) -> None:
        """
        为旧部署补建 system_settings 表。

        本项目历史上没有迁移工具，线上很多实例是直接在旧 SQLite 库上升级代码。
        如果这里只依赖应用启动时的 `create_all()`，一旦进程未完全重启或旧库未补表，
        首次访问签到接口就会直接 500。这里按需补建，确保接口层对旧库具备自愈能力。
        """
        async with self.db.bind.begin() as conn:
            await conn.run_sync(SystemSetting.__table__.create, checkfirst=True)

    async def ensure_required_columns(self) -> None:
        """
        为旧部署补齐后续新增的系统配置列。

        `system_settings` 是单例全局配置表，历史上很多实例已经存在该表但没有后续新增字段。
        如果这里只依赖 `create_all()`，旧表不会自动补列，随后任意一次 `select(SystemSetting)`
        都会因为 ORM 映射里带着新列而直接报错，导致管理员配置页和登录态恢复一起失效。
        """
        async with self.db.bind.begin() as conn:
            dialect_name = conn.dialect.name

            def _load_columns(sync_conn):
                inspector = inspect(sync_conn)
                if not inspector.has_table(SystemSetting.__tablename__):
                    return None
                return {column["name"] for column in inspector.get_columns(SystemSetting.__tablename__)}

            existing_columns = await conn.run_sync(_load_columns)
            if existing_columns is None:
                await conn.run_sync(SystemSetting.__table__.create, checkfirst=True)
                return

            if "menu_visibility_json" not in existing_columns:
                column_type = "TEXT" if dialect_name == "sqlite" else "LONGTEXT"
                await conn.exec_driver_sql(
                    f"ALTER TABLE {SystemSetting.__tablename__} ADD COLUMN menu_visibility_json {column_type}"
                )

    def _build_default_config(self) -> SystemSetting:
        """
        统一构造默认系统配置。

        默认值必须收口到一个地方，避免后续菜单默认可见性、SMTP 默认端口等配置在
        “首次建行”“旧库补行”“单测构造”之间出现语义漂移。
        """
        return SystemSetting(
            id=1,
            smtp_enabled=False,
            smtp_port=465,
            smtp_use_ssl=True,
            menu_visibility_json=serialize_menu_visibility(normalize_menu_visibility(None)),
            updated_at=utc_now_naive(),
        )

    async def _persist_default_config_in_isolated_session(self) -> SystemSetting:
        """
        在独立事务中确保默认系统配置行存在。

        这里不能直接提交当前 `self.db`：
        - 调用方常常在同一个 session 里还挂着账号状态、任务日志等未提交业务改动
        - 如果为了创建 system_settings 而直接 `commit` 当前 session，会把这些无关改动一并提前落库

        因此默认配置初始化必须使用独立短生命周期 session，只提交 system_settings 自己。
        并发初始化时若别的请求已先创建出 id=1，这里吞掉唯一键冲突并回查现有行即可。
        """
        bind = self.db.bind
        if bind is None:
            raise RuntimeError("SystemSettingsService 需要绑定数据库引擎的 AsyncSession")

        isolated_session_factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
        async with isolated_session_factory() as isolated_session:
            config = self._build_default_config()
            isolated_session.add(config)
            try:
                await isolated_session.commit()
            except IntegrityError:
                await isolated_session.rollback()
                result = await isolated_session.execute(
                    select(SystemSetting).order_by(SystemSetting.id.asc()).limit(1)
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                isolated_session.expunge(existing)
                return existing

            await isolated_session.refresh(config)
            isolated_session.expunge(config)
            return config

    async def get_or_create(self) -> SystemSetting:
        try:
            # 查询 system_settings 只是在判断“单例配置是否已经存在”，
            # 不能把当前 session 里与此无关的脏对象先自动 flush 到数据库。
            # 否则后续若为了初始化默认配置而开启独立事务，在单连接或特殊连接池场景下，
            # 很容易把这些本不该提前落库的业务改动一起带入提交。
            with self.db.no_autoflush:
                result = await self.db.execute(
                    select(SystemSetting).order_by(SystemSetting.id.asc()).limit(1)
                )
                config = result.scalar_one_or_none()
        except (OperationalError, ProgrammingError) as exc:
            if not self._is_missing_storage_error(exc):
                raise
            await self.ensure_storage_ready(force=True)
            with self.db.no_autoflush:
                result = await self.db.execute(
                    select(SystemSetting).order_by(SystemSetting.id.asc()).limit(1)
                )
                config = result.scalar_one_or_none()

        if config is not None:
            return config

        persisted_config = await self._persist_default_config_in_isolated_session()
        return await self.db.merge(persisted_config, load=False)

    async def get_menu_visibility(self) -> AdminMenuVisibilityResponse:
        config = await self.get_or_create()
        normalized = normalize_menu_visibility(config.menu_visibility_json)
        serialized = serialize_menu_visibility(normalized)
        if config.menu_visibility_json != serialized:
            config.menu_visibility_json = serialized
            self.db.add(config)
            await self.db.commit()
            await self.db.refresh(config)
        return AdminMenuVisibilityResponse(
            items=[
                AdminMenuVisibilityItem(
                    key=item.key,
                    label=item.label,
                    path=item.path,
                    user_visible=normalized[item.key]["user"],
                    admin_visible=normalized[item.key]["admin"],
                    editable=item.editable,
                    navigable=item.navigable,
                )
                for item in APP_MENU_DEFINITIONS
            ]
        )

    async def update_menu_visibility(self, payload: AdminMenuVisibilityUpdate) -> AdminMenuVisibilityResponse:
        config = await self.get_or_create()
        normalized = normalize_menu_visibility(config.menu_visibility_json)

        for item in payload.items:
            if item.key not in MENU_DEFINITION_MAP:
                raise ValueError(f"未知菜单 key：{item.key}")
            if item.key == GUARDED_ADMIN_MENU_KEY:
                raise ValueError(f"{GUARDED_ADMIN_MENU_KEY} 为管理员保底入口，不允许修改")

            normalized[item.key]["user"] = item.user_visible
            normalized[item.key]["admin"] = item.admin_visible

        config.menu_visibility_json = serialize_menu_visibility(normalized)
        config.updated_at = utc_now_naive()
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return await self.get_menu_visibility()

    async def is_menu_visible_for_role(self, *, menu_key: str, role: str) -> bool:
        """
        在系统配置上下文里判断指定功能是否对当前角色开放。

        Notes API 需要在真正进入业务链路前就做统一拦截；若每个接口各自查表、各自解析，
        很容易把“默认值补齐”“旧库脏数据兜底”“管理员保底菜单规则”实现出多份，
        后续某一处漏同步时就会出现权限判断不一致。
        """
        config = await self.get_or_create()
        return is_menu_visible_for_role(
            menu_key=menu_key,
            role=role,
            raw_value=config.menu_visibility_json,
        )
