"""Crafting rules sensor: parsing poe2db item boxes, spotting changed effects and minimum levels."""
import pytest

from soe.kb import craft_rules

BOX = ('<div class="property">Stack Size: 1 / 20</div>{lvl}<div class="separator"></div>'
       '<div class="explicitMod">{effect}</div><div class="secDescrText">Right click...</div>')


def page(effect, lvl=None):
    extra = f'<div class="property">Minimum Modifier Level : <span>{lvl}</span></div>' if lvl else ""
    return BOX.format(effect=effect, lvl=extra).encode()


@pytest.fixture
def rules(tmp_path, monkeypatch):
    monkeypatch.setattr(craft_rules, "FILE", tmp_path / "_rules.json")
    omens = {"now": ["Omen of Light"]}
    monkeypatch.setattr(craft_rules, "_omens_now", lambda: omens["now"])
    return omens


def test_parse_item():
    got = craft_rules.parse_item(page("Augments a <a>Rare</a> item with a new random modifier", 35).decode())
    assert got == {"effect": "Augments a Rare item with a new random modifier", "min_level": 35}


def test_changes_minimum_levels_and_new_omens(rules):
    texts = {n: page(f"effect of {n}", craft_rules.DEFAULT_MIN.get(n)) for n in craft_rules.TRACKED}
    craft_rules.check(force=True, fetch=lambda url: texts[_name(url)])
    r = craft_rules.report()
    assert r["checked_items"] == len(craft_rules.TRACKED) and not r["changes"] and not r["new_omens"]

    texts["Exalted Orb"] = page("Augments a Rare item with two new random modifiers")
    texts["Greater Exalted Orb"] = page("effect of Greater Exalted Orb", 40)
    rules["now"] = ["Omen of Light", "Omen of Something New"]
    craft_rules.check(force=True, fetch=lambda url: texts[_name(url)])
    r = craft_rules.report()
    assert [c["item"] for c in r["changes"]] == ["Exalted Orb"] and "two new" in r["changes"][0]["new"]
    assert craft_rules.min_levels()["Greater Exalted Orb"] == 40 and any("35 -> 40" in a for a in r["applied"])
    assert r["new_omens"] == ["Omen of Something New"]

    r = craft_rules.accept()
    assert not r["changes"] and not r["new_omens"]


def test_network_error_is_no_change(rules):
    def boom(url):
        raise OSError("offline")
    craft_rules.check(force=True, fetch=boom)
    assert craft_rules.report()["changes"] == []


def _name(url: str) -> str:
    slug = url.rsplit("/", 1)[-1]
    return next(n for n in craft_rules.TRACKED if craft_rules.page_name(n) == slug)
