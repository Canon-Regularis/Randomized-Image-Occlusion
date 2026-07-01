# Randomized Image Occlusion — configuration

Changes take effect for **newly reviewed cards**. Behaviour and appearance keys
are baked into the note type's template, so after changing them the note type is
refreshed automatically the next time a profile is opened.

| Key | Meaning |
| --- | --- |
| `deck` | Deck the editor selects by default. Updated when you pick a deck while adding a card. |
| `min_arrow_fraction` | Shortest allowed arrow length, as a fraction of the image's diagonal. Larger values push the prompt box further from the structure. |
| `show_target_dot` | Draw a dot on the structure the arrow points at. |
| `prompt_text` | Text shown inside the prompt box on the question side. |
| `max_placement_attempts` | How hard the placement algorithm tries to find a clean, in-bounds spot before falling back. |
| `show_decoy_dots` | Show a marker on **every** structure, not just the tested one, so you must follow the arrow to the correct spot instead of recognising a lone dot. |
| `show_context_labels` | Reveal the **other** structures' labels at shuffled positions as context (like "hide one, guess one"). Overrides `show_decoy_dots` when on. |
| `interaction` | `"reveal"` = flip the card to see the label; `"type"` = type the structure's name and let Anki grade it (stronger active recall). |
| `direction` | `"forward"` = name the arrowed structure; `"reverse"` = given the name, locate the structure; `"both"` = one of each per structure. Applies to newly created cards. |
| `accent_color` | Colour of the arrow, prompt-box border, and target dot. |
| `box_fill` | Background colour of the prompt box. |
| `box_text_color` | Text colour inside the prompt box. |
| `target_dot_color` | Colour of the target dot (defaults to the accent colour). |

Colours accept any CSS colour string, e.g. `#1a73e8` or `rgb(26,115,232)`.
