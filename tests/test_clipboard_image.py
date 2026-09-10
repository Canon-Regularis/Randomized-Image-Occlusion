from __future__ import annotations

from randomized_occlusion.editor.clipboard_image import (
    IMAGE_FILE_FILTER,
    PASTE_SUFFIX,
    SUPPORTED_SUFFIXES,
    ClipboardOffer,
    PasteChoice,
    choose_local_file,
    choose_mime,
    paste_filename,
    resolve_paste,
    suffix_for_mime,
)

# What Qt reports for a non-local URL (a web address dragged from a browser).
NOT_LOCAL = ""


def test_choose_local_file_selects_a_copied_image():
    offer = ClipboardOffer(urls=("/home/me/heart.png",), formats=("text/uri-list",))
    assert choose_local_file(offer) == "/home/me/heart.png"


def test_choose_local_file_ignores_non_images():
    offer = ClipboardOffer(urls=("/home/me/notes.pdf", "/home/me/data.csv"))
    assert choose_local_file(offer) is None


def test_choose_local_file_selects_the_first_image():
    offer = ClipboardOffer(urls=("/tmp/readme.txt", "/tmp/a.jpg", "/tmp/b.png"))
    assert choose_local_file(offer) == "/tmp/a.jpg"


def test_choose_local_file_skips_non_local_urls():
    # Qt hands back an empty string for anything that is not a file on disk, so
    # a web address must not be mistaken for a path.
    offer = ClipboardOffer(urls=(NOT_LOCAL, "/tmp/real.png"))
    assert choose_local_file(offer) == "/tmp/real.png"
    assert choose_local_file(ClipboardOffer(urls=(NOT_LOCAL,))) is None


def test_choose_local_file_matches_extensions_case_insensitively():
    offer = ClipboardOffer(urls=("/tmp/SCAN.JPEG",))
    assert choose_local_file(offer) == "/tmp/SCAN.JPEG"


def test_file_filter_matches_supported_suffixes():
    # Both ways in are generated from one set, so this only has to prove the
    # filter is well-formed and covers it; they cannot drift apart.
    assert IMAGE_FILE_FILTER.startswith("Images (") and IMAGE_FILE_FILTER.endswith(")")
    tokens = IMAGE_FILE_FILTER[len("Images (") : -1].split()
    assert {token.lstrip("*") for token in tokens} == set(SUPPORTED_SUFFIXES)
    assert all(token.startswith("*.") for token in tokens)


def test_empty_offer_selects_nothing():
    assert choose_local_file(ClipboardOffer()) is None
    assert choose_mime(ClipboardOffer()) is None


def test_choose_mime_prefers_a_published_format():
    offer = ClipboardOffer(formats=("text/html", "image/png", "application/x-qt-image"))
    assert choose_mime(offer) == "image/png"


def test_choose_mime_ranks_svg_and_gif_above_png():
    # Re-encoding these to PNG would drop the animation frames or the vectors,
    # which nothing downstream could put back.
    assert choose_mime(ClipboardOffer(formats=("image/png", "image/gif"))) == "image/gif"
    assert (
        choose_mime(ClipboardOffer(formats=("image/png", "image/svg+xml")))
        == "image/svg+xml"
    )


def test_choose_mime_ranks_png_above_webp_and_jpeg():
    offer = ClipboardOffer(formats=("image/jpeg", "image/webp", "image/png"))
    assert choose_mime(offer) == "image/png"


def test_choose_mime_returns_none_for_bitmap_only():
    # BMP is uncompressed, so letting the caller re-encode as PNG is strictly
    # better; application/x-qt-image is Qt's own bitmap handle, not a file format.
    offer = ClipboardOffer(formats=("image/bmp", "application/x-qt-image"))
    assert choose_mime(offer) is None


def test_choose_mime_ignores_unknown_formats():
    assert choose_mime(ClipboardOffer(formats=("text/plain", "text/html"))) is None


def test_suffix_for_mime_maps_each_format_exactly():
    # Not merely "some supported extension": an SVG saved as .png would be
    # rasterised nonsense, and Anki names the media file from this suffix.
    assert suffix_for_mime("image/svg+xml") == ".svg"
    assert suffix_for_mime("image/gif") == ".gif"
    assert suffix_for_mime("image/png") == ".png"
    assert suffix_for_mime("image/webp") == ".webp"
    assert suffix_for_mime("image/jpeg") == ".jpg"


def test_suffix_for_mime_returns_a_supported_suffix():
    for mime in ("image/svg+xml", "image/gif", "image/png", "image/webp", "image/jpeg"):
        assert suffix_for_mime(mime) in SUPPORTED_SUFFIXES


