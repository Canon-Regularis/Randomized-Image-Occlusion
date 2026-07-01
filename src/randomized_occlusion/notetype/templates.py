"""Assembles the note type's HTML/CSS from the spec, config, and reviewer JS.

The ``TemplateAssembler`` has a single responsibility: turn a
:class:`NoteTypeSpec` plus a :class:`RenderConfig` plus the renderer JavaScript
into the three strings Anki stores on a note type (front HTML, back HTML, CSS).
It knows nothing about the collection or how the note type is installed.
"""

from __future__ import annotations

import hashlib
import re
from textwrap import dedent

from ..config.render_config import RenderConfig
from ..domain.codec import encode_json_b64
from .spec import NoteTypeSpec

__all__ = ["TEMPLATE_VERSION", "TemplateAssembler", "extract_fingerprint"]

#: Bump when the template *skeleton* (not the JS/CSS) changes, to force updates.
TEMPLATE_VERSION = 1

_FINGERPRINT_RE = re.compile(r"ro-fingerprint:([0-9a-f]+)")


def extract_fingerprint(css: str) -> str | None:
    """Recover the fingerprint embedded in an installed note type's CSS."""
    match = _FINGERPRINT_RE.search(css or "")
    return match.group(1) if match else None


def _script_safe(text: str) -> str:
    """Neutralise any ``</`` so embedded JS can't terminate its ``<script>``.

    ``<\\/`` is equivalent to ``</`` inside our JavaScript, so this is safe.
    Used for the renderer JS, which is add-on-authored (not user data).
    """
    return text.replace("</", "<\\/")


# The card stylesheet. Written with single braces (no ``str.format``) so the CSS
# stays readable; ``_css_body`` substitutes the config colour variables at
# ``__RO_VARIABLES__``. Theme colours are CSS custom properties on ``.card`` with
# a ``.nightMode`` override, so the card looks right in both Anki day and night
# mode; the config-driven label/accent colours cascade from ``.ro-root``.
_CARD_CSS = """\
.card {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  font-size: 18px;
  line-height: 1.5;
  text-align: center;
  color: var(--ro-fg);
  background-color: var(--ro-bg);
  --ro-bg: #ffffff;
  --ro-fg: #14161a;
  --ro-ok: #2e7d32;
  --ro-bad: #c62828;
  --ro-panel-bg: #f4f5f7;
  --ro-panel-border: #d5d8dd;
  --ro-focus-ring: rgba(0, 0, 0, 0.14);
}
.nightMode.card,
.nightMode .card {
  --ro-bg: #1e1f22;
  --ro-fg: #e6e7ea;
  --ro-ok: #81c784;
  --ro-bad: #ef9a9a;
  --ro-panel-bg: #2a2c31;
  --ro-panel-border: #45474e;
  --ro-focus-ring: rgba(255, 255, 255, 0.18);
}
.ro-root {
__RO_VARIABLES__
}
.ro-header { font-weight: 600; font-size: 1.05em; margin: 0 0 12px; }
.ro-stage { position: relative; display: inline-block; max-width: 100%; line-height: 0; }
.ro-stage img { display: block; max-width: 100%; height: auto; border-radius: 8px; }
.ro-overlay {
  position: absolute; left: 0; top: 0; width: 100%; height: 100%;
  pointer-events: none; overflow: visible;
}
/* Kept in the DOM (so JS can read them) but visually suppressed. */
.ro-hidden, .ro-answer { position: absolute; width: 0; height: 0; overflow: hidden; opacity: 0; }
/* SVG occlusion boxes, arrows and target dots. */
.ro-box-rect {
  fill: var(--ro-box-fill); stroke: var(--ro-accent); stroke-width: 2;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.35));
}
.ro-box-rect.ro-correct { stroke: var(--ro-ok); stroke-width: 2.5; }
.ro-box-rect.ro-wrong { stroke: var(--ro-bad); stroke-width: 2.5; }
.ro-box-text {
  fill: var(--ro-box-text); font-family: inherit; font-size: 18px; font-weight: 700;
}
.ro-arrow { stroke: var(--ro-accent); stroke-width: 3; stroke-linecap: round; fill: none; }
.ro-arrowhead path { fill: var(--ro-accent); stroke: none; }
.ro-dot {
  fill: var(--ro-dot); stroke: #ffffff; stroke-width: 2;
  filter: drop-shadow(0 0 1.5px rgba(0, 0, 0, 0.55));
}
.ro-extra {
  margin: 14px auto 0; max-width: 42em; padding-top: 10px;
  border-top: 1px solid var(--ro-panel-border);
  text-align: left; font-size: 0.9em; line-height: 1.5;
}
/* Native type-in box (multi mode). */
.ro-type { margin-top: 14px; line-height: normal; }
.ro-type input {
  font: inherit; padding: 7px 10px; border-radius: 8px;
  border: 1px solid var(--ro-panel-border);
  background: var(--ro-bg); color: var(--ro-fg);
}
/* Single-card cycler. */
.ro-cycler { margin-top: 16px; line-height: normal; font-size: 0.9em; }
.ro-cycler-row {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: center;
}
.ro-progress {
  font-weight: 700; font-variant-numeric: tabular-nums;
  padding: 4px 12px; border-radius: 999px;
  background: var(--ro-panel-bg); border: 1px solid var(--ro-panel-border);
}
.ro-cycler input {
  font: inherit; width: min(280px, 60vw); min-width: 0; padding: 8px 12px;
  border-radius: 8px; border: 1px solid var(--ro-panel-border);
  background: var(--ro-bg); color: var(--ro-fg);
}
.ro-cycler input:focus {
  outline: none; border-color: var(--ro-accent);
  box-shadow: 0 0 0 3px var(--ro-focus-ring);
}
.ro-cycler button {
  font: inherit; font-weight: 600; padding: 8px 16px; border-radius: 8px;
  cursor: pointer; border: 1px solid var(--ro-accent);
  background: var(--ro-accent); color: #ffffff; transition: filter 0.1s ease;
}
.ro-cycler button:hover { filter: brightness(1.06); }
.ro-cycler button:active { filter: brightness(0.94); }
.ro-cycler.ro-done button {
  background: var(--ro-panel-bg); color: var(--ro-fg);
  border-color: var(--ro-panel-border); cursor: default;
}
.ro-feedback { margin-top: 10px; min-height: 1.3em; font-weight: 600; }
.ro-feedback.correct { color: var(--ro-ok); }
.ro-feedback.wrong { color: var(--ro-bad); }
.tappable { cursor: pointer; }
@media (max-width: 400px) {
  .card { font-size: 16px; }
  .ro-cycler input, .ro-cycler button { padding: 7px 10px; }
}
"""


