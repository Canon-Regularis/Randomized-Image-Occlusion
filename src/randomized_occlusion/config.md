# Randomized Image Occlusion — configuration

Anki renders this file with its own Markdown, which has tables switched off, so
the keys are a list: a table here comes out as a wall of literal `|` characters.

**Appearance keys** (`min_arrow_fraction`, `show_target_dot`, `prompt_text`,
`max_placement_attempts`, `show_decoy_dots`, `accent_color`, `box_fill`,
`box_text_color`, `target_dot_color`) are baked into the note type's template, so
changing one takes effect for **every** card once the note type is refreshed,
which happens automatically the next time a profile is opened.

**Card-shape keys** (`direction`, `card_mode`, `interaction`,
`show_context_labels`) are stored on each note as it is saved. Changing one here
seeds the editor for the notes you create next; notes that already exist keep
whatever they were saved with.

**Editor keys** (`deck`, `editor_zoom`) only affect the marking dialog, and the
dialog writes them back as you use it.

- `deck` -- Deck the editor selects by default. Updated when you pick a deck
  while adding a card.
- `editor_zoom` -- Zoom the marking canvas opens at, as a multiple of the fitted
  size (`1.0` shows the whole image, `4.0` is 4x). Updated as you zoom while
  marking up, so the editor reopens where you left it. Clamped to 1-8; it is a
  multiple of *fit*, not of the image's own pixels, so it means the same thing on
  any image.
- `min_arrow_fraction` -- Shortest allowed arrow length, as a fraction of the
  image's diagonal. Larger values push the prompt box further from the structure.
- `show_target_dot` -- Draw a dot on the structure the arrow points at. (Hidden
  on a *reverse* question side, where a lone dot would give away the location
  you're being asked to find.)
- `prompt_text` -- Text shown inside the prompt box on the question side.
- `max_placement_attempts` -- How hard the placement algorithm tries to find a
  clean, in-bounds spot before falling back.
- `show_decoy_dots` -- Show a marker on **every** structure, not just the tested
  one, so you must follow the arrow to the correct spot instead of recognising a
  lone dot.
- `show_context_labels` -- Reveal the **other** structures' labels at shuffled
  positions as context (like "hide one, guess one"). Honours `show_decoy_dots`
  for those other structures; on a *reverse* question side the structure you are
  being asked to find is never dotted, or it would be the one dot with no arrow
  pointing at it.
- `interaction` -- `"reveal"` = flip the card to see the label; `"type"` = type
  the structure's name and let Anki grade it (stronger active recall). In
  **multi-card** mode Anki's own grader compares against an escaped copy of the
  label, so a label containing `::`, `{{` or `}}` (e.g. `std::vector`) won't
  match what you type -- use `"reveal"` or single-card mode for those.
- `direction` -- `"forward"` = name the arrowed structure; `"reverse"` = given
  the name, locate the structure; `"both"` = a random mix, re-rolled each review
  (per marker in single-card mode).
- `card_mode` -- `"multi"` = one card per structure (default); `"single"` = one
  card that cycles through every structure, re-randomised each review (forward
  markers are typed, reverse located).
- `accent_color` -- Colour of the arrow, the prompt-box border, the single-card
  mode buttons and focus ring, and the markers you place in the marking editor.
  It does **not** colour the target dots drawn on the card: those follow
  `target_dot_color`.
- `box_fill` -- Background colour of the prompt box.
- `box_text_color` -- Text colour inside the prompt box.
- `target_dot_color` -- Colour of the target dot on the card. Independent of
  `accent_color`; the shipped value merely happens to match it, so recolouring a
  card means changing both.

Colours are written straight into the note type's stylesheet, so they are checked
against a deliberately conservative allow-list: a `#rgb`, `#rgba`, `#rrggbb` or
`#rrggbbaa` hex value, a named colour such as `rebeccapurple`, or an `rgb()`,
`rgba()`, `hsl()` or `hsla()` function. Anything else -- `color-mix()`, `lab()`,
`oklch()`, `var(--x)` -- is rejected and the shipped default is used instead.

**Single-card mode** dots only the markers you have already answered, plus the
current one once it is revealed -- that is, exactly those an arrow points at.
`show_target_dot` switches those dots off, here as everywhere. `show_decoy_dots`
and `show_context_labels` shape **multi-card** mode only: a marker still to come
cannot be dotted without giving the last one away, and the other labels are
already on show as the answer key builds up.

It used to dot every marker, which is what gave the answer away: on the last
marker of the cycle every other structure had an arrow, so the single dot without
one was the answer. A marker still to come is simply not dotted.
