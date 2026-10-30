"""水印内容栏测试：两栏独立位置、顺序堆叠、占位符与清除还原。"""

from __future__ import annotations

from dawndine.services.watermark import (
    apply_style_overrides,
    apply_watermark_columns,
    describe_template_style,
    parse_column_lines,
    plan_watermark_blocks,
)

WIDTH = 800
HEIGHT = 1200


def _template() -> dict:
    return {
        "fixed_elements": [
            {
                "text": "校园食堂陪餐",
                "role": "title",
                "font_size": 24,
                "color": "#FFFFFF",
                "bg_color": "#0B6E4F",
                "bg_opacity": 190,
                "x_norm": 0.035,
                "y_norm": 0.035,
            },
            {
                "text": "地点：{location}",
                "role": "location",
                "font_size": 20,
                "color": "#FFFFFF",
                "bg_color": "#0B6E4F",
                "bg_opacity": 190,
                "x_norm": 0.035,
                "y_norm": 0.1,
            },
        ],
        "dynamic_vars": {
            "date": {"x_norm": 0.035, "y_norm": 0.78, "font_size": 20},
            "time": {"x_norm": 0.035, "y_norm": 0.84, "font_size": 20},
            "anti_counterfeit": {"x_norm": 0.035, "y_norm": 0.9, "font_size": 20},
        },
        "meta": {},
    }


def _variables() -> dict[str, str]:
    return {
        "location": "第一食堂",
        "date": "2026.10.28 星期三",
        "date_only": "2026.10.28",
        "date_iso": "2026-10-28",
        "time": "12:10",
        "weekday": "星期三",
        "anti_counterfeit": "ABCD1234",
    }


def test_parse_column_lines_keeps_order_and_strips_bullets() -> None:
    lines = parse_column_lines("1. 校园食堂陪餐\n- 地点：{location}\n\n  {date} {time} ")

    assert lines == ["校园食堂陪餐", "地点：{location}", "{date} {time}"]


def test_columns_replace_content_and_stack_top_down() -> None:
    template = apply_watermark_columns(
        _template(),
        [{"anchor": "bottom-left", "text": "第一行\n第二行\n第三行"}],
    )

    assert [element["text"] for element in template["fixed_elements"]] == [
        "第一行",
        "第二行",
        "第三行",
    ]
    assert template["dynamic_vars"] == {}
    assert template["meta"]["columns"][0]["anchor"] == "bottom-left"

    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)
    ys = [block["y"] for block in blocks]
    assert ys == sorted(ys)
    assert all(block["x"] < WIDTH / 2 for block in blocks)


def test_two_columns_use_independent_positions() -> None:
    template = apply_watermark_columns(
        _template(),
        [
            {"anchor": "top-left", "text": "左一\n左二"},
            {"anchor": "top-right", "text": "右一\n右二"},
        ],
    )
    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)
    left = [block for block in blocks if block["text"].startswith("左")]
    right = [block for block in blocks if block["text"].startswith("右")]

    assert len(left) == 2 and len(right) == 2
    assert all(block["x"] < WIDTH / 2 for block in left)
    assert all(block["x"] + block["width"] > WIDTH / 2 for block in right)
    assert left[0]["y"] < left[1]["y"]
    assert right[0]["y"] < right[1]["y"]


def test_columns_combine_with_style_overrides_and_placeholders() -> None:
    template = apply_style_overrides(
        _template(),
        {
            "columns": [
                {
                    "anchor": "bottom-right",
                    "text": "地点：{location}\n{date} {time}\n防伪：{anti_counterfeit}",
                }
            ],
            "font_scale": 1.5,
            "color": "#FFD54A",
            "bg_color": "#111111",
        },
    )

    assert [element["text"] for element in template["fixed_elements"]] == [
        "地点：{location}",
        "{date} {time}",
        "防伪：{anti_counterfeit}",
    ]
    first = template["fixed_elements"][0]
    assert first["font_size"] == 36
    assert first["color"] == "#FFD54A"
    assert first["bg_color"] == "#111111"
    assert template["dynamic_vars"] == {}

    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)
    assert blocks[0]["text"] == "地点：第一食堂"
    assert blocks[1]["text"] == "2026.10.28 星期三 12:10"
    assert blocks[2]["text"] == "防伪：ABCD1234"


def test_columns_flat_keys_are_supported() -> None:
    template = apply_style_overrides(
        _template(),
        {
            "left_content": "左侧标题",
            "left_anchor": "bottom-left",
            "right_content": "右侧标题",
            "right_anchor": "bottom-right",
        },
    )

    anchors = [element["anchor"] for element in template["fixed_elements"]]
    assert anchors == ["bottom-left", "bottom-right"]
    assert [element["text"] for element in template["fixed_elements"]] == [
        "左侧标题",
        "右侧标题",
    ]


def test_clear_columns_restores_original_content() -> None:
    templated = apply_watermark_columns(
        _template(),
        [{"anchor": "top-left", "text": "临时内容"}],
    )
    restored = apply_watermark_columns(templated, [])

    assert [element["text"] for element in restored["fixed_elements"]] == [
        "校园食堂陪餐",
        "地点：{location}",
    ]
    assert set(restored["dynamic_vars"]) == {"date", "time", "anti_counterfeit"}
    assert "columns" not in restored["meta"]
    assert "content_backup" not in restored["meta"]


def test_clear_columns_on_plain_template_is_noop() -> None:
    template = apply_watermark_columns(_template(), [])
    assert [element["text"] for element in template["fixed_elements"]] == [
        "校园食堂陪餐",
        "地点：{location}",
    ]
    assert set(template["dynamic_vars"]) == {"date", "time", "anti_counterfeit"}


def test_describe_template_style_reports_columns() -> None:
    template = apply_watermark_columns(
        _template(),
        [
            {"anchor": "bottom-left", "text": "左一\n左二\n左三"},
            {"anchor": "top-right", "text": "右一"},
        ],
    )
    summary = describe_template_style(template)

    assert "内容栏" in summary
    assert "左下角 3 行" in summary
    assert "右上角 1 行" in summary
