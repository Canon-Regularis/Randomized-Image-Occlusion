from __future__ import annotations

from randomized_occlusion.domain.card_options import (
    CardMode,
    CardOptions,
    Direction,
    Interaction,
)


def test_enum_values_are_the_wire_strings():
    assert Direction.FORWARD == "forward"
    assert Interaction.TYPE == "type"
    assert CardMode.SINGLE == "single"


def test_coerce_accepts_members_strings_and_case():
    assert Direction.coerce("reverse", Direction.FORWARD) is Direction.REVERSE
    assert Direction.coerce("BOTH", Direction.FORWARD) is Direction.BOTH
    assert Direction.coerce(Direction.BOTH, Direction.FORWARD) is Direction.BOTH


def test_coerce_falls_back_on_unknown_or_none():
    assert Direction.coerce("sideways", Direction.FORWARD) is Direction.FORWARD
    assert CardMode.coerce(None, CardMode.MULTI) is CardMode.MULTI
    assert Interaction.coerce(42, Interaction.REVEAL) is Interaction.REVEAL


def test_default_options():
    opts = CardOptions()
    assert opts.direction is Direction.FORWARD
    assert opts.interaction is Interaction.REVEAL
    assert opts.context_labels is False
    assert opts.mode is CardMode.MULTI


def test_from_config_reads_card_mode_key_and_coerces():
    opts = CardOptions.from_config(
        {
            "direction": "both",
            "interaction": "type",
            "show_context_labels": True,
            "card_mode": "single",
        }
    )
    assert opts == CardOptions(
        direction=Direction.BOTH,
        interaction=Interaction.TYPE,
        context_labels=True,
        mode=CardMode.SINGLE,
    )


def test_from_config_uses_defaults_for_missing_or_bad_values():
    opts = CardOptions.from_config({"direction": "nonsense"})
    assert opts == CardOptions()  # all defaults


def test_coerce_ignores_surrounding_whitespace():
    # Values arrive from a hand-editable config file.
    assert Direction.coerce("  reverse  ", Direction.FORWARD) is Direction.REVERSE
    assert CardMode.coerce("\tsingle\n", CardMode.MULTI) is CardMode.SINGLE


def test_from_config_reads_booleans_the_same_way_render_config_does():
    # The two read the SAME config keys, and config.json is meant to be edited by
    # hand. When this used a plain bool() while RenderConfig honoured the falsey
    # spellings, "show_context_labels": "false" switched context labels OFF for
    # every rendered card and ON for every newly created note.
    from randomized_occlusion.config.render_config import RenderConfig

    for value in ["false", "no", "off", "0", "none", "False", " off ", "", "yes", "1"]:
        mapping = {"show_context_labels": value}
        assert (
            CardOptions.from_config(mapping).context_labels
            == RenderConfig.from_mapping(mapping).show_context_labels
        ), f"the two config readers disagree about {value!r}"


def test_every_falsey_spelling_switches_a_config_boolean_off():
    # Absolute values, not agreement with RenderConfig: the two share one
    # implementation now, so a shrunken vocabulary would move them together
    # and the comparison above would still pass.
    for value in ["false", "0", "no", "off", "", "none", "FALSE", " Off "]:
        options = CardOptions.from_config({"show_context_labels": value})
        assert options.context_labels is False, f"{value!r} did not read as off"
    for value in ["true", "1", "yes", "on", "anything else"]:
        options = CardOptions.from_config({"show_context_labels": value})
        assert options.context_labels is True, f"{value!r} did not read as on"


def test_coerce_bool_is_total():
    # Never raises: it reads a hand-edited config value, and the save path cannot
    # afford an exception from a setting.
    from randomized_occlusion.domain.card_options import coerce_bool

    # Values with no sensible reading fall back to the caller's default.
    for value in [None, object(), [], {}, b"false"]:
        assert coerce_bool(value, True) is True
        assert coerce_bool(value, False) is False
    # A number reads as its own truthiness, whatever the default says.
    assert coerce_bool(1.5, False) is True
    assert coerce_bool(0.0, True) is False
