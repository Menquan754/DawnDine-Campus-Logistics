"""后勤全域数据库与查询工具的回归测试。"""

from __future__ import annotations

import pytest

from dawndine.agent.tools.logistics import query_logistics_records
from dawndine.db import (
    create_asset,
    create_feedback,
    create_inspection,
    create_maintenance,
    create_staff,
    list_assets,
    list_feedback,
    list_inspections,
    list_inventory,
    list_low_stock,
    list_maintenance,
    logistics_overview,
    upsert_inventory,
    upsert_supplier,
)


def test_asset_create_and_sort(tmp_db: None) -> None:
    create_asset("空调", asset_no="A-002", location="教学楼B", owner="李工")
    create_asset("投影仪", asset_no="A-001", location="教学楼A", owner="王老师")
    create_asset("闲置投影仪", location="教学楼A", status="闲置")

    rows = list_assets()

    assert [row["name"] for row in rows] == ["投影仪", "闲置投影仪", "空调"]
    assert rows[1]["status"] == "闲置"
    with pytest.raises(ValueError):
        create_asset("重复编号", asset_no="A-001")


def test_inventory_upsert_and_low_stock(tmp_db: None) -> None:
    upsert_inventory("84 消毒液", quantity=12, unit="瓶", reorder_level=10, location="库房")
    updated = upsert_inventory(
        "84 消毒液",
        quantity=5,
        unit="瓶",
        reorder_level=10,
        location="库房",
        supplier="校采",
    )

    assert updated["id"] > 0
    assert updated["quantity"] == 5
    assert len(list_inventory()) == 1
    low = list_low_stock()
    assert len(low) == 1
    assert low[0]["item"] == "84 消毒液"


def test_inspection_default_status(tmp_db: None) -> None:
    abnormal = create_inspection("三号宿舍楼", "热水管", result="异常", issue="接口渗水")
    normal = create_inspection("教学楼A", "照明", result="正常")

    assert abnormal["status"] == "待整改"
    assert normal["status"] == "已闭环"
    assert len(list_inspections()) == 2
    assert list_inspections(status="待整改")[0]["issue"] == "接口渗水"


def test_supplier_staff_feedback_and_overview(tmp_db: None) -> None:
    upsert_supplier("洁美保洁", category="保洁耗材", contact="张经理")
    upsert_supplier("洁美保洁", category="保洁耗材", contact="张经理", rating="A")
    create_staff("陈师傅", role="电工", department="后勤维修")
    create_feedback("三楼热水不热", category="宿舍", rating=7)
    create_maintenance("三号宿舍楼", "热水不热", reporter="宿管")

    counts = logistics_overview()
    assert counts["suppliers"] == 1
    assert counts["staff"] == 1
    assert counts["feedback"] == 1
    assert counts["maintenance"] == 1
    assert counts["assets"] == 0

    feedback = list_feedback()
    assert feedback[0]["rating"] == 5  # 评分超出 1—5 时收敛到边界
    assert len(list_maintenance()) == 1


def test_query_tool_overview_and_filter(tmp_db: None) -> None:
    create_maintenance("第二食堂", "蒸箱漏气", reporter="张师傅")
    create_maintenance("教学楼A", "走廊灯不亮", reporter="王老师")
    upsert_inventory("尘推", quantity=2, unit="把", reorder_level=5)

    overview = query_logistics_records.invoke({"kind": "概览"})
    assert overview["ok"] is True
    assert overview["kind"] == "overview"
    assert overview["counts"]["maintenance"] == 2

    filtered = query_logistics_records.invoke(
        {"kind": "维修记录", "keyword": "食堂", "limit": 5}
    )
    assert filtered["ok"] is True
    assert filtered["total"] == 1
    assert "第二食堂" in filtered["summary"]

    low = query_logistics_records.invoke({"kind": "库存预警"})
    assert low["ok"] is True
    assert "尘推" in low["summary"]
