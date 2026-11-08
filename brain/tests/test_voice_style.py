from brain.voice.style import DEFAULT_STYLE, MAX_SPEED, VOICE_STYLES, style_values
from shared.protocol.messages import Settings


def test_new_settings_default_to_the_expressive_voice() -> None:
    assert Settings().voice_style == DEFAULT_STYLE == "expressive"


def test_each_style_sets_every_field_so_switching_back_undoes_the_other() -> None:
    # Pipecat only sends the fields it's given, so a field missing from one style would keep the
    # other style's value after a switch.
    fields = {frozenset(values) for values in VOICE_STYLES.values()}
    assert len(fields) == 1


def test_expressive_varies_more_than_classic() -> None:
    expressive, classic = style_values("expressive"), style_values("classic")
    assert expressive["stability"] < classic["stability"]
    assert expressive["style"] > classic["style"]


def test_an_unknown_style_falls_back_to_the_default() -> None:
    assert style_values("loud") == style_values(None) == VOICE_STYLES[DEFAULT_STYLE]


def test_danger_speeds_up_every_style_without_passing_the_limit() -> None:
    for style in VOICE_STYLES:
        calm, urgent = style_values(style), style_values(style, urgent=True)
        assert calm["speed"] < urgent["speed"] <= MAX_SPEED
        assert {**urgent, "speed": calm["speed"]} == calm
