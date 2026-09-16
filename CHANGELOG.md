# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0]

### Upgrading
- **If you edited this note type's card template or its styling** (Tools > Manage
  Note Types > Cards), this release will notice and leave your version alone
  rather than overwriting it. Earlier versions replaced the template and the CSS
  outright on the next profile open, with no warning and nothing to undo. The
  cost of being left alone is that your cards keep the older renderer, so none of
  the reviewer fixes below reach them: copy your changes out, delete the
  customisation, and let the add-on reinstall the template to get both.
- **If you renamed or deleted one of the note type's fields** in Anki, the add-on
  will now refuse to touch the note type and say so, instead of "repairing" it by
  adding an empty field of the original name. That repair was silent and it blanked
  that field on every card of the note type at once. Renaming the field back
  restores everything; the content was never lost.

### Added
- **Space, Return and Enter now drive a single-card cycle.** Anki binds those keys
  to "show answer" on the main window, so they never reached the card and one
  press abandoned the cycle halfway through. They now step the cycle while a
  single-card question is on screen, and behave exactly as before everywhere else
  — including on the last step of a cycle, which hands the key back to Anki so the
  card can still be answered.

### Changed
- The `min_arrow_fraction` and `max_placement_attempts` settings document the
  range they are limited to, which they always had and never mentioned.
- Packaging no longer picks up per-profile files that Anki writes beside the
  add-on, so a build made from a working checkout cannot ship somebody's own
  state.

### Fixed
- **The add-on now loads on Anki 23.10 through 25.06 at all.** It used a Python
  3.10 feature while declaring 23.10 as its minimum, so on every Anki between
  23.10 and 25.06 — all of which ship Python 3.9 — it failed at import and never
  appeared. This was true for the project's whole history.
- **Editing a note no longer moves your review history onto a different
  structure.** Deleting one structure of several used to renumber the survivors,
  and a card's number *is* its identity to Anki: the card that had been asking
  about the aorta silently started asking about something else, keeping the
  interval, ease and history it had earned on the old one. Numbers are now kept
  as they are and the gaps left behind are simply left. Anki keeps the deleted
  structure's card until **Tools > Empty Cards** is run, and already tells you so
  on that card; the add-on no longer draws a prompt box and arrow over the top of
  that message, which had made the leftover card look like an ordinary one.
- **A label containing `<` no longer breaks every other card of its note.** Angle
  brackets in a structure's name were written into the card as markup, which
  swallowed the rest of the note. The same applied to **Header** and **Back
  extra**, where everything after a `<` disappeared.
- **A label ending in `}` is now graded correctly.** It used to make the card's
  cloze end early, so the typed answer was compared against a truncated label and
  could never be right, on every review, for the life of the note.
- **A question side can no longer be solved by elimination.** When the other
  structures were shown as context, each of them got an arrow pointing at it,
  leaving the structure you were being asked about as the only marked spot with
  no arrow — so it could be picked out without identifying anything. The same
  held at every step of a single-card cycle.
- **A card whose image loads slowly no longer comes up blank.** The drawing pass
  ran before the picture had a size, drew nothing, and never tried again.
- **Header and Back extra keep their formatting.** Text you had styled in those
  fields is preserved when you reopen a note, and removing the formatting now
  works — previously an edit that left the plain text unchanged was discarded and
  the old markup put back, so formatting could not be taken off at all.
- **A multi-line Back extra stays multi-line** on the answer side, instead of
  running together into a single paragraph.
- **Pasting a copied image works for more formats.** A JPEG copied from a
  browser on Windows (which names it `.jfif` or `.jpe`), and the `.avif` and
  `.ico` files Anki's own editor already accepted, are now recognised as
  pictures rather than rejected.
- **The configuration screen renders.** Anki's add-on settings showed the raw
  source of the help text instead of the text.
- **Filtered decks are no longer offered** as somewhere to add cards. They cannot
  receive new cards, so choosing one silently lost them.
- A note with more than 500 structures now explains that Anki cannot address that
  many on one note, instead of refusing to open with a three-thousand-character
  message listing every number.
- A note whose stored "next number" had been corrupted no longer refuses every new
  structure for good; an impossible value is now ignored rather than believed.

## [1.2.0]

