"""The JSON+base64 wire format used to embed data in a card template.

The reviewer reads base64-of-compact-UTF-8-JSON out of a ``<script>`` element
(``#ro-data``, ``#ro-config``). Encoding as base64 sidesteps every HTML /
``</script>`` / ``{{`` injection hazard that arbitrary label or config text
could otherwise introduce into the template. This module is the single owner of
that exact format, so every producer stays byte-consistent.
"""

from __future__ import annotations

import base64
import json
from typing import Any

__all__ = ["decode_json_b64", "encode_json_b64"]


def encode_json_b64(obj: Any) -> str:
    """Serialise ``obj`` to compact UTF-8 JSON, base64-encoded to ASCII.

    ``allow_nan=False`` guarantees the output is always valid JSON (never a bare
    ``NaN``/``Infinity`` token); callers validate their numbers upstream.
    """
    text = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def decode_json_b64(encoded: str) -> Any:
    """Inverse of :func:`encode_json_b64`: base64-of-UTF-8-JSON back to an object.

    This is what the editor uses to read a stored note back for editing, so it is
    the exact counterpart of the producer and stays in this single module.
    ``base64.b64decode(validate=True)`` rejects stray non-alphabet characters
    rather than silently ignoring them, so a corrupt field surfaces as an error.
    """
    text = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
    return json.loads(text)
