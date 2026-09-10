from __future__ import annotations

import pytest

from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure


def _structure(**kwargs):
    defaults = dict(ordinal=1, target=NormalizedPoint(0.3, 0.4), label="Aorta")
    defaults.update(kwargs)
    return Structure(**defaults)


def test_valid_structure_roundtrips_through_dict():
    structure = _structure()
    assert Structure.from_dict(structure.to_dict()) == structure


def test_to_dict_uses_compact_keys():
    assert _structure().to_dict() == {"ord": 1, "x": 0.3, "y": 0.4, "label": "Aorta"}


def test_rejects_non_positive_ordinal():
    with pytest.raises(ValueError):
        _structure(ordinal=0)


@pytest.mark.parametrize("label", ["", "   "])
def test_rejects_blank_label(label):
    with pytest.raises(ValueError):
        _structure(label=label)


def test_from_dict_coerces_the_stored_types():
    # Field values come back from Anki as JSON, where a hand-edited note can
    # carry the ordinal as a string and the label as a number.
    structure = Structure.from_dict({"ord": "2", "x": "0.25", "y": 0, "label": 7})
    assert structure.ordinal == 2 and isinstance(structure.ordinal, int)
    assert structure.target.x == 0.25 and isinstance(structure.target.x, float)
    assert structure.label == "7" and isinstance(structure.label, str)
