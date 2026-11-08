from brain.perception.observation import Observation
from brain.perception.tracker import ObservationTracker


def frame(**overrides: object) -> Observation:
    fields: dict[str, object] = {
        "screen_type": "gameplay",
        "summary": "Player walks through a forest.",
        "player_action": None,
        "health_visible": True,
        "health_raw": "100/100",
        "health_percent": 100,
        "danger_level": "none",
        "threats": [],
        "selected_item": None,
        "menu_title": None,
        "location": "forest",
        "on_screen_text": [],
        "notable": None,
        "unsure": [],
    }
    return Observation.model_validate({**fields, **overrides})


def fight(level: str = "medium", threat: str = "Skeleton") -> Observation:
    return frame(danger_level=level, threats=[threat], summary=f"Fighting a {threat}.")


def feed(tracker: ObservationTracker, *frames: Observation, start: float = 0.0) -> list[str]:
    names: list[str] = []
    for index, observation in enumerate(frames):
        names += [c.name for c in tracker.update(observation, start + index * 0.8)]
    return names


def test_one_frame_of_danger_is_not_believed() -> None:
    assert feed(ObservationTracker(), frame(), fight(), frame(), fight(), frame()) == []


def test_two_frames_in_a_row_confirm_danger() -> None:
    tracker = ObservationTracker()
    changes = tracker.update(fight(), 0.0) + tracker.update(fight(), 0.8)
    assert [c.name for c in changes] == ["danger_started"]
    assert changes[0].data == {"level": "medium", "threats": ["Skeleton"]}


def test_forgetting_drops_a_fight_so_one_still_going_is_confirmed_again() -> None:
    # Called when the partner is blinded: what it saw before doesn't hold once it looks again.
    tracker = ObservationTracker()
    assert feed(tracker, fight(), fight()) == ["danger_started"]
    tracker.forget()
    assert tracker.danger is None
    assert tracker.live_state(2.0) == {"screen": "can't see the game right now"}
    assert feed(tracker, fight(), fight(), start=3.0) == ["danger_started"]


def test_low_danger_never_raises_an_event() -> None:
    low = frame(danger_level="low", threats=["jellyfish in the water"])
    assert feed(ObservationTracker(), low, low, low, low) == []


def test_threat_names_must_agree_between_frames() -> None:
    tracker = ObservationTracker()
    tracker.update(fight(threat="King Slime"), 0.0)
    changes = tracker.update(fight(threat="Skeleton"), 0.8)
    assert changes[0].name == "danger_started"
    assert changes[0].data["threats"] == []


def test_rewordings_of_a_threat_count_as_the_same_one() -> None:
    tracker = ObservationTracker()
    tracker.update(fight(threat="Blue Slime"), 0.0)
    changes = tracker.update(fight(threat="the blue slime near the player"), 0.8)
    assert changes[0].data["threats"] == ["the blue slime near the player"]


def test_a_brief_lull_does_not_end_the_danger() -> None:
    names = feed(ObservationTracker(), fight(), fight(), frame(), frame(), fight())
    assert names == ["danger_started"]


def test_three_calm_frames_end_the_danger() -> None:
    names = feed(ObservationTracker(), fight(), fight(), frame(), frame(), frame())
    assert names == ["danger_started", "danger_ended"]


def test_danger_can_escalate_once_confirmed() -> None:
    names = feed(
        ObservationTracker(), fight(), fight(), fight("high"), fight("high"), fight("high")
    )
    assert names == ["danger_started", "danger_high"]


def test_starting_at_high_reports_high() -> None:
    tracker = ObservationTracker()
    tracker.update(fight("high"), 0.0)
    assert tracker.update(fight("high"), 0.8)[0].data["level"] == "high"


def test_frames_far_apart_do_not_confirm_each_other() -> None:
    tracker = ObservationTracker()
    assert tracker.update(fight(), 0.0) == []
    assert tracker.update(fight(), 60.0) == []
    assert [c.name for c in tracker.update(fight(), 60.8)] == ["danger_started"]


def test_low_health_needs_two_agreeing_frames_and_only_reports_once() -> None:
    low = frame(health_raw="20/100", health_percent=20)
    tracker = ObservationTracker()
    assert tracker.update(low, 0.0) == []
    changes = tracker.update(low, 0.8)
    assert [c.name for c in changes] == ["health_low"]
    assert changes[0].data == {"percent": 20}
    assert tracker.update(low, 1.6) == []


def test_low_health_reports_again_after_recovering() -> None:
    low = frame(health_raw="20/100", health_percent=20)
    healed = frame(health_raw="80/100", health_percent=80)
    names = feed(ObservationTracker(), low, low, healed, healed, low, low)
    assert names == ["health_low", "health_low"]


def test_a_single_misread_of_health_changes_nothing() -> None:
    misread = frame(health_raw="10/100", health_percent=10)
    tracker = ObservationTracker()
    assert feed(tracker, frame(), frame(), misread, frame()) == []
    assert tracker.live_state(3.0)["health"] == "100/100 (100%)"


def test_death_screen_needs_confirming_and_reports_once() -> None:
    dead = frame(screen_type="death", health_visible=False)
    names = feed(ObservationTracker(), frame(), dead, dead, dead)
    assert names == ["player_died"]


def test_live_state_holds_back_an_unconfirmed_claim() -> None:
    tracker = ObservationTracker()
    tracker.update(frame(), 0.0)
    tracker.update(frame(), 0.8)
    tracker.update(fight(threat="Blue Slime"), 1.6)
    state = tracker.live_state(1.6)
    assert state["danger"] == "none"
    assert "threats" not in state
    assert state["seen"] == "Player walks through a forest."


def test_live_state_reports_confirmed_danger() -> None:
    tracker = ObservationTracker()
    feed(tracker, fight(), fight())
    state = tracker.live_state(1.0)
    assert state["danger"] == "medium"
    assert state["threats"] == "Skeleton"
    assert state["seen"] == "Fighting a Skeleton."


def test_low_threats_stay_out_of_the_notable_line() -> None:
    low = frame(danger_level="low", threats=["jellyfish"], notable="Jellyfish nearby!")
    tracker = ObservationTracker()
    feed(tracker, low, low)
    assert "notable" not in tracker.live_state(1.0)


def test_live_state_admits_when_it_cannot_see() -> None:
    tracker = ObservationTracker()
    assert tracker.live_state(0.0) == {"screen": "can't see the game right now"}
    feed(tracker, frame(), frame())
    assert tracker.live_state(100.0) == {"screen": "can't see the game right now"}


def test_held_item_needs_two_agreeing_frames() -> None:
    tracker = ObservationTracker()
    tracker.update(frame(selected_item="Sword"), 0.0)
    assert "held item" not in tracker.live_state(0.0)
    tracker.update(frame(selected_item="Sword"), 0.8)
    assert tracker.live_state(0.8)["held item"] == "Sword"