class TemplateAssembler:
    def __init__(self, spec: NoteTypeSpec, render_js: str) -> None:
        self._spec = spec
        self._render_js = _script_safe(render_js)

    # -- public API ------------------------------------------------------------

    def front(self, render_config: RenderConfig) -> str:
        s = self._spec
        # A type-in box that grades the typed answer against the active cloze
        # (the label), gated by the per-note TypeAnswer field so only "type"
        # notes become Anki type-answer cards. Plain string (not f-string) so
        # the "{{" stay literal; inserted as a .format value so they aren't
        # re-parsed.
        type_block = (
            "{{#"
            + s.type_flag_field
            + '}}<div class="ro-type">{{type:cloze:'
            + s.cloze_field
            + "}}</div>{{/"
            + s.type_flag_field
            + "}}\n  "
        )
        return dedent(
            """\
            <div id="ro-root" class="ro-root">
              {{{{#{header}}}}}<div class="ro-header">{{{{{header}}}}}</div>{{{{/{header}}}}}
              <div id="ro-stage" class="ro-stage">
                {{{{{image}}}}}
                <svg id="ro-overlay" class="ro-overlay" xmlns="http://www.w3.org/2000/svg"></svg>
              </div>
              {type_block}<div id="ro-ordinal" class="ro-hidden">{{{{cloze:{cloze}}}}}</div>
              <script id="ro-data" type="application/json">{{{{{structures}}}}}</script>
              <script id="ro-config" type="application/json">{config}</script>
              <script>{render_js}</script>
            </div>
            """
        ).format(
            header=s.header_field,
            image=s.image_field,
            cloze=s.cloze_field,
            structures=s.structures_field,
            type_block=type_block,
            config=encode_json_b64(render_config.behaviour()),
            render_js=self._render_js,
        )

    def back(self) -> str:
        s = self._spec
        # The cloze note-type validator requires a literal {{cloze:...}} on BOTH
        # sides. The front already has one; the back reaches it only through
        # {{FrontSide}}, which the validator doesn't follow — so we add a hidden
        # one here. It doubles as the back-side sentinel (#ro-answer) the JS
        # looks for. The renderer reads the active ordinal from the FrontSide
        # copy inside #ro-ordinal, so this extra hidden cloze is inert.
        return dedent(
            """\
            {{{{FrontSide}}}}
            <div id="ro-answer" class="ro-answer" aria-hidden="true">{{{{cloze:{cloze}}}}}</div>
            {{{{#{extra}}}}}<div class="ro-extra">{{{{{extra}}}}}</div>{{{{/{extra}}}}}
            """
        ).format(cloze=s.cloze_field, extra=s.back_extra_field)

    def css(self, render_config: RenderConfig) -> str:
        fingerprint = self.fingerprint(render_config)
        return f"/* ro-fingerprint:{fingerprint} */\n" + self._css_body(render_config)

    def _css_body(self, render_config: RenderConfig) -> str:
        variables = "".join(
            f"  {name}: {value};\n"
            for name, value in render_config.css_variables().items()
        ).rstrip("\n")
        return _CARD_CSS.replace("__RO_VARIABLES__", variables)

    def fingerprint(self, render_config: RenderConfig) -> str:
        """A short hash over everything that affects the rendered card.

        Hashes the *actual* assembled front, back, and CSS body (which already
        embed the renderer JS, the config, and the colour variables), so any
        change — including to the HTML/CSS skeleton — is detected automatically
        and the installer refreshes already-installed note types. The CSS body
        is hashed *without* its own fingerprint comment to avoid self-reference.
        """
        payload = "\n".join(
            [
                str(TEMPLATE_VERSION),
                self.front(render_config),
                self.back(),
                self._css_body(render_config),
            ]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
