# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Changed
- The packaged `.ankiaddon` is now byte-reproducible: building the same source
  twice produces an identical file, so a release artifact can be verified.
- Saving your deck choice now persists only that change rather than a full copy
  of the current defaults, so later improvements to a default setting still
  reach you for options you never customised.

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

[1.1.1]: https://github.com/Canon-Regularis/Genius-Ezra-Idea-trillionaire-potential/releases/tag/v1.1.1
[1.1.0]: https://github.com/Canon-Regularis/Genius-Ezra-Idea-trillionaire-potential/releases/tag/v1.1.0
[1.0.0]: https://github.com/Canon-Regularis/Genius-Ezra-Idea-trillionaire-potential/releases/tag/v1.0.0
