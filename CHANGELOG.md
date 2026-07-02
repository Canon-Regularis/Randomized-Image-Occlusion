# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0]

### Added
- **Make occlusion cards from Anki's Add window.** With the Randomized Image
  Occlusion note type selected in **Add**, click the **Occlusion** toolbar button
  to mark the image up on the canvas instead of editing the raw fields by hand.
  Save stages the fields and Anki's **Add** button creates the card. The internal
  fields (Image, Structures, Ordinals, TypeAnswer) are collapsed by default to
  keep the Add window clean. (The canvas is never launched automatically — the
  Add window opens normally so you can pick your note type first.)
- **Edit existing cards.** Right-click a Randomized Occlusion note in the Browser
  and choose **Edit with Randomized Image Occlusion** to reopen it in the marking
  dialog with its image, markers, and options restored. Save updates the note
  (adding or removing cards if the marker count changed) in a single undo step.
- **Drag to reposition markers.** In the editor, drag any marker to move it
  instead of deleting and re-adding it.

### Changed
- The marking dialog's persistence is now a small strategy (add / edit /
  Add-window staging), so the same canvas UI drives every flow.
- The Save flow now freezes the image controls while it reads the markers, so a
  card can never be saved with markers that belong to a different image.

### Fixed
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

[1.1.0]: https://github.com/Canon-Regularis/Genius-Ezra-Idea-trillionaire-potential/releases/tag/v1.1.0
[1.0.0]: https://github.com/Canon-Regularis/Genius-Ezra-Idea-trillionaire-potential/releases/tag/v1.0.0
