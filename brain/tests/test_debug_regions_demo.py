"""The overlay debug-view demo: what it draws, and that the launcher can run it."""

from scripts.debug_regions_demo import BOXES, STATUS_EVERY_TICKS, STATUSES, regions_at
from scripts.run_all import brain_command


def test_every_box_is_drawn_with_a_known_status() -> None:
    regions = regions_at(0).regions
    assert [region.name for region in regions] == [name for name, _ in BOXES]
    assert {region.status for region in regions} <= set(STATUSES)


def test_readings_show_only_when_ok_and_tick_over() -> None:
    first, later = regions_at(0).regions, regions_at(1).regions
    assert all((region.display is not None) == (region.status == "ok") for region in first)
    assert first[0].status == "ok" and first[0].display != later[0].display


def test_statuses_take_turns() -> None:
    seen = {regions_at(tick * STATUS_EVERY_TICKS).regions[0].status for tick in range(3)}
    assert seen == set(STATUSES)


def test_every_box_fits_a_1280_by_720_screen() -> None:
    for _, rect in BOXES:
        assert rect.x + rect.width <= 1280 and rect.y + rect.height <= 720


def test_the_launcher_runs_a_script_in_the_brains_place() -> None:
    assert brain_command([r"scripts\debug_regions_demo.py"]) == [r"scripts\debug_regions_demo.py"]
    assert brain_command(["--live", "--type"]) == ["-m", "brain", "--live", "--type"]
