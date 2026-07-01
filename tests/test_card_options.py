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
