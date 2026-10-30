"""SQLite 本地日程库。

本文件职责：
- 初始化 data/dawndine.db 与 schedules / records 表；
- 提供日程新增、批量导入、倒序查询、Dataframe 行转换；
- 为台账、异常、水印、对话和图片导入提供统一的日程沉淀入口；
- 为工具完整草稿提供 records 历史留痕的写入与回查。

依赖：dawndine.config、dawndine.enums、sqlite3、json。
被调用：agent/tools/*.py、services/*.py、ui/*.py、__main__.py。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from dawndine.config import DB_PATH
from dawndine.enums import (
    ASSET_STATUS_VALUES,
    FEEDBACK_STATUS_VALUES,
    INSPECTION_RESULT_VALUES,
    INSPECTION_STATUS_VALUES,
    MAINTENANCE_STATUS_PENDING,
    RECORD_KIND_VALUES,
    SCHEDULE_SOURCE_CHAT,
    SCHEDULE_SOURCE_VALUES,
)

__all__ = [
    "DB_PATH",
    "init_db",
    "normalize_date",
    "normalize_time",
    "split_datetime",
    "create_schedule",
    "list_schedules",
    "list_schedule_rows",
    "delete_schedule",
    "delete_schedules",
    "delete_all_schedules",
    "update_schedule",
    "bulk_create_schedules",
    "safe_create_schedule",
    "create_maintenance",
    "list_maintenance",
    "list_maintenance_rows",
    "count_maintenance_by_location",
    "create_asset",
    "list_assets",
    "upsert_inventory",
    "list_inventory",
    "list_low_stock",
    "create_inspection",
    "list_inspections",
    "upsert_supplier",
    "list_suppliers",
    "create_staff",
    "list_staff",
    "create_feedback",
    "list_feedback",
    "logistics_overview",
    "reset_all_data",
    "delete_maintenance",
    "delete_maintenance_records",
    "delete_all_maintenance",
    "save_record",
    "safe_save_record",
    "list_records",
    "get_record",
]

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    "date" TEXT NOT NULL,
    "time" TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_date
    ON schedules("date" DESC, "time" DESC);
CREATE INDEX IF NOT EXISTS idx_schedules_created
    ON schedules(created_at DESC);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    schedule_id INTEGER,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_kind_created
    ON records(kind, created_at DESC);

CREATE TABLE IF NOT EXISTS maintenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location TEXT NOT NULL,
    issue TEXT NOT NULL,
    reporter TEXT NOT NULL,
    report_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '待处理',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_maintenance_location
    ON maintenance(location COLLATE NOCASE ASC, report_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_no TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '在用',
    purchase_date TEXT NOT NULL DEFAULT '',
    warranty_until TEXT NOT NULL DEFAULT '',
    last_check TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_no
    ON assets(asset_no COLLATE NOCASE) WHERE asset_no <> '';
CREATE INDEX IF NOT EXISTS idx_assets_location
    ON assets(location COLLATE NOCASE ASC, id DESC);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    reorder_level REAL NOT NULL DEFAULT 0,
    location TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_item
    ON inventory(item COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_inventory_category
    ON inventory(category COLLATE NOCASE ASC, item COLLATE NOCASE ASC);

CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    item TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '正常',
    issue TEXT NOT NULL DEFAULT '',
    inspector TEXT NOT NULL DEFAULT '',
    inspect_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '已闭环',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspections_date
    ON inspections(inspect_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    license_until TEXT NOT NULL DEFAULT '',
    rating TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_name
    ON suppliers(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    health_cert_until TEXT NOT NULL DEFAULT '',
    training_date TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_department
    ON staff(department COLLATE NOCASE ASC, name COLLATE NOCASE ASC);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    handler TEXT NOT NULL DEFAULT '',
    rating INTEGER,
    status TEXT NOT NULL DEFAULT '待处理',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_status
    ON feedback(status, created_at DESC);
"""


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """打开一次 SQLite 连接，自动提交/回滚并关闭。"""

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH), timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """创建数据库目录、表与索引；幂等。"""

    with _connection() as connection:
        connection.executescript(_SCHEMA)
    logger.info("本地数据库就绪：%s", DB_PATH)


def normalize_date(value: str | None) -> str:
    """把常见日期格式归一为 YYYY-MM-DD；空值取今天。"""

    clean = (value or "").strip()
    if not clean:
        return datetime.now().strftime("%Y-%m-%d")
    if clean in {"待补", "未知"}:
        return "待补"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"日期格式无法识别：{value}")


