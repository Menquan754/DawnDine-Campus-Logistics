"""SQLite 本地日程库。

本文件职责：
- 初始化 data/dawndine.db 与 schedules 表；
- 提供日程新增、批量导入、倒序查询、Dataframe 行转换；
- 为台账、异常、水印、对话和图片导入提供统一的日程沉淀入口。

依赖：constants.py、sqlite3。
被调用：tools/schedule.py、tools/ledger.py、tools/abnormal.py、
        tools/watermark.py、modules/vision.py、app.py、main.py。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from constants import (
    DB_PATH,
    SCHEDULE_SOURCE_CHAT,
    SCHEDULE_SOURCE_VALUES,
)

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
    logger.info("日程数据库就绪：%s", DB_PATH)


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
        cursor = connection.execute(
            'INSERT INTO schedules ("date", "time", content, source, created_at) '
            "VALUES (?, ?, ?, ?, ?)",
            (
                normalized_date,
                normalized_time,
                clean_content,
                normalized_source,
                created_at,
            ),
        )
        schedule_id = int(cursor.lastrowid or 0)

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


def list_schedules(limit: int = 500) -> list[dict[str, Any]]:
    """按日期、时间倒序返回日程。"""

    safe_limit = max(1, min(int(limit), 2000))
    with _connection() as connection:
        rows = connection.execute(
            'SELECT id, "date", "time", content, source, created_at '
            "FROM schedules ORDER BY (\"date\" = '待补') ASC, "
            '"date" DESC, ("time" = \'待补\') ASC, "time" DESC, id DESC LIMIT ?',
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_schedule_rows(limit: int = 500) -> list[list[Any]]:
    """返回可直接给 gr.Dataframe 的二维表。"""

    return [
        [
            item["id"],
            item["date"],
            item["time"],
            item["content"],
            item["source"],
            item["created_at"],
        ]
        for item in list_schedules(limit=limit)
    ]


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
