"""Somewhere to put a pasted image until the collection takes it.

An image pasted from the clipboard has no file of its own, but everything
downstream (the media import, the note's ``<img>`` field) works from a path.
So the bytes are written into a scratch directory and then travel exactly the
route a chosen file does.

Kept free of Qt so it can be unit tested: the caller supplies the bytes (or, for
a bitmap, something that can save itself to a path), and this raises ``OSError``
rather than knowing how to show a warning.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime

from .clipboard_image import paste_filename

__all__ = ["PasteScratch"]

#: Suffix a paste is written under before it is swapped into place.
PARTIAL = ".part"


class PasteScratch:
    """A per-dialog directory of pasted images, removed when the dialog is done.

    ``make_dir`` and ``now`` are injectable so the naming and the directory's
    lifetime can be exercised without touching a real clock or temp space.
    """

    def __init__(
        self,
        *,
        make_dir: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._make_dir = make_dir or (lambda: tempfile.mkdtemp(prefix="randomized-occlusion-"))
        self._now = now or datetime.now
        self._directory: str | None = None
        #: Distinguishes pastes made within the same second. The stamp alone
        #: collided, and a colliding write replaced the bytes of the paste the
        #: canvas was still displaying.
        self._sequence = 0

    @property
    def directory(self) -> str | None:
        """The scratch directory, or ``None`` if nothing has been pasted yet."""
        return self._directory

    def target(self, suffix: str) -> str:
        """The path a paste with this extension is written to.

        Every call returns a distinct path. The stamp only resolves to the
        second, so two pastes within one second used to collide -- and the
        second write landed on the file the dialog was still pointing at, so
        declining the replacement left the canvas showing one image while the
        save used another. :meth:`write_bytes` keeps each write atomic.
        """
        if self._directory is None:
            self._directory = self._make_dir()
        self._sequence += 1
        stamp = f'{self._now().strftime("%Y%m%d-%H%M%S")}-{self._sequence}'
        return os.path.join(self._directory, paste_filename(stamp, suffix))

    def write_bytes(self, data: bytes, suffix: str) -> str:
        """Write ``data`` and return its path.

        Staged under :data:`PARTIAL` and swapped into place, so a write that
        fails part-way cannot leave a previous paste truncated behind it; the
        canvas would go on showing an image the file no longer contains.
        """
        return self._stage(suffix, lambda path: _write(path, data))

    def write_via(self, save: Callable[[str], bool], suffix: str) -> str:
        """Write using ``save``, for a bitmap that knows how to encode itself.

        ``save`` is handed a path and returns whether it succeeded, which is the
        shape of ``QImage.save``.
        """

        def attempt(path: str) -> None:
            if not save(path):
                raise OSError("the image could not be encoded")

        return self._stage(suffix, attempt)

    def discard(self) -> None:
        """Drop the directory. Idempotent, and never raises.

        Called from whichever of several exits happens to be last, so it must
        tolerate being called twice, and a file left behind is a temp file the
        system will reclaim, which is a better outcome than raising out of a
        close handler.
        """
        directory, self._directory = self._directory, None
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)

    def _stage(self, suffix: str, write: Callable[[str], None], /) -> str:
        path = self.target(suffix)
        partial = path + PARTIAL
        try:
            write(partial)
            os.replace(partial, path)
        except OSError:
            # Remove the partial file so a later paste does not see it.
            with contextlib.suppress(OSError):
                os.unlink(partial)
            raise
        return path


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
