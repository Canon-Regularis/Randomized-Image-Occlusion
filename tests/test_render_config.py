from __future__ import annotations

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.domain.codec import encode_json_b64


def test_from_mapping_fills_missing_with_defaults():
    rc = RenderConfig.from_mapping({"accent_color": "#000000"})
    assert rc.accent_color == "#000000"
    assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]


def test_behaviour_uses_camel_case_keys():
    rc = RenderConfig.from_mapping(DEFAULT_CONFIG)
    assert set(rc.behaviour()) == {
        "minArrowFraction",
        "showTargetDot",
        "promptText",
        "maxPlacementAttempts",
        "showDecoyDots",
        "showContextLabels",
    }


def test_css_variables_cover_all_colors():
    rc = RenderConfig.from_mapping(DEFAULT_CONFIG)
    variables = rc.css_variables()
    assert variables["--ro-accent"] == DEFAULT_CONFIG["accent_color"]
    assert set(variables) == {"--ro-accent", "--ro-box-fill", "--ro-box-text", "--ro-dot"}


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


def test_non_finite_arrow_fraction_falls_back_and_encodes_cleanly():
    rc = RenderConfig.from_mapping({"min_arrow_fraction": float("inf")})
    assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]
    # The finite fallback means the behaviour dict encodes without NaN tokens.
    nan_rc = RenderConfig.from_mapping({"min_arrow_fraction": float("nan")})
    assert encode_json_b64(nan_rc.behaviour())  # would raise on a NaN value


def test_min_arrow_fraction_is_clamped_to_unit_interval():
    assert RenderConfig.from_mapping({"min_arrow_fraction": 5.0}).min_arrow_fraction == 1.0
    assert RenderConfig.from_mapping({"min_arrow_fraction": -1.0}).min_arrow_fraction == 0.0


def test_string_booleans_are_coerced():
    assert RenderConfig.from_mapping({"show_target_dot": "false"}).show_target_dot is False
    assert RenderConfig.from_mapping({"show_target_dot": "true"}).show_target_dot is True


def test_max_placement_attempts_clamped_to_at_least_one():
    assert RenderConfig.from_mapping({"max_placement_attempts": 0}).max_placement_attempts == 1
    assert RenderConfig.from_mapping({"max_placement_attempts": -5}).max_placement_attempts == 1


def test_max_placement_attempts_clamped_on_the_high_side():
    # A hand-edited absurd value must be capped so the renderer's per-structure
    # placement loop can't hang the webview (the default is well under the cap).
    def attempts(value: int) -> int:
        return RenderConfig.from_mapping({"max_placement_attempts": value}).max_placement_attempts

    assert attempts(100_000_000) == 1000  # absurd value capped
    assert attempts(1000) == 1000  # exactly at the cap
    assert attempts(60) == 60  # a normal value is untouched


def test_non_finite_int_config_falls_back_instead_of_crashing():
    # json.loads accepts Infinity/NaN, so a hand-edited config can smuggle a
    # non-finite value into an int field; int(inf) raises OverflowError.
    for bad in [float("inf"), float("-inf"), float("nan")]:
        rc = RenderConfig.from_mapping({"max_placement_attempts": bad})
        assert rc.max_placement_attempts == DEFAULT_CONFIG["max_placement_attempts"]


def test_huge_int_in_a_float_field_falls_back_instead_of_crashing():
    # A hand-edited config.json can hold an integer literal too large to convert
    # to a float — json.loads parses it as a Python int and float(10**400) raises
    # OverflowError. from_mapping must stay total (never raise), or note-type
    # install and card saving would crash for that profile.
    for bad in [10**400, 10**320, int("9" * 500)]:
        rc = RenderConfig.from_mapping({"min_arrow_fraction": bad})
        assert rc.min_arrow_fraction == DEFAULT_CONFIG["min_arrow_fraction"]


def test_valid_colors_are_accepted():
    colors = ["#e53935", "#fff", "#11223344", "red", "rebeccapurple", "rgb(1, 2, 3)"]
    for color in colors:
        assert RenderConfig.from_mapping({"accent_color": color}).accent_color == color


def test_malicious_or_malformed_colors_fall_back_to_default():
    for color in ["red; } </style><script>x</script>", "#nothex", "url(x)", ""]:
        assert (
            RenderConfig.from_mapping({"accent_color": color}).accent_color
            == DEFAULT_CONFIG["accent_color"]
        )
