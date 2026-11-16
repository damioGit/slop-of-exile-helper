import pytest

from soe.engine.pob import PoB, decode_build_code, encode_build_code
from tests.fixtures_synthetic import make_sorc


@pytest.fixture(scope="module")
def pob():
    return PoB()


def test_boots_and_new_build(pob):
    pob.new_build()
    s = pob.summary()
    assert s["level"] >= 1
    assert s["Life"] > 0


def test_build_code_codec():
    xml = "<PathOfBuilding2><Build level=\"90\"/></PathOfBuilding2>"
    assert decode_build_code(encode_build_code(xml)) == xml


def test_assemble_synthetic_build(pob):
    spent = make_sorc(pob)
    s = pob.summary()
    assert s["class"] == "Sorceress"
    assert s["ascendancy"] == "Stormweaver"
    assert s["main_skill"] == "Spark"
    assert s["passives_allocated"] == spent > 0
    assert s["TotalDPS"] > 0


def test_gear_changes_numbers(pob):
    make_sorc(pob, notables=0)
    with_wand = pob.summary()["TotalDPS"]
    pob.new_build()
    pob.set_class("Sorceress", "Stormweaver")
    pob.set_level(90)
    pob.paste_gems("Spark 20/0  1\nControlled Destruction 1/0  1")
    without_wand = pob.summary()["TotalDPS"]
    assert with_wand > without_wand


def test_export_roundtrip_is_exact(pob):
    make_sorc(pob)
    before = pob.summary()
    other = PoB()
    other.load_code(pob.export_code())
    assert other.summary() == before


def test_alloc_dealloc(pob):
    make_sorc(pob, notables=0)
    base = pob.summary()["passives_allocated"]
    node = pob.reachable("Notable", 1)[0]
    cost = pob.alloc_node(node["id"])
    assert pob.summary()["passives_allocated"] == base + cost
    assert pob.dealloc_node(node["id"])
    assert pob.summary()["passives_allocated"] < base + cost


def test_minion_main_skill_has_main_dps(pob):
    pob.new_build()
    pob.set_class("Witch", "Infernalist")
    pob.set_level(80)
    pob.paste_gems("Skeletal Warrior 20/0  1")
    s = pob.summary()
    assert s["CombinedDPS"] == 0 and s["MinionDPS"] > 0
    assert s["MainDPS"] == s["MinionDPS"]
    w = pob.whatif()
    assert w["MainDPS"] == pytest.approx(s["MainDPS"])


def test_infinite_values_are_finite_json():
    import json

    from soe.engine.pob import IMMUNE, _lua_to_py

    assert _lua_to_py(float("inf")) == IMMUNE and _lua_to_py(float("nan")) == 0.0
    json.dumps({"x": _lua_to_py(float("-inf"))}, allow_nan=False)
