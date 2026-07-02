from __future__ import annotations

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.notetype.installer import InstallResult, NoteTypeInstaller
from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.notetype.templates import TemplateAssembler


class FakeModelGateway:
    """In-memory ModelGateway, Liskov-substitutable for the real one."""

    def __init__(self):
        self.store = {}
        self.created = []
        self.updated = []

    def find(self, name):
        return self.store.get(name)

    def create_cloze_notetype(
        self, *, name, fields, sort_index, template_name, front, back, css, collapsed_fields=()
    ):
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