def normalize_time(value: str | None) -> str:
    """把常见时间格式归一为 HH:MM；空值写“待补”。"""

    clean = (value or "").strip()
    if not clean or clean in {"待补", "未知"}:
        return "待补"
    for fmt in ("%H:%M", "%H:%M:%S", "%H时%M分"):
        try:
            return datetime.strptime(clean, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"时间格式无法识别：{value}")


def split_datetime(value: str | None) -> tuple[str, str]:
    """把日期时间字符串拆成日期与时间；无法解析时取当前时间。"""

    clean = (value or "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y.%m.%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            moment = datetime.strptime(clean, fmt)
            return moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M")
        except ValueError:
            continue
    try:
        return normalize_date(clean), "待补"
    except ValueError:
        now = datetime.now()
        return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def _normalize_source(source: str | None) -> str:
    """限制来源到统一枚举，未知来源回退为对话。"""

    clean = (source or "").strip()
    if clean in SCHEDULE_SOURCE_VALUES:
        return clean
    return SCHEDULE_SOURCE_CHAT


def _reusable_id(connection: sqlite3.Connection, table: str) -> int:
    """返回指定表可用的最小正整数编号，删除后留下的空号优先复用。

    例：现有编号 1、2、4（3 被删除），下一条写入 3；若 1~4 连续，则写入 5。
    这样前面被删掉的编号会先被补回，编号始终尽量连续。
    仅供本模块以固定表名调用，table 不接收外部输入。
    """

    row = connection.execute(
        "SELECT MIN(cand) FROM ("
        "  SELECT 1 AS cand"
        f"  UNION ALL SELECT id + 1 AS cand FROM {table}"
        f") WHERE NOT EXISTS (SELECT 1 FROM {table} AS t WHERE t.id = cand)"
    ).fetchone()
    candidate = row[0] if row else None
    if candidate is None:
        top = connection.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()
        return int(top[0] or 1)
    return max(1, int(candidate))


def _reusable_schedule_id(connection: sqlite3.Connection) -> int:
    """日程编号：删除后留下的空号优先复用。"""

    return _reusable_id(connection, "schedules")


def _reusable_maintenance_id(connection: sqlite3.Connection) -> int:
    """维修编号：删除后留下的空号优先复用。"""

    return _reusable_id(connection, "maintenance")


def create_schedule(
    date: str | None,
    time: str | None,
    content: str,
    source: str = SCHEDULE_SOURCE_CHAT,
) -> dict[str, Any]:
    """写入一条日程并返回完整记录。

    Args:
        date: 日期，可传 YYYY-MM-DD / YYYY/MM/DD；空值取今天。
        time: 时间，可传 HH:MM / HH:MM:SS；空值写“待补”。
        content: 事项，不能为空。
        source: 来源，统一从 constants.py 的 SCHEDULE_SOURCE_* 取值。

    Returns:
        {"id", "date", "time", "content", "source", "created_at"}

    Raises:
        ValueError: 事项为空或日期/时间格式非法。
    """

    clean_content = (content or "").strip()
    if not clean_content:
        raise ValueError("日程事项不能为空。")

    normalized_date = normalize_date(date)
    normalized_time = normalize_time(time)
    normalized_source = _normalize_source(source)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _connection() as connection:
        # 编号不依赖自增：删除后留下的空号优先回填，编号尽量连续。
        schedule_id = _reusable_schedule_id(connection)
        connection.execute(
            'INSERT INTO schedules (id, "date", "time", content, source, created_at) '
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                schedule_id,
                normalized_date,
                normalized_time,
                clean_content,
                normalized_source,
                created_at,
            ),
        )

    record = {
        "id": schedule_id,
        "date": normalized_date,
        "time": normalized_time,
        "content": clean_content,
        "source": normalized_source,
        "created_at": created_at,
    }
    logger.info("日程已写入：id=%s source=%s", schedule_id, normalized_source)
    return record


