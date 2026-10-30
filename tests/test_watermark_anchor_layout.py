"""水印四角贴边与紧凑堆叠的像素布局测试。"""

from __future__ import annotations

from dawndine.services.watermark import plan_watermark_blocks

WIDTH = 400
HEIGHT = 800
MARGIN = 8
GAP = 2


def _template(anchor: str | None = "bottom-right", *, x: float = 0.035, y: float = 0.775) -> dict:
    def element(text: str, **extra: object) -> dict:
        item = {"text": text, "x_norm": x, "y_norm": y}
        if anchor is not None:
            item["anchor"] = anchor
        item.update(extra)
        return item

    return {
        "fixed_elements": [
            element("校园食堂陪餐", role="title"),
            element("地点：第一食堂"),
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


def _sorted_blocks(blocks: list[dict]) -> list[dict]:
    return sorted(blocks, key=lambda block: (block["y"], block["x"]))


def test_bottom_right_group_is_flush_and_tight() -> None:
    blocks = _sorted_blocks(plan_watermark_blocks(_template(), _variables(), WIDTH, HEIGHT))

    assert len(blocks) == 5
    for block in blocks:
        assert block["x"] + block["width"] == WIDTH - MARGIN
    for upper, lower in zip(blocks, blocks[1:], strict=False):
        assert lower["y"] - (upper["y"] + upper["height"]) == GAP
    assert blocks[-1]["y"] + blocks[-1]["height"] == HEIGHT - MARGIN


def test_top_left_group_is_flush_and_tight() -> None:
    blocks = _sorted_blocks(
        plan_watermark_blocks(_template("top-left", y=0.035), _variables(), WIDTH, HEIGHT)
    )

    assert len(blocks) == 5
    for block in blocks:
        assert block["x"] == MARGIN
    assert blocks[0]["y"] == MARGIN
    for upper, lower in zip(blocks, blocks[1:], strict=False):
        assert lower["y"] - (upper["y"] + upper["height"]) == GAP


def test_legacy_coordinates_are_inferred_as_bottom_right() -> None:
    template = _template(anchor=None, x=0.62, y=0.775)
    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)

    for block in blocks:
        assert block["x"] + block["width"] == WIDTH - MARGIN
    assert max(block["y"] + block["height"] for block in blocks) == HEIGHT - MARGIN


def test_template_layout_gap_override() -> None:
    template = _template()
    template["meta"]["layout_gap"] = 2
    blocks = _sorted_blocks(plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT))

    for upper, lower in zip(blocks, blocks[1:], strict=False):
        assert lower["y"] - (upper["y"] + upper["height"]) == 2


def test_center_free_coordinates_are_not_forced_to_corner() -> None:
    template = _template(anchor=None, x=0.34, y=0.34)
    blocks = plan_watermark_blocks(template, _variables(), WIDTH, HEIGHT)

    assert all(block["x"] > MARGIN for block in blocks)
    assert all(block["y"] == int(0.34 * HEIGHT) for block in blocks)
