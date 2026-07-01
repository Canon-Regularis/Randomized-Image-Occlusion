from __future__ import annotations

import json

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig


def test_from_mapping_fills_missing_with_defaults():
    rc = RenderConfig.from_mapping({"accent_color": "#000000"})
    assert rc.accent_color == "#000000"
    assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]


def test_behaviour_json_uses_camel_case_keys():
    rc = RenderConfig.from_mapping(DEFAULT_CONFIG)
    data = json.loads(rc.behaviour_json())
    assert set(data) == {
        "minArrowFraction",
        "showTargetDot",
        "promptText",
        "maxPlacementAttempts",
    }


def test_css_variables_cover_all_colors():
    rc = RenderConfig.from_mapping(DEFAULT_CONFIG)
    variables = rc.css_variables()
    assert variables["--ro-accent"] == DEFAULT_CONFIG["accent_color"]
    assert set(variables) == {"--ro-accent", "--ro-box-fill", "--ro-box-text", "--ro-dot"}


def test_fingerprint_payload_changes_with_values():
    a = RenderConfig.from_mapping(DEFAULT_CONFIG).fingerprint_payload()
    b = RenderConfig.from_mapping({**DEFAULT_CONFIG, "accent_color": "#123456"}).fingerprint_payload()
    assert a != b


def test_from_mapping_is_total_on_garbage():
    rc = RenderConfig.from_mapping(
        {
            "min_arrow_fraction": "not a number",
            "max_placement_attempts": "x",
            "accent_color": None,
        }
    )
    assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]
    assert rc.max_placement_attempts == DEFAULT_CONFIG["max_placement_attempts"]
    assert rc.accent_color == DEFAULT_CONFIG["accent_color"]


def test_non_finite_arrow_fraction_falls_back_and_json_stays_valid():
    rc = RenderConfig.from_mapping({"min_arrow_fraction": float("inf")})
    assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]
    # behaviour_json must always be parseable JSON (no NaN/Infinity tokens).
    json.loads(RenderConfig.from_mapping({"min_arrow_fraction": float("nan")}).behaviour_json())


def test_min_arrow_fraction_is_clamped_to_unit_interval():
    assert RenderConfig.from_mapping({"min_arrow_fraction": 5.0}).min_arrow_fraction == 1.0
    assert RenderConfig.from_mapping({"min_arrow_fraction": -1.0}).min_arrow_fraction == 0.0


def test_string_booleans_are_coerced():
    assert RenderConfig.from_mapping({"show_target_dot": "false"}).show_target_dot is False
    assert RenderConfig.from_mapping({"show_target_dot": "true"}).show_target_dot is True


def test_max_placement_attempts_clamped_to_at_least_one():
    assert RenderConfig.from_mapping({"max_placement_attempts": 0}).max_placement_attempts == 1
    assert RenderConfig.from_mapping({"max_placement_attempts": -5}).max_placement_attempts == 1


def test_valid_colors_are_accepted():
    for color in ["#e53935", "#fff", "#11223344", "red", "rebeccapurple", "rgb(1, 2, 3)", "rgba(1,2,3,.5)"]:
        assert RenderConfig.from_mapping({"accent_color": color}).accent_color == color


def test_malicious_or_malformed_colors_fall_back_to_default():
    for color in ["red; } </style><script>x</script>", "#nothex", "url(x)", ""]:
        assert (
            RenderConfig.from_mapping({"accent_color": color}).accent_color
            == DEFAULT_CONFIG["accent_color"]
        )