def list_schedules(
    limit: int = 500,
    date_from: str | None = None,
    date_to: str | None = None,
    only_pending: bool = False,
) -> list[dict[str, Any]]:
    """按日期、时间倒序返回日程，可按日期区间或待补时间过滤。

    Args:
        limit: 最大返回条数。
        date_from: 起始日期（含），None 表示不限制。
        date_to: 结束日期（含），None 表示不限制。
        only_pending: 为 True 时只返回 time='待补' 的记录。
    """

    safe_limit = max(1, min(int(limit), 2000))
    conditions: list[str] = []
    params: list[Any] = []
    start = (date_from or "").strip()
    end = (date_to or "").strip()
    if start:
        conditions.append('"date" >= ?')
        params.append(start)
    if end:
        conditions.append('"date" <= ?')
        params.append(end)
    if only_pending:
        conditions.append('"time" = ?')
        params.append("待补")
    where_sql = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    params.append(safe_limit)

    with _connection() as connection:
        rows = connection.execute(
            'SELECT id, "date", "time", content, source, created_at '
            f"FROM schedules {where_sql}"
            "ORDER BY (\"date\" = '待补') ASC, "
            '"date" DESC, ("time" = \'待补\') ASC, "time" DESC, id DESC LIMIT ?',
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def list_schedule_rows(
    limit: int = 500,
    date_from: str | None = None,
    date_to: str | None = None,
    only_pending: bool = False,
) -> list[list[Any]]:
    """返回可直接给 gr.Dataframe 的二维表，支持与 list_schedules 相同的过滤。"""

    return [
        [
            item["id"],
            item["date"],
            item["time"],
            item["content"],
            item["source"],
            item["created_at"],
        ]
        for item in list_schedules(
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            only_pending=only_pending,
        )
    ]


def delete_schedule(schedule_id: int) -> bool:
    """按 ID 删除日程；不存在时返回 False，不抛错。"""

    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM schedules WHERE id = ?",
            (int(schedule_id),),
        )
        deleted = cursor.rowcount > 0
    if deleted:
        logger.info("日程已删除：id=%s", schedule_id)
    return deleted


def delete_schedules(schedule_ids: Sequence[int]) -> int:
    """批量删除日程，返回实际删除条数；空列表直接返回 0。"""

    ids = sorted({int(item) for item in schedule_ids if int(item) > 0})
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    with _connection() as connection:
        cursor = connection.execute(
            f"DELETE FROM schedules WHERE id IN ({placeholders})",
            tuple(ids),
        )
        deleted = cursor.rowcount
    logger.info("日程批量删除：请求=%s 实际=%s", len(ids), deleted)
    return max(0, deleted)


def delete_all_schedules() -> int:
    """清空全部日程，返回删除条数。"""

    with _connection() as connection:
        cursor = connection.execute("DELETE FROM schedules")
        deleted = cursor.rowcount
    logger.info("日程已清空：%s 条", deleted)
    return max(0, deleted)


def update_schedule(
    schedule_id: int,
    date: str | None = None,
    time: str | None = None,
    content: str | None = None,
) -> dict[str, Any] | None:
    """按 ID 更新日程的非 None 字段，返回更新后的完整行。

    Args:
        schedule_id: 日程 ID。
        date: 新日期；None 表示不修改，合法值经 normalize_date。
        time: 新时间；None 表示不修改，合法值经 normalize_time。
        content: 新事项；None 表示不修改，空字符串/纯空白抛 ValueError。

    Returns:
        更新后的完整行；ID 不存在时返回 None。

    Raises:
        ValueError: content 传入空字符串或纯空白。
    """

    updates: dict[str, Any] = {}
    if date is not None:
        updates['"date"'] = normalize_date(date)
    if time is not None:
        updates['"time"'] = normalize_time(time)
    if content is not None:
        clean_content = str(content).strip()
        if not clean_content:
            raise ValueError("日程事项不能为空。")
        updates["content"] = clean_content

    with _connection() as connection:
        exists = connection.execute(
            "SELECT id FROM schedules WHERE id = ?",
            (int(schedule_id),),
        ).fetchone()
        if exists is None:
            return None
        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            connection.execute(
                f"UPDATE schedules SET {assignments} WHERE id = ?",
                (*updates.values(), int(schedule_id)),
            )
        row = connection.execute(
            'SELECT id, "date", "time", content, source, created_at FROM schedules WHERE id = ?',
            (int(schedule_id),),
        ).fetchone()

    if row is None:
        return None
    logger.info("日程已更新：id=%s fields=%s", schedule_id, tuple(updates))
    return dict(row)


