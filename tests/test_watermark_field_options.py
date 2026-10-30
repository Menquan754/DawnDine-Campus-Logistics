"""水印“使用地点/时间”与内容栏绑定测试。"""

from __future__ import annotations

from dawndine.services.watermark import (
    attach_column_lines,
    plan_watermark_blocks,
)

WIDTH = 800
HEIGHT = 1200


def _template() -> dict:
    return {
        "fixed_elements": [
            {"text": "校园食堂陪餐", "role": "title", "font_size": 24},
            {"text": "地点：{location}", "role": "location", "font_size": 20},
        ],
        "dynamic_vars": {
            "date": {"font_size": 20},
            "time": {"font_size": 20},
            "anti_counterfeit": {"font_size": 20},
        },
        "meta": {},
    }


def _variables() -> dict[str, str]:
    return {
        "location": "第一食堂",
        "date": "2026.10.28 星期三",
        "time": "12:10",
        "anti_counterfeit": "ABCD1234",
    }


def _texts(omitted: frozenset[str] = frozenset()) -> list[str]:
    blocks = plan_watermark_blocks(_template(), _variables(), WIDTH, HEIGHT, omitted)
    return [str(block["text"]) for block in blocks]


def test_omitting_location_drops_location_line() -> None:
    texts = _texts(frozenset({"location"}))

    assert "校园食堂陪餐" in texts
    assert not any("地点" in text for text in texts)
    assert any("2026.10.28" in text for text in texts)


def test_omitting_time_drops_date_and_time_blocks() -> None:
    texts = _texts(frozenset({"time"}))

    assert "地点：第一食堂" in texts
    assert not any("2026.10.28" in text for text in texts)
    assert not any("12:10" in text for text in texts)
    # 防伪码不受时间勾选影响。
    assert any("ABCD1234" in text for text in texts)


def test_column_lines_with_placeholders_follow_omissions() -> None:
    template = {
        "fixed_elements": [
            {"text": "地点：{location}", "anchor": "bottom-left"},
            {"text": "{date} {time}", "anchor": "bottom-left"},
            {"text": "陪餐人：张三", "anchor": "bottom-left"},
        ],
        "dynamic_vars": {},
        "meta": {},
    }
    blocks = plan_watermark_blocks(
        template,
        _variables(),
        WIDTH,
        HEIGHT,
        frozenset({"location", "time"}),
    )

    assert [block["text"] for block in blocks] == ["陪餐人：张三"]


def test_attach_column_lines_appends_to_bottom() -> None:
    columns = [
        {"anchor": "bottom-left", "text": "标题\n第一行"},
        {"anchor": "bottom-right", "text": "右一"},
    ]
    merged = attach_column_lines(columns, ["地点：{location}", "{date} {time}"], 1, "bottom")

    assert merged is not None
    assert merged[0]["text"] == "标题\n第一行\n地点：{location}\n{date} {time}"
    assert merged[1]["text"] == "右一"
    # 原列表不应被就地修改。
    assert columns[0]["text"] == "标题\n第一行"


def test_attach_column_lines_prepends_to_top_of_second_column() -> None:
    columns = [
        {"anchor": "bottom-left", "text": "左一"},
        {"anchor": "bottom-right", "text": "右一\n右二"},
    ]
    merged = attach_column_lines(columns, ["地点：{location}"], 2, "top")

    assert merged is not None
    assert merged[0]["text"] == "左一"
    assert merged[1]["text"] == "地点：{location}\n右一\n右二"


def test_attach_column_lines_falls_back_to_last_column() -> None:
    columns = [{"anchor": "bottom-left", "text": "唯一一栏"}]
    merged = attach_column_lines(columns, ["地点：{location}"], 2, "bottom")

    assert merged is not None
    assert merged[0]["text"] == "唯一一栏\n地点：{location}"


def test_attach_column_lines_without_columns_returns_none() -> None:
    assert attach_column_lines(None, ["地点：{location}"], 1, "bottom") is None
    assert attach_column_lines([], ["地点：{location}"], 1, "bottom") is None
    assert attach_column_lines([{"anchor": "bottom-left", "text": "左一"}], [], 1, "top") is None