### Added
- **Paste an image straight from the clipboard**, instead of having to save it to
  a file first. Press **Ctrl+V** or click the new **Paste image** button: a
  screenshot, a picture copied from a web page, or an image file copied in your
  file manager all work, when creating a card and when editing one. Loading from
  a file works exactly as before, and Ctrl+V still pastes *text* wherever you are
  typing — including the label fields beside the image — so it only reaches for a
  picture when you are not in a text field.
  - A copied *file* is used as-is, keeping its own name and bytes.
  - Otherwise the format the source published is preferred over a re-encode, so a
    copied animated GIF stays animated and an SVG stays vector.
  - A screenshot, which the clipboard only offers as a bitmap, is saved as a PNG.
- **Zoom the image while placing markers.** Scroll over the picture to zoom in
  around the pointer, so a structure that was a few pixels across at fit size can
  be marked precisely. There are **-**, **+** and **Fit** buttons beside the
  structure list, and `+`, `-` and `0` do the same from the keyboard.
- **Pan a zoomed image** with the middle mouse button, the right mouse button, or
  by holding **Space** and dragging. Clicking with the left button still places a
  marker at every zoom level, so panning can never drop one by accident.
- **Nudge a marker with the arrow keys.** Click a marker to select it, then use
  the arrow keys to move it one screen pixel at a time (hold **Shift** for ten).
  Zoomed in to 8x that is an eighth of an image pixel - finer than any click.
- **Crosshair guides** follow the pointer across the image, so at high zoom the
  exact spot a marker will land is unambiguous.
- The zoom level is remembered between sessions, in the new `editor_zoom`
  config key, and applies to both creating and editing cards.

### Changed
- Loading or pasting a new image now asks for confirmation first if you have
  already placed markers, since replacing the picture clears them and the editor
  has no undo. Previously a stray **Ctrl+V** could discard the whole labelling
  silently.
- The reviewer is now covered against what it actually draws, not just that it
  drew something. Arrows are checked to end on their structure and to start on
  the prompt box's border, dots to sit on the structures they mark, and the
  randomised placement to vary between reviews and stay put within one. Several
  earlier tests could not tell a working card from one that drew every arrow at
  the top-left corner, or none at all.
- The editor canvas and the paste flow are now covered end-to-end by automated
  tests — marker placement and dragging, zoom and pan, the label list, the
  keyboard shortcuts, and every decision about what to take off the clipboard.
  The suites are checked by mutation testing — `python mutate.py` breaks each
  piece of logic in turn and fails if no test notices — so they go red when the
  behaviour they describe changes, rather than merely running the code. The
  catalogue runs in CI and is itself checked on every ordinary test run, so an
  entry cannot stop matching the code it is meant to be guarding.
- The paste flow's decisions — which clipboard source to prefer, where a pasted
  image is written, when the zoom level is saved, and what to warn about before
  replacing an image — moved out of the Qt dialog into plain modules. Anki's
  libraries are not available to the test suite, so logic left inside a dialog
  cannot be tested at all; the same split already existed for the note savers
  and the config service.

### Fixed
- **Repositioning a marker no longer swallows your next click.** After dragging a
  marker (or panning with the middle/right button), the next structure you tried
  to mark was silently ignored and you had to click twice. The editor's "ignore
  the click that follows a drag" flag was being left set with nothing able to
  clear it; a new press now always clears it.
- A hand tremor during a click is no longer treated as a drag, so a press that
  moves a pixel or two can no longer eat the click that follows it.
- Switching to another application while holding **Space** no longer leaves the
  editor stuck in panning mode. Previously the key release went to the other
  application, and on returning, dragging a marker moved the picture instead of
  the marker until Space was pressed and released again.
- Loading or pasting a replacement image now keeps the zoom you are working at.
  It used to jump back to the level the editor opened with — so zooming in and
  replacing the image lost your magnification, and pressing **Fit** before
  replacing it was undone.
- Marker positions on the canvas are now measured the same way whether they are
  being drawn or being read from a click, removing a sub-pixel drift between the
  two. The reviewer had already been fixed this way; the editor had not.
- A drag whose mouse release goes missing (the pointer leaves the window at the
  wrong moment) no longer strands the editor in a state where no further marker
  can be dragged.