def bulk_create_schedules(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量导入日程；单条格式错误会跳过，不阻断其他记录。"""

    inserted: list[dict[str, Any]] = []
    for raw in records:
        try:
            inserted.append(
                create_schedule(
                    date=str(raw.get("date") or ""),
                    time=str(raw.get("time") or ""),
                    content=str(raw.get("content") or ""),
                    source=str(raw.get("source") or ""),
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning("跳过无效日程：%s，原因：%s", raw, exc)
    return inserted


def safe_create_schedule(
    date: str | None,
    time: str | None,
    content: str,
    source: str,
) -> dict[str, Any] | None:
    """写入日程但吞掉异常，供工具在主流程中做非阻断沉淀。"""

    try:
        return create_schedule(date=date, time=time, content=content, source=source)
    except Exception:  # noqa: BLE001 - 日程沉淀不能破坏主业务
        logger.exception("日程沉淀失败，source=%s", source)
        return None


def create_maintenance(
    location: str,
    issue: str,
    reporter: str = "",
    report_date: str = "",
    status: str = MAINTENANCE_STATUS_PENDING,
) -> dict[str, Any]:
    """写入一条后勤维修记录，返回入库后的完整字段。

    地点为空时记为“待补”；故障描述为空时拒绝写入，避免产生无意义记录。
    """

    clean_location = (location or "").strip() or "待补"
    clean_issue = (issue or "").strip()
    if not clean_issue:
        raise ValueError("故障描述不能为空。")
    clean_reporter = (reporter or "").strip() or "待补"
    clean_date = normalize_date(report_date)
    clean_status = (status or "").strip() or MAINTENANCE_STATUS_PENDING
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _connection() as connection:
        # 编号不依赖自增：删除后留下的空号优先回填，编号尽量连续。
        maintenance_id = _reusable_maintenance_id(connection)
        connection.execute(
            """
            INSERT INTO maintenance
                (id, location, issue, reporter, report_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                maintenance_id,
                clean_location,
                clean_issue,
                clean_reporter,
                clean_date,
                clean_status,
                created_at,
            ),
        )
        new_id = maintenance_id

    return {
        "id": new_id,
        "location": clean_location,
        "issue": clean_issue,
        "reporter": clean_reporter,
        "report_date": clean_date,
        "status": clean_status,
        "created_at": created_at,
    }


def list_maintenance() -> list[dict[str, Any]]:
    """读取全部维修记录，按地点 A-Z（英文忽略大小写）排序。"""

    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, location, issue, reporter, report_date, status, created_at
            FROM maintenance
            ORDER BY location COLLATE NOCASE ASC, report_date DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_maintenance_rows() -> list[list[Any]]:
    """把维修记录转换成 gr.Dataframe 需要的数组行。"""

    return [
        [
            item["id"],
            item["location"],
            item["issue"],
            item["reporter"],
            item["report_date"],
            item["status"],
            item["created_at"],
        ]
        for item in list_maintenance()
    ]