def test_suffix_for_mime_falls_back_to_png():
    assert suffix_for_mime("image/heif") == PASTE_SUFFIX


def test_paste_filename_keeps_the_suffix():
    assert paste_filename("20260908-134500", ".png") == "paste-20260908-134500.png"


def test_paste_filename_strips_unsafe_characters():
    # The name reaches the filesystem and then the media folder, so a stamp is
    # sanitised rather than trusted.
    assert paste_filename("../../etc/passwd", ".png") == "paste-etcpasswd.png"
    assert paste_filename("2026 09 08", ".png") == "paste-20260908.png"


def test_paste_filename_handles_an_empty_stamp():
    assert paste_filename("", ".png") == "paste-image.png"
    assert paste_filename("///", ".jpg") == "paste-image.jpg"


def test_paste_filename_rejects_an_unsupported_suffix():
    assert paste_filename("stamp", ".exe") == "paste-stamp.png"
    assert paste_filename("stamp", "") == "paste-stamp.png"


def test_bmp_is_a_supported_file_but_not_a_clipboard_format():
    # A deliberate asymmetry, and the only place the two lists disagree: a .bmp
    # FILE is copied as-is, but a clipboard offering raw bitmap data is better
    # served by falling through to the caller's PNG re-encode, which is smaller
    # and lossless. Pinned so it reads as intent rather than an oversight.
    assert ".bmp" in SUPPORTED_SUFFIXES
    assert choose_local_file(ClipboardOffer(urls=("C:/pictures/scan.bmp",))) == (
        "C:/pictures/scan.bmp"
    )
    assert choose_mime(ClipboardOffer(formats=("image/bmp",))) is None


# ------------------------------------------------- choosing what to paste


class FakeClipboard:
    """A clipboard that records which of its sources were actually consulted."""

    def __init__(self, *, urls=(), formats=(), data=None, bitmap=None):
        self._offer = ClipboardOffer(urls=tuple(urls), formats=tuple(formats))
        self._data = data or {}
        self._bitmap = bitmap
        self.consulted = []

    def offer(self):
        self.consulted.append("offer")
        return self._offer

    def data_for(self, mime):
        self.consulted.append(f"data:{mime}")
        return self._data.get(mime, b"")

    def bitmap(self):
        self.consulted.append("bitmap")
        return self._bitmap


def test_resolve_paste_prefers_a_copied_file():
    clipboard = FakeClipboard(
        urls=("C:/pictures/heart.png",),
        formats=("image/png",),
        data={"image/png": b"bytes"},
        bitmap=object(),
    )
    choice = resolve_paste(clipboard)

    assert choice == PasteChoice(path="C:/pictures/heart.png")
    assert clipboard.consulted == ["offer"], "the other sources must not be touched"


def test_resolve_paste_prefers_published_bytes_over_a_bitmap():
    marker = object()
    clipboard = FakeClipboard(
        formats=("image/gif", "image/png"),
        data={"image/gif": b"GIF89a"},
        bitmap=marker,
    )
    choice = resolve_paste(clipboard)

    assert choice == PasteChoice(data=b"GIF89a", suffix=".gif")
    assert "bitmap" not in clipboard.consulted, "the bitmap must not be materialised"


def test_resolve_paste_falls_back_to_the_bitmap():
    marker = object()
    clipboard = FakeClipboard(bitmap=marker)
    choice = resolve_paste(clipboard)

    assert choice == PasteChoice(bitmap=marker)


def test_resolve_paste_falls_through_an_empty_format():
    # Some applications list a format they cannot actually produce. That must
    # not abort the paste; the bitmap is very likely still there.
    marker = object()
    clipboard = FakeClipboard(
        formats=("image/png",),
        data={"image/png": b""},
        bitmap=marker,
    )
    choice = resolve_paste(clipboard)

    assert choice == PasteChoice(bitmap=marker)
    assert clipboard.consulted == ["offer", "data:image/png", "bitmap"]


def test_resolve_paste_continues_past_a_non_image_file():
    clipboard = FakeClipboard(
        urls=("C:/documents/notes.txt",),
        formats=("image/png",),
        data={"image/png": b"bytes"},
    )
    assert resolve_paste(clipboard) == PasteChoice(data=b"bytes", suffix=".png")


def test_resolve_paste_returns_none_for_an_empty_clipboard():
    clipboard = FakeClipboard()
    assert resolve_paste(clipboard) is None
    assert clipboard.consulted == ["offer", "bitmap"]
