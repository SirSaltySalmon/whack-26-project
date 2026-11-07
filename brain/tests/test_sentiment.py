import numpy as np

from brain.voice.sentiment import MoodTracker, label_mood, loudness_db


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def tracker() -> tuple[MoodTracker, Clock]:
    clock = Clock()
    mood = MoodTracker(clock=clock)
    mood.start_turn()
    clock.now += 5.0
    return mood, clock


def pcm(amplitude: int, samples: int = 320) -> bytes:
    return np.full(samples, amplitude, dtype=np.int16).tobytes()


def test_labels_combine_words_and_voice() -> None:
    assert label_mood(0.0, 0.0) == "neutral"
    assert label_mood(-0.3, 0.0) == "negative"
    assert label_mood(-0.3, 0.8) == "frustrated"
    assert label_mood(-0.8, 0.0) == "frustrated"
    assert label_mood(0.5, 0.0) == "positive"
    assert label_mood(0.5, 0.8) == "excited"
    assert label_mood(0.0, 0.8) == "intense"


def test_loudness_handles_silence_and_full_scale() -> None:
    assert loudness_db(pcm(0)) == -90.0
    assert loudness_db(b"") == -90.0
    assert abs(loudness_db(pcm(32767))) < 0.01


def test_angry_words_read_as_frustrated() -> None:
    mood, _ = tracker()
    result = mood.add_text("this is so stupid I hate this", final=True)
    assert result is not None and result.label == "frustrated"


def test_game_talk_is_not_hostile() -> None:
    mood, _ = tracker()
    result = mood.add_text("we killed the boss", final=True)
    assert result is not None and result.label != "frustrated" and result.valence >= 0


def test_shouting_above_the_players_normal_raises_intensity() -> None:
    mood, _ = tracker()
    for _ in range(2000):
        mood.add_audio(pcm(800))
    calm = mood.add_text("where do I go", final=True)
    for _ in range(30):
        mood.add_audio(pcm(16000))
    loud = mood.add_text("where do I go", final=True)
    assert calm is not None and loud is not None
    assert calm.intensity < 0.2 and loud.intensity >= 0.5 and loud.label == "intense"


def test_partial_scoring_is_throttled_but_the_final_always_counts() -> None:
    mood, clock = tracker()
    assert mood.add_text("I hate this") is not None
    clock.now += 0.1
    assert mood.add_text("I hate this so much") is None
    assert mood.add_text("I hate this so much", final=True) is not None


def test_partials_only_report_a_change_of_mood() -> None:
    mood, clock = tracker()
    assert mood.add_text("this is terrible and awful") is not None
    clock.now += 1.0
    assert mood.add_text("this is terrible and awful today") is None


def test_live_state_stays_quiet_when_neutral_or_old() -> None:
    mood, clock = tracker()
    assert mood.live_state() == {}
    mood.add_text("where do I go", final=True)
    assert mood.live_state() == {}
    mood.add_text("I hate this stupid game", final=True)
    assert mood.live_state() == {"player mood": "frustrated"}
    clock.now += 31.0
    assert mood.live_state() == {}