def count_maintenance_by_location() -> list[list[Any]]:
    """统计各地维修数量，结果按地点 A-Z 排序。"""

    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT location, COUNT(*) AS total
            FROM maintenance
            GROUP BY location
            ORDER BY location COLLATE NOCASE ASC
            """
        ).fetchall()
    return [[row["location"], int(row["total"])] for row in rows]


# ---------------------------------------------------------------------------
# 后勤全域数据：资产 / 库存 / 巡检 / 供应商 / 人员 / 反馈
# ---------------------------------------------------------------------------
def _normalize_status(value: str | None, allowed: Sequence[str], default: str) -> str:
    """把状态限制在常量枚举内；未知或空值回退默认值。"""

    clean = (value or "").strip()
    return clean if clean in allowed else default


def _now_text() -> str:
    """统一返回 YYYY-MM-DD HH:MM:SS 的入库时间。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_asset(
    name: str,
    asset_no: str = "",
    category: str = "",
    location: str = "",
    owner: str = "",
    status: str = "在用",
    purchase_date: str = "",
    warranty_until: str = "",
    last_check: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """新增资产/设备台账记录；资产编号可空，非空时唯一。"""

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("资产名称不能为空。")
    clean_no = (asset_no or "").strip()
    clean_status = _normalize_status(status, ASSET_STATUS_VALUES, "在用")
    created_at = _now_text()

    with _connection() as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO assets
                    (asset_no, name, category, location, owner, status,
                     purchase_date, warranty_until, last_check, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_no,
                    clean_name,
                    (category or "").strip(),
                    (location or "").strip(),
                    (owner or "").strip(),
                    clean_status,
                    (purchase_date or "").strip(),
                    (warranty_until or "").strip(),
                    (last_check or "").strip(),
                    (notes or "").strip(),
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"资产编号已存在：{clean_no}") from exc
        new_id = int(cursor.lastrowid or 0)

    return {
        "id": new_id,
        "asset_no": clean_no,
        "name": clean_name,
        "category": (category or "").strip(),
        "location": (location or "").strip(),
        "owner": (owner or "").strip(),
        "status": clean_status,
        "purchase_date": (purchase_date or "").strip(),
        "warranty_until": (warranty_until or "").strip(),
        "last_check": (last_check or "").strip(),
        "notes": (notes or "").strip(),
        "created_at": created_at,
    }


def list_assets(
    keyword: str = "",
    status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """按关键字/状态查询资产台账，按地点与名称排序。"""

    conditions: list[str] = []
    params: list[Any] = []
    clean_keyword = (keyword or "").strip()
    if clean_keyword:
        like = f"%{clean_keyword}%"
        conditions.append("(name LIKE ? OR asset_no LIKE ? OR location LIKE ? OR owner LIKE ?)")
        params.extend([like, like, like, like])
    if status:
        conditions.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    params.append(max(1, min(int(limit), 2000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, asset_no, name, category, location, owner, status, "
            "purchase_date, warranty_until, last_check, notes, created_at "
            f"FROM assets {where_sql}"
            "ORDER BY location COLLATE NOCASE ASC, name COLLATE NOCASE ASC, id DESC "
            "LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_inventory(
    item: str,
    quantity: float = 0,
    unit: str = "",
    category: str = "",
    reorder_level: float = 0,
    location: str = "",
    supplier: str = "",
) -> dict[str, Any]:
    """新增或按物资名称更新库存；数量低于补货线时由 list_low_stock 提醒。"""

    clean_item = (item or "").strip()
    if not clean_item:
        raise ValueError("物资名称不能为空。")
    try:
        clean_quantity = max(0.0, float(quantity))
        clean_reorder = max(0.0, float(reorder_level))
    except (TypeError, ValueError) as exc:
        raise ValueError("数量与补货线必须是数字。") from exc
    now = _now_text()

    with _connection() as connection:
        existing = connection.execute(
            "SELECT id FROM inventory WHERE item = ? COLLATE NOCASE",
            (clean_item,),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO inventory
                    (item, category, unit, quantity, reorder_level,
                     location, supplier, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_item,
                    (category or "").strip(),
                    (unit or "").strip(),
                    clean_quantity,
                    clean_reorder,
                    (location or "").strip(),
                    (supplier or "").strip(),
                    now,
                    now,
                ),
            )
            item_id = int(cursor.lastrowid or 0)
        else:
            item_id = int(existing["id"])
            connection.execute(
                """
                UPDATE inventory SET
                    category = ?, unit = ?, quantity = ?, reorder_level = ?,
                    location = ?, supplier = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    (category or "").strip(),
                    (unit or "").strip(),
                    clean_quantity,
                    clean_reorder,
                    (location or "").strip(),
                    (supplier or "").strip(),
                    now,
                    item_id,
                ),
            )
        row = connection.execute(
            "SELECT id, item, category, unit, quantity, reorder_level, "
            "location, supplier, updated_at, created_at FROM inventory WHERE id = ?",
            (item_id,),
        ).fetchone()
    return dict(row) if row else {}


def list_inventory(keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """查询物资库存，按分类与名称排序。"""

    conditions: list[str] = []
    params: list[Any] = []
    clean_keyword = (keyword or "").strip()
    if clean_keyword:
        like = f"%{clean_keyword}%"
        conditions.append("(item LIKE ? OR category LIKE ? OR supplier LIKE ?)")
        params.extend([like, like, like])
    where_sql = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    params.append(max(1, min(int(limit), 2000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, item, category, unit, quantity, reorder_level, "
            "location, supplier, updated_at, created_at "
            f"FROM inventory {where_sql}"
            "ORDER BY category COLLATE NOCASE ASC, item COLLATE NOCASE ASC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def list_low_stock() -> list[dict[str, Any]]:
    """返回已设置补货线且当前库存不高于补货线的物资。"""

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, item, category, unit, quantity, reorder_level, "
            "location, supplier, updated_at, created_at "
            "FROM inventory WHERE reorder_level > 0 AND quantity <= reorder_level "
            "ORDER BY category COLLATE NOCASE ASC, item COLLATE NOCASE ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_inspection(
    area: str,
    item: str,
    result: str = "正常",
    issue: str = "",
    inspector: str = "",
    inspect_date: str = "",
    status: str = "",
) -> dict[str, Any]:
    """新增后勤巡检记录；异常默认进入“待整改”，正常默认“已闭环”。"""

    clean_area = (area or "").strip()
    clean_item = (item or "").strip()
    if not clean_area:
        raise ValueError("巡检区域不能为空。")
    if not clean_item:
        raise ValueError("巡检项目不能为空。")
    clean_result = _normalize_status(result, INSPECTION_RESULT_VALUES, "正常")
    default_status = "已闭环" if clean_result == "正常" else "待整改"
    clean_status = _normalize_status(status, INSPECTION_STATUS_VALUES, default_status)
    clean_date = normalize_date(inspect_date)
    created_at = _now_text()

    with _connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO inspections
                (area, item, result, issue, inspector, inspect_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_area,
                clean_item,
                clean_result,
                (issue or "").strip(),
                (inspector or "").strip() or "待补",
                clean_date,
                clean_status,
                created_at,
            ),
        )
        new_id = int(cursor.lastrowid or 0)

    return {
        "id": new_id,
        "area": clean_area,
        "item": clean_item,
        "result": clean_result,
        "issue": (issue or "").strip(),
        "inspector": (inspector or "").strip() or "待补",
        "inspect_date": clean_date,
        "status": clean_status,
        "created_at": created_at,
    }


def list_inspections(
    keyword: str = "",
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """按区域/项目关键字查询巡检记录，按巡检日期倒序。"""

    conditions: list[str] = []
    params: list[Any] = []
    clean_keyword = (keyword or "").strip()
    if clean_keyword:
        like = f"%{clean_keyword}%"
        conditions.append("(area LIKE ? OR item LIKE ? OR issue LIKE ? OR inspector LIKE ?)")
        params.extend([like, like, like, like])
    if status:
        conditions.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    params.append(max(1, min(int(limit), 1000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, area, item, result, issue, inspector, inspect_date, status, created_at "
            f"FROM inspections {where_sql}"
            "ORDER BY inspect_date DESC, id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_supplier(
    name: str,
    category: str = "",
    contact: str = "",
    phone: str = "",
    license_until: str = "",
    rating: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """新增或按供应商名称更新档案。"""

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("供应商名称不能为空。")
    created_at = _now_text()

    with _connection() as connection:
        existing = connection.execute(
            "SELECT id FROM suppliers WHERE name = ? COLLATE NOCASE",
            (clean_name,),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO suppliers
                    (name, category, contact, phone, license_until, rating, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    (category or "").strip(),
                    (contact or "").strip(),
                    (phone or "").strip(),
                    (license_until or "").strip(),
                    (rating or "").strip(),
                    (notes or "").strip(),
                    created_at,
                ),
            )
            supplier_id = int(cursor.lastrowid or 0)
        else:
            supplier_id = int(existing["id"])
            connection.execute(
                """
                UPDATE suppliers SET
                    category = ?, contact = ?, phone = ?, license_until = ?,
                    rating = ?, notes = ?
                WHERE id = ?
                """,
                (
                    (category or "").strip(),
                    (contact or "").strip(),
                    (phone or "").strip(),
                    (license_until or "").strip(),
                    (rating or "").strip(),
                    (notes or "").strip(),
                    supplier_id,
                ),
            )
        row = connection.execute(
            "SELECT id, name, category, contact, phone, license_until, rating, notes, "
            "created_at FROM suppliers WHERE id = ?",
            (supplier_id,),
        ).fetchone()
    return dict(row) if row else {}


def list_suppliers(keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """查询供应商档案，按名称排序。"""

    clean_keyword = (keyword or "").strip()
    params: list[Any] = []
    where_sql = ""
    if clean_keyword:
        like = f"%{clean_keyword}%"
        where_sql = "WHERE name LIKE ? OR category LIKE ? OR contact LIKE ? "
        params.extend([like, like, like])
    params.append(max(1, min(int(limit), 2000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, name, category, contact, phone, license_until, rating, notes, "
            f"created_at FROM suppliers {where_sql}ORDER BY name COLLATE NOCASE ASC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def create_staff(
    name: str,
    role: str = "",
    department: str = "",
    health_cert_until: str = "",
    training_date: str = "",
    phone: str = "",
) -> dict[str, Any]:
    """新增后勤人员档案，用于健康证与培训到期提醒。"""

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("人员姓名不能为空。")
    created_at = _now_text()

    with _connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO staff
                (name, role, department, health_cert_until, training_date, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_name,
                (role or "").strip(),
                (department or "").strip(),
                (health_cert_until or "").strip(),
                (training_date or "").strip(),
                (phone or "").strip(),
                created_at,
            ),
        )
        new_id = int(cursor.lastrowid or 0)

    return {
        "id": new_id,
        "name": clean_name,
        "role": (role or "").strip(),
        "department": (department or "").strip(),
        "health_cert_until": (health_cert_until or "").strip(),
        "training_date": (training_date or "").strip(),
        "phone": (phone or "").strip(),
        "created_at": created_at,
    }


def list_staff(keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """查询后勤人员档案，按部门与姓名排序。"""

    clean_keyword = (keyword or "").strip()
    params: list[Any] = []
    where_sql = ""
    if clean_keyword:
        like = f"%{clean_keyword}%"
        where_sql = "WHERE name LIKE ? OR role LIKE ? OR department LIKE ? "
        params.extend([like, like, like])
    params.append(max(1, min(int(limit), 2000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, name, role, department, health_cert_until, training_date, phone, "
            f"created_at FROM staff {where_sql}"
            "ORDER BY department COLLATE NOCASE ASC, name COLLATE NOCASE ASC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def create_feedback(
    content: str,
    channel: str = "",
    category: str = "",
    handler: str = "",
    rating: int | None = None,
    status: str = "待处理",
) -> dict[str, Any]:
    """新增师生/教职工后勤反馈，默认待处理。"""

    clean_content = (content or "").strip()
    if not clean_content:
        raise ValueError("反馈内容不能为空。")
    clean_status = _normalize_status(status, FEEDBACK_STATUS_VALUES, "待处理")
    clean_rating: int | None = None
    if rating is not None:
        try:
            clean_rating = max(1, min(int(rating), 5))
        except (TypeError, ValueError):
            clean_rating = None
    created_at = _now_text()

    with _connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO feedback
                (channel, category, content, handler, rating, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (channel or "").strip(),
                (category or "").strip(),
                clean_content,
                (handler or "").strip(),
                clean_rating,
                clean_status,
                created_at,
            ),
        )
        new_id = int(cursor.lastrowid or 0)

    return {
        "id": new_id,
        "channel": (channel or "").strip(),
        "category": (category or "").strip(),
        "content": clean_content,
        "handler": (handler or "").strip(),
        "rating": clean_rating,
        "status": clean_status,
        "created_at": created_at,
    }


def list_feedback(
    status: str | None = None,
    keyword: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """查询后勤反馈，按创建时间倒序。"""

    conditions: list[str] = []
    params: list[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    clean_keyword = (keyword or "").strip()
    if clean_keyword:
        like = f"%{clean_keyword}%"
        conditions.append("(content LIKE ? OR category LIKE ? OR handler LIKE ?)")
        params.extend([like, like, like])
    where_sql = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    params.append(max(1, min(int(limit), 1000)))

    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, channel, category, content, handler, rating, status, created_at "
            f"FROM feedback {where_sql}ORDER BY created_at DESC, id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def logistics_overview() -> dict[str, int]:
    """返回后勤各数据表记录数，供助手概览与设置区展示。"""

    tables = (
        "maintenance",
        "assets",
        "inventory",
        "inspections",
        "suppliers",
        "staff",
        "feedback",
        "schedules",
    )
    with _connection() as connection:
        return {
            name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            for name in tables
        }


_ALL_DATA_TABLES: tuple[str, ...] = (
    "records",
    "schedules",
    "maintenance",
    "assets",
    "inventory",
    "inspections",
    "suppliers",
    "staff",
    "feedback",
)


def reset_all_data() -> dict[str, int]:
    """清空全部业务数据表，返回每张表被删除前的记录数（用于 Agent 初始化）。"""

    counts: dict[str, int] = {}
    with _connection() as connection:
        for name in _ALL_DATA_TABLES:
            counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            connection.execute(f"DELETE FROM {name}")
    logger.warning("已清空本地业务数据：%s", counts)
    return counts


def delete_maintenance(maintenance_id: int) -> bool:
    """按 ID 删除维修记录；不存在时返回 False。"""

    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM maintenance WHERE id = ?",
            (int(maintenance_id),),
        )
        return cursor.rowcount > 0


def delete_maintenance_records(maintenance_ids: Sequence[int]) -> int:
    """批量删除维修记录，返回实际删除条数；空列表直接返回 0。"""

    ids = sorted({int(item) for item in maintenance_ids if int(item) > 0})
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    with _connection() as connection:
        cursor = connection.execute(
            f"DELETE FROM maintenance WHERE id IN ({placeholders})",
            tuple(ids),
        )
        deleted = cursor.rowcount
    logger.info("维修记录批量删除：请求=%s 实际=%s", len(ids), deleted)
    return max(0, deleted)


def delete_all_maintenance() -> int:
    """清空全部维修记录，返回删除条数。"""

    with _connection() as connection:
        cursor = connection.execute("DELETE FROM maintenance")
        deleted = cursor.rowcount
    logger.info("维修记录已清空：%s 条", deleted)
    return max(0, deleted)


def save_record(
    kind: str,
    title: str,
    payload: dict[str, Any],
    source: str = "",
    schedule_id: int | None = None,
) -> int:
    """写入一条工具完整草稿记录并返回记录 ID。

    Args:
        kind: 记录类型，建议取 constants.py 的 RECORD_KIND_*。
        title: 可读标题。
        payload: 完整工具返回字典。
        source: 可选来源说明。
        schedule_id: 关联日程 ID，可为 None。

    Returns:
        records.id。

    Raises:
        ValueError: payload 不是 dict。
        RuntimeError: 插入后未取得有效 ID。
    """

    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict。")
    if kind not in RECORD_KIND_VALUES:
        logger.warning("未知记录类型：%s；按原值写入。", kind)

    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connection() as connection:
        cursor = connection.execute(
            "INSERT INTO records (kind, title, source, schedule_id, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(kind),
                str(title),
                str(source or ""),
                schedule_id,
                payload_json,
                created_at,
            ),
        )
        record_id = cursor.lastrowid

    if record_id is None or int(record_id) <= 0:
        raise RuntimeError("records 插入后未取得有效 ID。")
    logger.info("历史留痕已写入：id=%s kind=%s", record_id, kind)
    return int(record_id)


def safe_save_record(
    kind: str,
    title: str,
    payload: dict[str, Any],
    source: str = "",
    schedule_id: int | None = None,
) -> int | None:
    """写入 records，但吞掉异常，绝不影响主业务返回。"""

    try:
        return save_record(
            kind=kind,
            title=title,
            payload=payload,
            source=source,
            schedule_id=schedule_id,
        )
    except Exception:  # noqa: BLE001 - 留痕失败不能破坏工具结果
        logger.exception("历史留痕写入失败，kind=%s", kind)
        return None


def _record_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """把 records 行转换为含 payload 的字典。"""

    item = dict(row)
    raw_payload = item.get("payload_json")
    try:
        parsed = json.loads(str(raw_payload or "{}"))
        item["payload"] = parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        logger.warning("记录 %s 的 payload_json 无法解析。", item.get("id"))
        item["payload"] = {}
    return item


def list_records(kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """按创建时间倒序查询历史留痕，并把 payload_json 解析到 payload。"""

    safe_limit = max(1, min(int(limit), 500))
    with _connection() as connection:
        if kind:
            rows = connection.execute(
                "SELECT id, kind, title, source, schedule_id, payload_json, created_at "
                "FROM records WHERE kind = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (kind, safe_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, kind, title, source, schedule_id, payload_json, created_at "
                "FROM records ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
    return [_record_row_to_dict(row) for row in rows]


def get_record(record_id: int) -> dict[str, Any] | None:
    """按 ID 读取一条历史留痕，不存在时返回 None。"""

    with _connection() as connection:
        row = connection.execute(
            "SELECT id, kind, title, source, schedule_id, payload_json, created_at "
            "FROM records WHERE id = ?",
            (int(record_id),),
        ).fetchone()
    return _record_row_to_dict(row) if row is not None else None
