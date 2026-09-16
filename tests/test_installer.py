from __future__ import annotations

from dataclasses import replace

import pytest

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.notetype.installer import InstallResult, NoteTypeInstaller
from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.notetype.templates import (
    TemplateAssembler,
    extract_fingerprint,
)


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


def _installer(gateway, spec=DEFAULT_SPEC):
    assembler = TemplateAssembler(spec, "/* render */")
    return NoteTypeInstaller(gateway, assembler, spec)


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


def _spec_with_a_droppable_field():
    """A spec carrying one field the installer may legitimately append back.

    The field whose removal leaves fields_changed as the ONLY term must not be
    collapsed (or collapse_fields flips too when it is re-added without the
    flag) and must sit after the sort field (or sortf shifts). Every field
    DEFAULT_SPEC declares now fails one of those or is required -- and a missing
    required field is a rename, which the installer refuses outright. So the
    test gets a field of its own rather than a weaker assertion.
    """
    return replace(DEFAULT_SPEC, fields=(*DEFAULT_SPEC.fields, "Scratch"))


def test_missing_field_alone_forces_an_update():
    spec = _spec_with_a_droppable_field()
    gateway = FakeModelGateway()
    _installer(gateway, spec).ensure_installed(_rc())
    notetype = gateway.store[spec.name]
    before = notetype["sortf"]
    notetype["flds"] = [f for f in notetype["flds"] if f["name"] != "Scratch"]

    result = _installer(gateway, spec).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert [f["name"] for f in notetype["flds"]].count("Scratch") == 1
    assert notetype["sortf"] == before, (
        "this field was chosen so sortf cannot move; if it did, sort_changed "
        "would mask a broken fields_changed term"
    )


