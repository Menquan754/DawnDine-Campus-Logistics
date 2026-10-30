"""水印格式、位置、字号与日期时间格式测试。"""

from __future__ import annotations

import json
from pathlib import Path

from dawndine.agent.tools.watermark import update_template_style
from dawndine.services.watermark import (
    ANCHOR_VALUES,
    apply_style_overrides,
    apply_watermark_format,
    build_dynamic_vars,
    describe_template_style,
    plan_watermark_blocks,
)

WIDTH = 400
HEIGHT = 800


def _template() -> dict:
    def element(text: str, role: str | None = None, anchor: str = "bottom-right") -> dict:
        item = {
            "text": text,
            "x_norm": 0.35,
            "y_norm": 0.35,
            "anchor": anchor,
            "font_size": 32,
            "color": "#FFFFFF",
            "bg_color": "#0B6E4F",
        }
        if role:
            item["role"] = role
        return item

    return {
        "fixed_elements": [
            element("校园食堂陪餐", role="title"),
            element("地点：第一食堂", role="location"),
        ],
        "dynamic_vars": {
            "date": element("2026.10.28 星期三"),
            "time": element("12:10"),
            "anti_counterfeit": element("ABCD1234"),
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


def test_center_anchors_are_supported() -> None:
    assert "top-center" in ANCHOR_VALUES
    assert "bottom-center" in ANCHOR_VALUES


def test_top_center_group_is_horizontally_centered() -> None:
    template = apply_style_overrides(_template(), {"anchor": "top-center"})
    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)

    for block in blocks:
        assert abs((block["x"] + block["width"] / 2) - WIDTH / 2) <= 1
    assert min(block["y"] for block in blocks) == 8


def test_format_compact_removes_location_and_anti() -> None:
    template = apply_watermark_format(_template(), "compact")

    roles = [element.get("role") for element in template["fixed_elements"]]
    assert roles == ["title"]
    assert set(template["dynamic_vars"]) == {"date", "time"}
    assert template["meta"]["format"] == "compact"


def test_format_datetime_keeps_only_date_and_time() -> None:
    template = apply_watermark_format(_template(), "datetime")

    assert template["fixed_elements"] == []
    assert set(template["dynamic_vars"]) == {"date", "time"}
    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)
    assert len(blocks) == 2


def test_format_full_keeps_everything() -> None:
    template = apply_watermark_format(_template(), "full")

    assert len(template["fixed_elements"]) == 2
    assert set(template["dynamic_vars"]) == {"date", "time", "anti_counterfeit"}


def test_style_overrides_combine_format_size_color_and_anchor() -> None:
    template = apply_style_overrides(
        _template(),
        {
            "format": "standard",
            "anchor": "bottom-left",
            "font_scale": 1.5,
            "color": "#FFD54A",
            "bg_color": "#111111",
            "bg_opacity": 160,
            "layout_gap": 2,
            "date_format": "cn",
            "time_format": "hms",
        },
    )

    assert set(template["dynamic_vars"]) == {"date", "time"}
    assert template["meta"]["layout_gap"] == 2
    assert template["meta"]["date_format"] == "cn"
    assert template["meta"]["time_format"] == "hms"
    first = template["fixed_elements"][0]
    assert first["anchor"] == "bottom-left"
    assert first["color"] == "#FFD54A"
    assert first["bg_color"] == "#111111"
    assert first["bg_opacity"] == 160
    assert first["font_size"] == 48


def test_build_dynamic_vars_respects_date_and_time_formats() -> None:
    variables = build_dynamic_vars(
        "第一食堂",
        manual_time="2026-10-28 14:30",
        date_format="cn",
        time_format="hms",
    )

    assert variables["date"].startswith("2026年10月28日")
    assert variables["time"] == "14:30:00"
    assert variables["date_iso"] == "2026-10-28"

    short = build_dynamic_vars("第一食堂", "2026-10-28 14:30", date_format="short")
    assert short["date"].startswith("10-28")


def test_format_switch_is_reversible() -> None:
    compact = apply_style_overrides(_template(), {"format": "compact"})
    assert set(compact["dynamic_vars"]) == {"date", "time"}

    restored = apply_style_overrides(compact, {"format": "full"})
    assert [element.get("role") for element in restored["fixed_elements"]] == [
        "title",
        "location",
    ]
    assert set(restored["dynamic_vars"]) == {"date", "time", "anti_counterfeit"}


def test_repeated_font_scale_does_not_compound() -> None:
    once = apply_style_overrides(_template(), {"font_scale": 1.5})
    twice = apply_style_overrides(once, {"font_scale": 1.5})

    assert once["fixed_elements"][0]["font_size"] == 48
    assert twice["fixed_elements"][0]["font_size"] == 48
    assert twice["dynamic_vars"]["date"]["font_size"] == 48


def test_font_scale_keeps_hidden_elements_consistent() -> None:
    compact = apply_style_overrides(_template(), {"format": "compact", "font_scale": 1.5})
    restored = apply_style_overrides(compact, {"format": "full"})

    # 切换到简洁格式时隐藏的地点、防伪码，也应按同一倍率缩放后再回来。
    assert restored["fixed_elements"][1]["font_size"] == 48
    assert restored["dynamic_vars"]["anti_counterfeit"]["font_size"] == 48


def test_describe_template_style_summarizes_controls() -> None:
    template = apply_style_overrides(
        _template(),
        {"format": "standard", "anchor": "bottom-left", "font_scale": 1.5, "date_format": "cn"},
    )
    summary = describe_template_style(template)

    assert "内容：标准" in summary
    assert "位置：左下角" in summary
    assert "字号：48" in summary
    assert "2026年10月28日" in summary


def test_update_template_style_persists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    template_file = tmp_path / "templates.json"
    monkeypatch.setattr("dawndine.services.watermark_store.TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr("dawndine.services.watermark_store.TEMPLATE_FILE", template_file)
    template_file.write_text(
        json.dumps({"demo": _template()}, ensure_ascii=False),
        encoding="utf-8",
    )

    updated = update_template_style(
        "demo",
        {"format": "location_time", "anchor": "top-center", "font_scale": 1.25},
    )

    assert updated is not None
    assert updated["meta"]["format"] == "location_time"
    assert [element.get("role") for element in updated["fixed_elements"]] == ["location"]
    assert updated["fixed_elements"][0]["anchor"] == "top-center"
    assert "updated_at" in updated

    saved = json.loads(template_file.read_text(encoding="utf-8"))
    assert saved["demo"]["meta"]["format"] == "location_time"
    assert update_template_style("missing", {"font_scale": 1.2}) is None
