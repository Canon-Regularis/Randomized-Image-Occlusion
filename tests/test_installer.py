from __future__ import annotations

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.notetype.installer import InstallResult, NoteTypeInstaller
from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.notetype.templates import TemplateAssembler


class FakeModelGateway:
    """In-memory ModelGateway, Liskov-substitutable for the real one.

    It both applies the call and records its arguments. The recorded arguments
    are what tests should assert against: reading state back out of ``store``
    only proves this class stored what it was told, since the real gateway's
    equivalent lines live in ``gateways.py`` (see ``test_gateways.py``).
    """

    def __init__(self):
        self.store = {}
        self.created = []
        self.updated = []
        #: kwargs of each create_cloze_notetype / update_templates call.
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    def find(self, name):
        return self.store.get(name)

    def create_cloze_notetype(
        self, *, name, fields, sort_index, template_name, front, back, css, collapsed_fields=()
    ):
        self.create_calls.append(
            {
                "name": name,
                "fields": fields,
                "sort_index": sort_index,
                "template_name": template_name,
                "front": front,
                "back": back,
                "css": css,
                "collapsed_fields": collapsed_fields,
            }
        )
        collapsed = set(collapsed_fields)
        self.store[name] = {
            "name": name,
            "type": 1,
            "flds": [
                {"name": f, "collapsed": True} if f in collapsed else {"name": f}
                for f in fields
            ],
            "tmpls": [{"name": template_name, "qfmt": front, "afmt": back}],
            "css": css,
            "sortf": sort_index,
        }
        self.created.append(name)

    def update_templates(self, notetype, *, front, back, css):
        self.update_calls.append({"front": front, "back": back, "css": css})
        notetype["tmpls"][0]["qfmt"] = front
        notetype["tmpls"][0]["afmt"] = back
        notetype["css"] = css
        self.updated.append(notetype["name"])

    def ensure_fields(self, notetype, field_names):
        existing = {f["name"] for f in notetype["flds"]}
        changed = False
        for name in field_names:
            if name not in existing:
                notetype["flds"].append({"name": name})
                changed = True
        return changed

    def collapse_fields(self, notetype, field_names):
        targets = set(field_names)
        changed = False
        for field in notetype["flds"]:
            if field["name"] in targets and not field.get("collapsed", False):
                field["collapsed"] = True
                changed = True
        return changed


def _installer(gateway):
    assembler = TemplateAssembler(DEFAULT_SPEC, "/* render */")
    return NoteTypeInstaller(gateway, assembler, DEFAULT_SPEC)


def _rc(**overrides):
    return RenderConfig.from_mapping({**DEFAULT_CONFIG, **overrides})


def test_creates_when_absent():
    gw = FakeModelGateway()
    result = _installer(gw).ensure_installed(_rc())
    assert result is InstallResult.CREATED
    assert gw.created == [DEFAULT_SPEC.name]
    assert DEFAULT_SPEC.name in gw.store


def test_unchanged_when_fingerprint_matches():
    gw = FakeModelGateway()
    installer = _installer(gw)
    installer.ensure_installed(_rc())
    result = installer.ensure_installed(_rc())
    assert result is InstallResult.UNCHANGED
    assert gw.updated == []


def test_updates_when_config_changes():
    gw = FakeModelGateway()
    installer = _installer(gw)
    installer.ensure_installed(_rc())
    result = installer.ensure_installed(_rc(accent_color="#000000"))
    assert result is InstallResult.UPDATED
    assert gw.updated == [DEFAULT_SPEC.name]
    assert "--ro-accent: #000000;" in gw.store[DEFAULT_SPEC.name]["css"]


def test_creates_a_cloze_notetype():
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    assert gw.store[DEFAULT_SPEC.name]["type"] == 1


def test_adds_missing_fields_to_an_existing_notetype():
    gw = FakeModelGateway()
    installer = _installer(gw)
    installer.ensure_installed(_rc())
    # Simulate an older install that predates the TypeAnswer field.
    notetype = gw.store[DEFAULT_SPEC.name]
    notetype["flds"] = [f for f in notetype["flds"] if f["name"] != "TypeAnswer"]

    result = installer.ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert any(f["name"] == "TypeAnswer" for f in notetype["flds"])


def test_machine_fields_are_collapsed_on_create():
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    flds = {f["name"]: f for f in gw.store[DEFAULT_SPEC.name]["flds"]}
    for name in DEFAULT_SPEC.collapsed_fields:
        assert flds[name].get("collapsed") is True
    # The user-facing fields stay expanded.
    assert flds["Header"].get("collapsed", False) is False
    assert flds["Back Extra"].get("collapsed", False) is False


def test_collapse_migrates_an_existing_uncollapsed_notetype():
    gw = FakeModelGateway()
    installer = _installer(gw)
    installer.ensure_installed(_rc())
    # Simulate an older install whose machine fields were never collapsed.
    notetype = gw.store[DEFAULT_SPEC.name]
    for field in notetype["flds"]:
        field.pop("collapsed", None)
    gw.updated.clear()

    result = installer.ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert gw.updated == [DEFAULT_SPEC.name]  # persisted via update_templates
    flds = {f["name"]: f for f in notetype["flds"]}
    assert flds["Structures"]["collapsed"] is True


