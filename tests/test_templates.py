from __future__ import annotations

import base64
import json
import re

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.notetype.templates import (
    TemplateAssembler,
    extract_fingerprint,
)
from randomized_occlusion.resources import read_web

RC = RenderConfig.from_mapping(DEFAULT_CONFIG)

_FIELD_TOKEN_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def _assembler(render_js="/* render */"):
    return TemplateAssembler(DEFAULT_SPEC, render_js)


def test_front_contains_required_anki_tokens():
    front = _assembler().front(RC)
    assert "{{#Header}}" in front and "{{/Header}}" in front
    assert "{{Image}}" in front
    assert "{{Structures}}" in front
    assert "{{cloze:Ordinals}}" in front
    assert 'id="ro-stage"' in front
    assert 'id="ro-overlay"' in front


def _extract_config(front: str) -> dict:
    match = re.search(r'id="ro-config"[^>]*>([^<]*)</script>', front)
    assert match, "config script element not found"
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))


def test_front_embeds_config_as_decodable_base64():
    front = _assembler().front(RC)
    assert _extract_config(front)["promptText"] == RC.prompt_text


def test_front_embeds_render_js():
    front = _assembler("window.__SENTINEL__ = 1;").front(RC)
    assert "window.__SENTINEL__ = 1;" in front


def test_bundled_render_js_has_no_double_brace_tokens():
    # render.js is inlined into the card template; a literal {{ or }} (even in a
    # comment) would be parsed by Anki as a field directive and break the card.
    js = read_web("review/render.js")
    assert "{{" not in js and "}}" not in js


def test_front_only_references_declared_fields_with_real_js():
    # Uses the REAL render.js (not the stub) so a stray token in it is caught.
    asm = TemplateAssembler(DEFAULT_SPEC, read_web("review/render.js"))
    tokens = set(_FIELD_TOKEN_RE.findall(asm.front(RC)))
    assert tokens == {
        "#Header",
        "Header",
        "/Header",
        "Image",
        "cloze:Ordinals",
        "Structures",
    }


def test_back_only_references_declared_fields():
    tokens = set(_FIELD_TOKEN_RE.findall(_assembler().back()))
    assert tokens == {
        "FrontSide",
        "cloze:Ordinals",
        "#Back Extra",
        "Back Extra",
        "/Back Extra",
    }


def test_type_mode_adds_a_type_in_box():
    type_rc = RenderConfig.from_mapping({**DEFAULT_CONFIG, "interaction": "type"})
    assert "{{type:cloze:Ordinals}}" in _assembler().front(type_rc)


def test_reveal_mode_has_no_type_in_box():
    assert "{{type:cloze:Ordinals}}" not in _assembler().front(RC)


def test_both_sides_contain_a_literal_cloze_reference():
    # Anki's cloze note-type validator requires {{cloze:...}} on both sides.
    asm = _assembler()
    assert "{{cloze:Ordinals}}" in asm.front(RC)
    assert "{{cloze:Ordinals}}" in asm.back()


def test_back_contains_frontside_and_answer_sentinel():
    back = _assembler().back()
    assert "{{FrontSide}}" in back
    assert 'id="ro-answer"' in back
    assert "{{#Back Extra}}" in back and "{{Back Extra}}" in back


def test_render_js_closing_tag_is_escaped():
    front = _assembler("var x = '</script>';").front(RC)
    # The dangerous closing tag inside the JS must be neutralised...
    assert "'</script>'" not in front
    assert "'<\\/script>'" in front
    # ...leaving only the three structural <script> closers (data/config/render).
    assert front.count("</script>") == 3


def test_config_script_breakout_is_neutralised():
    rc = RenderConfig.from_mapping({**DEFAULT_CONFIG, "prompt_text": "</script><b>x"})
    front = _assembler().front(rc)
    # base64 config carries no raw '<', so it can't close the script early...
    assert front.count("</script>") == 3  # only the three structural closers
    # ...yet the value round-trips intact.
    assert _extract_config(front)["promptText"] == "</script><b>x"


def test_config_template_directive_cannot_be_injected():
    # An Anki directive in prompt_text must not survive as a live {{...}} in the
    # baked template (base64 hides it).
    rc = RenderConfig.from_mapping({**DEFAULT_CONFIG, "prompt_text": "{{Deck}}"})
    front = _assembler().front(rc)
    assert "{{Deck}}" not in front
    assert _extract_config(front)["promptText"] == "{{Deck}}"


def test_css_embeds_fingerprint_and_variables():
    css = _assembler().css(RC)
    assert extract_fingerprint(css) == _assembler().fingerprint(RC)
    assert "--ro-accent: #e53935;" in css


def test_fingerprint_is_deterministic():
    assert _assembler().fingerprint(RC) == _assembler().fingerprint(RC)


def test_fingerprint_changes_with_config():
    other = RenderConfig.from_mapping({**DEFAULT_CONFIG, "accent_color": "#000000"})
    assert _assembler().fingerprint(RC) != _assembler().fingerprint(other)


def test_fingerprint_changes_with_render_js():
    assert _assembler("a").fingerprint(RC) != _assembler("b").fingerprint(RC)
