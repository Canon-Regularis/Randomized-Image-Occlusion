from __future__ import annotations

from randomized_occlusion.editor.bridge import MarkerBridge


class Spy:
    def __init__(self):
        self.ready = 0
        self.counts = []
        self.zooms = []
        self.text_focus = []
        self.broken = []

    def on_ready(self):
        self.ready += 1

    def on_count(self, n):
        self.counts.append(n)

    def on_zoom(self, z):
        self.zooms.append(z)

    def on_text_focus(self, focused):
        self.text_focus.append(focused)

    def on_broken(self, broken):
        self.broken.append(broken)


def _bridge(spy):
    return MarkerBridge(
        on_ready=spy.on_ready,
        on_count=spy.on_count,
        on_zoom=spy.on_zoom,
        on_text_focus=spy.on_text_focus,
        on_broken=spy.on_broken,
    )


def test_ready_message_invokes_callback():
    spy = Spy()
    _bridge(spy).handle("ro:ready")
    assert spy.ready == 1


def test_count_message_parses_integer():
    spy = Spy()
    _bridge(spy).handle("ro:count:3")
    assert spy.counts == [3]


def test_a_negative_count_is_floored_at_zero():
    # The count gates the Save button; a negative one would make "has markers"
    # nonsense. The canvas cannot send one today, but the bridge is the boundary
    # and treats everything crossing it as untrusted.
    spy = Spy()
    _bridge(spy).handle("ro:count:-3")
    assert spy.counts == [0]


def test_count_message_with_garbage_defaults_to_zero():
    spy = Spy()
    _bridge(spy).handle("ro:count:abc")
    assert spy.counts == [0]


def test_zoom_message_parses_float():
    spy = Spy()
    _bridge(spy).handle("ro:zoom:2.5")
    assert spy.zooms == [2.5]


def test_zoom_message_with_garbage_falls_back_to_fit():
    # The canvas is the only sender, but a malformed message must never raise
    # out of Anki's webview callback, and NaN/inf would poison the config.
    spy = Spy()
    bridge = _bridge(spy)
    for raw in ("abc", "", "nan", "inf", "-inf"):
        bridge.handle(f"ro:zoom:{raw}")
    assert spy.zooms == [1.0, 1.0, 1.0, 1.0, 1.0]


def test_text_focus_message_parses_the_flag():
    # Reported when a label field on the canvas gains or loses focus, so the
    # dialog can let Ctrl+V mean "paste text" there instead of "paste image".
    spy = Spy()
    bridge = _bridge(spy)
    bridge.handle("ro:textfocus:1")
    bridge.handle("ro:textfocus:0")
    bridge.handle("ro:textfocus:whatever")  # anything but "1" means not focused
    assert spy.text_focus == [True, False, False]


def test_foreign_messages_are_ignored():
    spy = Spy()
    bridge = _bridge(spy)
    bridge.handle("anki:something")
    bridge.handle("")
    bridge.handle("ro:unknown:1")
    assert spy.ready == 0
    assert spy.counts == [] and spy.zooms == [] and spy.text_focus == []


def test_broken_image_message_is_routed():
    # Its own message rather than a marker count of zero: the count also decides
    # whether replacing the image asks "the N markers you have placed will be
    # removed", and reporting zero disarmed that confirmation entirely.
    spy = Spy()
    bridge = _bridge(spy)
    bridge.handle("ro:broken:1")
    bridge.handle("ro:broken:0")
    assert spy.broken == [True, False]
    assert spy.counts == [], "brokenness must not be reported as a marker count"