def test_collapse_is_idempotent_and_leaves_current_notetype_unchanged():
    gw = FakeModelGateway()
    installer = _installer(gw)
    installer.ensure_installed(_rc())
    gw.updated.clear()
    result = installer.ensure_installed(_rc())
    assert result is InstallResult.UNCHANGED
    assert gw.updated == []


# ---- what the installer hands the gateway ----------------------------------
#
# The tests above cover when the installer acts. These cover what it passes,
# which the fake's stored state cannot show: reading `store` back only proves
# the fake kept what it was given.


def _installed():
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    return gateway.create_calls[0]


def test_create_receives_the_spec_field_order():
    assert _installed()["fields"] == DEFAULT_SPEC.fields


def test_create_receives_the_spec_sort_index():
    call = _installed()
    assert call["sort_index"] == DEFAULT_SPEC.sort_index
    # A literal. `fields[sort_index] == sort_field` holds for any spec by
    # construction, since sort_index is defined as fields.index(sort_field), so
    # asserting it says nothing about which field is actually sorted on.
    assert call["fields"][call["sort_index"]] == "Header"


def test_create_receives_the_spec_names():
    call = _installed()
    assert call["name"] == DEFAULT_SPEC.name
    assert call["template_name"] == DEFAULT_SPEC.template_name


def test_create_does_not_swap_front_and_back():
    call = _installed()
    template = TemplateAssembler(DEFAULT_SPEC, "/* render */").assemble(_rc())
    assert call["front"] == template.front
    assert call["back"] == template.back
    assert call["front"] != call["back"], "a swap would be invisible if they matched"


def test_create_collapses_the_spec_internal_fields():
    assert _installed()["collapsed_fields"] == DEFAULT_SPEC.collapsed_fields


def test_update_does_not_swap_front_and_back():
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    gateway.store[DEFAULT_SPEC.name]["css"] = "stale"  # force an update

    _installer(gateway).ensure_installed(_rc())

    template = TemplateAssembler(DEFAULT_SPEC, "/* render */").assemble(_rc())
    assert gateway.update_calls[-1]["front"] == template.front
    assert gateway.update_calls[-1]["back"] == template.back


def _uncollapsed_field_after_the_sort_field() -> str:
    """A field whose removal leaves every other term of the update test alone.

    It must not be collapsed (or collapse_fields would flip to True when it is
    re-added without the flag) and it must sit after the sort field (or removing
    it would shift sortf and set sort_changed). What is left can only be
    fields_changed.
    """
    fields = DEFAULT_SPEC.fields
    after = fields[fields.index(DEFAULT_SPEC.sort_field) + 1:]
    candidates = [f for f in after if f not in DEFAULT_SPEC.collapsed_fields]
    assert candidates, "the spec no longer has a field this test can use"
    return candidates[0]


def test_missing_field_alone_forces_an_update():
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    notetype = gateway.store[DEFAULT_SPEC.name]
    dropped = _uncollapsed_field_after_the_sort_field()
    before = notetype["sortf"]
    notetype["flds"] = [f for f in notetype["flds"] if f["name"] != dropped]

    result = _installer(gateway).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert [f["name"] for f in notetype["flds"]].count(dropped) == 1
    assert notetype["sortf"] == before, (
        "this field was chosen so sortf cannot move; if it did, sort_changed "
        "would mask a broken fields_changed term"
    )


def test_a_removed_sort_field_keeps_the_sort_column():
    # ensure_fields appends, so the sort field comes back at the END of the list.
    # An untouched sortf would still point at the index it used to occupy, and
    # the browser would sort on whatever moved into that slot.
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    notetype = gateway.store[DEFAULT_SPEC.name]
    notetype["flds"] = [
        f for f in notetype["flds"] if f["name"] != DEFAULT_SPEC.sort_field
    ]

    result = _installer(gateway).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert [f["name"] for f in notetype["flds"]].count(DEFAULT_SPEC.sort_field) == 1
    assert notetype["flds"][notetype["sortf"]]["name"] == DEFAULT_SPEC.sort_field
    assert notetype["sortf"] != DEFAULT_SPEC.sort_index, (
        "the field was re-appended, so its index is no longer the declared one; "
        "if these matched, the test would not distinguish a name lookup from "
        "blindly restoring spec.sort_index"
    )


def test_a_stale_sort_index_is_repaired():
    # An install whose field list was migrated by an older version can be left
    # with sortf pointing at the wrong field. Nothing else in the note type is
    # wrong, so only re-asserting sortf can fix it.
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    notetype = gateway.store[DEFAULT_SPEC.name]
    notetype["sortf"] = 0
    assert notetype["flds"][0]["name"] != DEFAULT_SPEC.sort_field, "pick a wrong index"

    result = _installer(gateway).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert notetype["flds"][notetype["sortf"]]["name"] == DEFAULT_SPEC.sort_field


def test_a_correct_sort_index_is_not_an_update():
    # Re-asserting sortf must not make every startup report a change, or the
    # add-on would rewrite the note type on every profile load.
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())

    assert _installer(gateway).ensure_installed(_rc()) is InstallResult.UNCHANGED