- Replacing the image while a card is being saved is no longer possible via
  **Ctrl+V**; the shortcut is now frozen along with the buttons, so the markers
  being saved always belong to the picture they were placed on.
- A failed image paste can no longer leave the previous pasted image truncated:
  the new file is written alongside and swapped in only once it is complete.
- **The Browse window sorts on the right field again after a repair.** A note
  type records its sort column as a *position* in its field list, so whenever the
  **Header** field had to be added back — because an older version of the add-on
  created the note type without it, or because it was deleted by hand — it
  returned at the end of the list while the recorded position stayed where it
  was. Browse then sorted on whatever had moved into that slot, showing the
  base64 payload instead of your headers. The add-on now checks the sort field on
  every start and puts it right.
- **Changing one setting no longer freezes all the others.** Saving a deck (or,
  now, a zoom level) wrote the entire configuration back to your profile,
  including every key you had never touched. Those keys were then pinned to
  whatever the default happened to be that day, so later improvements to a
  default silently never reached you. Only values you have actually changed are
  stored now.

## [1.1.1]

### Fixed
- Switching a note's mode to **Single** and back to **Multi** no longer silently
  changes how it's answered. Single mode locks the **Type the answer** option (on
  for forward/both, off for reverse); returning to Multi now restores the choice
  you had made instead of leaving single mode's forced value behind — so a note
  can no longer be saved as typed when you meant reveal, or vice-versa.
- Saving a card now disables **Save** until the save finishes, so an impatient
  second click can no longer add a duplicate note. If a save fails, the error is
  shown and you can try again.
- Editing the **same** note from the Browser can no longer open two edit dialogs
  at once, which previously let the second save silently overwrite the first.
- **Reverse** ("locate the structure") cards no longer reveal the answer on the
  question side: with decoy dots turned off, the single target dot is now hidden
  until you flip to the answer.
- Editing an older note no longer silently turns its **context labels** off. A
  note saved before per-note context labels existed now keeps rendering the way
  it did (following your global setting) after an edit.
- A corrupt or absurd `max_placement_attempts` value in `config.json` can no
  longer freeze the reviewer; it is capped to a safe range.
- A structure label containing doubled cloze markers (e.g. `{{{{…::::…}}}}`) no
  longer slips a live cloze into the card, which could make Anki generate an
  extra phantom card with no matching structure; such labels are now fully
  neutralised.
- Cancelling the editor (Cancel or Escape) in the brief moment while a card is
  being saved no longer creates the card you just cancelled, and can no longer
  crash by acting on the already-closed dialog.
- A wildly out-of-range number in `config.json` (a huge value in a decimal field
  such as the minimum arrow length) no longer breaks note-type installation and
  card saving; it falls back to the default like other invalid config values.
- Typing an accented answer (e.g. *café*, *Müller*, *Sjögren*) is now graded
  correctly even when the stored label and what you type use different Unicode
  forms (composed vs decomposed) — which can happen across platforms/keyboards.
  The answer and label are normalised before comparison, so a visually identical
  answer is no longer marked wrong.
