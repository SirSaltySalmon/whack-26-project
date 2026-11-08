"""The overlay debug-view demo: what it draws, and that the launcher can run it."""

from scripts.debug_regions_demo import (
    BOXES,
    STATUS_EVERY_TICKS,
    STATUSES,
    TOOL_EVERY_TICKS,
    TOOLS,
    regions_at,
    sightings_at,
)
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


def test_every_sighting_kind_shows_within_one_round_of_tools() -> None:
    ticks = range(TOOL_EVERY_TICKS * len(TOOLS))
    kinds = {s.kind for tick in ticks for s in sightings_at(tick).sightings}
    assert kinds == {"noticed", "look", "point", "look_back"}


def test_noticed_boxes_move_and_stay_on_a_1280_by_720_screen() -> None:
    first, later = sightings_at(1).sightings, sightings_at(2).sightings
    assert first[0].rect != later[0].rect
    for tick in range(100):
        for sighting in sightings_at(tick).sightings:
            rect = sighting.rect
            assert rect.x >= 0 and rect.y >= 0
            assert rect.x + rect.width <= 1280 and rect.y + rect.height <= 720


def test_the_launcher_runs_a_script_in_the_brains_place() -> None:
    assert brain_command([r"scripts\debug_regions_demo.py"]) == [r"scripts\debug_regions_demo.py"]
    assert brain_command(["--live", "--type"]) == ["-m", "brain", "--live", "--type"]
