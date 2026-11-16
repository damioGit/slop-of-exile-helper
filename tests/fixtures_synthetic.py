"""A build assembled through the API, so tests do not depend on external build codes."""

WAND = """Rarity: RARE
Soe Test Wand
Attuned Wand
Item Level: 80
--
+3 to Level of all Spell Skills
89% increased Spell Damage
+120 to maximum Mana
"""


def make_sorc(pob, notables: int = 15) -> int:
    pob.new_build()
    assert pob.set_class("Sorceress", "Stormweaver"), "class not found"
    pob.set_level(90)
    pob.paste_gems("Spark 20/0  1\nControlled Destruction 1/0  1")
    pob.add_item(WAND)
    spent = 0
    for _ in range(notables):
        cand = pob.reachable("Notable", 1)
        if not cand:
            break
        spent += pob.alloc_node(cand[0]["id"]) or 0
    return spent
