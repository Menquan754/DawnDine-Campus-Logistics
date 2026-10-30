"""日程图片导出测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from dawndine.services.schedule import render_schedule_image


def test_render_schedule_image_with_rows(tmp_path: Path) -> None:
    rows = [
        [1, "2026-10-28", "08:30", "晨检并记录冷库温度", "manual", "2026-10-28 08:00:00"],
        [2, "2026-10-29", "待补", "留样检查与记录核对", "chat", "2026-10-28 09:00:00"],
    ]

    path = render_schedule_image(rows, view="今天", output_dir=tmp_path)

    assert path.is_file()
    assert path.parent == tmp_path
    assert path.name.startswith("schedule-")
    assert path.name.isascii()
    with Image.open(path) as image:
        assert image.width >= 1080
        assert image.height > 200


def test_render_schedule_image_accepts_mapping_rows(tmp_path: Path) -> None:
    rows = [
        {
            "id": 3,
            "date": "2026-10-30",
            "time": "16:00",
            "content": "家长开放日陪餐",
            "source": "manual",
        }
    ]

    path = render_schedule_image(rows, view="未来 7 天", output_dir=tmp_path)

    assert path.is_file()


def test_render_schedule_image_without_rows(tmp_path: Path) -> None:
    path = render_schedule_image([], view="全部", output_dir=tmp_path)

    assert path.is_file()
    assert path.stat().st_size > 0