- On a device where the webview's session storage is full or unavailable, the
  front and back of a card could disagree on the randomised layout (so the arrow
  and answer wouldn't match the question). The layout seed now stays consistent
  even in that degraded state.
- A long structure label (e.g. a full anatomical name) no longer runs its prompt
  box off the edge of the image or phone screen with the text clipped: long
  labels now wrap onto multiple lines and the box is kept on-screen, while the
  front and back still line up.

### Changed
- The packaged `.ankiaddon` is now byte-reproducible: building the same source
  twice produces an identical file, so a release artifact can be verified.
- Saving your deck choice now persists only that change rather than a full copy
  of the current defaults, so later improvements to a default setting still
  reach you for options you never customised.
- Documented a limitation of Anki's built-in **type the answer** grading in
  multi-card mode: a label containing `::`, `{{` or `}}` (e.g. `std::vector`) is
  compared against an escaped copy of itself, so the correct answer is marked
  wrong. Use *reveal* or single-card mode for such labels. (README, `config.md`.)
- Documented that `show_target_dot`, `show_decoy_dots` and `show_context_labels`
  shape **multi-card** mode only: a single card always dots every marker, because
  a lone dot would give away a *locate it* marker's answer and the running answer
  key needs them all.
- The reviewer is now covered end-to-end by automated tests: the multi-card
  renderer and the single-card cycler are driven against a headless DOM (prompt
  text, arrow, dots, the type-answer box, front/back layout parity, typed grading
  and the full cycle), alongside geometry checks for markers on an image's corners
  and edges. A CI pipeline runs the lint, type, Python and JavaScript suites and
  publishes the built add-on on every push and pull request.

## [1.1.0]

### Added
- **Make occlusion cards from Anki's Add window.** With the **Randomized Image
  Occlusion** note type selected in the **Add** window, click the **Occlusion**
  toolbar button to open the marking canvas — pick a deck, mark up the image, and
  **Save** adds the card directly, exactly like the Tools‑menu creator (same deck
  picker and one‑step save). On any other note type the button asks you to switch
  to the occlusion note type first, so it never appears out of context.
- **Edit existing cards.** Right-click a Randomized Occlusion note in the Browser
  and choose **Edit with Randomized Image Occlusion** to reopen it in the marking
  dialog with its image, markers, and options restored. Save updates the note
  (adding or removing cards if the marker count changed) in a single undo step.
- **Drag to reposition markers.** In the editor, drag any marker to move it
  instead of deleting and re-adding it.

### Changed
- The marking dialog's persistence is now a small strategy (add / edit), so the
  same canvas UI drives every flow.
- The Save flow now freezes the image controls while it reads the markers, so a
  card can never be saved with markers that belong to a different image.

### Fixed
- The **both** direction now works. Previously it did nothing in single-card mode
  and split each structure into two fixed cards in multi mode; now every card
  randomly tests the structure **forwards** (name the arrowed structure) or
  **backwards** (locate it from its name), re-rolled each review. In single-card
  mode each marker in the cycle gets its own random direction — forward markers
  are typed, backward markers ask you to locate the named structure and reveal an
  arrow to confirm.
- The editor dialog is now released when closed, so repeatedly editing notes no
  longer leaves hidden dialogs in memory for the session.
- Adding or editing a note can no longer corrupt Anki's undo queue when the
  chosen image or the note becomes unavailable mid-save: the image import and
  note load now happen before the undo step is opened.
- On a small image with a large minimum arrow, the prompt box could land almost
  on top of the structure (an invisible arrow); placement now falls back to the
  farthest valid point so the arrow always stays visible.
- A non-finite value in `config.json` (e.g. `Infinity`) no longer crashes config
  loading — it falls back to the default.
- The **Occlusion** button in the Add window no longer becomes unclickable after
  switching note type away from and back to Randomized Image Occlusion. Anki
  disables add-on buttons while no field is focused; the button is now marked
  permanent so it stays usable regardless of focus.

## [1.0.0]

### Added
- Initial release: image occlusion that **randomises the prompt-box position on
  every review** and draws a leader-line arrow to the structure, so recall can't
  lean on where the box usually sits.
- Per-note study options:
  - **Directions** — forward (name the structure), reverse (locate it), or both.
  - **Type-to-answer** — type the label and let Anki grade it.
  - **Context labels** — reveal the surrounding labels while you answer.
  - **Decoy dots** — mark every structure so you must follow the arrow.
  - **Single-card mode** — one card that cycles through every label in a fresh
    random order each review, with a running counter.
- Light/dark mode support and phone rendering (AnkiDroid / AnkiMobile) with no
  add-on required on the device, since the renderer is baked into the card.
- Configurable colours, minimum arrow length, and default study mode.

[1.3.0]: https://github.com/Canon-Regularis/Randomized-Image-Occlusion/releases/tag/v1.3.0
[1.2.0]: https://github.com/Canon-Regularis/Randomized-Image-Occlusion/releases/tag/v1.2.0
[1.1.1]: https://github.com/Canon-Regularis/Randomized-Image-Occlusion/releases/tag/v1.1.1
[1.1.0]: https://github.com/Canon-Regularis/Randomized-Image-Occlusion/releases/tag/v1.1.0
[1.0.0]: https://github.com/Canon-Regularis/Randomized-Image-Occlusion/releases/tag/v1.0.0
