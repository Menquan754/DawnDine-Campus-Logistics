"""水印模板自然语言位置解析测试。"""

from __future__ import annotations

from dawndine.services.watermark import apply_layout_requirement, build_template_from_analysis


def _template() -> dict:
    return {
        "fixed_elements": [
            {"role": "title", "text": "标题", "x_norm": 0.035, "y_norm": 0.035},
            {"role": "location", "text": "地点：{location}", "x_norm": 0.035, "y_norm": 0.115},
        ],
        "dynamic_vars": {
            "date": {"x_norm": 0.035, "y_norm": 0.775},
            "time": {"x_norm": 0.035, "y_norm": 0.835},
            "anti_counterfeit": {"x_norm": 0.035, "y_norm": 0.895},
        },
        "meta": {"sample_note": ""},
    }


def test_layout_all_bottom_right() -> None:
    result = apply_layout_requirement(_template(), "水印放最右下角")
    assert result["fixed_elements"][0]["anchor"] == "bottom-right"
    assert result["fixed_elements"][0]["x_norm"] == 0.965
    assert result["dynamic_vars"]["time"]["anchor"] == "bottom-right"
    assert "已按描述调整水印位置" in result["meta"]["sample_note"]


def test_layout_target_specific() -> None:
    result = apply_layout_requirement(_template(), "标题放右上角，日期和时间放左下角")
    assert result["fixed_elements"][0]["anchor"] == "top-right"
    assert result["fixed_elements"][0]["x_norm"] == 0.965
    assert result["dynamic_vars"]["date"]["anchor"] == "bottom-left"
    assert result["dynamic_vars"]["time"]["anchor"] == "bottom-left"
    assert result["dynamic_vars"]["anti_counterfeit"].get("anchor") is None


def test_layout_group_and_negative_clause() -> None:
    result = apply_layout_requirement(
        _template(),
        "不要挡住中间，日期、时间、防伪码放右下角",
    )
    assert result["dynamic_vars"]["date"]["anchor"] == "bottom-right"
    assert result["dynamic_vars"]["time"]["anchor"] == "bottom-right"
    assert result["dynamic_vars"]["anti_counterfeit"]["anchor"] == "bottom-right"
    assert result["fixed_elements"][0].get("anchor") is None
    assert result["fixed_elements"][0]["x_norm"] == 0.035


def test_layout_tight_spacing_requirement() -> None:
    result = apply_layout_requirement(_template(), "日期、时间、防伪码放右下角，元素紧靠在一起")
    assert result["meta"]["layout_gap"] == 2
    assert result["dynamic_vars"]["date"]["anchor"] == "bottom-right"


def test_layout_no_requirement_keeps_template() -> None:
    original = _template()
    result = apply_layout_requirement(original, "")
    assert result == original
    assert result is not original


def test_build_template_applies_requirement() -> None:
    analysis = _template()
    analysis["canvas"] = {"width": 1080, "height": 1920}
    template = build_template_from_analysis(
        analysis,
        template_name="layout_demo",
        user_requirement="水印放在最右下角",
    )
    assert template["fixed_elements"][0]["anchor"] == "bottom-right"
    assert template["dynamic_vars"]["time"]["anchor"] == "bottom-right"
    assert "已按描述调整水印位置" in template["meta"]["sample_note"]


def test_layout_user_request_with_colors_and_targets() -> None:
    result = apply_layout_requirement(
        _template(),
        "左下角显示打卡时间、深蓝色底色、白色文字，带上防伪编码，"
        "最右下角带上校园食堂陪餐，地点信息等",
    )
    title = result["fixed_elements"][0]
    location = result["fixed_elements"][1]
    date = result["dynamic_vars"]["date"]
    time = result["dynamic_vars"]["time"]
    anti = result["dynamic_vars"]["anti_counterfeit"]

    assert title["anchor"] == "bottom-right"
    assert location["anchor"] == "bottom-right"
    assert date["anchor"] == "bottom-left"
    assert time["anchor"] == "bottom-left"
    assert anti["anchor"] == "bottom-left"
    assert title["color"] == "#FFFFFF"
    assert title["bg_color"] == "#0B2E4F"
    assert time["color"] == "#FFFFFF"
    assert time["bg_color"] == "#0B2E4F"
