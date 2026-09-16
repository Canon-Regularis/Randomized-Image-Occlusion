"""Working out what, if anything, on the clipboard is an image we can use.

Kept free of Qt so it can be unit tested directly: the dialog reads the
``QMimeData`` and hands the plain facts over as a :class:`ClipboardOffer`, and
these functions decide which of them to take.

Three sources are worth trying, in this order:

1. **A local file URL**, as when copying a picture in Explorer/Finder. Taking
   itself preserves the original bytes *and* its name, which is what ends up in
   the media folder.
2. **Bytes in a known image format**: a browser publishing ``image/png``
   alongside its own formats. Preferred over a re-encode because it is exactly
   what the source app meant to hand over (an animated GIF stays animated).
3. **Whatever Qt can decode into a bitmap**: the screenshot case, handled by
   the caller as a PNG. Nothing here to decide.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "IMAGE_FILE_FILTER",
    "PASTE_SUFFIX",
    "SUPPORTED_SUFFIXES",
    "ClipboardOffer",
    "ClipboardSource",
    "PasteChoice",
    "choose_local_file",
    "choose_mime",
    "paste_filename",
    "resolve_paste",
    "suffix_for_mime",
]

#: Every extension the add-on will open, however the image arrives. The file
#: picker's filter is generated from it below, so the two ways in (choosing a
#: file and pasting one) cannot start disagreeing about what an image is.
#: ``.jfif``/``.jpe`` because Windows names JPEGs that way when they come from
#: a browser, and ``.avif``/``.ico`` because Anki's own editor accepts them; all
#: four were refused here with "There is no image on the clipboard", which names
#: the wrong cause. ``.bmp`` is deliberately pickable but not pasteable.
#: :data:`_MIME_SUFFIXES` is unchanged: it decides what *written* bytes are
#: called, and every JPEG the add-on writes should still be called ``.jpg``.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".gif", ".webp",
        ".avif", ".bmp", ".ico", ".svg",
    }
)

#: The ``QFileDialog`` name filter for :data:`SUPPORTED_SUFFIXES`.
IMAGE_FILE_FILTER = "Images (" + " ".join(
    f"*{suffix}" for suffix in sorted(SUPPORTED_SUFFIXES)
) + ")"

#: The extension used when the bytes have to be re-encoded by the caller.
PASTE_SUFFIX = ".png"

# Ordered by preference, not by quality alone:
#   * SVG and GIF come first because a re-encode would lose something the other
#     formats cannot carry back (vectors, animation frames);
#   * PNG next, being lossless and universally correct;
#   * WEBP and JPEG only if nothing better is on offer.
# BMP is deliberately absent: it is uncompressed, so falling through to the
# caller's PNG re-encode produces a smaller file with no loss.
_MIME_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("image/svg+xml", ".svg"),
    ("image/gif", ".gif"),
    ("image/png", ".png"),
    ("image/webp", ".webp"),
    ("image/jpeg", ".jpg"),
)


@dataclass(frozen=True)
class ClipboardOffer:
    """What the clipboard is offering, as plain Python.

    ``urls`` holds local filesystem paths; anything the clipboard offered that
    is not a local file (a web address, say) arrives as an empty string, exactly
    as ``QUrl.toLocalFile()`` reports it.
    """

    urls: tuple[str, ...] = ()
    formats: tuple[str, ...] = ()


def choose_local_file(offer: ClipboardOffer) -> str | None:
    """The first copied file that looks like an image we can open."""
    for url in offer.urls:
        if _suffix_of(url) in SUPPORTED_SUFFIXES:
            return url
    return None


def choose_mime(offer: ClipboardOffer) -> str | None:
    """The best image format on offer, or ``None`` to fall back to a re-encode."""
    available = set(offer.formats)
    for mime, _suffix in _MIME_SUFFIXES:
        if mime in available:
            return mime
    return None


def suffix_for_mime(mime: str) -> str:
    """The file extension for a MIME type :func:`choose_mime` returned."""
    for candidate, suffix in _MIME_SUFFIXES:
        if candidate == mime:
            return suffix
    return PASTE_SUFFIX


def paste_filename(stamp: str, suffix: str) -> str:
    """The name a pasted image is written under.

    This becomes the media filename, so it is worth being both readable and
    hard to collide with. ``stamp`` is expected to be a timestamp; anything odd
    in it is stripped rather than trusted, since it reaches the filesystem.
    """
    safe = "".join(ch for ch in stamp if ch.isalnum() or ch in "-_")
    if suffix not in SUPPORTED_SUFFIXES:
        suffix = PASTE_SUFFIX
    return f"paste-{safe or 'image'}{suffix}"


class ClipboardSource(Protocol):
    """The little of a clipboard this module needs.

    Deliberately lazy: ``data_for`` and ``bitmap`` are only called if the step
    before them found nothing, so a paste never materialises every format the
    clipboard happens to advertise.
    """

    def offer(self) -> ClipboardOffer:
        """What the clipboard is advertising."""

    def data_for(self, mime: str) -> bytes:
        """The bytes published under ``mime``."""

    def bitmap(self) -> Any | None:
        """Whatever the clipboard can render as an image, or ``None``."""


@dataclass(frozen=True)
class PasteChoice:
    """Where a pasted image is coming from. Exactly one field is set."""

    #: An existing file to import as-is.
    path: str | None = None
    #: Bytes to write out, in the format the source published.
    data: bytes | None = None
    #: A bitmap the caller must encode itself.
    bitmap: Any = None
    #: The extension ``data`` should be written under.
    suffix: str = PASTE_SUFFIX


def resolve_paste(source: ClipboardSource) -> PasteChoice | None:
    """Pick what to paste, or ``None`` if there is no image to be had."""
    offer = source.offer()

    # A copied file is best taken as-is: same bytes, and its own name is the one
    # that ends up in the media folder.
    path = choose_local_file(offer)
    if path is not None:
        return PasteChoice(path=path)

    # Otherwise prefer the source's own encoding over a re-encode, so an
    # animated GIF or an SVG survives the trip intact. A format that is
    # advertised but yields nothing falls through rather than failing the paste.
    mime = choose_mime(offer)
    if mime is not None:
        data = source.data_for(mime)
        if data:
            return PasteChoice(data=data, suffix=suffix_for_mime(mime))

    # Last resort, and the common one: a screenshot, which the clipboard only
    # offers as a bitmap.
    bitmap = source.bitmap()
    if bitmap is not None:
        return PasteChoice(bitmap=bitmap)
    return None


def _suffix_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()
