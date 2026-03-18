"""
SQLite 核心数据迁移工具。

迁移目标不是“把整个旧库原样拷过去”，而是把继续影响登录、签到和系统配置的核心数据
稳定搬到新库，同时明确排除抽卡/兑换等可重新积累的历史表，避免迁移窗口无限膨胀。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, build_engine_kwargs, normalize_database_url
from app.models import MihoyoAccount, GameRole, TaskLog  # noqa: F401
import app.models  # noqa: F401  # 确保 Base.metadata 完整注册所有表

CORE_TABLE_MIGRATION_ORDER = (
    "users",
    "mihoyo_accounts",
    "game_roles",
    "task_configs",
    "task_logs",
    "system_settings",
)


@dataclass
class MigrationResult:
    migrated_row_counts: dict[str, int]
    skipped_source_tables: list[str]
    validation_errors: list[str]


def _list_sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _normalize_value(column, value):
    if value is None:
        return None

    if isinstance(column.type, Boolean):
        return bool(value)

    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # 历史 SQLite 库理论上都由 SQLAlchemy 落库，正常应是 ISO 风格字符串。
            # 这里保留原值继续写入，是为了在少量脏数据存在时让迁移先暴露具体记录，
            # 而不是在预处理阶段直接吞掉上下文。
            return value

    return value


def _build_insert_payloads(table_name: str, rows: list[sqlite3.Row]) -> list[dict]:
    table = Base.metadata.tables[table_name]
    payloads: list[dict] = []
    for row in rows:
        row_dict = dict(row)
        payloads.append(
            {
                column.name: _normalize_value(column, row_dict.get(column.name))
                for column in table.columns
            }
        )
    return payloads


async def _ensure_target_core_tables_empty(session) -> None:
    non_empty_tables: dict[str, int] = {}
    for table_name in CORE_TABLE_MIGRATION_ORDER:
        table = Base.metadata.tables[table_name]
        count = (
            await session.execute(select(func.count()).select_from(table))
        ).scalar_one()
        if count:
            non_empty_tables[table_name] = count

    if non_empty_tables:
        details = ", ".join(f"{name}={count}" for name, count in non_empty_tables.items())
        raise RuntimeError(f"目标数据库不是空库，已有核心表数据：{details}")


async def _validate_core_relationships(session) -> list[str]:
    errors: list[str] = []

    invalid_account_refs = (
        await session.execute(
            select(func.count(TaskLog.id))
            .select_from(TaskLog)
            .outerjoin(MihoyoAccount, TaskLog.account_id == MihoyoAccount.id)
            .where(MihoyoAccount.id.is_(None))
        )
    ).scalar_one()
    if invalid_account_refs:
        errors.append(f"task_logs.account_id 存在 {invalid_account_refs} 条失效关联")

    invalid_role_refs = (
        await session.execute(
            select(func.count(TaskLog.id))
            .select_from(TaskLog)
            .outerjoin(GameRole, TaskLog.game_role_id == GameRole.id)
            .where(TaskLog.game_role_id.is_not(None), GameRole.id.is_(None))
        )
    ).scalar_one()
    if invalid_role_refs:
        errors.append(f"task_logs.game_role_id 存在 {invalid_role_refs} 条失效关联")

    for table_name, expected_count in []:
        # 预留给将来扩展更细的校验项，避免后续改动时重复设计返回结构。
        _ = table_name, expected_count

    return errors


async def migrate_sqlite_core_data(
    *,
    source_sqlite_path: str,
    target_database_url: str,
    require_empty_target: bool = True,
) -> MigrationResult:
    source_path = Path(source_sqlite_path)
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite 源库不存在：{source_path}")

    normalized_target_url = normalize_database_url(target_database_url)
    target_engine = create_async_engine(
        normalized_target_url,
        echo=False,
        **build_engine_kwargs(normalized_target_url),
    )
    target_session_factory = async_sessionmaker(
        target_engine,
        expire_on_commit=False,
    )

    sqlite_connection = sqlite3.connect(source_path)
    sqlite_connection.row_factory = sqlite3.Row

    migrated_row_counts: dict[str, int] = {}
    skipped_source_tables: list[str] = []
    validation_errors: list[str] = []
    try:
        source_tables = _list_sqlite_tables(sqlite_connection)

        async with target_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with target_session_factory() as session:
            # 核心迁移必须是“要么全成、要么全回滚”的单事务。
            # 如果按表逐个提交，一旦中途失败，目标库会留下半套核心数据，
            # 下次又会被“非空库保护”拦住，只能人工清库，运维成本和误操作风险都很高。
            async with session.begin():
                if require_empty_target:
                    await _ensure_target_core_tables_empty(session)

                for table_name in CORE_TABLE_MIGRATION_ORDER:
                    if table_name not in source_tables:
                        migrated_row_counts[table_name] = 0
                        skipped_source_tables.append(table_name)
                        continue

                    rows = sqlite_connection.execute(
                        f'SELECT * FROM "{table_name}" ORDER BY id ASC'
                    ).fetchall()
                    payloads = _build_insert_payloads(table_name, rows)
                    if payloads:
                        await session.execute(insert(Base.metadata.tables[table_name]), payloads)
                    migrated_row_counts[table_name] = len(payloads)

                validation_errors = await _validate_core_relationships(session)
                if validation_errors:
                    raise RuntimeError(
                        "迁移校验失败：" + "；".join(validation_errors)
                    )
    finally:
        sqlite_connection.close()
        await target_engine.dispose()

    return MigrationResult(
        migrated_row_counts=migrated_row_counts,
        skipped_source_tables=skipped_source_tables,
        validation_errors=validation_errors,
    )