def test_a_repositioned_sort_field_keeps_the_sort_column():
    # Anki lets a user reposition fields, which moves the sort field without
    # moving sortf. The browser then sorts on whatever slid into that slot, with
    # nothing on screen to say so.
    gateway = FakeModelGateway()
    _installer(gateway).ensure_installed(_rc())
    notetype = gateway.store[DEFAULT_SPEC.name]
    moved = [f for f in notetype["flds"] if f["name"] != DEFAULT_SPEC.sort_field]
    moved.append(next(
        f for f in notetype["flds"] if f["name"] == DEFAULT_SPEC.sort_field
    ))
    notetype["flds"] = moved

    result = _installer(gateway).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert [f["name"] for f in notetype["flds"]].count(DEFAULT_SPEC.sort_field) == 1
    assert notetype["flds"][notetype["sortf"]]["name"] == DEFAULT_SPEC.sort_field
    assert notetype["sortf"] != DEFAULT_SPEC.sort_index, (
        "the field moved, so its index is no longer the declared one; "
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


def _edit_the_back(notetype):
    """Stand in for a user editing the Back template in Card Types."""
    notetype["tmpls"][0]["afmt"] += "<div class=mine>hand edited</div>"


def _edit_all_three(notetype):
    """A user who edited the front, the back and the styling."""
    notetype["tmpls"][0]["qfmt"] += "<div class=mine>front</div>"
    notetype["tmpls"][0]["afmt"] += "<div class=mine>back</div>"
    notetype["css"] += ".mine { color: red; }"


def test_a_hand_edited_template_survives_an_upgrade():
    # The whole point: an upgrade that WOULD rewrite the templates (the config
    # changed, so the fingerprint no longer matches) must not take the user's
    # edit with it. Before this guard, ensure_installed clobbered it silently.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    _edit_the_back(notetype)
    gw.update_calls.clear()

    result = _installer(gw).ensure_installed(_rc(accent_color="#000000"))

    assert result is InstallResult.CUSTOMISED
    assert gw.update_calls == [], "nothing may be written back"
    assert "hand edited" in notetype["tmpls"][0]["afmt"]
    assert "--ro-accent: #000000;" not in notetype["css"]


def test_hand_edited_css_survives_an_upgrade():
    # The CSS carries the fingerprint, so it is the one string whose edit could
    # plausibly be mistaken for our own write. It is hashed without the marker
    # line, so an edit anywhere else in it still registers.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    notetype["css"] += ".mine { color: red; }"

    result = _installer(gw).ensure_installed(_rc(accent_color="#000000"))

    assert result is InstallResult.CUSTOMISED
    assert ".mine { color: red; }" in notetype["css"]


def test_an_untouched_notetype_is_still_upgraded():
    # The guard must not freeze every install. Nobody edited this one, so the
    # new templates land exactly as they did before the guard existed.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())

    result = _installer(gw).ensure_installed(_rc(accent_color="#000000"))

    assert result is InstallResult.UPDATED
    assert "--ro-accent: #000000;" in gw.store[DEFAULT_SPEC.name]["css"]


def test_a_notetype_with_no_fingerprint_is_still_upgraded():
    # An install predating the marker, or one whose CSS was replaced wholesale,
    # has nothing to compare against. Treating that as customised would strand
    # it on an old renderer for good, so it is treated as ours.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    notetype["css"] = ".ro-wrap { color: red; }"
    assert extract_fingerprint(notetype["css"]) is None, "no marker to find"

    result = _installer(gw).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert extract_fingerprint(notetype["css"]) is not None


def test_a_field_migration_is_persisted_even_on_a_customised_notetype():
    # Leaving the templates alone must not also abandon the field migration --
    # the new field is added to the dict in memory, and update_templates is the
    # only thing that writes the dict back. It is called with the STORED
    # strings, which is what makes persisting the fields safe.
    #
    # All three strings are edited, so that passing any one of them back from
    # the freshly assembled template instead of from storage shows up here --
    # an edit to only one would leave the other two identical either way.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    _edit_all_three(notetype)
    notetype["flds"] = [f for f in notetype["flds"] if f["name"] != "TypeAnswer"]
    stored = {
        "front": notetype["tmpls"][0]["qfmt"],
        "back": notetype["tmpls"][0]["afmt"],
        "css": notetype["css"],
    }
    gw.update_calls.clear()

    result = _installer(gw).ensure_installed(_rc())

    assert result is InstallResult.CUSTOMISED
    assert any(f["name"] == "TypeAnswer" for f in notetype["flds"])
    assert gw.update_calls == [stored], "written back unchanged, not re-assembled"


def test_a_renamed_field_is_refused_rather_than_repaired():
    # Renaming Structures in Anki keeps every note's payload under the new name.
    # "Repairing" it by appending an empty Structures is what the templates then
    # render: every card in the collection loses its occlusions at once.
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    for field in notetype["flds"]:
        if field["name"] == DEFAULT_SPEC.structures_field:
            field["name"] = "Payload"
    before = [f["name"] for f in notetype["flds"]]
    gw.update_calls.clear()

    result = _installer(gw).ensure_installed(_rc())

    assert result is InstallResult.FIELDS_MISSING
    assert [f["name"] for f in notetype["flds"]] == before, "no empty field appended"
    assert gw.update_calls == [], "and nothing written back"


def test_every_required_field_is_guarded_not_just_one():
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    pristine = [dict(f) for f in gw.store[DEFAULT_SPEC.name]["flds"]]

    for name in DEFAULT_SPEC.required_fields:
        notetype = gw.store[DEFAULT_SPEC.name]
        notetype["flds"] = [dict(f) for f in pristine if f["name"] != name]

        assert _installer(gw).ensure_installed(_rc()) is InstallResult.FIELDS_MISSING, (
            f"removing {name} was repaired instead of refused"
        )


def test_a_field_a_later_version_added_is_still_appended():
    # The other half of the same rule: TypeAnswer is not required, because a
    # note type created before 1.1 genuinely lacks it. Refusing those would
    # strand every older install rather than migrate it.
    assert DEFAULT_SPEC.type_flag_field not in DEFAULT_SPEC.required_fields
    gw = FakeModelGateway()
    _installer(gw).ensure_installed(_rc())
    notetype = gw.store[DEFAULT_SPEC.name]
    notetype["flds"] = [
        f for f in notetype["flds"] if f["name"] != DEFAULT_SPEC.type_flag_field
    ]

    result = _installer(gw).ensure_installed(_rc())

    assert result is InstallResult.UPDATED
    assert any(f["name"] == DEFAULT_SPEC.type_flag_field for f in notetype["flds"])


def test_the_required_fields_are_all_declared_fields():
    missing = set(DEFAULT_SPEC.required_fields) - set(DEFAULT_SPEC.fields)
    assert not missing, f"required but never declared: {sorted(missing)}"


def test_a_spec_demanding_a_field_it_never_creates_is_refused():
    # Such a spec looks for a field that is never there, so it would report
    # every untouched install as renamed and refuse to update any of them.
    with pytest.raises(ValueError, match="required_fields"):
        replace(DEFAULT_SPEC, required_fields=(*DEFAULT_SPEC.required_fields, "Ghost"))
