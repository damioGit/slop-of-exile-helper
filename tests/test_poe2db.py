"""poe2db: parsing a ModsView page and mapping bases to their page."""
from pathlib import Path

from soe.kb import poe2db

SAMPLE = Path(__file__).parent / "data" / "poe2db_sample.html"


def test_parse_page():
    d = poe2db.parse("Rings", SAMPLE.read_text(encoding="utf-8"))
    strength, life = d["normal"]
    assert strength == {"id": "Strength1", "type": "Suffix", "level": 1, "weight": 1000, "fams": ["Strength"],
                        "text": "+(5-8) to Strength"}
    assert life["type"] == "Prefix" and life["weight"] == 250 and life["text"] == "+(100-119) to maximum Life"
    assert d["desecrated"][0]["fams"] == ["Strength", "Intelligence"]
    ess = d["essence"][0]
    assert ess["name"] == "Lesser Essence of the Body" and not ess["perfect"] and ess["id"] == "IncreasedLife2"


def test_page_for_base():
    assert poe2db.page_for_base({"type": "Ring", "tags": ["ring"]}) == "Rings"
    assert poe2db.page_for_base({"type": "Body Armour", "tags": ["armour", "body_armour", "int_armour"]}) == "Body_Armours_int"
    assert poe2db.page_for_base({"type": "Gloves", "tags": ["armour", "str_dex_armour"]}) == "Gloves_str_dex"
    assert poe2db.page_for_base({"type": "Staff", "sub_type": "Warstaff", "tags": ["warstaff"]}) == "Quarterstaves"
    assert poe2db.page_for_base({"type": "Shield", "tags": ["armour", "buckler", "dex_armour"]}) == "Bucklers"
    assert poe2db.bone_kind({"type": "Belt"}) == "jewellery" and poe2db.bone_kind({"type": "Helmet"}) == "armour"


def test_offline_never_fetches(monkeypatch, tmp_path):
    monkeypatch.setattr(poe2db, "DIR", tmp_path)
    monkeypatch.setattr(poe2db, "_mem", {})
    monkeypatch.setattr(poe2db, "_get", lambda url: (_ for _ in ()).throw(AssertionError("network in offline mode")))
    assert poe2db.page_data("Rings") is None  # conftest sets SOE_POE2DB=offline
