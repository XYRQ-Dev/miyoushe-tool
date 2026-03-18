"""
把旧 SQLite 核心数据迁移到 MySQL 8。

运行示例：
python scripts/migrate_sqlite_to_mysql.py --sqlite-path ../data/miyoushe.db --mysql-url "mysql+asyncmy://user:pwd@host:3306/db?charset=utf8mb4"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 迁移脚本经常会按 README 指引以 `python scripts/...` 方式直接执行。
# 此时 Python 只会把 `backend/scripts` 放入 `sys.path`，导致同级的 `app` 包不可见。
# 这里显式把 `backend` 根目录加入模块搜索路径，避免运维在真实迁移时因为启动方式不同直接失败。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.database import normalize_database_url
from app.migrations.sqlite_to_mysql import migrate_sqlite_core_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移 SQLite 核心数据到 MySQL 8")
    parser.add_argument(
        "--sqlite-path",
        required=True,
        help="旧 SQLite 数据库文件路径",
    )
    parser.add_argument(
        "--mysql-url",
        default=settings.DATABASE_URL,
        help="目标 MySQL 异步连接串，默认读取当前环境的 DATABASE_URL",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    target_url = normalize_database_url(args.mysql_url)
    if not target_url.startswith("mysql+asyncmy://"):
        raise SystemExit("目标数据库必须是 mysql+asyncmy:// 连接串，避免误覆盖到非 MySQL 库")

    try:
        result = await migrate_sqlite_core_data(
            source_sqlite_path=args.sqlite_path,
            target_database_url=target_url,
        )
    except Exception as exc:
        print(f"迁移失败：{exc}")
        return 1

    print("核心表迁移完成：")
    for table_name, count in result.migrated_row_counts.items():
        print(f"  - {table_name}: {count}")

    if result.skipped_source_tables:
        print("源库中不存在的可选核心表：")
        for table_name in result.skipped_source_tables:
            print(f"  - {table_name}")

    if result.validation_errors:
        print("迁移校验失败：")
        for error in result.validation_errors:
            print(f"  - {error}")
        return 1

    print("迁移校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
