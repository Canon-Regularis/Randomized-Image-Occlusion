"""Default configuration values.

These mirror ``config.json`` exactly. Keeping them here as well lets the rest of
the code obtain a complete, valid configuration even in contexts where Anki's
config plumbing is unavailable (tests, the editor preview, etc.).
"""

from __future__ import annotations

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    # Where new notes are placed when the editor's deck picker is unused.
    "deck": "Default",
    # --- behaviour (consumed by the reviewer JS) ---
    # Shortest allowed arrow length, as a fraction of the image's diagonal.
    "min_arrow_fraction": 0.22,
    # Draw a dot on the structure the arrow points at.
    "show_target_dot": True,
    # Text shown inside the prompt box on the question side.
    "prompt_text": "?",
    # How hard the placement algorithm tries to find a clean, in-bounds spot.
    "max_placement_attempts": 48,
    # Show every structure's marker (not only the tested one) so the learner
    # must follow the arrow to the right spot rather than recognise a lone dot.
    "show_decoy_dots": True,
    # Also reveal the OTHER structures' labels at shuffled positions as context
    # (like image occlusion's "hide one, guess one"). Off by default.
    "show_context_labels": False,
    # How you answer: "reveal" (flip to see the label) or "type" (type the
    # structure's name and let Anki grade it for stronger active recall).
    "interaction": "reveal",
    # Which cards to generate per note:
    #   "forward" = name the arrowed structure (default),
    #   "reverse" = given the name, locate the structure,
    #   "both"    = one of each per structure.
    "direction": "forward",
    # --- appearance (consumed by the note-type CSS) ---
    "accent_color": "#e53935",
    "box_fill": "#ffffff",
    "box_text_color": "#202124",
    "target_dot_color": "#e53935",
}
